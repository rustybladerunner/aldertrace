import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from adapters import MODELS,canonical,build as original_build
from core import public_state
from development import run,load_development
from experiment_v2 import freeze,verify_phase
from locks import sha,write_once
from routing_contract import build
from budget import CampaignBudget
from test_runner import fake_transports


class VersionedStudy(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)
        self.dataset=self.base/'data';self.dataset.mkdir()
        cases,_=load_development();self.cases=[dict(c,split='calibration') for c in cases]
        for phase in ('development','calibration','test'):
            write_once(self.dataset/(phase+'.json'),[dict(c,split=phase) for c in cases])
        write_once(self.dataset/'MANIFEST.json',{'assets':{p.name:sha(p) for p in self.dataset.glob('*.json')}})
        self.settings={'models':dict(MODELS,**{})|{},'label_status':'agent_authored_unreviewed',
            'tokenizer_identity':'synthetic-fixture-not-a-measurement','preflight_sha256':'a'*64,
            'policy':'all_cases','prompt_version':'v2','local_status':'unavailable: test fixture',
            'available_arms':['jev','chat'],'cloud_model_identity':'test fixture',
            'measurement_scope':'test fixture','source_commit':'test fixture'}
        self.settings['models']={a:MODELS[a] for a in ('local','jev','chat')}
        self.exp=self.base/'experiment'
        self.patch=patch('experiment_v2.implementation_assets',return_value={'TEST_FIXTURE':'same'})
        self.patch.start();freeze(self.exp,self.dataset,self.settings)
    def tearDown(self):self.patch.stop();self.tmp.cleanup()
    def test_v1_is_identical_and_v2_is_matched_without_labels(self):
        c=self.cases[0]
        for arm in ('local','jev','chat'):
            self.assertEqual(build(c,arm,'v1'),original_build(c,arm))
            self.assertNotIn('rationale',canonical(build(c,arm,'v2')))
        jev=build(c,'jev','v2');chat=build(c,'chat','v2')
        self.assertEqual(jev['questions']['route']['instructions'],json.loads(chat['messages'][1]['content'])['instructions'])
    def test_changed_prompt_and_dataset_refused_before_execution(self):
        models={a:MODELS[a] for a in ('jev','chat')}
        with self.assertRaises(ValueError):
            verify_phase(self.exp,'calibration',self.cases,models,sha(self.dataset/'calibration.json'),'all_cases','v1')
        changed=[dict(self.cases[0],id='changed')]+self.cases[1:]
        with self.assertRaises(ValueError):
            verify_phase(self.exp,'calibration',changed,models,sha(self.dataset/'calibration.json'),'all_cases','v2')
    def test_missing_calibration_blocks_heldout(self):
        cases=json.loads((self.dataset/'test.json').read_text())
        with self.assertRaises(FileNotFoundError):
            verify_phase(self.exp,'test',cases,{a:MODELS[a] for a in ('jev','chat')},sha(self.dataset/'test.json'),'all_cases','v2')
    def test_locked_calibration_and_no_reopening(self):
        calls=[];transports=fake_transports(calls);transports.pop('local')
        with CampaignBudget(self.base/'budget.jsonl','2',create=True) as budget:
            kwargs=dict(approved=True,dataset_hash=sha(self.dataset/'calibration.json'),
                        phase='calibration',prompt_version='v2')
            result=run(self.cases,self.exp/'calibration',transports,
                       {a:MODELS[a] for a in transports},budget,**kwargs)
            self.assertTrue(result['complete']);self.assertEqual(len(calls),160)
            with self.assertRaises(FileExistsError):
                run(self.cases,self.exp/'calibration',transports,
                    {a:MODELS[a] for a in transports},budget,**kwargs)
    def test_asset_change_invalidates_freeze(self):
        with patch('experiment_v2.implementation_assets',return_value={'TEST_FIXTURE':'changed'}):
            with self.assertRaises(ValueError):
                verify_phase(self.exp,'calibration',self.cases,{a:MODELS[a] for a in ('jev','chat')},
                             sha(self.dataset/'calibration.json'),'all_cases','v2')


if __name__=='__main__':unittest.main()
