import json
import tempfile
import unittest
from pathlib import Path
from preflight import run
from adapters import ROOT,MODELS
from budget import CampaignBudget

CASES=json.loads((ROOT/'study/cases.json').read_text())

def fake(arm,wrong_usage=False):
    answer={'choice':'review','confidence':1,'probabilities':{'skip':0,'read':0,'run_check':0,'review':1}}
    if arm=='jev':
        raw={'model':MODELS[arm],'answers':{'route':{'type':'choice',**answer}},
             'usage':{'input_tokens':6000 if wrong_usage else 100,'output_tokens':40}}
    else:raw={'model':MODELS[arm],'choices':[{'finish_reason':'stop','message':{'content':json.dumps(answer)}}],
              'usage':{'prompt_tokens':100,'completion_tokens':40,'cost':.0001}}
    return lambda body:{'status':200,'body':json.dumps(raw)}

class Preflight(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.budget=CampaignBudget(Path(self.tmp.name)/'campaign.jsonl','2',create=True)
    def tearDown(self):
        self.budget.close();self.tmp.cleanup()
    def test_default_refuses_before_creating_or_dispatching(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'run';calls=[]
            with self.assertRaises(PermissionError):run(CASES,target,{'jev':lambda b:calls.append(b),'chat':lambda b:calls.append(b)},MODELS)
            self.assertFalse(target.exists());self.assertEqual(calls,[])
    def test_offline_round_trip_and_development_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'run'
            result=run(CASES,target,{a:fake(a) for a in ('jev','chat')},
                       {a:MODELS[a] for a in ('jev','chat')},approved=True,per_arm=2,campaign=self.budget)
            self.assertIsNone(result['halted']);self.assertEqual(len(result['notes']),4)
            dev={c['id'] for c in CASES if c['split']=='development'}
            self.assertTrue(all(n['case_id'] in dev for n in result['notes']))
            self.assertTrue((target/'attempts.jsonl').exists())
    def test_bad_usage_stops_before_next_arm(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls=[]
            result=run(CASES,Path(tmp)/'run',{'jev':fake('jev',True),'chat':lambda b:calls.append(b)},
                       {a:MODELS[a] for a in ('jev','chat')},approved=True,campaign=self.budget)
            self.assertIsNotNone(result['halted']);self.assertEqual(calls,[])
            self.assertTrue(self.budget.halted)

    def test_no_campaign_refuses_before_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls=[]
            with self.assertRaises(ValueError):
                run(CASES,Path(tmp)/'run',{a:lambda b:calls.append(b) for a in ('jev','chat')},
                    {a:MODELS[a] for a in ('jev','chat')},approved=True)
            self.assertEqual(calls,[])

if __name__=='__main__':unittest.main()
