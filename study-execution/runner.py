"""Phase orchestration with injected transports. No live CLI or credential loading."""
from pathlib import Path
from contextlib import ExitStack
from adapters import build, execution_plan, strict_json, parse_response
from core import verify_manifest
from journal import Journal, execute_one, replay, money
from locks import verify_definition, verify_calibration, start_test, write_once, sha
from replay_analysis import analyze
from transport import usage

BOUNDS={'local':'0','jev':'.00025','chat':'.003'}


def run_phase(root, experiment, phase, transports, models, campaign, *, approved=False, secrets=()):
    """A callback receives one label-blind request and returns an HTTP-like envelope.

    The caller must separately authorize each real provider/resource and validate its
    prices. Use one campaign for preflight and all phases. Incomplete phases cannot be
    retried automatically. Local transport/telemetry wiring remains caller-owned.
    """
    if approved is not True:raise PermissionError('explicit execution approval required')
    if phase not in ('development','calibration','test'):raise ValueError('unknown phase')
    if set(transports)!=set(BOUNDS) or set(models)!=set(BOUNDS):raise ValueError('all primary arms required')
    if campaign is None or campaign.halted:raise ValueError('active shared campaign required')
    root=Path(root).resolve();experiment=Path(experiment).resolve()
    if experiment.is_relative_to(root):raise ValueError('run evidence must be outside frozen source tree')
    verify_manifest(root/'study')
    cases=strict_json((root/'study/cases.json').read_text(encoding='utf8'))
    by_id={c['id']:c for c in cases}
    if len(by_id)!=len(cases):raise ValueError('duplicate case identifier')
    if phase!='development':
        definition=verify_definition(root,experiment)
        if definition['settings']['resolved_models']!=models:raise ValueError('models differ from definition')
    if phase=='test':verify_calibration(root,experiment)
    directory=experiment/phase
    directory.mkdir(parents=True,exist_ok=False)
    # The directory itself is an exclusive phase claim, including interrupted runs.
    if phase=='test':start_test(root,experiment)
    rows=[row for row in execution_plan(cases) if row['split']==phase]
    mapping={arm:{} for arm in BOUNDS};notes=[];halted=None
    interruption=None;failure=None;halt_persistence_error=None
    try:
        with ExitStack() as stack:
            journals={}
            for arm in BOUNDS:
                j=Journal(directory/(arm+'.jsonl'),'2',secrets=secrets,
                          campaign=campaign,scope=str(directory)+':'+arm)
                stack.callback(j.close);journals[arm]=j
            for row in rows:
                arm=row['arm'];case=by_id[row['case_id']]
                key=f"{arm}:{case['id']}:{row['trial']}"
                if row['trial']==1:mapping[arm][key]=case['id']
                captures=[]
                def observed(body):
                    response=transports[arm](body);captures.append(response);return response
                parsed=execute_one(journals[arm],key,arm,build(case,arm),models[arm],BOUNDS[arm],observed)
                usage_notes=[]
                for response in captures:
                    if isinstance(response,dict) and response.get('status')==200 and arm!='local':
                        try:
                            measured=usage(response['body'],arm);usage_notes.append(measured)
                            if money(measured['accounting_usd'])>money(BOUNDS[arm]):
                                halted='usage exceeds reservation'
                        except (ValueError,TypeError,KeyError):halted='usage unavailable or outside envelope'
                if not parsed or not parsed['valid']:halted=halted or 'response requires review'
                notes.append({**row,'key':key,'valid':bool(parsed and parsed['valid']),'usage':usage_notes})
                if halted:
                    campaign.halt()
                    break
    except BaseException as exc:
        # Cancellation and persistence failures must not leave an active campaign.
        # Do not manufacture a result for an attempt whose billing is unresolved.
        failure=exc
        interruption={'error_type':type(exc).__name__}
        halted=halted or 'phase interrupted; reconcile retained reservations before continuing'
        try:campaign.halt()
        except BaseException as halt_exc:halt_persistence_error=type(halt_exc).__name__
        raise
    finally:
        result={'phase':phase,'complete':halted is None and len(notes)==len(rows),
                'halted':halted,'completed_requests':len(notes),'planned_requests':len(rows),
                'campaign_reserved_usd':str(campaign.reserved),'notes':notes,
                'interruption':interruption,'halt_persistence_error':halt_persistence_error}
        # Attempt both evidence writes even when one fails. Preserve the original
        # exception instead of replacing a cancellation with a finalization error.
        finalization_errors=[]
        for name,value in (('primary-mapping.json',mapping),('summary.json',result)):
            try:write_once(directory/name,value)
            except BaseException as exc:
                finalization_errors.append(exc)
                result['complete']=False
                result['halted']=result['halted'] or 'phase evidence finalization failed'
                result['finalization_error_types']=[type(e).__name__ for e in finalization_errors]
        if finalization_errors:
            try:campaign.halt()
            except BaseException:pass
            if failure is None:raise finalization_errors[0]
    return result


def calibration_bundles(root, experiment, models):
    """Export calibration answers by reparsing raw journals, never cached answers."""
    directory=Path(experiment)/'calibration'
    summary=strict_json((directory/'summary.json').read_text())
    if summary.get('phase')!='calibration' or summary.get('complete') is not True:
        raise ValueError('incomplete calibration; no threshold freeze')
    definition=verify_definition(Path(root),Path(experiment))
    if definition['settings']['resolved_models']!=models:raise ValueError('model mismatch')
    cases=[c for c in strict_json((Path(root)/'study/cases.json').read_text()) if c['split']=='calibration']
    mapping=strict_json((directory/'primary-mapping.json').read_text())
    bundles={}
    for arm in BOUNDS:
        raw=directory/(arm+'.jsonl')
        # Enforce request/case identity and reservation sequencing before deriving answers.
        report=analyze(raw,cases,mapping[arm],arm,models[arm],None)
        if report['unresolved_attempts'] or report['missing_case_ids']:
            raise ValueError('unfinished calibration evidence')
        responses=replay(raw)['results']
        answers={cid:parse_response(responses[key].get('body',''),arm,models[arm])['answer']
                 if responses[key].get('status')==200 else None for key,cid in mapping[arm].items()}
        target=directory/(arm+'-bundle.json')
        write_once(target,{'arm':arm,'resolved_model':models[arm],'answers':answers,
                          'source_journals':{raw.name:sha(raw)}})
        bundles[arm]=target
    return bundles
