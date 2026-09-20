import json
import tempfile
import unittest
from pathlib import Path
from journal import Journal,execute_one,replay,BudgetExceeded


class Recording(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'attempts.jsonl'
    def tearDown(self):self.tmp.cleanup()
    def test_budget_blocks_before_dispatch(self):
        j=Journal(self.path,'.01'); calls=[]
        try:
            with self.assertRaises(BudgetExceeded):
                execute_one(j,'x','jev',{},'jev','.02',lambda b:calls.append(b))
            self.assertEqual(calls,[])
        finally:j.close()
    def test_timeout_reserved_no_retry_and_secret_redacted(self):
        j=Journal(self.path,'.10',secrets=['SYNTHETIC_SECRET'])
        def fail(body):raise TimeoutError('SYNTHETIC_SECRET')
        try:
            execute_one(j,'x','jev',{'synthetic':'SYNTHETIC_SECRET'},'jev','.01',fail)
        finally:j.close()
        text=self.path.read_text()
        self.assertNotIn('SYNTHETIC_SECRET',text)
        r=replay(self.path)
        self.assertEqual(r['results']['x']['billing'],'uncertain')
        self.assertEqual(j.attempts['x'],1)
        self.assertEqual(str(j.reserved),'0.01')
    def test_http_retry_limit_and_no_auth_retry(self):
        for status,n in ((503,2),(401,1),(422,1),(200,1)):
            path=self.path.with_name(str(status)+'.jsonl')
            j=Journal(path,'.10'); delays=[]
            try:
                execute_one(j,'x','jev',{},'jev','.01',lambda b:{'status':status,'body':'{}'},sleep=delays.append)
                self.assertEqual(j.attempts['x'],n)
            finally:j.close()
    def test_durable_reservation_and_exclusive_creation(self):
        j=Journal(self.path,'.10')
        j.reserve('x','.01'); j.close()
        self.assertEqual(replay(self.path)['unfinished_attempts'],[('x',1)])
        with self.assertRaises(FileExistsError):Journal(self.path,'.10')
    def test_repeated_key_blocked_and_raw_invalid_preserved(self):
        j=Journal(self.path,'.10')
        try:
            response={'status':200,'body':'this is not JSON'}
            result=execute_one(j,'x','jev',{},'jev','.01',lambda b:response)
            self.assertFalse(result['valid'])
            with self.assertRaises(ValueError):
                execute_one(j,'x','jev',{},'jev','.01',lambda b:response)
        finally:j.close()
        self.assertEqual(replay(self.path)['results']['x']['body'],'this is not JSON')

    def test_malformed_transport_envelopes_are_recorded_without_retry(self):
        envelopes=(None,[],{}, {'status':200}, {'status':200,'body':None},
            {'status':200.0,'body':'{}'}, {'status':True,'body':'{}'},
            {'status':600,'body':'{}'}, {'status':200,'body':'{}','request_id':[]})
        for index,envelope in enumerate(envelopes):
            with self.subTest(envelope=envelope):
                path=self.path.with_name(f'malformed-{index}.jsonl')
                j=Journal(path,'.10');calls=[]
                def malformed(body):calls.append(body);return envelope
                try:
                    self.assertIsNone(execute_one(j,'x','jev',{},'jev','.01',malformed))
                finally:j.close()
                self.assertEqual(len(calls),1)
                self.assertEqual(str(j.reserved),'0.01')
                record=replay(path)
                self.assertEqual(record['unfinished_attempts'],[])
                self.assertEqual(record['results']['x']['error_type'],'InvalidTransportEnvelope')
                self.assertEqual(record['results']['x']['billing'],'uncertain')

    def test_malformed_envelope_preserves_redacted_body(self):
        j=Journal(self.path,'.10',secrets=['SYNTHETIC_SECRET'])
        try:
            execute_one(j,'x','jev',{},'jev','.01',
                lambda b:{'status':None,'body':'SYNTHETIC_SECRET invalid status'})
        finally:j.close()
        self.assertEqual(replay(self.path)['results']['x']['body'],'[REDACTED] invalid status')

if __name__=='__main__':unittest.main()
