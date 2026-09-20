"""Development-only cloud preflight. Default CLI mode makes no calls."""
from pathlib import Path
import os
import json
from decimal import Decimal
from adapters import ROOT,MODELS,build,strict_json
from journal import Journal,execute_one,money
from transport import CloudTransport,usage
from core import verify_manifest
from budget import CampaignBudget

BOUNDS={'jev':Decimal('.00025'),'chat':Decimal('.003')}


def run(cases,directory,transports,expected_models,*,approved=False,secrets=(),per_arm=1,campaign=None):
    if approved is not True:raise PermissionError('session approval required before preflight')
    if campaign is None:raise ValueError('shared campaign budget required')
    if set(transports)!={'jev','chat'} or set(expected_models)!=set(transports):
        raise ValueError('preflight requires both primary cloud arms')
    if type(per_arm) is not int or not 1<=per_arm<=10:raise ValueError('at most ten preflight cases per arm')
    development=sorted((c for c in cases if c['split']=='development'),key=lambda c:c['id'])[:per_arm]
    if len(development)!=per_arm:raise ValueError('insufficient development cases')
    directory.mkdir(parents=True,exist_ok=False)
    journal=Journal(directory/'attempts.jsonl','.065',secrets=secrets,
                    campaign=campaign,scope='preflight:'+str(directory.resolve()))
    notes=[];halted=None
    try:
        for i,c in enumerate(development):
            for arm in (('jev','chat') if i%2==0 else ('chat','jev')):
                captures=[]
                def observed(body):
                    response=transports[arm](body);captures.append(response);return response
                key=arm+':'+c['id']
                parsed=execute_one(journal,key,arm,build(c,arm),expected_models[arm],BOUNDS[arm],observed)
                note={'arm':arm,'case_id':c['id'],'attempts':journal.attempts[key],
                      'valid':bool(parsed and parsed['valid']),'usage':[]}
                for response in captures:
                    if response.get('status')==200:
                        try:
                            u=usage(response['body'],arm);note['usage'].append(u)
                            if money(u['accounting_usd'])>BOUNDS[arm]:halted='usage exceeded reservation'
                        except (ValueError,TypeError,KeyError):halted='usage unavailable or outside envelope'
                if not note['valid']:halted=halted or 'preflight response failed validation; inspect raw evidence before any further calls'
                notes.append(note)
                if halted:
                    campaign.halt()
                    break
            if halted:break
    finally:journal.close()
    result={'phase':'development-preflight','synthetic_only':True,'notes':notes,
            'halted':halted,'reserved_usd':str(journal.reserved),
            'remaining_work':'Verify resolved identities, usage/prices and tokenizer; no calibration/test dispatched.'}
    with (directory/'summary.json').open('x',encoding='utf8') as f:
        json.dump(result,f,indent=2,allow_nan=False);f.write('\n')
    return result


def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--execute',action='store_true')
    p.add_argument('--output',type=Path)
    p.add_argument('--approval-reference',help='Reference to explicit operator consent; not self-authorization')
    p.add_argument('--per-arm',type=int,default=1)
    p.add_argument('--campaign',type=Path,help='Shared campaign ledger; reuse for every study phase')
    p.add_argument('--create-campaign',action='store_true',help='Create the first ledger; refuses existing file')
    a=p.parse_args()
    verify_manifest(ROOT/'study')
    if not a.execute:
        print(json.dumps({'mode':'plan-only','network_calls':0,'per_arm':a.per_arm,
            'requires':'explicit $2 cloud approval, credentials in process environment, new output directory',
            'note':'The preflight reservations count toward the same overall $2 study cap, not an additional allowance.'},indent=2));return
    if not a.approval_reference or not a.output or not a.campaign:
        p.error('execution requires approval reference, output directory, and shared campaign ledger')
    keys={'jev':os.environ.get('TYPESAFE_API_KEY'),'chat':os.environ.get('OPENROUTER_API_KEY')}
    if not all(keys.values()):p.error('required process-environment credentials missing; values withheld')
    transports={arm:CloudTransport(arm,key,authorized=True) for arm,key in keys.items()}
    cases=json.loads((ROOT/'study/cases.json').read_text())
    with CampaignBudget(a.campaign,'2',create=a.create_campaign) as campaign:
        result=run(cases,a.output,transports,{arm:MODELS[arm] for arm in transports},
                   approved=True,secrets=tuple(keys.values()),per_arm=a.per_arm,campaign=campaign)
    # Output contains no keys, raw response bodies, or provider error messages.
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
