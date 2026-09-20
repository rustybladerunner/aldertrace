"""A new orchestration version around unchanged, frozen study instruments.

The caller owns one existing campaign lock for the whole operation. Only fresh
planned keys can dispatch. Recovery classifies a lost request; it never retries it.
"""
import hashlib
import math
import os
import time
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path

import bootstrap
from adapters import canonical, parse_response, strict_json
from budget import CampaignBudget
from core import baseline, enforce
from development import BOUNDS
from development_report import _journal
from durability import RecoverableJournal, RecoveryRequired
from journal import BudgetExceeded, execute_one, money
from locks import sha, write_once
from routing_contract import build
from transport import usage
import definition_next
import experiment_v2


def _read(path):
    return strict_json(Path(path).read_text(encoding='utf8'))


def _same_path(left, right):
    return os.path.normcase(str(Path(left).resolve())) == os.path.normcase(str(Path(right).resolve()))


def make_plan(experiment, phase):
    experiment = Path(experiment).resolve()
    frozen = definition_next.verify(experiment)
    cases, digest, models = definition_next.phase_inputs(experiment, phase)
    settings = frozen['settings']
    ordered = sorted(cases, key=lambda c: hashlib.sha256(('20260919:' + c['id']).encode()).hexdigest())
    repeats = set()
    if phase == 'test':
        for family in {c['family'] for c in ordered}:
            repeats.update(c['id'] for c in [c for c in ordered if c['family'] == family][:5])
    arms = [arm for arm in ('local', 'jev', 'chat') if arm in models]
    rows = []
    for trial in range(1, 4 if phase == 'test' else 2):
        for index, case in enumerate(ordered):
            if trial > 1 and case['id'] not in repeats:
                continue
            rotation = (index + trial - 1) % len(arms)
            for arm in arms[rotation:] + arms[:rotation]:
                rows.append({'key': f"{arm}:{case['id']}:{trial}", 'arm': arm,
                             'case_id': case['id'], 'trial': trial, 'family': case['family'],
                             'kind': case['state']['unit']['kind'],
                             'deterministic_bypass': settings['policy'] == 'deterministic_first'
                                 and case['state']['unit']['kind'] == 'executable'})
    return {'schema': 3, 'phase': phase, 'freeze_sha256': sha(experiment / 'freeze.json'),
            'case_ids': [c['id'] for c in ordered], 'models': models,
            'journals': {arm: arm + '.jsonl' for arm in models},
            'policy': settings['policy'], 'prompt_version': settings['prompt_version'],
            'dataset_sha256': digest, 'campaign_path': settings['campaign_path'],
            'cloud_cap_usd': settings['cloud_cap_usd'], 'repeat_case_ids': sorted(repeats), 'rows': rows}


def _definition(experiment, plan, frozen):
    phase, settings = plan['phase'], frozen['settings']
    cases, _, models = definition_next.phase_inputs(experiment, phase)
    threshold = 0.0 if phase == 'development' else experiment_v2.verify_phase(
        experiment, phase, cases, models, plan['dataset_sha256'], plan['policy'], plan['prompt_version'])
    return {'schema': 2, 'evidence_kind': ('simulated-instrument-' if settings['purpose'] == 'instrument-test'
                                        else 'provisional-') + phase,
            'split': phase, 'dataset_sha256': plan['dataset_sha256'], 'models': models,
            'policy': plan['policy'], 'prompt_version': plan['prompt_version'], 'threshold': threshold,
            'threshold_status': 'exploratory; not calibrated' if phase == 'development' else 'phase-locked',
            'repeat_case_ids': plan['repeat_case_ids'], 'case_ids': plan['case_ids'],
            'trials': 3 if phase == 'test' else 1, 'source_commit': settings['source_commit'],
            'source_files': frozen['implementation_assets'], 'next_source_files': settings['next_source_assets'],
            'settings': {'chat_temperature': 0, 'chat_seed': 20260919, 'chat_max_tokens': 512,
                         'local_temperature': 0, 'local_seed': 1, 'local_num_predict': 1},
            'label_status': settings['label_status'], 'synthetic_only': True,
            'started_utc': datetime.now(timezone.utc).isoformat(), 'resource_before': None}


def _observations(path, plan):
    raw = path.read_bytes()
    if raw and not raw.endswith(b'\n'):
        raise ValueError('incomplete observations tail; evidence unchanged')
    expected = {r['key']: r for r in plan['rows']}
    rows, seen = [], set()
    for line in raw.splitlines():
        row = strict_json(line)
        key = row.get('key') if isinstance(row, dict) else None
        if key not in expected or key in seen:
            raise ValueError('unexpected or repeated observation')
        for field in ('arm', 'case_id', 'family', 'kind', 'trial'):
            if row.get(field) != expected[key][field]:
                raise ValueError('observation identity differs from plan')
        elapsed = row.get('end_to_end_ms')
        if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0:
            raise ValueError('observation timing must be measured, not a missing-time placeholder')
        if type(row.get('attempts')) is not int or not 0 <= row['attempts'] <= 2:
            raise ValueError('invalid observation attempt count')
        seen.add(key)
        rows.append(row)
    return rows


def _append_observation(path, row):
    with path.open('ab') as file:
        payload = (canonical(row) + '\n').encode('utf8')
        if file.write(payload) != len(payload):
            raise OSError('short observation write')
        file.flush()
        os.fsync(file.fileno())


def _owned_results(journals):
    # On Windows the byte-range lock forbids a second read handle. Read from the
    # owned handle; reports only open paths after the journal locks are closed.
    results = {}
    for journal in journals.values():
        journal.file.seek(0)
        for line in journal.file.read().splitlines():
            event = strict_json(line)
            if event.get('event') == 'result':
                results[event['key']] = event
    return results


def _safety(arm, events, expected_model, *, require_final=True):
    """Check each receipt, including failed-first-attempt retry overhead."""
    measured = []
    for event in events:
        if event.get('status') == 200:
            try:
                item = event['usage'] if arm == 'local' else usage(event['body'], arm)
                if money(item['accounting_usd']) > money(BOUNDS[arm]):
                    raise ValueError('receipt exceeds reservation')
                measured.append(item)
            except (KeyError, TypeError, ValueError):
                return measured, 'usage unavailable or outside reservation'
            parsed = parse_response(event['body'], arm, expected_model)
            if parsed.get('reason') == 'model_mismatch':
                return measured, 'resolved model differs from frozen identity'
        elif event.get('status') in (401, 403, 404):
            return measured, 'provider access or model unavailable'
    if require_final and (not events or events[-1].get('status') != 200):
        return measured, 'transport failure; no further automatic dispatch'
    return measured, None


def _verify_complete(directory, plan):
    marker = _read(directory / 'COMPLETE.json')
    if marker.get('schema') != 3 or marker.get('plan_sha256') != sha(directory / 'phase-plan.json'):
        raise ValueError('completion marker differs')
    required = {'phase-plan.json', 'definition.json', 'observations.jsonl', 'summary.json', 'READY.json'}
    for filename in plan['journals'].values():
        required.update((filename, filename + '.binding.json', filename + '.recovery.jsonl'))
    files = marker.get('files', {})
    if not isinstance(files, dict) or not required <= set(files):
        raise ValueError('completion inventory is incomplete')
    for name, digest in files.items():
        if Path(name).name != name or sha(directory / name) != digest:
            raise ValueError('completed evidence differs: ' + name)
    summary = _read(directory / 'summary.json')
    if summary.get('complete') is not True:
        raise ValueError('completed summary differs')
    return summary


def _save_summary(directory, value):
    payload = (canonical(value) + '\n').encode('utf8')
    digest = hashlib.sha256(payload).hexdigest()
    snapshot = directory / ('summary-' + digest + '.json')
    if not snapshot.exists():
        # Hash and persist the same bytes on Windows too: text mode translates
        # LF to CRLF and otherwise makes identical recovery retries disagree.
        with snapshot.open('xb') as file:
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
    elif snapshot.read_bytes() != payload:
        raise ValueError('summary snapshot differs')
    temporary = directory / 'summary.next'
    with temporary.open('wb') as file:
        file.write(payload)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temporary, directory / 'summary.json')


def run_phase(experiment, phase, transports, campaign, *, approved=False, resume=False,
              secrets=(), reconcile_reference=None, stop_after=None):
    if approved is not True:
        raise PermissionError('explicit session execution approval required')
    if type(resume) is not bool:
        raise ValueError('explicit resume boolean required')
    if stop_after is not None and (type(stop_after) is not int or stop_after < 1):
        raise ValueError('stop_after must be a positive observation count')
    experiment = Path(experiment).resolve()
    plan = make_plan(experiment, phase)
    frozen = definition_next.verify(experiment)
    if (set(transports) != set(plan['models']) or any(not callable(t) for t in transports.values())):
        raise ValueError('callable transport coverage must match frozen available models')
    if (not isinstance(campaign, CampaignBudget) or not campaign.locked or campaign.file.closed
            or not _same_path(campaign.file.name, plan['campaign_path'])
            or campaign.cap != money(plan['cloud_cap_usd'])):
        raise ValueError('active original same-cap campaign lock required')
    if campaign.halted:
        raise BudgetExceeded('campaign halted; reconciliation cannot remove a resource/billing stop')
    directory = experiment / phase
    expected_definition = _definition(experiment, plan, frozen)
    if resume:
        if _read(directory / 'phase-plan.json') != plan:
            raise ValueError('immutable phase plan changed')
        definition = _read(directory / 'definition.json')
        for key, value in expected_definition.items():
            if key != 'started_utc' and definition.get(key) != value:
                raise ValueError('run definition differs: ' + key)
        ready = _read(directory / 'READY.json')
        if ready != {'schema': 3, 'plan_sha256': sha(directory / 'phase-plan.json'),
                     'definition_sha256': sha(directory / 'definition.json')}:
            raise ValueError('phase initialization incomplete or altered')
        if (directory / 'COMPLETE.json').exists():
            return _verify_complete(directory, plan)
    else:
        if reconcile_reference is not None:
            raise ValueError('reconciliation requires an existing phase')
        directory.mkdir(parents=True, exist_ok=False)
        write_once(directory / 'phase-plan.json', plan)
        definition = expected_definition
        write_once(directory / 'definition.json', definition)
        with (directory / 'observations.jsonl').open('xb') as file:
            file.flush()
            os.fsync(file.fileno())
    rows = _observations(directory / 'observations.jsonl', plan)
    cases = {c['id']: c for c in definition_next.phase_inputs(experiment, phase)[0]}
    by_key = {r['key']: r for r in plan['rows']}
    prior = {}
    # The lifetime campaign lock serializes all authorized operations. Validate
    # request bodies before opening byte-locked journals (Windows read semantics).
    if resume:
        for arm, filename in plan['journals'].items():
            path = directory / filename
            if not path.is_file():
                raise ValueError('started journal is missing; no replacement is permitted')
            expected = {r['key']: cases[r['case_id']] for r in plan['rows']
                        if r['arm'] == arm and not r['deterministic_bypass']}
            records, _ = _journal(path, arm, plan['models'][arm], expected, plan['prompt_version'])
            prior.update(records)
        for row in rows:
            bypass = by_key[row['key']]['deterministic_bypass']
            attempts = prior.get(row['key'], {}).get('attempts', {})
            if (row['attempts'] != len(attempts) or row['status'] != ('deterministic' if bypass else 'observed')
                    or (not bypass and not attempts.get(max(attempts, default=0), {}).get('result'))):
                raise ValueError('observation is not supported by its journal')
            durations = [attempt.get('result', {}).get('elapsed_ms') for attempt in attempts.values()]
            if (all(type(t) in (int, float) and math.isfinite(t) and t >= 0 for t in durations)
                    and row['end_to_end_ms'] + 2 < sum(durations) + prior.get(row['key'], {}).get('backoff_ms', 0)):
                raise ValueError('observation timing is shorter than journal attempts and backoff')
        for key, record in prior.items():
            arm = by_key[key]['arm']
            events = [a['result'] for a in record['attempts'].values() if 'result' in a]
            if events and events[-1].get('error_type') == 'InterruptedProcess':
                continue
            # Local usage is independently replayed from worker captures by report;
            # a paused live local run is disabled at the CLI until its adapter is versioned.
            if events and arm != 'local':
                latest = record['attempts'][max(record['attempts'])]
                _, failure = _safety(arm, events, plan['models'][arm], require_final='result' in latest)
                if failure:
                    campaign.halt()
                    raise RecoveryRequired('prior response needs review: ' + failure)
    stopped, interrupted, newly_recorded = None, None, 0
    results = {}
    with ExitStack() as stack:
        journals = {}
        for arm, filename in plan['journals'].items():
            journal = RecoverableJournal(directory / filename, plan['cloud_cap_usd'], campaign=campaign,
                scope=str(directory) + ':' + arm, identity={'phase_plan_sha256': sha(directory / 'phase-plan.json')},
                create=not resume, secrets=secrets)
            stack.callback(journal.close)
            journals[arm] = journal
        if not resume:
            write_once(directory / 'READY.json', {'schema': 3,
                'plan_sha256': sha(directory / 'phase-plan.json'), 'definition_sha256': sha(directory / 'definition.json')})
        if any(j.orphans for j in journals.values()):
            raise RecoveryRequired('orphan campaign reservation; no dispatch or automatic repair')
        if any(j.unresolved for j in journals.values()):
            if not reconcile_reference:
                raise RecoveryRequired('explicit reference required to classify interrupted requests')
            for journal in journals.values():
                journal.reconcile(reconcile_reference)
            if any(j.unresolved for j in journals.values()):
                raise RecoveryRequired('reservation has no durable request; manual evidence review required')
        results = _owned_results(journals)
        completed = {r['key'] for r in rows} | set(results)
        try:
            for planned in plan['rows']:
                key, arm = planned['key'], planned['arm']
                if key in completed:
                    continue
                case = cases[planned['case_id']]
                started = time.perf_counter()
                row = {k: planned[k] for k in ('key', 'arm', 'case_id', 'family', 'kind', 'trial')}
                row['usage'] = []
                if planned['deterministic_bypass']:
                    row.update(status='deterministic', raw_action=None, action=baseline(case, 'deterministic'),
                               valid=None, attempts=0)
                else:
                    captures = []
                    def observed(body):
                        response = transports[arm](body)
                        captures.append(response)
                        return response
                    parsed = execute_one(journals[arm], key, arm, build(case, arm, plan['prompt_version']),
                                         plan['models'][arm], BOUNDS[arm], observed)
                    answer = parsed.get('answer') if parsed else None
                    threshold = definition['threshold'] if phase == 'development' else definition['threshold'][arm]
                    row.update(status='observed', valid=bool(parsed and parsed['valid']),
                               reason=parsed.get('reason') if parsed else 'transport_failure',
                               raw_action=answer['choice'] if answer else 'review', action=enforce(case, answer, threshold),
                               attempts=journals[arm].attempts[key])
                    if any(not isinstance(capture, dict) for capture in captures):
                        stopped = 'malformed transport envelope'
                    else:
                        row['usage'], stopped = _safety(arm, captures, plan['models'][arm])
                    if parsed is None:
                        stopped = stopped or 'transport failure or invalid envelope'
                    if stopped:
                        campaign.halt()
                row['end_to_end_ms'] = round((time.perf_counter() - started) * 1000, 3)
                _append_observation(directory / 'observations.jsonl', row)
                rows.append(row)
                newly_recorded += 1
                completed.add(key)
                if stopped:
                    break
                if stop_after is not None and newly_recorded >= stop_after and len(completed) < len(plan['rows']):
                    stopped = 'clean pause after requested observation count'
                    break
        except BaseException as exc:
            stopped = 'interrupted:' + type(exc).__name__
            interrupted = exc
        finally:
            results = _owned_results(journals)
            completed = {r['key'] for r in rows} | set(results)
            summary = {'schema': 2, 'evidence_kind': definition['evidence_kind'], 'split': phase,
                       'complete': stopped is None and len(completed) == len(plan['rows']), 'stopped': stopped,
                       'unique_cases_planned': len(plan['case_ids']), 'planned_observations': len(plan['rows']),
                       'recorded_observations': len(rows), 'completed_observations': len(completed),
                       'measured_timing_observations': len(rows),
                       'campaign_reserved_usd': str(campaign.reserved), 'rows': rows}
            _save_summary(directory, summary)
    if summary['complete']:
        # No report is written until all journals are closed and strict replay passes.
        replayed = definition_next.report(experiment, phase)
        if not replayed['complete_from_evidence']:
            raise ValueError('summary completion is not supported by independent replay')
        files = {p.name: sha(p) for p in directory.iterdir() if p.is_file() and p.name != 'COMPLETE.json'}
        write_once(directory / 'COMPLETE.json', {'schema': 3, 'plan_sha256': sha(directory / 'phase-plan.json'), 'files': files})
    if interrupted:
        raise interrupted
    return summary
