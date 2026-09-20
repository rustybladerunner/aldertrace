import io,json,unittest
from local_capture import RecordingBackend
from adapters import MODELS,LOCAL_DIGEST,ROOT,local_with_backend

class Fake:
    def __init__(self):self.calls=[];self.digest=LOCAL_DIGEST;self.running=[];self.omit=None
    def open(self,req,timeout):
        self.calls.append((req.full_url,timeout))
        if req.full_url.endswith('/tags'):d={'models':[{'name':MODELS['local'],'digest':self.digest}]}
        elif req.full_url.endswith('/ps'):d={'models':self.running}
        else:
            d={'model':MODELS['local'],'done':True,'response':'A',
               'logprobs':[{'top_logprobs':[{'token':k,'logprob':v} for k,v in zip('ABCD',[-.1,-2,-3,-4])]}],
               'prompt_eval_count':100,'eval_count':1,'load_duration':100,'prompt_eval_duration':200,
               'eval_duration':30,'total_duration':330}
            if self.omit:d.pop(self.omit)
        return io.BytesIO(json.dumps(d).encode())

class Local(unittest.TestCase):
    def test_authorization_before_any_request(self):
        fake=Fake()
        with self.assertRaises(PermissionError):RecordingBackend(lambda r:None,opener=fake)
        self.assertEqual(fake.calls,[])
    def test_existing_engine_and_raw_timing_preserved(self):
        fake=Fake();records=[]
        backend=RecordingBackend(records.append,authorized=True,opener=fake)
        case=next(c for c in json.loads((ROOT/'study/cases.json').read_text()) if c['split']=='development')
        result=local_with_backend(case,backend)
        self.assertEqual(result['answers']['route']['status'],'ok')
        self.assertEqual([r['event'] for r in records],['local_request','local_response','local_usage'])
        self.assertEqual(records[-1]['prompt_eval_count'],100)
        self.assertTrue(records[-1]['cold_observed'])
    def test_changed_digest_or_other_model_prevents_generation(self):
        for other in (False,True):
            fake=Fake()
            if other:fake.running=[{'name':'other-model','digest':'different'}]
            else:fake.digest='changed'
            backend=RecordingBackend(lambda r:None,authorized=True,opener=fake)
            with self.assertRaises(ValueError):backend.next_token('synthetic',model=MODELS['local'])
            self.assertFalse(any('/generate' in url for url,t in fake.calls))
    def test_missing_telemetry_keeps_raw_body_and_fails(self):
        fake=Fake();fake.omit='load_duration';records=[]
        backend=RecordingBackend(records.append,authorized=True,opener=fake)
        with self.assertRaises(ValueError):backend.next_token('synthetic',model=MODELS['local'])
        self.assertEqual(records[-1]['event'],'local_response')
    def test_deadline_and_request_count_prevent_dispatch(self):
        fake=Fake();now=[0]
        backend=RecordingBackend(lambda r:None,authorized=True,opener=fake,clock=lambda:now[0])
        now[0]=3600
        with self.assertRaises(ValueError):backend.next_token('synthetic',model=MODELS['local'])
        self.assertEqual(fake.calls,[])
        now[0]=0;backend.calls=290
        with self.assertRaises(ValueError):backend.next_token('synthetic',model=MODELS['local'])
        self.assertEqual(fake.calls,[])

if __name__=='__main__':unittest.main()
