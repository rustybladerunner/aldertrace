import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from adapters import MODELS,canonical,strict_json
from budget import CampaignBudget
from development import run,load_development
from development_report import report,generate
from locks import write_once


class DevelopmentReport(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)
        cases,_=load_development()
        self.cases=[c for c in cases if c['state']['unit']['kind']=='executable'
                    and c['label']['action']=='run_check'][:1]
        self.dataset=self.base/'development.json'
        self.dataset.write_text(canonical(self.cases),encoding='utf8')
        self.sha=hashlib.sha256(self.dataset.read_bytes()).hexdigest()
        self.budget=CampaignBudget(self.base/'budget.jsonl','2',create=True)
        self.run=self.base/'run'
    def tearDown(self):
        self.budget.close();self.tmp.cleanup()
    def response(self,choice='skip'):
        answer={'type':'choice','choice':choice,'confidence':1,
            'probabilities':{a:int(a==choice) for a in ('skip','read','run_check','review')}}
        return {'status':200,'body':canonical({'model':MODELS['jev'],'answers':{'route':answer},
            'usage':{'input_tokens':100,'output_tokens':1}})}
    def execute(self,transport=None,**kwargs):
        return run(self.cases,self.run,{'jev':transport or (lambda b:self.response())},
            {'jev':MODELS['jev']},self.budget,dataset_hash=self.sha,approved=True,**kwargs)
    def rewrite(self,name,mutate):
        path=self.run/name;value=strict_json(path.read_text());mutate(value)
        path.write_text(canonical(value)+'\n',encoding='utf8')

    def test_reparses_raw_and_ignores_cached_actions_and_usage(self):
        self.execute()
        self.rewrite('summary.json',lambda s:s['rows'][0].update(action='skip',raw_action='read',usage=[{'input_tokens':1}]))
        journal=self.run/'jev.jsonl';events=[strict_json(line) for line in journal.read_text().splitlines()]
        for event in events:
            if event['event']=='result':event['parsed']={'valid':True,'answer':{'choice':'read'}}
        journal.write_text(''.join(canonical(e)+'\n' for e in events),encoding='utf8')
        value=report(self.run,self.dataset);arm=value['arms']['jev']
        self.assertEqual(arm['raw']['overall']['unsafe_skips'],1)
        self.assertEqual(arm['enforced']['overall']['unsafe_skips'],0)
        self.assertEqual(arm['resources_all_attempts']['input_tokens']['total'],100)
        self.assertIsNone(arm['resources_all_attempts']['reported_usd']['total'])
        self.assertIsNone(value['net_tokens_saved']);self.assertIsNone(value['task_success'])
        self.assertIsNone(arm['repeat_stability']['raw_changed_cases'])
        self.assertEqual(arm['observations'][0]['action'],'run_check')

    def test_request_identity_tampering_is_rejected(self):
        self.execute();path=self.run/'jev.jsonl'
        events=[strict_json(line) for line in path.read_text().splitlines()]
        for event in events:
            if event['event']=='request':event['body']['state']='different synthetic case'
        path.write_text(''.join(canonical(e)+'\n' for e in events),encoding='utf8')
        with self.assertRaisesRegex(ValueError,'does not match'):report(self.run,self.dataset)

    def test_missing_attempt_remains_unknown_and_planned_denominator_stays(self):
        def interrupted(body):raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):self.execute(interrupted)
        value=report(self.run,self.dataset);arm=value['arms']['jev']
        self.assertFalse(value['complete_from_evidence'])
        self.assertEqual(arm['primary_missing_n'],1)
        self.assertEqual(arm['unresolved_attempts'],1)
        self.assertEqual(arm['enforced']['overall']['n_unique'],1)
        self.assertIsNone(arm['resources_all_attempts']['input_tokens']['total'])
        self.assertIsNone(arm['primary_latency']['p50_ms'])

    def test_retry_counts_every_attempt_and_unknown_failed_usage(self):
        calls=[]
        def retry(body):
            calls.append(body)
            return {'status':503,'body':'{}','retry_after':0} if len(calls)==1 else self.response()
        with patch('journal.random.Random') as rng:
            rng.return_value.uniform.return_value=0
            self.execute(retry)
        arm=report(self.run,self.dataset)['arms']['jev'];resources=arm['resources_all_attempts']
        self.assertEqual(arm['retries'],1);self.assertEqual(resources['attempts'],2)
        self.assertEqual(resources['input_tokens']['known_subtotal'],100)
        self.assertIsNone(resources['input_tokens']['total'])
        self.assertIsNone(resources['estimated_usd']['total'])
        self.assertEqual(resources['estimated_usd']['known_subtotal'],'0.0000042')

    def test_summary_attempt_count_and_impossible_timing_rejected(self):
        self.execute();original=(self.run/'summary.json').read_text()
        self.rewrite('summary.json',lambda s:s['rows'][0].update(attempts=2))
        with self.assertRaisesRegex(ValueError,'attempt count'):report(self.run,self.dataset)
        (self.run/'summary.json').write_text(original)
        journal=self.run/'jev.jsonl';events=[strict_json(line) for line in journal.read_text().splitlines()]
        for event in events:
            if event['event']=='result':event['elapsed_ms']=100000
        journal.write_text(''.join(canonical(e)+'\n' for e in events))
        with self.assertRaisesRegex(ValueError,'timing'):report(self.run,self.dataset)

    def test_heldout_and_dataset_drift_are_rejected(self):
        self.execute()
        self.dataset.write_text(canonical([dict(self.cases[0],split='test')]))
        with self.assertRaisesRegex(ValueError,'development cases only'):report(self.run,self.dataset)
        self.dataset.write_text(canonical(self.cases)+' ')
        with self.assertRaisesRegex(ValueError,'dataset hash'):report(self.run,self.dataset)

    def test_repeat_stability_uses_unique_cases_and_all_attempt_costs(self):
        calls=[]
        def alternate(body):
            calls.append(body);return self.response('read' if len(calls)==3 else 'skip')
        self.execute(alternate,trials=3)
        arm=report(self.run,self.dataset)['arms']['jev']
        self.assertEqual(arm['enforced']['overall']['n_unique'],1)
        self.assertEqual(arm['repeat_stability']['complete_unique'],1)
        self.assertEqual(arm['repeat_stability']['raw_changed_cases'],1)
        self.assertEqual(arm['repeat_stability']['enforced_changed_cases'],0)
        self.assertEqual(arm['resources_all_attempts']['input_tokens']['total'],300)
        self.assertEqual(arm['primary_latency']['measured_n'],1)

    def test_local_telemetry_is_bound_to_exact_worker_and_request(self):
        from local_capture import RecordingBackend
        from test_local_capture import Fake
        from logitpick.engine import pick
        from logitpick.schema import parse_request
        def local(body):
            records=[]
            response=pick(parse_request(strict_json(canonical(body))),
                RecordingBackend(records.append,authorized=True,opener=Fake()))
            write_once(self.run/'local-worker-1.json',{'response':response,'records':records})
            return {'status':200,'body':canonical(response),'usage':{'input_tokens':100,'output_tokens':1}}
        run(self.cases,self.run,{'local':local},{'local':MODELS['local']},self.budget,
            dataset_hash=self.sha,approved=True)
        value=report(self.run,self.dataset);resources=value['arms']['local']['resources_all_attempts']
        self.assertEqual(resources['input_tokens']['total'],100)
        self.assertEqual(resources['cold_requests'],1)
        self.assertEqual(resources['cloud_cost_usd'],'0')
        self.assertIsNone(resources['local_hardware_energy_cost_usd'])
        def tamper(worker):
            next(e for e in worker['records'] if e['event']=='local_usage')['prompt_eval_count']=1
        self.rewrite('local-worker-1.json',tamper)
        with self.assertRaisesRegex(ValueError,'telemetry counts'):report(self.run,self.dataset)

    def test_static_demo_is_self_contained_and_outputs_are_exclusive(self):
        self.execute();output=self.base/'report'
        generate(self.run,output,self.dataset)
        page=(output/'index.html').read_text(encoding='utf8')
        self.assertIn('Not measured',page);self.assertIn('unsafe',page)
        self.assertNotIn('<script src=',page);self.assertNotIn('https://',page)
        self.assertTrue((output/'report.json').is_file())
        with self.assertRaises(FileExistsError):generate(self.run,output,self.dataset)

    def test_versioned_prompt_replay_accepts_v2_and_rejects_false_v1(self):
        self.execute(prompt_version='v2')
        self.assertEqual(report(self.run,self.dataset)['prompt_version'],'v2')
        self.rewrite('definition.json',lambda d:d.update(prompt_version='v1'))
        with self.assertRaisesRegex(ValueError,'does not match'):report(self.run,self.dataset)

    def test_optional_input_proxy_counts_retries_and_preserves_negative_unknown_actual(self):
        from test_measured_tokens import FakeTokenizer
        calls=[]
        def retry(body):
            calls.append(body)
            return {'status':503,'body':'{}','retry_after':0} if len(calls)==1 else self.response()
        with patch('journal.random.Random') as rng:
            rng.return_value.uniform.return_value=0
            self.execute(retry)
        with patch('measured_tokens.FrozenTokenizer',return_value=FakeTokenizer()):
            value=generate(self.run,self.base/'proxy-report',self.dataset,tokenizer_environment='SIMULATED_TEST_ONLY')
        proxy=value['arms']['jev']['input_proxy'];totals=proxy['primary_including_retries']
        self.assertEqual(totals['attempts'],2)
        self.assertEqual(totals['baseline_reading_tokens'],0)
        self.assertEqual(totals['net_input_proxy_tokens_saved'],-totals['routing_input_proxy_tokens'])
        self.assertLess(totals['net_input_proxy_tokens_saved'],0)
        self.assertIsNone(value['net_tokens_saved']);self.assertFalse(proxy['h1_eligible'])
        self.assertEqual(proxy['primary_case_measurements'][self.cases[0]['id']]['document_utf8_bytes'],
                         len(self.cases[0]['document'].encode('utf8')))
        page=(self.base/'proxy-report/index.html').read_text(encoding='utf8')
        self.assertIn('right:50%',page)
        self.assertIn('Actual net token reduction remains unknown',page)

    def test_arbitrary_test_directory_has_no_heldout_permission(self):
        self.execute()
        phase_dir=self.base/'test';self.run.rename(phase_dir);self.run=phase_dir
        fake=[dict(c,split='test') for c in self.cases]
        self.dataset.write_text(canonical(fake),encoding='utf8')
        self.rewrite('definition.json',lambda d:d.update(split='test',dataset_sha256=hashlib.sha256(self.dataset.read_bytes()).hexdigest()))
        self.rewrite('summary.json',lambda s:s.update(split='test'))
        with self.assertRaises(FileNotFoundError):report(phase_dir,self.dataset)

    def test_locked_fake_phases_thresholds_and_repeat_subset_are_verified(self):
        from experiment_v2 import freeze,freeze_thresholds
        dataset=self.base/'phase-fixtures';dataset.mkdir()
        phase_cases={phase:[dict(self.cases[0],id='synthetic-'+phase+'-'+str(i),split=phase)
                            for i in range(6)] for phase in ('calibration','test')}
        hashes={}
        for phase,cases in phase_cases.items():
            path=dataset/(phase+'.json');path.write_text(canonical(cases),encoding='utf8')
            hashes[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
        write_once(dataset/'MANIFEST.json',{'assets':hashes})
        settings={'models':{a:MODELS[a] for a in ('local','jev','chat')},
            'available_arms':['jev'],'label_status':'agent_authored_unreviewed',
            'tokenizer_identity':'synthetic fixture; not a tokenizer attestation',
            'preflight_sha256':'fixture','policy':'all_cases','prompt_version':'v2',
            'local_status':'fixture unavailable','cloud_model_identity':'fixture',
            'measurement_scope':'offline tests only','source_commit':'fixture'}
        experiment=self.base/'locked'
        with patch('experiment_v2.implementation_assets',return_value={'synthetic_fixture':'fixed'}):
            freeze(experiment,dataset,settings)
            run(phase_cases['calibration'],experiment/'calibration',{'jev':lambda b:self.response()},
                {'jev':MODELS['jev']},self.budget,dataset_hash=hashes['calibration.json'],
                approved=True,phase='calibration',prompt_version='v2')
            calibration=report(experiment/'calibration',dataset/'calibration.json')
            self.assertEqual(calibration['threshold'],{'jev':None})
            self.assertEqual(calibration['split'],'calibration')
            freeze_thresholds(experiment,unavailable={'local':'fixture','chat':'fixture'})
            run(phase_cases['test'],experiment/'test',{'jev':lambda b:self.response()},
                {'jev':MODELS['jev']},self.budget,dataset_hash=hashes['test.json'],
                approved=True,phase='test',prompt_version='v2')
            value=report(experiment/'test',dataset/'test.json');arm=value['arms']['jev']
            self.assertEqual(value['split'],'test')
            self.assertEqual(value['threshold'],{'jev':1.0})
            self.assertEqual(arm['enforced']['overall']['n_unique'],6)
            self.assertEqual(arm['repeat_stability']['planned_unique'],5)
            self.assertEqual(arm['repeat_stability']['complete_unique'],5)
            self.assertEqual(arm['resources_all_attempts']['attempts'],16)
            self.assertEqual(set(value['phase_locks']),{'freeze.json','thresholds.json'})
            self.run=experiment/'test'
            original=(self.run/'definition.json').read_text()
            self.rewrite('definition.json',lambda d:d.update(threshold={'jev':0.5}))
            with self.assertRaisesRegex(ValueError,'thresholds differ'):report(self.run,dataset/'test.json')
            (self.run/'definition.json').write_text(original)
            self.rewrite('definition.json',lambda d:d['repeat_case_ids'].pop())
            with self.assertRaisesRegex(ValueError,'repeat subset'):report(self.run,dataset/'test.json')


if __name__=='__main__':unittest.main()
