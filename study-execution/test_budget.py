import json
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from budget import CampaignBudget
from journal import Journal, execute_one, BudgetExceeded


class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.path=self.root/'budget.jsonl'
    def tearDown(self): self.tmp.cleanup()

    def test_two_run_directories_share_one_cap(self):
        calls=[]
        for n in (1,2):
            with CampaignBudget(self.path,'.01',create=n==1) as budget:
                j=Journal(self.root/f'{n}.jsonl','2',campaign=budget,scope=str(n))
                try:
                    action=lambda:execute_one(j,'request','jev',{},'jev','.006',lambda b:calls.append(b))
                    if n==1:
                        # Transport error has uncertain billing and must retain its reservation.
                        def timeout(body):calls.append(body);raise TimeoutError()
                        execute_one(j,'request','jev',{},'jev','.006',timeout)
                    else:
                        with self.assertRaises(BudgetExceeded):action()
                    self.assertEqual(budget.reserved,Decimal('.006'))
                finally:j.close()
        self.assertEqual(len(calls),1)

    def test_retry_reservation_blocks_second_dispatch(self):
        calls=[]
        with CampaignBudget(self.path,'.01',create=True) as budget:
            j=Journal(self.root/'a.jsonl','2',campaign=budget,scope='a')
            try:
                def unavailable(body):calls.append(body);return {'status':503,'body':'{}'}
                with self.assertRaises(BudgetExceeded):
                    execute_one(j,'x','jev',{},'jev','.006',unavailable,sleep=lambda _:None)
            finally:j.close()
        self.assertEqual(len(calls),1)

    def test_process_crash_releases_lock_but_keeps_charge(self):
        script='from budget import CampaignBudget; import os,sys; b=CampaignBudget(sys.argv[1],".01",create=True); b.reserve("uncertain",".008"); os._exit(0)'
        subprocess.run([sys.executable,'-B','-c',script,str(self.path)],cwd=Path(__file__).parent,check=True)
        with CampaignBudget(self.path,'.01') as budget:
            self.assertEqual(budget.reserved,Decimal('.008'))
            with self.assertRaises(BudgetExceeded):budget.reserve('new','.003')
            with self.assertRaises(ValueError):budget.reserve('uncertain','.001')

    def test_concurrent_writer_is_refused(self):
        with CampaignBudget(self.path,'.01',create=True):
            script='from budget import CampaignBudget; import sys;\ntry: CampaignBudget(sys.argv[1],".01")\nexcept OSError: sys.exit(0)\nsys.exit(9)'
            p=subprocess.run([sys.executable,'-B','-c',script,str(self.path)],cwd=Path(__file__).parent)
            self.assertEqual(p.returncode,0)

    def test_changed_cap_or_recreation_refused(self):
        with CampaignBudget(self.path,'.01',create=True): pass
        with self.assertRaises(FileExistsError):CampaignBudget(self.path,'.01',create=True)
        with self.assertRaises(ValueError):CampaignBudget(self.path,'2')

    def test_partial_or_forged_ledger_refused(self):
        with CampaignBudget(self.path,'.01',create=True) as budget:budget.reserve('x','.006')
        original=self.path.read_bytes()
        for data in (original[:-1], original.replace(b'0.006',b'0.060'), original+b'{bad}\n'):
            self.path.write_bytes(data)
            with self.assertRaises(ValueError):CampaignBudget(self.path,'.01')

    def test_halt_survives_reopen(self):
        with CampaignBudget(self.path,'.01',create=True) as budget:budget.halt()
        with CampaignBudget(self.path,'.01') as budget:
            with self.assertRaises(BudgetExceeded):budget.reserve('x','.001')

    def test_global_reservation_survives_local_journal_write_failure(self):
        with CampaignBudget(self.path,'.01',create=True) as budget:
            j=Journal(self.root/'a.jsonl','2',campaign=budget,scope='a')
            j.write=lambda event:(_ for _ in ()).throw(OSError('synthetic disk failure'))
            try:
                with self.assertRaises(OSError):j.reserve('x','.008')
                self.assertEqual(budget.reserved,Decimal('.008'))
            finally:j.close()
        with CampaignBudget(self.path,'.01') as budget:
            with self.assertRaises(BudgetExceeded):budget.reserve('other','.003')

if __name__=='__main__':unittest.main()
