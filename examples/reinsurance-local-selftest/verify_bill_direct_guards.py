"""Direct bill ownership and prerequisite guards; isolated fake/memory only."""
import asyncio,unittest,ast,importlib.util,sys,json
from pathlib import Path
from verify_guards import DraftContext,result
ROOT=Path(__file__).parent/'rejection_bill_direct_steps'
def execute(name,ctx,inputs):
 ns={};p=ROOT/name;exec(compile(p.read_text(),str(p),'exec'),ns);return asyncio.run(ns['run'](ctx,inputs))
class DirectGuards(unittest.TestCase):
 def test_foreign_draft_never_edited(self):
  ctx=DraftContext([(10,'T-SOAP1',0,'仅供本地自测 OLD','000050',1,1,1,'N')])
  try:
   with self.assertRaisesRegex(ValueError,'其他轮次草稿'):execute('02-create.py',ctx,dict(treaty_master_id=1,bill_label='NEW',expected_unsaved_draft_id=10))
   self.assertEqual(ctx.business_calls,[])
  finally:ctx.db.close()
 def test_unmarked_draft_blocks_new_creation(self):
  ctx=DraftContext([(10,'T-SOAP1',0,None,'000050',1,1,1,'N')])
  try:
   with self.assertRaisesRegex(ValueError,'未标识草稿'):execute('02-create.py',ctx,dict(treaty_master_id=1,bill_label='NEW',expected_unsaved_draft_id=None))
   self.assertEqual(ctx.business_calls,[])
  finally:ctx.db.close()
 def check_save(self,mutation):
  row=dict(id=10,treaty_id=317093,record_no='OWN',statement_status=0,comment=None);row.update(mutation)
  class Context:
   calls=[]
   async def call(self,action,args):
    self.calls.append(action)
    if action!='tidb.query':raise AssertionError('Guard reached UI '+action)
    return result([row])
  ctx=Context()
  with self.assertRaisesRegex(ValueError,'归属或草稿阶段不符'):execute('03-items-save.py',ctx,dict(statement_id=10,treaty_master_id=317093,record_no='OWN',bill_label='NEW'))
  self.assertEqual(ctx.calls,['tidb.query'])
 def test_wrong_base_blocks_save(self):self.check_save({'treaty_id':325094})
 def test_other_record_blocks_save(self):self.check_save({'record_no':'OTHER'})
 def test_completed_bill_blocks_save(self):self.check_save({'statement_status':8})
 def test_other_marker_blocks_save(self):self.check_save({'comment':'仅供本地自测 OLD'})
class DirectPrerequisite(unittest.TestCase):
 def probe(self,rows):
  s=(ROOT/'01-prerequisite.py').read_text();start=s.index('    handoff=');end=s.index('    now=');ns={};exec('async def probe(ctx,inputs):\n'+s[start:end]+'    return rows\n',ns)
  class Context:
   async def call(self,action,args):
    if action=='file.read':return {'content':dict(readOnly=True,verdict='USABLE_AS_EXISTING_LOCAL_BILL_FIXTURE_WITH_EXPLICIT_LIMITATIONS',master=dict(id=317093,cedent_treaty_no='T',org_business_code='BACKUPDATA-20261015-BILL-BASE'),limitations=['synthetic'])}
    if action!='tidb.query':raise AssertionError('Prerequisite reached business '+action)
    return result([dict(id=317093,cedent_treaty_no='T',org_business_code='BACKUPDATA-20261015-BILL-BASE',status='8')]) if 'ri_treaty_master' in args['sql'] else result(rows)
  return asyncio.run(ns['probe'](Context(),{'completed_treaty_path':'fixture-only'}))
 def rows(self):return [dict(id=11,org_code='000050',reinsurance_role='01',from_id=None,status='8',file_status=None),dict(id=12,org_code='000045',reinsurance_role='02',from_id=11,status='8',file_status='2')]
 def test_completed_direct_base_accepted(self):self.assertEqual(len(self.probe(self.rows())),2)
 def test_three_party_base_rejected(self):
  rows=self.rows();rows.insert(1,dict(id=13,org_code='000053',reinsurance_role='03',from_id=11,status='8',file_status='2'))
  with self.assertRaisesRegex(ValueError,'必须直连'):self.probe(rows)
 def test_unconfirmed_file_blocks_prerequisite(self):
  rows=self.rows();rows[1]['file_status']='1'
  with self.assertRaisesRegex(ValueError,'尚未确认'):self.probe(rows)
 def test_rejected_treaty_blocks_prerequisite(self):
  rows=self.rows();rows[1]['status']='4'
  with self.assertRaisesRegex(ValueError,'尚未完成'):self.probe(rows)
 def test_wrong_direct_parent_rejected(self):
  rows=self.rows();rows[1]['from_id']=13
  with self.assertRaisesRegex(ValueError,'上下游不符'):self.probe(rows)
class CalendarMotionRegression(unittest.TestCase):
 def probe(self,legacy=False):
  s=(ROOT/'02-create.py').read_text();start=s.index('    async def choose_date(');end=s.index('    await ctx.call("playwright.page_click",{"selector":"#statementDate"',start);segment=s[start:end]
  if legacy:
   segment='\n'.join(line for line in segment.splitlines() if not any(t in line for t in ('await ctx.call("playwright.page_wait"','popup=await','ctx.log("本笔日历稳定浮层=')))
  ns={};exec('async def probe(ctx):\n    role="cedant"\n'+segment+'\n    await choose_date("2026-10-16")\n',ns)
  class Context:
   stable=False
   clicked=False
   def log(self,message):pass
   async def call(self,action,args):
    if action=='playwright.page_wait':self.stable=True
    if action=='playwright.page_attribute':return {'value':'ant-picker-dropdown'}
    if action=='playwright.page_state':return dict(match_count=1,visible=self.stable)
    if action=='playwright.page_list':return dict(total_count=2,items=[dict(text=t) for t in (['2026年','2026年'] if 'year-btn' in args['selector'] else ['10月','11月'])])
    if action=='playwright.page_click':
     if not self.stable:raise RuntimeError('LOCATOR_HIDDEN during motion')
     self.clicked=True
    return {}
  ctx=Context();asyncio.run(ns['probe'](ctx));return ctx
 def test_old_cell_only_visible_assert_can_race_motion(self):
  with self.assertRaisesRegex(RuntimeError,'LOCATOR_HIDDEN'):self.probe(True)
 def test_popup_motion_completion_precedes_date_click(self):self.assertTrue(self.probe().clicked)
class DirectPendingGuards(unittest.TestCase):
 def fixture(self):
  i=dict(statement_id=544943,record_no='T-SOAP3',bill_label='OWN',v1_comment='V1',platform_treaty_no='T',normal_id=10,expected_biz_id='BIZ',initial_parent_id=100,initial_detail_id=101)
  m=result([dict(id=544943,treaty_id=317093,record_no='T-SOAP3',comment='V1')]);n=result([dict(id=10,statement_id=544943,input_org_code='000050',enter_org_code='000045',parent_id=None,treaty_reinsurer_id=10947283,currency='CNY',net_balance='14000.00',platform_statement_no='T-SOA3',cedent_statement_no='OWN-TOTAL',biz_id='BIZ',reviewer=None,review_level=None,business_comment='V1')])
  st=result([dict(statement_normal_id=10,org_code='000045',reinsurance_role='02',statement_status=3),dict(statement_normal_id=10,org_code='000050',reinsurance_role='01',statement_status=3)])
  job=result([dict(parent_id=100,parent_group=544943,parent_status=8,detail_id=101,detail_group=544943,detail_status=8,biz_no='T-SOA3',onchain_business_id=10,biz_id='BIZ',callback_result='成功',onchain_times=1)])
  return i,m,n,st,job
 def stop(self,replies,i,message):
  class Context:
   def __init__(self):self.replies=iter(replies);self.calls=[]
   async def call(self,action,args):
    self.calls.append(action)
    if action!='tidb.query':raise AssertionError('guard reached auth/claim/UI '+action)
    return next(self.replies)
  ctx=Context()
  with self.assertRaisesRegex(ValueError,message):execute('05-reinsurer-pending.py',ctx,i)
  self.assertEqual(ctx.calls,['tidb.query']*len(replies))
 def test_no_broker_or_wrong_parent_before_claim(self):
  i,m,n,st,j=self.fixture();n['rows'][0]['parent_id']=9
  self.stop([m,n],i,'normal树或活动ID')
 def test_old100percent_balance_rejected(self):
  i,m,n,st,j=self.fixture();n['rows'][0]['net_balance']='70000.00'
  self.stop([m,n],i,'金额或币种')
 def test_rejected_state_never_reclaimed_as_first_pending(self):
  i,m,n,st,j=self.fixture();st['rows'][0]['statement_status']=4
  self.stop([m,n,st],i,'未处于首次直连再保')
 def test_existing_snapshot_never_replayed_as_initial(self):
  i,m,n,st,j=self.fixture();self.stop([m,n,st,result([dict(id=1,is_deleted='N')])],i,'已存在退回快照')
 def test_wrong_initial_job_detail_blocks_claim(self):
  i,m,n,st,j=self.fixture();j['rows'][0]['onchain_business_id']=20
  self.stop([m,n,st,result([]),j],i,'初始直连任务归属')
class DirectInitialGuards(unittest.TestCase):
 def test_already_submitted_master_blocks_every_business_call(self):
  class Context:
   calls=[]
   async def call(self,action,args):
    self.calls.append(action)
    if action!='tidb.query':raise AssertionError(action)
    return result([dict(id=544943,treaty_id=317093,record_no='T-SOAP3',statement_status=3,comment='仅供本地自测 OWN')])
  ctx=Context()
  with self.assertRaisesRegex(ValueError,'禁止重复提交'):execute('04-initial-submit.py',ctx,dict(statement_id=544943,bill_label='OWN',platform_treaty_no='T'))
  self.assertEqual(ctx.calls,['tidb.query'])
class ActualHelperContracts(unittest.TestCase):
 def test_actual_wait_and_claim_arguments_parse(self):
  for filename,expect in [('04-initial-submit.py','wait'),('05-reinsurer-pending.py','claim')]:
   tree=ast.parse((ROOT/filename).read_text());calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='call' and n.args and isinstance(n.args[0],ast.Constant) and n.args[0].value=='process.run'];self.assertEqual(len(calls),1)
   node=next(v for k,v in zip(calls[0].args[1].keys,calls[0].args[1].values) if k.value=='args');args=eval(compile(ast.Expression(node),'<actual-helper-args>','eval'),{'str':str,'inputs':{'normal_id':257322}})
   helper=Path(args[0]);sys.path.insert(0,str(helper.parent))
   try:
    spec=importlib.util.spec_from_file_location('direct_'+expect,helper);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);a=m.parse_args(args[1:])
    if expect=='wait':self.assertEqual((a.phase,a.before_job),('initial',0))
    else:self.assertEqual((a.actor,a.normal_id,a.expected_status,a.expected_level,a.claim),('000045',257322,3,'none',True))
   finally:sys.path.pop(0)
class DirectReturnGuards(unittest.TestCase):
 def stop(self,file,replies,i,message):
  class Context:
   def __init__(self):self.replies=iter(replies);self.calls=[]
   async def call(self,action,args):
    self.calls.append(action)
    if action!='tidb.query':raise AssertionError('guard reached business '+action)
    return next(self.replies)
  ctx=Context()
  with self.assertRaisesRegex(ValueError,message):execute(file,ctx,i)
  self.assertEqual(ctx.calls,['tidb.query']*len(replies))
 def fixture(self):
  i,m,n,st,j=DirectPendingGuards().fixture();i.update(snapshot_id=90,snapshot_sha256='a'*64,ab_platform_no='T-SOA3',v2_comment='V1 V2')
  f=result([dict(id=90,is_deleted='N',snapshot_sha256='a'*64,frozen_comment='V1',back_up_data='V1-json')]);return i,m,n,st,j,f
 def test_unclaimed_first_reject_never_reaches_ui(self):
  i,m,n,st,j,f=self.fixture();self.stop('06-first-reinsurer-return.py',[m,n,st,result([]),j],i,'尚未由')
 def test_saved_v2_rejects_normal_save_replay(self):
  i,m,n,st,j,f=self.fixture();n['rows'][0]['business_comment']='V1 V2'
  for r,v in zip(st['rows'],[4,13]):r['statement_status']=v
  self.stop('08-modify-comment-and-verify-v1.py',[st,f,m,n],i,'实际业务备注版本不符')
 def test_readonly_recovery_unowned_never_claims(self):
  i,m,n,st,j,f=self.fixture();i['verify_saved_only']=True;n['rows'][0]['business_comment']='V1 V2'
  for r,v in zip(st['rows'],[4,13]):r['statement_status']=v
  self.stop('08-modify-comment-and-verify-v1.py',[st,f,m,n],i,'只读恢复不领取')
 def test_saved_old_snapshot_hash_change_blocks_edit(self):
  i,m,n,st,j,f=self.fixture();f['rows'][0]['snapshot_sha256']='b'*64
  for r,v in zip(st['rows'],[4,13]):r['statement_status']=v
  self.stop('08-modify-comment-and-verify-v1.py',[st,f],i,'V1快照已变化')
 def test_sync_resubmit_already_sent_never_repeats(self):
  i,m,n,st,j,f=self.fixture();self.stop('10-synchronous-resubmit.py',[st],i,'未处于退回待修改')
 def test_sync_resubmit_requires_live_v2(self):
  i,m,n,st,j,f=self.fixture()
  for r,v in zip(st['rows'],[4,13]):r['statement_status']=v
  self.stop('10-synchronous-resubmit.py',[st,f,m,n],i,'实际业务备注版本不符')
 def test_second_reject_existing_two_snapshots_stops_before_claim(self):
  i,m,n,st,j,f=self.fixture();n['rows'][0]['business_comment']='V1 V2'
  self.stop('12-second-return.py',[m,n,st,result(f['rows']+[dict(id=91)])],i,'已二次退回或快照数量变化')
 def test_second_reject_live_v1_stops_before_claim(self):
  i,m,n,st,j,f=self.fixture();self.stop('12-second-return.py',[m,n],i,'实际V1备注不符')
class OwnInitialJobBindingRegression(unittest.TestCase):
 def test_sync_resubmit_uses_this_task_initial_output(self):
  d=next(x for x in json.loads((ROOT/'definitions.json').read_text()) if x['step_number']==10)
  for key in ('parent_id','detail_id'):
   name='initial_'+key;p=d['input_schema']['properties'][name]
   self.assertEqual(p,{'type':'integer','minimum':1});self.assertEqual(d['bindings'][name],{'ref':{'source':'step','step_id':'step-4','output':'data','pointer':'/initial_core_mock_job/'+key}})
if __name__=='__main__':unittest.main()
