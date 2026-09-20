"""Offline o200k_base measurement with immutable tokenizer provenance.

Cloud HTTP JSON counts are observable serialization proxies, not hidden model
prompts. The local engine render is observable; Ollama's chat wrapper is not.
This module deliberately never marks these routing measurements H1-eligible.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys
from adapters import canonical, strict_json
from core import ACTIONS, baseline

VERSION = '0.14.0'
ENCODING = 'o200k_base'
VOCABULARY_SHA256 = '446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d'
DEFAULT_MANIFEST_SHA256 = '84f40a9953de9923f546e700c2a36b8074337823dc51d6fe83cbb6849652f477'


def sha(value):
    return hashlib.sha256(value).hexdigest()


class FrozenTokenizer:
    """Verify the isolated install, then construct Encoding using local ranks only.

    No package installation, network client, plugin discovery, or cache download.
    Import search-path changes remain process-local. Literal special-token-looking
    strings use encode_ordinary, so untrusted text is never promoted to control IDs.
    """
    def __init__(self, environment, *, expected_manifest_sha256=DEFAULT_MANIFEST_SHA256):
        self.root = Path(environment).resolve()
        raw = (self.root/'tokenizer-manifest.json').read_bytes()
        if sha(raw) != expected_manifest_sha256:
            raise ValueError('tokenizer manifest hash differs from frozen identity')
        self.manifest = strict_json(raw.decode('utf8'))
        m = self.manifest
        if m.get('schema') != 1 or m.get('version') != VERSION or m.get('encoding') != ENCODING:
            raise ValueError('unsupported frozen tokenizer definition')
        if m['vocabulary']['sha256'] != VOCABULARY_SHA256:
            raise ValueError('vocabulary differs from pinned OpenAI o200k_base')
        for name, entry in m['wheels'].items():
            self._verify(name, entry['sha256'])
        actual = {p.relative_to(self.root).as_posix() for p in (self.root/'site').rglob('*')
                  if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.py','.pyd')}
        if actual != set(m['modules']):
            raise ValueError('tokenizer module inventory differs from frozen install')
        for name, digest in m['modules'].items():
            self._verify(name, digest)
        vocab = self._verify(m['vocabulary']['path'], VOCABULARY_SHA256)
        site = self.root/'site'
        loaded = sys.modules.get('tiktoken')
        if loaded is not None and not Path(loaded.__file__).resolve().is_relative_to(site):
            raise ValueError('another tokenizer installation is already imported')
        sys.path.insert(0, str(site))
        import tiktoken
        if tiktoken.__version__ != VERSION or not Path(tiktoken.__file__).resolve().is_relative_to(site):
            raise ValueError('imported tokenizer differs from isolated installation')
        ranks = {}
        for line in vocab.read_bytes().splitlines():
            token, rank = line.split()
            token = base64.b64decode(token, validate=True)
            if token in ranks:
                raise ValueError('duplicate vocabulary token')
            ranks[token] = int(rank)
        self.encoding = tiktoken.Encoding(name=ENCODING, pat_str=m['pattern'],
                                          mergeable_ranks=ranks, special_tokens=m['special_tokens'])
        self.identity = f'tiktoken:{VERSION}:{ENCODING}:manifest-sha256:{expected_manifest_sha256}'
        self.provenance = {'tokenizer_identity': self.identity,
            'manifest_sha256': expected_manifest_sha256, 'vocabulary_sha256': VOCABULARY_SHA256,
            'measurement_module_sha256': sha(Path(__file__).read_bytes()),
            'encoding_policy': 'encode_ordinary; literal special-token strings stay ordinary text',
            'environment_python': m['python_version'], 'runtime_python': sys.version.split()[0]}

    def _verify(self, relative, expected):
        path = (self.root/relative).resolve()
        if not path.is_relative_to(self.root) or sha(path.read_bytes()) != expected:
            raise ValueError('tokenizer asset changed: '+relative)
        return path

    def tokens(self, text):
        if not isinstance(text, str):
            raise ValueError('token measurement requires the exact text')
        return self.encoding.encode_ordinary(text)

    def measure(self, text):
        ids = self.tokens(text)
        return {'tokens': len(ids), 'utf8_bytes': len(text.encode('utf8')),
                'text_sha256': sha(text.encode('utf8')),
                'token_ids_sha256': sha(canonical(ids).encode('utf8'))}


def local_renders(body):
    """Reconstruct the unchanged engine's complete prompt for each question."""
    from logitpick.schema import parse_request
    from logitpick.codes import assign_codes
    from logitpick.prompt import render
    request = parse_request(body)
    return [render(request.state, q.instructions, q.options, assign_codes(list(q.options)))
            for q in request.questions]


def _output_text(response, arm):
    if not isinstance(response, dict):
        return None
    if arm == 'chat':
        choices = response.get('choices')
        if isinstance(choices, list) and len(choices) == 1:
            message = choices[0].get('message', {})
            content = message.get('content')
            if isinstance(content, str):
                return content
    elif arm == 'local':
        answers = response.get('answers')
        if isinstance(answers, dict) and len(answers) == 1:
            answer = next(iter(answers.values()))
            if isinstance(answer, dict) and isinstance(answer.get('generated_token'), str):
                return answer['generated_token']
    # Jev's structured decision is not an observed generated-token sequence.
    return None


def measure_attempt(tokenizer, request, result=None):
    """Measure every recorded request, including failures and retries.

    A request journal entry proves the observable payload, not server consumption.
    Provider usage is retained separately without mixing tokenizers. Missing output
    or native usage remains null, even for HTTP errors and interrupted requests.
    """
    if request.get('event') != 'request' or request.get('arm') not in ('local','jev','jev_openrouter','chat'):
        raise ValueError('recognized request journal event required')
    if type(request.get('attempt')) is not int or request['attempt'] < 1 or not isinstance(request.get('key'), str):
        raise ValueError('request identity required')
    if result is not None and (result.get('event') != 'result' or
            (request['key'],request['attempt']) != (result.get('key'),result.get('attempt'))):
        raise ValueError('result does not match request attempt')
    arm = request['arm']
    serialized = tokenizer.measure(canonical(request['body']))
    renders = [tokenizer.measure(text) for text in local_renders(request['body'])] if arm == 'local' else []
    renderer_hashes = {}
    if renders:
        from logitpick import prompt, codes, schema
        renderer_hashes = {module.__name__:sha(Path(module.__file__).read_bytes())
                           for module in (prompt,codes,schema)}
    chosen_input = sum(m['tokens'] for m in renders) if renders else serialized['tokens']
    raw = result.get('body') if result else None
    response = None
    if isinstance(raw, str):
        try:
            response = strict_json(raw)
        except (ValueError,TypeError):
            pass
    generated = _output_text(response, arm)
    output = tokenizer.measure(generated) if generated is not None else None
    native = response.get('usage') if isinstance(response, dict) else None
    native_fields = ('prompt_tokens','completion_tokens') if arm == 'chat' else ('input_tokens','output_tokens')
    native_counts = None
    if isinstance(native, dict) and all(type(native.get(k)) is int and native[k]>=0 for k in native_fields):
        native_counts = {'input_tokens':native[native_fields[0]], 'output_tokens':native[native_fields[1]]}
    return {'key':request['key'], 'attempt':request['attempt'], 'arm':arm,
        'tokenizer_identity':tokenizer.identity, 'status':'measured_observable_input_proxy',
        'request_event_sha256':sha(canonical(request).encode('utf8')),
        'result_event_sha256':sha(canonical(result).encode('utf8')) if result else None,
        'public_serialization':serialized, 'local_engine_renders':renders,
        'local_renderer_sources_sha256':renderer_hashes,
        'common_input_proxy_tokens':chosen_input,
        'input_basis':'exact local engine render; server chat wrapper unknown' if renders else
                      'complete canonical HTTP JSON; provider prompt serialization unknown',
        'observed_generated_output':output,
        'common_input_plus_observed_output_tokens':chosen_input+output['tokens'] if output else None,
        'response_serialization':tokenizer.measure(raw) if isinstance(raw,str) else None,
        'provider_native_tokens':native_counts,
        'request_consumption_confirmed':native_counts is not None,
        'response_observed':result is not None, 'h1_eligible':False}


def measure_journal(tokenizer, path):
    path = Path(path)
    raw = path.read_bytes()
    if raw and not raw.endswith(b'\n'):
        raise ValueError('incomplete journal line; token totals remain unknown')
    requests = {};results = {};reserved = set()
    for line in raw.decode('utf8').splitlines():
        event = strict_json(line)
        if event.get('event') not in ('reserved','request','result'):
            continue
        identity = (event.get('key'),event.get('attempt'))
        if event['event'] == 'reserved':
            if identity in reserved:raise ValueError('duplicate reservation')
            reserved.add(identity)
        elif event['event'] == 'request':
            if identity in requests:raise ValueError('duplicate request attempt')
            requests[identity] = event
        else:
            if identity in results:raise ValueError('duplicate attempt result')
            results[identity] = event
    if set(results)-set(requests):
        raise ValueError('result has no observable request')
    return {'journal_sha256':sha(raw), 'tokenizer':tokenizer.provenance,
            'attempts':[measure_attempt(tokenizer,req,results.get(identity)) for identity,req in requests.items()],
            'reserved_without_request':[{'key':key,'attempt':attempt} for key,attempt in sorted(reserved-set(requests))],
            'h1_eligible':False}


def measure_case(tokenizer, case, attempts):
    """One unique case in one trial; retry attempts stay in its denominator."""
    identities = [(a['key'],a['attempt']) for a in attempts]
    if len(identities)!=len(set(identities)) or len({a['key'] for a in attempts})>1 or len({a['arm'] for a in attempts})>1:
        raise ValueError('duplicate attempts or repeat trials mixed into one primary case')
    if any(a['tokenizer_identity']!=tokenizer.identity for a in attempts):
        raise ValueError('mixed tokenizer identities')
    document = tokenizer.measure(case['document'])
    output = [a['observed_generated_output'] for a in attempts]
    complete_output = all(m is not None for m in output)
    return {'case_id':case['id'],'tokenizer_identity':tokenizer.identity,
        'status':'measured_observable_input_proxy','document_sha256':document['text_sha256'],
        'document_tokens':document['tokens'],'document_utf8_bytes':document['utf8_bytes'],
        'attempts':attempts,'attempt_count':len(attempts),
        'routing_input_proxy_tokens':sum(a['common_input_proxy_tokens'] for a in attempts),
        'routing_observed_output_tokens':sum(m['tokens'] for m in output) if complete_output else None,
        'routing_total_proxy_tokens':sum(a['common_input_plus_observed_output_tokens'] for a in attempts)
                                     if complete_output else None,
        'h1_eligible':False}


def summarize(cases, predictions, measurements, tokenizer_identity):
    """Input-only net proxy, plus output-inclusive proxy when fully observable.

    Executable-check avoidance does not become invented guide-token savings.
    Unknown hidden wrappers and consumption prevent this proxy from establishing H1.
    """
    ids = [c['id'] for c in cases]
    if len(ids)!=len(set(ids)) or set(ids)!=set(predictions) or set(ids)!=set(measurements):
        raise ValueError('exact unique case coverage required')
    families = {}; total = {'baseline_reading_tokens':0,'safely_avoided_reading_tokens':0,
                           'routing_input_proxy_tokens':0,'routing_observed_output_tokens':0,'attempts':0}
    for case in cases:
        m = measurements[case['id']]; action = predictions[case['id']]
        if action not in ACTIONS or m['tokenizer_identity']!=tokenizer_identity:
            raise ValueError('invalid action or mixed tokenizer')
        if m['document_sha256'] != sha(case['document'].encode('utf8')):
            raise ValueError('guide changed after token measurement')
        doc = m['document_tokens'] if baseline(case,'read_everything')=='read' else 0
        saved = doc if action=='skip' and case['label']['action']=='skip' else 0
        row = {'baseline_reading_tokens':doc,'safely_avoided_reading_tokens':saved,
               'routing_input_proxy_tokens':m['routing_input_proxy_tokens'],
               'routing_observed_output_tokens':m['routing_observed_output_tokens'],
               'attempts':m['attempt_count']}
        family = families.setdefault(case['family'],{k:0 for k in total})
        for k,v in row.items():
            if v is not None and (type(v) is not int or v<0):raise ValueError('invalid measured token count')
            for target in (total,family):
                target[k] = None if v is None or target[k] is None else target[k]+v
    for row in [total,*families.values()]:
        row['net_input_proxy_tokens_saved'] = row['safely_avoided_reading_tokens']-row['routing_input_proxy_tokens']
        row['input_proxy_fraction_saved'] = row['net_input_proxy_tokens_saved']/row['baseline_reading_tokens'] if row['baseline_reading_tokens'] else None
        row['net_input_plus_observed_output_proxy_tokens_saved'] = row['net_input_proxy_tokens_saved']-row['routing_observed_output_tokens'] if row['routing_observed_output_tokens'] is not None else None
    return {**total,'families':families,'n_unique_cases':len(cases),'tokenizer_identity':tokenizer_identity,
        'measurement_scope':'observable routing input proxy including every recorded retry; exact guide text',
        'h1_eligible':False,'limitation':'Provider prompt wrappers and unreported generation remain unknown. This is not an actual end-to-end or provider-native token reduction.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--environment',type=Path,required=True)
    parser.add_argument('--manifest-sha256',default=DEFAULT_MANIFEST_SHA256)
    parser.add_argument('--journal',type=Path,action='append',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    tokenizer=FrozenTokenizer(args.environment,expected_manifest_sha256=args.manifest_sha256)
    value={'tokenizer':tokenizer.provenance,'journals':[measure_journal(tokenizer,p) for p in args.journal]}
    with args.output.open('x',encoding='utf8') as output:
        output.write(canonical(value)+'\n')


if __name__=='__main__':main()
