"""Immutable experiment definition and calibration lock. Does not authorize inference."""
import hashlib
import json
import os
from pathlib import Path
from adapters import canonical,strict_json
from core import calibrate


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def assets(root):
    """Bind protocol, complete fixture draft, scoring engine and execution sources."""
    paths=[root/'EVALUATION_PROTOCOL.md']
    for folder in ('study','logitpick','study-execution'):
        paths += [p for p in (root/folder).rglob('*') if p.is_file()
            and not any(part in ('results','__pycache__') for part in p.relative_to(root/folder).parts)
            and p.suffix in ('.py','.md','.json')]
    if not all(p.exists() for p in paths) or not (root/'study/cases.json').exists():
        raise ValueError('missing required study assets')
    return {p.relative_to(root).as_posix():sha(p) for p in sorted(set(paths))}


def write_once(path,value):
    with open(path,'x',encoding='utf8') as f:
        f.write(canonical(value)+'\n');f.flush();os.fsync(f.fileno())


def freeze_definition(root,run,settings):
    """Call only after development. Approval must be checked by the live driver.

    Recorded attestations are provenance, not independent verification or consent.
    No convenience defaults for unresolved models, tokenizer or label status.
    """
    if set(settings.get('resolved_models',{})) != {'local','jev','chat'}:
        raise ValueError('all three resolved model identifiers required')
    if any(not isinstance(v,str) or not v.strip() for v in settings['resolved_models'].values()):
        raise ValueError('empty model identifier')
    for name in ('local_digest','tokenizer_asset_sha256'):
        v=settings.get(name,'')
        if not isinstance(v,str) or len(v)!=64 or any(c not in '0123456789abcdef' for c in v):
            raise ValueError('missing digest: '+name)
    if not settings.get('tokenizer_method') or not settings.get('preflight_evidence_sha256'):
        raise ValueError('tokenizer method and preflight evidence required')
    if settings.get('label_status') not in ('independently_reviewed','agent_authored_unreviewed'):
        raise ValueError('label status must be explicit')
    if settings.get('label_status')=='independently_reviewed' and not settings.get('adjudication_sha256'):
        raise ValueError('reviewed status requires adjudication evidence')
    run.mkdir(exist_ok=False,parents=True)
    value={'schema':1,'phase':'definition-frozen','assets':assets(root),'settings':settings}
    write_once(run/'definition.json',value)
    return value


def verify_definition(root,run):
    value=strict_json((run/'definition.json').read_text(encoding='utf8'))
    if value['assets']!=assets(root):raise ValueError('experiment asset drift; create new version')
    return value


def freeze_calibration(root,run,bundles):
    definition=verify_definition(root,run)
    if (run/'test-started.json').exists():raise ValueError('test already opened')
    if set(bundles)!=set(definition['settings']['resolved_models']):raise ValueError('arm coverage mismatch')
    cases=[c for c in strict_json((root/'study/cases.json').read_text()) if c['split']=='calibration']
    if len(cases)!=80:raise ValueError('requires all 80 calibration cases')
    entries={}
    # Every bundle has normalized answers plus hashes of the raw source journals.
    # A driver must produce this through independent replay, never model labels.
    for arm,path in bundles.items():
        bundle=strict_json(Path(path).read_text(encoding='utf8'))
        if bundle['arm']!=arm or bundle['resolved_model']!=definition['settings']['resolved_models'][arm]:
            raise ValueError('calibration model mismatch')
        if not bundle.get('source_journals'):raise ValueError('raw evidence references required')
        for source,expected in bundle['source_journals'].items():
            source_path=(Path(path).parent/source).resolve()
            if sha(source_path)!=expected:raise ValueError('calibration journal drift')
        threshold=calibrate(cases,bundle['answers'])
        entries[arm]={'threshold':threshold,'bundle_sha256':sha(path),
            'bundle_path':os.path.relpath(Path(path).resolve(),run.resolve()),
            'source_journals':{os.path.relpath((Path(path).parent/p).resolve(),run.resolve()):h
                               for p,h in bundle['source_journals'].items()}}
    value={'definition_sha256':sha(run/'definition.json'),'arms':entries,
           'policy':'zero unsafe semantic calibration skips; maximize coverage; ties higher threshold'}
    write_once(run/'calibration.json',value)
    return value


def verify_calibration(root,run):
    verify_definition(root,run)
    value=strict_json((run/'calibration.json').read_text(encoding='utf8'))
    if value['definition_sha256']!=sha(run/'definition.json'):raise ValueError('definition lock drift')
    for entry in value['arms'].values():
        if sha(run/entry['bundle_path'])!=entry['bundle_sha256']:raise ValueError('calibration bundle drift')
        for path,expected in entry['source_journals'].items():
            if sha(run/path)!=expected:raise ValueError('raw calibration evidence drift')
    return value


def start_test(root,run):
    """One-shot marker before dispatch. Interrupted tests require audited resume.

    This marker provides scientific sequencing, not user authorization. The caller
    must separately enforce approval, spend/resource limits and request scheduling.
    """
    verify_calibration(root,run)
    value={'definition_sha256':sha(run/'definition.json'),
           'calibration_sha256':sha(run/'calibration.json'),'status':'opened_once'}
    write_once(run/'test-started.json',value)
    return value
