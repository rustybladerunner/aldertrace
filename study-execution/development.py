"""Versioned, development-only measured execution. No inference on import."""
import hashlib
import json
import subprocess
import time
from contextlib import ExitStack
from pathlib import Path
from adapters import ROOT, MODELS, canonical, strict_json, execution_plan, parse_response
from routing_contract import build
from core import verify_manifest, baseline, enforce, normalized_answer
from journal import Journal, execute_one, replay, BudgetExceeded, money
from locks import write_once
from transport import usage

BOUNDS = {'local': '0', 'jev': '.00025', 'chat': '.003'}


def load_development(root=ROOT):
    verify_manifest(root / 'study')
    raw = (root / 'study/cases.json').read_bytes()
    return ([c for c in strict_json(raw.decode()) if c['split'] == 'development'],
            hashlib.sha256(raw).hexdigest())


def run(cases, directory, transports, models, campaign, *, dataset_hash,
        approved=False, secrets=(), limit=None, trials=1, policy='all_cases',
        evidence_kind='development', threshold=0.0, resource_snapshot=None,
        phase='development',prompt_version='v1'):
    """Development thresholds are exploratory; this function cannot open held-out.

    Invalid schema/top-k is an observed review, not permission for an invisible retry.
    Billing uncertainty, authentication, identity drift, or resource failure stops
    dispatch. Every attempt retains its shared reservation. A stopped run never resumes.
    """
    if approved is not True:
        raise PermissionError('explicit session approval required')
    if phase not in ('development','calibration','test') or not cases or any(c['split'] != phase for c in cases):
        raise ValueError('case split does not match execution phase')
    thresholds=None
    if phase!='development':
        from experiment_v2 import verify_phase
        if Path(directory).name!=phase:raise ValueError('fixed phase directory required')
        thresholds=verify_phase(Path(directory).parent,phase,cases,models,dataset_hash,policy,prompt_version)
        if limit is not None:raise ValueError('frozen phases cannot select subsets')
        evidence_kind='provisional-'+phase
    if set(transports) != set(models) or not set(transports) <= set(BOUNDS):
        raise ValueError('transport/model coverage differs')
    if trials not in (1, 3) or policy not in ('all_cases', 'deterministic_first'):
        raise ValueError('invalid development design')
    if campaign.halted:
        raise BudgetExceeded('campaign halted')
    ordered = sorted(cases, key=lambda c: hashlib.sha256(('20260919:'+c['id']).encode()).hexdigest())
    if limit is not None:
        if type(limit) is not int or not 1 <= limit <= len(ordered):
            raise ValueError('invalid subset size')
        ordered = ordered[:limit]
    directory = Path(directory).resolve()
    if directory.is_relative_to(ROOT.resolve()):
        raise ValueError('raw evidence must be outside source tree')
    directory.mkdir(parents=True, exist_ok=False)
    repeats=set()
    if phase=='test':
        for family in sorted({c['family'] for c in ordered}):
            repeats.update(c['id'] for c in [c for c in ordered if c['family']==family][:5])
        trials=3
    definition = {'schema': 2, 'evidence_kind': evidence_kind, 'split': phase,
        'dataset_sha256': dataset_hash, 'models': models, 'policy': policy,'prompt_version':prompt_version,
        'threshold': threshold if thresholds is None else thresholds,
        'threshold_status': 'exploratory; not calibrated' if phase=='development' else 'phase-locked',
        'repeat_case_ids':sorted(repeats),
        'case_ids': [c['id'] for c in ordered], 'trials': trials,
        'source_commit': subprocess.check_output(['git','-c','safe.directory='+ROOT.as_posix(),
                                                 'rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'source_files': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in sorted(Path(__file__).parent.glob('*.py'))},
        'settings': {'chat_temperature': 0, 'chat_seed': 20260919, 'chat_max_tokens': 512,
                     'local_temperature': 0, 'local_seed': 1, 'local_num_predict': 1},
        'label_status': 'agent_authored_unreviewed', 'synthetic_only': True,
        'started_utc': __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),
        'resource_before': resource_snapshot}
    write_once(directory/'definition.json', definition)
    rows=[]; stopped=None; interrupted=None
    arms=[a for a in ('local','jev','chat') if a in transports]
    try:
        with ExitStack() as stack:
            journals={}
            for arm in arms:
                journal=Journal(directory/(arm+'.jsonl'), '2', secrets=secrets,
                                campaign=campaign, scope=str(directory)+':'+arm)
                stack.callback(journal.close); journals[arm]=journal
            for trial in range(1,trials+1):
                for index, case in enumerate(ordered):
                    if phase=='test' and trial>1 and case['id'] not in repeats:continue
                    rotation=(index+trial-1)%len(arms)
                    for arm in arms[rotation:]+arms[:rotation]:
                        key=f"{arm}:{case['id']}:{trial}"
                        row={'arm':arm,'case_id':case['id'],'family':case['family'],
                             'kind':case['state']['unit']['kind'],'trial':trial,'key':key,
                             'usage':[], 'status':'not_dispatched'}
                        started=time.perf_counter(); captures=[]
                        def observed(body):
                            response=transports[arm](body); captures.append(response); return response
                        if policy=='deterministic_first' and case['state']['unit']['kind']=='executable':
                            action=baseline(case,'deterministic')
                            row.update(status='deterministic',raw_action=None,action=action,valid=None,attempts=0)
                        else:
                            parsed=execute_one(journals[arm],key,arm,build(case,arm,prompt_version),models[arm],BOUNDS[arm],observed)
                            answer=parsed.get('answer') if parsed else None
                            row.update(status='observed', valid=bool(parsed and parsed['valid']),
                                reason=parsed.get('reason') if parsed else 'transport_failure',
                                raw_action=answer['choice'] if answer else 'review',
                                action=enforce(case,answer,threshold if thresholds is None else thresholds[arm]),
                                attempts=journals[arm].attempts[key])
                            for response in captures:
                                if not isinstance(response,dict):
                                    stopped='malformed transport envelope'; break
                                if response.get('status')==200:
                                    try:
                                        if arm=='local':
                                            measured=response['usage']
                                        else:
                                            measured=usage(response['body'],arm)
                                            if money(measured['accounting_usd'])>money(BOUNDS[arm]):
                                                raise ValueError('usage exceeded reservation')
                                        row['usage'].append(measured)
                                    except (KeyError,TypeError,ValueError):
                                        campaign.halt(); stopped='usage unavailable or outside reservation'
                                elif response.get('status') in (401,403,404):
                                    stopped='provider access or model unavailable'
                            if parsed and parsed.get('reason')=='model_mismatch':
                                stopped='resolved model differs; preserve preflight and pin before new run'
                            if not captures or not isinstance(captures[-1],dict) or captures[-1].get('status')!=200:
                                stopped=stopped or 'transport failure; no further automatic dispatch'
                        row['end_to_end_ms']=round((time.perf_counter()-started)*1000,3)
                        rows.append(row)
                        if stopped: break
                    if stopped: break
                if stopped: break
    except BaseException as exc:
        stopped='interrupted:'+type(exc).__name__
        interrupted=exc
    finally:
        summary={'schema':2,'evidence_kind':evidence_kind,'split':phase,
                 'complete':stopped is None,'stopped':stopped,
                 'unique_cases_planned':len(ordered),
                 'planned_observations':(len(ordered)+2*len(repeats))*len(arms) if phase=='test' else len(ordered)*len(arms)*trials,
                 'recorded_observations':len(rows),'campaign_reserved_usd':str(campaign.reserved),'rows':rows}
        write_once(directory/'summary.json',summary)
    if interrupted: raise interrupted
    return summary
