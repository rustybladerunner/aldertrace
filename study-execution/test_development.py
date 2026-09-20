import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from adapters import MODELS, canonical
from budget import CampaignBudget
from development import run, load_development
from test_runner import fake_transports


class Development(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)
        self.budget=CampaignBudget(self.path/'budget.jsonl','2',create=True)
        self.cases,self.digest=load_development();self.calls=[]
        self.transports=fake_transports(self.calls)
        self.models={a:MODELS[a] for a in self.transports}
        old=self.transports['local']
        def local(body):
            response=old(body);response['usage']={'input_tokens':100,'output_tokens':1};return response
        self.transports['local']=local
    def tearDown(self):
        self.budget.close();self.tmp.cleanup()
    def execute(self,**kwargs):
        return run(self.cases,self.path/'run',self.transports,self.models,self.budget,
                   approved=True,dataset_hash=self.digest,**kwargs)
    def test_invalid_recommendations_are_recorded_reviews_not_rerun(self):
        def invalid(body):
            return {'status':200,'body':canonical({'model':MODELS['jev'],'answers':{},
                'usage':{'input_tokens':50,'output_tokens':0}})}
        self.transports['jev']=invalid
        result=self.execute(limit=2)
        self.assertTrue(result['complete']);self.assertEqual(len(result['rows']),6)
        rows=[r for r in result['rows'] if r['arm']=='jev']
        self.assertTrue(all(r['action']=='review' and r['attempts']==1 and not r['valid'] for r in rows))
    def test_uncertain_billing_halts_shared_campaign(self):
        self.transports['jev']=lambda b:{'status':200,'body':canonical({'model':MODELS['jev'],'answers':{}})}
        result=self.execute(limit=2)
        self.assertFalse(result['complete']);self.assertTrue(self.budget.halted)
        self.assertLess(len(result['rows']),6)
    def test_interruption_keeps_partial_summary_and_reservation(self):
        def interrupted(body):raise KeyboardInterrupt()
        self.transports['local']=interrupted
        with self.assertRaises(KeyboardInterrupt):self.execute(limit=2)
        result=json.loads((self.path/'run/summary.json').read_text())
        self.assertFalse(result['complete']);self.assertIn('KeyboardInterrupt',result['stopped'])
        self.assertEqual(len(self.budget.keys),1)
        with self.assertRaises(FileExistsError):self.execute(limit=2)
    def test_heldout_and_missing_authorization_refused_before_call(self):
        with self.assertRaises(PermissionError):
            run(self.cases,self.path/'run',self.transports,self.models,self.budget,dataset_hash=self.digest)
        self.cases=[dict(self.cases[0],split='test')]
        with self.assertRaises(ValueError):self.execute()
        self.assertFalse(self.calls)
    def test_deterministic_first_avoids_machine_calls_and_records_actions(self):
        self.cases=[c for c in self.cases if c['state']['unit']['kind']=='executable']
        result=self.execute(limit=2,policy='deterministic_first')
        self.assertTrue(result['complete']);self.assertFalse(self.calls)
        self.assertTrue(all(r['attempts']==0 and r['status']=='deterministic' for r in result['rows']))
    def test_forced_stale_skip_is_rejected_and_labels_stay_local(self):
        self.cases=[c for c in self.cases if c['state']['unit']['kind']=='executable'
                    and c['label']['action']=='run_check'][:1]
        answer={'type':'choice','choice':'skip','confidence':1,
                'probabilities':{'skip':1,'read':0,'run_check':0,'review':0}}
        def unsafe(body):
            self.assertNotIn('label',canonical(body));self.assertNotIn('rationale',canonical(body))
            return {'status':200,'body':canonical({'model':MODELS['jev'],'answers':{'route':answer},
                'usage':{'input_tokens':100,'output_tokens':0}})}
        self.transports={'jev':unsafe};self.models={'jev':MODELS['jev']}
        result=self.execute()
        self.assertEqual(result['rows'][0]['raw_action'],'skip')
        self.assertEqual(result['rows'][0]['action'],'run_check')
    def test_all_attempt_usage_and_retries_retained(self):
        count=[0]
        def retry(body):
            count[0]+=1
            if count[0]==1:return {'status':503,'body':'{}','retry_after':0}
            return fake_transports([])['jev'](body)
        self.transports={'jev':retry};self.models={'jev':MODELS['jev']}
        with patch('journal.time.sleep'):
            result=self.execute(limit=1)
        self.assertEqual(result['rows'][0]['attempts'],2)
        self.assertEqual(str(self.budget.reserved),'0.00050')
        self.assertEqual(len(result['rows'][0]['usage']),1)


if __name__=='__main__':unittest.main()
