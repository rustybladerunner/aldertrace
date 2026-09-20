"""Build an append-only, offline Aldertrace evidence story from scored JSON artifacts.

This presentation generator is deliberately outside the frozen experiment checkout.
It never opens a held-out report unless --heldout is supplied explicitly.
"""
import argparse
import csv
import hashlib
import html
import json
import re
from decimal import Decimal
from pathlib import Path
import shutil

DEV_NAMES=(('D1','v002-development-cloud-001-report-final','Original instructions'),
           ('D2','v002-development-cloud-002-report','Clarified semantic evidence'),
           ('D3','v002-development-cloud-003-report','Deterministic checks first'))
COLORS={'jev':'#b4dd8f','chat':'#bdb5fa','local':'#f1bf83'}
NAMES={'jev':'Jev','chat':'Chat model','local':'Local scoring'}
BLINDING_NOTE=('The operator was not fully blinded: a source-blinding diagnostic printed the tail of held-out source/labels after all three development choices had been selected but before freeze. No prompt, policy or dataset change followed that exposure. No tuning used held-out outcomes.')


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text(encoding='utf8'))
def esc(value):return html.escape(str(value))
def num(value,decimals=0):
    return 'Unknown' if value is None else f'{float(value):,.{decimals}f}'
def percent(value):return 'Unknown' if value is None else num(value*100,1)+'%'
def money(value):return 'Unknown' if value is None else '$'+format(Decimal(str(value)),'.8f').rstrip('0').rstrip('.')
def ratio(m,n='safe_skips',d='skip_eligible'):return f'{m[n]}/{m[d]}'
def quantile(values,q):
    if not values:return None
    values=sorted(values);k=(len(values)-1)*q;i=int(k)
    return values[i]+(values[min(i+1,len(values)-1)]-values[i])*(k-i)
def latency(arm,requests=True):
    rows=[o for o in arm['observations'] if o['trial']==1 and o.get('end_to_end_ms') is not None
          and (not requests or o['attempts']>0)]
    return {'n':len(rows),'p50_ms':quantile([o['end_to_end_ms'] for o in rows],.5),
            'p95_ms':quantile([o['end_to_end_ms'] for o in rows],.95)}
def proxy(arm):return (arm.get('input_proxy') or {}).get('primary_including_retries',{})
def overall(arm,kind='enforced'):return arm[kind]['overall']


def state(root,heldout=None):
    root=Path(root).resolve();sources={};reports=[]
    def source(relative):
        candidates=[root/relative]
        if relative.startswith('campaign/'):
            tail=relative[len('campaign/'):]
            candidates += [root/'reports'/tail,root/'evidence/campaign'/tail]
        elif relative.startswith('aldertrace-memory-v1-results/'):
            candidates.append(root.parent/'memory-v1/evidence'/relative.split('/',1)[1])
        elif relative.startswith('agent-review-provisional-v2-20260920/'):
            candidates.append(root/'label-review/aggregate-summary.json')
        path=next((p for p in candidates if p.exists()),candidates[0])
        sources[relative]=sha(path);return read(path)
    for tag,dirname,title in DEV_NAMES:
        report=source('campaign/'+dirname+'/report.json')
        if report['split']!='development':raise ValueError('development evidence has wrong split')
        reports.append({'tag':tag,'title':title,'directory':dirname,'report':report})
    signatures=[(r['report']['dataset_sha256'], sorted(o['case_id'] for o in next(iter(r['report']['arms'].values()))['observations'] if o['trial']==1)) for r in reports]
    if any(s!=signatures[0] for s in signatures):raise ValueError('development versions do not use matched cases')
    local=source('campaign/v002-development-local-002-report/report.json')
    memory=source('aldertrace-memory-v1-results/summary.json')
    review=source('agent-review-provisional-v2-20260920/aggregate-summary.json')
    freeze=source('campaign/v002-frozen/freeze.json')
    thresholds=source('campaign/v002-frozen/thresholds.json')
    calibration=source('campaign/v002-calibration-report/report.json')
    receipt=source('campaign/budget-receipt-final.json')
    held=None
    if heldout is not None:
        path=Path(heldout).resolve()
        if path.is_dir():path=path/'report.json'
        if path.exists():
            held=read(path)
            if held.get('split')!='test' or not held.get('phase_locks'):
                raise ValueError('heldout input must be a scored locked test report')
            sources[path.relative_to(root).as_posix()]=sha(path)
    budgets={}
    for name in ('cloud','local'):
        path=root/'campaign'/(name+'-budget.jsonl')
        if not path.exists():path=root/'evidence/campaign'/(name+'-budget.jsonl')
        raw=path.read_bytes()
        if not raw.endswith(b'\n'):raise ValueError('budget snapshot interrupted; rerun after writer finishes')
        events=[json.loads(line) for line in raw.decode().splitlines()]
        sources['campaign/'+name+'-budget.jsonl']=sha(path)
        if name=='cloud':
            cap=events[0]['cap_usd'];used=next((e['reserved_total_usd'] for e in reversed(events) if 'reserved_total_usd' in e),'0')
            budgets[name]={'cap_usd':cap,'reserved_usd':used,'remaining_reserved_usd':str(Decimal(cap)-Decimal(used)),
                           'meaning':'Conservative reserved upper bounds, not actual provider spend.',
                           'halted':any(e['event']=='halt' for e in events)}
        else:
            cap=events[0]['cap_seconds'];used=next((e['used_seconds'] for e in reversed(events) if 'used_seconds' in e),'0')
            pending=set()
            for event in events:
                if event['event']=='reserve':pending.add(event['key'])
                if event['event']=='complete':pending.discard(event['key'])
            budgets[name]={'cap_seconds':cap,'charged_seconds':used,'pending_reservations':len(pending),
                           'halted':any(e['event']=='halt' or e.get('halted') is True for e in events)}
    if Decimal(budgets['cloud']['reserved_usd'])!=Decimal(receipt['cloud']['reserved_usd']):raise ValueError('budget receipt does not match cloud ledger')
    if Decimal(budgets['local']['charged_seconds'])!=Decimal(receipt['local']['charged_seconds']):raise ValueError('budget receipt does not match local ledger')
    if held:
        for name in ('freeze.json','thresholds.json'):
            if held['phase_locks'][name]!=sources['campaign/v002-frozen/'+name]:raise ValueError('heldout report lock mismatch')
        if held['source_commit']!=freeze['settings']['source_commit']:raise ValueError('heldout source commit mismatch')
    return {'schema':1,'development':reports,'local':local,'memory':memory,'review':review,
        'calibration':calibration,'threshold_selection':thresholds,'budget_receipt':receipt,'operator_blinding_note':BLINDING_NOTE,
        'heldout':held,'frozen_source_commit':freeze['settings']['source_commit'],
        'frozen_settings':freeze['settings'],'budgets':budgets,'sources_sha256':sources,
        'actual_net_tokens_saved':None,'paired_task_success':None,
        'presentation_generator_sha256':sha(__file__)}


def log_rows(value):
    runs=[(v['tag'],v['report']) for v in value['development']]+[('local-incomplete',value['local']),('calibration-selection',value['calibration'])]
    if value['heldout']:runs.append(('heldout',value['heldout']))
    rows=[]
    for version,r in runs:
        for arm,a in r['arms'].items():
            raw=overall(a,'raw');enforced=overall(a);resources=a['resources_all_attempts'];times=latency(a)
            rows.append({'version':version,'phase':r['split'],'evidence_kind':r['evidence_kind'],
                'source_commit':r['source_commit'],'dataset_sha256':r['dataset_sha256'],
                'prompt_version':r.get('prompt_version'),'policy':r['policy'],'arm':arm,'model':a['model'],
                'settings':json.dumps(r.get('settings'),sort_keys=True),'threshold':json.dumps(r['threshold'],sort_keys=True),
                'scoring_note':'Calibration actions use a null threshold; see thresholds.json for selected operating points.' if r['split']=='calibration' else '',
                'planned_unique':r['n_unique_planned'],'observed_primary':a['primary_observed_n'],
                'raw_safe':raw['safe_skips'],'raw_eligible':raw['skip_eligible'],
                'raw_unsafe':raw['unsafe_skips'],'raw_prohibited':raw['non_skippable'],
                'enforced_safe':enforced['safe_skips'],'enforced_eligible':enforced['skip_eligible'],
                'enforced_unsafe':enforced['unsafe_skips'],'enforced_prohibited':enforced['non_skippable'],
                'all_attempts':resources['attempts'],'retries':a['retries'],
                'request_latency_n':times['n'],'request_p50_ms':times['p50_ms'],'request_p95_ms':times['p95_ms'],
                'mixed_policy_p50_ms':a['primary_latency']['p50_ms'],
                'native_input_tokens':resources['input_tokens']['total'],'native_output_tokens':resources['output_tokens']['total'],
                'estimated_usd':resources['estimated_usd']['total'],'reported_usd':resources['reported_usd']['total'],
                'net_input_proxy_saved':proxy(a).get('net_input_proxy_tokens_saved'),
                'actual_net_token_savings':None,'task_success':None,'complete':r['complete_from_evidence'],
                'stopped':r['stopped'],'repeat_complete_unique':a['repeat_stability']['complete_unique'],
                'repeat_raw_changed':a['repeat_stability']['raw_changed_cases'],
                'repeat_enforced_changed':a['repeat_stability']['enforced_changed_cases']})
    return rows


def coverage_svg(value):
    runs=value['development'];parts=['<svg viewBox="0 0 800 315" role="img" aria-label="Development safe coverage; matched cases and visible regression">']
    for pct in (0,50,100):
        y=235-pct*1.8;parts.append(f'<line x1="90" y1="{y}" x2="720" y2="{y}" stroke="#35413b"/><text x="20" y="{y+5}" fill="#98a59d">{pct}%</text>')
    baseline=runs[0]['report']['baselines']['deterministic']['overall']['safe_skip_coverage'];y=235-baseline*180
    parts.append(f'<line x1="90" y1="{y}" x2="720" y2="{y}" stroke="#738779" stroke-dasharray="5 6"/><text x="440" y="{y+22}" fill="#91a694" font-size="12">Deterministic baseline {percent(baseline)}</text>')
    for arm in ('jev','chat'):
        coords=[]
        for i,run in enumerate(runs):
            m=overall(run['report']['arms'][arm]);x=130+i*270;y=235-m['safe_skip_coverage']*180;coords.append(f'{x},{y}')
        parts.append(f'<polyline points="{" ".join(coords)}" fill="none" stroke="{COLORS[arm]}" stroke-width="3"/>')
        for i,run in enumerate(runs):
            m=overall(run['report']['arms'][arm]);x=130+i*270;y=235-m['safe_skip_coverage']*180
            dy=23 if arm=='jev' else -16
            parts.append(f'<circle cx="{x}" cy="{y}" r="5" fill="{COLORS[arm]}"/><text x="{x}" y="{y+dy}" text-anchor="middle" fill="{COLORS[arm]}">{NAMES[arm]} {ratio(m)}</text>')
    for i,run in enumerate(runs):parts.append(f'<text x="{130+i*270}" y="285" text-anchor="middle" fill="#dee8df">{run["tag"]} · {esc(run["report"].get("prompt_version"))}</text>')
    return ''.join(parts)+'</svg>'


def proxy_bars(value):
    items=[(run['tag']+' / '+NAMES[arm],proxy(a).get('net_input_proxy_tokens_saved'),COLORS[arm])
           for run in value['development'] for arm,a in run['report']['arms'].items()]
    if value['heldout']:
        items += [('Held-out / '+NAMES[arm],proxy(a).get('net_input_proxy_tokens_saved'),COLORS[arm]) for arm,a in value['heldout']['arms'].items()]
    maximum=max([abs(v) for n,v,c in items if v is not None]+[1]);out=[]
    for name,v,color in items:
        if v is None:bar='<span class="unknown">Unknown</span>'
        else:
            side='right' if v<0 else 'left'
            bar=f'<div class="signed"><i style="{side}:50%;width:{abs(v)/maximum*50:.2f}%;background:{color}"></i></div>'
        out.append(f'<div class="proxyrow"><span>{esc(name)}</span>{bar}<b>{num(v)}</b></div>')
    return ''.join(out)


def performance_table(report,baselines=False):
    rows=[]
    if baselines:
        for name in ('read_everything','deterministic'):
            m=report['baselines'][name]['overall'];label={'read_everything':'Read everything','deterministic':'Deterministic rules'}[name]
            rows.append(f'<tr><th>{label}</th><td>{ratio(m)}</td><td>—</td><td>{ratio(m,"unsafe_skips","non_skippable")}</td><td>Unknown<small>baseline execution unmeasured</small></td><td>0 routing calls</td><td>Unknown<small>end-to-end cost</small></td></tr>')
    for arm,a in report['arms'].items():
        raw=overall(a,'raw');m=overall(a);t=latency(a);r=a['resources_all_attempts']
        rows.append(f'<tr><th>{NAMES[arm]}</th><td>{ratio(m)}</td><td>{ratio(raw,"unsafe_skips","non_skippable")}</td><td>{ratio(m,"unsafe_skips","non_skippable")}</td><td>{num(t["p50_ms"],1)} / {num(t["p95_ms"],1)}<small>{t["n"]} primary requests</small></td><td>{r["attempts"]}</td><td>{money(r["estimated_usd"]["total"])}<small>reported {money(r["reported_usd"]["total"])}</small></td></tr>')
    if baselines:rows.append('<tr><th>Local scoring</th><td>Unknown</td><td>Unknown</td><td>Unknown</td><td>Unknown</td><td>0 test calls</td><td>Unknown<small>resource stop; not evaluated</small></td></tr>')
    return '<div class="scroll"><table><thead><tr><th>Arm</th><th>Safe / eligible</th><th>Raw unsafe</th><th>Enforced unsafe</th><th>Request wall p50 / p95 ms</th><th>All attempts</th><th>All-attempt estimated cost</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></div>'


def heldout_svg(value):
    r=value['heldout'];items=[('Read everything',r['baselines']['read_everything']['overall'],'#66776b'),('Deterministic rules',r['baselines']['deterministic']['overall'],'#819386')]
    items += [(NAMES[arm]+' + enforcement',overall(r['arms'][arm]),COLORS[arm]) for arm in ('chat','jev')]
    out=['<svg viewBox="0 0 900 270" role="img" aria-label="Held-out eligible skip coverage; Jev plus enforcement versus simple baselines">']
    for i,(name,m,color) in enumerate(items):
        y=35+i*57;out.append(f'<text x="0" y="{y+15}" fill="#dce6dc" font-size="15">{name}</text><rect x="245" y="{y}" width="515" height="23" fill="#111713" rx="3"/><rect x="245" y="{y}" width="{515*m["safe_skip_coverage"]}" height="23" fill="{color}" rx="3"/><text x="780" y="{y+17}" fill="{color}" font-size="16">{ratio(m)}</text>')
    out.append('<text x="245" y="262" fill="#98a59d" font-size="12">Safe skips / eligible cases · observed synthetic fixture outcomes</text></svg>')
    return ''.join(out)


def threshold_note(value):
    held=value['heldout'];selected=value['threshold_selection'];cal=value['calibration']
    if not held:return 'Threshold selection is recorded separately from test outcomes.'
    chat=held['arms']['chat'];sem=chat['enforced']['kinds']['semantic'];jev=held['arms']['jev']['enforced']['kinds']['semantic']
    return (f'The prespecified selection rule was: {selected["rule"]}. Calibration raw unsafe recommendations were '
            f'{ratio(overall(cal["arms"]["chat"],"raw"),"unsafe_skips","non_skippable")} for chat and '
            f'{ratio(overall(cal["arms"]["jev"],"raw"),"unsafe_skips","non_skippable")} for Jev. '
            f'The selected operating thresholds were chat {selected["arms"]["chat"]["threshold"]:.2f} and Jev {selected["arms"]["jev"]["threshold"]:.2f}. '
            f'On held-out cases, the chat threshold rejected its {overall(chat,"raw")["unsafe_skips"]} unsafe recommendations, but also rejected all '
            f'{overall(chat,"raw")["safe_skips"]} correct semantic skip recommendations: enforced coverage {ratio(sem)}. '
            f'Jev retained {ratio(jev)} semantic coverage. Threshold selection is not probability calibration; no post-test retuning occurred.')


def heldout_section(value):
    r=value['heldout']
    if r is None:return '<div class="pending"><b>Held-out evidence pending</b><p>No test result has been imported into this presentation. Development outcomes are exploratory.</p></div>'
    families=[];repeats=[];paired=[]
    for arm,a in r['arms'].items():
        for family,m in a['enforced']['families'].items():families.append(f'<tr><td>{NAMES[arm]}</td><td>{esc(family)}</td><td>{m["n_unique"]}</td><td>{ratio(m)}</td><td>{ratio(m,"unsafe_skips","non_skippable")}</td></tr>')
        s=a['repeat_stability'];repeats.append(f'<li>{NAMES[arm]}: {s["complete_unique"]}/{s["planned_unique"]} complete repeated cases; changed raw {num(s["raw_changed_cases"])}, enforced {num(s["enforced_changed_cases"])}.</li>')
    for name,p in r['paired'].items():
        if 'deterministic' in name or ('chat' in name and 'jev' in name):
            paired.append(f'<li>{esc(name)}: matched n={p["n_unique_matched"]}; right-minus-left safe skips {p["safe_skips_difference"]:+}; unsafe skips {p["unsafe_skips_difference"]:+}; mixed-policy paired median latency difference {num(p["median_latency_difference_ms"],1)} ms. Mixed-policy mean latency family-bootstrap interval: {esc(p["mean_latency_difference_family_bootstrap_95"])}. These paired times include bypasses; they are not model inference timings.</li>')
    return f'<p>{r["n_unique_planned"]} unique held-out cases. Thresholds were frozen from calibration before test; repeats do not increase the unique sample size. Raw model denominators exclude deterministic bypasses. Costs include repeats; coverage and request latency use primary observations.</p><div class="panel">{heldout_svg(value)}</div>'+performance_table(r,baselines=True)+f'<p class="note">{esc(threshold_note(value))}</p><p class="note">{esc(BLINDING_NOTE)}</p><details><summary>Family results, paired uncertainty, and repeats</summary><div class="scroll"><table><tr><th>Arm</th><th>Family</th><th>n</th><th>Safe / eligible</th><th>Unsafe / prohibited</th></tr>{"".join(families)}</table></div><ul>{"".join(paired)}</ul><ul>{"".join(repeats)}</ul><p>Whole-family intervals are exploratory with few authored families. Degenerate zero-error intervals do not establish zero population risk. Model-assisted semantic results cover only two test families. Request wall timings include driver overhead.</p></details>'


def local_matched(value):
    local=value['local'];cloud=value['development'][0]['report']
    if local['dataset_sha256']!=cloud['dataset_sha256'] or local['prompt_version']!=cloud['prompt_version']:raise ValueError('local/cloud comparison is not matched')
    completed=[o for o in local['arms']['local']['observations'] if o['trial']==1 and o['resources'].get('local_telemetry_sources')]
    ids={o['case_id'] for o in completed};result={}
    for arm,a in {**cloud['arms'],'local':local['arms']['local']}.items():
        rows=[o for o in a['observations'] if o['trial']==1 and o['case_id'] in ids]
        if len(rows)!=len(ids) or any(not o['observed'] for o in rows):raise ValueError('missing matched local/cloud observation')
        eligible=sum(o['expected']=='skip' for o in rows);times=[o['end_to_end_ms'] for o in rows]
        result[arm]={'n':len(rows),'model':a['model'],'safe_skips':sum(o['expected']=='skip' and o['action']=='skip' for o in rows),
            'skip_eligible':eligible,'non_skippable':len(rows)-eligible,
            'unsafe_skips':sum(o['expected']!='skip' and o['action']=='skip' for o in rows),
            'raw_unsafe':sum(o['expected']!='skip' and o['raw_action']=='skip' for o in rows),
            'p50_ms':quantile(times,.5),'p95_ms':quantile(times,.95),
            'native_input_tokens':sum(o['resources']['input_tokens']['total'] for o in rows),
            'native_output_tokens':sum(o['resources']['output_tokens']['total'] for o in rows),
            'cold_requests':sum(o['resources'].get('cold_requests',0) for o in rows),
            'load_p50_ms':quantile([o['resources']['load_ms']['p50_ms'] for o in rows if 'load_ms' in o['resources']],.5)}
    return {'scope':'Completed local development intersection only; resource-selected and incomplete, not full-study evidence. Native tokens use different model tokenizers.',
        'case_ids':sorted(ids),'prompt_version':local['prompt_version'],'dataset_sha256':local['dataset_sha256'],'arms':result}


def local_table(value):
    matched=local_matched(value);rows=[]
    for arm,m in matched['arms'].items():
        rows.append(f'<tr><th>{NAMES[arm]}</th><td>{ratio(m)}</td><td>{m["raw_unsafe"]}/{m["non_skippable"]} → {ratio(m,"unsafe_skips","non_skippable")}</td><td>{num(m["p50_ms"],1)} / {num(m["p95_ms"],1)}</td><td>{m["native_input_tokens"]} / {m["native_output_tokens"]}</td></tr>')
    return f'<details><summary>Matched local vs. cloud: {len(matched["case_ids"])} completed development cases only</summary><p>These case identities and v1 prerequisite inputs match D1. The seventh journaled local result was a resource failure; it is excluded here, retained as missing model evidence in the full run, and never assigned zero latency. This resource-selected intersection does not complete the five-arm evaluation.</p><div class="scroll"><table><tr><th>Arm</th><th>Safe / eligible</th><th>Raw → enforced unsafe</th><th>Request wall p50 / p95 ms</th><th>Native input / output tokens</th></tr>{"".join(rows)}</table></div><p>Local: {matched["arms"]["local"]["cold_requests"]} cold requests, load-duration p50 {num(matched["arms"]["local"]["load_p50_ms"],1)} ms. No warm throughput result. Native tokens use different model tokenizers; compare the common proxy separately. Baseline execution latency and local energy cost are unknown.</p></details>'


def html_page(value):
    dev=value['development'];first=dev[0]['report'];second=dev[1]['report'];last=dev[2]['report']
    before=second['arms']['jev']['resources_all_attempts']['attempts'];after=last['arms']['jev']['resources_all_attempts']['attempts']
    avoided=before-after;reduction=avoided/before
    local=value['local']['arms']['local'];local_resources=local['resources_all_attempts']
    memory=value['memory'];review=value['review'];reviewed=review['total_reviewed'];agreements=sum(v['agreements'] for v in review['by_split'].values())
    rows=[]
    for item in dev:
        r=item['report'];cells=[]
        for arm in ('jev','chat'):
            a=r['arms'][arm];m=overall(a);raw=overall(a,'raw');sem=a['enforced']['kinds'].get('semantic',{})
            cells.append(f'<td>{ratio(m)}<small>semantic {ratio(sem) if sem else "Unknown"}</small></td><td>{ratio(raw,"unsafe_skips","non_skippable")} → {ratio(m,"unsafe_skips","non_skippable")}</td>')
        rows.append(f'<tr><th>{item["tag"]}<small>{esc(item["title"])}</small></th>{"".join(cells)}</tr>')
    memory_rows=[]
    for arm in ('no_memory','exact_cache','token_jaccard','stock_calyx_flylsh'):
        m=memory['metrics'][arm]
        label={'no_memory':'No memory','exact_cache':'Exact cache','token_jaccard':'Token similarity','stock_calyx_flylsh':'Calyx FlyLSH'}[arm]
        memory_rows.append(f'<tr><th>{label}</th><td>{m["candidate_hits"]}/{m["queries"]}</td><td>{m["false_action_reuses"]}</td><td>{m["raw_unsafe_skips"]}/{memory["counts"]["non_skippable_queries"]}</td><td>{m["enforced_unsafe_skips"]}/{memory["counts"]["non_skippable_queries"]}</td><td>{m["safe_enforced_skips"]}/{memory["counts"]["skip_eligible_queries"]}</td><td>{num(m["per_query_median_p50_ms"],4)}</td></tr>')
    failure=next((f for f in first['failures'] if f['arm']=='chat' and f['raw_action']=='skip' and f['expected']!='skip'),None)
    regression=next((o for o in last['arms']['jev']['observations'] if o['trial']==1 and o['expected']=='skip' and o['action']!='skip'),None)
    local_note=f'{local_resources["attempts"]} journaled attempts; {len(local_resources.get("local_telemetry_sources",[]))} have model telemetry. {local["primary_missing_n"]} planned observations missing. Stopped: {value["local"]["stopped"]}.'
    budget=value['budgets'];test_status='held-out evidence included' if value['heldout'] else 'held-out evidence pending'
    receipt=value['budget_receipt'];held=value['heldout']
    hero_metric=(f'<b>{ratio(overall(held["arms"]["jev"]))}</b><span>Jev held-out safe skips; deterministic {ratio(held["baselines"]["deterministic"]["overall"])}</span>' if held else f'<b>{percent(reduction)}</b><span>fewer development requests in D3</span>')
    hero_delta=(f'<b>+{overall(held["arms"]["jev"])["safe_skips"]-held["baselines"]["deterministic"]["overall"]["safe_skips"]}</b><span>eligible skips over deterministic rules; {ratio(overall(held["arms"]["jev"]),"unsafe_skips","non_skippable")} enforced unsafe observed</span>' if held else f'<b>{ratio(overall(last["arms"]["jev"]))}</b><span>D3 Jev coverage, with one regression</span>')
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Aldertrace — evidence before autonomy</title><style>
    :root{{color-scheme:dark;--bg:#111713;--panel:#19211c;--ink:#eef1e8;--muted:#a2afa3;--line:#354239;--green:#b4dd8f;--purple:#bdb5fa;--warm:#f1bf83}}*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 system-ui,sans-serif}}a{{color:var(--green);text-decoration:none}}a:hover{{text-decoration:underline}}main{{max-width:1200px;padding:36px 30px 80px;margin:auto}}header{{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--line);padding-bottom:24px;font-size:12px;letter-spacing:2px}}.brand{{font-size:19px;font-weight:700;letter-spacing:3px}}.mark{{display:inline-block;width:17px;height:23px;border-left:4px solid var(--green);border-right:4px solid var(--green);transform:skew(-17deg);margin-right:15px}}.hero{{padding:68px 0 36px;display:grid;grid-template-columns:1.5fr 1fr;gap:52px}}.eyebrow{{font-size:12px;text-transform:uppercase;letter-spacing:2px;color:var(--green)}}h1{{font-size:clamp(42px,6vw,75px);line-height:1.03;letter-spacing:-3.5px;margin:20px 0 28px;max-width:760px}}h1 em{{font-style:normal;color:var(--green)}}h2{{font-size:29px;line-height:1.2;letter-spacing:-.6px;margin:6px 0 18px}}h3{{font-size:18px;margin:10px 0}}p{{color:var(--muted);margin:12px 0;max-width:820px}}.lede{{font-size:20px;line-height:1.5;max-width:650px}}.badges{{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0}}.badge{{border:1px solid var(--line);border-radius:40px;padding:5px 11px;font-size:12px;color:var(--muted)}}.decision{{background:var(--panel);padding:27px;border:1px solid var(--line);border-top:3px solid var(--green);border-radius:5px;align-self:center}}.decision strong{{font-size:22px;line-height:1.4;display:block;margin:16px 0}}.decision small{{display:block;color:var(--muted)}}.metrics{{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin:14px 0 42px}}.metric{{padding:23px;border:1px solid var(--line);border-radius:6px}}.metric b{{display:block;font-size:35px;letter-spacing:-1px}}.metric span{{font-size:13px;color:var(--muted)}}section{{border-top:1px solid var(--line);padding:37px 0;margin-top:18px}}.sectionhead{{display:grid;grid-template-columns:65px 1fr;gap:12px}}.sectionno{{font-family:ui-monospace,monospace;color:var(--green);font-size:18px;padding-top:4px}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:24px}}.panel{{border:1px solid var(--line);border-radius:8px;background:var(--panel);padding:24px;margin:18px 0}}.panel svg{{width:100%;height:auto}}.legend{{display:flex;gap:20px;font-size:13px;color:var(--muted)}}.dot{{width:9px;height:9px;border-radius:50%;display:inline-block;margin-right:6px}}.note{{border-left:3px solid var(--warm);padding-left:16px;margin:23px 0;color:var(--muted);font-size:14px}}.scroll{{overflow:auto}}table{{width:100%;border-collapse:collapse;font-size:13px}}th,td{{padding:13px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;white-space:normal}}th{{font-weight:600}}td{{font-variant-numeric:tabular-nums}}small{{display:block;font-size:11px;color:var(--muted);font-weight:400;max-width:230px}}.proxyrow{{display:grid;grid-template-columns:115px 1fr 76px;gap:12px;align-items:center;margin:14px 0;font-size:13px}}.proxyrow b{{text-align:right}}.signed{{position:relative;height:13px;background:linear-gradient(90deg,#111713 49.6%,#768477 49.6%,#768477 50.4%,#111713 50.4%);border-radius:2px}}.signed i{{position:absolute;height:100%;display:block}}.unknown{{color:var(--warm)}}details{{margin-top:25px;border:1px solid var(--line);padding:18px;border-radius:6px}}summary{{cursor:pointer;color:var(--green);font-weight:600}}details p,details li{{font-size:13px}}.pending{{border:1px dashed #687967;padding:24px;border-radius:6px}}.failuregrid{{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}}.failure{{border:1px solid var(--line);border-radius:6px;padding:22px;background:var(--panel)}}.failure h3{{font-size:17px}}.failure p{{font-size:13px}}.flow{{font-family:ui-monospace,monospace;color:var(--green);font-size:13px;margin:14px 0}}.foot{{color:var(--muted);font-size:12px;overflow-wrap:anywhere}}.downloads{{display:flex;flex-wrap:wrap;gap:12px;margin:22px 0}}.button{{border:1px solid var(--green);padding:8px 14px;border-radius:4px;font-size:13px}}ul{{color:var(--muted)}}code{{font-size:12px;overflow-wrap:anywhere}}@media(max-width:800px){{main{{padding:20px 16px 50px}}.hero,.grid{{grid-template-columns:1fr;gap:18px}}.hero{{padding-top:36px}}.failuregrid{{grid-template-columns:1fr}}h1{{letter-spacing:-2px}}header{{font-size:10px;gap:20px}}.metrics{{gap:8px}}.metric{{padding:14px}}.metric b{{font-size:25px}}.sectionhead{{grid-template-columns:40px 1fr}}.panel{{padding:15px}}.proxyrow{{grid-template-columns:100px 1fr 65px;font-size:12px}}}}
    </style></head><body><main><header><div class="brand"><i class="mark"></i>ALDERTRACE</div><div>STUDY 002 / PRIVATE RESEARCH PREVIEW</div></header>
    <div class="hero"><div><div class="eyebrow">Evidence before autonomy</div><h1>Measure the route.<br><em>Enforce the evidence.</em></h1><p class="lede">A recommendation can become more useful without becoming cheaper. This study keeps those outcomes separate.</p><div class="badges"><span class="badge">Synthetic cases</span><span class="badge">Provisional labels</span><span class="badge">{test_status}</span></div></div><aside class="decision"><div class="eyebrow">Current recommendation</div><strong>Keep deterministic evidence checks.<br>Further-test semantic routing.</strong><p>Do not claim net token savings or full-task reliability from this evidence. Similarity is a retrieval hint, not proof.</p><small>All figures below are generated from versioned JSON evidence. No hand-entered performance numbers.</small></aside></div>
    <div class="metrics"><div class="metric"><b>{percent(reduction)}</b><span>fewer development cloud requests in D3 ({before} → {after} per arm)</span></div><div class="metric"><b>{ratio(overall(last['arms']['jev']))} / {ratio(overall(last['arms']['chat']))}</b><span>D3 eligible skips: Jev / chat; Jev lost one vs. D2</span></div><div class="metric"><b class="unknown">Unknown</b><span>actual net token reduction and paired full-task success</span></div></div>
    <section><div class="sectionhead"><div class="sectionno">01</div><div><h2>Instructions changed the recommendation.</h2><p>Three documented development versions used the same {first['n_unique_planned']} cases. D2 clarified what satisfies a semantic prerequisite. D3 let deterministic rules resolve executable checks before calling a model.</p></div></div><div class="panel">{coverage_svg(value)}<div class="legend"><span><i class="dot" style="background:var(--green)"></i>Jev enforced coverage</span><span><i class="dot" style="background:var(--purple)"></i>Chat enforced coverage</span></div></div><div class="scroll"><table><tr><th>Version</th><th>Jev safe / eligible</th><th>Jev raw → enforced unsafe</th><th>Chat safe / eligible</th><th>Chat raw → enforced unsafe</th></tr>{''.join(rows)}</table></div><p class="note">D3 preserved chat coverage but Jev fell from {ratio(overall(second['arms']['jev']))} to {ratio(overall(last['arms']['jev']))}. The regression remains in the evidence. Reusing the same development cases does not create independent samples. Raw denominators in D3 cover model-eligible semantic cases only.</p></section>
    <section><div class="sectionhead"><div class="sectionno">02</div><div><h2>Fewer calls still did not pay for routing.</h2><p>The proxy subtracts full observable routing inputs from safely avoided guide tokens. Every primary retry counts. Hidden provider serialization prevents this proxy from establishing actual savings.</p></div></div><div class="grid"><div class="panel"><h3>Net input proxy saved</h3><p style="font-size:13px">Negative values mean more input overhead than guide tokens avoided. Zero is the center line.</p>{proxy_bars(value)}<p class="unknown">Actual net tokens: unknown. This is not H1 confirmation.</p></div><div class="panel"><h3>D3: request latency and cost</h3><p style="font-size:13px">Request-only timings exclude deterministic bypasses. The mixed policy median is not Jev or chat inference latency.</p>{performance_table(last)}<p style="font-size:12px">Cost includes all attempts in this run. Jev monetary charges are estimates; provider-reported totals remain unknown. Native input/output totals are in the experiment log.</p></div></div></section>
    <section><div class="sectionhead"><div class="sectionno">03</div><div><h2>Held-out evaluation stays separate.</h2><p>Frozen routing source: <code>{esc(value['frozen_source_commit'])}</code>. No tuning follows held-out outcomes. A later experiment needs a new version and fresh evaluation cases.</p></div></div>{heldout_section(value)}</section>
    <section><div class="sectionhead"><div class="sectionno">04</div><div><h2>Memory retrieved matches. Rules supplied permission.</h2><p>Separate preliminary mechanism ablation: {memory['counts']['unique_queries']} queries over {memory['counts']['history_records']} fixed history records. Calyx FlyLSH used its stock hashing mechanism; persistent memory, reinforcement and MCP overhead were not exercised.</p></div></div><div class="scroll"><table><tr><th>Memory arm</th><th>Hits</th><th>False action reuse</th><th>Raw unsafe</th><th>Enforced unsafe</th><th>Safe / eligible</th><th>Per-query median p50 ms</th></tr>{''.join(memory_rows)}</table></div><p class="note">The deterministic reference already resolved {memory['deterministic_reference']['gate_action_matches']}/{memory['counts']['unique_queries']} cases with {memory['deterministic_reference']['model_calls_required_for_this_fixture']} model calls. Retrieval hits are hypothetical fallback avoidance, not measured model or token savings. Timing repetitions do not increase the {memory['counts']['unique_queries']}-query sample. This does not establish Calyx product efficacy.</p></section>
    <section><div class="sectionhead"><div class="sectionno">05</div><div><h2>Failures are part of the demonstration.</h2></div></div><div class="failuregrid"><article class="failure"><div class="eyebrow">Machine evidence</div><h3>A plausible skip was rejected.</h3><div class="flow">{esc(failure['raw_action'] if failure else 'unknown')} → {esc(failure['action'] if failure else 'unknown')}</div><p>{esc(failure['rationale'] if failure else 'No representative failure available.')}</p><small>{esc(failure['case_id'] if failure else '')} · development</small></article><article class="failure"><div class="eyebrow">Semantic variation</div><h3>Jev lost one eligible skip.</h3><div class="flow">expected skip → {esc(regression['action'] if regression else 'unknown')}</div><p>Prompt v2 stayed fixed between D2 and D3. The changed recommendation is observed variation; this experiment does not isolate its cause.</p><small>{esc(regression['case_id'] if regression else '')} · development</small></article><article class="failure"><div class="eyebrow">Local resource boundary</div><h3>Incomplete means incomplete.</h3><p>{esc(local_note)}</p><p>Cold-load telemetry is separate. These partial observations are not a matched complete local comparison.</p></article></div></section>
    <section><div class="sectionhead"><div class="sectionno">06</div><div><h2>Reproduce the result, including its limits.</h2><p>{agreements}/{reviewed} labels agreed in a blind separate-agent review. This was not human adjudication or an independent external assessment. All efficacy results remain provisional.</p></div></div><div class="grid"><div><h3>Budget snapshot</h3><p>Cloud reservations: {money(budget['cloud']['reserved_usd'])} / {money(budget['cloud']['cap_usd'])}. Reservations are conservative bounds, not actual billing.<br>Local allowance charged: {num(budget['local']['charged_seconds'],2)} / {num(budget['local']['cap_seconds'])} seconds.</p><p class="foot">No purchases, auto-recharge or new inference are performed by this artifact generator.</p></div><div><h3>Acceptance boundaries</h3><ul><li>20% actual net-token target: unresolved; public-input proxy is negative.</li><li>Semantic coverage must be considered with unsafe skips, families, and provisional labels.</li><li>Full-task success and end-to-end pilot: not measured.</li><li>Game-AI remains a separate future experiment.</li></ul></div></div><div class="downloads"><a class="button" href="REPORT.md">Research report</a><a class="button" href="EXPERIMENT_LOG.csv">Experiment log</a><a class="button" href="evidence.json">Evidence JSON</a><a class="button" href="MANIFEST.json">Artifact hashes</a></div><p class="foot">Public serialization proxy uses a frozen tokenizer; no byte-to-token conversion. Request repeats and correlated families are not treated as independent evidence. Source inputs and this generator are hash-bound in the manifest.</p></section></main></body></html>'''


def markdown(value):
    out=['# Aldertrace: evidence before autonomy','',
         'Provisional synthetic research. This report is generated from scored JSON artifacts; no inference is performed.',
         '', '**Recommendation:** retain deterministic prerequisite enforcement; further-test semantic routing without claiming net savings. Do not adopt similarity as proof. The paired full-task pilot remains unmeasured.',
         '', '## Development comparison','',
         f'The three versions reuse the same {value["development"][0]["report"]["n_unique_planned"]} cases. D1 uses original instructions; D2 clarifies semantic evidence; D3 keeps D2 instructions and resolves executable checks deterministically before model calls. These are development iterations, not independent samples. Development definitions record a base commit plus implementation hashes; the base commit alone does not identify the uncommitted development source.','',
         '| Run / arm | Safe / eligible | Raw unsafe | Enforced unsafe | Calls | Request p50 / p95 ms | Estimated / reported cost | Net input proxy saved |',
         '|---|---:|---:|---:|---:|---:|---:|---:|']
    for run in value['development']:
        for arm,a in run['report']['arms'].items():
            m=overall(a);raw=overall(a,'raw');r=a['resources_all_attempts'];t=latency(a)
            out.append(f'| {run["tag"]} / {NAMES[arm]} | {ratio(m)} | {ratio(raw,"unsafe_skips","non_skippable")} | {ratio(m,"unsafe_skips","non_skippable")} | {r["attempts"]} | {num(t["p50_ms"],1)} / {num(t["p95_ms"],1)} | {money(r["estimated_usd"]["total"])} / {money(r["reported_usd"]["total"])} | {num(proxy(a).get("net_input_proxy_tokens_saved"))} |')
    out += ['', f'D3 retained chat coverage but Jev declined from {ratio(overall(value["development"][1]["report"]["arms"]["jev"]))} to {ratio(overall(value["development"][2]["report"]["arms"]["jev"]))} eligible skips. This regression remains visible. Raw model denominators exclude deterministic bypasses in D3. Request-only latency excludes those bypasses; a mixed policy median is not model latency.',
            '', 'The input proxy counts exact guides and observable public requests with a frozen tokenizer, including primary retries. It preserves negative outcomes. Hidden provider serialization remains unknown, so actual net-token reduction and H1 remain unknown. No full-task success or H3 measurement exists.',
            '', '## Held-out evaluation','']
    held=value['heldout']
    if held is None:out.append('Pending: no held-out result was imported. No held-out efficacy claim is supported by this report.')
    else:
        out += [f'Frozen source commit: `{value["frozen_source_commit"]}`. Unique test cases: {held["n_unique_planned"]}. Thresholds: `{json.dumps(held["threshold"],sort_keys=True)}`. Labels remain provisional.', '',
                '| Arm | Safe / eligible | Raw unsafe | Enforced unsafe | Semantic safe / eligible | Repeat raw / enforced changed |',
                '|---|---:|---:|---:|---:|---:|']
        for arm,a in held['arms'].items():
            m=overall(a);raw=overall(a,'raw');sem=a['enforced']['kinds'].get('semantic',{});s=a['repeat_stability']
            out.append(f'| {NAMES[arm]} | {ratio(m)} | {ratio(raw,"unsafe_skips","non_skippable")} | {ratio(m,"unsafe_skips","non_skippable")} | {ratio(sem) if sem else "Unknown"} | {num(s["raw_changed_cases"])} / {num(s["enforced_changed_cases"])} among {s["complete_unique"]} repeated cases |')
        for name in ('read_everything','deterministic'):
            m=held['baselines'][name]['overall'];out.append(f'| {name} | {ratio(m)} | — | {ratio(m,"unsafe_skips","non_skippable")} | 0/{held["arms"]["jev"]["enforced"]["kinds"]["semantic"]["skip_eligible"]} | Deterministic by construction, not timed |')
        out.append('| Local scoring | Unknown | Unknown | Unknown | Unknown | Not executed after resource stop |')
        out += ['',threshold_note(value),'',BLINDING_NOTE,'',
                '| Test arm | Primary requests | Request wall p50 / p95 ms | All attempts incl. repeats | Native input / output | Estimated / reported cost | Net input proxy saved |',
                '|---|---:|---:|---:|---:|---:|---:|']
        for arm,a in held['arms'].items():
            t=latency(a);r=a['resources_all_attempts'];out.append(f'| {NAMES[arm]} | {t["n"]} | {num(t["p50_ms"],1)} / {num(t["p95_ms"],1)} | {r["attempts"]} | {r["input_tokens"]["total"]} / {r["output_tokens"]["total"]} | {money(r["estimated_usd"]["total"])} / {money(r["reported_usd"]["total"])} | {num(proxy(a).get("net_input_proxy_tokens_saved"))} |')
        out += ['', 'The net input proxy covers primary observations including their retries. Native usage and cost cover every attempt, including repeats. Request wall time includes driver overhead and excludes bypasses. Baseline runtime and end-to-end cost are unknown.', '',
                '| Test family | Jev safe / eligible | Chat safe / eligible | Jev / chat enforced unsafe |',
                '|---|---:|---:|---:|']
        for family,j in held['arms']['jev']['enforced']['families'].items():
            c=held['arms']['chat']['enforced']['families'][family];out.append(f'| {family} | {ratio(j)} | {ratio(c)} | {ratio(j,"unsafe_skips","non_skippable")} / {ratio(c,"unsafe_skips","non_skippable")} |')
        p=held['paired']['chat -> jev'];out += ['',f'Paired Jev minus chat: {p["safe_skips_difference"]:+} safe skips, {p["safe_coverage_difference"]*100:+.1f} percentage points, {p["unsafe_skips_difference"]:+} enforced unsafe skips on {p["n_unique_matched"]} matched unique cases. Paired mixed-policy median latency difference {num(p["median_latency_difference_ms"],1)} ms; mean-latency whole-family bootstrap interval {p["mean_latency_difference_family_bootstrap_95"]} ms. This timing comparison includes bypasses and must not be read as inference latency.',
                '', 'Family and paired results are preserved in `evidence.json`. Whole-family bootstrap uncertainty is exploratory with four authored test families, only two semantic families. Repeats do not increase the unique sample size. Zero observed errors cannot establish production safety or a tiny population error rate. No significance or calibrated-probability claim is supported. No post-test tuning is permitted; future experiments need new versions and fresh cases.']
    local=value['local']['arms']['local'];resource=local['resources_all_attempts'];review=value['review'];memory=value['memory']
    out += ['', '## Local arm and labels','',f'Local run stopped: {value["local"]["stopped"]}. It contains {resource["attempts"]} journaled attempts, {len(resource.get("local_telemetry_sources",[]))} with model telemetry, and {local["primary_missing_n"]} missing primary observations. It is not a complete matched local comparison. Local electricity/hardware cost is unknown.',
            '',f'Blind separate-agent review recorded {sum(v["agreements"] for v in review["by_split"].values())}/{review["total_reviewed"]} agreement. Human adjudication: {review["human_adjudication_performed"]}. This does not establish independent human validation; results remain provisional.',
            '', '## Separate memory mechanism comparison','',f'{memory["counts"]["unique_queries"]} unique synthetic queries; {memory["counts"]["history_records"]} fixed history records. No reinforcement, persistent Calyx state, MCP overhead, or model fallback was measured.','',
            '| Arm | Hits | False action reuse | Raw unsafe | Enforced unsafe | Safe / eligible | Per-query median p50 ms |',
            '|---|---:|---:|---:|---:|---:|---:|']
    for name,m in memory['metrics'].items():out.append(f'| {name} | {m["candidate_hits"]}/{m["queries"]} | {m["false_action_reuses"]} | {m["raw_unsafe_skips"]}/{memory["counts"]["non_skippable_queries"]} | {m["enforced_unsafe_skips"]}/{memory["counts"]["non_skippable_queries"]} | {m["safe_enforced_skips"]}/{memory["counts"]["skip_eligible_queries"]} | {num(m["per_query_median_p50_ms"],4)} |')
    out += ['',f'Deterministic reference: {memory["deterministic_reference"]["gate_action_matches"]}/{memory["counts"]["unique_queries"]} action matches with {memory["deterministic_reference"]["model_calls_required_for_this_fixture"]} model calls. A retrieval hit is simulated fallback avoidance, not actual model/token/cost savings. The experiment does not establish Calyx product efficacy or superiority.',
            '', '## Budget and reproducibility','',f'Cloud reservation ledger: `{json.dumps(value["budgets"]["cloud"],sort_keys=True)}`.',f'Local allowance ledger: `{json.dumps(value["budgets"]["local"],sort_keys=True)}`.',
            '', 'The snapshot preserves conservative reservations separately from measured provider totals. Unknown monetary amounts stay unknown. Per-run commits, dataset hashes, settings, samples, retries, native usage, and stop status are in `EXPERIMENT_LOG.csv` and `evidence.json`.',
            '', 'Regenerate offline from the original artifact root into a new directory:', '', '```sh',
            'python -B build_evidence_demo.py --root ARTIFACT_ROOT --output NEW_OUTPUT_DIRECTORY'+(' --heldout ARTIFACT_ROOT/campaign/v002-test-report' if held else ''), '```',
            '', 'Frozen full-phase replay is currently supported on Windows/Python 3.12.14: threshold journal keys preserve Windows separators, and the recorded tokenizer wheel is CPython 3.12 Windows. Do not claim cross-platform full replay. A portability fix needs a new instrument version; this presentation itself uses only the Python standard library. Original scoring reports replay through `study-execution/development_report.py` with the run directory, split-specific dataset and existing frozen tokenizer environment. Locked phases verify the prospective freeze before replay; existing source and dependencies suffice without inference.',
            '', 'This presentation generator is outside the frozen experiment implementation. It only renders already-scored evidence. `MANIFEST.json` binds its source, presentation outputs, and input JSON hashes. Repositories remain private; no publication or external message is performed.',
            '', 'Game-AI acceptance criteria and full-task agent pilots remain separate, unexecuted studies.']
    return '\n'.join(out)+'\n'


def final_page(value):
    page=html_page(value);held=value['heldout'];receipt=value['budget_receipt']
    page=page.replace('</style>', '''
    .grid>*,.hero>*,.sectionhead>*{min-width:0}
    .panel,.scroll{min-width:0;max-width:100%}
    .scroll{overflow-x:auto}
    .proxyrow{grid-template-columns:115px minmax(0,1fr) 76px}
    .proxyrow>*,.signed{min-width:0}
    @media(max-width:800px){.proxyrow{grid-template-columns:100px minmax(0,1fr) 65px}}
    </style>''')
    if held:
        j=overall(held['arms']['jev']);d=held['baselines']['deterministic']['overall']
        cards=f'<div class="metrics"><div class="metric"><b>{ratio(j)}</b><span>Jev held-out safe skips; deterministic {ratio(d)}</span></div><div class="metric"><b>+{j["safe_skips"]-d["safe_skips"]}</b><span>eligible skips over rules; {ratio(j,"unsafe_skips","non_skippable")} enforced unsafe observed</span></div><div class="metric"><b class="unknown">Unknown</b><span>actual net-token reduction and accepted-task cost</span></div></div>'
        page=re.sub(r'<div class="metrics">.*?</div>\s*<section>',cards+'<section>',page,count=1,flags=re.S)
        page=page.replace('A recommendation can become more useful without becoming cheaper. This study keeps those outcomes separate.',f'Jev plus evidence checks added {j["safe_skips"]-d["safe_skips"]} eligible skips on {held["n_unique_planned"]} held-out synthetic cases. Routing overhead still exceeded avoided reading in the measured input proxy.')
    page=page.replace('<section><div class="sectionhead"><div class="sectionno">06</div>',local_table(value)+'<section><div class="sectionhead"><div class="sectionno">06</div>')
    page=page.replace('<h3>Budget snapshot</h3>',f'<h3>Budget snapshot</h3><p>Current provider-reported known subtotal: {money(receipt["cloud"]["current_provider_reported_known_usd"])}. Reported-or-estimated current subtotal: {money(receipt["cloud"]["current_reported_or_estimated_known_usd"])}. Historical actual charge remains unknown; its {money(receipt["cloud"]["historical_reserved_usd"])} reservation is retained.</p>')
    page=page.replace('<li>Game-AI remains a separate future experiment.</li>','<li>Game-AI remains a separate future experiment.</li><li>Before a real development pilot: human label review and advancement criteria. Measure total cost per accepted change, including repair and human intervention.</li>')
    page=page.replace('<div class="downloads">','<p class="note">The proposed building stack gives agent-syllabus prerequisite order, Aldertrace evidence enforcement, and Jev bounded semantic routing. Tools and coding agents still implement changes. No result here establishes near-free accepted changes or that this stack performs most development work.</p><div class="downloads">')
    page=page.replace('href="EXPERIMENT_LOG.csv">Experiment log','href="EXPERIMENT-LOG.md">Experiment log')
    page=page.replace('<a class="button" href="MANIFEST.json">Artifact hashes</a>','<a class="button" href="MANIFEST.json">Artifact hashes</a><a class="button" href="reports/v002-test-report/index.html">Detailed test replay</a><a class="button" href="evidence/campaign/budget-receipt-final.json">Budget receipt</a>')
    page=page.replace('Source inputs and this generator are hash-bound in the manifest.','Source inputs and this generator are hash-bound in the manifest. Frozen full-phase replay is Windows/Python 3.12.14; the frozen paths and tokenizer wheel are not cross-platform. This presentation is standard-library only.')
    return page


def final_markdown(value):
    text=markdown(value);matched=local_matched(value);receipt=value['budget_receipt'];out=[]
    out += ['','### Completed local/cloud intersection','',f'Only {len(matched["case_ids"])} completed local requests have telemetry and the same v1 case inputs as D1 cloud. This resource-selected subset is a partial comparison, not a complete five-arm evaluation. The failed next request is not silently treated as a zero-cost, zero-latency model response.','',
        '| Arm | Safe / eligible | Raw unsafe | Enforced unsafe | Request wall p50 / p95 ms | Native input / output tokens |',
        '|---|---:|---:|---:|---:|---:|']
    for arm,m in matched['arms'].items():out.append(f'| {NAMES[arm]} | {ratio(m)} | {m["raw_unsafe"]}/{m["non_skippable"]} | {ratio(m,"unsafe_skips","non_skippable")} | {num(m["p50_ms"],1)} / {num(m["p95_ms"],1)} | {m["native_input_tokens"]} / {m["native_output_tokens"]} |')
    lm=matched['arms']['local'];out += ['',f'Local: {lm["cold_requests"]} cold requests, model-load p50 {num(lm["load_p50_ms"],1)} ms; warm throughput unknown. Native model tokenizers differ. Baseline execution latency and local energy costs remain unknown.','']
    text=text.replace('## Separate memory mechanism comparison','\n'.join(out)+'\n## Separate memory mechanism comparison')
    out=['','Current provider-reported known subtotal: '+money(receipt['cloud']['current_provider_reported_known_usd'])+'. Current reported-or-estimated subtotal: '+money(receipt['cloud']['current_reported_or_estimated_known_usd'])+'. Historical actual spend remains unknown; '+money(receipt['cloud']['historical_reserved_usd'])+' is reserved for it. Provider response costs are not invoices. No unresolved reservations remain in the receipt. Local execution remains stopped.','',
        'Portable export links: [frozen settings](evidence/campaign/v002-frozen/freeze.json), [threshold selection](evidence/campaign/v002-frozen/thresholds.json), [test replay](reports/v002-test-report/report.json), [calibration replay](reports/v002-calibration-report/report.json), [budget receipt](evidence/campaign/budget-receipt-final.json), [label-review aggregate](label-review/aggregate-summary.json), [memory evidence](../memory-v1/evidence/summary.json), [protocol amendment](PROTOCOL-AMENDMENT.md).','',
        'To regenerate this presentation from the exported layout, run `python -B build_evidence_demo.py --root . --output NEW_OUTPUT_DIRECTORY --heldout reports/v002-test-report`. Link targets assume these files live at experiments/v002; root packaging preserves that layout. Input JSON hashes are the same in both layouts.','',
        '## Further-test recommendation','',
        'The intended building stack assigns prerequisite order to agent-syllabus, evidence enforcement to Aldertrace, and bounded semantic routing to Jev; tools and coding agents implement changes. This study does not establish near-free building, most work being automated, or lower cost per accepted change. Retain deterministic enforcement, reject semantic similarity as permission, and investigate the routing-overhead weakness with a new version and fresh cases. Before a real development pilot, satisfy advancement criteria and obtain human label review; then measure a repeatable workflow by total cost per accepted change, including retries, repairs, failed attempts and human intervention. No pilot is launched here.','']
    return text+'\n'.join(out)


def experiment_markdown(value,rows):
    out=['# Experiment log — study v002','', 'Generated from immutable scored reports and the final campaign receipt. Development is exploratory; calibration selects operating thresholds, not calibrated probabilities; held-out labels remain provisional. See [full data](EXPERIMENT_LOG.csv) and [hash manifest](MANIFEST.json).','',
         '| Run | Arm / model | Evidence | Unique planned / observed | All attempts / retries | Native input / output | Estimated / reported USD | Complete |',
         '|---|---|---|---:|---:|---:|---:|---|']
    for r in rows:
        out.append(f'| {r["version"]} | {r["arm"]} / {r["model"]} | {r["evidence_kind"]} | {r["planned_unique"]} / {r["observed_primary"]} | {r["all_attempts"]} / {r["retries"]} | {num(r["native_input_tokens"])} / {num(r["native_output_tokens"])} | {money(r["estimated_usd"])} / {money(r["reported_usd"])} | {r["complete"]} |')
    out += ['', 'Each development definition identifies its base commit plus exact implementation hashes; source_commit alone does not capture development edits. Frozen calibration/test use the full committed source below. Calibration report enforced actions use a null threshold and must not be read as post-selection coverage; the selected threshold record is separate.','',BLINDING_NOTE,'', '## Version identities','']
    seen=set()
    for r in rows:
        if r['version'] in seen:continue
        seen.add(r['version']);out += [f'### {r["version"]}','',f'- Code/base commit: `{r["source_commit"]}`',f'- Dataset SHA-256: `{r["dataset_sha256"]}`',f'- Prompt / policy: `{r["prompt_version"]}` / `{r["policy"]}`',f'- Settings: `{r["settings"]}`',f'- Threshold: `{r["threshold"]}`',f'- Stop reason: {r["stopped"] or "none"}','']
    out += ['## Separate mechanism evidence','',f'Memory experiment `{value["memory"].get("version","memory-v1")}` remains separate: {value["memory"]["counts"]["unique_queries"]} unique queries and no live fallback inference. Repeated lookup timings are not additional unique cases.','', '## What remains unknown','', '- Actual net end-to-end tokens, downstream task success, and cost per accepted change.', '- Complete matched local performance; the resource-selected observed intersection is descriptive only.', '- Baseline check runtime and energy/hardware charges.', '- Population safety and generalization beyond authored families.', '', 'No new model execution, installation, purchase, push or external publication is performed by this generator.']
    return '\n'.join(out)+'\n'


def build(root,output,heldout=None):
    value=state(root,heldout);value['local_matched_completed_intersection']=local_matched(value);output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    (output/'evidence.json').write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf8')
    (output/'index.html').write_text('\n'.join(line.rstrip() for line in final_page(value).splitlines())+'\n',encoding='utf8')
    (output/'REPORT.md').write_text(final_markdown(value),encoding='utf8')
    rows=log_rows(value)
    (output/'EXPERIMENT-LOG.md').write_text(experiment_markdown(value,rows),encoding='utf8')
    with (output/'EXPERIMENT_LOG.csv').open('x',encoding='utf8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    shutil.copyfile(__file__,output/'build_evidence_demo.py')
    manifest={'schema':1,'input_sha256':value['sources_sha256'],'output_sha256':{
        p.name:sha(p) for p in sorted(output.iterdir()) if p.is_file()},
        'heldout_included':value['heldout'] is not None,'claim_status':'provisional; no actual net-token or task-success result'}
    (output/'MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf8')
    return {'output':str(output),'heldout_included':manifest['heldout_included'],'live_calls':0,
            'files':len(manifest['output_sha256'])+1}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--heldout',type=Path,help='Explicit permission to import the scored held-out report; missing path remains pending')
    args=parser.parse_args()
    print(json.dumps(build(args.root,args.output,args.heldout)))
