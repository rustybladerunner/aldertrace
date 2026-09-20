import unittest
import io
import json
import datetime
from transport import CloudTransport,NoRedirect,retry_seconds,usage
from adapters import MODELS,ENDPOINTS

class Response(io.BytesIO):
    code=200
    headers={'x-request-id':'fixture-id'}
class FakeOpener:
    def __init__(self,body=b'{}'):self.calls=[];self.body=body
    def open(self,req,timeout):self.calls.append((req,timeout));return Response(self.body)

class Transport(unittest.TestCase):
    def test_no_authorization_no_dispatch(self):
        fake=FakeOpener()
        with self.assertRaises(PermissionError):CloudTransport('jev','synthetic',opener=fake)
        self.assertEqual(fake.calls,[])
    def test_endpoint_timeout_and_headers_are_bounded(self):
        fake=FakeOpener();transport=CloudTransport('jev','synthetic',authorized=True,opener=fake)
        r=transport({'model':MODELS['jev'],'state':'synthetic'})
        self.assertEqual(fake.calls[0][0].full_url,ENDPOINTS['jev'])
        self.assertEqual(fake.calls[0][1],30)
        self.assertNotIn('synthetic',json.dumps(r))
        self.assertIsNone(NoRedirect().redirect_request(None,None,None,None,None,None))
    def test_size_model_and_output_limit_checked_before_dispatch(self):
        fake=FakeOpener();t=CloudTransport('chat','synthetic',authorized=True,opener=fake)
        for body in ({'model':'wrong'},{'model':MODELS['chat'],'max_tokens':999},
                     {'model':MODELS['chat'],'max_tokens':512,'state':'x'*5000}):
            with self.assertRaises(ValueError):t(body)
        self.assertEqual(fake.calls,[])
    def test_response_size_limit(self):
        t=CloudTransport('jev','synthetic',authorized=True,opener=FakeOpener(b'x'*70000))
        with self.assertRaises(ValueError):t({'model':MODELS['jev']})
    def test_retry_after_date_and_bad_header(self):
        now=datetime.datetime(2026,9,19,tzinfo=datetime.timezone.utc)
        self.assertEqual(retry_seconds('Sat, 19 Sep 2026 00:00:05 GMT',now),5)
        self.assertGreater(retry_seconds('bad header'),30)
    def test_usage_separates_estimated_from_reported(self):
        direct=usage(json.dumps({'usage':{'input_tokens':1000,'output_tokens':100}}),'jev')
        self.assertIsNone(direct['reported_usd'])
        chat=usage(json.dumps({'usage':{'prompt_tokens':1000,'completion_tokens':100,'cost':.002}}),'chat')
        self.assertEqual(chat['accounting_usd'],'0.002')
    def test_missing_or_over_envelope_usage_rejected(self):
        for u in ({},{'input_tokens':True,'output_tokens':0},{'input_tokens':5001,'output_tokens':0},
                  {'input_tokens':1,'output_tokens':0,'cost':-1},
                  {'input_tokens':1,'output_tokens':0,'cost':'invalid'}):
            with self.assertRaises(ValueError):usage(json.dumps({'usage':u}),'jev')

if __name__=='__main__':unittest.main()
