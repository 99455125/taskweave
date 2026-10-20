"""Adjustment prerequisites: fake SELECT only; no live business calls."""
import asyncio,unittest
from pathlib import Path
from verify_guards import result
ROOT=Path(__file__).parent/'rejection_bill_adjust_steps'
def execute(ctx,i):
 ns={};p=ROOT/'01-prerequisite-and-source-row.py';exec(compile(p.read_text(),str(p),'exec'),ns);return asyncio.run(ns['run'](ctx,i))
class GuardTests(unittest.TestCase):
 def fixture(self):
  i=dict(source_statement_id=544940,source_normal_id=257312,source_platform_no='000050-2026PT00011-SOA0001')
  m=result([dict(id=544940,treaty_id=325094,record_no='000050-2026PT00011-SOAP0001',statement_status=6,comment='OWN')]);n=result([dict(id=257312,statement_id=544940,input_org_code='000050',enter_org_code='000053',parent_id=None,treaty_reinsurer_id=10925281,currency='CNY',net_balance='70000.00',platform_statement_no=i['source_platform_no'],sign_file_id='owned-test-file',settlement_status='6',extra_info='{}')]);st=result([dict(org_code='000050',reinsurance_role='01',statement_status=8),dict(org_code='000053',reinsurance_role='02',statement_status=8)]);return i,m,n,st
 def stop(self,replies,i,message):
  class Context:
   def __init__(self):self.calls=[];self.replies=iter(replies)
   async def call(self,action,args):
    self.calls.append(action)
    if action!='tidb.query':raise AssertionError('guard reached auth/UI '+action)
    return next(self.replies)
  c=Context()
  with self.assertRaisesRegex(ValueError,message):execute(c,i)
  self.assertEqual(c.calls,['tidb.query']*len(replies))
 def test_other_master_rejected(self):
  i,m,n,st=self.fixture();m['rows'][0]['treaty_id']=317093;self.stop([m],i,'主表或合约归属')
 def test_wrong_normal_relationship_rejected(self):
  i,m,n,st=self.fixture();n['rows'][0]['enter_org_code']='000045';self.stop([m,n],i,'原AB机构')
 def test_unsigned_original_rejected(self):
  i,m,n,st=self.fixture();n['rows'][0]['sign_file_id']='';self.stop([m,n],i,'尚未生成文件')
 def test_incomplete_role_blocks_ui(self):
  i,m,n,st=self.fixture();st['rows'][0]['statement_status']=6;self.stop([m,n,st],i,'角色尚未完成')
 def test_existing_correction_blocks_new_attempt(self):
  i,m,n,st=self.fixture();self.stop([m,n,st,result([dict(id=100)])],i,'已有修正记录')

class LateMountTests(unittest.TestCase):
 fixture=GuardTests.fixture
 def test_late_advanced_control_is_awaited_and_source_is_readonly(self):
  i,m,n,st=self.fixture();i.update(name_prefix='TW-LOCAL-BILL-ADJ-',credentials_path='credentials.json')
  class Context:
   def __init__(self):self.calls=[];self.answers=iter([m,n,st,result([]),result([])])
   async def call(self,a,p):
    self.calls.append((a,p))
    if a=='tidb.query':return next(self.answers)
    if a=='utility.now':return {'compact':'20261016080000'}
    if a=='file.read':return {'content':{'ui':{'url':'http://localhost:9877/login','accounts':{'cedent':'000050'},'sharedPassword':'FAKE'}}}
    if a=='playwright.page_inspect':return {'url':'http://localhost:9877/Home'}
    if a=='playwright.page_state':return {'match_count':0,'visible':False}
    if a=='playwright.page_text':return {'text':'000050-2026PT00011-SOA0001 修正'}
    if a.startswith('playwright.'):return {}
    raise AssertionError(a)
   def result(self,**kw):return kw
  c=Context();out=execute(c,i)['data'];self.assertFalse(out['new_adjust_created']);self.assertTrue(out['adjust_entry_observed'])
  advanced=".bill-search-box a:has-text('高级查询')"
  waiting=next(k for k,(a,p) in enumerate(c.calls) if a=='playwright.page_assert_state' and p['selector']==advanced)
  clicking=next(k for k,(a,p) in enumerate(c.calls) if a=='playwright.page_click' and p['selector']==advanced)
  self.assertLess(waiting,clicking)
  self.assertFalse(any(a=='playwright.page_click' and isinstance(p['selector'],dict) and p['selector'].get('name')=='修正' for a,p in c.calls))
  self.assertTrue(all(p['sql'].startswith('SELECT ') for a,p in c.calls if a=='tidb.query'))



class CreationGuardTests(unittest.TestCase):
 def fixture(self):
  i=dict(source_statement_id=544940,source_normal_id=257312,source_platform_no='000050-2026PT00011-SOA0001',bill_label='TW-LOCAL-BILL-ADJ-TEST')
  source=result([dict(id=257312,statement_id=544940,input_org_code='000050',enter_org_code='000053',parent_id=None,platform_statement_no=i['source_platform_no'],sign_file_id='FAKE')])
  states=result([dict(org_code='000050',reinsurance_role='01',statement_status=8),dict(org_code='000053',reinsurance_role='02',statement_status=8)])
  master=result([dict(id=900,treaty_id=325094,record_no='NEW-ADJ',treaty_statement_type='31',former_treaty_statement_type='01',statement_status=0)])
  rows=[]
  for id,frm,to,parent,party,old,no in [(901,'000050','000053',None,10925281,257312,i['source_platform_no']),(902,'000053','000045',901,10925282,257313,'000050-2026PT00011-SOA0002')]:
   rows.append(dict(id=id,input_org_code=frm,enter_org_code=to,parent_id=parent,treaty_reinsurer_id=party,former_statement_normal_id=old,former_platform_statement_no=no,**{k:None for k in ['biz_id','parent_biz_id','sign_biz_id','sign_file_id','settlement_id','settlement_status']}))
  return i,[source,result([]),states,master,result(rows)]
 def context(self,answers):
  class Context:
   def __init__(self):self.calls=[];self.answers=iter(answers)
   async def call(self,a,p):
    self.calls.append((a,p))
    if a=='tidb.query':return next(self.answers)
    if a=='playwright.page_inspect':return {'url':'http://localhost:9877/ContractBill/list/adjustBill_add?id=900&treatyCode=T&operation=add'}
    if a.startswith('playwright.'):return {}
    raise AssertionError(a)
   def result(self,**kw):return kw
  return Context()
 def execute(self,c,i):
  p=ROOT/'02-create-from-source.py';ns={};exec(compile(p.read_text(),str(p),'exec'),ns);return asyncio.run(ns['run'](c,i))
 def test_existing_adjustment_blocks_click(self):
  i,answers=self.fixture();answers[1]=result([dict(id=900)])
  c=self.context(answers)
  with self.assertRaisesRegex(ValueError,'已有修正单'):self.execute(c,i)
  self.assertEqual([a for a,p in c.calls],['tidb.query']*2)
 def test_source_state_change_blocks_click(self):
  i,answers=self.fixture();answers[2]['rows'][0]['statement_status']=13;c=self.context(answers)
  with self.assertRaisesRegex(ValueError,'角色已变化'):self.execute(c,i)
  self.assertEqual([a for a,p in c.calls],['tidb.query']*3)
 def test_creation_clicks_exactly_once_and_checks_both_original_links(self):
  i,answers=self.fixture();c=self.context(answers);out=self.execute(c,i)['data']
  clicks=[p for a,p in c.calls if a=='playwright.page_click'];self.assertEqual(len(clicks),1);self.assertEqual(clicks[0]['selector']['name'],'修正')
  self.assertEqual(out['source_id'],901);self.assertFalse(out['new_adjust_submitted'])
  self.assertTrue(all(p['sql'].startswith('SELECT ') for a,p in c.calls if a=='tidb.query'))
 def test_wrong_child_link_stops_after_one_create_without_retry(self):
  i,answers=self.fixture();answers[-1]['rows'][1]['former_statement_normal_id']=999;c=self.context(answers)
  with self.assertRaisesRegex(ValueError,'原AB/BC引用不符'):self.execute(c,i)
  self.assertEqual(sum(a=='playwright.page_click' for a,p in c.calls),1)

 def test_real_varchar_original_ids_are_checked_exactly(self):
  i,answers=self.fixture()
  for row in answers[-1]['rows']:row['former_statement_normal_id']=str(row['former_statement_normal_id'])
  c=self.context(answers);self.assertTrue(self.execute(c,i)['data']['new_adjust_created'])
 def test_owned_readonly_recovery_never_clicks_create(self):
  i,answers=self.fixture();i.update(verify_only=True,expected_created_draft_id=544944)
  answers[1]=result([dict(id=544944)]);answers[3]['rows'][0]['id']=544944
  c=self.context(answers);out=self.execute(c,i)['data'];self.assertTrue(out['existing_created_draft_verified']);self.assertFalse(out['new_adjust_created'])
  self.assertFalse(any(a=='playwright.page_click' for a,p in c.calls))
 def test_readonly_missing_draft_stops_before_browser(self):
  i,answers=self.fixture();i.update(verify_only=True,expected_created_draft_id=544944);c=self.context(answers)
  with self.assertRaisesRegex(ValueError,'只读恢复'):self.execute(c,i)
  self.assertTrue(all(a=='tidb.query' for a,p in c.calls))



class SaveGuardTests(unittest.TestCase):
 def fixture(self):
  i=dict(statement_id=544944,v1_comment='OWN V1')
  m=result([dict(id=544944,treaty_id=325094,treaty_statement_type='31',former_platform_statement_no='000050-2026PT00011-SOA0001',statement_status=0,comment='仅供本地自测 TW-LOCAL-BILL-20261016025047')])
  n=result([dict(id=901,input_org_code='000050',enter_org_code='000053',former_statement_normal_id='257312',parent_id=None),dict(id=902,input_org_code='000053',enter_org_code='000045',former_statement_normal_id='257313',parent_id=901)])
  return i,m,n
 def stop(self,answers,i,message):
  class Context:
   def __init__(self):self.answers=iter(answers);self.calls=[]
   async def call(self,a,p):
    self.calls.append(a)
    if a!='tidb.query':raise AssertionError('unsafe guard reachedUI '+a)
    return next(self.answers)
  c=Context();p=ROOT/'03-items-save.py';ns={};exec(compile(p.read_text(),str(p),'exec'),ns)
  with self.assertRaisesRegex(ValueError,message):asyncio.run(ns['run'](c,i))
  self.assertEqual(c.calls,['tidb.query']*len(answers))
 def test_other_adjustment_blocks_save(self):
  i,m,n=self.fixture();m['rows'][0]['id']=900;self.stop([m],i,'原单归属')
 def test_foreign_comment_blocks_overwrite(self):
  i,m,n=self.fixture();m['rows'][0]['comment']='OTHER';self.stop([m],i,'其他业务备注')
 def test_wrong_original_child_blocks_edit(self):
  i,m,n=self.fixture();n['rows'][1]['former_statement_normal_id']='999';self.stop([m,n],i,r'AB\+BC引用')
 def test_wrong_parent_blocks_edit(self):
  i,m,n=self.fixture();n['rows'][1]['parent_id']=999;self.stop([m,n],i,'父子关系')

if __name__=='__main__':unittest.main()
