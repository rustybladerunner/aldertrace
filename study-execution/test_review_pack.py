import unittest
import tempfile
import csv
import json
from pathlib import Path
from review_pack import select,export,assess,ROOT

class ReviewTests(unittest.TestCase):
    def test_full_semantic_and_balanced_machine_coverage(self):
        cases=json.loads((ROOT/'study/cases.json').read_text())
        rows=select(cases)
        self.assertEqual(len(rows),144)
        for family in {c['family'] for c in cases if c['state']['unit']['kind']=='executable'}:
            group=[c for c in rows if c['family']==family]
            self.assertEqual(len(group),4)
            self.assertEqual(sum(c['label']['action']=='skip' for c in group),2)
        self.assertEqual(sum(c['state']['unit']['kind']=='semantic' for c in rows),120)

    def test_blank_review_is_not_approval_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'review.csv';export(path)
            self.assertEqual(len(assess(path)['pending']),144)
            self.assertFalse(assess(path)['adjudicated'])
            with self.assertRaises(FileExistsError):export(path)
            with path.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
            rows[0]['state']='changed'
            with path.open('w',encoding='utf-8-sig',newline='') as f:
                w=csv.DictWriter(f,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)
            with self.assertRaises(ValueError):assess(path)

if __name__=='__main__':unittest.main()
