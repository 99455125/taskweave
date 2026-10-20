"""No live calls: owned31 claim refuses other master, wrong source and snapshots."""
import asyncio,unittest
from pathlib import Path
from verify_guards import result
P=Path(__file__).parent/'rejection_bill_adjust_steps/05-broker-pending-and-claim.py'
class GuardTests(unittest.TestCase):
 def fixture(self):
  label='TW-LOCAL-BILL-ADJ-20261016080007';v1='仅供本地自测 '+label
  i=dict(statement_id=544944,record_no=None,normal_id=257328,downstream_normal_id=257329,bill_label=label,v1_comment=v1,expected_biz_id='owned-local-bill-adj-20261016080007')
  m=result([dict(id=544944,treaty_id=325094,record_no=None,treaty_statement_type='31',former_platform_statement_no='000050-2026PT00011-SOA0001',comment=v1)])
  a=dict(id=257328,input_org_code='000050',enter_org_code='000053',parent_id=None,treaty_reinsurer_id=10925281,currency='CNY',net_balance='1000.00',cedent_statement_no=label+'-AB',biz_id=i['expected_biz_id'],business_comment=v1,platform_statement_no='000050-2026PT00011-A001',reviewer=None,former_statement_normal_id='257312')
  b=dict(id=257329,input_org_code='000053',enter_org_code='000045',parent_id=257328,treaty_reinsurer_id=10925282,currency='CNY',net_balance='1000.00',former_statement_normal_id='257313')
  states=result([dict(statement_normal_id=id,org_code=org,reinsurance_role=role,statement_status=status) for id,org,role,status in [(257328,'000050','01',3),(257328,'000053','02',3),(257329,'000045','02',0),(257329,'000053','01',0)]])
  return i,[m,result([a,b]),states,result([])]
 def stop(self,answers,i,message):
  class C:
   def __init__(self):self.answers=iter(answers);self.calls=[]
   async def call(self,a,p):
    self.calls.append(a)
    if a!='tidb.query':raise AssertionError('unsafe guard reached '+a)
    return next(self.answers)
  c=C();ns={};exec(compile(P.read_text(),str(P),'exec'),ns)
  with self.assertRaisesRegex(ValueError,message):asyncio.run(ns['run'](c,i))
  self.assertEqual(c.calls,['tidb.query']*len(answers))
 def test_wrong_type_blocks_before_claim(self):
  i,a=self.fixture();a[0]['rows'][0]['treaty_statement_type']='01';self.stop(a[:1],i,'31原AB')
 def test_wrong_original_child_blocks_claim(self):
  i,a=self.fixture();a[1]['rows'][1]['former_statement_normal_id']='999';self.stop(a[:2],i,'原normal引用')
 def test_receiver_not_pending_blocks_claim(self):
  i,a=self.fixture();a[2]['rows'][1]['statement_status']=4;self.stop(a[:3],i,'首次经纪待确认')
 def test_existing_snapshot_blocks_first_round(self):
  i,a=self.fixture();a[3]=result([dict(id=999)]);self.stop(a,i,'已存在退回快照')
if __name__=='__main__':unittest.main()
