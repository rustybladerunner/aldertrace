"""Export all semantic labels and a stratified machine sample for human review."""
import csv
import hashlib
import json
from pathlib import Path
from adapters import ROOT,canonical


def select(cases):
    selected=[c for c in cases if c['state']['unit']['kind']=='semantic']
    machine=[c for c in cases if c['state']['unit']['kind']=='executable']
    for family in sorted({c['family'] for c in machine}):
        for eligible in (True,False):
            group=[c for c in machine if c['family']==family and (c['label']['action']=='skip')==eligible]
            selected+=sorted(group,key=lambda c:hashlib.sha256(('review:'+c['id']).encode()).hexdigest())[:2]
    return sorted(selected,key=lambda c:(c['split'],c['family'],c['id']))


def export(destination):
    cases=json.loads((ROOT/'study/cases.json').read_text())
    selected=select(cases)
    fields=['id','split','family','kind','state','expected_action','rationale',
            'reviewer','reviewer_action','reviewer_notes','near_duplicate_concern']
    with open(destination,'x',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields)
        writer.writeheader()
        for c in selected:
            writer.writerow({'id':c['id'],'split':c['split'],'family':c['family'],
                'kind':c['state']['unit']['kind'],'state':canonical(c['state']),
                'expected_action':c['label']['action'],'rationale':c['label']['rationale']})
    return {'semantic':sum(c['state']['unit']['kind']=='semantic' for c in selected),
            'machine':sum(c['state']['unit']['kind']=='executable' for c in selected),
            'status':'pending; reviewer fields intentionally blank'}


def assess(path):
    cases=json.loads((ROOT/'study/cases.json').read_text())
    expected={c['id']:c for c in select(cases)}
    with open(path,encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    if len(rows)!=len(expected) or {r['id'] for r in rows}!=set(expected):
        raise ValueError('review coverage mismatch')
    disagreements=[]; pending=[]; concerns=[]
    for r in rows:
        c=expected[r['id']]
        if r['expected_action']!=c['label']['action'] or r['state']!=canonical(c['state']):
            raise ValueError('review source altered')
        if not r['reviewer'].strip() or r['reviewer_action'] not in ('skip','read','run_check','review'):
            pending.append(r['id'])
        elif r['reviewer_action']!=r['expected_action']:
            disagreements.append({'id':r['id'],'expected':r['expected_action'],
                                  'reviewed':r['reviewer_action'],'notes':r['reviewer_notes']})
        if r['near_duplicate_concern'].strip():concerns.append(r['id'])
    return {'pending':pending,'disagreements':disagreements,'near_duplicate_flags':concerns,
            'adjudicated':False,'note':'CSV entries are attestations, not proof of independent identity; cross-family novelty still needs review.'}


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['export','assess']);p.add_argument('path',type=Path)
    a=p.parse_args()
    print(json.dumps(export(a.path) if a.command=='export' else assess(a.path),indent=2))
