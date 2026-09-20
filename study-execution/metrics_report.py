"""Reproducible development-baseline chart data; no inference or fabricated gains."""
import argparse
from collections import Counter
import json
from pathlib import Path
from adapters import ROOT
from core import ACTIONS,baseline,score,verify_manifest,digest


def report(root=ROOT):
    verify_manifest(root/'study')
    cases=[c for c in json.loads((root/'study/cases.json').read_text()) if c['split']=='development']
    groups={}
    for group in ('all','executable','semantic'):
        selected=[c for c in cases if group=='all' or c['state']['unit']['kind']==group]
        arms={}
        for arm in ('read_everything','deterministic'):
            predictions={c['id']:baseline(c,arm) for c in selected}
            metrics=score(selected,predictions)
            counts=Counter(predictions.values())
            arms[arm]={'metrics':metrics,'actions':{a:counts[a] for a in ACTIONS},
                       'latency_p50_ms':None,'latency_p95_ms':None,'cost_usd':None}
        groups[group]={'n':len(selected),'families':len({c['family'] for c in selected}),'arms':arms}
    return {'schema':1,'scope':'synthetic development only','label_status':'agent_authored_unreviewed',
            'cases_sha256':digest(root/'study/cases.json'),'groups':groups,
            'unmeasured_arms':['local','jev','chat','calyx_memory'],
            'claim_status':'Descriptive fixture outcomes only; no held-out efficacy or statistical significance established.',
            'targets_not_results':{'net_token_reduction':0.20,'semantic_coverage_gain_pp':10},
            'required_future_metrics':['raw_and_enforced_unsafe_skips','safe_skip_coverage',
                'net_tokens_including_router_overhead','wall_latency_p50_p95','reported_cost_per_success',
                'invalid_response_rate','repeat_stability','paired_task_success',
                'family_clustered_uncertainty','no_memory_exact_cache_similarity_calyx_ablation']}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    value=report()
    if args.output:
        with args.output.open('x',encoding='utf8') as out:
            json.dump(value,out,indent=2,allow_nan=False);out.write('\n')
        print('Wrote development metrics; no model calls.')
    else:print(json.dumps(value,indent=2,allow_nan=False))
