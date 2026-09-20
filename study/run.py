"""Study CLI: validation, development baselines, and integrity; offline only."""
import argparse
import json
from pathlib import Path
from core import baseline, canonical, request, score, validate_dataset, write_manifest, verify_manifest

ROOT=Path(__file__).resolve().parent


def load():
    return json.loads((ROOT/'cases.json').read_text()), json.loads((ROOT/'family-plan.json').read_text())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['validate','baseline','manifest','verify'])
    args=parser.parse_args()
    if args.command=='manifest':
        result=write_manifest(ROOT)
        result={'phase':result['phase'],'assets':len(result['assets']),
                'ready_for_heldout_model_evaluation':False}
    elif args.command=='verify':
        result=verify_manifest(ROOT)
    else:
        cases,plan=load()
        result=validate_dataset(cases,plan)
        if args.command=='baseline':
            # Keep test and calibration outcomes untouched by development commands.
            cases=[c for c in cases if c['split']=='development']
            result={'scope':'development only','labels':'agent_authored_unreviewed','arms':{}}
            for arm in ('read_everything','deterministic'):
                predictions={c['id']:baseline(c,arm) for c in cases}
                result['arms'][arm]={'overall':score(cases,predictions),
                    'families':{family:score([c for c in cases if c['family']==family],
                        {c['id']:predictions[c['id']] for c in cases if c['family']==family})
                        for family in sorted({c['family'] for c in cases})},
                    'predictions':predictions}
            output=ROOT/'results'/'development-baselines.json'
            output.parent.mkdir(exist_ok=True)
            output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
            result={'scope':result['scope'],'arms':{k:v['overall'] for k,v in result['arms'].items()},
                    'evidence':str(output)}
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
