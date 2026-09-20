"""Outcome-based tests of the actual new coordinator; all providers are fake."""
import json
import os
from collections import Counter
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import bootstrap
from budget import CampaignBudget
from journal import BudgetExceeded
import definition_next
from coordinator import make_plan, run_phase
from fixtures_next import FakeProviders, fake_response, fixture_cases, settings, write_dataset


class SyntheticProcessLoss(BaseException):
    """Simulate process loss past the Exception-level transport failure handler."""


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        # Independent writers may be implementing sibling staging modules. These
        # tests exercise input binding; source-inventory binding has separate tests.
        self.inventory = patch.object(definition_next, 'source_inventory',
                                      return_value={'synthetic-test-inventory': 'a' * 64})
        self.inventory.start()
        self.addCleanup(self.inventory.stop)
        self.dataset = write_dataset(self.root / 'dataset')

    def experiment(self, name='experiment', *, cap='2', policy='deterministic_first', campaign=None):
        if campaign is None:
            campaign_path = self.root / (name + '-campaign.jsonl')
            with CampaignBudget(campaign_path, cap, create=True):
                pass
        else:
            campaign_path, cap = campaign.file.name, str(campaign.cap)
            campaign.close()
        directory = self.root / name
        definition_next.freeze(directory, self.dataset,
                               settings(campaign_path, cap=cap, policy=policy))
        campaign = CampaignBudget(campaign_path, cap)
        self.addCleanup(campaign.close)
        return directory, campaign

    @staticmethod
    def events(path):
        return [json.loads(line) for line in Path(path).read_text(encoding='utf8').splitlines()]

    def test_actual_phases_report_correct_actions_repeats_and_resolved_model(self):
        directory, campaign = self.experiment()
        fake = FakeProviders()
        for phase in ('development', 'calibration'):
            summary = run_phase(directory, phase, fake.transports(), campaign, approved=True)
            self.assertTrue(summary['complete'])
            self.assertEqual(summary['planned_observations'], 12)
            self.assertEqual(summary['recorded_observations'], 12)
            self.assertTrue((directory / phase / 'COMPLETE.json').is_file())
        threshold = definition_next.freeze_thresholds(directory)
        self.assertEqual(threshold['jev']['threshold'], 1.0)
        self.assertEqual(threshold['chat']['threshold'], 1.0)
        before = len(fake.calls)
        summary = run_phase(directory, 'test', fake.transports(), campaign, approved=True)
        self.assertTrue(summary['complete'])
        self.assertEqual(summary['planned_observations'], 36)
        self.assertEqual(len(fake.calls) - before, 18)
        report = definition_next.report(directory, 'test')
        self.assertTrue(report['complete_from_evidence'])
        self.assertEqual(report['n_unique_planned'], 6)
        self.assertIsNone(report['net_tokens_saved'])
        self.assertIsNone(report['task_success'])
        for arm in ('jev', 'chat'):
            observed = report['arms'][arm]
            self.assertEqual(observed['primary_observed_n'], 6)
            self.assertEqual(observed['enforced']['overall']['safe_skips'], 3)
            self.assertEqual(observed['enforced']['overall']['unsafe_skips'], 0)
            self.assertEqual(observed['repeat_stability']['complete_unique'], 6)
            self.assertEqual(observed['repeat_stability']['raw_changed_cases'], 0)
            self.assertEqual(observed['repeat_stability']['enforced_changed_cases'], 0)
            self.assertIsNone(observed['input_proxy'])
        self.assertEqual(report['arms']['chat']['model'], 'openai/gpt-4.1-mini-2025-04-14')

    def test_clean_pause_preserves_full_schedule_and_completed_resume_is_idempotent(self):
        directory, campaign = self.experiment()
        fake = FakeProviders()
        expected_plan = make_plan(directory, 'development')
        first = run_phase(directory, 'development', fake.transports(), campaign,
                          approved=True, stop_after=3)
        self.assertFalse(first['complete'])
        self.assertEqual(first['recorded_observations'], 3)
        self.assertEqual(first['planned_observations'], 12)
        self.assertEqual(make_plan(directory, 'development'), expected_plan)
        final = run_phase(directory, 'development', fake.transports(), campaign,
                          approved=True, resume=True)
        self.assertTrue(final['complete'])
        self.assertEqual(len(fake.calls), 6)
        self.assertTrue(all(n == 1 for n in Counter((c['arm'], c['case_id']) for c in fake.calls).values()))
        reservation = campaign.reserved
        again = run_phase(directory, 'development', fake.transports(), campaign,
                          approved=True, resume=True)
        self.assertTrue(again['complete'])
        self.assertEqual(len(fake.calls), 6)
        self.assertEqual(campaign.reserved, reservation)

    def test_inflight_process_loss_requires_audit_and_never_resends(self):
        directory, campaign = self.experiment()
        fake = FakeProviders()
        real = fake.transports()
        crash_seen = []

        def crash(body):
            crash_seen.append(body)
            raise SyntheticProcessLoss('simulated power loss after request persistence')

        with self.assertRaises(SyntheticProcessLoss):
            run_phase(directory, 'development', {a: crash for a in real}, campaign, approved=True)
        self.assertEqual(len(crash_seen), 1)
        before = campaign.reserved
        with self.assertRaises((ValueError, RuntimeError)):
            run_phase(directory, 'development', real, campaign, approved=True, resume=True)
        self.assertEqual(fake.calls, [])
        self.assertEqual(campaign.reserved, before)
        final = run_phase(directory, 'development', real, campaign, approved=True, resume=True,
                          reconcile_reference='synthetic-test: operator classifies unknown attempt; no resend')
        self.assertTrue(final['complete'])
        self.assertEqual(len(fake.calls), 5)
        interrupted = [e for arm in real for e in self.events(directory / 'development' / (arm + '.jsonl'))
                       if e.get('error_type') == 'InterruptedProcess']
        self.assertEqual(len(interrupted), 1)
        self.assertIsNone(interrupted[0]['elapsed_ms'])
        self.assertEqual(interrupted[0]['billing'], 'uncertain')
        report = definition_next.report(directory, 'development')
        self.assertEqual(len(report['recovery_unknowns']), 1)
        self.assertIsNone(report['recovery_unknowns'][0]['elapsed_ms'])

    def test_missing_started_journal_rejects_resume_without_replacement_dispatch(self):
        directory, campaign = self.experiment()
        fake = FakeProviders()
        run_phase(directory, 'development', fake.transports(), campaign, approved=True, stop_after=4)
        journal = directory / 'development' / 'chat.jsonl'
        journal.rename(journal.with_suffix('.preserved'))
        before_calls, before_reservation = len(fake.calls), campaign.reserved
        with self.assertRaises((ValueError, RuntimeError, FileNotFoundError)):
            run_phase(directory, 'development', fake.transports(), campaign,
                      approved=True, resume=True)
        self.assertEqual(len(fake.calls), before_calls)
        self.assertEqual(campaign.reserved, before_reservation)
        self.assertFalse(journal.exists())

    def test_fresh_run_directory_cannot_reset_existing_campaign_allowance(self):
        first, campaign = self.experiment('first', cap='.010')
        fake = FakeProviders()
        complete = run_phase(first, 'development', fake.transports(), campaign, approved=True)
        self.assertTrue(complete['complete'])
        self.assertEqual(campaign.reserved, Decimal('.00975'))
        second, campaign = self.experiment('second', campaign=campaign)
        before_calls = len(fake.calls)
        try:
            resumed = run_phase(second, 'development', fake.transports(), campaign, approved=True)
        except BudgetExceeded:
            resumed = {'complete': False}
        self.assertFalse(resumed['complete'])
        self.assertLess(len(fake.calls) - before_calls, 6)
        self.assertGreaterEqual(campaign.reserved, Decimal('.00975'))
        self.assertLessEqual(campaign.reserved, Decimal('.010'))

    def test_changed_frozen_dataset_rejected_before_any_dispatch(self):
        directory, campaign = self.experiment()
        path = self.dataset / 'calibration.json'
        changed = json.loads(path.read_text(encoding='utf8'))
        changed[0]['state']['explanation'] = 'Changed after freeze.'
        changed[0]['label']['action'] = 'read'
        path.write_text(json.dumps(changed), encoding='utf8')
        fake = FakeProviders()
        with self.assertRaises(ValueError):
            run_phase(directory, 'calibration', fake.transports(), campaign, approved=True)
        self.assertEqual(fake.calls, [])
        self.assertEqual(campaign.reserved, 0)

    def test_invalid_response_with_valid_usage_stays_review_and_calibration_finishes(self):
        directory, campaign = self.experiment()
        bad = fixture_cases('calibration')[0]
        fake = FakeProviders(overrides={('jev', bad['id']): fake_response('jev', invalid=True)})
        summary = run_phase(directory, 'calibration', fake.transports(), campaign, approved=True)
        self.assertTrue(summary['complete'])
        self.assertEqual(len(fake.calls), 6)
        self.assertFalse(campaign.halted)
        report = definition_next.report(directory, 'calibration')
        self.assertEqual(report['arms']['jev']['invalid_primary_n'], 1)
        row = next(o for o in report['arms']['jev']['observations'] if o['case_id'] == bad['id'])
        self.assertTrue(row['observed'])
        self.assertFalse(row['valid'])
        self.assertEqual(row['action'], 'review')
        self.assertEqual(row['attempts'], 1)
        self.assertEqual(definition_next.freeze_thresholds(directory)['jev']['status'], 'calibration-derived')

    def test_confident_raw_skip_does_not_override_stale_machine_evidence(self):
        directory, campaign = self.experiment(policy='all_cases')
        stale = fixture_cases('development')[4]
        fake = FakeProviders(overrides={('jev', stale['id']): fake_response('jev', 'skip')})
        run_phase(directory, 'development', fake.transports(), campaign, approved=True)
        report = definition_next.report(directory, 'development')
        observed = report['arms']['jev']
        self.assertEqual(observed['raw']['overall']['unsafe_skips'], 1)
        self.assertEqual(observed['enforced']['overall']['unsafe_skips'], 0)
        row = next(o for o in observed['observations'] if o['case_id'] == stale['id'])
        self.assertEqual(row['raw_action'], 'skip')
        self.assertEqual(row['action'], 'run_check')

    def test_access_identity_usage_and_cost_failures_halt_before_next_call(self):
        cases = {
            'access': {'status': 401},
            'identity': {'model': 'unexpected-model'},
            'usage': {'missing_usage': True},
            'cost': {'reported_cost': '9'},
        }
        for name, response_settings in cases.items():
            with self.subTest(failure=name):
                directory, campaign = self.experiment(name)
                calls = []

                def failing(arm):
                    def dispatch(body):
                        calls.append(body)
                        return fake_response(arm, **response_settings)
                    return dispatch

                result = run_phase(directory, 'development',
                                   {arm: failing(arm) for arm in ('jev', 'chat')}, campaign, approved=True)
                self.assertFalse(result['complete'])
                self.assertEqual(len(calls), 1)
                self.assertTrue(campaign.halted)

    def test_transport_coverage_and_approval_fail_before_dispatch(self):
        directory, campaign = self.experiment()
        fake = FakeProviders()
        with self.assertRaises(PermissionError):
            run_phase(directory, 'development', fake.transports(), campaign)
        with self.assertRaises(ValueError):
            run_phase(directory, 'development', fake.transports(('jev',)), campaign, approved=True)
        self.assertEqual(fake.calls, [])
        self.assertEqual(campaign.reserved, 0)

    @unittest.skipUnless(os.environ.get('ALDERTRACE_TOKENIZER_ENV'),
                         'optional existing pinned tokenizer path not supplied')
    def test_validated_tokenizer_uses_real_enforced_skips_and_keeps_negative_proxy(self):
        from measured_tokens import FrozenTokenizer
        environment = Path(os.environ['ALDERTRACE_TOKENIZER_ENV'])
        tokenizer = FrozenTokenizer(environment)
        campaign_path = self.root / 'tokens-campaign.jsonl'
        with CampaignBudget(campaign_path, '2', create=True):
            pass
        directory = self.root / 'tokens-experiment'
        config = settings(campaign_path)
        config['tokenizer_identity'] = tokenizer.identity
        definition_next.freeze(directory, self.dataset, config)
        campaign = CampaignBudget(campaign_path, '2')
        self.addCleanup(campaign.close)
        fake = FakeProviders()
        run_phase(directory, 'calibration', fake.transports(), campaign, approved=True)
        definition_next.freeze_thresholds(directory)
        run_phase(directory, 'test', fake.transports(), campaign, approved=True)
        report = definition_next.report(directory, 'test', environment)
        expected_avoided = sum(len(tokenizer.tokens(c['document'])) for c in fixture_cases('test')
                               if c['state']['unit']['kind'] == 'semantic'
                               and c['label']['action'] == 'skip')
        self.assertGreater(expected_avoided, 0)
        for arm in ('jev', 'chat'):
            proxy = report['arms'][arm]['input_proxy']
            measured = proxy['primary_including_retries']
            self.assertEqual(measured['safely_avoided_reading_tokens'], expected_avoided)
            self.assertLess(measured['net_input_proxy_tokens_saved'], 0)
            self.assertEqual(measured['attempts'], 3)
            self.assertFalse(proxy['h1_eligible'])
        self.assertIsNone(report['net_tokens_saved'])

    @unittest.skipUnless(os.environ.get('ALDERTRACE_TOKENIZER_ENV'),
                         'optional existing pinned tokenizer path not supplied')
    def test_transient_retry_counts_each_primary_request_in_observable_input_proxy(self):
        from adapters import canonical
        from measured_tokens import FrozenTokenizer
        from routing_contract import build
        environment = Path(os.environ['ALDERTRACE_TOKENIZER_ENV'])
        tokenizer = FrozenTokenizer(environment)
        campaign_path = self.root / 'retry-campaign.jsonl'
        with CampaignBudget(campaign_path, '2', create=True):
            pass
        directory = self.root / 'retry-experiment'
        config = settings(campaign_path)
        config['tokenizer_identity'] = tokenizer.identity
        definition_next.freeze(directory, self.dataset, config)
        campaign = CampaignBudget(campaign_path, '2')
        self.addCleanup(campaign.close)
        fake = FakeProviders()
        run_phase(directory, 'calibration', fake.transports(), campaign, approved=True)
        definition_next.freeze_thresholds(directory)
        case = fixture_cases('test')[0]
        pending = [True]

        def fail_once(body):
            if pending:
                pending.pop()
                return {'status': 503, 'body': '{}', 'elapsed_ms': 0.0, 'retry_after': 0.0}
            return None

        fake.overrides[('jev', case['id'])] = fail_once
        run_phase(directory, 'test', fake.transports(), campaign, approved=True)
        report = definition_next.report(directory, 'test', environment)
        jev = report['arms']['jev']
        self.assertEqual(jev['retries'], 1)
        proxy = jev['input_proxy']['primary_including_retries']
        self.assertEqual(proxy['attempts'], 4)
        expected = sum(len(tokenizer.tokens(canonical(build(c, 'jev', 'v2'))))
                       for c in fixture_cases('test') if c['state']['unit']['kind'] == 'semantic')
        repeated = len(tokenizer.tokens(canonical(build(case, 'jev', 'v2'))))
        self.assertEqual(proxy['routing_input_proxy_tokens'], expected + repeated)
        self.assertEqual(report['arms']['chat']['input_proxy']['primary_including_retries']['attempts'], 3)
        self.assertIsNone(report['net_tokens_saved'])


if __name__ == '__main__':
    unittest.main()
