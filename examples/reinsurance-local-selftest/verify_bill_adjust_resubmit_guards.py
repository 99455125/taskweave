"""31 sync resubmit must reject wrong V2 rule, completed stage and changed snapshot."""
import unittest
from pathlib import Path
import verify_bill_cb_guards as cb
from verify_guards import result
class ResubmitTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.previous=cb.ROOT;cb.ROOT=Path(__file__).parent/'rejection_bill_adjust_steps'
 @classmethod
 def tearDownClass(cls):cb.ROOT=cls.previous
 def test_wrong_v2_rule_before_any_action(self):
  c=cb.ReadContext({})
  with self.assertRaisesRegex(ValueError,'V2备注规则'):cb.execute('10-synchronous-resubmit.py',c,dict(v1_comment='V1',v2_comment='OTHER'))
  self.assertEqual(c.calls,[])
 def test_already_resubmitted_cannot_replay(self):
  c=cb.ReadContext(dict(statement_normal_id=11,org_code='000050',reinsurance_role='01',statement_status=3))
  with self.assertRaisesRegex(ValueError,'退回待修改阶段'):cb.execute('10-synchronous-resubmit.py',c,dict(v1_comment='V1',v2_comment='V1 V2',normal_id=11,downstream_normal_id=12))
  self.assertEqual(c.calls,['tidb.query'])
 def test_retired_first_snapshot_stops_before_login(self):
  states=result([dict(statement_normal_id=n,org_code=o,reinsurance_role=r,statement_status=s) for n,o,r,s in [(11,'000050','01',13),(11,'000053','02',4),(12,'000045','02',0),(12,'000053','01',0)]])
  class C:
   def __init__(self):self.calls=[];self.replies=iter([states,result([dict(id=998,is_deleted='Y',snapshot_sha256='x'*64,frozen_comment='V1')])])
   async def call(self,a,p):
    self.calls.append(a)
    if a!='tidb.query':raise AssertionError('unsafe action '+a)
    return next(self.replies)
  c=C()
  with self.assertRaisesRegex(ValueError,'V1快照已变化'):cb.execute('10-synchronous-resubmit.py',c,dict(v1_comment='V1',v2_comment='V1 V2',normal_id=11,downstream_normal_id=12,snapshot_id=998,snapshot_sha256='x'*64))
  self.assertEqual(c.calls,['tidb.query']*2)
if __name__=='__main__':unittest.main()
