"""Serialize explicit synthetic scenario pairs. Offline; standard library only.

Source rows own their domain narratives, evidence and labels. This module does
not import the evaluator, generate error variants or query a model. Paired rows
share one concept only within their assigned family/split.
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SPLITS = ('development', 'calibration', 'test')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def rows(path, width):
    for number, line in enumerate(path.read_text(encoding='utf8').splitlines(), 1):
        if not line.strip() or line.startswith('#'):
            continue
        fields = [x.strip() for x in line.split('|')]
        if len(fields) != width:
            raise ValueError(f'{path.name}:{number}: expected {width} fields, got {len(fields)}')
        yield fields


def record(spec, unit, revision):
    # Explicit source notation is only shorthand for typed fixture records.
    trust, rev, artifact, command, exit_code = spec.split(',')
    output = {}
    for name, value, expected in (
        ('trusted', trust, True), ('revision', rev, revision),
        ('artifact', artifact, unit['artifact']), ('command', command, unit['command']),
        ('exit_code', exit_code, 0),
    ):
        if value == '_':
            continue
        if value == '=':
            output[name] = expected
        elif value == 'true':
            output[name] = True
        elif value == 'false':
            output[name] = False
        elif value == 'null':
            output[name] = None
        elif value.startswith('s:'):
            output[name] = value[2:]
        elif value.lstrip('-').isdigit():
            output[name] = int(value)
        else:
            output[name] = value
    return output


def base(family, concept, branch, state, document, action, rationale, source):
    return {
        'id': 'v2-' + sha(f'{family["id"]}/{concept}/{branch}'.encode())[:16],
        'family': family['id'], 'split': family['split'], 'state': state,
        'document': document, 'label': {'action': action, 'rationale': rationale},
        'authoring_variant': concept + '/' + branch,
        'concept_cluster': family['id'] + '/' + concept,
        'review_status': 'agent_authored_unreviewed',
        'source': source,
    }


def build(split=None):
    plan = json.loads((ROOT / 'family-plan.json').read_text())
    output = {name: [] for name in SPLITS if split is None or name == split}
    for family in plan['families']:
        if family['split'] not in output:
            continue
        source = f'sources/{family["split"]}/{family["id"]}.txt'
        source_rows = list(rows(ROOT / source, 7 if family['kind'] == 'semantic' else 11))
        if len(source_rows) != 10:
            raise ValueError(f'{source}: expected ten explicitly authored concept pairs')
        for row in source_rows:
            concept = row[0]
            revision = family['id'] + '-' + concept + '-r1'
            if family['kind'] == 'semantic':
                _, criterion, sufficient, insufficient, why_good, why_bad, guide = row
                unit = {'kind': 'semantic', 'artifact': f'guides/{family["id"]}/{concept}.md',
                        'command': None, 'skip_condition': criterion}
                document = '# ' + concept.replace('-', ' ').title() + '\n\n' + guide + '\n'
                for branch, explanation, action, rationale in (
                    ('supported', sufficient, 'skip', why_good),
                    ('unsupported', insufficient, 'read', why_bad),
                ):
                    state = {'unit': dict(unit), 'current_revision': revision, 'scope_known': True,
                             'runner_evidence': [], 'explanation': explanation}
                    output[family['split']].append(base(family, concept, branch, state, document,
                                                        action, rationale, source))
            else:
                (_, command, artifact, criterion, good_context, good_records, why_good,
                 bad_context, bad_records, bad_action, why_bad) = row
                unit = {'kind': 'executable', 'artifact': artifact, 'command': command,
                        'skip_condition': criterion + ' Requires trusted integer exit 0 bound to this command, artifact and current revision.'}
                document = '# ' + concept.replace('-', ' ').title() + '\n\n' + criterion + '\n'
                for branch, explanation, specifications, action, rationale in (
                    ('supported', good_context, good_records, 'skip', why_good),
                    ('unsupported', bad_context, bad_records, bad_action, why_bad),
                ):
                    scope_known = not specifications.startswith('?')
                    specifications = specifications.lstrip('?')
                    evidence = [] if specifications == '-' else [record(x, unit, revision) for x in specifications.split(';')]
                    state = {'unit': dict(unit), 'current_revision': revision, 'scope_known': scope_known,
                             'runner_evidence': evidence, 'explanation': explanation}
                    output[family['split']].append(base(family, concept, branch, state, document,
                                                        action, rationale, source))
    # Stable ordering independent of authoring order. IDs are not sent to backends.
    return {split: sorted(cases, key=lambda c: c['id']) for split, cases in output.items()}


def materialize(split=None):
    output = build(split)
    for split, cases in output.items():
        path = ROOT / (split + '.json')
        if path.exists():
            raise ValueError('Refusing to overwrite authored cases: ' + path.name)
        path.write_text(json.dumps(cases, indent=2, ensure_ascii=True) + '\n', encoding='utf8')
    return {k: len(v) for k, v in output.items()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['build', 'check'])
    parser.add_argument('--split', choices=SPLITS)
    args = parser.parse_args()
    if args.command == 'build':
        print(json.dumps(materialize(args.split)))
    else:
        for split, cases in build(args.split).items():
            if cases != json.loads((ROOT / (split + '.json')).read_text()):
                raise SystemExit('Source mismatch: ' + split)
        print('All split files match their explicit authoring sources.')
