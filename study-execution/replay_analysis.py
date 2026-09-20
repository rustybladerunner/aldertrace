"""Recompute an arm's primary metrics from journal bodies and explicit case mapping."""
import json
from adapters import build,canonical,strict_json,parse_response,ROOT
from analysis import summarize


def analyze(path,cases,mapping,arm,expected_model,threshold):
    """mapping is logical-request-key -> unique case ID, never inferred from order.

    The journal supplied here must contain this one arm/primary subset only. A
    future multi-arm driver must export an exact event subset, preserving every
    attempt. This reader never filters unknown records silently.
    """
    by_id={c['id']:c for c in cases}
    if len(by_id)!=len(cases) or set(mapping.values())!=set(by_id) or len(mapping)!=len(cases):
        raise ValueError('mapping must cover each unique case once')
    reserved={};requests={};results={};delays={};begin=False
    with open(path,encoding='utf8') as f:
        for line in f:
            e=strict_json(line);kind=e['event']
            if kind=='begin':
                if begin:raise ValueError('duplicate journal header')
                begin=True;continue
            if not begin:raise ValueError('missing journal header')
            key=e.get('key')
            if key not in mapping:raise ValueError('unexpected request key')
            if kind=='retry_delay':
                seconds=e['seconds']
                if type(seconds) not in (int,float) or not 0<=seconds<=30:raise ValueError('invalid retry delay')
                delays[key]=delays.get(key,0)+seconds*1000;continue
            if kind=='retry_declined':continue
            pair=(key,e['attempt'])
            if type(e['attempt']) is not int or e['attempt'] not in (1,2):raise ValueError('invalid attempt')
            if kind=='reserved':
                if pair in reserved:raise ValueError('duplicate reservation')
                reserved[pair]=e
            elif kind=='request':
                if pair not in reserved or pair in requests:raise ValueError('request without unique reservation')
                if e['arm']!=arm or e['expected_model']!=expected_model:raise ValueError('arm/model mismatch')
                if canonical(e['body'])!=canonical(build(by_id[mapping[key]],arm)):
                    raise ValueError('request body does not match mapped synthetic case')
                requests[pair]=e
            elif kind=='result':
                if pair not in requests or pair in results:raise ValueError('result without unique request')
                results[pair]=e
            else:raise ValueError('unknown journal event')
    if not begin:raise ValueError('empty journal')
    answers={};missing=[];invalid=[];http_failed=[];transport_failed=[]
    elapsed={};attempt_counts={}
    for key,cid in mapping.items():
        attempts=sorted(n for k,n in reserved if k==key)
        if attempts and attempts!=list(range(1,max(attempts)+1)):raise ValueError('attempt gap')
        attempt_counts[cid]=len(attempts)
        final=results.get((key,max(attempts))) if attempts else None
        if final is None:
            missing.append(cid);answers[cid]=None;elapsed[cid]=None;continue
        # Never trust e['parsed']; independently decode body using pinned expectations.
        if final.get('status')==200:
            parsed=parse_response(final.get('body',''),arm,expected_model)
            answers[cid]=parsed['answer'] if parsed['valid'] else None
            if not parsed['valid']:invalid.append(cid)
        else:
            answers[cid]=None
            (transport_failed if final.get('error_type') else http_failed).append(cid)
        times=[results.get((key,n),{}).get('elapsed_ms') for n in attempts]
        elapsed[cid]=sum(times)+delays.get(key,0) if all(type(t) in (int,float) and 0<=t<float('inf') for t in times) else None
    report=summarize(cases,answers,threshold)
    report.update({'arm':arm,'expected_model':expected_model,'source':'reparsed journal bodies',
        'dataset_review':'agent-authored; independent adjudication not established by this reader',
        'missing_case_ids':missing,'invalid_response_case_ids':invalid,
        'http_failure_case_ids':http_failed,'transport_failure_case_ids':transport_failed,
        'unresolved_attempts':[{'key':k,'attempt':n} for k,n in reserved if (k,n) not in results],
        'attempt_counts':attempt_counts,'attempt_processing_plus_backoff_ms':elapsed,
        'latency_note':'Sum of recorded attempt processing and backoff, excludes unrecorded driver/journal overhead. Missing timing stays null.',
        'provider_cost_usd':None,'cost_status':'requires usage reconciliation; reservations are not measured spend'})
    return report


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('journal');p.add_argument('mapping')
    p.add_argument('--arm',required=True,choices=['jev','jev_openrouter','chat','local'])
    p.add_argument('--expected-model',required=True)
    p.add_argument('--threshold',required=True,help='frozen numeric threshold or none')
    a=p.parse_args();mapping=json.loads(open(a.mapping,encoding='utf8').read())
    cases=[c for c in json.loads((ROOT/'study/cases.json').read_text()) if c['id'] in set(mapping.values())]
    threshold=None if a.threshold=='none' else float(a.threshold)
    print(json.dumps(analyze(a.journal,cases,mapping,a.arm,a.expected_model,threshold),indent=2,allow_nan=False))
