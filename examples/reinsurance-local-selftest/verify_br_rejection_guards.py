"""Independent broker/reinsurer guards using in-memory replies; no business calls."""
import asyncio,ast,importlib.util,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).parent/'rejection_reinsurer_broker_steps'
def rows(*values):return {'rows':list(values),'row_count':len(values),'truncated':False}
def execute(n,ctx,overrides=None):
    d=next(x for x in json.loads((ROOT/'definitions.json').read_text()) if x['step_number']==n)
    inputs={k:v['default'] for k,v in d['input_schema']['properties'].items() if 'default' in v}
    inputs.update(platform_contract_number='OWN',contract_suffix='OWN',expected_biz_id='OWN-BC',master_id=100,cedant_id=10,broker_id=11,source_id=12)
    inputs.update(overrides or {})
    scope={};p=ROOT/d['source'];exec(compile(p.read_text(),str(p),'exec'),scope)
    return asyncio.run(scope['run'](ctx,inputs))
class Context:
    def __init__(self,replies):self.replies=iter(replies);self.actions=[]
    async def call(self,action,args):
        self.actions.append(action)
        if action!='tidb.query':raise AssertionError('guard reached side effect '+action)
        return next(self.replies)
class Guards(unittest.TestCase):
    def test_initial_wait_arguments_match_real_helper_parser(self):
        helper=Path('/Users/xiaojuju/Projects/company/bjs/dev-environment/test-support/wait_owned_br_00014.py')
        sys.path.insert(0,str(helper.parent))
        try:
            spec=importlib.util.spec_from_file_location('checked_br_wait',helper);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            for n,phase in [(5,'initial-ab'),(6,'initial-bc')]:
                d=next(d for d in json.loads((ROOT/'definitions.json').read_text()) if d['step_number']==n)
                calls=[node for node in ast.walk(ast.parse((ROOT/d['source']).read_text())) if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='call' and node.args and isinstance(node.args[0],ast.Constant) and node.args[0].value=='process.run']
                self.assertEqual(len(calls),1)
                args=ast.literal_eval(calls[0].args[1])['args'];self.assertEqual(Path(args[0]),helper)
                parsed=module.parse_args(args[1:]);self.assertEqual((parsed.phase,parsed.before_job,parsed.attempt),(phase,0,1))
        finally:sys.path.pop(0)
    def master(self):
        props=next(d for d in json.loads((ROOT/'definitions.json').read_text()) if d['step_number']==7)['input_schema']['properties']
        return rows({'id':100,'treaty_name':props['expected_treaty_name']['default']})
    def parties(self,statuses=('3','5','3')):
        return rows(*[dict(id=i,org_code=o,reinsurance_role=r,from_id=p,status=s,reviewer=None,biz_id='OWN-BC') for i,o,r,p,s in zip([10,11,12],['000050','000053','000045'],['01','03','02'],[None,10,11],statuses)])
    def test_initial_submit_existing_effect_stops(self):
        ctx=Context([self.parties(('3','3','0'))])
        with self.assertRaisesRegex(ValueError,'禁止重复提交'):execute(5,ctx)
        self.assertEqual(ctx.actions,['tidb.query'])
    def test_initial_submit_existing_job_stops(self):
        ctx=Context([self.parties(('0','0','0')),rows({'id':99,'status':4})])
        with self.assertRaisesRegex(ValueError,'核心任务已存在'):execute(5,ctx)
        self.assertEqual(ctx.actions,['tidb.query']*2)
    def test_initial_broker_other_master_stops(self):
        ctx=Context([rows()])
        with self.assertRaisesRegex(ValueError,'主表归属'):execute(6,ctx)
        self.assertEqual(ctx.actions,['tidb.query'])
    def test_initial_broker_wrong_relation_stops(self):
        value=self.parties(('3','3','0'));value['rows'][2]['from_id']=10
        ctx=Context([self.master(),value])
        with self.assertRaisesRegex(ValueError,'上下游不符'):execute(6,ctx)
        self.assertEqual(ctx.actions,['tidb.query']*2)
    def test_pending_wrong_phase_stops_before_login(self):
        ctx=Context([self.master(),self.parties(('3','13','4'))])
        with self.assertRaisesRegex(ValueError,'首次经纪确认后再保人待确认'):execute(7,ctx)
        self.assertEqual(ctx.actions,['tidb.query']*2)
    def test_pending_wrong_bc_biz_stops_before_login(self):
        value=self.parties();value['rows'][2]['biz_id']='OTHER'
        ctx=Context([self.master(),value])
        with self.assertRaisesRegex(ValueError,'业务ID'):execute(7,ctx)
        self.assertEqual(ctx.actions,['tidb.query']*2)
    def test_pending_wrong_fee_stops_before_login(self):
        ctx=Context([self.master(),self.parties(),rows({'broker_rate':'0.025'})])
        with self.assertRaisesRegex(ValueError,'V1经纪费率'):execute(7,ctx)
        self.assertEqual(ctx.actions,['tidb.query']*3)
    def test_reject_wrong_source_stops_before_write(self):
        ctx=Context([self.master(),self.parties()])
        with self.assertRaisesRegex(ValueError,'阶段或上下游'):execute(8,ctx,{'source_id':11})
        self.assertEqual(ctx.actions,['tidb.query']*2)
    def test_existing_snapshot_stops_repeat_rejection(self):
        ctx=Context([self.master(),self.parties(),rows({'broker_rate':'0.01'}),rows({'id':500})])
        with self.assertRaisesRegex(ValueError,'已有退回快照'):execute(8,ctx)
        self.assertEqual(ctx.actions,['tidb.query']*4)
    def test_modify_wrong_live_rate_stops_before_login(self):
        ctx=Context([self.parties(('3','13','4')),self.master(),rows({'broker_rate':'0.02'})])
        with self.assertRaisesRegex(ValueError,'暂存前实时费率'):execute(10,ctx)
        self.assertEqual(ctx.actions,['tidb.query']*3)
    def test_modify_changed_snapshot_stops_before_login(self):
        ctx=Context([self.parties(('3','13','4')),self.master(),rows({'broker_rate':'0.01'}),rows({'id':60005,'snapshot_sha256':'OTHER'})])
        with self.assertRaisesRegex(ValueError,'首次退回快照已变化'):execute(10,ctx)
        self.assertEqual(ctx.actions,['tidb.query']*4)
    def resubmit_parties(self,statuses=('3','13','4')):
        value=self.parties(statuses)
        for r in value['rows']:r['broker_rate']=None
        value['rows'][2]['broker_rate']='0.025'
        return value
    def test_resubmit_wrong_phase_stops_before_login(self):
        ctx=Context([self.master(),self.resubmit_parties(('3','5','3'))])
        with self.assertRaisesRegex(ValueError,'待重提阶段'):execute(12,ctx,{'expected_ab_biz_id':'OWN-BC'})
        self.assertEqual(ctx.actions,['tidb.query']*2)
    def test_existing_bc_resubmit_stops_before_login(self):
        props=next(d for d in json.loads((ROOT/'definitions.json').read_text()) if d['step_number']==12)['input_schema']['properties']
        ctx=Context([self.master(),self.resubmit_parties(),rows({'id':60005,'snapshot_sha256':props['snapshot_sha256']['default']}),rows({'id':props['before_job_id']['default'],'status':8},{'id':props['before_job_id']['default']+1,'status':4})])
        with self.assertRaisesRegex(ValueError,'不重复提交'):execute(12,ctx,{'expected_ab_biz_id':'OWN-BC'})
        self.assertEqual(ctx.actions,['tidb.query']*4)
    def test_full_two_audits_can_recheck_snapshot(self):
        props=next(d for d in json.loads((ROOT/'definitions.json').read_text()) if d['step_number']==12)['input_schema']['properties']
        outer=self
        class HappyContext:
            phase=0
            snapshot_reads=0
            helper_args=None
            def log(self,value):pass
            def result(self,**value):return value
            async def call(self,action,args):
                if action=='tidb.query':
                    title=args['title']
                    if title=='本笔重提主表归属':return outer.master()
                    if title=='本笔再保退经纪重提前后参与方':
                        value=outer.resubmit_parties(('3','13','4') if self.phase==0 else ('3','1','4') if self.phase<3 else ('3','5','3'))
                        for r in value['rows']:r['review_level']=None
                        if self.phase in [1,2]:value['rows'][1]['review_level']=str(self.phase)
                        return value
                    if title=='重提保留首次V1快照':
                        self.snapshot_reads+=1
                        return rows({'id':60005,'snapshot_sha256':props['snapshot_sha256']['default']})
                    if title=='首次BC基线及重复重提守卫':return rows({'id':props['before_job_id']['default'],'status':8})
                    if title=='V2 BC重提终审前record水位':return rows({'max_id':999})
                    if title=='本次新BC父和明细核对':return rows({'parent_id':props['before_job_id']['default']+1,'parent_status':8,'detail_id':123,'status':8,'biz_id':'OWN-BC','callback_result':'{"code":"0"}','onchain_times':1})
                    raise AssertionError(title)
                if action=='file.read':return {'content':{'ui':{'url':'http://localhost:9877/login','accounts':{'broker':'000053'},'sharedPassword':'FAKE'}}}
                if action=='playwright.page_inspect':
                    decision='确认并提交审核' if self.phase<2 else '本公司确认并提交至再保人'
                    return {'url':'http://localhost:9877/TreatyManagement/Treaty','elements':[{'type':'radio','enabled':True,'name':decision,'preferred_selector':{'kind':'label','value':decision}}]}
                if action=='playwright.page_text':return {'text':'平台合约编号：OWN'}
                if action=='playwright.page_input_value':return {'value':'2.5000'}
                if action=='playwright.page_click':
                    selector=args['selector']
                    if isinstance(selector,dict) and selector.get('name')=='确 定':self.phase=1
                    elif isinstance(selector,dict) and selector.get('name')=='提 交' and self.phase in [1,2]:self.phase+=1
                    return {}
                if action=='process.run':
                    self.helper_args=args['args']
                    return {'exit_code':0,'stdout':'{}','stdout_truncated':False,'stderr_truncated':False}
                if action.startswith('playwright.'):return {}
                raise AssertionError(action)
        ctx=HappyContext();result=execute(12,ctx,{'expected_ab_biz_id':'OWN-BC'})
        self.assertEqual(result['data']['audit_levels_in_this_attempt'],['1','2'])
        self.assertTrue(result['data']['resubmitted'])
        self.assertEqual(ctx.snapshot_reads,2)
        helper=Path(ctx.helper_args[0]);sys.path.insert(0,str(helper.parent))
        try:
            spec=importlib.util.spec_from_file_location('checked_br_resubmit_wait',helper);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
            args=m.parse_args(ctx.helper_args[1:]);self.assertEqual((args.phase,args.before_job,args.attempt),('resubmit-bc',props['before_job_id']['default'],2))
        finally:sys.path.pop(0)
    def test_second_reject_changed_v1_snapshot_stops_before_login(self):
        ctx=Context([self.master(),self.parties(),rows({'id':60005,'snapshot_sha256':'OTHER'})])
        with self.assertRaisesRegex(ValueError,'旧快照已变化'):execute(14,ctx)
        self.assertEqual(ctx.actions,['tidb.query']*3)
    def test_second_reject_wrong_v2_fee_stops_before_login(self):
        props=next(d for d in json.loads((ROOT/'definitions.json').read_text()) if d['step_number']==14)['input_schema']['properties']
        ctx=Context([self.master(),self.parties(),rows({'id':60005,'snapshot_sha256':props['snapshot_sha256']['default']}),rows({'broker_rate':'0.01'})])
        with self.assertRaisesRegex(ValueError,'实时V2费率不符'):execute(14,ctx)
        self.assertEqual(ctx.actions,['tidb.query']*4)
    def test_final_view_wrong_hash_stops_before_login(self):
        ctx=Context([rows({'id':60006,'snapshot_sha256':'b'*64})])
        with self.assertRaisesRegex(ValueError,'V2快照归属或内容'):execute(15,ctx,{'expected_snapshot_id':60006,'expected_snapshot_sha256':'a'*64})
        self.assertEqual(ctx.actions,['tidb.query'])
    def test_final_view_old_fee_stops_before_login(self):
        props=next(d for d in json.loads((ROOT/'definitions.json').read_text()) if d['step_number']==15)['input_schema']['properties']
        ctx=Context([rows({'id':60006,'snapshot_sha256':'a'*64,'frozen_name':props['expected_treaty_name']['default'],'frozen_number':'OWN','frozen_party_id':12,'frozen_rate':'1'})])
        with self.assertRaisesRegex(ValueError,'V2快照参与方或费率'):execute(15,ctx,{'expected_snapshot_id':60006,'expected_snapshot_sha256':'a'*64})
        self.assertEqual(ctx.actions,['tidb.query'])
if __name__=='__main__':unittest.main()
