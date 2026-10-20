"""Create the requested local plans, draft workflows and evidence-complete exports."""
import ast
import base64
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3

from taskweave.application.service import Application
from taskweave.core.validation import normalize_step
from build_catalog import BJS, EVIDENCE, OUTPUT, ROOT
from variables import business_properties

HOME = Path('/Users/xiaojuju/taskweave/workspace')
GROUPS = {'environment':'本地环境与角色', 'treaty':'分出方合约录入确认与退回',
          'bill':'合约账单录入确认与退回', 'settlement':'结算单录入确认与退回',
          'onchain':'上链记录与场内外来源'}

SNAPSHOT = '''async def run(ctx, inputs):
    result = await ctx.call("tidb.query", {"sql": "SELECT id, source_table, source_id, SHA2(back_up_data,256) AS snapshot_sha256 FROM t_business_back_up_data WHERE source_table=%s AND source_id=%s AND is_deleted='N' ORDER BY id", "params": [inputs["source_table"], inputs["source_id"]], "max_rows": 20, "title": "本轮有效快照"})
    if result["truncated"] or result["row_count"] != 1:
        raise ValueError("目标来源必须恰好1条有效快照，不能把空结果或截断结果计为通过")
    row = result["rows"][0]
    if not row["snapshot_sha256"]:
        raise ValueError("快照内容为空")
    if "expected_snapshot_sha256" in inputs:
        if row["snapshot_sha256"] != inputs["expected_snapshot_sha256"] or str(row["id"]) != str(inputs["expected_snapshot_id"]):
            raise ValueError("暂存或重新提交改变了应保留的旧快照")
    return ctx.result(data={"snapshot_id": row["id"], "snapshot_sha256": row["snapshot_sha256"], "source_table": row["source_table"], "source_id": row["source_id"]})
'''

RECORD = '''async def run(ctx, inputs):
    checked = []
    for expected in inputs["record_expectations"]:
        result = await ctx.call("tidb.query", {"sql": "SELECT id,biz_id,msg_name,otc_flag,tx_hash,data_from,data_to FROM t_ri_gsc_onchain_record WHERE biz_id=%s AND msg_name=%s AND id>%s ORDER BY id", "params": [expected["biz_id"], expected["msg_name"], inputs["after_record_id"]], "max_rows": 100, "title": "本轮新增上链记录"})
        if result["truncated"] or result["row_count"] == 0:
            raise ValueError("本轮没有完整的目标record，不能以Mock返回成功或历史业务状态判通过")
        for row in result["rows"]:
            if row["otc_flag"] != expected["otc_flag"]:
                raise ValueError("本次调用的场内外标记不符合预期")
            checked.append(row)
    if not checked:
        raise ValueError("没有目标记录")
    return ctx.result(data={"record_count": len(checked), "records": checked, "boundary": "仅证明本地record落库和来源标记，不能代表真实链节点已验收"})
'''

ENVIRONMENT = '''async def run(ctx, inputs):
    result = await ctx.call("process.check_environment", {"directories": [inputs["bjs_root"], inputs["evidence_root"]], "programs": [{"executable": inputs["python_executable"]}], "max_output_bytes": 65536})
    if any(not entry["available"] for entry in result["directories"] + result["programs"]):
        raise ValueError("本地目录或Python不可用")
    return ctx.result(data=result)
'''

DATABASE = '''async def run(ctx, inputs):
    result = await ctx.call("tidb.query", {"sql": "SELECT DATABASE() AS current_database, VERSION() AS version", "max_rows": 1, "title": "本地自测数据库"})
    if result["row_count"] != 1 or result["rows"][0]["current_database"] != inputs["expected_database"]:
        raise ValueError("连接的数据库不是本地交接库")
    return ctx.result(data=result)
'''


def schema(properties, required=None):
    return dict(type='object', properties=properties, required=list(properties) if required is None else required, additionalProperties=False)


def document(step, case, first_snapshot):
    bindings = {}
    props = {}
    code = ''
    kind = step['kind']
    input_schema = None
    authored_source = ROOT/'examples/reinsurance-local-selftest'/({'TREATY-01':'treaty_steps','BILL-01':'bill_steps','SETTLE-01':'settlement_steps','SETTLE-02':'settlement_receiver_steps','TREATY-03':'rejection_broker_steps','TREATY-02':'rejection_direct_steps','TREATY-04':'rejection_reinsurer_broker_steps','BILL-02':'rejection_bill_direct_steps','BILL-03':'rejection_bill_broker_steps','BILL-04':'rejection_bill_reinsurer_broker_steps','BILL-05':'rejection_bill_adjust_steps'}.get(case['key'], ''))
    definition = next((d for d in json.loads((authored_source/'definitions.json').read_text()) if d['name']==step['name']), None) if case['key'] in {'TREATY-01','TREATY-02','TREATY-03','TREATY-04','BILL-02','BILL-03','BILL-04','BILL-05','BILL-01','SETTLE-01','SETTLE-02'} else None
    if definition:
        code=(authored_source/definition['source']).read_text()
        input_schema=definition['input_schema']
        bindings=definition['bindings']
    elif case['key']=='ENV-01' and step['role'] in {'cedant','broker','reinsurer'}:
        code=(ROOT/'examples/reinsurance-local-selftest/login.py').read_text()
        accounts={'cedant':('cedent','000050','京东安联'),'broker':('broker','000053','日本财产'),'reinsurer':('reinsurer','000045','三星')}
        key,account,name=accounts[step['role']]
        props={k:{'type':'string','default':v} for k,v in dict(role=step['role'],account_key=key,expected_account=account,expected_org_text=name,credentials_path='dev-environment/imports/runtime/selftest-handoff/credentials.json').items()}
    elif kind in {'snapshot','snapshot_compare'}:
        code = SNAPSHOT
        props = {'source_table':{'type':'integer','enum':[2,3,5]},'source_id':{'type':'integer','minimum':1}}
        bindings = {name: {'ref':{'source':'task','pointer':'/'+name}} for name in props}
        if kind == 'snapshot_compare':
            props.update(expected_snapshot_id={'type':['integer','string']},expected_snapshot_sha256={'type':'string','minLength':64,'maxLength':64})
            for field,output in [('expected_snapshot_id','snapshot_id'),('expected_snapshot_sha256','snapshot_sha256')]:
                bindings[field]={'ref':{'source':'step','step_id':first_snapshot,'output':'data','pointer':'/'+output}}
    elif kind=='record':
        code=RECORD
        props={'record_expectations':{'type':'array','minItems':1,'items':schema({'biz_id':{'type':'string','minLength':1},'msg_name':{'type':'string','minLength':1},'otc_flag':{'enum':[0,1,None]}})},'after_record_id':{'type':'integer','minimum':0}}
        bindings={name:{'ref':{'source':'task','pointer':'/'+name}} for name in props}
    elif kind=='database':
        code=DATABASE;props={'expected_database':{'type':'string','default':'ricloud_boar_db_local'}}
    elif kind=='environment':
        code=ENVIRONMENT;props={'bjs_root':{'type':'string','default':str(BJS)},'evidence_root':{'type':'string','default':str(EVIDENCE)},'python_executable':{'type':'string','default':str(ROOT/'.venv/bin/python')}}
    capabilities=sorted({node.args[0].value for node in ast.walk(ast.parse(code)) if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and isinstance(node.func.value,ast.Name) and node.func.value.id=='ctx' and node.func.attr=='call'}) if code else ['playwright.page_open','playwright.page_inspect']
    # Each step keeps its evidence provider available, including read-only SQL assertions.
    if 'playwright.page_inspect' not in capabilities:capabilities.append('playwright.page_inspect')
    versions={'playwright':'0.4.0','tidb':'0.2.0','process':'0.1.0','file':'0.1.0','utility':'0.1.0'}
    notes=f"用例{case['key']}；角色{step['role']}；依赖：{','.join(case.get('dependencies',[])) or '本地交接环境'}。\n前置：本轮独立测试单和正确角色，历史ID仅供回看。\n操作：{step['instructions']}\n成功标准：{step['expected']}\n状态："+('已编写代码，须对应当前内容哈希的实际试跑记录证明通过。' if code else '已编写操作与验收要求；本地写操作代码待对应页面采集后补齐，不可当作自动执行通过。')+"\n证据为backupdatafix及recordotcflag历史本地记录，当前运行结果单独保存。"
    return normalize_step(dict(name=step['name'],step_description=f"角色：{step['role']}。{step['instructions']} 成功标准：{step['expected']}",step_notes=notes,step_content=code,input_schema=input_schema or schema(props),output_schema={'type':'object'},bindings=bindings,capabilities=capabilities,plugin_requirements={c.split('.')[0]:versions[c.split('.')[0]] for c in capabilities},timeout_ms=180000))


def capture(label, payload, views=(), notes=''):
    return {'label':label,'operation_notes':notes,'send_preview':False,'captured_at':datetime.now().astimezone().isoformat(),
            'source_page':'historical_bjs_evidence_import','include_view':True,
            'request':{'url':'http://localhost:9877','scope':'full_page','role':'operator'},
            'capture':{'items':[{'kind':'text','mime_type':'application/json','content':json.dumps(payload,ensure_ascii=False,default=str),'source':'backupdatafix及recordotcflag historical local evidence','truncated':False}], 'views':list(views)}}


def source_materials(names, ui_results):
    captures=[]
    for name in dict.fromkeys(names):
        path=EVIDENCE/name
        if not path.is_file():
            raise ValueError('历史证据文件不存在：'+name)
        data=json.loads(path.read_text())
        related=[r for r in ui_results if r.get('source')==name]
        captures.append(capture('历史记录 '+name,{'source_path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'historical_only':True,'data':data,'recorded_results':[{k:v for k,v in row.items() if k not in ('screenshots','historicalScreenshots','desktopRecapture')} for row in related]},notes='历史记录导入；不能用其PASS证明本轮执行通过。'))
        images=[]
        for row in related:
            current=row.get('screenshots',[])
            recapture=row.get('desktopRecapture',{}).get('screenshots',[])
            images.extend(current or recapture)
        if name=='otc-e2e-four-cases.json':
            for row in data:images.extend(row.get('images',[]))
        for image_name in dict.fromkeys(images):
            image_path=EVIDENCE/image_name
            if not image_path.is_file():raise ValueError('历史图片不存在：'+str(image_path))
            mime='image/png' if image_path.suffix=='.png' else 'image/jpeg'
            captures.append(capture('历史截图 '+image_path.name,{'source_path':str(image_path),'historical_only':True,'sha256':hashlib.sha256(image_path.read_bytes()).hexdigest()},[{'title':'历史自测截图 '+image_path.name,'renderer':'playwright.screenshot','data':{'image_base64':base64.b64encode(image_path.read_bytes()).decode(),'mime_type':mime}}],notes='历史真实页面或明确标记的结果整理图；时间点与Mock边界以来源记录为准。'))
    return captures


def main():
    catalog=json.loads((ROOT/'examples/reinsurance-local-selftest/catalog.json').read_text())
    receipt_path=OUTPUT/'authoring-receipt.json'
    if receipt_path.exists():raise SystemExit('已有创建收据；先核对，不重复创建或覆盖现有任务。')
    OUTPUT.mkdir(parents=True,exist_ok=True)
    backup=OUTPUT/'workspace-before-authoring.db'
    if not backup.exists():
        with sqlite3.connect('file:'+str(HOME/'taskweave.db')+'?mode=ro',uri=True) as src,sqlite3.connect(backup) as dst:src.backup(dst)
        backup.chmod(0o600)
    ui_results=json.loads((EVIDENCE/'ui-results.json').read_text())['results']
    receipt={'created_at':datetime.now().astimezone().isoformat(),'workspace':str(HOME),'plans':{},'tasks':[],'issues':[]}
    with Application(HOME) as app:
        with app.repo.unit_of_work.transaction():
            env=app.dispatch('environment.save',{'name':'BJS 本地自测 20261016','public_config':{'base_url':'http://localhost:9877','tidb_host':'127.0.0.1','tidb_port':4000,'tidb_database':'ricloud_boar_db_local','tidb_username':'root','tidb_password':'','tidb_tls':False,'tidb_timeout_seconds':30,'process_root':str(BJS),'file_root':str(BJS),'playwright_headless':False,'playwright_locale':'zh-CN','cedant_org_code':'000050','broker_org_code':'000053','reinsurer_org_code':'000045','local_mode':'business_mock'},'descriptions':{'local_mode':'默认业务回归Mock；来源验证须按交接切真实provider，不把Mock成功当真实链通过。'}})
            receipt['environment_id']=env['environment_id']
            for domain,title in GROUPS.items():
                plan=app.dispatch('plan.create',{'name':'本地自测 '+title})
                plan=app.dispatch('plan.update',{'plan_id':plan['plan_id'],'expected_revision':plan['revision'],'name':plan['name'],'plan_description':'依据backupdatafix及recordotcflag及现有本地自测证据，形成可续编和复测的流程。历史结论不等于本轮通过。','plan_notes':'；'.join(c['key']+' '+c['title'] for c in catalog['cases'] if c['domain']==domain)+'。各任务线性执行，任务间依赖通过收据及实际业务ID交接。写操作草稿需本地页面采集和补齐代码；只读断言可先试跑。','environment_id':env['environment_id'],'plugin_ids':['playwright','tidb','process']})
                receipt['plans'][domain]={'plan_id':plan['plan_id'],'name':plan['name']}
            for case in catalog['cases']:
                props={}
                if case.get('snapshot_source_table'):
                    props.update(source_table={'type':'integer','const':case['snapshot_source_table'],'default':case['snapshot_source_table']},source_id={'type':'integer','minimum':1,'description':'本轮来源主键；来源5必须为settlementId，不能使用taskId。'})
                if any(s['kind']=='record' for s in case['steps']):
                    props.update(record_expectations={'type':'array','minItems':1,'items':schema({'biz_id':{'type':'string','minLength':1},'msg_name':{'type':'string','minLength':1},'otc_flag':{'enum':[0,1,None]}}),'description':'本轮业务ID/消息类型/预期来源；普通场内0场外1，清结算null。'},after_record_id={'type':'integer','minimum':0,'description':'开始本轮写操作前记录的record最大ID；只核对此ID之后新记录。'})
                required=[key for key in props if not (case['key'] in {'TREATY-02','TREATY-03','TREATY-04','BILL-02','BILL-03','BILL-04','BILL-05'} and key=='source_id')]
                props.update(business_properties(case['domain']))
                if case['key'] in {'TREATY-02','TREATY-03','TREATY-04'}:props['name_prefix']['default']='TW-LOCAL-DIRECT-' if case['key']=='TREATY-02' else ('TW-LOCAL-CB-' if case['key']=='TREATY-03' else 'TW-LOCAL-BR-')
                if case['key']=='BILL-02':props['name_prefix']['default']='TW-LOCAL-BILL-DIRECT-'
                if case['key']=='BILL-03':props['name_prefix']['default']='TW-LOCAL-BILL-CB-'
                if case['key']=='BILL-04':props['name_prefix']['default']='TW-LOCAL-BILL-BR-'
                if case['key']=='BILL-05':props['name_prefix']['default']='TW-LOCAL-BILL-ADJ-'
                task=app.dispatch('task.create',{'name':'本地自测 '+case['key']+' '+case['title'],'description':'对应规划：'+receipt['plans'][case['domain']]['name']+'；依赖：'+','.join(case.get('dependencies',[]))+'。历史证据已随步骤保存；写操作为待续编草稿，未宣称本轮全流程通过。','input_schema':schema(props,required)})
                mapping={};first_snapshot=None;compiled=0
                case_sources=list(dict.fromkeys(f for s in case['steps'] for f in s['sources']))
                plan_id=receipt['plans'][case['domain']]['plan_id']
                material=source_materials(case_sources,ui_results)
                plan=app.dispatch('plan.get',{'plan_id':plan_id})
                plan_captures=[capture('任务 '+case['key'],{'case':case,'source_thread':catalog['source_thread'],'historical_only':True})]+material
                app.dispatch('plan.context.save_batch',{'plan_id':plan_id,'expected_revision':plan['revision'],'context_id':None,'provider_id':'playwright.page','name':case['key']+' '+case['title'],'context_notes':'业务说明与历史原始自测记录，包含真实图片预览。新执行证据另行采集。','captures':plan_captures})
                for i,step in enumerate(case['steps'],1):
                    doc=document(step,case,first_snapshot)
                    for binding in doc['bindings'].values():
                        ref=binding.get('ref',{})
                        if ref.get('source')=='step':ref['step_id']=mapping[ref['step_id']]
                    saved=app.dispatch('step.save',{'task_id':task['task_id'],'document':doc})
                    mapping[f'step-{i}']=saved['step_id']
                    if step['kind']=='snapshot' and first_snapshot is None:first_snapshot=f'step-{i}'
                    if doc['step_content']:
                        result=app.dispatch('step.validate',{'step_id':saved['step_id']})
                        if not result['valid']:raise ValueError(result)
                        compiled+=1
                    materials=[capture('本步骤操作与验收',{'case':case['key'],'step':step,'plan_id':plan_id,'evidence_boundary':'历史素材，不是本轮通过证据'})]+source_materials(step['sources'],ui_results)
                    app.dispatch('context.save_batch',{'step_id':saved['step_id'],'context_id':None,'expected_revision':None,'provider_id':'playwright.page','name':case['key']+' '+str(i)+' 操作要求与证据','context_notes':'保留步骤对应的历史记录和预览；未采集的当前写操作不猜测控件和提交结果。','captures':materials})
                package=app.dispatch('task.export',{'task_id':task['task_id']})
                out=OUTPUT/(case['key']+'.task.json');out.write_text(json.dumps(package,ensure_ascii=False,indent=2)+'\n');out.chmod(0o600)
                if out.stat().st_size>32*1024*1024:
                    receipt['issues'].append({'id':'TW-LOCAL-IMPORT-SIZE','task':case['key'],'bytes':out.stat().st_size,'status':'待本批编写完成后修复','reproduction':'完整含素材的官方导出超过文件导入32MiB上限'})
                receipt['tasks'].append({'key':case['key'],'task_id':task['task_id'],'name':task['name'],'plan_id':plan_id,'steps':len(case['steps']),'coded_steps':compiled,'coded_login_steps':3 if case['key']=='ENV-01' else 0,'coded_readonly_steps':sum(s['kind'] in {'snapshot','snapshot_compare','record','database','environment'} for s in case['steps']),'business_draft_steps':len(case['steps'])-compiled,'context_groups':len(package['contexts']),'captures':sum(len(g['captures']) for g in package['contexts']),'export':str(out),'export_bytes':out.stat().st_size})
            receipt_path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n');receipt_path.chmod(0o600)
    (ROOT/'examples/reinsurance-local-selftest/authoring-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'plans':len(receipt['plans']),'tasks':len(receipt['tasks']),'steps':sum(t['steps'] for t in receipt['tasks']),'coded':sum(t['coded_steps'] for t in receipt['tasks']),'issues':receipt['issues']},ensure_ascii=False))


if __name__=='__main__':main()
