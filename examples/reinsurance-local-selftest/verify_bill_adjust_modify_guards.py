"""Offline31 modify guards: snapshot protection and readonly recovery cannot claim."""
import unittest
from pathlib import Path
import verify_bill_cb_guards as cb
from verify_guards import result
class ModifyTests(cb.ModifyGuards):
 @classmethod
 def setUpClass(cls):cls.previous=cb.ROOT;cb.ROOT=Path(__file__).parent/'rejection_bill_adjust_steps'
 @classmethod
 def tearDownClass(cls):cb.ROOT=cls.previous
 def test_readonly_recovery_cannot_claim_unowned_task(self):
  i=dict(statement_id=544944,v1_comment='OWN',v2_comment='OWN V2',verify_saved_only=True,normal_id=11,downstream_normal_id=12,snapshot_id=998,snapshot_sha256='x'*64,ab_platform_no='A001',bill_label='NEW',expected_biz_id='BIZ',platform_treaty_no='T')
  states=result([dict(statement_normal_id=n,org_code=o,reinsurance_role=r,statement_status=s) for n,o,r,s in [(11,'000050','01',13),(11,'000053','02',4),(12,'000045','02',0),(12,'000053','01',0)]])
  snap=result([dict(id=998,is_deleted='N',snapshot_sha256='x'*64,frozen_comment='OWN')])
  master=result([dict(treaty_id=325094,record_no=None,treaty_statement_type='31',former_platform_statement_no='000050-2026PT00011-SOA0001')])
  rows=[]
  for id,frm,to,parent,party,old in [(11,'000050','000053',None,10925281,'257312'),(12,'000053','000045',11,10925282,'257313')]:rows.append(dict(id=id,input_org_code=frm,enter_org_code=to,parent_id=parent,treaty_reinsurer_id=party,former_statement_normal_id=old,currency='CNY',net_balance='1000.00',platform_statement_no='A001',cedent_statement_no='NEW-AB',biz_id='BIZ',business_comment='OWN V2',reviewer=None))
  class C:
   def __init__(self):self.calls=[];self.replies=iter([states,snap,master,result(rows)])
   async def call(self,a,p):
    self.calls.append(a)
    if a!='tidb.query':raise AssertionError('readonly recovery attempted '+a)
    return next(self.replies)
   def log(self,*args):pass
  c=C()
  with self.assertRaisesRegex(ValueError,'只读恢复不能领取'):cb.execute('08-modify-comment-and-verify-v1.py',c,i)
  self.assertEqual(c.calls,['tidb.query']*4)
if __name__=='__main__':unittest.main()
