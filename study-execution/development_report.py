"""Offline measured replay; non-development phases require prospective study locks."""
import argparse
import hashlib
import html
import itertools
import math
import random
from decimal import Decimal
from pathlib import Path
from adapters import ROOT, canonical, strict_json, parse_response
from routing_contract import build
from core import baseline, enforce, score
from development import load_development
from locks import write_once
from transport import usage
from analysis import wilson, cluster_ratio


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def quantile(values, q):
    if not values:
        return None
    values = sorted(values)
    k = (len(values)-1)*q
    i = int(k)
    return values[i]+(values[min(i+1,len(values)-1)]-values[i])*(k-i)


def distribution(values):
    known = [v for v in values if v is not None]
    return {'measured_n':len(known), 'unknown_n':len(values)-len(known),
            'p50_ms':quantile(known,.5), 'p95_ms':quantile(known,.95)}


def _journal(path, arm, model, expected, prompt_version='v1'):
    records = {}
    request_order = []
    if not path.exists():
        return records, request_order
    raw = path.read_bytes()
    if not raw.endswith(b'\n'):
        raise ValueError('partial journal; reconcile before replay')
    header = False
    for line in raw.decode('utf8').splitlines():
        event = strict_json(line)
        kind = event.get('event')
        if kind == 'begin':
            if header or records:
                raise ValueError('duplicate journal header')
            header = True
            continue
        if not header or event.get('key') not in expected:
            raise ValueError('unexpected journal key or missing header')
        key = event['key']
        record = records.setdefault(key, {'attempts':{}, 'backoff_ms':0})
        if kind == 'retry_delay':
            value = event.get('seconds')
            if not number(value) or value > 30:
                raise ValueError('invalid backoff')
            record['backoff_ms'] += value*1000
            continue
        if kind == 'retry_declined':
            continue
        attempt = event.get('attempt')
        if type(attempt) is not int or attempt not in (1,2):
            raise ValueError('invalid attempt')
        attempts = record['attempts']
        if kind == 'reserved':
            if attempt in attempts or attempt != len(attempts)+1:
                raise ValueError('duplicate or out-of-order reservation')
            attempts[attempt] = {'reserved':event}
        elif kind == 'request':
            if attempt not in attempts or 'request' in attempts[attempt]:
                raise ValueError('request lacks unique reservation')
            if event.get('arm') != arm or event.get('expected_model') != model:
                raise ValueError('journal model or arm differs')
            if canonical(event.get('body')) != canonical(build(expected[key],arm,prompt_version)):
                raise ValueError('journal request does not match synthetic case')
            attempts[attempt]['request'] = event
            request_order.append((key,attempt))
        elif kind == 'result':
            if attempt not in attempts or 'request' not in attempts[attempt] or 'result' in attempts[attempt]:
                raise ValueError('result lacks unique request')
            attempts[attempt]['result'] = event
        else:
            raise ValueError('unknown journal event')
    if not header:
        raise ValueError('empty journal')
    return records, request_order


def _local_usage(directory, index, attempt, expected_model):
    """Bind this worker's response and exact prompt to its journal request."""
    path = directory/f'local-worker-{index}.json'
    if not path.exists() or not path.stat().st_size:
        return None
    value = strict_json(path.read_text(encoding='utf8'))
    result = attempt.get('result',{})
    if result.get('status') != 200:
        return None
    if canonical(value.get('response')) != canonical(strict_json(result['body'])):
        raise ValueError('local worker response differs from journal')
    events = value.get('records',[])
    by_kind = {}
    for event in events:
        kind = event.get('event')
        if kind in by_kind:
            raise ValueError('duplicate local telemetry event')
        by_kind[kind] = event
    if not {'local_request','local_response','local_usage'} <= set(by_kind):
        return None
    from logitpick.schema import parse_request
    from logitpick.codes import assign_codes
    from logitpick.prompt import render
    request = parse_request(attempt['request']['body'])
    question = request.questions[0]
    prompt = render(request.state,question.instructions,question.options,assign_codes(list(question.options)))
    sent = by_kind['local_request']['body']
    if sent.get('prompt') != prompt or sent.get('model') != expected_model:
        raise ValueError('local telemetry prompt/model differs from request')
    raw = strict_json(by_kind['local_response']['body'])
    measured = by_kind['local_usage']
    if raw.get('model') != expected_model or raw.get('done') is not True:
        raise ValueError('invalid local telemetry response')
    names = ('prompt_eval_count','eval_count','load_duration','prompt_eval_duration','eval_duration','total_duration')
    if any(type(raw.get(n)) is not int or raw[n] < 0 or measured.get(n) != raw[n] for n in names):
        raise ValueError('local telemetry counts differ or are invalid')
    cold = measured.get('cold_observed')
    if type(cold) is not bool or any(by_kind[k].get('cold_observed') != cold for k in ('local_request','local_response')):
        raise ValueError('local cold status differs')
    return {'input_tokens':raw['prompt_eval_count'],'output_tokens':raw['eval_count'],
            'estimated_usd':None,'reported_usd':None,'accounting_usd':'0',
            'cold_observed':cold,'load_ms':raw['load_duration']/1000000,
            'model_total_ms':raw['total_duration']/1000000,
            'worker_sha256':digest(path),'source':path.name}


def _resources(attempts, arm):
    known = [a['usage'] for a in attempts if a.get('usage') is not None]
    unknown = len(attempts)-len(known)
    def tokens(name):
        subtotal = sum(u[name] for u in known)
        return {'total':None if unknown else subtotal,'known_subtotal':subtotal,'unknown_attempts':unknown}
    result = {'attempts':len(attempts),'input_tokens':tokens('input_tokens'),
              'output_tokens':tokens('output_tokens'),'unknown_usage_attempts':unknown,
              'rate_snapshots':sorted({u['rate_snapshot'] for u in known if u.get('rate_snapshot')})}
    for name in ('estimated_usd','reported_usd'):
        values = [Decimal(str(u[name])) for u in known if u.get(name) is not None]
        missing = len(attempts)-len(values)
        result[name] = {'total':str(sum(values,Decimal(0))) if not missing else None,
                        'known_subtotal':str(sum(values,Decimal(0))), 'unknown_attempts':missing}
    if arm == 'local':
        result['cloud_cost_usd'] = '0'
        result['local_hardware_energy_cost_usd'] = None
        result['cold_requests'] = sum(u.get('cold_observed') is True for u in known)
        result['warm_requests'] = sum(u.get('cold_observed') is False for u in known)
        result['load_ms'] = distribution([u.get('load_ms') for u in known])
        result['local_telemetry_sources'] = [{'file':u['source'],'sha256':u['worker_sha256']} for u in known]
    return result


def _metrics(cases, predictions):
    value = score(cases,predictions)
    families = {f:score([c for c in cases if c['family']==f],
        {c['id']:predictions[c['id']] for c in cases if c['family']==f}) for f in sorted({c['family'] for c in cases})}
    value['unsafe_wilson_95_descriptive'] = wilson(value['unsafe_skips'],value['non_skippable'])
    if families:
        value['unsafe_family_bootstrap'] = cluster_ratio([(v['unsafe_skips'],v['non_skippable']) for v in families.values()],draws=1000)
    kinds={kind:score([c for c in cases if c['state']['unit']['kind']==kind],
        {c['id']:predictions[c['id']] for c in cases if c['state']['unit']['kind']==kind})
        for kind in sorted({c['state']['unit']['kind'] for c in cases})}
    return {'overall':value,'families':families,'kinds':kinds}


def _paired(left, right, cases):
    """Observed common primary cases; repeat requests do not increase n."""
    common = [c for c in cases if left[c['id']]['observed'] and right[c['id']]['observed']]
    def metric(name):
        return score(common,{c['id']:name[c['id']]['action'] for c in common})
    l,r = metric(left),metric(right)
    times = [(c['family'],right[c['id']]['end_to_end_ms']-left[c['id']]['end_to_end_ms'])
             for c in common if left[c['id']]['end_to_end_ms'] is not None and right[c['id']]['end_to_end_ms'] is not None]
    interval = None
    if times:
        families = sorted({f for f,v in times}); rng=random.Random(20260919);draws=[]
        for _ in range(1000):
            sample=[v for f in rng.choices(families,k=len(families)) for family,v in times if family==f]
            draws.append(sum(sample)/len(sample))
        interval=[quantile(draws,.025),quantile(draws,.975)]
    costs={}
    for signal in ('reported_usd','estimated_usd'):
        differences=[]
        for c in common:
            lv=left[c['id']].get('resources',{}).get(signal,{}).get('total')
            rv=right[c['id']].get('resources',{}).get(signal,{}).get('total')
            if lv is not None and rv is not None:
                differences.append(Decimal(rv)-Decimal(lv))
        costs[signal]={'matched_known_pairs':len(differences),
            'sum_difference':str(sum(differences,Decimal(0))) if differences else None,
            'scope':'Matched observations with known totals only; missing pairs excluded explicitly.'}
    return {'n_unique_matched':len(common),'safe_skips_difference':r['safe_skips']-l['safe_skips'],
            'unsafe_skips_difference':r['unsafe_skips']-l['unsafe_skips'],
            'safe_coverage_difference':r['safe_skip_coverage']-l['safe_skip_coverage'] if l['safe_skip_coverage'] is not None else None,
            'latency_pairs':len(times),'median_latency_difference_ms':quantile([v for f,v in times],.5),
            'mean_latency_difference_family_bootstrap_95':interval,
            'cost_differences':costs,
            'uncertainty_note':'Exploratory whole-family resampling; few authored families, no significance claim.'}


def report(directory, dataset=None, tokenizer_environment=None):
    directory = Path(directory).resolve()
    definition = strict_json((directory/'definition.json').read_text(encoding='utf8'))
    summary = strict_json((directory/'summary.json').read_text(encoding='utf8'))
    phase=definition.get('split')
    if phase not in ('development','calibration','test') or summary.get('split')!=phase:
        raise ValueError('report phase is invalid or inconsistent')
    if phase!='development' and (dataset is None or directory.name!=phase):
        raise ValueError('locked phase requires explicit dataset and fixed phase directory')
    if dataset is None:
        cases, dataset_hash = load_development()
    else:
        raw = Path(dataset).read_bytes(); cases = strict_json(raw.decode('utf8'))
        dataset_hash = hashlib.sha256(raw).hexdigest()
        if not isinstance(cases,list) or any(c.get('split')!=phase for c in cases):
            raise ValueError('custom dataset must contain '+phase+' cases only')
    if dataset_hash != definition.get('dataset_sha256'):
        raise ValueError('dataset hash differs from run definition')
    by_id = {c['id']:c for c in cases}
    selected = definition.get('case_ids',[])
    if len(by_id)!=len(cases) or not selected or len(set(selected))!=len(selected) or not set(selected)<=set(by_id):
        raise ValueError('invalid case selection')
    full_cases=cases
    cases = [by_id[cid] for cid in selected]
    models=definition.get('models',{}); trials=definition.get('trials');policy=definition.get('policy')
    prompt_version=definition.get('prompt_version','v1')
    if not models or not set(models)<= {'local','jev','chat'} or trials not in (1,3) or policy not in ('all_cases','deterministic_first'):
        raise ValueError('invalid development design')
    if prompt_version not in ('v1','v2'):
        raise ValueError('invalid prompt version')
    threshold=definition.get('threshold')
    locks={}
    if phase=='development':
        if threshold is not None and (not number(threshold) or threshold>1):
            raise ValueError('invalid exploratory threshold')
        thresholds={arm:threshold for arm in models}
        repeat_ids=set(selected) if trials==3 else set()
    else:
        from experiment_v2 import verify_phase
        thresholds=verify_phase(directory.parent,phase,full_cases,models,dataset_hash,policy,prompt_version)
        if threshold!=thresholds:
            raise ValueError('phase thresholds differ from frozen lock')
        if set(selected)!=set(by_id):
            raise ValueError('locked phase cannot select a subset')
        if (phase=='calibration' and trials!=1) or (phase=='test' and trials!=3):
            raise ValueError('locked phase trial count differs')
        repeat_ids=set()
        if phase=='test':
            ordered=sorted(cases,key=lambda c:hashlib.sha256(('20260919:'+c['id']).encode()).hexdigest())
            for family in sorted({c['family'] for c in ordered}):
                repeat_ids.update(c['id'] for c in [c for c in ordered if c['family']==family][:5])
        if definition.get('repeat_case_ids')!=sorted(repeat_ids):
            raise ValueError('locked repeat subset differs')
        locks['freeze.json']=digest(directory.parent/'freeze.json')
        if phase=='test':locks['thresholds.json']=digest(directory.parent/'thresholds.json')
    if set(thresholds)!=set(models) or any(t is not None and (not number(t) or t>1) for t in thresholds.values()):
        raise ValueError('invalid per-arm thresholds')
    tokenizer=None
    if tokenizer_environment is not None:
        from measured_tokens import FrozenTokenizer
        tokenizer=FrozenTokenizer(tokenizer_environment)
        if phase!='development':
            frozen=strict_json((directory.parent/'freeze.json').read_text(encoding='utf8'))
            if frozen['settings']['tokenizer_identity']!=tokenizer.identity:
                raise ValueError('measured tokenizer identity differs from frozen study')
    expected={f'{arm}:{c["id"]}:{trial}':(arm,c,trial) for arm in models for c in cases
        for trial in range(1,trials+1) if trial==1 or c['id'] in repeat_ids}
    rows={}
    for row in summary.get('rows',[]):
        key=row.get('key')
        if key not in expected or key in rows:
            raise ValueError('unexpected or duplicate summary row')
        arm,c,trial=expected[key]
        if any(row.get(k)!=v for k,v in {'arm':arm,'case_id':c['id'],'family':c['family'],'kind':c['state']['unit']['kind'],'trial':trial}.items()):
            raise ValueError('summary identity differs from request')
        if not number(row.get('end_to_end_ms')):
            raise ValueError('invalid summary timing')
        rows[key]=row
    if summary.get('recorded_observations')!=len(rows) or summary.get('planned_observations')!=len(expected):
        raise ValueError('summary counts differ from design')
    output={'schema':1,'evidence_kind':definition.get('evidence_kind'),'split':phase,
        'provisional':True,'label_status':definition.get('label_status'),'threshold':threshold,
        'threshold_status':('exploratory development operating point; not calibrated' if phase=='development'
                            else 'phase-locked; threshold selection is not probability calibration'),
        'phase_locks':locks,'prompt_version':prompt_version,'repeat_case_ids':sorted(repeat_ids),
        'policy':policy,'settings':definition.get('settings'),
        'source_commit':definition.get('source_commit'),'source_files':definition.get('source_files'),
        'report_code_sha256':digest(__file__),
        'dataset_sha256':dataset_hash,'n_unique_planned':len(cases),'trials':trials,
        'reported_complete':summary.get('complete'),'stopped':summary.get('stopped'),
        'resource_before':definition.get('resource_before'),'baselines':{},'arms':{},'paired':{},
        'tokenizer_provenance':tokenizer.provenance if tokenizer is not None else None,
        'net_tokens_saved':None,'task_success':None,
        'limitations':['Agent-authored '+phase+' labels; independent adjudication not established.',
            'Authored cases share families. Uncertainty is exploratory; zero observed errors does not establish safety.',
            'Native provider token counts are routing overhead, not comparable downstream tokenizer savings.',
            'Net token reduction, full task success and execution/check savings remain unmeasured.',
            'Unknown attempt usage makes totals unknown; known subtotals exclude unknown charges.',
            'Elapsed routing time includes recorded driver overhead; baseline execution latency is unmeasured.'],
        'source_artifacts':{p.name:digest(p) for p in (directory/'definition.json',directory/'summary.json')},
        'failures':[]}
    for arm in ('read_everything','deterministic'):
        output['baselines'][arm]=_metrics(cases,{c['id']:baseline(c,arm) for c in cases})
    primary={}
    for arm,model in models.items():
        arm_expected={k:c for k,(a,c,t) in expected.items() if a==arm and not (policy=='deterministic_first' and c['state']['unit']['kind']=='executable')}
        journal=directory/(arm+'.jsonl')
        records,request_order=_journal(journal,arm,model,arm_expected,prompt_version=prompt_version)
        if journal.exists():output['source_artifacts'][journal.name]=digest(journal)
        local_indices={pair:i+1 for i,pair in enumerate(request_order)}
        observations=[];all_attempts=[]
        for key,(a,c,trial) in expected.items():
            if a!=arm:continue
            row=rows.get(key);record=records.get(key,{'attempts':{},'backoff_ms':0});attempts=record['attempts']
            bypass=key not in arm_expected
            if row is not None:
                if row.get('attempts')!=len(attempts) or row.get('status')!=('deterministic' if bypass else 'observed'):
                    raise ValueError('summary attempt count/status differs from journal')
            times=[];measures=[]
            for n,attempt in sorted(attempts.items()):
                result=attempt.get('result',{});u=None
                if result.get('status')==200:
                    if arm=='local':u=_local_usage(directory,local_indices[(key,n)],attempt,model)
                    else:
                        try:u=usage(result['body'],arm)
                        except (KeyError,TypeError,ValueError):pass
                entry={'key':key,'attempt':n,'usage':u,'unresolved':'result' not in attempt}
                all_attempts.append(entry);measures.append(entry)
                times.append(result.get('elapsed_ms') if number(result.get('elapsed_ms')) else None)
            measured_time=row['end_to_end_ms'] if row else None
            if measured_time is not None and all(t is not None for t in times) and measured_time+2 < sum(times)+record['backoff_ms']:
                raise ValueError('summary timing is shorter than journal attempts and backoff')
            final=attempts[max(attempts)].get('result') if attempts else None
            parsed=parse_response(final.get('body',''),arm,model) if final and final.get('status')==200 else None
            answer=parsed['answer'] if parsed and parsed['valid'] else None
            observed=(row is not None) if bypass else final is not None
            raw_action=answer['choice'] if answer else 'review'
            action=baseline(c,'deterministic') if bypass and observed else enforce(c,answer,thresholds[arm])
            item={'key':key,'case_id':c['id'],'family':c['family'],'trial':trial,'observed':observed,
                'deterministic_bypass':bypass,'valid':bool(answer),'raw_action':None if bypass else raw_action,
                'action':action,'expected':c['label']['action'],'end_to_end_ms':measured_time,
                'attempts':len(attempts),'reason':parsed.get('reason') if parsed else 'missing_or_failed_response',
                'resources':_resources(measures,arm)}
            observations.append(item)
            if trial==1 and (not observed or (not bypass and not answer) or action!=c['label']['action'] or (not bypass and raw_action!=c['label']['action'])):
                output['failures'].append({'arm':arm,**item,'rationale':c['label']['rationale']})
        first={o['case_id']:o for o in observations if o['trial']==1};primary[arm]=first
        model_cases=[c for c in cases if not first[c['id']]['deterministic_bypass']]
        repeats=[]
        if trials==3:
            for c in cases:
                if c['id'] not in repeat_ids:continue
                sample=[o for o in observations if o['case_id']==c['id']]
                if all(o['observed'] for o in sample):
                    repeats.append({'case_id':c['id'],'raw_changed':len({(o['valid'],o['raw_action']) for o in sample})>1,
                        'enforced_changed':len({o['action'] for o in sample})>1})
        arm_report={'model':model,'primary_observed_n':sum(o['observed'] for o in first.values()),
            'primary_missing_n':sum(not o['observed'] for o in first.values()),
            'raw':_metrics(model_cases,{c['id']:first[c['id']]['raw_action'] for c in model_cases}),
            'raw_scope':'Model-eligible primary cases; no recommendation on deterministic bypasses. Missing/invalid answers count as review.',
            'enforced':_metrics(cases,{cid:o['action'] for cid,o in first.items()}),
            'invalid_primary_n':sum(not o['valid'] and not o['deterministic_bypass'] and o['observed'] for o in first.values()),
            'primary_latency':distribution([o['end_to_end_ms'] for o in first.values()]),
            'all_observation_latency':distribution([o['end_to_end_ms'] for o in observations]),
            'resources_all_attempts':_resources(all_attempts,arm),
            'unresolved_attempts':sum(a['unresolved'] for a in all_attempts),
            'retries':sum(max(0,o['attempts']-1) for o in observations),'observations':observations,
            'repeat_stability':{'planned_unique':len(repeat_ids),'complete_unique':len(repeats),
                'raw_changed_cases':sum(r['raw_changed'] for r in repeats) if repeats else None,
                'enforced_changed_cases':sum(r['enforced_changed'] for r in repeats) if repeats else None}}
        arm_report['input_proxy']=None
        if tokenizer is not None:
            from measured_tokens import measure_journal,measure_case,summarize
            measured=measure_journal(tokenizer,journal) if journal.exists() else {
                'attempts':[],'reserved_without_request':[],'journal_sha256':None}
            grouped={}
            for attempt in measured['attempts']:
                grouped.setdefault(attempt['key'],[]).append(attempt)
            case_measurements={c['id']:measure_case(tokenizer,c,grouped.get(f'{arm}:{c["id"]}:1',[])) for c in cases}
            totals=summarize(cases,{cid:o['action'] for cid,o in first.items()},case_measurements,tokenizer.identity)
            arm_report['input_proxy']={'primary_including_retries':totals,
                'primary_case_measurements':case_measurements,
                'all_trials_recorded_input_proxy_tokens':sum(a['common_input_proxy_tokens'] for a in measured['attempts']),
                'reserved_without_request':measured['reserved_without_request'],
                'journal_sha256':measured['journal_sha256'],'h1_eligible':False,
                'scope':'Exact guide text minus observable recorded routing input proxy. Primary retries included; repeat trials separate. Actual provider wrappers remain unknown.'}
        output['arms'][arm]=arm_report
    for arm in ('read_everything','deterministic'):
        primary[arm]={c['id']:{'observed':True,'action':baseline(c,arm),'end_to_end_ms':None} for c in cases}
    for left,right in itertools.combinations(primary,2):
        output['paired'][left+' -> '+right]=_paired(primary[left],primary[right],cases)
    output['complete_from_evidence']=all(a['primary_missing_n']==0 and not a['unresolved_attempts'] and
        all(o['observed'] for o in a['observations']) for a in output['arms'].values())
    return output


def render_html(value):
    esc=lambda s:html.escape(str(s))
    def fmt(v,suffix=''):
        return 'Not measured' if v is None else (f'{v:,.2f}' if isinstance(v,float) else esc(v))+suffix
    rows=[];bars=[]
    def graph(title,values,unit,signed=False):
        maximum=max([abs(float(v)) if signed else float(v) for name,v in values if v is not None]+[1])
        lines=[]
        for name,v in values:
            if v is None:plot='<span class="unknown">Not measured</span>'
            elif signed:
                side='left' if float(v)>=0 else 'right';color='#b3df85' if float(v)>=0 else '#e4a19a'
                plot=f'<div class="track signedtrack"><div class="bar" style="position:absolute;{side}:50%;width:{abs(float(v))/maximum*50:.2f}%;background:{color}"></div></div>'
            else:plot=f'<div class="track"><div class="bar" style="width:{float(v)/maximum*100:.2f}%"></div></div>'
            lines.append(f'<div class="minirow"><span>{esc(name)}</span>{plot}<b>{fmt(v,unit) if v is not None else "—"}</b></div>')
        return '<div class="minicard"><h3>'+esc(title)+'</h3>'+''.join(lines)+'</div>'
    graphs=graph('Primary routing p50',[(n,a['primary_latency']['p50_ms']) for n,a in value['arms'].items()],' ms')
    graphs+=graph('All-attempt routing input',[(n,a['resources_all_attempts']['input_tokens']['total']) for n,a in value['arms'].items()],' tokens')
    graphs+=graph('All-attempt estimated cloud cost',[(n,('0' if n=='local' else a['resources_all_attempts']['estimated_usd']['total'])) for n,a in value['arms'].items()],' USD')
    proxy_graph=graph('Net input proxy saved · primary requests and retries',
        [(n,a['input_proxy']['primary_including_retries']['net_input_proxy_tokens_saved'] if a.get('input_proxy') else None)
         for n,a in value['arms'].items()],' tokens',signed=True)
    proxy_rows=[]
    for name,a in value['arms'].items():
        p=a['input_proxy']['primary_including_retries'] if a.get('input_proxy') else {}
        proxy_rows.append('<tr><td>'+esc(name)+'</td>'+''.join('<td>'+fmt(p.get(k))+'</td>' for k in
            ('baseline_reading_tokens','safely_avoided_reading_tokens','routing_input_proxy_tokens','net_input_proxy_tokens_saved'))+'</tr>')
    series=[(name,entry['overall']) for name,entry in value['baselines'].items()]
    for name,entry in value['arms'].items():
        series.extend([(name+' raw',entry['raw']['overall']),(name+' enforced',entry['enforced']['overall'])])
    for name,m in series:
        coverage=m['safe_skip_coverage']
        bars.append(f'<div class="barrow"><span>{esc(name)}</span><div class="track"><div class="bar" style="width:{0 if coverage is None else coverage*100:.2f}%"></div></div><b>{fmt(None if coverage is None else coverage*100,"%")}</b><small>{m["safe_skips"]}/{m["skip_eligible"]} eligible · {m["unsafe_skips"]}/{m["non_skippable"]} unsafe</small></div>')
    for name,a in value['arms'].items():
        r=a['resources_all_attempts'];lat=a['primary_latency'];cost=r['reported_usd']
        rows.append(f'<tr><th>{esc(name)}</th><td>{a["primary_observed_n"]}/{value["n_unique_planned"]}</td><td>{fmt(lat["p50_ms"])}</td><td>{fmt(lat["p95_ms"])}</td><td>{fmt(r["input_tokens"]["total"])}<small>known {r["input_tokens"]["known_subtotal"]}</small></td><td>{fmt(r["output_tokens"]["total"])}<small>known {r["output_tokens"]["known_subtotal"]}</small></td><td>{fmt(cost["total"])}<small>known ${cost["known_subtotal"]}</small></td><td>{fmt(r["estimated_usd"]["total"])}<small>known ${r["estimated_usd"]["known_subtotal"]}</small></td><td>{r["attempts"]} / {a["retries"]}</td></tr>')
    failures=''.join(f'<tr><td>{esc(f["arm"])}</td><td>{esc(f["case_id"])}</td><td>{esc(f["raw_action"])}</td><td>{esc(f["action"])}</td><td>{esc(f["expected"])}</td><td>{esc(f["rationale"])}</td></tr>' for f in value['failures'][:12])
    pairs=''.join(f'<tr><td>{esc(name)}</td><td>{p["n_unique_matched"]}</td><td>{p["safe_skips_difference"]:+}</td><td>{p["unsafe_skips_difference"]:+}</td><td>{fmt(p["median_latency_difference_ms"])}</td></tr>' for name,p in value['paired'].items())
    family_rows=[]
    repeat_rows=[]
    for name,a in value['arms'].items():
        stability=a['repeat_stability']
        repeat_rows.append(f'<tr><td>{esc(name)}</td><td>{stability["complete_unique"]}/{stability["planned_unique"]}</td><td>{fmt(stability["raw_changed_cases"])}</td><td>{fmt(stability["enforced_changed_cases"])}</td></tr>')
        for family,m in a['enforced']['families'].items():
            family_rows.append(f'<tr><td>{esc(name)}</td><td>{esc(family)}</td><td>{m["n_unique"]}</td><td>{m["safe_skips"]}/{m["skip_eligible"]}</td><td>{m["unsafe_skips"]}/{m["non_skippable"]}</td></tr>')
    return f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Aldertrace · Measured routing</title><style>
    :root{{color-scheme:dark}}*{{box-sizing:border-box}}body{{margin:0;background:#101a20;color:#e5eee8;font:16px/1.5 system-ui,sans-serif}}main{{max-width:1200px;margin:auto;padding:48px 28px}}h1{{font-size:42px;line-height:1.12;letter-spacing:-1.5px;margin:12px 0}}h2{{font-size:23px;margin:0 0 20px}}p{{max-width:850px;color:#b9c9c4}}.eyebrow{{color:#a9d98b;letter-spacing:2px;font-size:12px;text-transform:uppercase}}.tag{{display:inline-block;border:1px solid #77936a;border-radius:30px;padding:5px 12px;margin:6px 8px 0 0;font-size:13px}}section{{margin-top:30px;padding:26px;background:#17262d;border:1px solid #2e4045;border-radius:16px}}.barrow{{display:grid;grid-template-columns:160px 1fr 100px 230px;gap:16px;align-items:center;margin:17px 0}}.track{{height:14px;background:#0d171b;border-radius:8px;overflow:hidden}}.signedtrack{{position:relative;background:linear-gradient(90deg,#0d171b 49.7%,#789086 49.7%,#789086 50.3%,#0d171b 50.3%)}}.bar{{height:100%;background:#b3df85}}small{{display:block;color:#9db2ab;font-size:12px}}table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{padding:12px 10px;text-align:left;vertical-align:top;border-bottom:1px solid #35474d}}th{{color:#d2e4da}}.scroll{{overflow:auto}}.unknown{{color:#edcc85}}code{{font-size:12px;overflow-wrap:anywhere}}a{{color:#b3df85}}.notice{{border-left:3px solid #edcc85;padding-left:16px}}.minicard{{margin:24px 0;padding:16px;border:1px solid #35474d;border-radius:10px}}.minirow{{display:grid;grid-template-columns:80px 1fr 180px;gap:12px;align-items:center;margin:10px 0}}.minirow b{{font-size:13px;text-align:right}}@media(max-width:760px){{main{{padding:24px 14px}}h1{{font-size:32px}}section{{padding:18px}}.barrow{{grid-template-columns:120px 1fr 70px;gap:10px}}.barrow small{{grid-column:2/4}}.minirow{{grid-template-columns:55px 1fr 120px}}}}</style><main>
    <div class="eyebrow">Aldertrace / evidence before autonomy</div><h1>What the routing evidence supports</h1>
    <p>A reproducible {esc(value['split'])} comparison. Raw model recommendations and enforced actions are scored separately; failed and missing responses remain visible.</p>
    <span class="tag">{esc(value['evidence_kind'])} · provisional</span><span class="tag">{value['n_unique_planned']} unique cases · {value['trials']} trial(s)</span><span class="tag">{esc(value['policy'])}</span>
    <p class="notice">Operating threshold(s): {esc(value['threshold'])}. {esc(value['threshold_status'])}. Labels are agent-authored and unreviewed. These observations do not establish calibrated probabilities, production safety, or general superiority.</p>
    <section><h2>Safe skip coverage</h2><p>Each bar uses its eligible-case denominator. Deterministic bypasses have no raw model recommendation. Unsafe skips are shown alongside coverage.</p>{''.join(bars)}</section>
    <section><h2>Measured overhead and latency</h2><p>Tokens and costs include every reserved attempt, including retries and repeat trials. Latency columns summarize primary routing observations only. Local hardware and energy cost remain unknown; cloud cost for local inference is $0. Tokenizers differ across models; native token counts describe each arm and are not equivalent units of downstream savings.</p>{graphs}<div class="scroll"><table><thead><tr><th>Arm</th><th>Observed</th><th>p50 ms</th><th>p95 ms</th><th>Input tokens</th><th>Output tokens</th><th>Reported $</th><th>Estimated $</th><th>Attempts / retries</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div><p class="unknown">Net downstream token reduction: Not measured. Full-task success: Not measured. A token count is not a token-saving result.</p></section>
    <section><h2>Paired differences</h2><p>Right arm minus left arm on observed common primary cases. Baseline task/check latency is unknown. Family resampling intervals and repeat stability are available in the JSON report.</p><div class="scroll"><table><tr><th>Pair</th><th>Matched n</th><th>Safe skips Δ</th><th>Unsafe skips Δ</th><th>Median latency Δ ms</th></tr>{pairs}</table></div></section>
    <section><h2>Input-token proxy · not actual H1 savings</h2><p>One frozen tokenizer counts exact guide text and the public serialized routing request (local engine render for local scoring). Hidden provider prompts remain unknown. Net proxy = safely avoided guide tokens − observable routing input, including every primary retry. Negative values are retained; repeats are reported separately. Exact guide bytes, token counts, and hashes are in the JSON report.</p>{proxy_graph}<div class="scroll"><table><tr><th>Arm</th><th>Baseline guide tokens</th><th>Safely avoided</th><th>Routing input proxy</th><th>Net input proxy saved</th></tr>{''.join(proxy_rows)}</table></div><p class="unknown">Actual net token reduction remains unknown. This proxy cannot establish H1.</p></section>
    <section><h2>Repeat stability</h2><p>Three observations per repeated case. Repeat trials never increase the unique sample count. No completed repeats means stability is not measured.</p><div class="scroll"><table><tr><th>Arm</th><th>Complete / planned unique</th><th>Changed raw cases</th><th>Changed enforced cases</th></tr>{''.join(repeat_rows)}</table></div></section>
    <section><h2>Families and failures</h2><p>Cases share authored families; request counts do not create independent evidence.</p><div class="scroll"><table><tr><th>Arm</th><th>Family</th><th>n</th><th>Safe / eligible</th><th>Unsafe / prohibited</th></tr>{''.join(family_rows)}</table></div><h3>Representative mismatches / invalid responses</h3><div class="scroll"><table><tr><th>Arm</th><th>Case</th><th>Raw</th><th>Enforced</th><th>Expected</th><th>Rationale</th></tr>{failures or '<tr><td colspan="6">No mismatches in the recorded comparison. This does not establish general reliability.</td></tr>'}</table></div></section>
    <section><h2>Reproduce the evidence</h2><p>Commit <code>{esc(value['source_commit'])}</code><br>Dataset SHA-256 <code>{esc(value['dataset_sha256'])}</code><br>Raw bodies are independently reparsed. Recorded actions, cached answers, and summary usage are not trusted.</p><p><a href="report.json">Open complete machine-readable report</a></p><ul>{''.join('<li>'+esc(s)+'</li>' for s in value['limitations'])}</ul></section></main></html>'''


def generate(directory, output, dataset=None, tokenizer_environment=None):
    output=Path(output).resolve()
    if output.is_relative_to(ROOT.resolve()):
        raise ValueError('report output must be outside source tree')
    value=report(directory,dataset,tokenizer_environment)
    output.mkdir(parents=True,exist_ok=False)
    write_once(output/'report.json',value)
    with (output/'index.html').open('x',encoding='utf8') as f:
        f.write(render_html(value))
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--dataset',type=Path)
    parser.add_argument('--tokenizer-environment',type=Path)
    args=parser.parse_args()
    value=generate(args.run,args.output,args.dataset,args.tokenizer_environment)
    print(canonical({'output':str(args.output),'unique_cases':value['n_unique_planned'],
                     'complete_from_evidence':value['complete_from_evidence'],'live_calls':0}))


if __name__=='__main__':
    main()
