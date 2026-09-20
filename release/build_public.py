"""Export a privacy-reviewed derivative without changing private frozen evidence.

Run against a clean source commit. The output must not exist. No network, Git
history copying, model calls, installs or publication are performed.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess

HOME = re.compile(r'(?:[A-Za-z]:[\\/]+Users[\\/]+|/(?:Users|home)/)')
GPU = re.compile(r'GPU-[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}')
SECRET = re.compile(r'\b(?:sk-(?:proj-|ant-|or-v1-)?[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,}|(?:AKIA|ASIA)[A-Z0-9]{16})\b|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')
PATH_FILES = {
    'experiments/v002/evidence/campaign/v002-frozen/freeze.json',
    'experiments/v002/evidence/campaign/cloud-budget.jsonl',
    'experiments/v002/evidence/campaign/local-budget.jsonl',
    'experiments/v002/evidence/campaign/preflight-local-001/local-telemetry.jsonl',
    'experiments/v002/evidence/campaign/v002-development-local-002/local-telemetry.jsonl',
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(root, *args):
    return subprocess.check_output(['git','-c','safe.directory='+root.as_posix(),*args],cwd=root)


def json_bytes(value, lines=False):
    if lines:
        return ''.join(json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=True)+'\n' for v in value).encode()
    return (json.dumps(value,indent=2,sort_keys=True,ensure_ascii=True)+'\n').encode()


def parse(name, raw):
    if name.endswith('.jsonl'):
        return [json.loads(line) for line in raw.decode('utf8').splitlines()]
    return json.loads(raw)


def walk(value, transform, pointer=''):
    if isinstance(value,dict):
        return {k:walk(v,transform,pointer+'/'+k.replace('~','~0').replace('/','~1')) for k,v in value.items()}
    if isinstance(value,list):
        return [walk(v,transform,pointer+'/'+str(i)) for i,v in enumerate(value)]
    return transform(value,pointer)


def relative_key(value):
    # The cloud ledger serializes [scope, request, attempt] as its key.
    if value.startswith('['):
        parts=json.loads(value)
        if not isinstance(parts,list) or len(parts)!=3 or not isinstance(parts[0],str):
            raise ValueError('unexpected cloud key structure')
        parts[0]=relative_key(parts[0])
        return json.dumps(parts,separators=(',',':'),ensure_ascii=True)
    normalized=value.replace('\\','/')
    if normalized.count('/campaign/')!=1:
        raise ValueError('path not under the known campaign boundary')
    tail=normalized.split('/campaign/',1)[1]
    if not tail or '..' in tail.split('/') or HOME.search(tail):
        raise ValueError('unsafe campaign-relative key')
    return 'campaign/'+tail


def prepare(source, output):
    source=source.resolve();output=output.resolve()
    if output.exists() or output.is_relative_to(source):
        raise ValueError('output must be new and outside source')
    if (source/'PUBLIC-EXPORT.json').exists():
        raise ValueError('source is already a derivative; use the original recorded source')
    if git(source,'status','--porcelain').strip():
        raise ValueError('source must be committed and clean')
    commit=git(source,'rev-parse','HEAD').decode().strip()
    names=git(source,'ls-files','-z').decode().split('\0')
    original={n:(source/n).read_bytes() for n in names if n and not n.startswith('docs/domains/')}
    if any((source/n).is_symlink() for n in original):
        raise ValueError('symlinks are not part of the export contract')
    files=dict(original)
    rules={n:[] for n in files}
    gpu_ids=sorted({match for raw in files.values() for match in GPU.findall(raw.decode('utf8'))})
    pseudonyms={old:'GPU-REDACTED-'+str(i+1).zfill(2) for i,old in enumerate(gpu_ids)}
    key_mapping={}
    for name,raw in list(files.items()):
        if not name.endswith(('.json','.jsonl')):
            continue
        value=parse(name,raw)
        def sanitize(item,pointer):
            if not isinstance(item,str):return item
            result=item
            if HOME.search(result):
                if name not in PATH_FILES:raise ValueError('unexpected path-bearing file: '+name)
                if name.endswith('/freeze.json') and pointer=='/dataset_path':
                    result='study-v2'
                elif pointer.endswith('/key'):
                    result=relative_key(result)
                    if result in key_mapping and key_mapping[result]!=item:
                        raise ValueError('redacted reservation key collision')
                    key_mapping[result]=item
                else:raise ValueError('unexpected path-bearing field: '+name+pointer)
                rules[name].append({'field':pointer,'change':'workstation path to repository/campaign-relative identity'})
            for old,new in pseudonyms.items():
                result=result.replace(old,new)
            if result!=item and not HOME.search(item):
                rules[name].append({'field':pointer,'change':'hardware UUID to consistent public pseudonym'})
            return result
        changed=walk(value,sanitize)
        if changed!=value:files[name]=json_bytes(changed,name.endswith('.jsonl'))

    # Public entry points replace private coordination text; frozen scientific
    # source/protocol files are not rewritten.
    files['README.md']=original['release/README-PUBLIC.md']
    files['CONTRIBUTING.md']=original['release/CONTRIBUTING-PUBLIC.md']
    files['AGENTS.md']=b'''# Aldertrace public checkout\n\nRead README.md and CONTRIBUTING.md. Preserve frozen datasets and implementation.\nRun affected offline checks. No model calls, installs or publication by default.\nUse the supplied skills/context map; no private domain memory is bundled.\n'''
    files['COLLABORATING.md']=b'# Collaboration\n\nSee [CONTRIBUTING.md](CONTRIBUTING.md), [README.md](README.md), and [skills](skills/README.md).\n'
    files['PUBLISH.md']=b'''# Release candidate\n\nMIT licensed. This is a sanitized derivative with fresh history.\nSee PUBLIC-EXPORT.json for provenance. Publication still requires the owner's\napproval; do not upload private source history or alter repository visibility.\nThe fresh synthetic live routing smoke passed; see release/RELEASE-STATUS.md.\n'''
    for name in ('README.md','AGENTS.md','COLLABORATING.md','PUBLISH.md'):
        rules[name]=[{'change':'public entry-point documentation; original retained privately'}]
    rules['CONTRIBUTING.md']=[{'change':'new public contribution guide'}]
    next_readme='study-next/README.md'
    text=files[next_readme].decode()
    marker='## Decisions and continuity'
    if marker in text:
        text=text.split(marker)[0]+'''## Decisions and continuity

Use the current code, tests and recorded evidence as the integration baseline.
The public [skills](../skills/README.md) provide project-context templates;
private domain notes and contributor review archives are not bundled.
'''
        files[next_readme]=text.encode()
        rules[next_readme].append({'change':'replace private domain-note links with public context map'})
    export_name='experiments/v002/EXPORT-MANIFEST.json'
    export=parse(export_name,files[export_name])
    export['scope']='sanitized derivative of reviewed synthetic evidence; see PUBLIC-EXPORT.json'
    export['notes']='Workstation metadata and hardware identifiers pseudonymized; dependent provenance hashes rebound. Scientific measurements unchanged. Private originals preserved.'
    files[export_name]=json_bytes(export)
    rules[export_name].append({'change':'describe derivative scope accurately'})

    # Rebuild the dependency graph from the original digest identities. Applying
    # each round to the same sanitized base avoids chained replacement drift.
    sanitized=dict(files)
    for iteration in range(30):
        replacements={sha(raw):sha(files[name]) for name,raw in original.items() if raw!=files[name]}
        updated=dict(files)
        for name,raw in sanitized.items():
            if not name.endswith(('.json','.jsonl')):continue
            value=parse(name,raw)
            changed=walk(value,lambda v,p:replacements.get(v,v) if isinstance(v,str) else v)
            updated[name]=json_bytes(changed,name.endswith('.jsonl')) if changed!=value else raw
        if updated==files:break
        files=updated
    else:raise ValueError('hash dependency graph did not converge')

    replacements={sha(raw):sha(files[name]) for name,raw in original.items() if raw!=files[name]}
    for name,raw in sanitized.items():
        if not name.endswith(('.json','.jsonl')):continue
        def record(v,p):
            if isinstance(v,str) and v in replacements:
                rules[name].append({'field':p,'change':'rebind exact SHA-256 to corresponding exported bytes'})
            return v
        walk(parse(name,raw),record)
    frozen=json.loads(original['experiments/v002/evidence/campaign/v002-frozen/freeze.json'])
    for name,digest in frozen['implementation_assets'].items():
        if sha(files[name])!=digest:raise ValueError('frozen implementation altered: '+name)
    for folder,manifest in (('study','manifest.json'),('study-v2','MANIFEST.json')):
        for name in json.loads(original[folder+'/'+manifest])['assets']:
            path=folder+'/'+name
            if files[path]!=original[path]:raise ValueError('dataset altered: '+path)
    # Every raw model journal remains byte-identical, including requests, raw
    # responses, usage and failures. Only aggregate budget/telemetry keys change.
    journal_names=[n for n in original if n.endswith(('/chat.jsonl','/jev.jsonl','/local.jsonl'))]
    if any(files[n]!=original[n] for n in journal_names):raise ValueError('raw model journal changed')
    threshold='experiments/v002/evidence/campaign/v002-frozen/thresholds.json'
    old_lock=parse(threshold,original[threshold]);new_lock=parse(threshold,files[threshold])
    for key in ('arms','journals','rule'):
        if old_lock[key]!=new_lock[key]:raise ValueError('scientific threshold lock changed')
    # Rebinding must affect only references to copied objects, plus declared
    # path/hardware fields above. The data-level changes are fully enumerated.
    files['experiments/v002/PUBLIC-DERIVATIVE.md']=b'This is a privacy-sanitized derivative of the original v002 export. The 95-file export inventory binds the derived bytes. Workstation identities and dependent hashes differ from the private originals; scientific inputs and raw model journals are preserved. See ../../PUBLIC-EXPORT.json for the exact mapping. The historical REPRODUCE.md description of the original export must be read with this note. No original files were modified in place.\n'
    rules['experiments/v002/PUBLIC-DERIVATIVE.md']=[{'change':'new derivative-scope note'}]
    manifest={'schema':1,'kind':'sanitized derivative, not a new experiment','source_commit':commit,
        'transformer_sha256':sha(Path(__file__).read_bytes()),'source_history_copied':False,
        'private_domain_notes_included':False,'hardware_identifiers_pseudonymized':len(pseudonyms),
        'frozen_implementation_files_unchanged':len(frozen['implementation_assets']),
        'raw_model_journals_byte_identical':len(journal_names),'threshold_values_unchanged':True,
        'limits':['Original hashes bind private originals; they do not independently attest chronology.',
                  'Windows-only full replay remains unchanged.','No new model efficacy or human label validation is implied.'],
        'files':{n:{'source_sha256':sha(original[n]) if n in original else None,
                    'export_sha256':sha(raw),'transformations':rules.get(n,[])} for n,raw in sorted(files.items())}}
    for name,raw in files.items():
        text=raw.decode('utf8')
        if HOME.search(text) or GPU.search(text) or SECRET.search(text):
            raise ValueError('privacy pattern remains in candidate: '+name)
        if name!='release/build_public.py' and re.search(r'"signature"\s*:|redacted_thinking',text):
            raise ValueError('reasoning-trace marker requires review: '+name)
        if name.endswith(('.json','.jsonl')) and re.search(r'[A-Za-z0-9+/]{200,}={0,2}',text):
            raise ValueError('encoded blob requires review: '+name)
    output.mkdir(parents=True)
    # Scope is an explicit inventory; .git and ignored source files are never copied.
    for name,raw in sorted(files.items()):
        dest=output/name
        if not dest.resolve().is_relative_to(output):raise ValueError('export path escape')
        dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw)
    (output/'PUBLIC-EXPORT.json').write_bytes(json_bytes(manifest))
    return {'source_commit':commit,'files':len(files),'raw_model_journals_unchanged':len(journal_names),
            'transformed_files':sum(bool(v) for v in rules.values()),'hash_rounds':iteration+1}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(prepare(args.source,args.output),indent=2))
