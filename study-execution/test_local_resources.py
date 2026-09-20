import json
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from local_resources import (LocalBudget, LocalBudgetExceeded, ResourceContention,
                             ResourceGuard, ResourceProbeUnavailable, probe_nvidia_smi)


class LocalBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'local-seconds.jsonl'
        self.now = 100.0

    def tearDown(self):
        self.tmp.cleanup()

    def open(self, **kwargs):
        return LocalBudget(self.path, clock=lambda: self.now, **kwargs)

    def test_elapsed_is_aggregate_across_runs_pending_is_conservative(self):
        with self.open(create=True) as budget:
            budget.reserve('first', 180)
            self.now += 4
            self.assertEqual(budget.complete('first'), Decimal('4'))
            budget.reserve('interrupted', 180)
        with self.open() as budget:
            self.assertEqual(budget.used, 184)
            self.assertEqual(budget.remaining, 3416)
            with self.assertRaises(ValueError):
                budget.complete('interrupted', 1)
            budget.reserve('next-run', 60)
            budget.complete('next-run', 12)
            self.assertEqual(budget.used, 196)

    def test_reserved_duration_blocks_dispatch_before_cap(self):
        with self.open(create=True) as budget:
            budget.reserve('a', 3550)
            with self.assertRaises(LocalBudgetExceeded):
                budget.reserve('b', 51)
            self.assertEqual(budget.used, 3550)
            budget.reserve('at-limit', 50)
            self.assertEqual(budget.remaining, 0)

    def test_supplied_elapsed_cannot_reduce_observed_charge(self):
        with self.open(create=True) as budget:
            budget.reserve('request', 60)
            self.now += 10
            budget.complete('request', 2)
            self.assertEqual(budget.used, 10)

    def test_failed_or_invalid_response_charged_by_finally(self):
        with self.open(create=True) as budget:
            budget.reserve('invalid-json', 60)
            try:
                self.now += 5
                raise ValueError('invalid response')
            except ValueError:
                pass
            finally:
                budget.complete('invalid-json')
            self.assertEqual(budget.used, 5)

    def test_overrun_is_fully_recorded_and_halts_even_after_reopen(self):
        with self.open(create=True) as budget:
            budget.reserve('slow', 60)
            self.now += 75
            with self.assertRaises(LocalBudgetExceeded):
                budget.complete('slow')
            self.assertEqual(budget.used, 75)
        with self.open() as budget:
            self.assertTrue(budget.halted)
            self.assertEqual(budget.used, 75)
            with self.assertRaises(LocalBudgetExceeded):
                budget.reserve('later', 1)

    def test_cap_recreation_missing_and_invalid_numbers_refused(self):
        with self.assertRaises(FileNotFoundError):
            self.open()
        with self.open(create=True):
            pass
        with self.assertRaises(FileExistsError):
            self.open(create=True)
        for cap in (1, 3601, float('nan'), float('inf'), -1, True):
            with self.subTest(cap=cap), self.assertRaises(ValueError):
                LocalBudget(self.path, cap)
        with self.open() as budget:
            for amount in (0, -1, float('nan'), float('inf'), 'NaN', True):
                with self.subTest(amount=amount), self.assertRaises(ValueError):
                    budget.reserve('bad', amount)

    def test_corrupt_partial_duplicate_nonfinite_and_wrong_total_refused(self):
        with self.open(create=True) as budget:
            budget.reserve('a', 60)
        original = self.path.read_bytes()
        bad = (original[:-1], original + b'{bad}\n',
               original.replace(b'"used_seconds":"60"', b'"used_seconds":"1"'),
               original.replace(b'"timeout_seconds":"60"', b'"timeout_seconds":"NaN"'),
               original.replace(b'"key":"a"', b'"key":"a","key":"b"'),
               original.replace(b'"used_seconds":"60"', b'"used_seconds":NaN'),
               original.replace(b'"schema":1', b'"schema":true'))
        for data in bad:
            self.path.write_bytes(data)
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.open()

    def test_duplicate_and_unreserved_completion_refused(self):
        with self.open(create=True) as budget:
            budget.reserve('a', 60)
            budget.complete('a', 1)
            with self.assertRaises(ValueError):
                budget.reserve('a', 60)
            with self.assertRaises(ValueError):
                budget.complete('a', 1)
            with self.assertRaises(ValueError):
                budget.complete('absent', 1)

    def test_clock_failure_retains_full_reservation(self):
        with self.open(create=True) as budget:
            budget.reserve('a', 60)
            self.now = float('nan')
            with self.assertRaises(ValueError):
                budget.complete('a')
        self.now = 200
        with self.open() as budget:
            self.assertEqual(budget.used, 60)

    def test_persistence_failure_disables_session(self):
        with self.open(create=True) as budget:
            with patch('local_resources.os.fsync', side_effect=OSError('disk failure')):
                with self.assertRaises(OSError):
                    budget.reserve('uncertain', 60)
            with self.assertRaises(LocalBudgetExceeded):
                budget.reserve('later', 60)
        with self.open() as budget:
            self.assertEqual(budget.used, 60)

    def test_process_crash_releases_lock_but_keeps_reservation(self):
        script = ('import os,sys; from local_resources import LocalBudget; '
                  'b=LocalBudget(sys.argv[1],create=True); b.reserve("crash",180); os._exit(0)')
        subprocess.run([sys.executable, '-B', '-c', script, str(self.path)],
                       cwd=Path(__file__).parent, check=True)
        with self.open() as budget:
            self.assertEqual(budget.used, 180)
            with self.assertRaises(ValueError):
                budget.complete('crash', 1)

    def test_other_process_cannot_write(self):
        with self.open(create=True):
            script = ('import sys\nfrom local_resources import LocalBudget\n'
                      'try: LocalBudget(sys.argv[1])\nexcept OSError: sys.exit(0)\nsys.exit(9)')
            result = subprocess.run([sys.executable, '-B', '-c', script, str(self.path)],
                                    cwd=Path(__file__).parent)
            self.assertEqual(result.returncode, 0)

    def test_resource_halt_is_persistent(self):
        with self.open(create=True) as budget:
            budget.reserve('interrupted', 60)
            budget.halt()
        with self.open() as budget:
            self.assertEqual(budget.used, 60)
            with self.assertRaises(LocalBudgetExceeded):
                budget.reserve('later', 60)


class ResourceProbeTests(unittest.TestCase):
    def probe(self, output):
        return probe_nvidia_smi(which=lambda _: 'fake-nvidia-smi',
                                run=lambda *a, **k: SimpleNamespace(stdout=output))

    def test_valid_probe_and_default_guard(self):
        samples = self.probe('0, GPU-example, 4, 1000, 8192\n')
        self.assertEqual(samples[0]['memory_free_mib'], 7192)
        self.assertEqual(ResourceGuard(probe=lambda: samples).check(), samples)

    def test_missing_failed_and_unknown_probe_fail_closed(self):
        with self.assertRaises(ResourceProbeUnavailable):
            probe_nvidia_smi(which=lambda _: None)
        def timeout(*a, **k):
            raise subprocess.TimeoutExpired('nvidia-smi', 5)
        with self.assertRaises(ResourceProbeUnavailable):
            probe_nvidia_smi(which=lambda _: 'fake', run=timeout)
        for output in ('', '0, GPU-example, N/A, 1000, 8192\n',
                       '0, GPU-example, NaN, 1000, 8192\n',
                       '0, GPU-example, 4, 9000, 8192\n',
                       '0, GPU-example, 4, 1000, 8192\n0, GPU-example, 4, 1000, 8192\n'):
            with self.subTest(output=output), self.assertRaises(ResourceProbeUnavailable):
                self.probe(output)

    def test_contention_utilization_and_memory(self):
        for output in ('0, GPU-example, 26, 1000, 8192\n',
                       '0, GPU-example, 0, 7000, 8192\n'):
            with self.subTest(output=output), self.assertRaises(ResourceContention):
                ResourceGuard(probe=lambda: self.probe(output)).check()

    def test_invalid_guard_policy_or_custom_probe_fails_closed(self):
        for kwargs in ({'max_utilization_percent': float('nan')}, {'min_free_mib': -1},
                       {'max_utilization_percent': True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                ResourceGuard(**kwargs)
        for samples in ([], [{}], [{'utilization_percent': float('nan'), 'memory_free_mib': 8000}]):
            with self.subTest(samples=samples), self.assertRaises(ResourceProbeUnavailable):
                ResourceGuard(probe=lambda: samples).check()


if __name__ == '__main__':
    unittest.main()
