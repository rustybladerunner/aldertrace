"""Offline analysis. Missing/invalid answers never become a successful skip."""
import math
import random
from collections import Counter
from adapters import ROOT
from core import ACTIONS,normalized_answer,enforce,score


def wilson(successes,n,z=1.959963984540054):
    """Descriptive binomial interval; dependence warning is attached by caller."""
    if type(n) is not int or type(successes) is not int or not 0<=successes<=n:
        raise ValueError('invalid count')
    if n==0:return None
    p=successes/n; d=1+z*z/n
    center=(p+z*z/(2*n))/d
    radius=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d
    return [max(0,center-radius),min(1,center+radius)]


def _quantile(xs,q):
    ys=sorted(xs); k=(len(ys)-1)*q; lower=int(k)
    return ys[lower]+(ys[min(lower+1,len(ys)-1)]-ys[lower])*(k-lower)


def cluster_ratio(family_counts,draws=5000,seed=20260919):
    """Resample whole family numerator/denominator pairs, not observations."""
    if not family_counts or draws<1:raise ValueError('need families and draws')
    if any(n<0 or d<0 or n>d for n,d in family_counts):raise ValueError('invalid family counts')
    rng=random.Random(seed); values=[]; undefined=0
    for _ in range(draws):
        sample=[rng.choice(family_counts) for _ in family_counts]
        denominator=sum(d for n,d in sample)
        if denominator:values.append(sum(n for n,d in sample)/denominator)
        else:undefined+=1
    return {'percentile_95':[_quantile(values,.025),_quantile(values,.975)] if values else None,
            'draws':draws,'undefined_draws':undefined,'families':len(family_counts),
            'seed':seed,'method':'whole-family bootstrap ratio',
            'limitation':'Exploratory with few families. A degenerate zero interval cannot establish zero population risk.'}


def reliability(cases,answers,signal='confidence',bins=5):
    if signal not in ('confidence','max_probability'):raise ValueError('unknown signal')
    buckets=[{'n':0,'sum_signal':0.0,'correct':0} for _ in range(bins)]
    omitted=0
    for c in cases:
        answer=normalized_answer(answers.get(c['id']))
        if answer is None:omitted+=1;continue
        p=answer['confidence'] if signal=='confidence' else max(answer['probabilities'].values())
        b=buckets[min(int(p*bins),bins-1)]
        b['n']+=1;b['sum_signal']+=p;b['correct']+=answer['choice']==c['label']['action']
    return {'signal':signal,'omitted_invalid':omitted,'exploratory':True,
            'bins':[{'lower':i/bins,'upper':(i+1)/bins,'n':b['n'],
                     'mean_signal':b['sum_signal']/b['n'] if b['n'] else None,
                     'observed_accuracy':b['correct']/b['n'] if b['n'] else None}
                    for i,b in enumerate(buckets)],
            'note':'Entropy concentration and self-reported/provider confidence are not interchangeable calibrated probabilities.'}


def summarize(cases,answers,threshold):
    ids=[c['id'] for c in cases]
    if len(ids)!=len(set(ids)) or set(answers)!=set(ids):
        raise ValueError('one primary response per unique case required')
    if threshold is not None and (type(threshold) not in (int,float) or not math.isfinite(threshold) or not 0<=threshold<=1):
        raise ValueError('invalid frozen threshold')
    raw={};hybrid={};invalid=[];briers=[];failures=[]
    for c in cases:
        cid=c['id'];a=normalized_answer(answers[cid])
        raw[cid]=a['choice'] if a else 'review'
        hybrid[cid]=enforce(c,answers[cid],threshold)
        if a is None:invalid.append(cid)
        else:briers.append(sum((a['probabilities'][k]-(k==c['label']['action']))**2 for k in ACTIONS))
        if a is None or raw[cid]!=c['label']['action'] or hybrid[cid]!=c['label']['action']:
            failures.append({'case_id':cid,'family':c['family'],'expected':c['label']['action'],
                'raw_action':raw[cid],'hybrid_action':hybrid[cid],'invalid':a is None,
                'raw_unsafe_skip':raw[cid]=='skip' and c['label']['action']!='skip',
                'hybrid_unsafe_skip':hybrid[cid]=='skip' and c['label']['action']!='skip',
                'rationale':c['label']['rationale']})
    result={'n_unique':len(cases),'threshold':threshold,'invalid_count':len(invalid),
            'invalid_ids':invalid,'invalid_policy':'counted as review; no fabricated probability vector',
            'multiclass_brier':sum(briers)/len(briers) if briers else None,
            'brier_valid_n':len(briers),'brier_definition':'sum over four classes; range 0 to 2',
            'reliability':{s:reliability(cases,answers,s) for s in ('confidence','max_probability')},
            'failures':failures,'arms':{}}
    for name,predictions in (('raw',raw),('hybrid',hybrid)):
        overall=score(cases,predictions)
        families={family:score([c for c in cases if c['family']==family],
            {c['id']:predictions[c['id']] for c in cases if c['family']==family})
            for family in sorted({c['family'] for c in cases})}
        pairs=[(m['unsafe_skips'],m['non_skippable']) for m in families.values()]
        overall['unsafe_wilson_95']=wilson(overall['unsafe_skips'],overall['non_skippable'])
        overall['unsafe_family_bootstrap']=cluster_ratio(pairs)
        overall['interval_warning']='Wilson assumes independent Bernoulli trials; correlated authored cases violate that assumption. Report families and counts alongside it.'
        result['arms'][name]={'overall':overall,'families':families}
    return result


def stability(rows):
    """Repeats are a separate summary, never extra unique primary cases."""
    groups={}
    for row in rows:
        cid=row['case_id'];trial=row['trial']
        if type(trial) is not int or trial not in (1,2,3):raise ValueError('bad trial')
        group=groups.setdefault(cid,{})
        if trial in group:raise ValueError('duplicate case/trial')
        a=normalized_answer(row['answer']);group[trial]=a['choice'] if a else 'invalid'
    if any(set(g)!={1,2,3} for g in groups.values()):raise ValueError('incomplete repeats')
    return {'n_unique':len(groups),'observations':3*len(groups),
            'changed_choice_cases':sum(len(set(g.values()))>1 for g in groups.values()),
            'cases_with_invalid':sum('invalid' in g.values() for g in groups.values()),
            'choices':groups}
