"""Own-draft guards for a fresh broker-return bill. No browser/network/BJS writes."""
import asyncio,ast,importlib.util,sys,unittest
from pathlib import Path
from verify_guards import DraftContext,result
ROOT=Path(__file__).parent/'rejection_bill_broker_steps'
def execute(name,ctx,inputs):
    p=ROOT/name;scope={};exec(compile(p.read_text(),str(p),'exec'),scope)
    return asyncio.run(scope['run'](ctx,inputs))
class ReadContext:
    def __init__(self,row):self.row=row;self.calls=[]
    async def call(self,action,args):
        self.calls.append(action)
        if action!='tidb.query':raise AssertionError('Guard reached UI action '+action)
        return result([self.row])
class Guards(unittest.TestCase):
    def pending_data(self):
        inputs=dict(statement_id=100,record_no='T-SOAP0002',platform_treaty_no='T',bill_label='NEW',normal_id=11,downstream_normal_id=12,expected_biz_id='OWN',v1_comment='V1')
        master=result([dict(id=100,treaty_id=325094,record_no='T-SOAP0002',comment='V1')])
        tree=result([dict(id=11,statement_id=100,input_org_code='000050',enter_org_code='000053',parent_id=None,treaty_reinsurer_id=10925281,currency='CNY',net_balance='70000.00',platform_statement_no='T-SOA1',cedent_statement_no='NEW-TOTAL',biz_id='OWN',reviewer=None,business_comment='V1'),dict(id=12,statement_id=100,input_org_code='000053',enter_org_code='000045',parent_id=11,treaty_reinsurer_id=10925282,currency='CNY',net_balance='70000.00')])
        states=result([dict(statement_normal_id=n,org_code=o,reinsurance_role=r,statement_status=s) for n,o,r,s in [(11,'000050','01',3),(11,'000053','02',3),(12,'000045','02',0),(12,'000053','01',0)]])
        return inputs,master,tree,states
    def pending_stops(self,replies,inputs,message):
        class Context:
            def __init__(self):self.calls=[];self.replies=iter(replies)
            async def call(self,action,args):
                self.calls.append(action)
                if action!='tidb.query':raise AssertionError('guard reached external action '+action)
                return next(self.replies)
        ctx=Context()
        with self.assertRaisesRegex(ValueError,message):execute('05-broker-pending-and-claim.py',ctx,inputs)
        self.assertEqual(ctx.calls,['tidb.query']*len(replies))
    def test_pending_wrong_tree_stops_before_claim(self):
        inputs,m,t,s=self.pending_data();t['rows'][1]['parent_id']=99
        self.pending_stops([m,t],inputs,'normal树或活动ID')
    def test_pending_wrong_phase_stops_before_claim(self):
        inputs,m,t,s=self.pending_data();s['rows'][1]['statement_status']=4
        self.pending_stops([m,t,s],inputs,'首次经纪待确认')
    def test_pending_other_reviewer_stops_before_claim(self):
        inputs,m,t,s=self.pending_data();t['rows'][0]['reviewer']='000045'
        self.pending_stops([m,t,s],inputs,'其他账号领取')
    def test_pending_existing_snapshot_stops_before_claim(self):
        inputs,m,t,s=self.pending_data()
        self.pending_stops([m,t,s,result([dict(id=999)])],inputs,'已存在退回快照')
    def test_claim_arguments_match_real_parser(self):
        calls=[n for n in ast.walk(ast.parse((ROOT/'05-broker-pending-and-claim.py').read_text())) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='call' and n.args and isinstance(n.args[0],ast.Constant) and n.args[0].value=='process.run']
        self.assertEqual(len(calls),1);arg_node=next(v for k,v in zip(calls[0].args[1].keys,calls[0].args[1].values) if k.value=='args');args=[]
        for node in arg_node.elts:
            if isinstance(node,ast.Constant):args.append(node.value)
            else:
                self.assertIsInstance(node,ast.Call);self.assertEqual(node.func.id,'str');self.assertEqual(node.args[0].value.id,'inputs');self.assertEqual(node.args[0].slice.value,'normal_id');args.append('123')
        helper=Path(args[0]);sys.path.insert(0,str(helper.parent))
        try:
            spec=importlib.util.spec_from_file_location('checked_bill_claim',helper);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
            parsed=m.parse_args(args[1:]);self.assertEqual((parsed.actor,parsed.normal_id,parsed.expected_status,parsed.claim),('000053',123,3,True))
        finally:sys.path.pop(0)
    def test_initial_wait_arguments_match_real_parser(self):
        p=ROOT/'04-submit.py';calls=[n for n in ast.walk(ast.parse(p.read_text())) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='call' and n.args and isinstance(n.args[0],ast.Constant) and n.args[0].value=='process.run']
        self.assertEqual(len(calls),1);args=ast.literal_eval(calls[0].args[1])['args'];helper=Path(args[0]);sys.path.insert(0,str(helper.parent))
        try:
            spec=importlib.util.spec_from_file_location('checked_bill_initial_wait',helper);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
            parsed=m.parse_args(args[1:]);self.assertEqual(parsed.phase,'initial');self.assertIsNone(parsed.expected_comment)
        finally:sys.path.pop(0)
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
    def test_old_completed_bill_rejected_before_edit(self):self.assert_save_guard({'statement_status':6})
    def test_other_record_rejected_before_edit(self):self.assert_save_guard({'record_no':'OTHER'})
    def test_other_marker_rejected_before_edit(self):self.assert_save_guard({'comment':'仅供本地自测 OLD'})
    def test_initial_submit_after_effect_stops_before_ui(self):
        ctx=ReadContext(dict(id=100,record_no='T-SOAP0002',statement_status=3,comment='仅供本地自测 NEW'))
        with self.assertRaisesRegex(ValueError,'禁止重复提交'):execute('04-submit.py',ctx,dict(statement_id=100,platform_treaty_no='T',bill_label='NEW',expected_record_no='T-SOAP0002'))
        self.assertEqual(ctx.calls,['tidb.query'])
    def test_existing_initial_job_stops_before_ui(self):
        normals=[dict(id=11,statement_id=100,input_org_code='000050',enter_org_code='000053',parent_id=None,net_balance='70000.00'),dict(id=12,statement_id=100,input_org_code='000053',enter_org_code='000045',parent_id=11,net_balance='70000.00')]
        expected=[dict(code=c,amount=a) for c,a in [('01','100000.00'),('02','20000.00'),('21','10000.00'),('60','0.00')]]
        replies=iter([result([dict(id=100,record_no='T-SOAP0002',statement_status=0,comment='仅供本地自测 NEW')]),result(normals),result([dict(object_id=n['id'],item_code=i['code'],item_amount=i['amount']) for n in normals for i in expected]),result([dict(id=999,status=4)])])
        class Context:
            def __init__(self):self.calls=[]
            async def call(self,action,args):
                self.calls.append(action)
                if action!='tidb.query':raise AssertionError(action)
                return next(replies)
        ctx=Context()
        with self.assertRaisesRegex(ValueError,'初始任务已存在'):execute('04-submit.py',ctx,dict(statement_id=100,platform_treaty_no='T',bill_label='NEW',expected_record_no='T-SOAP0002',expected_normals=normals,expected_items=expected))
        self.assertEqual(ctx.calls,['tidb.query']*4)
    def test_foreign_pending_warning_stops_before_modal_read_or_click(self):
        normals=[dict(id=11,statement_id=100,input_org_code='000050',enter_org_code='000053',parent_id=None,net_balance='70000.00'),dict(id=12,statement_id=100,input_org_code='000053',enter_org_code='000045',parent_id=11,net_balance='70000.00')]
        expected=[dict(code='01',amount='100000.00')]
        replies=iter([result([dict(id=100,record_no='T-SOAP0002',statement_status=0,comment='仅供本地自测 NEW')]),result(normals),result([dict(object_id=n['id'],item_code='01',item_amount='100000.00') for n in normals]),result([]),result([dict(max_id=999)])])
        class Context:
            def __init__(self):self.actions=[]
            def log(self,value):pass
            async def call(self,action,args):
                self.actions.append(action)
                if action=='tidb.query':return next(replies)
                if action=='playwright.page_assert_text':return {}
                if action=='playwright.page_assert_url':
                    self.expected_url=args['url']
                    # An unrelated bill's same-message warning is currently open.
                    raise ValueError('FOREIGN_BILL_PAGE')
                raise AssertionError('Guard reached modal or write '+action)
        ctx=Context()
        with self.assertRaisesRegex(ValueError,'FOREIGN_BILL_PAGE'):execute('04-submit.py',ctx,dict(statement_id=100,platform_treaty_no='T',bill_label='NEW',expected_record_no='T-SOAP0002',expected_normals=normals,expected_items=expected))
        self.assertIn('id=100&',ctx.expected_url)
        self.assertNotIn('playwright.page_state',ctx.actions)
        self.assertNotIn('playwright.page_click',ctx.actions)
class ReturnGuards(unittest.TestCase):
    pending_data=Guards.pending_data
    # Inherited fixture helpers exercise the real first-return body until the
    # first external action; all data are isolated fake query responses.
    def return_stops(self,replies,inputs,message):
        class Context:
            def __init__(self):self.calls=[];self.replies=iter(replies)
            async def call(self,action,args):
                self.calls.append(action)
                if action!='tidb.query':raise AssertionError('return guard reached external action '+action)
                return next(self.replies)
        ctx=Context()
        with self.assertRaisesRegex(ValueError,message):execute('06-first-return.py',ctx,inputs)
        self.assertEqual(ctx.calls,['tidb.query']*len(replies))
    def test_first_return_wrong_phase_has_no_ui_effect(self):
        inputs,m,t,s=self.pending_data();s['rows'][1]['statement_status']=4
        self.return_stops([m,t,s],inputs,'首次经纪待确认')
    def test_first_return_existing_snapshot_has_no_ui_effect(self):
        inputs,m,t,s=self.pending_data();t['rows'][0]['reviewer']='000053'
        self.return_stops([m,t,s,result([dict(id=999)])],inputs,'已存在退回快照')
    def test_first_return_unclaimed_has_no_ui_effect(self):
        inputs,m,t,s=self.pending_data()
        self.return_stops([m,t,s,result([])],inputs,'尚未由经纪账号领取')
class ModifyGuards(unittest.TestCase):
    def test_wrong_v2_rule_stops_before_any_read_or_action(self):
        ctx=ReadContext({})
        with self.assertRaisesRegex(ValueError,'V2业务备注'):execute('08-modify-comment-and-verify-v1.py',ctx,dict(v1_comment='OWN',v2_comment='OTHER'))
        self.assertEqual(ctx.calls,[])
    def test_wrong_stage_stops_before_claim_or_save(self):
        ctx=ReadContext(dict(statement_normal_id=11,org_code='000050',reinsurance_role='01',statement_status=3))
        with self.assertRaisesRegex(ValueError,'退回待修改阶段'):execute('08-modify-comment-and-verify-v1.py',ctx,dict(v1_comment='OWN',v2_comment='OWN V2',normal_id=11,downstream_normal_id=12))
        self.assertEqual(ctx.calls,['tidb.query'])
    def test_changed_snapshot_stops_before_claim_or_save(self):
        _,_,_,r=Guards().pending_data();r['rows'][0]['statement_status']=13;r['rows'][1]['statement_status']=4
        replies=iter([r,result([dict(id=999,is_deleted='N',snapshot_sha256='x'*64,frozen_comment='OWN')])])
        class Context:
            def __init__(self):self.calls=[]
            async def call(self,action,args):
                self.calls.append(action)
                if action!='tidb.query':raise AssertionError(action)
                return next(replies)
        ctx=Context()
        with self.assertRaisesRegex(ValueError,'V1快照已变化'):execute('08-modify-comment-and-verify-v1.py',ctx,dict(v1_comment='OWN',v2_comment='OWN V2',normal_id=11,downstream_normal_id=12,snapshot_id=998,snapshot_sha256='x'*64))
        self.assertEqual(ctx.calls,['tidb.query']*2)
class ResubmitGuards(unittest.TestCase):
    def test_already_resubmitted_stops_before_ui(self):
        _,_,_,states=Guards().pending_data()
        class Context:
            def __init__(self):self.calls=[]
            async def call(self,action,args):
                self.calls.append(action)
                if action!='tidb.query':raise AssertionError(action)
                return states
        ctx=Context()
        with self.assertRaisesRegex(ValueError,'退回待修改阶段'):execute('10-synchronous-resubmit.py',ctx,dict(v1_comment='OWN',v2_comment='OWN V2',normal_id=11,downstream_normal_id=12))
        self.assertEqual(ctx.calls,['tidb.query'])
    def test_resubmit_wait_arguments_match_parser(self):
        code=ast.parse((ROOT/'10-synchronous-resubmit.py').read_text())
        calls=[n for n in ast.walk(code) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='call' and n.args and isinstance(n.args[0],ast.Constant) and n.args[0].value=='process.run']
        self.assertEqual(len(calls),1)
        node=next(v for k,v in zip(calls[0].args[1].keys,calls[0].args[1].values) if k.value=='args');values={'snapshot_id':60007,'snapshot_sha256':'f'*64,'v2_comment':'TW-LOCAL-BILL-CB-20261016061154 V2'}
        args=eval(compile(ast.Expression(node),'<args>','eval'),{'str':str,'inputs':values});helper=Path(args[0]);sys.path.insert(0,str(helper.parent))
        try:
            spec=importlib.util.spec_from_file_location('checked_bill_resubmit_wait',helper);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
            parsed=m.parse_args(args[1:]);self.assertEqual(parsed.phase,'resubmit');self.assertEqual(parsed.snapshot_id,60007);self.assertEqual(parsed.expected_comment,values['v2_comment'])
        finally:sys.path.pop(0)
class DecisionReadyRegression(unittest.TestCase):
    def run_segment(self,remove_wait=False):
        root=ast.parse((ROOT/'10-synchronous-resubmit.py').read_text());body=root.body[0].body
        start=next(i for i,n in enumerate(body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='decision' for t in n.targets))
        end=next(i for i in range(start,len(body)) if isinstance(body[i],ast.Expr) and isinstance(body[i].value,ast.Await) and body[i].value.value.args[0].value=='playwright.page_click')
        segment=body[start:end+1]
        if remove_wait:segment=[n for n in segment if not(isinstance(n,ast.Expr) and isinstance(n.value,ast.Await) and n.value.value.args[0].value=='playwright.page_assert_state')]
        template=ast.parse('async def probe(ctx,inputs): pass');template.body[0].body=segment;ast.fix_missing_locations(template);ns={};exec(compile(template,'<actual-decision-segment>','exec'),ns)
        class Context:
            def __init__(self):self.ready=False;self.clicks=0
            async def call(self,action,args):
                if action=='playwright.page_assert_state':self.ready=True
                if action=='playwright.page_check' and not self.ready:raise ValueError('LOCATOR_NOT_FOUND_before_decision_loaded')
                if action=='playwright.page_click':self.clicks+=1
                return {}
        ctx=Context();asyncio.run(ns['probe'](ctx,dict(bill_label='OWN')));return ctx
    def test_old_no_wait_reproduces_missing_decision(self):
        with self.assertRaisesRegex(ValueError,'LOCATOR_NOT_FOUND'):self.run_segment(True)
    def test_new_wait_handles_delayed_decision_and_one_submit(self):
        ctx=self.run_segment();self.assertEqual(ctx.clicks,1)
class SecondReturnGuards(unittest.TestCase):
    def inputs_and_replies(self):
        i,m,t,r=Guards().pending_data();i.update(v2_comment='V1 V2',snapshot_id=700,snapshot_sha256='f'*64);t['rows'][0]['business_comment']=i['v2_comment'];return i,m,t,r
    def stop(self,replies,inputs,message):
        class Context:
            def __init__(self):self.calls=[];self.replies=iter(replies)
            async def call(self,action,args):
                self.calls.append(action)
                if action!='tidb.query':raise AssertionError('Guard reached side effect '+action)
                return next(self.replies)
        ctx=Context()
        with self.assertRaisesRegex(ValueError,message):execute('12-second-return.py',ctx,inputs)
        self.assertEqual(ctx.calls,['tidb.query']*len(replies))
    def test_already_second_returned_stops_before_claim(self):
        i,m,t,r=self.inputs_and_replies();r['rows'][1]['statement_status']=4
        self.stop([m,t,r],i,'首次经纪待确认')
    def test_old_snapshot_changed_stops_before_claim(self):
        i,m,t,r=self.inputs_and_replies()
        self.stop([m,t,r,result([dict(id=700,is_deleted='Y',snapshot_sha256='f'*64,frozen_comment='V1')])],i,'V1快照已变化')
    def test_unexpected_third_snapshot_stops_before_claim(self):
        i,m,t,r=self.inputs_and_replies()
        self.stop([m,t,r,result([dict(id=700),dict(id=701)])],i,'已二次退回或快照数量变化')
if __name__=='__main__':unittest.main()
