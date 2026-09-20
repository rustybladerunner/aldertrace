import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from adapters import ROOT,MODELS
from budget import CampaignBudget
from locks import freeze_definition,freeze_calibration,start_test
from runner import run_phase,calibration_bundles
from journal import Journal,replay,BudgetExceeded
from locks import write_once


def fake_transports(calls):
    """Synthetic transport fixtures only; no model, credentials, or networking."""
    answer={'choice':'review','confidence':1,'probabilities':{'skip':0,'read':0,'run_check':0,'review':1}}
    def make(arm):
        def send(body):
            calls.append((arm,body))
            response={'model':MODELS[arm]}
            if arm=='chat':
                response.update(choices=[{'finish_reason':'stop','message':{'content':json.dumps(answer)}}],
                                usage={'prompt_tokens':100,'completion_tokens':40,'cost':.0001})
            else:
                response.update(answers={'route':{'type':'choice',**answer}},
                                usage={'input_tokens':100,'output_tokens':40})
            return {'status':200,'body':json.dumps(response)}
        return send
    return {arm:make(arm) for arm in ('local','jev','chat')}


class PhaseRunner(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)
        self.campaign=CampaignBudget(self.base/'budget.jsonl','2',create=True)
        self.run=self.base/'experiment';self.calls=[]
        self.transports=fake_transports(self.calls)
        self.models={a:MODELS[a] for a in self.transports}
        self.settings={'resolved_models':self.models,'local_digest':'a'*64,
                      'tokenizer_asset_sha256':'b'*64,'tokenizer_method':'SYNTHETIC TEST FIXTURE ONLY',
                      'preflight_evidence_sha256':'c'*64,'label_status':'agent_authored_unreviewed'}
    def tearDown(self):self.campaign.close();self.tmp.cleanup()
    def execute(self,phase,**kw):
        return run_phase(ROOT,self.run,phase,self.transports,self.models,self.campaign,approved=True,**kw)

    def test_default_permission_and_missing_freeze_block_without_calls(self):
        with self.assertRaises(PermissionError):
            run_phase(ROOT,self.run,'development',self.transports,self.models,self.campaign)
        with self.assertRaises(FileNotFoundError):self.execute('calibration')
        self.assertEqual(self.calls,[])
        self.assertFalse(self.run.exists())

    def test_test_cannot_run_without_calibration(self):
        freeze_definition(ROOT,self.run,self.settings)
        with self.assertRaises(FileNotFoundError):self.execute('test')
        self.assertEqual(self.calls,[])
        self.assertFalse((self.run/'test').exists())

    def test_full_offline_sequence_and_no_test_reopening(self):
        development=self.base/'development-run'
        first=run_phase(ROOT,development,'development',self.transports,self.models,self.campaign,approved=True)
        self.assertTrue(first['complete']);self.assertEqual(first['completed_requests'],240)
        freeze_definition(ROOT,self.run,self.settings)
        calibration=self.execute('calibration')
        self.assertTrue(calibration['complete']);self.assertEqual(calibration['completed_requests'],240)
        bundles=calibration_bundles(ROOT,self.run,self.models)
        freeze_calibration(ROOT,self.run,bundles)
        heldout=self.execute('test')
        self.assertTrue(heldout['complete']);self.assertEqual(heldout['completed_requests'],360)
        self.assertEqual(heldout['campaign_reserved_usd'],'0.91000')
        with self.assertRaises(FileExistsError):self.execute('test')
        self.assertEqual(len(self.calls),840)

    def test_asset_drift_blocks_before_dispatch(self):
        freeze_definition(ROOT,self.run,self.settings)
        with patch('locks.assets',return_value={'changed':'asset'}):
            with self.assertRaises(ValueError):self.execute('calibration')
        self.assertEqual(self.calls,[])

    def test_changed_model_refused(self):
        freeze_definition(ROOT,self.run,self.settings)
        self.models=dict(self.models,jev='wrong')
        with self.assertRaises(ValueError):self.execute('calibration')
        self.assertEqual(self.calls,[])

    def test_failure_stops_and_cannot_restart_phase_or_campaign(self):
        def invalid(body):self.calls.append(('invalid',body));return {'status':200,'body':'{}'}
        self.transports={a:invalid for a in self.transports}
        result=self.execute('development')
        self.assertFalse(result['complete']);self.assertEqual(len(self.calls),1)
        self.assertTrue(self.campaign.halted)
        with self.assertRaises(ValueError):self.execute('development')

    def test_malformed_envelope_stops_campaign_with_phase_evidence(self):
        def malformed(body):self.calls.append(body);return None
        self.transports={a:malformed for a in self.transports}
        result=self.execute('development')
        self.assertFalse(result['complete']);self.assertEqual(len(self.calls),1)
        self.assertTrue(self.campaign.halted)
        directory=self.run/'development'
        self.assertEqual(json.loads((directory/'summary.json').read_text()),result)
        mapping=json.loads((directory/'primary-mapping.json').read_text())
        self.assertEqual(sum(len(rows) for rows in mapping.values()),1)
        records=[r for path in directory.glob('*.jsonl') for r in replay(path)['results'].values()]
        self.assertEqual(records[0]['error_type'],'InvalidTransportEnvelope')

    def test_cancellation_preserves_unresolved_attempt_and_halts_reopened_campaign(self):
        def interrupted(body):self.calls.append(body);raise KeyboardInterrupt()
        self.transports={a:interrupted for a in self.transports}
        with self.assertRaises(KeyboardInterrupt):self.execute('development')
        directory=self.run/'development'
        summary=json.loads((directory/'summary.json').read_text())
        self.assertFalse(summary['complete'])
        self.assertEqual(summary['completed_requests'],0)
        self.assertEqual(summary['interruption'],{'error_type':'KeyboardInterrupt'})
        mapping=json.loads((directory/'primary-mapping.json').read_text())
        self.assertEqual(sum(len(rows) for rows in mapping.values()),1)
        self.assertEqual(sum(len(replay(p)['unfinished_attempts']) for p in directory.glob('*.jsonl')),1)
        self.assertEqual(len(self.calls),1)
        self.campaign.close()
        with CampaignBudget(self.base/'budget.jsonl','2') as reopened:
            self.assertTrue(reopened.halted)
            with self.assertRaises(BudgetExceeded):reopened.reserve('new','.001')

    def test_result_persistence_failure_keeps_reservation_and_phase_summary(self):
        original=Journal.write
        def fail_result(journal,event):
            if event['event']=='result':raise OSError('synthetic result persistence failure')
            return original(journal,event)
        with patch.object(Journal,'write',fail_result):
            with self.assertRaises(OSError):self.execute('development')
        directory=self.run/'development'
        summary=json.loads((directory/'summary.json').read_text())
        self.assertFalse(summary['complete'])
        self.assertEqual(summary['interruption'],{'error_type':'OSError'})
        self.assertTrue(self.campaign.halted)
        self.assertEqual(sum(len(replay(p)['unfinished_attempts']) for p in directory.glob('*.jsonl')),1)

    def test_budget_exhaustion_preserves_incomplete_phase_and_mapping(self):
        self.campaign.reserve('earlier-authorized-work','2')
        with self.assertRaises(BudgetExceeded):self.execute('development')
        directory=self.run/'development'
        summary=json.loads((directory/'summary.json').read_text())
        self.assertFalse(summary['complete'])
        self.assertEqual(summary['interruption'],{'error_type':'BudgetExceeded'})
        self.assertEqual(summary['campaign_reserved_usd'],'2')
        self.assertEqual(len(self.calls),1)  # First local request reserves zero dollars.
        self.assertTrue((directory/'primary-mapping.json').is_file())
        self.assertTrue(self.campaign.halted)

    def test_mapping_write_failure_still_saves_incomplete_summary_and_halts(self):
        def invalid(body):return {'status':200,'body':'{}'}
        self.transports={a:invalid for a in self.transports}
        def fail_mapping(path,value):
            if path.name=='primary-mapping.json':raise OSError('synthetic mapping persistence failure')
            return write_once(path,value)
        with patch('runner.write_once',fail_mapping):
            with self.assertRaises(OSError):self.execute('development')
        summary=json.loads((self.run/'development/summary.json').read_text())
        self.assertFalse(summary['complete'])
        self.assertEqual(summary['finalization_error_types'],['OSError'])
        self.assertTrue(self.campaign.halted)

    def test_calibration_reparses_body_instead_of_cached_answer(self):
        freeze_definition(ROOT,self.run,self.settings);self.execute('calibration')
        path=self.run/'calibration/jev.jsonl'
        events=[json.loads(line) for line in path.read_text().splitlines()]
        for event in events:
            if event['event']=='result':event['parsed']={'valid':True,'answer':{'choice':'skip'}}
        path.write_text(''.join(json.dumps(e)+'\n' for e in events))
        bundles=calibration_bundles(ROOT,self.run,self.models)
        answers=json.loads(bundles['jev'].read_text())['answers']
        self.assertTrue(all(a['choice']=='review' for a in answers.values()))

if __name__=='__main__':unittest.main()
