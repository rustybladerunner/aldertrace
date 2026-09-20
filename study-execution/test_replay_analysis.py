import json
import tempfile
import unittest
from pathlib import Path
from replay_analysis import analyze
from adapters import ROOT,build,MODELS
from journal import Journal,execute_one

CASE=next(c for c in json.loads((ROOT/'study/cases.json').read_text())
          if c['split']=='development' and c['label']['action']=='run_check')
RAW=json.dumps({'model':MODELS['jev'],'answers':{'route':{'type':'choice','choice':'skip',
    'confidence':1,'probabilities':{'skip':1,'read':0,'run_check':0,'review':0}}}})

class Replay(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'journal.jsonl'
    def tearDown(self):self.temp.cleanup()
    def seed(self):
        j=Journal(self.path,1)
        try:execute_one(j,'q','jev',build(CASE,'jev'),MODELS['jev'],'.01',lambda b:{'status':200,'body':RAW})
        finally:j.close()
    def report(self):return analyze(self.path,[CASE],{'q':CASE['id']},'jev',MODELS['jev'],.9)
    def test_reparse_does_not_trust_saved_safe_summary(self):
        self.seed()
        rows=[json.loads(s) for s in self.path.read_text().splitlines()]
        rows[-1]['parsed']={'valid':True,'answer':{'choice':'run_check'}}
        self.path.write_text('\n'.join(json.dumps(r) for r in rows)+'\n')
        result=self.report()
        self.assertEqual(result['arms']['raw']['overall']['unsafe_skips'],1)
        self.assertEqual(result['arms']['hybrid']['overall']['unsafe_skips'],0)
    def test_duplicate_result_and_mapping_drift_rejected(self):
        self.seed();text=self.path.read_text();last=text.splitlines()[-1]
        self.path.write_text(text+last+'\n')
        with self.assertRaises(ValueError):self.report()
        self.path.write_text(text.replace('"state":','"wrong_state":'))
        with self.assertRaises(ValueError):self.report()
    def test_unfinished_attempt_retained_as_missing(self):
        j=Journal(self.path,1);j.reserve('q','.01');j.close()
        r=self.report()
        self.assertEqual(r['missing_case_ids'],[CASE['id']])
        self.assertEqual(r['unresolved_attempts'],[{'key':'q','attempt':1}])
        self.assertIsNone(r['provider_cost_usd'])
    def test_all_retry_time_counted(self):
        j=Journal(self.path,1);calls=[]
        def transport(body):
            calls.append(body)
            return {'status':503,'body':'{}','retry_after':3} if len(calls)==1 else {'status':200,'body':RAW}
        try:execute_one(j,'q','jev',build(CASE,'jev'),MODELS['jev'],'.01',transport,sleep=lambda _:None)
        finally:j.close()
        r=self.report()
        self.assertEqual(r['attempt_counts'][CASE['id']],2)
        self.assertGreaterEqual(r['attempt_processing_plus_backoff_ms'][CASE['id']],3000)

if __name__=='__main__':unittest.main()
