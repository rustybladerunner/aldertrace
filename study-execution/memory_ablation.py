"""Offline, disposable memory-retrieval mechanism ablation. No model calls.

Only Calyx's unmodified config and hasher modules are loaded. No persistent
memory, server, installer, user configuration or reinforcement is accessed.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import math
import os
import platform
import re
import statistics
import sys
import time
import types
from collections import Counter
from dataclasses import asdict
from pathlib import Path

VERSION = 'memory-v1-mechanism-1'
THRESHOLD = 0.8
REPETITIONS = 31
SOURCE_COMMIT = '05d5dddf2c66b82e40fcbc40502a01e6336314be'
SOURCE_HASHES = {
    'src/calyx_mcp/config.py': '28ca4a47cf4953b08e78b0c912fa48dc9796d0d63cf85b30b2f01dc2044099d9',
    'src/calyx_mcp/hasher.py': 'bbd91d602e055907c177dd3ef393eb6510979cda96c8e23e39fa28feea5ea52c',
    'LICENSE': '16d1ce2cf935d55314a6e975bf71e22937520b921517e44839efc29b9d196a7d',
}
ARMS = ('no_memory', 'exact_cache', 'token_jaccard', 'stock_calyx_flylsh')


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_once(path, value):
    with Path(path).open('x', encoding='utf8') as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True) + '\n')


def numeric_tokens(text):
    """Keep numeric literals, unlike the stock hasher's lexical extraction."""
    return set(re.findall(r'[A-Za-z_][A-Za-z0-9_]*|[+-]?\d+(?:\.\d+)?', text.lower()))


def jaccard(left, right):
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def source_provenance(source):
    source = Path(source).resolve()
    observed = {name: digest(source / name) for name in SOURCE_HASHES}
    if observed != SOURCE_HASHES:
        raise ValueError('Pinned Calyx module/license hashes do not match')
    return {'reported_commit': SOURCE_COMMIT, 'sha256': observed,
            'commit_verification': 'Inherited from prior local release review; archive has no .git. Module bytes are independently hash-checked here.',
            'license': 'MIT; copyright 2026 Calyx Research Team; no implementation vendored'}


def load_calyx(source):
    source = Path(source).resolve()
    source_provenance(source)
    # A private package shell avoids calyx_mcp.__init__, which imports services,
    # persistence and installers. These two source files are loaded unmodified.
    name = '_aldertrace_calyx_v107'
    package = types.ModuleType(name)
    package.__path__ = [str(source / 'src/calyx_mcp')]
    sys.modules[name] = package
    config = load_module(name + '.config', source / 'src/calyx_mcp/config.py')
    hasher = load_module(name + '.hasher', source / 'src/calyx_mcp/hasher.py')
    return hasher.FlyLSHHasher(config.HasherConfig())


def state(title, artifact, command, revision, exit_code=0, explanation=None,
          evidence_revision=None, evidence_artifact=None, evidence_command=None,
          trusted=True, scope=True, missing=False, contradiction=False):
    record = {'trusted': trusted, 'revision': evidence_revision or revision,
              'artifact': evidence_artifact or artifact,
              'command': evidence_command or command, 'exit_code': exit_code}
    evidence = [] if missing else [record]
    if contradiction:
        evidence.append(dict(record, exit_code=6))
    return {'unit': {'kind': 'executable', 'artifact': artifact, 'command': command,
                     'skip_condition': title + ': require a trusted current integer-zero result for this exact command and artifact.'},
            'current_revision': revision, 'scope_known': scope,
            'runner_evidence': evidence,
            'explanation': explanation or 'Synthetic fixture outcome is attached as typed runner evidence.'}


def dataset():
    """Fresh explicit histories and query list; unrelated to routing splits."""
    weave = ('Verify selvage counts', 'weaving/482.json', 'python fixtures/selvage_count.py', '410')
    folio = ('Verify folio imposition', 'binding/719.json', 'python fixtures/folio_pairs.py', '620')
    audio = ('Verify resampler impulses', 'audio/238.json', 'python fixtures/impulse_grid.py', '530')
    fold = ('Verify paper-fold stops', 'paper/964.json', 'python fixtures/fold_stops.py', '840')
    loom = ('Verify treadle sequence', 'weaving/335.json', 'python fixtures/treadle_order.py', '760')
    drum = ('Verify percussion bars', 'score/557.json', 'python fixtures/bar_lengths.py', '280')
    cut = ('Verify paper-cut margins', 'paper/683.json', 'python fixtures/margin_clearance.py', '390')
    stitch = ('Verify stitch-repeat closure', 'weaving/126.json', 'python fixtures/repeat_closure.py', '950')
    histories = [
        {'id': 'h-weave', 'state': state(*weave), 'action': 'skip'},
        {'id': 'h-folio', 'state': state(*folio), 'action': 'skip'},
        {'id': 'h-audio', 'state': state(*audio), 'action': 'skip'},
        {'id': 'h-fold', 'state': state(*fold), 'action': 'skip'},
        {'id': 'h-loom-failed', 'state': state(*loom, exit_code=3), 'action': 'run_check'},
        {'id': 'h-drum-failed', 'state': state(*drum, exit_code=5), 'action': 'run_check'},
        {'id': 'h-cut-unknown', 'state': state(*cut, scope=False), 'action': 'review'},
        {'id': 'h-stitch-conflict', 'state': state(*stitch, contradiction=True), 'action': 'review'},
    ]
    queries = [
        {'id': 'q01', 'family': 'exact-repeat', 'state': state(*weave), 'expected': 'skip'},
        {'id': 'q02', 'family': 'exact-repeat', 'state': state(*folio), 'expected': 'skip'},
        {'id': 'q03', 'family': 'exact-repeat', 'state': state(*audio), 'expected': 'skip'},
        {'id': 'q04', 'family': 'exact-repeat', 'state': state(*fold), 'expected': 'skip'},
        {'id': 'q05', 'family': 'exact-repeat', 'state': state(*loom, exit_code=3), 'expected': 'run_check'},
        {'id': 'q06', 'family': 'exact-repeat', 'state': state(*drum, exit_code=5), 'expected': 'run_check'},
        {'id': 'q07', 'family': 'exact-repeat', 'state': state(*cut, scope=False), 'expected': 'review'},
        {'id': 'q08', 'family': 'exact-repeat', 'state': state(*stitch, contradiction=True), 'expected': 'review'},
        {'id': 'q09', 'family': 'near-repeat-valid', 'state': state(*weave, explanation='Synthetic fixture outcome is attached as typed runner evidence. The operator added a note.'), 'expected': 'skip'},
        {'id': 'q10', 'family': 'near-repeat-valid', 'state': state(*folio, explanation='Synthetic fixture outcome is attached as typed runner evidence. This note mentions pagination.'), 'expected': 'skip'},
        {'id': 'q11', 'family': 'near-repeat-valid', 'state': state(*audio, explanation='Synthetic fixture outcome is attached as typed runner evidence. The note now says verified.'), 'expected': 'skip'},
        {'id': 'q12', 'family': 'near-repeat-valid', 'state': state(*fold, explanation='Synthetic fixture outcome is attached as typed runner evidence. Comments were reformatted.'), 'expected': 'skip'},
        {'id': 'q13', 'family': 'near-repeat-failed', 'state': state(*loom, exit_code=3, explanation='Synthetic fixture outcome is attached as typed runner evidence. The same failure persists.'), 'expected': 'run_check'},
        {'id': 'q14', 'family': 'near-repeat-failed', 'state': state(*drum, exit_code=5, explanation='Synthetic fixture outcome is attached as typed runner evidence. A new note was attached.'), 'expected': 'run_check'},
        {'id': 'q15', 'family': 'numeric-collision', 'state': state(*weave, exit_code=1), 'expected': 'run_check'},
        {'id': 'q16', 'family': 'stale-proof', 'state': state(*weave[:3], '411', evidence_revision='410'), 'expected': 'run_check'},
        {'id': 'q17', 'family': 'stale-proof', 'state': state(*weave, evidence_revision='409'), 'expected': 'run_check'},
        {'id': 'q18', 'family': 'numeric-collision', 'state': state(*weave, evidence_artifact='weaving/483.json'), 'expected': 'run_check'},
        {'id': 'q19', 'family': 'wrong-proof-identity', 'state': state(*folio, evidence_artifact='binding/covers.json'), 'expected': 'run_check'},
        {'id': 'q20', 'family': 'wrong-proof-identity', 'state': state(*folio, evidence_command='python fixtures/trim_edges.py'), 'expected': 'run_check'},
        {'id': 'q21', 'family': 'untrusted-proof', 'state': state(*audio, trusted=False), 'expected': 'run_check'},
        {'id': 'q22', 'family': 'missing-proof', 'state': state(*fold, missing=True), 'expected': 'run_check'},
        {'id': 'q23', 'family': 'conflicting-proof', 'state': state(*weave, contradiction=True), 'expected': 'review'},
        {'id': 'q24', 'family': 'unknown-scope', 'state': state(*folio, scope=False), 'expected': 'review'},
    ]
    return {'version': VERSION, 'evidence_kind': 'synthetic-development-mechanism',
            'review_status': 'agent_authored_unreviewed', 'histories': histories, 'queries': queries}


class Retriever:
    def __init__(self, arm, histories, hasher=None):
        if arm not in ARMS:
            raise ValueError('Unknown retrieval arm')
        self.arm, self.histories, self.hasher = arm, histories, hasher
        self.texts = [canonical(row['state']) for row in histories] if arm != 'no_memory' else []
        self.exact = {text: i for i, text in enumerate(self.texts)} if arm == 'exact_cache' else {}
        self.tokens = [numeric_tokens(text) for text in self.texts] if arm == 'token_jaccard' else []
        self.hashes = [hasher.hash_code(text) for text in self.texts] if arm == 'stock_calyx_flylsh' else []

    def lookup(self, query):
        if self.arm == 'no_memory':
            return {'hit': False, 'candidate_id': None, 'similarity': None, 'recommendation': 'review'}
        text = canonical(query)
        if self.arm == 'exact_cache':
            index = self.exact.get(text)
            best = 1.0 if index is not None else 0.0
        else:
            if self.arm == 'token_jaccard':
                representation = numeric_tokens(text)
                scores = [jaccard(representation, tokens) for tokens in self.tokens]
            else:
                representation = self.hasher.hash_code(text)
                scores = [self.hasher.calculate_hamming_similarity(representation, value) for value in self.hashes]
            # The fixed original history order breaks ties; no label-aware choice.
            index = max(range(len(scores)), key=scores.__getitem__) if scores else None
            best = scores[index] if index is not None else 0.0
            if best < THRESHOLD:
                index = None
        hit = index is not None
        return {'hit': hit, 'candidate_id': self.histories[index]['id'] if hit else None,
                'similarity': best, 'recommendation': self.histories[index]['action'] if hit else 'review'}


def enforce(core, query, recommendation):
    """Same executable behavior as frozen core.enforce, without invented model probabilities."""
    gate = core.machine_gate(query)
    if gate not in ('skip', 'run_check', 'review'):
        raise ValueError('This mechanism study accepts executable units only')
    return recommendation if gate == 'skip' else gate


def percentile(values, p):
    """Prespecified nearest-rank empirical quantile, no parametric assumption."""
    return sorted(values)[max(0, math.ceil(p * len(values)) - 1)] if values else None


def validate_data(data, core):
    if data != dataset():
        raise ValueError('Frozen synthetic dataset differs from its authoring source')
    for history in data['histories']:
        if core.machine_gate(history['state']) != history['action']:
            raise ValueError('History action disagrees with the trusted contract')
    for query in data['queries']:
        if core.machine_gate(query['state']) != query['expected']:
            raise ValueError('Query label disagrees with the trusted contract')


def prepare(output, source, evaluator, protocol):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    # Refuse even partial-plan overwrite; leave any interrupted plan auditable.
    if any(output.iterdir()):
        raise ValueError('Preparation needs a new empty output directory')
    provenance = source_provenance(source)
    core = load_module('_memory_core', evaluator)
    data = dataset()
    validate_data(data, core)
    write_once(output / 'dataset.json', data)
    definition = {
        'version': VERSION, 'phase': 'frozen-before-mechanism-outcomes',
        'dataset_sha256': digest(output / 'dataset.json'), 'code_sha256': digest(__file__),
        'protocol_sha256': digest(protocol), 'evaluator_sha256': digest(evaluator),
        'source': provenance, 'threshold': THRESHOLD, 'latency_repetitions': REPETITIONS,
        'history_size': len(data['histories']), 'queries': len(data['queries']),
        'calyx_defaults': {'dense_dim': 64, 'kenyon_cells': 2048, 'active_k': 102,
                           'seed': 42, 'ngram_min': 2, 'ngram_max': 4},
        'tie_break': 'original history order', 'warmup': 'one lookup of the first query per arm',
        'index_policy': 'immutable, built once per arm; no query feedback',
        'measurement': 'actual local lookup only; includes query encoding and search over eight histories',
        'model_calls': 0, 'cloud_spending_usd': 0,
        'simulated_avoidance': 'Each hit is one hypothetical fallback call avoided; no model is invoked or measured. machine_gate alone already resolves every query.',
    }
    write_once(output / 'definition.json', definition)
    return {'definition_sha256': digest(output / 'definition.json'),
            'dataset_sha256': definition['dataset_sha256'], 'queries': definition['queries']}


def verify_definition(output, source, evaluator, protocol):
    definition = json.loads((output / 'definition.json').read_text())
    expected = {'dataset_sha256': digest(output / 'dataset.json'),
                'code_sha256': digest(__file__), 'protocol_sha256': digest(protocol),
                'evaluator_sha256': digest(evaluator), 'threshold': THRESHOLD,
                'latency_repetitions': REPETITIONS, 'source': source_provenance(source)}
    if any(definition.get(key) != value for key, value in expected.items()):
        raise ValueError('Frozen definition drift')
    return definition


def execute(output, source, evaluator, protocol):
    output = Path(output).resolve()
    definition = verify_definition(output, source, evaluator, protocol)
    if any((output / name).exists() for name in ('STARTED.json', 'raw.jsonl', 'summary.json')):
        raise ValueError('Execution already started; preserve it and use a separately versioned run')
    core = load_module('_memory_core', evaluator)
    data = json.loads((output / 'dataset.json').read_text())
    validate_data(data, core)
    write_once(output / 'STARTED.json', {'definition_sha256': digest(output / 'definition.json'),
                                       'time_unix': time.time(), 'pid': os.getpid()})
    wall_start = time.perf_counter()
    cpu_start = time.process_time()
    hash_start = time.perf_counter_ns()
    hasher = load_calyx(source)
    hasher_initialization_ms = (time.perf_counter_ns() - hash_start) / 1e6
    import numpy as np
    if asdict(hasher.config) != definition['calyx_defaults']:
        raise ValueError('Stock hasher configuration drift')
    retrievers = {}
    build_ms = {}
    for arm in ARMS:
        started = time.perf_counter_ns()
        retrievers[arm] = Retriever(arm, data['histories'], hasher)
        build_ms[arm] = (time.perf_counter_ns() - started) / 1e6
        retrievers[arm].lookup(data['queries'][0]['state'])
    histories = {h['id']: h for h in data['histories']}
    raw = []
    # Rotate order by query and repetition to reduce a fixed-order timing bias.
    latencies = {(a, q['id']): [] for a in ARMS for q in data['queries']}
    first = {}
    changes = Counter()
    for repeat in range(REPETITIONS):
        for index, query in enumerate(data['queries']):
            shift = (index + repeat) % len(ARMS)
            for arm in ARMS[shift:] + ARMS[:shift]:
                started = time.perf_counter_ns()
                response = retrievers[arm].lookup(query['state'])
                elapsed = (time.perf_counter_ns() - started) / 1e6
                key = arm, query['id']
                latencies[key].append(elapsed)
                if key not in first:
                    first[key] = response
                elif response != first[key]:
                    changes[arm] += 1
    for query in data['queries']:
        for arm in ARMS:
            response = first[(arm, query['id'])]
            candidate = histories.get(response['candidate_id'])
            recommendation = response['recommendation']
            permitted = enforce(core, query['state'], recommendation)
            expected = query['expected']
            stale_proof = any(e.get('trusted') is True and e.get('revision') != query['state']['current_revision']
                              for e in query['state']['runner_evidence'])
            binding_mismatch = bool(candidate and (
                candidate['state']['current_revision'] != query['state']['current_revision']
                or candidate['state']['unit']['artifact'] != query['state']['unit']['artifact']
                or candidate['state']['unit']['command'] != query['state']['unit']['command']))
            raw.append({'query_id': query['id'], 'family': query['family'], 'arm': arm,
                        **response, 'expected': expected, 'enforced_action': permitted,
                        'raw_unsafe_skip': recommendation == 'skip' and expected != 'skip',
                        'enforced_unsafe_skip': permitted == 'skip' and expected != 'skip',
                        'false_action_reuse': response['hit'] and recommendation != expected,
                        'raw_stale_proof_skip': recommendation == 'skip' and stale_proof,
                        'candidate_binding_mismatch': binding_mismatch,
                        'simulated_fallback_calls_avoided': int(response['hit']),
                        'actual_model_calls_avoided': None,
                        'lookup_latency_ms': latencies[(arm, query['id'])]})
    with (output / 'raw.jsonl').open('x', encoding='utf8') as stream:
        for row in raw:
            stream.write(canonical(row) + '\n')
    metrics = {}
    for arm in ARMS:
        selected = [r for r in raw if r['arm'] == arm]
        samples = [x for r in selected for x in r['lookup_latency_ms']]
        medians = [statistics.median(r['lookup_latency_ms']) for r in selected]
        metrics[arm] = {
            'queries': len(selected), 'history_records': len(data['histories']),
            'candidate_hits': sum(r['hit'] for r in selected),
            'false_action_reuses': sum(r['false_action_reuse'] for r in selected),
            'raw_unsafe_skips': sum(r['raw_unsafe_skip'] for r in selected),
            'raw_stale_proof_skips': sum(r['raw_stale_proof_skip'] for r in selected),
            'candidate_binding_mismatches': sum(r['candidate_binding_mismatch'] for r in selected),
            'enforced_unsafe_skips': sum(r['enforced_unsafe_skip'] for r in selected),
            'safe_enforced_skips': sum(r['enforced_action']=='skip' and r['expected']=='skip' for r in selected),
            'raw_action_matches': sum(r['recommendation']==r['expected'] for r in selected),
            'enforced_action_matches': sum(r['enforced_action']==r['expected'] for r in selected),
            'lookup_samples': len(samples), 'latency_repetitions_per_query': REPETITIONS,
            'lookup_p50_ms': percentile(samples, .50), 'lookup_p95_ms': percentile(samples, .95),
            'per_query_median_p50_ms': percentile(medians, .50),
            'per_query_median_p95_ms': percentile(medians, .95),
            'response_changes_across_repetitions': changes[arm],
            'index_build_ms': build_ms[arm],
            'simulated_fallback_calls_avoided': sum(r['hit'] for r in selected),
            'actual_model_calls_avoided': None, 'actual_token_savings': None,
            'actual_cost_savings_usd': None,
            'families': {family: {'queries': sum(r['family']==family for r in selected),
                                  'candidate_hits': sum(r['family']==family and r['hit'] for r in selected),
                                  'raw_unsafe_skips': sum(r['family']==family and r['raw_unsafe_skip'] for r in selected),
                                  'enforced_unsafe_skips': sum(r['family']==family and r['enforced_unsafe_skip'] for r in selected)}
                         for family in sorted({r['family'] for r in selected})},
        }
    # Directly record the prespecified numeric-value collision, not an optimized search.
    history_text = canonical(histories['h-weave']['state'])
    numeric_query = next(q for q in data['queries'] if q['id']=='q15')
    query_text = canonical(numeric_query['state'])
    collision = {'query_id': 'q15', 'history_id': 'h-weave',
                 'same_dense_features': bool(np.array_equal(hasher.extract_features(history_text), hasher.extract_features(query_text))),
                 'same_active_indices': bool(np.array_equal(hasher.hash_code(history_text).active_indices, hasher.hash_code(query_text).active_indices)),
                 'numeric_token_sets_equal': numeric_tokens(history_text)==numeric_tokens(query_text)}
    safe_queries = sum(q['expected']=='skip' for q in data['queries'])
    summary = {
        'version': VERSION, 'evidence_kind': data['evidence_kind'], 'provisional': True,
        'claim_boundary': 'Preliminary synthetic retrieval mechanism ablation; not Calyx product efficacy, calibration, model savings or task success.',
        'definition_sha256': digest(output/'definition.json'), 'dataset_sha256': definition['dataset_sha256'],
        'raw_sha256': digest(output/'raw.jsonl'), 'source': definition['source'],
        'environment': {'python': sys.version, 'numpy': np.__version__, 'platform': platform.platform(),
                        'blas_threads_requested': {key: os.environ.get(key) for key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS')}},
        'counts': {'history_records': len(histories), 'unique_queries': len(data['queries']),
                   'skip_eligible_queries': safe_queries, 'non_skippable_queries': len(data['queries'])-safe_queries,
                   'recommendation_rows': len(raw), 'total_lookup_timings': len(raw)*REPETITIONS},
        'threshold': THRESHOLD, 'metrics': metrics, 'prespecified_numeric_collision': collision,
        'resources': {'elapsed_seconds': time.perf_counter()-wall_start, 'cpu_seconds': time.process_time()-cpu_start,
                      'calyx_import_and_initialization_ms': hasher_initialization_ms,
                      'projection_array_bytes': int(hasher.projection_matrix.nbytes),
                      'peak_process_memory_bytes': None,
                      'actual_model_calls': 0, 'cloud_cost_usd': 0},
        'deterministic_reference': {'gate_action_matches': len(data['queries']), 'gate_safe_skips': safe_queries,
                                    'model_calls_required_for_this_fixture': 0},
        'limitations': ['Curated paired/corrupted fixtures are dependent and not a population sample.',
                       'Frozen threshold 0.8 was selected as a simple convention, not calibrated or tuned.',
                       'Timing repeats characterize this process only; they do not increase unique query count.',
                       'No persistent Calyx memory, reinforcement, MCP schema cost or remote fallback was exercised.',
                       'A retrieval hit is only a simulated fallback avoidance; trusted machine_gate already decides every case.',
                       'Exact cache is whole-state equality, not a cache of a real measured model response.',
                       'Labels are agent-authored and unreviewed; source commit attribution comes from the prior local review.'],
    }
    write_once(output / 'summary.json', summary)
    failures = []
    for row in raw:
        if row['false_action_reuse'] or row['raw_unsafe_skip']:
            q = next(q for q in data['queries'] if q['id']==row['query_id'])
            failures.append({key: value for key, value in row.items() if key!='lookup_latency_ms'} |
                            {'query_state': q['state'], 'candidate_state': histories[row['candidate_id']]['state']})
    write_once(output / 'failures.json', {'examples': failures, 'status': 'synthetic development mechanism failures'})
    write_once(output / 'COMPLETE.json', {'summary_sha256': digest(output/'summary.json'),
                                        'raw_sha256': digest(output/'raw.jsonl'),
                                        'failures_sha256': digest(output/'failures.json')})
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'run'])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--calyx-source', type=Path, required=True)
    parser.add_argument('--evaluator', type=Path, required=True)
    parser.add_argument('--protocol', type=Path, required=True)
    args = parser.parse_args()
    # Restrict NumPy work to one requested BLAS thread before importing it.
    for key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
        os.environ[key] = '1'
    result = prepare(args.output, args.calyx_source, args.evaluator, args.protocol) if args.command=='prepare' else execute(args.output, args.calyx_source, args.evaluator, args.protocol)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
