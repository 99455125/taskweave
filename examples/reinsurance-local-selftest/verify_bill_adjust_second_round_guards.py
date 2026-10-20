"""Offline second-round guards: no live auth, claim, browser or business mutations."""
import asyncio,unittest
from pathlib import Path
import verify_bill_adjust_claim_guards as claim
from verify_guards import result
ROOT=Path(__file__).parent/'rejection_bill_adjust_steps'
class GuardTests(unittest.TestCase):
 def fixture(self):
  i,a=claim.GuardTests().fixture();i.update(v2_comment=i['v1_comment']+' V2',snapshot_id=60013,snapshot_sha256='x'*64,platform_treaty_no='000050-2026PT00011',ab_platform_no='000050-2026PT00011-A001');a[1]['rows'][0]['business_comment']=i['v2_comment'];return i,a
 def stop(self,name,answers,i,message):
  class C:
   def __init__(self):self.replies=iter(answers);self.calls=[]
   async def call(self,a,p):
    self.calls.append(a)
    if a!='tidb.query':raise AssertionError('guard reached '+a)
    return next(self.replies)
   def log(self,*args):pass
  c=C();p=ROOT/name;ns={};exec(compile(p.read_text(),str(p),'exec'),ns)
  with self.assertRaisesRegex(ValueError,message):asyncio.run(ns['run'](c,i))
  self.assertEqual(c.calls,['tidb.query']*len(answers))
 def test_second_return_wrong_type_blocks_claim(self):
  i,a=self.fixture();a[0]['rows'][0]['treaty_statement_type']='01';self.stop('12-second-return.py',a[:1],i,'31原AB')
 def test_second_return_wrong_child_blocks_claim(self):
  i,a=self.fixture();a[1]['rows'][1]['former_statement_normal_id']='999';self.stop('12-second-return.py',a[:2],i,'原normal引用')
 def test_second_return_wrong_receiver_stage_blocks_claim(self):
  i,a=self.fixture();a[2]['rows'][1]['statement_status']=4;self.stop('12-second-return.py',a[:3],i,'首次经纪待确认')
 def test_second_return_missing_old_snapshot_blocks_claim(self):
  i,a=self.fixture();self.stop('12-second-return.py',a,i,'快照数量变化')
 def final_fixture(self):
  i,a=self.fixture();states=a[2]
  states['rows'][0]['statement_status']=13;states['rows'][1]['statement_status']=4;i['expected_role_states']=states['rows']
  i.update(old_snapshot_id=60013,old_snapshot_sha256='x'*64,snapshot_id=60014,snapshot_sha256='y'*64)
  return i,a,states
 def test_final_wrong_role_stops_before_browser(self):
  i,a,states=self.final_fixture();i['expected_role_states']=[dict(r) for r in states['rows']];states['rows'][0]['statement_status']=3;self.stop('13-final-snapshot-and-readonly-v2.py',[states],i,'最终AB13/4')
 def test_final_wrong_source_type_stops_before_browser(self):
  i,a,states=self.final_fixture();a[0]['rows'][0]['treaty_statement_type']='01';self.stop('13-final-snapshot-and-readonly-v2.py',[states,a[0]],i,'主表归属变化')
 def test_final_old_snapshot_not_retired_cannot_pass(self):
  i,a,states=self.final_fixture();back=result([dict(id=60013,is_deleted='N',snapshot_sha256='x'*64,frozen_comment=i['v1_comment']),dict(id=60014,is_deleted='N',snapshot_sha256='y'*64,frozen_comment=i['v2_comment'])]);self.stop('13-final-snapshot-and-readonly-v2.py',[states,a[0],a[1],back],i,'旧Y新N')
if __name__=='__main__':unittest.main()
