"""Subprocess tests of the real entry point; no real provider is reachable."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import bootstrap


class EntryPointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.inputs = self.root / 'inputs'
        self.experiment = self.root / 'experiment'
        self.command('fixture', '--output', self.inputs)
        self.command('freeze', '--experiment', self.experiment,
                     '--dataset', self.inputs / 'dataset', '--settings', self.inputs / 'settings.json')

    def command(self, *args, expected=0):
        env = dict(os.environ, ALDERTRACE_SOURCE_ROOT=str(bootstrap.SOURCE_ROOT))
        proc = subprocess.run([sys.executable, '-B', str(Path(__file__).with_name('run.py')),
                               *map(str, args)], capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(proc.returncode, expected, proc.stderr)
        return json.loads(proc.stdout) if expected == 0 else proc.stderr

    def test_real_cli_plans_without_dispatch_then_runs_freezes_and_replays(self):
        result = self.command('run', '--experiment', self.experiment, '--phase', 'calibration')
        self.assertFalse(result['execution'])
        self.assertFalse((self.experiment / 'calibration').exists())
        for phase in ('calibration', 'test'):
            result = self.command('run', '--experiment', self.experiment, '--phase', phase,
                                  '--execute', '--simulate', '--approval-reference', 'offline-regression')
            self.assertTrue(result['summary']['complete'])
            self.assertEqual(result['fake_dispatches_this_invocation'], 6 if phase == 'calibration' else 18)
            if phase == 'calibration':
                lock = self.command('freeze-thresholds', '--experiment', self.experiment)
                self.assertEqual(lock['jev']['threshold'], 1.0)
                again = self.command('freeze-thresholds', '--experiment', self.experiment)
                self.assertEqual(again, lock)
        report = self.command('report', '--experiment', self.experiment, '--phase', 'test')
        self.assertTrue(report['complete_from_evidence'])
        self.assertEqual(report['n_unique_planned'], 6)
        self.assertEqual(report['arms']['jev']['enforced']['overall']['safe_skips'], 3)
        self.assertEqual(report['arms']['jev']['enforced']['overall']['unsafe_skips'], 0)
        self.assertEqual(report['arms']['chat']['repeat_stability']['complete_unique'], 6)
        self.assertIsNone(report['net_tokens_saved'])
        self.assertEqual(report['purpose'], 'instrument-test')

    def test_real_cli_pause_resume_and_completed_idempotence(self):
        common = ('run', '--experiment', self.experiment, '--phase', 'development',
                  '--execute', '--simulate', '--approval-reference', 'offline-regression')
        first = self.command(*common, '--stop-after', '3')
        self.assertFalse(first['summary']['complete'])
        self.assertEqual(first['summary']['recorded_observations'], 3)
        final = self.command(*common, '--resume')
        self.assertTrue(final['summary']['complete'])
        repeated = self.command(*common, '--resume')
        self.assertEqual(repeated['fake_dispatches_this_invocation'], 0)
        self.assertEqual(repeated['summary'], final['summary'])

    def test_cli_nonzero_errors_and_no_implicit_live_path(self):
        common = ('run', '--experiment', self.experiment, '--phase', 'development', '--execute')
        self.assertIn('approval', self.command(*common, '--simulate', expected=2))
        self.assertIn('simulation only', self.command(*common, '--approval-reference', 'offline', expected=2))
        self.assertFalse((self.experiment / 'development').exists())
        self.command('run', '--experiment', self.experiment, '--phase', 'test', expected=2)
        self.assertFalse((self.experiment / 'test').exists())
        ledger = (self.inputs / 'SIMULATED-campaign.jsonl').read_text(encoding='utf8').splitlines()
        self.assertEqual(len(ledger), 1)


class SummarySnapshotTests(unittest.TestCase):
    def test_repeated_snapshot_finalization_preserves_identical_bytes(self):
        from coordinator import _save_summary
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            value = {'schema': 2, 'complete': False, 'rows': [], 'stopped': 'interrupted'}
            _save_summary(directory, value)
            snapshot, = directory.glob('summary-*.json')
            original = snapshot.read_bytes()
            _save_summary(directory, value)
            self.assertEqual(snapshot.read_bytes(), original)
            self.assertEqual((directory / 'summary.json').read_bytes(), original)
            self.assertEqual(len(list(directory.glob('summary-*.json'))), 1)


if __name__ == '__main__':
    unittest.main()
