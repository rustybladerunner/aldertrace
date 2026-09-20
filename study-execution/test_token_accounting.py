import copy
import hashlib
import unittest
from token_accounting import account

C={'id':'synthetic','family':'fixture','document':'synthetic guide','label':{'action':'skip'},
   'state':{'scope_known':True,'unit':{'kind':'semantic'},'current_revision':'synthetic',
            'runner_evidence':[],'explanation':'fixture'}}
M={'tokenizer_identity':'fixture-tokenizer-only','status':'measured',
   'document_sha256':hashlib.sha256(C['document'].encode()).hexdigest(),
   'router_input_sha256':'a'*64,'document_tokens':100,'router_input_tokens':20}

class Tokens(unittest.TestCase):
    def run_case(self,c=C,m=M,pred='skip'):
        return account([c],{c['id']:pred},{c['id']:m},'fixture-tokenizer-only')
    def test_overhead_subtracted_and_negative_savings_retained(self):
        self.assertEqual(self.run_case()['fraction_saved'],.8)
        m={**M,'router_input_tokens':120}
        self.assertEqual(self.run_case(m=m)['fraction_saved'],-.2)
    def test_unsafe_skip_never_earns_saved_reading(self):
        c=copy.deepcopy(C);c['label']['action']='read'
        self.assertEqual(self.run_case(c=c)['avoided_input_tokens'],0)
    def test_machine_check_does_not_invent_guide_savings(self):
        c=copy.deepcopy(C);c['state']['unit']['kind']='executable'
        result=self.run_case(c=c)
        self.assertEqual(result['baseline_input_tokens'],0)
        self.assertIsNone(result['fraction_saved'])
        self.assertEqual(result['net_input_tokens_saved'],-20)
    def test_estimate_mixed_tokenizer_and_changed_document_rejected(self):
        for patch in ({'status':'estimated'},{'tokenizer_identity':'different'},
                      {'document_sha256':'b'*64},{'router_input_sha256':'missing'},
                      {'router_input_tokens':True},{'document_tokens':-1}):
            with self.subTest(patch=patch):
                with self.assertRaises(ValueError):self.run_case(m={**M,**patch})
    def test_repeated_case_cannot_inflate_savings(self):
        with self.assertRaises(ValueError):account([C,C],{'synthetic':'skip'},{'synthetic':M},'fixture-tokenizer-only')

if __name__=='__main__':unittest.main()
