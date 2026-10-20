"""Offline initial31 submission guards. No authentication/browser/business calls."""
import asyncio,unittest
from pathlib import Path
from verify_guards import result
SOURCE=Path(__file__).parent/'rejection_bill_adjust_steps/04-initial-submit.py'
class GuardTests(unittest.TestCase):
 def fixture(self):
  i=dict(statement_id=544944,bill_label='TW-LOCAL-BILL-ADJ-20261016080007',initial_job_biz_no='000050-2026PT00011-A001',expected_normals=[dict(id=257326,net_balance='1000.00'),dict(id=257327,net_balance='1000.00')],expected_items=[dict(code=c,amount=a) for c,a in [('01','1000.00'),('02','0.00'),('21','0.00'),('60','0.00')]])
  m=result([dict(id=544944,treaty_id=325094,record_no=None,treaty_statement_type='31',former_platform_statement_no='000050-2026PT00011-SOA0001',statement_status=0,comment='仅供本地自测 '+i['bill_label'])])
  n=result([dict(id=257326,parent_id=None,input_org_code='000050',enter_org_code='000053',treaty_reinsurer_id=10925281,former_statement_normal_id='257312',net_balance='1000.00',currency='CNY',platform_statement_no='000050-2026PT00011-A001',cedent_statement_no=i['bill_label']+'-AB'),dict(id=257327,parent_id=257326,input_org_code='000053',enter_org_code='000045',treaty_reinsurer_id=10925282,former_statement_normal_id='257313',net_balance='1000.00',currency='CNY',platform_statement_no='000050-2026PT00011-A002',cedent_statement_no=i['bill_label']+'-BC')])
  items=result([dict(object_id=id,item_code=x['code'],item_amount=x['amount'],version=1) for id in [257326,257327] for x in i['expected_items']]);return i,m,n,items
 def stop(self,answers,i,message):
  class Context:
   def __init__(self):self.calls=[];self.answers=iter(answers)
   async def call(self,a,p):
    self.calls.append(a)
    if a!='tidb.query':raise AssertionError('Guard reached auth or WRITE: '+a)
    return next(self.answers)
  c=Context();ns={};exec(compile(SOURCE.read_text(),str(SOURCE),'exec'),ns)
  with self.assertRaisesRegex(ValueError,message):asyncio.run(ns['run'](c,i))
  self.assertEqual(c.calls,['tidb.query']*len(answers))
 def test_non31_blocks_submission(self):
  i,m,n,items=self.fixture();m['rows'][0]['treaty_statement_type']='01';self.stop([m],i,'31原AB引用')
 def test_already_submitted_blocks_duplicate(self):
  i,m,n,items=self.fixture();m['rows'][0]['statement_status']=3;self.stop([m],i,'已经提交')
 def test_changed_draft_ids_require_recheck(self):
  i,m,n,items=self.fixture();n['rows'][0]['id']=999;self.stop([m,n],i,'明细版本变化')
 def test_wrong_child_original_stops(self):
  i,m,n,items=self.fixture();n['rows'][1]['former_statement_normal_id']='999';self.stop([m,n],i,'父子关系不符')
 def test_existing_initial_job_blocks_before_login(self):
  i,m,n,items=self.fixture();self.stop([m,n,items,result([dict(id=999,status=8)])],i,'初始任务已存在')
 def test_changed_currency_blocks_before_login(self):
  i,m,n,items=self.fixture();n['rows'][0]['currency']='EUR';self.stop([m,n],i,'币种/平台号/机构编号变化')
if __name__=='__main__':unittest.main()
