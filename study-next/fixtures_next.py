"""New synthetic instrument fixtures; no historical evaluation cases or inference.

FakeProviders deliberately reads fixture labels to generate simulated responses.
These outcomes test plumbing and must never be presented as model performance.
"""
import copy
import hashlib
import json
from pathlib import Path


MODELS = {'jev': 'jev-1.13.0',
          'chat': 'openai/gpt-4.1-mini-2025-04-14',
          'local': 'llama3.2:latest'}
ACTIONS = ('skip', 'read', 'run_check', 'review')


def fixture_cases(phase):
    if phase not in ('development', 'calibration', 'test'):
        raise ValueError('unknown fixture phase')
    cases = []
    for index, expected in enumerate(('skip', 'skip', 'read')):
        identity = f'instrument-{phase}-semantic-{index}'
        condition = 'Explain why a receipt must identify the exact package revision.'
        explanation = ('A receipt proves only the revision it names; compare the current revision.'
                       if expected == 'skip' else 'Every old receipt certifies all later revisions.')
        cases.append({'id': identity, 'split': phase,
                      'family': f'instrument-{phase}-semantic',
                      'state': {'unit': {'kind': 'semantic',
                                         'artifact': f'guides/{identity}.md',
                                         'command': None, 'skip_condition': condition},
                                'current_revision': f'{identity}-r2', 'scope_known': True,
                                'runner_evidence': [], 'explanation': explanation},
                      'document': condition + ' A receipt never proves a different revision.',
                      'label': {'action': expected, 'rationale': 'Synthetic instrumentation oracle.'},
                      'review_status': 'agent_authored_unreviewed'})
    for index, variant in enumerate(('current', 'stale', 'failed')):
        identity = f'instrument-{phase}-executable-{index}'
        revision = f'{identity}-r2'
        artifact = f'packages/{identity}.json'
        command = 'checks/check_instrument_package.py'
        proof = {'trusted': True, 'revision': revision, 'artifact': artifact,
                 'command': command, 'exit_code': 0}
        if variant == 'stale':
            proof['revision'] = f'{identity}-r1'
        if variant == 'failed':
            proof['exit_code'] = 1
        cases.append({'id': identity, 'split': phase,
                      'family': f'instrument-{phase}-executable',
                      'state': {'unit': {'kind': 'executable', 'artifact': artifact,
                                         'command': command,
                                         'skip_condition': 'Require a trusted current matching exit zero.'},
                                'current_revision': revision, 'scope_known': True,
                                'runner_evidence': [proof],
                                'explanation': 'Fixture text is data, never permission.'},
                      'document': 'Run the package check for the exact current revision.',
                      'label': {'action': 'skip' if variant == 'current' else 'run_check',
                                'rationale': 'Synthetic instrumentation oracle: ' + variant},
                      'review_status': 'agent_authored_unreviewed'})
    return cases


def write_dataset(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    assets = {}
    for phase in ('development', 'calibration', 'test'):
        path = directory / (phase + '.json')
        path.write_text(json.dumps(fixture_cases(phase), indent=2) + '\n', encoding='utf8')
        assets[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    (directory / 'MANIFEST.json').write_text(json.dumps({
        'schema': 1, 'purpose': 'synthetic instrument regression fixtures; not efficacy data',
        'assets': assets}, indent=2) + '\n', encoding='utf8')
    return directory


def settings(campaign_path, *, arms=('jev', 'chat'), cap='2', policy='deterministic_first'):
    return {'models': dict(MODELS), 'available_arms': list(arms),
            'label_status': 'agent_authored_unreviewed',
            'tokenizer_identity': None, 'preflight_sha256': '1' * 64,
            'policy': policy, 'prompt_version': 'v2',
            'local_status': 'unavailable: offline instrument tests do not load models',
            'cloud_model_identity': {'jev': MODELS['jev'], 'chat': MODELS['chat']},
            'measurement_scope': 'unknown until explicitly supplied validated tokenizer',
            'source_commit': 'instrument-tests-only', 'purpose': 'instrument-test',
            'campaign_path': str(Path(campaign_path).resolve()), 'cloud_cap_usd': cap,
            'unavailable_arms': {a: 'unavailable in this simulated instrument fixture'
                                 for a in ('jev', 'chat') if a not in arms}}


class FakeProviders:
    """Callable transport doubles with complete telemetry and observable calls."""
    def __init__(self, cases=None, *, models=None, overrides=None):
        self.cases = cases or sum((fixture_cases(p) for p in
                                  ('development', 'calibration', 'test')), [])
        self.models = dict(models or MODELS)
        self.by_artifact = {c['state']['unit']['artifact']: c for c in self.cases}
        self.overrides = overrides or {}
        self.calls = []

    def transports(self, arms=('jev', 'chat')):
        return {arm: self.transport(arm) for arm in arms}

    def transport(self, arm):
        def respond(body):
            common = json.loads(body['messages'][1]['content']) if arm == 'chat' else body
            state = json.loads(common['state'])
            case = self.by_artifact[state['unit']['artifact']]
            self.calls.append({'arm': arm, 'case_id': case['id'], 'body': copy.deepcopy(body)})
            override = self.overrides.get((arm, case['id']))
            if callable(override):
                value = override(body)
                if value is not None:
                    return value
            elif override is not None:
                return copy.deepcopy(override)
            return fake_response(arm, case['label']['action'], model=self.models[arm])
        return respond


def fake_response(arm, choice='skip', *, model=None, invalid=False, missing_usage=False,
                  reported_cost=None, status=200):
    answer = {'choice': choice, 'confidence': 1.0,
              'probabilities': {a: float(a == choice) for a in ACTIONS}}
    if invalid:
        answer['probabilities'].pop('review')
    if arm == 'chat':
        usage = {'prompt_tokens': 100, 'completion_tokens': 20}
        raw = {'model': model or MODELS[arm],
               'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(answer)}}]}
    else:
        usage = {'input_tokens': 100, 'output_tokens': 20}
        raw = {'model': model or MODELS[arm], 'answers': {'route': {'type': 'choice', **answer}}}
    if reported_cost is not None:
        usage['cost'] = reported_cost
    if not missing_usage:
        raw['usage'] = usage
    return {'status': status, 'body': json.dumps(raw),
            'elapsed_ms': 2.0, 'request_id': 'simulated-instrument-response'}
