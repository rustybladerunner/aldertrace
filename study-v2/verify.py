"""Aggregate-only integrity checks; does not reveal calibration/test rows."""
import argparse
import hashlib
import importlib.util
import json
import re
from collections import Counter
from itertools import combinations
from pathlib import Path

from build import ROOT, SPLITS, build, canonical


def content(case):
    state = case['state']
    criterion = state['unit']['skip_condition'].split(' Requires trusted integer exit 0')[0]
    # Schema fields, paths, IDs and the common typed-proof contract are excluded.
    # This is lexical screening, never a claim of semantic independence.
    return criterion + ' ' + state['explanation']


def shingles(text):
    words = re.findall(r'[a-z]+', text.lower())
    return {tuple(words[i:i+4]) for i in range(max(0, len(words)-3))}


def verify(split=None, evaluator=None):
    names = [split] if split else list(SPLITS)
    rows = []
    hashes = {}
    regenerated = build(split)
    for name in names:
        path = ROOT / (name + '.json')
        saved = json.loads(path.read_text())
        if saved != regenerated[name]:
            raise ValueError('Authored source mismatch: ' + name)
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.extend(saved)
    if len({c['id'] for c in rows}) != len(rows):
        raise ValueError('Duplicate identifiers')
    if len({canonical(c['state']) for c in rows}) != len(rows):
        raise ValueError('Duplicate complete states')
    mapping = {f['id']: f for f in json.loads((ROOT/'family-plan.json').read_text())['families']}
    for case in rows:
        family = mapping[case['family']]
        if case['split'] != family['split'] or case['state']['unit']['kind'] != family['kind']:
            raise ValueError('Family ownership mismatch')
        if case['review_status'] != 'agent_authored_unreviewed':
            raise ValueError('Unverified review provenance')
        if not case['label']['rationale'].strip() or not case['document'].strip():
            raise ValueError('Missing rationale or guide')
        if case['state']['unit']['kind'] == 'semantic':
            if len(case['document'].split()) < 40:
                raise ValueError('Semantic guide lacks substantive minimum content')
            if case['label']['action'] not in ('skip', 'read'):
                raise ValueError('Unexpected semantic label')
    counts = {}
    for name in names:
        selected = [c for c in rows if c['split'] == name]
        labels = Counter(c['label']['action'] for c in selected)
        if len(selected) != 80 or labels['skip'] < 30 or len(selected)-labels['skip'] < 40:
            raise ValueError('Split count or balance requirement failed')
        if set(Counter(c['family'] for c in selected).values()) != {20}:
            raise ValueError('Family size mismatch')
        if set(Counter(c['concept_cluster'] for c in selected).values()) != {2}:
            raise ValueError('Concept-pair size mismatch')
        counts[name] = {'cases': len(selected), 'families': 4, 'concept_clusters': 40,
                        'semantic': sum(c['state']['unit']['kind']=='semantic' for c in selected),
                        'skip_eligible': labels['skip'], 'non_skippable': len(selected)-labels['skip']}
    normalized = [content(c) for c in rows]
    tokens = [shingles(t) for t in normalized]
    cross_split_pairs = 0
    flagged = 0
    max_jaccard = 0.0
    for i, j in combinations(range(len(rows)), 2):
        if rows[i]['split'] == rows[j]['split']:
            continue
        cross_split_pairs += 1
        a, b = tokens[i], tokens[j]
        overlap = len(a & b)
        jaccard = overlap / len(a | b) if a | b else 0.0
        containment = overlap / min(len(a), len(b)) if a and b else 0.0
        max_jaccard = max(max_jaccard, jaccard)
        if jaccard >= .45 or containment >= .75:
            flagged += 1
    if flagged:
        raise ValueError(f'Cross-split lexical near-duplicate flags: {flagged}')
    machine_agreement = None
    if evaluator:
        spec = importlib.util.spec_from_file_location('frozen_study_core', evaluator)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        machine = [c for c in rows if c['state']['unit']['kind']=='executable']
        disagreement = sum(module.machine_gate(c['state']) != c['label']['action'] for c in machine)
        if disagreement:
            raise ValueError('Executable contract disagrees with authored labels')
        machine_agreement = {'cases_checked': len(machine), 'disagreements': disagreement}
        if split is None:
            module.validate_dataset(rows, {'families': list(mapping.values())})
    return {'version': 'aldertrace-study-v2-draft-1', 'counts': counts, 'sha256': hashes,
            'evaluator_contract_check': machine_agreement,
            'lexical_screen': {'cross_split_pairs': cross_split_pairs, 'flagged': flagged,
                               'maximum_fourgram_jaccard': max_jaccard,
                               'status': 'lexical screening only; semantic review remains unperformed'},
            'independent_review': 'unavailable; agent-authored and unreviewed; provisional',
            'authoring': 'No target backend, network service or personal corpus used.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--split', choices=SPLITS)
    parser.add_argument('--evaluator', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = verify(args.split, args.evaluator)
    serialized = json.dumps(result, indent=2) + '\n'
    if args.output:
        with args.output.open('x', encoding='utf8') as target:
            target.write(serialized)
    print(serialized)
