"""Offline regression tests; all ledgers are synthetic and temporary."""
import bootstrap  # Establish the unchanged legacy module search path.
import json
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import durability
from adapters import canonical, MODELS
from budget import CampaignBudget
from journal import BudgetExceeded, execute_one
from durability import RecoverableJournal, RecoveryRequired


class DurabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.budget_path = self.base / 'campaign.jsonl'
        self.campaign = CampaignBudget(self.budget_path, '.01', create=True)
        self.path = self.base / 'attempts.jsonl'
        self.scope = 'synthetic:phase:jev'
        self.identity = {'phase': 'synthetic', 'plan_sha256': 'a' * 64}

    def tearDown(self):
        self.campaign.close()
        self.temp.cleanup()

    def open(self, *, create=False, **changes):
        args = dict(campaign=self.campaign, scope=self.scope, identity=self.identity,
                    create=create)
        args.update(changes)
        return RecoverableJournal(self.path, '.01', **args)

    def request(self, journal, key='x', bound='.003', body=None):
        attempt = journal.reserve(key, bound)
        journal.write({'event': 'request', 'key': key, 'attempt': attempt,
                       'arm': 'jev', 'body': {} if body is None else body,
                       'expected_model': MODELS['jev']})
        return attempt

    def complete(self, journal, key='x', bound='.003'):
        return execute_one(journal, key, 'jev', {}, MODELS['jev'], bound,
                           lambda body: {'status': 200, 'body': '{}'})

    def rows(self, path=None):
        return [json.loads(line) for line in (path or self.path).read_text().splitlines()]

    def locked_bytes(self, journal):
        # Windows byte-range locking also excludes other read handles.
        position = journal.file.tell()
        journal.file.seek(0)
        result = journal.file.read()
        journal.file.seek(position)
        return result

    def test_missing_journal_and_binding_fail_closed(self):
        with self.assertRaises(FileNotFoundError):
            self.open()
        self.assertFalse(self.path.exists())
        with self.open(create=True):
            pass
        binding = Path(str(self.path) + '.binding.json')
        binding.rename(self.base / 'preserved-binding.json')
        before = self.path.read_bytes()
        with self.assertRaises(FileNotFoundError):
            self.open()
        self.assertEqual(self.path.read_bytes(), before)

    def test_second_handle_cannot_replay_or_append(self):
        with self.open(create=True) as first:
            before = self.locked_bytes(first)
            with self.assertRaises(OSError):
                self.open()
            self.assertEqual(self.locked_bytes(first), before)
            self.complete(first)

    def test_explicit_creation_cannot_replace_existing_or_scoped_evidence(self):
        with self.open(create=True) as journal:
            self.complete(journal)
        with self.assertRaises(FileExistsError):
            self.open(create=True)
        other = self.base / 'replacement.jsonl'
        with self.assertRaises(RecoveryRequired):
            RecoverableJournal(other, '.01', campaign=self.campaign, scope=self.scope,
                               identity=self.identity, create=True)

    def test_cap_identity_scope_and_campaign_drift_rejected(self):
        with self.open(create=True):
            pass
        for changed in ({'identity': {'phase': 'different'}}, {'scope': 'different'}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.open(**changed)
        with self.assertRaises(ValueError):
            RecoverableJournal(self.path, '.02', campaign=self.campaign,
                               scope=self.scope, identity=self.identity)
        with CampaignBudget(self.base / 'other-campaign.jsonl', '.01', create=True) as other:
            with self.assertRaises(ValueError):
                self.open(campaign=other)

    def test_completed_resume_initializes_campaign_and_can_continue(self):
        with self.open(create=True) as journal:
            self.complete(journal)
        with self.open() as resumed:
            self.assertIs(resumed.campaign, self.campaign)
            self.assertEqual(resumed.scope, self.scope)
            self.assertEqual(resumed.attempts, {'x': 1})
            with self.assertRaises(ValueError):
                self.complete(resumed)
            self.complete(resumed, 'next')
            self.assertEqual(resumed.reserved, Decimal('.006'))
        self.assertEqual(self.campaign.reserved, Decimal('.006'))

    def test_missing_newline_and_partial_json_fail_without_repair(self):
        with self.open(create=True) as journal:
            self.request(journal)
        original = self.path.read_bytes()
        for corrupted in (original.rstrip(b'\r\n'), original + b'{"event":'):
            self.path.write_bytes(corrupted)
            with self.subTest(data=corrupted[-30:]), self.assertRaises(ValueError):
                self.open()
            self.assertEqual(self.path.read_bytes(), corrupted)
        self.path.write_bytes(original)
        with self.open() as journal:
            self.assertEqual(journal.unresolved, {('x', 1)})

    def test_duplicate_reordered_and_forged_events_fail_closed(self):
        with self.open(create=True) as journal:
            self.complete(journal)
        original = self.rows()
        corruptions = [original + [original[-1]],
                       [original[0], original[2], original[1], original[3]],
                       [original[0], {**original[1], 'reserved_total_usd': '.009'}, *original[2:]],
                       original + [{'event': 'surprise', 'key': 'x', 'attempt': 1}]]
        for rows in corruptions:
            data = ''.join(canonical(row) + '\n' for row in rows).encode()
            self.path.write_bytes(data)
            with self.subTest(last=rows[-1]), self.assertRaises(ValueError):
                self.open()
            self.assertEqual(self.path.read_bytes(), data)

    def test_pending_request_requires_explicit_reconciliation_and_stays_unknown(self):
        with self.open(create=True) as journal:
            self.request(journal)
        with self.open() as resumed:
            with self.assertRaises(RecoveryRequired):
                resumed.reserve('new', '.001')
            self.assertEqual(resumed.reconcile('operator-review:synthetic-1'), [('x', 1)])
            self.assertEqual(resumed.reconcile('operator-review:synthetic-1'), [])
            self.assertEqual(resumed.unresolved, set())
            with self.assertRaises(ValueError):
                self.complete(resumed, 'x')
            self.complete(resumed, 'new')
        rows = self.rows()
        interrupted = next(row for row in rows if row.get('error_type') == 'InterruptedProcess')
        self.assertIsNone(interrupted['elapsed_ms'])
        self.assertEqual(interrupted['billing'], 'uncertain')
        self.assertNotIn('status', interrupted)
        self.assertEqual(len(self.rows(Path(str(self.path) + '.recovery.jsonl'))), 2)
        with self.open() as resumed:
            self.assertEqual(resumed.unresolved, set())
            self.assertEqual(resumed.reserved, Decimal('.006'))

    def test_requestless_reservation_never_fabricates_request_or_result(self):
        with self.open(create=True) as journal:
            journal.reserve('x', '.003')
        before = self.path.read_bytes()
        with self.open() as resumed:
            self.assertEqual(resumed.reconcile('synthetic-review'), [])
            self.assertEqual(resumed.unresolved, {('x', 1)})
            with self.assertRaises(RecoveryRequired):
                resumed.reserve('new', '.001')
        self.assertEqual(self.path.read_bytes(), before)

    def test_global_orphan_counts_as_attempted_and_blocks_continuation(self):
        with self.open(create=True):
            pass
        self.campaign.reserve(canonical([self.scope, 'orphan', 1]), '.004')
        with self.open() as resumed:
            self.assertEqual(resumed.orphans, {('orphan', 1)})
            self.assertEqual(resumed.attempts, {'orphan': 1})
            self.assertEqual(resumed.reserved, Decimal('.004'))
            self.assertEqual(resumed.reconcile('synthetic-review'), [])
            with self.assertRaises(RecoveryRequired):
                resumed.reserve('new', '.001')
            with self.assertRaises(ValueError):
                self.complete(resumed, 'orphan')

    def test_global_charge_survives_local_write_failure_and_poisoned_writer(self):
        with self.open(create=True) as journal:
            with patch('durability._append', side_effect=OSError('synthetic fsync failure')):
                with self.assertRaises(OSError):
                    journal.reserve('x', '.006')
            self.assertEqual(self.campaign.reserved, Decimal('.006'))
            with self.assertRaises(RecoveryRequired):
                journal.reserve('next', '.001')
        with self.open() as resumed:
            self.assertEqual(resumed.orphans, {('x', 1)})
            self.assertEqual(resumed.reserved, Decimal('.006'))

    def test_result_failure_after_audit_can_reconcile_idempotently(self):
        with self.open(create=True) as journal:
            self.request(journal)
        append = durability._append
        def fail_result(file, event):
            if event['event'] == 'result':
                raise OSError('synthetic result persistence failure')
            return append(file, event)
        with self.open() as resumed:
            with patch('durability._append', side_effect=fail_result), self.assertRaises(OSError):
                resumed.reconcile('synthetic-review')
        with self.open() as resumed:
            resumed.reconcile('synthetic-review')
        self.assertEqual(len(self.rows(Path(str(self.path) + '.recovery.jsonl'))), 2)
        self.assertEqual(len([r for r in self.rows() if r['event'] == 'result']), 1)

    def test_missing_or_changed_audit_cannot_certify_interrupted_result(self):
        with self.open(create=True) as journal:
            self.request(journal)
            journal.reconcile('synthetic-review')
        audit = Path(str(self.path) + '.recovery.jsonl')
        rows = self.rows(audit)
        rows[-1]['reference'] = 'edited'
        audit.write_text(''.join(canonical(row) + '\n' for row in rows))
        with self.assertRaises(ValueError):
            self.open()

    def test_partial_audit_fails_without_changing_attempt_evidence(self):
        with self.open(create=True) as journal:
            self.request(journal)
        before = self.path.read_bytes()
        audit = Path(str(self.path) + '.recovery.jsonl')
        audit.write_bytes(audit.read_bytes().rstrip(b'\r\n'))
        with self.assertRaises(ValueError):
            self.open()
        self.assertEqual(self.path.read_bytes(), before)

    def test_audit_persistence_failure_never_writes_synthetic_result(self):
        with self.open(create=True) as journal:
            self.request(journal)
        before = self.path.read_bytes()
        with self.open() as resumed:
            with patch('durability._append', side_effect=OSError('synthetic audit failure')):
                with self.assertRaises(OSError):
                    resumed.reconcile('synthetic-review')
            with self.assertRaises(RecoveryRequired):
                resumed.reserve('new', '.001')
        self.assertEqual(self.path.read_bytes(), before)
        with self.open() as resumed:
            self.assertEqual(resumed.reconcile('synthetic-review'), [('x', 1)])

    def test_changed_header_cap_is_rejected_even_when_reservations_fit(self):
        with self.open(create=True):
            pass
        rows = self.rows()
        rows[0]['cap_usd'] = '.02'
        self.path.write_text(''.join(canonical(row) + '\n' for row in rows))
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            self.open()
        self.assertEqual(self.path.read_bytes(), before)

    def test_global_reservation_is_required_for_every_local_attempt(self):
        with self.open(create=True):
            pass
        forged = {'event': 'reserved', 'key': 'fabricated', 'attempt': 1,
                  'bound_usd': '.001', 'reserved_total_usd': '.001'}
        with self.path.open('ab') as file:
            file.write((canonical(forged) + '\n').encode())
        with self.assertRaises(ValueError):
            self.open()

    def test_one_bounded_transient_retry_works_and_reopen_preserves_attempts(self):
        calls = []
        def transport(body):
            calls.append(body)
            return {'status': 503, 'body': '{}', 'retry_after': 0} if len(calls) == 1 else {'status': 200, 'body': '{}'}
        with self.open(create=True) as journal:
            execute_one(journal, 'x', 'jev', {}, MODELS['jev'], '.003', transport, sleep=lambda delay: None)
        self.assertEqual(len(calls), 2)
        with self.open() as resumed:
            self.assertEqual(resumed.attempts, {'x': 2})
            self.assertEqual(resumed.reserved, Decimal('.006'))
            with self.assertRaises(ValueError):
                resumed.reserve('x', '.001')

    def test_unknown_retry_delay_and_unreserved_results_cannot_be_written(self):
        with self.open(create=True) as journal:
            before = self.locked_bytes(journal)
            for event in ({'event': 'retry_delay', 'key': 'x', 'seconds': 1},
                          {'event': 'result', 'key': 'x', 'attempt': 1,
                           'status': 200, 'body': '{}', 'elapsed_ms': 0}):
                with self.assertRaises(ValueError):
                    journal.write(event)
            self.assertEqual(self.locked_bytes(journal), before)

    def test_fresh_scope_and_campaign_reopen_retain_aggregate_cap(self):
        with self.open(create=True) as journal:
            self.complete(journal, bound='.006')
        self.campaign.close()
        self.campaign = CampaignBudget(self.budget_path, '.01')
        other = self.base / 'new-output.jsonl'
        with RecoverableJournal(other, '.01', campaign=self.campaign, scope='another-scope',
                                identity=self.identity, create=True) as journal:
            calls = []
            with self.assertRaises(BudgetExceeded):
                execute_one(journal, 'new', 'jev', {}, MODELS['jev'], '.006',
                            lambda body: calls.append(body))
            self.assertEqual(calls, [])
        self.assertEqual(self.campaign.reserved, Decimal('.006'))

    def test_halt_cannot_be_cleared_by_journal_reopen(self):
        with self.open(create=True):
            pass
        self.campaign.halt()
        self.campaign.close()
        self.campaign = CampaignBudget(self.budget_path, '.01')
        with self.assertRaises(BudgetExceeded):
            self.open()
        self.assertTrue(self.campaign.halted)

    def test_process_crash_releases_locks_preserves_charge_and_unknown_outcome(self):
        self.campaign.close()
        script = '''import bootstrap
import os,sys
from budget import CampaignBudget
from durability import RecoverableJournal
b=CampaignBudget(sys.argv[1],'.01')
j=RecoverableJournal(sys.argv[2],'.01',campaign=b,scope='synthetic:phase:jev',identity={'phase':'synthetic','plan_sha256':'a'*64},create=True)
n=j.reserve('crashed','.004')
j.write({'event':'request','key':'crashed','attempt':n,'arm':'jev','body':{},'expected_model':'jev-1.13.0'})
os._exit(0)
'''
        subprocess.run([sys.executable, '-B', '-c', script, str(self.budget_path), str(self.path)],
                       cwd=Path(__file__).parent, check=True)
        self.campaign = CampaignBudget(self.budget_path, '.01')
        with self.open() as resumed:
            self.assertEqual(resumed.unresolved, {('crashed', 1)})
            self.assertEqual(self.campaign.reserved, Decimal('.004'))
            with self.assertRaises(RecoveryRequired):
                resumed.reserve('another', '.001')

    def test_reconciled_record_remains_compatible_with_frozen_raw_reader(self):
        from development_report import _journal, distribution
        from routing_contract import build
        case = {'id': 'fixture', 'family': 'fixture', 'document': 'Synthetic guide',
                'label': {'action': 'read'}, 'state': {'scope_known': True,
                'unit': {'kind': 'semantic'}, 'current_revision': 'fixture',
                'runner_evidence': [], 'explanation': 'fixture'}}
        with self.open(create=True) as journal:
            self.request(journal, body=build(case, 'jev', 'v1'))
            journal.reconcile('synthetic-review')
        records, order = _journal(self.path, 'jev', MODELS['jev'], {'x': case}, prompt_version='v1')
        self.assertEqual(order, [('x', 1)])
        elapsed = records['x']['attempts'][1]['result']['elapsed_ms']
        self.assertIsNone(elapsed)
        self.assertEqual(distribution([elapsed]), {'measured_n': 0, 'unknown_n': 1,
                                                  'p50_ms': None, 'p95_ms': None})

    def test_secret_redaction_precedes_result_persistence(self):
        with self.open(create=True, secrets=('SYNTHETIC_SECRET',)) as journal:
            execute_one(journal, 'x', 'jev', {}, MODELS['jev'], '.003',
                        lambda body: {'status': 200, 'body': 'SYNTHETIC_SECRET'})
        self.assertNotIn('SYNTHETIC_SECRET', self.path.read_text())
        self.assertIn('[REDACTED]', self.path.read_text())


if __name__ == '__main__':
    unittest.main()
