import unittest
import json
import copy
from analysis import wilson,cluster_ratio,reliability,summarize,stability
from adapters import ROOT

CASES=[c for c in json.loads((ROOT/'study/cases.json').read_text()) if c['split']=='development']

def answer(choice,confidence=1):
    return {'choice':choice,'confidence':confidence,'probabilities':{
        k:float(k==choice) for k in ('skip','read','run_check','review')}}


class Metrics(unittest.TestCase):
    def test_zero_errors_is_not_zero_uncertainty(self):
        self.assertGreater(wilson(0,40)[1],.08)
        self.assertLess(wilson(0,40)[1],.09)
        self.assertIsNone(wilson(0,0))
        with self.assertRaises(ValueError):wilson(41,40)

    def test_forced_unsafe_distinguishes_raw_and_hybrid(self):
        cases=[c for c in CASES if c['state']['unit']['kind']=='executable']
        result=summarize(cases,{c['id']:answer('skip') for c in cases},.9)
        self.assertEqual(result['arms']['raw']['overall']['unsafe_skips'],20)
        self.assertEqual(result['arms']['hybrid']['overall']['unsafe_skips'],0)
        self.assertEqual(result['arms']['raw']['overall']['non_skippable'],20)
        self.assertTrue(any(f['raw_unsafe_skip'] for f in result['failures']))

    def test_perfect_brier_and_invalid_exclusion(self):
        cases=CASES[:3]
        answers={c['id']:answer(c['label']['action']) for c in cases}
        answers[cases[0]['id']]=None
        result=summarize(cases,answers,.9)
        self.assertEqual(result['invalid_count'],1)
        self.assertEqual(result['brier_valid_n'],2)
        self.assertEqual(result['multiclass_brier'],0)
        self.assertIsNone(result['arms']['hybrid']['overall']['token_savings'])

    def test_bad_probability_is_not_scored_as_valid(self):
        c=CASES[0];a=answer('skip');a['probabilities']['skip']=float('nan')
        result=summarize([c],{c['id']:a},.9)
        self.assertIsNone(result['multiclass_brier'])
        self.assertEqual(result['reliability']['confidence']['omitted_invalid'],1)

    def test_reliability_one_in_last_bin_and_distinct_signals(self):
        c=CASES[0];a=answer('skip',.2)
        r=reliability([c],{c['id']:a},'max_probability')
        self.assertEqual(r['bins'][-1]['n'],1)
        r=reliability([c],{c['id']:a},'confidence')
        self.assertEqual(r['bins'][1]['n'],1)

    def test_cluster_draws_are_families_and_reproducible(self):
        a=cluster_ratio([(0,20),(20,20)],draws=1000)
        self.assertEqual(a,cluster_ratio([(0,20),(20,20)],draws=1000))
        self.assertEqual(a['families'],2)
        self.assertEqual(a['percentile_95'],[0,1])
        self.assertEqual(cluster_ratio([(0,0)],draws=10)['undefined_draws'],10)

    def test_repetitions_not_independent_examples(self):
        rows=[{'case_id':'a','trial':i,'answer':answer('read' if i==3 else 'skip')} for i in (1,2,3)]
        r=stability(rows)
        self.assertEqual(r['n_unique'],1);self.assertEqual(r['observations'],3)
        self.assertEqual(r['changed_choice_cases'],1)
        with self.assertRaises(ValueError):stability(rows[:2])
        with self.assertRaises(ValueError):stability(rows+rows[:1])

    def test_primary_rejects_missing_or_duplicate_cases(self):
        c=CASES[0]
        with self.assertRaises(ValueError):summarize([c],{},.9)
        with self.assertRaises(ValueError):summarize([c,c],{c['id']:answer('skip')},.9)

if __name__=='__main__':unittest.main()
