import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from adapters import build, canonical
from development import load_development
from measured_tokens import (FrozenTokenizer, DEFAULT_MANIFEST_SHA256, local_renders,
                             measure_attempt, measure_case, measure_journal, summarize)


class FakeTokenizer:
    """Deliberately byte counts for offline plumbing tests; not token evidence."""
    identity='SIMULATED_TEST_ONLY';provenance={'tokenizer_identity':identity}
    def measure(self,text):
        return {'tokens':len(text.encode('utf8')),'utf8_bytes':len(text.encode('utf8')),
                'text_sha256':hashlib.sha256(text.encode('utf8')).hexdigest(),
                'token_ids_sha256':'0'*64}


class AccountingTests(unittest.TestCase):
    def setUp(self):
        self.tokenizer=FakeTokenizer()
        cases,_=load_development()
        self.case=next(c for c in cases if c['state']['unit']['kind']=='semantic' and c['label']['action']=='skip')
        self.request={'event':'request','key':'chat:'+self.case['id']+':1','attempt':1,
                      'arm':'chat','body':build(self.case,'chat')}

    def test_full_payload_includes_system_schema_and_model_settings(self):
        measured=measure_attempt(self.tokenizer,self.request)
        exact=canonical(self.request['body'])
        self.assertEqual(measured['public_serialization']['text_sha256'],hashlib.sha256(exact.encode()).hexdigest())
        self.assertEqual(measured['common_input_proxy_tokens'],len(exact.encode()))
        self.assertIn('response_format',exact);self.assertIn('system',exact)
        self.assertFalse(measured['h1_eligible'])
        self.assertIsNone(measured['provider_native_tokens'])

    def test_retry_and_failed_attempt_overhead_both_counted(self):
        first=measure_attempt(self.tokenizer,self.request,
            {'event':'result','key':self.request['key'],'attempt':1,'status':503,'body':'{"error":"synthetic"}'})
        second=measure_attempt(self.tokenizer,{**self.request,'attempt':2})
        measured=measure_case(self.tokenizer,self.case,[first,second])
        report=summarize([self.case],{self.case['id']:'skip'},{self.case['id']:measured},self.tokenizer.identity)
        self.assertEqual(report['attempts'],2)
        self.assertEqual(report['routing_input_proxy_tokens'],2*first['common_input_proxy_tokens'])
        self.assertIsNone(report['routing_observed_output_tokens'])
        self.assertLess(report['net_input_proxy_tokens_saved'],report['safely_avoided_reading_tokens'])

    def test_observed_output_and_native_usage_stay_separate(self):
        result={'event':'result','key':self.request['key'],'attempt':1,'status':200,
                'body':json.dumps({'choices':[{'message':{'content':'{"choice":"review"}'}}],
                                   'usage':{'prompt_tokens':1234,'completion_tokens':7}})}
        measured=measure_attempt(self.tokenizer,self.request,result)
        self.assertEqual(measured['provider_native_tokens'],{'input_tokens':1234,'output_tokens':7})
        self.assertEqual(measured['observed_generated_output']['tokens'],len('{"choice":"review"}'))
        self.assertNotEqual(measured['common_input_proxy_tokens'],1234)

    def test_changed_guide_and_mixed_tokenizer_refused(self):
        measured=measure_case(self.tokenizer,self.case,[])
        changed={**self.case,'document':self.case['document']+' changed'}
        with self.assertRaisesRegex(ValueError,'guide changed'):
            summarize([changed],{changed['id']:'skip'},{changed['id']:measured},self.tokenizer.identity)
        attempt=measure_attempt(self.tokenizer,self.request);attempt['tokenizer_identity']='other'
        with self.assertRaisesRegex(ValueError,'mixed tokenizer'):measure_case(self.tokenizer,self.case,[attempt])

    def test_duplicate_attempts_or_repeats_refused(self):
        first=measure_attempt(self.tokenizer,self.request)
        with self.assertRaises(ValueError):measure_case(self.tokenizer,self.case,[first,first])
        second={**first,'key':self.request['key'][:-1]+'2'}
        with self.assertRaises(ValueError):measure_case(self.tokenizer,self.case,[first,second])

    def test_local_render_matches_frozen_template_and_generated_letter(self):
        body=build(self.case,'local');request={**self.request,'arm':'local','body':body}
        prompts=local_renders(body)
        self.assertEqual(len(prompts),1)
        self.assertTrue(prompts[0].startswith('Reply with exactly one letter.'))
        self.assertTrue(prompts[0].endswith('Answer:'))
        result={'event':'result','key':request['key'],'attempt':1,'status':200,
                'body':json.dumps({'answers':{'route':{'generated_token':'A'}}})}
        measured=measure_attempt(self.tokenizer,request,result)
        self.assertEqual(measured['common_input_proxy_tokens'],len(prompts[0].encode()))
        self.assertEqual(measured['observed_generated_output']['tokens'],1)
        self.assertIsNone(measured['provider_native_tokens'])

    def test_jev_decision_is_not_fabricated_generated_output(self):
        request={**self.request,'arm':'jev','body':build(self.case,'jev')}
        result={'event':'result','key':request['key'],'attempt':1,'status':200,
                'body':json.dumps({'answers':{'route':{'choice':'skip'}},'usage':{'input_tokens':10,'output_tokens':0}})}
        measured=measure_attempt(self.tokenizer,request,result)
        self.assertIsNone(measured['observed_generated_output'])
        self.assertEqual(measured['provider_native_tokens']['output_tokens'],0)

    def test_journal_keeps_pending_and_counts_all_retries(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'journal.jsonl'
            records=[{'event':'reserved','key':self.request['key'],'attempt':1},self.request,
                     {'event':'result','key':self.request['key'],'attempt':1,'body':'bad'},
                     {'event':'reserved','key':self.request['key'],'attempt':2},{**self.request,'attempt':2},
                     {'event':'reserved','key':'undispatched','attempt':1}]
            path.write_text(''.join(canonical(e)+'\n' for e in records))
            measured=measure_journal(self.tokenizer,path)
            self.assertEqual(len(measured['attempts']),2)
            self.assertFalse(measured['attempts'][1]['response_observed'])
            self.assertEqual(measured['reserved_without_request'],[{'key':'undispatched','attempt':1}])
            path.write_text(path.read_text()[:-1])
            with self.assertRaisesRegex(ValueError,'incomplete'):measure_journal(self.tokenizer,path)

    def test_executable_skip_never_invents_reading_savings(self):
        cases,_=load_development()
        case=next(c for c in cases if c['state']['unit']['kind']=='executable' and c['label']['action']=='skip')
        measured=measure_case(self.tokenizer,case,[])
        report=summarize([case],{case['id']:'skip'},{case['id']:measured},self.tokenizer.identity)
        self.assertEqual(report['baseline_reading_tokens'],0)
        self.assertEqual(report['safely_avoided_reading_tokens'],0)
        self.assertIsNone(report['input_proxy_fraction_saved'])


@unittest.skipUnless(os.environ.get('ALDERTRACE_TOKENIZER_ENV'),'requires explicitly supplied isolated tokenizer path')
class InstalledTokenizerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # A network failure here is a test failure: construction must stay offline.
        with patch('socket.socket.connect',side_effect=AssertionError('unexpected network')):
            cls.tokenizer=FrozenTokenizer(os.environ['ALDERTRACE_TOKENIZER_ENV'])

    def test_known_token_ids_and_exact_text_hash(self):
        self.assertEqual(self.tokenizer.tokens('hello world'),[24912,2375])
        measured=self.tokenizer.measure('hello world')
        self.assertEqual(measured['tokens'],2)
        self.assertEqual(measured['text_sha256'],hashlib.sha256(b'hello world').hexdigest())
        self.assertEqual(self.tokenizer.tokens(''),[])

    def test_literal_special_tokens_roundtrip_without_control_ids(self):
        text='Synthetic <|endoftext|> café 東京'
        tokens=self.tokenizer.tokens(text)
        self.assertNotIn(199999,tokens)
        self.assertEqual(self.tokenizer.encoding.decode(tokens),text)

    def test_changed_manifest_identity_refused_before_import(self):
        with self.assertRaisesRegex(ValueError,'manifest hash'):
            FrozenTokenizer(os.environ['ALDERTRACE_TOKENIZER_ENV'],expected_manifest_sha256='0'*64)

    def test_changed_asset_hash_refused(self):
        m=self.tokenizer.manifest
        with self.assertRaisesRegex(ValueError,'asset changed'):
            self.tokenizer._verify(m['vocabulary']['path'],'0'*64)


if __name__=='__main__':unittest.main()
