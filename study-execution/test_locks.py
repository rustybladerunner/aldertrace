import unittest
import tempfile
import json
from pathlib import Path
from locks import freeze_definition,verify_definition,freeze_calibration,verify_calibration,start_test,sha


class Locks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/'study-root'
        self.root.mkdir();(self.root/'study').mkdir();(self.root/'logitpick').mkdir();(self.root/'study-execution').mkdir()
        (self.root/'EVALUATION_PROTOCOL.md').write_text('Synthetic lock fixture only')
        cases=[{'id':str(i),'split':'calibration','family':'fixture','state':{'scope_known':True,'unit':{'kind':'semantic'},
                'current_revision':'synthetic','runner_evidence':[],'explanation':'fixture'},
                'label':{'action':'read'},'document':'fixture'} for i in range(80)]
        (self.root/'study/cases.json').write_text(json.dumps(cases))
        self.run=Path(self.temp.name)/'run'
        self.settings={'resolved_models':{'local':'local-v1','jev':'jev-v1','chat':'chat-v1'},
            'local_digest':'a'*64,'tokenizer_asset_sha256':'b'*64,'tokenizer_method':'fixture',
            'preflight_evidence_sha256':'c'*64,'label_status':'agent_authored_unreviewed'}
    def tearDown(self):self.temp.cleanup()
    def bundles(self):
        paths={};raw=Path(self.temp.name)/'raw.jsonl';raw.write_text('synthetic evidence fixture')
        for arm,model in self.settings['resolved_models'].items():
            p=Path(self.temp.name)/(arm+'.json')
            answer={'choice':'review','confidence':1,'probabilities':{'skip':0,'read':0,'run_check':0,'review':1}}
            p.write_text(json.dumps({'arm':arm,'resolved_model':model,'answers':{str(i):answer for i in range(80)},
                'source_journals':{'raw.jsonl':sha(raw)}}));paths[arm]=p
        return paths
    def test_unresolved_model_or_tokenizer_prevents_freeze(self):
        for field in ('resolved_models','tokenizer_asset_sha256','preflight_evidence_sha256'):
            s=dict(self.settings);s.pop(field)
            with self.assertRaises(ValueError):freeze_definition(self.root,self.run,s)
    def test_new_or_changed_source_invalidates_definition(self):
        freeze_definition(self.root,self.run,self.settings)
        (self.root/'study-execution/added.py').write_text('x=1')
        with self.assertRaises(ValueError):verify_definition(self.root,self.run)
    def test_test_needs_calibration_and_cannot_reopen(self):
        freeze_definition(self.root,self.run,self.settings)
        with self.assertRaises(FileNotFoundError):start_test(self.root,self.run)
        result=freeze_calibration(self.root,self.run,self.bundles())
        self.assertTrue(all(e['threshold']==1 for e in result['arms'].values()))
        start_test(self.root,self.run)
        with self.assertRaises(FileExistsError):start_test(self.root,self.run)
        with self.assertRaises(ValueError):freeze_calibration(self.root,self.run,self.bundles())
    def test_missing_calibration_and_raw_drift_rejected(self):
        freeze_definition(self.root,self.run,self.settings);b=self.bundles()
        value=json.loads(b['jev'].read_text());value['answers'].pop('0');b['jev'].write_text(json.dumps(value))
        with self.assertRaises(ValueError):freeze_calibration(self.root,self.run,b)
        b=self.bundles();freeze_calibration(self.root,self.run,b)
        (Path(self.temp.name)/'raw.jsonl').write_text('changed')
        with self.assertRaises(ValueError):verify_calibration(self.root,self.run)
    def test_existing_freezes_never_overwritten(self):
        freeze_definition(self.root,self.run,self.settings)
        with self.assertRaises(FileExistsError):freeze_definition(self.root,self.run,self.settings)
        b=self.bundles();freeze_calibration(self.root,self.run,b)
        with self.assertRaises(FileExistsError):freeze_calibration(self.root,self.run,b)

if __name__=='__main__':unittest.main()
