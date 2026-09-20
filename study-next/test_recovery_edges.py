"""Crash-boundary regressions against the actual coordinator; fake providers only."""
import json
from collections import Counter
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import bootstrap
from budget import CampaignBudget
from journal import execute_one
from durability import RecoveryRequired
import coordinator
import definition_next
from fixtures_next import FakeProviders, fake_response, settings, write_dataset


class SyntheticProcessLoss(BaseException):
    """Bypass Exception-only transport handling to model interrupted execution."""


class RecoveryEdgeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        inventory = patch.object(definition_next, 'source_inventory', return_value={
            'synthetic-recovery-test-inventory': 'b' * 64})
        inventory.start()
        self.addCleanup(inventory.stop)
        dataset = write_dataset(self.root / 'dataset')
        campaign_path = self.root / 'campaign.jsonl'
        with CampaignBudget(campaign_path, '2', create=True):
            pass
        self.experiment = self.root / 'experiment'
        definition_next.freeze(self.experiment, dataset,
                               settings(campaign_path, policy='all_cases'))
        self.campaign = CampaignBudget(campaign_path, '2')
        self.addCleanup(self.campaign.close)
        self.plan = coordinator.make_plan(self.experiment, 'development')

    def run_phase(self, providers, **kwargs):
        return coordinator.run_phase(self.experiment, 'development', providers,
                                     self.campaign, approved=True, **kwargs)

    def journal_events(self, arm):
        path = self.experiment / 'development' / (arm + '.jsonl')
        return [json.loads(line) for line in path.read_text(encoding='utf8').splitlines()]

    def test_successful_response_before_observation_loss_is_not_resent_and_time_stays_unknown(self):
        fake = FakeProviders()
        first = self.plan['rows'][0]
        with patch('coordinator._append_observation', side_effect=SyntheticProcessLoss('after raw result fsync')):
            with self.assertRaises(SyntheticProcessLoss):
                self.run_phase(fake.transports())
        self.assertEqual(len(fake.calls), 1)
        self.assertFalse(self.campaign.halted)
        results = [e for e in self.journal_events(first['arm']) if e['event'] == 'result']
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['status'], 200)
        self.assertIsInstance(results[0]['elapsed_ms'], (int, float))

        final = self.run_phase(fake.transports(), resume=True)
        self.assertTrue(final['complete'])
        self.assertEqual(final['completed_observations'], len(self.plan['rows']))
        self.assertEqual(final['recorded_observations'], len(self.plan['rows']) - 1)
        counts = Counter((call['arm'], call['case_id']) for call in fake.calls)
        self.assertEqual(len(fake.calls), len(self.plan['rows']))
        self.assertTrue(all(value == 1 for value in counts.values()))

        report = definition_next.report(self.experiment, 'development')
        observed = next(row for row in report['arms'][first['arm']]['observations']
                        if row['key'] == first['key'])
        self.assertTrue(observed['observed'])
        self.assertTrue(observed['valid'])
        self.assertIsNone(observed['end_to_end_ms'])
        self.assertEqual(report['recovery_unknowns'], [])  # Raw receipt was never lost.
        self.run_phase(fake.transports(), resume=True)
        self.assertEqual(len(fake.calls), len(self.plan['rows']))

    def test_second_retry_inflight_loss_can_be_audited_without_resending_that_key(self):
        first = self.plan['rows'][0]
        dispatched = []
        def unreliable(arm):
            def send(body):
                dispatched.append((arm, body))
                if len(dispatched) == 1:
                    result = fake_response(arm, status=503)
                    result['retry_after'] = 0
                    return result
                raise SyntheticProcessLoss('after second request fsync')
            return send
        def execute_without_wait(*args, **kwargs):
            return execute_one(*args, **kwargs, sleep=lambda delay: None)
        with patch('coordinator.execute_one', side_effect=execute_without_wait):
            with self.assertRaises(SyntheticProcessLoss):
                self.run_phase({arm: unreliable(arm) for arm in self.plan['models']})
        self.assertEqual(len(dispatched), 2)
        self.assertEqual(dispatched[0], dispatched[1])
        self.assertFalse(self.campaign.halted)

        fake = FakeProviders()
        final = self.run_phase(fake.transports(), resume=True,
                               reconcile_reference='synthetic operator review: retain uncertain retry charge')
        self.assertTrue(final['complete'])
        self.assertFalse(self.campaign.halted)
        self.assertEqual(len(fake.calls), len(self.plan['rows']) - 1)
        self.assertNotIn((first['arm'], first['case_id']),
                         {(call['arm'], call['case_id']) for call in fake.calls})
        events = [event for event in self.journal_events(first['arm'])
                  if event.get('key') == first['key'] and event['event'] == 'result']
        self.assertEqual([event['attempt'] for event in events], [1, 2])
        self.assertEqual(events[0]['status'], 503)
        self.assertEqual(events[1]['error_type'], 'InterruptedProcess')
        self.assertIsNone(events[1]['elapsed_ms'])
        self.assertEqual(events[1]['billing'], 'uncertain')
        report = definition_next.report(self.experiment, 'development')
        self.assertEqual(len(report['recovery_unknowns']), 1)
        self.assertEqual(report['recovery_unknowns'][0]['attempt'], 2)

    def test_impossible_paused_timing_is_rejected_before_any_further_dispatch(self):
        fake = FakeProviders()
        transports = fake.transports()
        def delayed(transport):
            def send(body):
                time.sleep(.01)
                return transport(body)
            return send
        initial = self.run_phase({arm: delayed(send) for arm, send in transports.items()}, stop_after=1)
        self.assertFalse(initial['complete'])
        self.assertEqual(len(fake.calls), 1)
        path = self.experiment / 'development' / 'observations.jsonl'
        row = json.loads(path.read_text(encoding='utf8'))
        self.assertGreater(row['end_to_end_ms'], 2)
        row['end_to_end_ms'] = 0
        path.write_text(json.dumps(row) + '\n', encoding='utf8')
        before_calls, before_reserved = len(fake.calls), self.campaign.reserved
        with self.assertRaisesRegex(ValueError, 'timing is shorter'):
            self.run_phase(transports, resume=True)
        self.assertEqual(len(fake.calls), before_calls)
        self.assertEqual(self.campaign.reserved, before_reserved)

    def test_lost_observation_cannot_hide_over_budget_receipt_from_resume_safety(self):
        first = self.plan['rows'][0]
        fake = FakeProviders(overrides={
            (first['arm'], first['case_id']): fake_response(first['arm'], reported_cost='9')})
        def die_after_receipt(*args, **kwargs):
            execute_one(*args, **kwargs)
            raise SyntheticProcessLoss('raw receipt saved before coordinator usage validation')
        with patch('coordinator.execute_one', side_effect=die_after_receipt):
            with self.assertRaises(SyntheticProcessLoss):
                self.run_phase(fake.transports())
        self.assertEqual(len(fake.calls), 1)
        self.assertFalse(self.campaign.halted)
        next_fake = FakeProviders()
        before_reserved = self.campaign.reserved
        with self.assertRaisesRegex(RecoveryRequired, 'usage unavailable or outside reservation'):
            self.run_phase(next_fake.transports(), resume=True)
        self.assertEqual(next_fake.calls, [])
        self.assertEqual(self.campaign.reserved, before_reserved)
        self.assertTrue(self.campaign.halted)


if __name__ == '__main__':
    unittest.main()
