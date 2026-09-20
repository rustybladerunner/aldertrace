"""New-file-only prospective locks for the split-specific version-two study."""
import hashlib
import json
from pathlib import Path
from adapters import ROOT, strict_json, parse_response
from locks import sha, write_once
from core import calibrate
from journal import replay


def implementation_assets(root=ROOT):
    paths=[]
    for folder in ('study-execution','logitpick'):
        paths.extend(p for p in (root/folder).glob('*.py')
                     if p.name not in ('memory_ablation.py','test_memory_ablation.py'))
    paths.extend([root/'study/core.py',root/'EVALUATION_PROTOCOL.md'])
    return {p.relative_to(root).as_posix():sha(p) for p in sorted(paths)}


def dataset_assets(dataset):
    manifest=strict_json((dataset/'MANIFEST.json').read_text())
    entries=manifest.get('assets',manifest.get('sha256',{}))
    if not entries:raise ValueError('dataset asset hashes missing')
    for name,expected in entries.items():
        if sha(dataset/name)!=expected:raise ValueError('dataset asset drift: '+name)
    return entries


def freeze(directory,dataset,settings):
    """Record prospective models, resource/measurement policy and reviewed status.

    This is a provisional study if labels lack human adjudication. A freeze is not
    evidence that opaque provider serialization or model versioning is observable.
    """
    required={'models','label_status','tokenizer_identity','preflight_sha256','policy','prompt_version',
              'local_status','cloud_model_identity','measurement_scope','source_commit'}
    if not required<=set(settings):raise ValueError('freeze prerequisites incomplete')
    if set(settings['models'])!={'local','jev','chat'}:raise ValueError('three arm identities required')
    if settings['label_status']!='agent_authored_unreviewed':
        raise ValueError('no human adjudication record available')
    if settings['policy'] not in ('all_cases','deterministic_first'):
        raise ValueError('unknown policy')
    assets=dataset_assets(dataset)
    directory.mkdir(parents=True,exist_ok=False)
    relative=dataset.resolve().relative_to(ROOT.resolve()).as_posix() if dataset.resolve().is_relative_to(ROOT.resolve()) else None
    write_once(directory/'freeze.json',{'schema':2,'dataset_path':str(dataset.resolve()),'dataset_relative':relative,
        'dataset_assets':assets,'implementation_assets':implementation_assets(),
        'settings':settings,'heldout_opened':False})


def dataset_directory(value):
    return ROOT/value['dataset_relative'] if value.get('dataset_relative') else Path(value['dataset_path'])


def verify(directory):
    value=strict_json((directory/'freeze.json').read_text())
    if implementation_assets()!=value['implementation_assets']:
        raise ValueError('frozen implementation drift; new experiment version required')
    dataset=dataset_directory(value)
    if dataset_assets(dataset)!=value['dataset_assets']:raise ValueError('dataset manifest drift')
    return value


def verify_phase(directory,phase,cases,models,dataset_hash,policy,prompt_version):
    value=verify(directory)
    if phase not in ('calibration','test'):raise ValueError('unrecognized locked phase')
    expected=value['settings']['models']
    if any(expected.get(a)!=m for a,m in models.items()):raise ValueError('model identity differs')
    if set(models)!=set(value['settings'].get('available_arms',expected)):
        raise ValueError('available arm set differs from frozen design')
    if policy!=value['settings']['policy']:raise ValueError('policy changed')
    if prompt_version!=value['settings']['prompt_version']:raise ValueError('prompt version changed')
    path=dataset_directory(value)/(phase+'.json')
    if sha(path)!=dataset_hash or strict_json(path.read_text())!=cases:
        raise ValueError('phase input differs from frozen file')
    if phase=='test':
        calibration=strict_json((directory/'thresholds.json').read_text())
        if calibration['freeze_sha256']!=sha(directory/'freeze.json'):
            raise ValueError('calibration definition mismatch')
        for file,expected in calibration['journals'].items():
            if sha(directory/file)!=expected:raise ValueError('calibration evidence drift')
        return {a:e['threshold'] for a,e in calibration['arms'].items() if a in models}
    return {a:None for a in models}


def freeze_thresholds(directory,unavailable=None):
    value=verify(directory);unavailable=unavailable or {}
    cases=strict_json((dataset_directory(value)/'calibration.json').read_text())
    definition=strict_json((directory/'calibration/definition.json').read_text())
    summary=strict_json((directory/'calibration/summary.json').read_text())
    if summary.get('complete') is not True:raise ValueError('calibration run incomplete')
    journals={};arms={}
    for arm in value['settings']['models']:
        if arm in unavailable:
            arms[arm]={'threshold':None,'status':'unavailable','reason':unavailable[arm]};continue
        path=directory/'calibration'/(arm+'.jsonl')
        from development_report import _journal
        selected=[c for c in cases if definition['policy']!='deterministic_first' or c['state']['unit']['kind']!='executable']
        mapping={f"{arm}:{c['id']}:1":c for c in selected}
        _journal(path,arm,value['settings']['models'][arm],mapping,
                 prompt_version=definition.get('prompt_version','v1'))
        data=replay(path)
        if data['unfinished_attempts']:raise ValueError('unresolved calibration attempt')
        answers={}
        for c in cases:
            key=f"{arm}:{c['id']}:1"
            # Machine-only policy avoids a model call; calibration only concerns semantic cases.
            if definition['policy']=='deterministic_first' and c['state']['unit']['kind']=='executable':
                answers[c['id']]=None;continue
            if key not in data['results']:raise ValueError('calibration response missing')
            result=data['results'][key]
            parsed=parse_response(result.get('body',''),arm,value['settings']['models'][arm]) if result.get('status')==200 else None
            answers[c['id']]=parsed['answer'] if parsed and parsed['valid'] else None
        arms[arm]={'threshold':calibrate(cases,answers),'status':'calibration-derived'}
        journals[str(path.relative_to(directory))]=sha(path)
    write_once(directory/'thresholds.json',{'freeze_sha256':sha(directory/'freeze.json'),
        'arms':arms,'journals':journals,'rule':'zero observed unsafe semantic skips; maximize safe coverage; tie high'})
    return arms
