from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from demo import Receipt, accounting, demonstrate, enforce, run_check


class EvidenceBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='jev-demo-test-')
        self.addCleanup(self.temporary.cleanup)
        self.file = Path(self.temporary.name)/'fixture.json'
        self.file.write_text('{"enabled": true, "version": 2}', encoding='utf8')

    def test_actual_check_then_edit_invalidates_proof(self):
        receipt = run_check(self.file)
        self.assertEqual(enforce('skip', self.file, receipt)[0], 'skip')
        self.file.write_text('{"enabled": false, "version": 2}', encoding='utf8')
        self.assertEqual(enforce('skip', self.file, receipt)[0], 'review')

    def test_serialized_proof_cannot_be_promoted_to_runner_receipt(self):
        claimed = run_check(self.file).__dict__
        self.assertEqual(enforce('skip', self.file, claimed)[0], 'review')

    def test_failed_check_and_checker_substitution_are_rejected(self):
        self.file.write_text('{}', encoding='utf8')
        failed = run_check(self.file)
        self.assertNotEqual(failed.exit_code, 0)
        self.assertEqual(enforce('skip', self.file, failed)[0], 'review')
        self.assertEqual(enforce('skip', self.file, replace(failed, exit_code=0, checker_sha256='0'*64))[0], 'review')

    def test_lookalike_json_types_do_not_pass_the_prerequisite(self):
        for value in ('{"enabled": 1, "version": 2}', '{"enabled": true, "version": 2.0}',
                      '{"enabled": true, "version": true}'):
            self.file.write_text(value, encoding='utf8')
            self.assertNotEqual(run_check(self.file).exit_code, 0)

    def test_no_skip_recommendation_is_not_promoted_by_valid_receipt(self):
        self.assertEqual(enforce('read', self.file, run_check(self.file))[0], 'review')

    def test_overhead_includes_rejected_recommendations(self):
        result = demonstrate()
        self.assertEqual(result['rejected_skips'], 4)
        self.assertEqual(result['accounting']['illustrative_net_input_saved'], -100)
        self.assertIsNone(result['accounting']['actual_model_tokens'])

    def test_invalid_accounting_inputs_do_not_become_savings(self):
        for bad in (-1, True, float('nan')):
            with self.assertRaises(ValueError):
                accounting([{'enforced':'skip','illustrative_read_tokens':500,'illustrative_routing_tokens':bad}])


if __name__ == '__main__':
    unittest.main()
