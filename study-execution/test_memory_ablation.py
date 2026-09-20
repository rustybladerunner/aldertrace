"""Offline regression tests for memory authority and frozen-run boundaries."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import memory_ablation as m


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.data = m.dataset()
        self.queries = {q['id']: q for q in self.data['queries']}

    def test_exact_cache_rejects_changed_outcome_and_revision(self):
        exact = m.Retriever('exact_cache', self.data['histories'])
        self.assertTrue(exact.lookup(self.queries['q01']['state'])['hit'])
        for q in ('q15', 'q16', 'q17', 'q18', 'q21'):
            with self.subTest(query=q):
                self.assertFalse(exact.lookup(self.queries[q]['state'])['hit'])

    def test_exact_cache_preserves_saved_failure(self):
        exact = m.Retriever('exact_cache', self.data['histories'])
        result = exact.lookup(self.queries['q05']['state'])
        self.assertTrue(result['hit'])
        self.assertEqual(result['recommendation'], 'run_check')

    def test_numeric_baseline_does_not_discard_numeric_changes(self):
        good = m.canonical(self.queries['q01']['state'])
        failed = m.canonical(self.queries['q15']['state'])
        self.assertNotEqual(m.numeric_tokens(good), m.numeric_tokens(failed))
        self.assertLess(m.jaccard(m.numeric_tokens(good), m.numeric_tokens(failed)), 1)
        self.assertIn('410', m.numeric_tokens(good))
        self.assertIn('1', m.numeric_tokens(failed))

    def test_no_memory_cannot_reuse_or_build_an_index(self):
        empty = m.Retriever('no_memory', self.data['histories'])
        self.assertEqual(empty.texts, [])
        result = empty.lookup(self.queries['q01']['state'])
        self.assertFalse(result['hit'])
        self.assertEqual(result['recommendation'], 'review')

    def test_labels_are_not_part_of_lookup_payload(self):
        for row in self.data['histories'] + self.data['queries']:
            text = m.canonical(row['state'])
            self.assertNotIn('"expected":', text)
            self.assertNotIn('"action":', text)
            self.assertNotIn('"family":', text)

    def test_low_similarity_abstains_and_ties_use_history_order(self):
        history = self.data['histories'][0]
        duplicate = copy.deepcopy(history)
        duplicate['id'] = 'later-duplicate'
        duplicate['action'] = 'review'
        retriever = m.Retriever('token_jaccard', [history, duplicate])
        result = retriever.lookup(history['state'])
        self.assertEqual(result['candidate_id'], history['id'])
        self.assertEqual(result['recommendation'], 'skip')
        self.assertFalse(retriever.lookup({'completely': 'unrelated vocabulary'})['hit'])

    def test_percentile_is_nearest_rank(self):
        self.assertEqual(m.percentile([9, 1, 4, 2], .50), 2)
        self.assertEqual(m.percentile([9, 1, 4, 2], .95), 9)


class FrozenOutputTests(unittest.TestCase):
    def test_write_once_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'evidence.json'
            m.write_once(target, {'original': True})
            with self.assertRaises(FileExistsError):
                m.write_once(target, {'replacement': True})
            self.assertEqual(json.loads(target.read_text()), {'original': True})

    def test_missing_or_changed_pinned_source_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                m.source_provenance(directory)
            for name in m.SOURCE_HASHES:
                path = Path(directory) / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('changed source')
            with self.assertRaisesRegex(ValueError, 'hashes'):
                m.source_provenance(directory)

    def test_definition_rejects_threshold_drift_before_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            m.write_once(root / 'dataset.json', m.dataset())
            fields = {'dataset_sha256': m.digest(root / 'dataset.json'),
                      'code_sha256': m.digest(m.__file__), 'protocol_sha256': 'p',
                      'evaluator_sha256': 'e', 'threshold': .79,
                      'latency_repetitions': m.REPETITIONS, 'source': {'fake': True}}
            m.write_once(root / 'definition.json', fields)
            original_digest = m.digest
            def hashes(path):
                return {'protocol': 'p', 'evaluator': 'e'}.get(str(path)) or original_digest(path)
            with patch.object(m, 'source_provenance', return_value={'fake': True}), patch.object(m, 'digest', side_effect=hashes):
                with self.assertRaisesRegex(ValueError, 'definition drift'):
                    m.verify_definition(root, 'source', 'evaluator', 'protocol')
            self.assertFalse((root/'STARTED.json').exists())


@unittest.skipUnless(os.environ.get('ALDERTRACE_EVALUATOR'), 'Set ALDERTRACE_EVALUATOR for the existing frozen evaluator')
class AuthorityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.core = m.load_module('_memory_test_core', Path(os.environ['ALDERTRACE_EVALUATOR']))

    def test_author_labels_agree_with_unmodified_machine_gate(self):
        m.validate_data(m.dataset(), self.core)

    def test_every_prohibited_query_blocks_reused_skip(self):
        for query in m.dataset()['queries']:
            if query['expected'] != 'skip':
                with self.subTest(query=query['id']):
                    self.assertNotEqual(m.enforce(self.core, query['state'], 'skip'), 'skip')

    def test_valid_gate_does_not_upgrade_a_memory_miss(self):
        query = m.dataset()['queries'][0]
        self.assertEqual(self.core.machine_gate(query['state']), 'skip')
        self.assertEqual(m.enforce(self.core, query['state'], 'review'), 'review')


@unittest.skipUnless(os.environ.get('CALYX_REVIEW_SOURCE'), 'Set CALYX_REVIEW_SOURCE for the pinned source collision regression')
class StockHasherTests(unittest.TestCase):
    def test_numeric_collision_is_visible_without_loading_services(self):
        before = set(sys.modules)
        hasher = m.load_calyx(Path(os.environ['CALYX_REVIEW_SOURCE']))
        data = m.dataset()
        one = m.canonical(data['queries'][0]['state'])
        failed = m.canonical(next(q['state'] for q in data['queries'] if q['id']=='q15'))
        import numpy as np
        self.assertTrue(np.array_equal(hasher.extract_features(one), hasher.extract_features(failed)))
        self.assertEqual(hasher.calculate_hamming_similarity(hasher.hash_code(one), hasher.hash_code(failed)), 1.0)
        added = set(sys.modules) - before
        self.assertFalse(any(name.startswith('calyx_mcp') for name in added))
        self.assertFalse(any(name.endswith(('.server', '.memory', '.installer')) for name in added))


if __name__ == '__main__':
    unittest.main()
