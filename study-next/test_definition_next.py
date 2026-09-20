"""Synthetic freeze/replay regressions; never creates live providers."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import ExitStack

import definition_next as target
from bootstrap import SOURCE_ROOT
from adapters import canonical, strict_json
from budget import CampaignBudget
from durability import RecoverableJournal
from locks import sha, write_once
from routing_contract import build
from fixtures_next import write_dataset, settings, fake_response


class DefinitionNextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.dataset = write_dataset(self.base / 'dataset')
        self.campaign = self.base / 'campaign.jsonl'
        with CampaignBudget(self.campaign, '2', create=True):
            pass
        self.settings = settings(self.campaign)
        self.directory = self.base / 'experiment'
        # Isolate unit fixtures from unrelated source edits by parallel implementers.
        inventory = patch.object(target, 'source_inventory', return_value={'fixture.py': 'a' * 64})
        inventory.start()
        self.addCleanup(inventory.stop)

    def freeze(self):
        return target.freeze(self.directory, self.dataset, self.settings)

    def phase(self, phase, *, invalid=False, interrupted=False, unresolved=False):
        """Write independent mock journal evidence matching the public schema."""
        frozen = target.verify(self.directory)
        config = frozen['settings']
        cases, digest, models = target.phase_inputs(self.directory, phase)
        ordered = sorted(cases, key=lambda c: hashlib.sha256(('20260919:' + c['id']).encode()).hexdigest())
        repeat_ids = set()
        if phase == 'test':
            for family in {c['family'] for c in ordered}:
                repeat_ids.update(c['id'] for c in [c for c in ordered if c['family'] == family][:5])
        threshold = ({arm: None for arm in models} if phase == 'calibration' else
                     {arm: strict_json((self.directory / 'thresholds.json').read_text())['arms'][arm]['threshold']
                      for arm in models} if phase == 'test' else 0.0)
        destination = self.directory / phase
        destination.mkdir()
        plan = {'schema': 3, 'phase': phase, 'freeze_sha256': sha(self.directory / 'freeze.json'),
                'case_ids': [c['id'] for c in ordered], 'models': models,
                'journals': {arm: arm + '.jsonl' for arm in models},
                'policy': config['policy'], 'prompt_version': config['prompt_version'],
                'dataset_sha256': digest, 'campaign_path': config['campaign_path'],
                'cloud_cap_usd': config['cloud_cap_usd'], 'repeat_case_ids': sorted(repeat_ids), 'rows': []}
        definition = {'schema': 2, 'evidence_kind': 'simulated-instrument-test', 'split': phase,
                      'dataset_sha256': digest, 'models': models, 'policy': config['policy'],
                      'prompt_version': config['prompt_version'], 'threshold': threshold,
                      'case_ids': plan['case_ids'], 'trials': 3 if phase == 'test' else 1,
                      'repeat_case_ids': sorted(repeat_ids), 'label_status': 'agent_authored_unreviewed',
                      'source_commit': 'synthetic', 'source_files': {}, 'settings': {}}
        write_once(destination / 'definition.json', definition)
        for trial in range(1, 4 if phase == 'test' else 2):
            for case in ordered:
                if trial > 1 and case['id'] not in repeat_ids:
                    continue
                for arm in models:
                    key = f"{arm}:{case['id']}:{trial}"
                    plan['rows'].append({'key': key, 'arm': arm, 'case_id': case['id'],
                        'family': case['family'], 'kind': case['state']['unit']['kind'], 'trial': trial,
                        'deterministic_bypass': config['policy'] == 'deterministic_first' and
                                                case['state']['unit']['kind'] == 'executable'})
        write_once(destination / 'phase-plan.json', plan)
        rows = []
        used_special = False
        with ExitStack() as stack:
            campaign = stack.enter_context(CampaignBudget(self.campaign, '2'))
            journals = {}
            for arm in models:
                journal = RecoverableJournal(destination / (arm + '.jsonl'), '2', campaign=campaign,
                    scope=str(destination.resolve()) + ':' + arm,
                    identity={'phase_plan_sha256': sha(destination / 'phase-plan.json')}, create=True)
                stack.callback(journal.close)
                journals[arm] = journal
            write_once(destination / 'READY.json', {'schema': 3,
                'plan_sha256': sha(destination / 'phase-plan.json'),
                'definition_sha256': sha(destination / 'definition.json')})
            for trial in range(1, 4 if phase == 'test' else 2):
                for case in ordered:
                    if trial > 1 and case['id'] not in repeat_ids:
                        continue
                    for arm, model in models.items():
                        key = f"{arm}:{case['id']}:{trial}"
                        bypass = config['policy'] == 'deterministic_first' and case['state']['unit']['kind'] == 'executable'
                        row = {'key': key, 'arm': arm, 'case_id': case['id'], 'family': case['family'],
                               'kind': case['state']['unit']['kind'], 'trial': trial}
                        if bypass:
                            rows.append({**row, 'status': 'deterministic', 'attempts': 0, 'end_to_end_ms': 0.1})
                            continue
                        journal = journals[arm]
                        journal.reserve(key, '.00025' if arm == 'jev' else '.003')
                        journal.write({'event': 'request', 'key': key, 'attempt': 1, 'arm': arm,
                                       'body': build(case, arm, config['prompt_version']), 'expected_model': model})
                        special = not used_special and (invalid or interrupted or unresolved)
                        if special:
                            used_special = True
                        if special and unresolved:
                            # An unresolved attempt prevents further reservations in that arm.
                            # This incomplete fixture ends before any subsequent dispatch.
                            break
                        if special and interrupted:
                            journal.reconcile('synthetic unit-test interrupted request')
                            continue
                        response = fake_response(arm, case['label']['action'], model=model,
                                                 invalid=special and invalid)
                        journal.write({'event': 'result', 'key': key, 'attempt': 1,
                                       'status': 200, 'body': response['body'], 'elapsed_ms': 2.0})
                        rows.append({**row, 'status': 'observed', 'attempts': 1, 'end_to_end_ms': 3.0})
                    if unresolved and used_special:
                        break
                if unresolved and used_special:
                    break
        (destination / 'observations.jsonl').write_bytes(
            ''.join(canonical(row) + '\n' for row in rows).encode('utf8'))
        write_once(destination / 'summary.json', {'schema': 2, 'split': phase, 'complete': not unresolved,
                   'stopped': None, 'planned_observations': len(plan['rows']),
                   'recorded_observations': len(rows), 'rows': rows})
        if not unresolved:
            self.seal(destination)
        return destination

    def seal(self, destination):
        marker = destination / 'COMPLETE.json'
        value = {'schema': 3, 'plan_sha256': sha(destination / 'phase-plan.json'),
                 'files': {p.name: sha(p) for p in destination.iterdir()
                           if p.is_file() and p != marker}}
        marker.write_text(canonical(value) + '\n', encoding='utf8')

    def test_definition_is_idempotent_and_inputs_are_copied(self):
        first = self.freeze()
        before = {p.name: p.read_bytes() for p in self.directory.glob('*.json')}
        self.assertEqual(first, self.freeze())
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.directory.glob('*.json')})
        cases, _, _ = target.phase_inputs(self.directory, 'calibration')
        cases[0]['state']['explanation'] = 'mutated caller copy'
        self.assertNotEqual(cases, target.phase_inputs(self.directory, 'calibration')[0])

    def test_definition_recovers_after_frozen_file_before_version_sidecar(self):
        with patch.object(target, '_write_checked', side_effect=RuntimeError('synthetic interruption')):
            with self.assertRaises(RuntimeError):
                self.freeze()
        self.assertTrue((self.directory / 'freeze.json').is_file())
        self.assertFalse((self.directory / 'version.json').exists())
        frozen_bytes = (self.directory / 'freeze.json').read_bytes()
        self.freeze()
        self.assertEqual(frozen_bytes, (self.directory / 'freeze.json').read_bytes())

    def test_changed_source_settings_campaign_or_dataset_are_rejected(self):
        self.freeze()
        with patch.object(target, 'source_inventory', return_value={'fixture.py': 'b' * 64}):
            with self.assertRaisesRegex(ValueError, 'source'):
                target.verify(self.directory)
        changed = dict(self.settings, policy='all_cases')
        with self.assertRaisesRegex(ValueError, 'differs'):
            target.freeze(self.directory, self.dataset, changed)
        changed = dict(self.settings, cloud_cap_usd='1')
        with self.assertRaisesRegex(ValueError, 'cap differs'):
            target.freeze(self.directory, self.dataset, changed)
        path = self.dataset / 'calibration.json'
        path.write_text(path.read_text() + '\n')
        with self.assertRaisesRegex(ValueError, 'drift'):
            target.verify(self.directory)

    def test_research_cannot_reuse_old_study_and_legacy_freeze_is_immutable(self):
        with self.assertRaisesRegex(ValueError, 'fresh dataset'):
            target.freeze(self.directory, SOURCE_ROOT / 'study-v2', dict(self.settings, purpose='research'))
        target.experiment_v2.freeze(self.directory, self.dataset, self.settings)
        before = (self.directory / 'freeze.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'cannot become'):
            self.freeze()
        self.assertEqual(before, (self.directory / 'freeze.json').read_bytes())

    def test_invalid_calibration_answer_is_retained_as_review(self):
        self.freeze()
        self.phase('calibration', invalid=True)
        result = target.freeze_thresholds(self.directory)
        self.assertEqual(set(result), {'local', 'jev', 'chat'})
        value = target.report(self.directory, 'calibration')
        self.assertEqual(sum(a['invalid_primary_n'] for a in value['arms'].values()), 1)
        self.assertTrue(value['complete_from_evidence'])

    def test_threshold_freeze_retry_is_identical_without_intermediate_bundles(self):
        self.freeze()
        self.phase('calibration')
        first = target.freeze_thresholds(self.directory)
        before = (self.directory / 'thresholds.json').read_bytes()
        # Red reference: the unchanged legacy finalizer refuses an identical retry.
        with self.assertRaises(FileExistsError):
            target.experiment_v2.freeze_thresholds(self.directory, unavailable={
                'local': self.settings['local_status']})
        self.assertEqual(first, target.freeze_thresholds(self.directory))
        self.assertEqual(before, (self.directory / 'thresholds.json').read_bytes())
        self.assertEqual(list((self.directory / 'calibration').glob('*bundle*')), [])

    def test_thresholds_reject_pending_attempt(self):
        self.freeze()
        self.phase('calibration', unresolved=True)
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            target.freeze_thresholds(self.directory)
        self.assertFalse((self.directory / 'thresholds.json').exists())

    def test_existing_changed_threshold_cannot_be_overwritten(self):
        self.freeze()
        self.phase('calibration')
        target.freeze_thresholds(self.directory)
        path = self.directory / 'thresholds.json'
        changed = strict_json(path.read_text())
        changed['arms']['jev']['threshold'] = 0.0
        path.write_text(canonical(changed) + '\n')
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'existing artifact differs'):
            target.freeze_thresholds(self.directory)
        self.assertEqual(before, path.read_bytes())

    def test_report_uses_resolved_model_and_includes_repeat_inventory(self):
        self.freeze()
        self.phase('calibration')
        target.freeze_thresholds(self.directory)
        self.phase('test')
        value = target.report(self.directory, 'test')
        self.assertEqual(value['arms']['chat']['model'], 'openai/gpt-4.1-mini-2025-04-14')
        self.assertEqual(value['arms']['chat']['repeat_stability']['complete_unique'], 6)
        self.assertTrue(value['complete_from_evidence'])
        self.assertIsNone(value['net_tokens_saved'])
        self.assertEqual(value['next_version'], 3)

    def test_missing_journal_or_plan_row_is_not_silently_accepted(self):
        self.freeze()
        destination = self.phase('calibration')
        path = destination / 'phase-plan.json'
        plan = strict_json(path.read_text())
        original = path.read_bytes()
        plan['rows'].pop()
        path.write_text(canonical(plan) + '\n')
        with self.assertRaisesRegex(ValueError, 'row coverage'):
            target.report(self.directory, 'calibration')
        path.write_bytes(original)
        (destination / 'chat.jsonl').unlink()
        with self.assertRaisesRegex(ValueError, 'journal is missing'):
            target.report(self.directory, 'calibration')

    def test_reconciled_interruption_preserves_unknown_time_and_billing(self):
        self.freeze()
        self.phase('calibration', interrupted=True)
        value = target.report(self.directory, 'calibration')
        self.assertEqual(len(value['recovery_unknowns']), 1)
        self.assertIsNone(value['recovery_unknowns'][0]['elapsed_ms'])
        self.assertEqual(value['recovery_unknowns'][0]['billing'], 'uncertain')
        self.assertGreater(sum(a['primary_latency']['unknown_n'] for a in value['arms'].values()), 0)

    def test_threshold_requires_complete_marker_but_incomplete_report_remains_available(self):
        self.freeze()
        destination = self.phase('calibration')
        (destination / 'COMPLETE.json').unlink()
        value = target.report(self.directory, 'calibration')
        self.assertFalse(value['completion_marker_verified'])
        with self.assertRaisesRegex(ValueError, 'COMPLETE marker required'):
            target.freeze_thresholds(self.directory)

    def test_ready_and_campaign_binding_are_validated_beyond_inventory_hashes(self):
        self.freeze()
        destination = self.phase('calibration')
        ready = destination / 'READY.json'
        original = ready.read_bytes()
        changed = strict_json(ready.read_text())
        changed['definition_sha256'] = '0' * 64
        ready.write_text(canonical(changed) + '\n')
        self.seal(destination)
        with self.assertRaisesRegex(ValueError, 'READY binding'):
            target.report(self.directory, 'calibration')
        ready.write_bytes(original)
        binding = destination / 'jev.jsonl.binding.json'
        changed = strict_json(binding.read_text())
        changed['campaign'] = 'different-campaign-ledger'
        binding.write_text(canonical(changed) + '\n')
        self.seal(destination)
        with self.assertRaisesRegex(ValueError, 'journal binding'):
            target.report(self.directory, 'calibration')

    def test_interrupted_result_requires_original_matching_recovery_audit(self):
        self.freeze()
        destination = self.phase('calibration', interrupted=True)
        for path in destination.glob('*.recovery.jsonl'):
            rows = [strict_json(line) for line in path.read_text().splitlines()]
            if len(rows) > 1:
                rows[1]['request_sha256'] = '0' * 64
                rows[1]['recovery_id'] = hashlib.sha256(canonical({
                    k: v for k, v in rows[1].items() if k != 'recovery_id'}).encode()).hexdigest()
                path.write_text(''.join(canonical(row) + '\n' for row in rows))
                break
        else:
            self.fail('fixture did not produce a recovery audit')
        self.seal(destination)
        with self.assertRaisesRegex(ValueError, 'does not match a durable request'):
            target.report(self.directory, 'calibration')

    def test_heldout_binds_the_frozen_calibration_completion_and_recovery_inventory(self):
        self.freeze()
        destination = self.phase('calibration')
        target.freeze_thresholds(self.directory)
        ready = destination / 'READY.json'
        ready.write_text(ready.read_text() + '\n')
        self.seal(destination)
        with self.assertRaisesRegex(ValueError, 'recovery provenance changed'):
            target.phase_inputs(self.directory, 'test')


if __name__ == '__main__':
    unittest.main()
