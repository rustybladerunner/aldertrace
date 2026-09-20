"""Version-three orchestration locks over unchanged version-two instruments.

No function here creates a transport, loads a model, installs a tokenizer, or
authorizes inference. The coordinator owns the exclusive operation/run lock.
"""
import hashlib
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path

from bootstrap import SOURCE_ROOT
from adapters import canonical, strict_json, parse_response
from core import calibrate
from locks import sha, write_once
import experiment_v2
import development_report
from journal import replay


PHASES = ('development', 'calibration', 'test')
ARMS = ('local', 'jev', 'chat')


def source_inventory():
    """Bind every Python implementation and test in this new source directory."""
    return {p.name: sha(p) for p in sorted(Path(__file__).parent.glob('*.py'))}


def _read(path):
    return strict_json(Path(path).read_text(encoding='utf8'))


def _write_checked(path, value):
    """An existing identical artifact is success; differing bytes are never replaced.

    The caller holds the operation lock. A partial/corrupt artifact fails closed;
    only complete, independently recomputed values can be accepted on recovery.
    """
    path = Path(path)
    if path.exists():
        if path.read_text(encoding='utf8') != canonical(value) + '\n':
            raise ValueError('existing artifact differs: ' + path.name)
        return
    try:
        write_once(path, value)
    except FileExistsError:
        if path.read_text(encoding='utf8') != canonical(value) + '\n':
            raise ValueError('concurrent artifact differs: ' + path.name)


def _phase_cases(dataset, phase, expected_count=None):
    path = Path(dataset) / (phase + '.json')
    cases = _read(path)
    if not isinstance(cases, list) or not cases:
        raise ValueError('phase requires nonempty case list: ' + phase)
    ids = []
    for case in cases:
        if not isinstance(case, dict) or case.get('split') != phase:
            raise ValueError('case belongs to a different phase')
        cid = case.get('id')
        if not isinstance(cid, str) or not cid or cid in ids:
            raise ValueError('case identifiers must be unique nonempty strings')
        ids.append(cid)
    if expected_count is not None and len(cases) != expected_count:
        raise ValueError('case count differs from version-three definition')
    return cases, sha(path)


def _settings(dataset, settings):
    # Canonical round-trip prevents retaining mutable caller-owned structures.
    value = strict_json(canonical(settings))
    if value.get('purpose') not in ('instrument-test', 'research'):
        raise ValueError('purpose must be instrument-test or research')
    if value.get('next_version', 3) != 3:
        raise ValueError('only a new version-three definition is supported')
    campaign = Path(value.get('campaign_path', ''))
    if not campaign.is_absolute() or not campaign.is_file():
        raise ValueError('campaign_path must name an existing absolute ledger')
    try:
        cap = Decimal(str(value['cloud_cap_usd']))
    except (KeyError, InvalidOperation, ValueError):
        raise ValueError('explicit cloud cap required') from None
    if not cap.is_finite() or not 0 <= cap <= 2:
        raise ValueError('cloud cap must remain within the approved two dollars')
    raw = campaign.read_bytes()
    if not raw.endswith(b'\n'):
        raise ValueError('campaign ledger has an incomplete tail')
    header = strict_json(raw.splitlines()[0]) if raw else {}
    if header.get('event') != 'campaign' or header.get('schema') != 1:
        raise ValueError('unrecognized campaign ledger')
    if Decimal(str(header.get('cap_usd'))) != cap:
        raise ValueError('cloud cap differs from existing campaign')
    value['campaign_path'] = str(campaign.resolve())
    value['cloud_cap_usd'] = str(cap)
    models = value.get('models', {})
    if not isinstance(models, dict) or set(models) != set(ARMS):
        raise ValueError('all three declared model identities required')
    if any(not isinstance(m, str) or not m.strip() for m in models.values()):
        raise ValueError('model identities must be nonempty strings')
    available = value.get('available_arms')
    if (not isinstance(available, list) or not available or
            len(available) != len(set(available)) or not set(available) <= set(ARMS)):
        raise ValueError('explicit unique available arm list required')
    reasons = value.get('unavailable_arms', {})
    if not isinstance(reasons, dict) or set(reasons) - (set(ARMS) - set(available)):
        raise ValueError('unavailable arm reasons do not match declared arms')
    for arm in set(ARMS) - set(available):
        reason = reasons.get(arm, value.get('local_status') if arm == 'local' else None)
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError('unavailable arm requires an explicit reason: ' + arm)
    dataset = Path(dataset).resolve()
    if value['purpose'] == 'research':
        for old in (SOURCE_ROOT / 'study', SOURCE_ROOT / 'study-v2'):
            if dataset.is_relative_to(old.resolve()):
                raise ValueError('research requires a fresh dataset, not a completed study')
    counts = {}
    all_ids = set()
    for phase in PHASES:
        cases, _ = _phase_cases(dataset, phase)
        ids = {c['id'] for c in cases}
        if ids & all_ids:
            raise ValueError('case identifier crosses a phase boundary')
        all_ids.update(ids)
        counts[phase] = len(cases)
    if value['purpose'] == 'research' and any(n != 80 for n in counts.values()):
        raise ValueError('research requires the prospective 80/80/80 case counts')
    sources = source_inventory()
    for name, derived in (('next_source_assets', sources), ('next_phase_counts', counts)):
        if name in value and value[name] != derived:
            raise ValueError('supplied ' + name + ' differs from current inputs')
        value[name] = derived
    value['next_version'] = 3
    return value


def freeze(directory, dataset, settings):
    """Freeze once, or finish an interrupted sidecar for the same exact inputs."""
    directory, dataset = Path(directory).resolve(), Path(dataset).resolve()
    if directory.is_relative_to(SOURCE_ROOT.resolve()):
        raise ValueError('run evidence must be outside source checkout')
    proposed = _settings(dataset, settings)
    frozen_path = directory / 'freeze.json'
    if frozen_path.exists():
        frozen = experiment_v2.verify(directory)
        if frozen['settings'].get('next_version') != 3:
            raise ValueError('existing v2 study cannot become version three')
        if (frozen['settings'] != proposed or
                experiment_v2.dataset_directory(frozen).resolve() != dataset):
            raise ValueError('existing definition differs from requested inputs')
    else:
        experiment_v2.freeze(directory, dataset, proposed)
        frozen = experiment_v2.verify(directory)
    version = {'schema': 3, 'next_version': 3, 'freeze_sha256': sha(frozen_path),
               'source_assets': proposed['next_source_assets'],
               'phase_counts': proposed['next_phase_counts']}
    _write_checked(directory / 'version.json', version)
    return verify(directory)


def verify(directory):
    directory = Path(directory).resolve()
    frozen = experiment_v2.verify(directory)
    settings = frozen['settings']
    if settings.get('next_version') != 3:
        raise ValueError('version-three definition required; legacy study is immutable')
    version = _read(directory / 'version.json')
    expected = {'schema': 3, 'next_version': 3,
                'freeze_sha256': sha(directory / 'freeze.json'),
                'source_assets': source_inventory(),
                'phase_counts': settings['next_phase_counts']}
    if version != expected or settings.get('next_source_assets') != expected['source_assets']:
        raise ValueError('version-three source or freeze identity changed')
    for phase in PHASES:
        _phase_cases(experiment_v2.dataset_directory(frozen), phase,
                     settings['next_phase_counts'][phase])
    return frozen


def phase_inputs(directory, phase):
    if phase not in PHASES:
        raise ValueError('unknown execution phase')
    frozen = verify(directory)
    settings = frozen['settings']
    cases, digest = _phase_cases(experiment_v2.dataset_directory(frozen), phase,
                                 settings['next_phase_counts'][phase])
    models = {arm: settings['models'][arm] for arm in settings['available_arms']}
    if phase != 'development':
        experiment_v2.verify_phase(Path(directory), phase, cases, models, digest,
                                   settings['policy'], settings['prompt_version'])
    if phase == 'test':
        threshold = _read(Path(directory) / 'thresholds.json')
        _, _, _, calibration_plan = _phase_plan(directory, 'calibration')
        provenance = _phase_provenance(directory, 'calibration', calibration_plan,
                                       require_complete=True)
        if threshold.get('calibration_provenance') != provenance['hashes']:
            raise ValueError('calibration completion or recovery provenance changed')
    return cases, digest, models


def _phase_plan(directory, phase, *, require_journals=True):
    directory = Path(directory).resolve()
    frozen = verify(directory)
    cases, digest, models = phase_inputs(directory, phase)
    settings = frozen['settings']
    plan = _read(directory / phase / 'phase-plan.json')
    ordered = sorted(cases, key=lambda c: hashlib.sha256(('20260919:' + c['id']).encode()).hexdigest())
    repeat_ids = set()
    if phase == 'test':
        for family in {c['family'] for c in ordered}:
            repeat_ids.update(c['id'] for c in [c for c in ordered if c['family'] == family][:5])
    expected = {'schema': 3, 'phase': phase, 'freeze_sha256': sha(directory / 'freeze.json'),
                'case_ids': [c['id'] for c in ordered], 'models': models,
                'journals': {arm: arm + '.jsonl' for arm in models},
                'policy': settings['policy'], 'prompt_version': settings['prompt_version'],
                'dataset_sha256': digest, 'campaign_path': settings['campaign_path'],
                'cloud_cap_usd': settings['cloud_cap_usd'], 'repeat_case_ids': sorted(repeat_ids)}
    if any(plan.get(name) != value for name, value in expected.items()):
        raise ValueError('phase plan differs from frozen definition')
    wanted = {}
    for trial in range(1, 4 if phase == 'test' else 2):
        for case in ordered:
            if trial > 1 and case['id'] not in repeat_ids:
                continue
            for arm in models:
                key = f"{arm}:{case['id']}:{trial}"
                wanted[key] = {'key': key, 'arm': arm, 'case_id': case['id'], 'trial': trial,
                               'family': case['family'], 'kind': case['state']['unit']['kind'],
                               'deterministic_bypass': settings['policy'] == 'deterministic_first' and
                                                       case['state']['unit']['kind'] == 'executable'}
    rows = plan.get('rows')
    if not isinstance(rows, list) or len(rows) != len(wanted):
        raise ValueError('phase plan row coverage differs')
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or row.get('key') in seen or row != wanted.get(row.get('key')):
            raise ValueError('phase plan row identity differs')
        seen.add(row['key'])
    if require_journals:
        for filename in expected['journals'].values():
            if not (directory / phase / filename).is_file():
                raise ValueError('declared journal is missing: ' + filename)
    return frozen, cases, models, plan


def _event_rows(path):
    raw = Path(path).read_bytes()
    if not raw or not raw.endswith(b'\n'):
        raise ValueError('incomplete provenance file: ' + Path(path).name)
    rows = [strict_json(line) for line in raw.decode('utf8').splitlines()]
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError('provenance event must be an object')
    return rows


def _phase_provenance(directory, phase, plan, *, require_complete=False):
    """Read-only validation; never reopens a locked campaign or mutates journals."""
    directory = Path(directory) / phase
    ready = {'schema': 3, 'plan_sha256': sha(directory / 'phase-plan.json'),
             'definition_sha256': sha(directory / 'definition.json')}
    if _read(directory / 'READY.json') != ready:
        raise ValueError('phase READY binding differs')
    complete = directory / 'COMPLETE.json'
    if require_complete and not complete.is_file():
        raise ValueError('calibration completion is incomplete; COMPLETE marker required')
    if complete.exists():
        # Lazy import avoids the coordinator -> definition -> coordinator import cycle.
        from coordinator import _verify_complete
        _verify_complete(directory, plan)
    hashes = {'READY.json': sha(directory / 'READY.json'),
              'phase-plan.json': sha(directory / 'phase-plan.json')}
    if complete.exists():
        hashes['COMPLETE.json'] = sha(complete)
    interrupted = []
    def normalized(path):
        return os.path.normcase(str(Path(path).resolve()))
    for arm, filename in plan['journals'].items():
        path = directory / filename
        binding_path = Path(str(path) + '.binding.json')
        audit_path = Path(str(path) + '.recovery.jsonl')
        binding = {'schema': 1, 'journal': normalized(path),
                   'scope': str(directory.resolve()) + ':' + arm,
                   'identity': {'phase_plan_sha256': ready['plan_sha256']},
                   'campaign': normalized(plan['campaign_path']),
                   'cap_usd': str(Decimal(plan['cloud_cap_usd']).normalize()),
                   'audit': normalized(audit_path)}
        if _event_rows(binding_path) != [binding]:
            raise ValueError('journal binding differs from frozen phase/campaign')
        rows = _event_rows(audit_path)
        header = {'event': 'recovery_audit', 'schema': 1,
                  'binding_sha256': hashlib.sha256(canonical(binding).encode()).hexdigest()}
        if rows[0] != header:
            raise ValueError('recovery audit header differs from journal binding')
        events = _event_rows(path)
        requests = {}
        results = {}
        for event in events:
            if event.get('event') in ('request', 'result'):
                pair = (event.get('key'), event.get('attempt'))
                target = requests if event['event'] == 'request' else results
                if pair in target:
                    raise ValueError('duplicate request/result in recovery provenance')
                target[pair] = event
        audits = {}
        fields = {'event', 'key', 'attempt', 'reference', 'request_sha256', 'recovery_id'}
        for event in rows[1:]:
            if set(event) != fields or event['event'] != 'reconcile_interrupted':
                raise ValueError('unknown recovery audit event')
            if (not isinstance(event['reference'], str) or not event['reference'].strip() or
                    len(event['reference']) > 2048 or type(event['attempt']) is not int or
                    event['attempt'] not in (1, 2)):
                raise ValueError('invalid recovery reference or attempt')
            identity = hashlib.sha256(canonical({k: v for k, v in event.items()
                                                 if k != 'recovery_id'}).encode()).hexdigest()
            if event['recovery_id'] != identity or identity in audits:
                raise ValueError('invalid or duplicate recovery audit identity')
            request = requests.get((event['key'], event['attempt']))
            if request is None or event['request_sha256'] != hashlib.sha256(canonical(request).encode()).hexdigest():
                raise ValueError('recovery audit does not match a durable request')
            audits[identity] = event
        for pair, event in results.items():
            if event.get('error_type') != 'InterruptedProcess':
                continue
            audit = audits.get(event.get('recovery_id'))
            if (event.get('elapsed_ms') is not None or event.get('billing') != 'uncertain' or
                    'status' in event or audit is None or (audit['key'], audit['attempt']) != pair):
                raise ValueError('interrupted result requires matching audit and unknown timing/billing')
            interrupted.append({'arm': arm, 'key': pair[0], 'attempt': pair[1], 'elapsed_ms': None,
                                'billing': 'uncertain', 'recovery_id': event['recovery_id']})
        hashes[binding_path.name] = sha(binding_path)
        hashes[audit_path.name] = sha(audit_path)
    return {'hashes': hashes, 'interrupted': interrupted}


def freeze_thresholds(directory):
    """Recompute complete calibration evidence; never create intermediate bundles."""
    directory = Path(directory).resolve()
    frozen, cases, models, plan = _phase_plan(directory, 'calibration')
    settings = frozen['settings']
    if (directory / 'test').exists() and not (directory / 'thresholds.json').exists():
        raise ValueError('test has opened without an existing threshold freeze')
    provenance = _phase_provenance(directory, 'calibration', plan, require_complete=True)
    report_value = report(directory, 'calibration')
    summary = _read(directory / 'calibration' / 'summary.json')
    if summary.get('complete') is not True or not report_value['complete_from_evidence']:
        raise ValueError('calibration run incomplete; thresholds cannot be frozen')
    journals, arms = {}, {}
    for arm in ARMS:
        if arm not in models:
            reason = settings.get('unavailable_arms', {}).get(arm, settings.get('local_status'))
            arms[arm] = {'threshold': None, 'status': 'unavailable', 'reason': reason}
            continue
        path = directory / 'calibration' / plan['journals'][arm]
        evidence = replay(path)
        if evidence['unfinished_attempts']:
            raise ValueError('unresolved calibration attempt')
        answers = {}
        for case in cases:
            if settings['policy'] == 'deterministic_first' and case['state']['unit']['kind'] == 'executable':
                answers[case['id']] = None
                continue
            event = evidence['results'].get(f"{arm}:{case['id']}:1")
            if event is None:
                raise ValueError('calibration response missing')
            parsed = parse_response(event.get('body', ''), arm, models[arm]) if event.get('status') == 200 else None
            answers[case['id']] = parsed['answer'] if parsed and parsed['valid'] else None
        arms[arm] = {'threshold': calibrate(cases, answers), 'status': 'calibration-derived'}
        journals[path.relative_to(directory).as_posix()] = sha(path)
    value = {'freeze_sha256': sha(directory / 'freeze.json'), 'arms': arms, 'journals': journals,
             'calibration_provenance': provenance['hashes'],
             'rule': 'zero observed unsafe semantic skips; maximize safe coverage; tie high'}
    _write_checked(directory / 'thresholds.json', value)
    return arms


def report(directory, phase, tokenizer_environment=None):
    """Replay with legacy instruments after checking the new run's complete inventory."""
    directory = Path(directory).resolve()
    frozen, _, models, plan = _phase_plan(directory, phase)
    provenance = _phase_provenance(directory, phase, plan)
    value = development_report.report(directory / phase,
                                      experiment_v2.dataset_directory(frozen) / (phase + '.json'),
                                      tokenizer_environment)
    value['next_version'] = 3
    value['next_source_assets'] = source_inventory()
    value['version_sha256'] = sha(directory / 'version.json')
    value['phase_plan_sha256'] = sha(directory / phase / 'phase-plan.json')
    value['recovery_unknowns'] = provenance['interrupted']
    value['phase_provenance'] = provenance['hashes']
    value['completion_marker_verified'] = 'COMPLETE.json' in provenance['hashes']
    value['purpose'] = frozen['settings']['purpose']
    return value
