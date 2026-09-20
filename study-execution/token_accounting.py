"""Account for measured input tokens without inventing a tokenizer or conversion."""
import hashlib
from adapters import ROOT
from core import baseline,ACTIONS


def count(value):
    if type(value) is not int or value<0:raise ValueError('token counts must be nonnegative integers')
    return value


def account(cases,predictions,measurements,tokenizer_identity):
    """Each record must measure guide and full router input in the SAME tokenizer.

    Provider-native token counts with different tokenizers cannot be pooled here.
    Count the complete adapter prompt, including wrappers/options/schema where
    consumed. Records are supplied by a separately validated tokenizer adapter.
    """
    ids=[c['id'] for c in cases]
    if len(ids)!=len(set(ids)) or set(ids)!=set(predictions) or set(ids)!=set(measurements):
        raise ValueError('exact unique primary-case coverage required')
    if not isinstance(tokenizer_identity,str) or not tokenizer_identity.strip():
        raise ValueError('frozen tokenizer identity required')
    baseline_tokens=0;avoided=0;overhead=0;families={}
    for c in cases:
        cid=c['id'];m=measurements[cid];pred=predictions[cid]
        if pred not in ACTIONS:raise ValueError('invalid action')
        if m.get('tokenizer_identity')!=tokenizer_identity:raise ValueError('mixed or missing tokenizer')
        if m.get('status')!='measured':raise ValueError('estimated tokens cannot support H1')
        if m.get('document_sha256')!=hashlib.sha256(c['document'].encode('utf8')).hexdigest():
            raise ValueError('guide changed after token measurement')
        prompt_hash=m.get('router_input_sha256','')
        if len(prompt_hash)!=64 or any(ch not in '0123456789abcdef' for ch in prompt_hash):
            raise ValueError('measured router input hash required')
        # The final run manifest must bind this hash to the exact rendered prompt.
        doc=count(m['document_tokens']);routing=count(m['router_input_tokens'])
        mandatory=doc if baseline(c,'read_everything')=='read' else 0
        saved=mandatory if pred=='skip' and c['label']['action']=='skip' else 0
        baseline_tokens+=mandatory;avoided+=saved;overhead+=routing
        f=families.setdefault(c['family'],{'baseline_input_tokens':0,'avoided_input_tokens':0,'routing_input_tokens':0})
        f['baseline_input_tokens']+=mandatory;f['avoided_input_tokens']+=saved;f['routing_input_tokens']+=routing
    net=avoided-overhead
    return {'tokenizer_identity':tokenizer_identity,'n_unique':len(cases),
        'baseline_input_tokens':baseline_tokens,'avoided_input_tokens':avoided,
        'routing_input_tokens':overhead,'net_input_tokens_saved':net,
        'fraction_saved':net/baseline_tokens if baseline_tokens else None,
        'families':families,
        'scope':'Mandatory reading input minus full routing input, primary requests only. Check runtime, model outputs and task completion costs are separate.',
        'limitation':'Measurement provenance and prompt hashes must be verified by final run manifest; this arithmetic does not independently certify a tokenizer.'}
