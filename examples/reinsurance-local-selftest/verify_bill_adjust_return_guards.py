"""31 first return reuses identity guards and requires already-owned receiver task."""
import unittest
from pathlib import Path
import verify_bill_adjust_claim_guards as claim
class FirstReturnTests(claim.GuardTests):
 @classmethod
 def setUpClass(cls):
  cls.previous=claim.P;claim.P=Path(__file__).parent/'rejection_bill_adjust_steps/06-first-return.py'
 @classmethod
 def tearDownClass(cls):claim.P=cls.previous
 def test_unowned_task_cannot_reject(self):
  i,answers=self.fixture();i['platform_treaty_no']='000050-2026PT00011';self.stop(answers,i,'尚未由经纪账号领取')
if __name__=='__main__':unittest.main()
