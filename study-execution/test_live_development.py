import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from local_resources import LocalBudget, ResourceProbeUnavailable
from live_development import LocalTransport, cpu_percent
import local_worker


GPU = [{'index':0,'uuid':'GPU-synthetic','utilization_percent':1,
        'memory_free_mib':7000,'memory_used_mib':1000,'memory_total_mib':8000}]
BODY = {'model':'llama3.2:latest','state':'Synthetic fixture',
        'questions':{'route':{'instructions':'Choose','options':{'skip':'skip','read':'read'}}}}


def completed_value(cold=True):
    return {'response':{'synthetic':True},'records':[{'event':'local_usage',
            'prompt_eval_count':20,'eval_count':1,'load_duration':100,
            'prompt_eval_duration':200,'eval_duration':300,'total_duration':600,
            'cold_observed':cold}]}


class FakeGuard:
    def check(self):return GPU


class FakeProcess:
    def __init__(self,done=True):
        self.done=done;self.returncode=0 if done else None;self.killed=False
    def poll(self):return self.returncode
    def kill(self):self.killed=True;self.returncode=-9
    def wait(self,timeout=None):return self.returncode


class LocalTransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.now=0
        self.cpu_count=0;self.spawned=[];self.process=FakeProcess()
        self.value=completed_value();self.high_cpu=False
        self.budget=LocalBudget(self.root/'budget.jsonl',5,create=True,clock=lambda:self.now)
        self.record=self.root/'telemetry.jsonl'

    def tearDown(self):self.budget.close();self.tmp.cleanup()

    def sleep(self,seconds):self.now+=seconds

    def cpu(self):
        self.cpu_count+=1
        idle=80*min(self.cpu_count,2) if self.high_cpu else 80*self.cpu_count
        return idle,100*self.cpu_count,0

    def popen(self,args,**kwargs):
        self.spawned.append((args,kwargs))
        kwargs['stdout'].write(json.dumps(self.value));kwargs['stdout'].flush()
        return self.process

    def transport(self,**kwargs):
        return LocalTransport(self.budget,self.record,guard=FakeGuard(),clock=lambda:self.now,
                sleep=self.sleep,memory_probe=kwargs.pop('memory_probe',lambda:8000),
                cpu_probe=self.cpu,gpu_probe=kwargs.pop('gpu_probe',lambda timeout:GPU),
                popen=kwargs.pop('popen',self.popen),**kwargs)

    def events(self):return [json.loads(line) for line in self.record.read_text().splitlines()]

    def test_success_uses_file_input_sanitized_env_and_observed_cold_status(self):
        self.value=completed_value(cold=False)
        with patch.dict(os.environ,{'OPENROUTER_API_KEY':'SYNTHETIC_SECRET','PYTHONPATH':'untrusted'}):
            result=self.transport()(BODY)
        args,kwargs=self.spawned[0]
        self.assertNotIn('OPENROUTER_API_KEY',kwargs['env'])
        self.assertNotIn('PYTHONPATH',kwargs['env'])
        self.assertIsNone(getattr(self.process,'stdin',None))
        self.assertEqual(json.loads(Path(args[-2]).read_text()),BODY)
        self.assertEqual(result['usage']['input_tokens'],20)
        self.assertFalse(result['usage']['cold_observed'])
        self.assertFalse(self.budget.pending)
        self.assertEqual(self.events()[-1]['event'],'local_outcome')
        self.assertTrue(self.events()[-1]['telemetry_complete'])

    def test_preflight_unknown_memory_persists_block_without_dispatch(self):
        with self.assertRaises(RuntimeError):self.transport(memory_probe=lambda:None)(BODY)
        self.assertFalse(self.spawned);self.assertEqual(self.budget.used,0)
        self.assertEqual(self.events()[-1]['event'],'local_blocked')

    def test_capture_collision_is_charged_and_cannot_dispatch(self):
        (self.root/'local-worker-1.json').write_text('existing')
        with self.assertRaises(FileExistsError):self.transport()(BODY)
        self.assertFalse(self.spawned);self.assertFalse(self.budget.pending)
        self.assertEqual((self.root/'local-worker-1.json').read_text(),'existing')

    def test_spawn_failure_releases_only_measured_reservation(self):
        def fail(*args,**kwargs):self.now+=1;raise OSError('synthetic spawn failure')
        with self.assertRaises(OSError):self.transport(popen=fail)(BODY)
        self.assertEqual(self.budget.used,1);self.assertFalse(self.budget.halted)

    def test_deadline_kills_only_owned_child_and_retains_uncertain_reservation(self):
        self.process=FakeProcess(done=False)
        with self.assertRaises(TimeoutError):self.transport()(BODY)
        self.assertTrue(self.process.killed);self.assertTrue(self.budget.halted)
        self.assertEqual(self.budget.used,5)
        self.assertLessEqual(self.now,5)
        self.assertFalse(self.events()[-1]['server_completion_confirmed'])

    def test_sustained_cpu_contention_stops_owned_worker(self):
        self.process=FakeProcess(done=False);self.high_cpu=True
        with self.assertRaisesRegex(RuntimeError,'sustained CPU'):self.transport()(BODY)
        self.assertTrue(self.process.killed);self.assertTrue(self.budget.halted)

    def test_gpu_probe_failure_is_not_filled_with_default_memory(self):
        self.process=FakeProcess(done=False)
        def unavailable(timeout):raise ResourceProbeUnavailable('synthetic unavailable probe')
        with self.assertRaises(ResourceProbeUnavailable):self.transport(gpu_probe=unavailable)(BODY)
        self.assertTrue(self.process.killed);self.assertFalse(self.events()[-1]['telemetry_complete'])

    def test_gpu_memory_contention_stops_worker(self):
        self.process=FakeProcess(done=False)
        low=[dict(GPU[0],memory_free_mib=100)]
        with self.assertRaises(RuntimeError):self.transport(gpu_probe=lambda timeout:low)(BODY)
        self.assertTrue(self.process.killed);self.assertEqual(self.budget.used,5)

    def test_incomplete_telemetry_halts_instead_of_claiming_zero_usage(self):
        self.value={'response':{},'records':[]}
        with self.assertRaisesRegex(ValueError,'usage record'):self.transport()(BODY)
        self.assertTrue(self.budget.halted);self.assertEqual(self.budget.used,5)
        self.assertFalse(self.events()[-1]['telemetry_complete'])

    def test_invalid_cpu_deltas_fail_closed(self):
        for before,after in (((0,0,0),(0,0,0)),((5,10,10),(4,20,20)),((0,0,0),(200,10,10))):
            with self.subTest(before=before,after=after),self.assertRaises(RuntimeError):cpu_percent(before,after)
        self.assertEqual(cpu_percent((0,0,0),(50,100,0)),50)


class WorkerTests(unittest.TestCase):
    def test_incremental_telemetry_survives_failure_and_records_actual_keep_alive(self):
        with tempfile.TemporaryDirectory() as d:
            request=Path(d)/'request.json';events=Path(d)/'events.jsonl'
            request.write_text(json.dumps(BODY))
            def fail(request,backend):
                backend.record({'event':'local_request','body':{'keep_alive':'5m'}})
                backend.record({'event':'local_response','body':'synthetic malformed response'})
                raise ValueError('synthetic invalid response')
            with patch('sys.argv',['local_worker.py',str(request),str(events)]),patch.object(local_worker,'pick',fail):
                with self.assertRaises(ValueError):local_worker.main()
            records=[json.loads(line) for line in events.read_text().splitlines()]
            self.assertEqual(records[0]['body']['keep_alive'],0)
            self.assertEqual(records[1]['event'],'local_response')
            self.assertEqual(records[-1]['event'],'local_worker_failure')
            self.assertFalse(records[-1]['telemetry_complete'])

    def test_worker_rejects_multiple_questions_before_model_use(self):
        with tempfile.TemporaryDirectory() as d:
            request=Path(d)/'request.json';events=Path(d)/'events.jsonl'
            body={**BODY,'questions':dict(BODY['questions'],second=BODY['questions']['route'])}
            request.write_text(json.dumps(body))
            with patch('sys.argv',['local_worker.py',str(request),str(events)]),patch.object(local_worker,'pick') as pick:
                with self.assertRaisesRegex(ValueError,'exactly one'):local_worker.main()
                pick.assert_not_called()

    def test_release_backend_uses_zero_keepalive_and_bounded_timeout(self):
        backend=local_worker.ImmediateReleaseBackend(lambda event:None,authorized=True)
        with patch('local_capture.RecordingBackend._read',return_value='{}') as read:
            backend._read('/api/generate',{'keep_alive':'5m'},timeout=180)
            self.assertEqual(read.call_args.kwargs['timeout'],50)
            self.assertEqual(read.call_args.args[1]['keep_alive'],0)


if __name__=='__main__':unittest.main()
