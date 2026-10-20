"""Independent billBR guards: isolated memory/fake reads, no UI or business calls."""
import asyncio,unittest,ast,importlib.util,sys
from pathlib import Path
from verify_guards import DraftContext,result
import verify_bill_cb_guards as cb
ROOT=Path(__file__).parent/'rejection_bill_reinsurer_broker_steps'
def execute(name,ctx,inputs):
    p=ROOT/name;ns={};exec(compile(p.read_text(),str(p),'exec'),ns)
    return asyncio.run(ns['run'](ctx,inputs))
class ReadContext:
    def __init__(self,row):self.row=row;self.calls=[]
    async def call(self,action,args):
        self.calls.append(action)
        if action!='tidb.query':raise AssertionError('Guard reached UI action '+action)
        return result([self.row])
class Guards(unittest.TestCase):
    def test_other_marked_draft_not_taken_over(self):
        ctx=DraftContext([(10,'T-SOAP1',0,'仅供本地自测 OLD','000050',1,1,1,'N')])
        try:
            with self.assertRaisesRegex(ValueError,'其他轮次草稿'):execute('02-create.py',ctx,dict(treaty_master_id=1,bill_label='NEW',expected_unsaved_draft_id=10))
            self.assertEqual(ctx.business_calls,[])
        finally:ctx.db.close()
    def test_unmarked_draft_prevents_new_creation(self):
        ctx=DraftContext([(10,'T-SOAP1',0,None,'000050',1,1,1,'N')])
        try:
            with self.assertRaisesRegex(ValueError,'未标识草稿'):execute('02-create.py',ctx,dict(treaty_master_id=1,bill_label='NEW',expected_unsaved_draft_id=None))
            self.assertEqual(ctx.business_calls,[])
        finally:ctx.db.close()
    def assert_save_guard(self,mutation):
        row=dict(id=10,treaty_id=1,record_no='OWN',statement_status=0,comment=None);row.update(mutation);ctx=ReadContext(row)
        with self.assertRaisesRegex(ValueError,'归属或草稿阶段不符'):execute('03-items-save.py',ctx,dict(statement_id=10,treaty_master_id=1,record_no='OWN',bill_label='NEW'))
        self.assertEqual(ctx.calls,['tidb.query'])
    def test_completed_bill_rejected_before_edit(self):self.assert_save_guard({'statement_status':6})
    def test_other_record_rejected_before_edit(self):self.assert_save_guard({'record_no':'OTHER'})
    def test_other_marker_rejected_before_edit(self):self.assert_save_guard({'comment':'仅供本地自测 OLD'})
class InitialSubmitGuards(unittest.TestCase):
    def test_initial_submit_stops_if_already_submitted(self):
        ctx=ReadContext(dict(id=100,record_no='T-SOAP0003',statement_status=3,comment='仅供本地自测 NEW'))
        with self.assertRaisesRegex(ValueError,'禁止重复提交'):execute('04-initial-submit.py',ctx,dict(statement_id=100,platform_treaty_no='T',bill_label='NEW',expected_record_no='T-SOAP0003'))
        self.assertEqual(ctx.calls,['tidb.query'])
    def test_real_initial_wait_parser(self):
        tree=ast.parse((ROOT/'04-initial-submit.py').read_text());calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='call' and n.args and isinstance(n.args[0],ast.Constant) and n.args[0].value=='process.run']
        self.assertEqual(len(calls),1)
        node=next(v for k,v in zip(calls[0].args[1].keys,calls[0].args[1].values) if k.value=='args');args=eval(compile(ast.Expression(node),'<actual-wait-args>','eval'),{'inputs':{'initial_wait_args':['--phase','initial-ab','--before-job','0']}})
        helper=Path(args[0]);sys.path.insert(0,str(helper.parent))
        try:
            spec=importlib.util.spec_from_file_location('checked_bill_br_initial_wait',helper);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
            parsed=m.parse_args(args[1:]);self.assertEqual((parsed.phase,parsed.before_job),('initial-ab',0))
        finally:sys.path.pop(0)
class PendingGuards(unittest.TestCase):
    def data(self):
        inputs,m,t,states=cb.Guards().pending_data();t['rows'][0]['review_level']=None
        return inputs,m,t,states
    def stop(self,replies,inputs,message):
        class Context:
            def __init__(self):self.calls=[];self.replies=iter(replies)
            async def call(self,action,args):
                self.calls.append(action)
                if action!='tidb.query':raise AssertionError('guard reached claim or UI '+action)
                return next(self.replies)
        ctx=Context()
        with self.assertRaisesRegex(ValueError,message):execute('05-broker-pending-inspect.py',ctx,inputs)
        self.assertEqual(ctx.calls,['tidb.query']*len(replies))
    def test_first_pending_existing_audit_level_stops(self):
        i,m,t,st=self.data();t['rows'][0]['review_level']=1
        self.stop([m,t,st],i,'不应已有审核级次')
    def test_existing_either_segment_snapshot_stops(self):
        i,m,t,st=self.data()
        self.stop([m,t,st,result([dict(id=60001)])],i,'已存在退回快照')
    def test_claim_real_parser_requires_explicit_none_level(self):
        tree=ast.parse((ROOT/'05-broker-pending-inspect.py').read_text());calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='call' and n.args and isinstance(n.args[0],ast.Constant) and n.args[0].value=='process.run']
        self.assertEqual(len(calls),1)
        node=next(v for k,v in zip(calls[0].args[1].keys,calls[0].args[1].values) if k.value=='args');args=eval(compile(ast.Expression(node),'<actual-claim-args>','eval'),{'str':str,'inputs':{'normal_id':11}})
        helper=Path(args[0]);sys.path.insert(0,str(helper.parent))
        try:
            spec=importlib.util.spec_from_file_location('checked_bill_br_claim',helper);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
            parsed=m.parse_args(args[1:]);self.assertEqual((parsed.actor,parsed.normal_id,parsed.expected_status,parsed.expected_level,parsed.claim),('000053',11,3,None,True))
        finally:sys.path.pop(0)
class FirstConfirmGuards(unittest.TestCase):
    def test_unclaimed_pending_stops_before_new_row(self):
        i,m,t,st=cb.Guards().pending_data();t['rows'][0]['review_level']=None
        replies=iter([m,t,st,result([])])
        class Context:
            def __init__(self):self.calls=[]
            async def call(self,action,args):
                self.calls.append(action)
                if action!='tidb.query':raise AssertionError(action)
                return next(replies)
        ctx=Context()
        with self.assertRaisesRegex(ValueError,'尚未领取'):execute('06-broker-custom-v1-and-first-confirm.py',ctx,i)
        self.assertEqual(ctx.calls,['tidb.query']*4)
class SubjectRegression(unittest.TestCase):
    def select_segment(self,remove_search=False):
        text=(ROOT/'06-broker-custom-v1-and-first-confirm.py').read_text();start=text.index('    await ctx.call("playwright.page_click",{"selector":new_subject');end=text.index('    comment=row+',start);segment=text[start:end]
        if remove_search:segment='\n'.join(line for line in segment.splitlines() if '"playwright.page_fill"' not in line)
        ns={};exec('async def probe(ctx):\n    new_subject="editable-subject"\n'+segment,ns)
        class Context:
            def __init__(self):self.filtered=False;self.selected=None
            async def call(self,action,args):
                if action=='playwright.page_fill':self.filtered=True
                if action=='playwright.page_list':return dict(items=[dict(text=t) for t in (['其他（借）','其他（贷）'] if self.filtered else ['保费','赔款'])],truncated=False)
                if action=='playwright.page_click' and 'has-text' in args['selector']:self.selected=args['selector']
                return {}
        ctx=Context();asyncio.run(ns['probe'](ctx));return ctx
    def test_old_unfiltered_virtual_dom_has_no_target(self):
        with self.assertRaisesRegex(ValueError,'实际其他贷方科目不唯一'):self.select_segment(True)
    def test_new_filtered_dom_selects_unique_other_credit(self):
        self.assertIn('其他（贷）',self.select_segment().selected)
    def baseline(self,mutation=None):
        text=(ROOT/'06-broker-custom-v1-and-first-confirm.py').read_text();start=text.index('    original=[x for x in saved[');end=text.index('    balances=await query(',start);ns={};exec('def probe(saved,items):\n'+text[start:end],ns)
        row=dict(id=1,object_id=11,item_code='01',item_amount='100000.00',item_comment=None,version=1);changed=dict(row);changed.update(mutation or {})
        return ns['probe']({'rows':[changed]},{'rows':[row]})
    def test_full_baseline_unchanged(self):self.baseline()
    def test_recreated_original_row_is_detected(self):
        with self.assertRaisesRegex(ValueError,'完整基线变化'):self.baseline({'id':2})
    def test_changed_original_comment_is_detected(self):
        with self.assertRaisesRegex(ValueError,'完整基线变化'):self.baseline({'item_comment':'changed'})
class AuditGuards(unittest.TestCase):
    def fixture(self):
        i,m,t,st=cb.Guards().pending_data();i.update(expected_level=1,custom_item_id=999,v1_item_comment='OWN-V1');t['rows'][0]['review_level']=1;st['rows'][1]['statement_status']=1
        rows=[dict(id=n*10+k,object_id=n,item_code=c,item_amount=a,item_comment=None,version=1) for n in [11,12] for k,(c,a) in enumerate([('01','100000.00'),('02','20000.00'),('21','10000.00'),('60','0.00')])]+[dict(id=999,object_id=12,item_code='98',item_amount='0.00',item_comment='OWN-V1',version=2)]
        return i,m,t,st,result(rows)
    def stop(self,replies,inputs,message):
        class Context:
            def __init__(self):self.calls=[];self.replies=iter(replies)
            async def call(self,action,args):
                self.calls.append(action)
                if action!='tidb.query':raise AssertionError('guard reached auth/claim/UI '+action)
                return next(self.replies)
        ctx=Context()
        with self.assertRaisesRegex(ValueError,message):execute('07-broker-initial-audit.py',ctx,inputs)
        self.assertEqual(ctx.calls,['tidb.query']*len(replies))
    def test_already_finalized_stops_before_claim(self):
        i,m,t,st,items=self.fixture();st['rows'][1]['statement_status']=5
        self.stop([m,t,st],i,'不在约定经纪审核阶段')
    def test_wrong_level_stops_before_claim(self):
        i,m,t,st,items=self.fixture();t['rows'][0]['review_level']=2
        self.stop([m,t,st],i,'审核级次或领取人不符')
    def test_existing_first_bc_job_stops_before_claim(self):
        i,m,t,st,items=self.fixture()
        self.stop([m,t,st,items,result([dict(id=900)])],i,'首次任务已存在')
    def test_foreign_custom_id_stops_before_claim(self):
        i,m,t,st,items=self.fixture();i['custom_item_id']=998
        self.stop([m,t,st,items],i,'自有科目ID/归属')
    def test_actual_audit_claim_parser_for_both_levels(self):
        root=ast.parse((ROOT/'07-broker-initial-audit.py').read_text());calls=[n for n in ast.walk(root) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='call' and n.args and isinstance(n.args[0],ast.Constant) and n.args[0].value=='process.run'];self.assertEqual(len(calls),2)
        node=next(v for k,v in zip(calls[0].args[1].keys,calls[0].args[1].values) if k.value=='args')
        helper=Path(node.elts[0].value);sys.path.insert(0,str(helper.parent))
        try:
            spec=importlib.util.spec_from_file_location('checked_broker_audit_claim',helper);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
            for level in [1,2]:
                args=eval(compile(ast.Expression(node),'<real-audit-args>','eval'),{'str':str,'inputs':{'normal_id':11,'expected_level':level}});parsed=m.parse_args(args[1:]);self.assertEqual((parsed.actor,parsed.expected_status,parsed.expected_level,parsed.claim),('000053',1,level,True))
        finally:sys.path.pop(0)
class ReinsurerGuards(unittest.TestCase):
    def fixture(self):
        i,m,t,st=cb.Guards().pending_data();i.update(expected_bc_biz_id='BC',custom_item_id=999,v1_item_comment='OWN-V1',initial_bc_parent_id=900,initial_bc_detail_id=901);t['rows'][0]['review_level']=None;t['rows'][1].update(biz_id='BC',parent_biz_id='OWN',review_level=None,reviewer=None,platform_statement_no='T-SOA2')
        for row,v in zip(st['rows'],[3,5,3,3]):row['statement_status']=v
        custom=result([dict(id=999,object_id=12,item_code='98',item_amount='0.00',item_comment='OWN-V1',version=2)])
        job=result([dict(parent_id=900,parent_group=11,parent_status=8,detail_id=901,detail_group=12,detail_status=8,biz_no='T-SOA2',onchain_business_id=12,biz_id='BC',callback_result='成功',onchain_times=1)])
        return i,m,t,st,custom,job
    def stop(self,filename,replies,inputs,message):
        class Context:
            def __init__(self):self.calls=[];self.replies=iter(replies)
            async def call(self,action,args):
                self.calls.append(action)
                if action!='tidb.query':raise AssertionError('guard reached external action '+action)
                return next(self.replies)
        ctx=Context()
        with self.assertRaisesRegex(ValueError,message):execute(filename,ctx,inputs)
        self.assertEqual(ctx.calls,['tidb.query']*len(replies))
    def test_foreign_bc_biz_stops_before_claim(self):
        i,m,t,st,c,j=self.fixture();t['rows'][1]['biz_id']='OTHER'
        self.stop('09-reinsurer-pending.py',[m,t],i,'BC业务或上游biz')
    def test_wrong_first_reinsurer_phase_stops(self):
        i,m,t,st,c,j=self.fixture();st['rows'][2]['statement_status']=4
        self.stop('09-reinsurer-pending.py',[m,t,st],i,'未处于首次再保待确认')
    def test_wrong_initial_bc_job_stops_before_claim(self):
        i,m,t,st,c,j=self.fixture();j['rows'][0]['detail_group']=11
        self.stop('09-reinsurer-pending.py',[m,t,st,c,j],i,'BC任务身份或终态')
    def test_existing_snapshot_stops_first_reject(self):
        i,m,t,st,c,j=self.fixture();t['rows'][1]['reviewer']='000045'
        self.stop('10-first-reinsurer-return.py',[m,t,st,c,j,result([dict(id=1)])],i,'已存在退回快照')
    def test_unclaimed_reinsurer_stops_before_reject(self):
        i,m,t,st,c,j=self.fixture()
        self.stop('10-first-reinsurer-return.py',[m,t,st,c,j,result([])],i,'尚未领取')
class ModifyGuards(ReinsurerGuards):
    def fixture_modify(self):
        i,m,t,st,c,j=self.fixture();i.update(verify_saved_only=False,snapshot_id=700,snapshot_sha256='a'*64,v2_item_comment=i['bill_label']+'-BROKER-V2')
        for row,v in zip(st['rows'],[3,13,4,4]):row['statement_status']=v
        frozen=result([dict(id=700,source_table=3,source_id=12,is_deleted='N',snapshot_sha256='a'*64,back_up_data='unchanged')])
        items=AuditGuards().fixture()[-1];items['rows'][-1]['item_comment']='OWN-V1'
        return i,m,t,st,frozen,items
    def test_modify_wrong_phase_before_save(self):
        i,m,t,st,f,it=self.fixture_modify();st['rows'][1]['statement_status']=1
        self.stop('12-broker-modify-and-readonly-v1.py',[m,t,st],i,'不在再保退经纪')
    def test_modify_wrong_snapshot_source_before_save(self):
        i,m,t,st,f,it=self.fixture_modify();f['rows'][0]['source_id']=11
        self.stop('12-broker-modify-and-readonly-v1.py',[m,t,st,f],i,'快照身份或SHA变化')
    def test_modify_changed_snapshot_hash_before_save(self):
        i,m,t,st,f,it=self.fixture_modify();f['rows'][0]['snapshot_sha256']='b'*64
        self.stop('12-broker-modify-and-readonly-v1.py',[m,t,st,f],i,'快照身份或SHA变化')
    def test_readonly_recovery_never_claims_unowned(self):
        i,m,t,st,f,it=self.fixture_modify();i['verify_saved_only']=True;t['rows'][0]['reviewer']=None;it['rows'][-1]['item_comment']=i['v2_item_comment']
        self.stop('12-broker-modify-and-readonly-v1.py',[m,t,st,f,it],i,'只读恢复不领取')
    def test_modify_already_saved_v2_before_save(self):
        i,m,t,st,f,it=self.fixture_modify();it['rows'][-1]['item_comment']=i['v2_item_comment']
        self.stop('12-broker-modify-and-readonly-v1.py',[m,t,st,f,it],i,'不重复修改')
class ResubmitGuards(unittest.TestCase):
    def fixture(self):
        i,m,t,st,f,it=ModifyGuards().fixture_modify();i.update(resume_phase=0,initial_bc_parent_id=900)
        it['rows'][-1]['item_comment']=i['v2_item_comment'];j=ReinsurerGuards().fixture()[-1]
        f['rows'][0].pop('back_up_data');f['rows'][0].pop('source_table')
        return i,m,t,st,f,it,j
    def stop(self,replies,i,message):ReinsurerGuards().stop('14-broker-resubmit-and-two-audits.py',replies,i,message)
    def test_resubmit_rejects_completed_or_wrong_phase(self):
        i,m,t,st,f,it,j=self.fixture();st['rows'][1]['statement_status']=5
        self.stop([m,t,st],i,'不在声明重提')
    def test_resubmit_rejects_v1_custom(self):
        i,m,t,st,f,it,j=self.fixture();it['rows'][-1]['item_comment']='OWN-V1'
        self.stop([m,t,st,f,it],i,'实际V2零科目')
    def test_resubmit_rejects_other_bc_job_watermark(self):
        i,m,t,st,f,it,j=self.fixture();j['rows'][0]['parent_id']=899
        self.stop([m,t,st,f,it,j],i,'首轮水位不符')
    def test_explicit_resume_requires_exact_audit_level(self):
        i,m,t,st,f,it,j=self.fixture();i['resume_phase']=2;st['rows'][1]['statement_status']=1;t['rows'][0]['review_level']=1
        self.stop([m,t,st,f,it,j],i,'实际经纪审核级次不符')
class SecondReturnGuards(unittest.TestCase):
    def fixture(self):
        i,m,t,st,f,it,j=ResubmitGuards().fixture();i.update(custom_item_id=999,resubmit_bc_parent_id=902,resubmit_bc_detail_id=903)
        for row,v in zip(st['rows'],[3,5,3,3]):row['statement_status']=v
        new=dict(j['rows'][0],parent_id=902,detail_id=903);j=result(j['rows']+[new])
        return i,m,t,st,f,it,j
    def stop(self,replies,i,message):ReinsurerGuards().stop('16-second-reinsurer-return.py',replies,i,message)
    def test_second_return_stops_unfinished_resubmit(self):
        i,m,t,st,f,it,j=self.fixture();st['rows'][1]['statement_status']=1
        self.stop([m,t,st],i,'不在声明重提')
    def test_second_return_requires_actual_new_bc_job(self):
        i,m,t,st,f,it,j=self.fixture();j['rows'][1]['parent_id']=900
        self.stop([m,t,st,f,it,j],i,'缺新独立BC')
    def test_second_return_requires_exact_detail_id(self):
        i,m,t,st,f,it,j=self.fixture();j['rows'][1]['detail_id']=9999
        self.stop([m,t,st,f,it,j],i,'缺新独立BC')
    def test_second_return_requires_actual_current_item_id(self):
        i,m,t,st,f,it,j=self.fixture();i['custom_item_id']=998
        self.stop([m,t,st,f,it,j],i,'实时V2行ID变化')
class SubmitIntervalRegression(unittest.TestCase):
    def probe(self,exit_code):
        text=(ROOT/'14-broker-resubmit-and-two-audits.py').read_text();start=text.index('        cooldown=');end=text.index('        await ctx.call("playwright.page_assert_url"',start);segment=text[start:end]
        ns={};exec('async def probe(ctx,roles):\n    stage=1\n'+''.join(line[4:]+'\n' for line in segment.splitlines()),ns)
        calls=[]
        class Context:
            async def call(self,action,args):
                calls.append((action,args))
                if action=='process.run':return dict(exit_code=exit_code,stdout_truncated=False,stderr_truncated=False)
                return {}
        async def roles(values):calls.append(('roles',values))
        async def run_probe():
            try:await ns['probe'](Context(),roles)
            except ValueError:
                if exit_code==0:raise
        asyncio.run(run_probe());return calls
    def test_real_throttle_precedes_fresh_state_and_single_submit(self):
        calls=self.probe(0);self.assertEqual([x[0] for x in calls],['process.run','roles','playwright.page_click']);self.assertEqual(calls[0][1]['executable'],'/bin/sleep');self.assertEqual(calls[0][1]['args'],['6'])
    def test_throttle_failure_never_clicks_submit(self):self.assertEqual([x[0] for x in self.probe(1)],['process.run'])
if __name__=='__main__':unittest.main()
