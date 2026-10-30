"""Deterministic generation; no live browser, model or execution of source text."""
import ast
import json
from urllib.parse import urlsplit
from taskweave.plugins.sdk import CodeGeneratorSpec, codegen_digest, MAX_RECORDING_BYTES, MAX_ACTIONS

OPTIONS = {'type':'object','properties': {
    'role': {'type':'string','minLength':1,'maxLength':256},
    'start': {'enum':['continue','open']},
    'url': {'type':'string','maxLength':8192},
    'url_input': {'type':'string','minLength':1,'maxLength':256}}, 'additionalProperties':False}
SPEC = CodeGeneratorSpec('playwright.recording','Playwright',('playwright.page',),
                         ('playwright.recording',),(1,),OPTIONS)


def diagnostic(code, sequence=None):
    messages = {
        'RECORDING_INVALID':'录制格式或完整性证据无效，请在上下文中重新录制。',
        'RECORDING_LEGACY':'此录制缺少本地生成证据，可用于 AI 编写，或重新录制。',
        'RECORDING_INCOMPLETE':'录制存在丢失、暂停或未确认操作，请重新录制连续片段。',
        'RECORDING_UNSUPPORTED':'录制包含暂不支持的操作或无法确认的定位器。',
        'CODEGEN_BINDING_INVALID':'参数绑定无效，或绑定了不存在的录制值。',
        'CODEGEN_VALUE_REQUIRED':'请为录制值选择已有输入或明确保留完整常量。',
        'CODEGEN_ROLE_REQUIRED':'请明确选择执行浏览器角色。',
        'CODEGEN_START_REQUIRED':'请补充可核对的执行起点或完整地址。',
        'RECORDING_NONPRIMARY_PAGE':'这份旧录制来自非主页面，缺少可重放的选页信息。请重新录制所选页面，或使用 AI 编写。',
        'RECORDING_UNSUPPORTED_INTERACTION':'录制包含当前本地生成不支持的交互（例如按键提交、滚动或拖动），不能省略这些动作后生成代码。',
        'RECORDING_DOCUMENT_UNSEALED':'录制发生页面跳转或文档销毁，旧文档的操作未能完整确认。',
        'RECORDING_EXTRA_PAGE':'录制涉及额外页面或弹出窗口，当前本地生成未支持跨页面重放。',
        'RECORDING_FRAME_UNAVAILABLE':'录制时页面或 frame 已不可用，无法确认对应的动作证据。',
        'RECORDING_PAUSED':'录制包含暂停区间，期间的操作没有完整记录，不能确定性重放整段流程。',
        'RECORDING_SOURCE_UNCONFIRMED':'浏览器发送的操作尚未全部确认，录制可能缺少动作。',
        'RECORDING_NOT_STOPPED':'请先在上下文中停止录制并保存，再生成代码。',
    }
    return {'severity':'error','code':code,'message':messages.get(code,code),'sequence':sequence}


def evidence_from_capture(capture):
    if not isinstance(capture, dict) or not isinstance(capture.get('items'),list):
        return None,'RECORDING_INVALID'
    try:
        if len(json.dumps(capture, ensure_ascii=False, allow_nan=False).encode()) > MAX_RECORDING_BYTES:
            return None,'RECORDING_INVALID'
        found=[]
        for item in capture['items']:
            if not isinstance(item,dict) or item.get('truncated'):
                return None,'RECORDING_INCOMPLETE'
            if item.get('source') != 'playwright.recording':
                continue
            data=json.loads(item['content'])
            if not isinstance(data,dict):
                return None,'RECORDING_INVALID'
            if 'codegen' in data:
                if data.get('recording_id') != data['codegen'].get('recording_id'):
                    return None,'RECORDING_INVALID'
                found.append(data['codegen'])
        if not found:
            return None,'RECORDING_LEGACY'
        if any(item != found[0] for item in found):
            return None,'RECORDING_INVALID'
        return found[0],None
    except (ValueError,TypeError,KeyError,AttributeError,RecursionError):
        return None,'RECORDING_INVALID'


def _valid_url(value):
    if not isinstance(value,str) or len(value)>8192:
        return False
    u=urlsplit(value)
    return u.scheme in {'http','https'} and bool(u.hostname) and not u.username and not u.password


def generate(generator_id, recording, bindings, options):
    result={'result_version':1,'converter_version':'1','source':'','body_fragment':'',
            'required_capabilities':[],'input_slots':[],'diagnostics':[],'applicable':False,
            'source_digest':codegen_digest(recording),'action_count':0,'operations':[]}
    def fail(code,sequence=None):
        if len(result['diagnostics'])<100:
            result['diagnostics'].append(diagnostic(code,sequence))
    from jsonschema import Draft202012Validator
    if generator_id != SPEC.id or not isinstance(bindings,dict) or not Draft202012Validator(OPTIONS).is_valid(options):
        fail('CODEGEN_BINDING_INVALID');return result
    evidence,error=evidence_from_capture(recording)
    if error:
        fail(error);return result
    if (evidence.get('schema_version') != 1 or type(evidence.get('schema_version')) is not int
            or not isinstance(evidence.get('recording_id'),str)):
        fail('RECORDING_INVALID');return result
    if evidence.get('state')!='STOPPED':
        fail('RECORDING_NOT_STOPPED')
    if evidence.get('primary') is not True and evidence.get('target_mode')!='selected':
        fail('RECORDING_NONPRIMARY_PAGE')
    issues=evidence.get('issues')
    if isinstance(issues,list):
        for issue in issues:
            code='RECORDING_'+issue if isinstance(issue,str) and issue in {
                'NONPRIMARY_PAGE','UNSUPPORTED_INTERACTION','DOCUMENT_UNSEALED','EXTRA_PAGE',
                'FRAME_UNAVAILABLE','PAUSED','SOURCE_UNCONFIRMED'} else 'RECORDING_INCOMPLETE'
            if not any(d['code']==code for d in result['diagnostics']):fail(code)
    if result['diagnostics'] or evidence.get('complete') is not True or issues!=[]:
        if not result['diagnostics']:fail('RECORDING_INCOMPLETE')
        return result
    documents=evidence.get('documents')
    if not isinstance(documents,list) or not documents:
        fail('RECORDING_INVALID');return result
    document_ids=set()
    for d in documents:
        if (not isinstance(d,dict) or not isinstance(d.get('document_id'),str) or d['document_id'] in document_ids
                or type(d.get('sent')) is not int or d['sent']<0 or type(d.get('acknowledged')) is not int
                or d['sent']!=d['acknowledged'] or d.get('sealed') is not True):
            fail('RECORDING_INCOMPLETE');return result
        document_ids.add(d['document_id'])
    actions=evidence.get('actions')
    if not isinstance(actions,list) or not 1<=len(actions)<=MAX_ACTIONS:
        fail('RECORDING_INVALID');return result
    result['action_count'] = len(actions)
    role=options.get('role',evidence.get('role'))
    if not isinstance(role,str) or not role.strip() or len(role)>256:
        fail('CODEGEN_ROLE_REQUIRED');return result
    calls=[];slot_ids=set();prefix=[]
    result['target_mode']=evidence.get('target_mode','primary')
    if evidence.get('target_mode')=='selected':
        url=evidence.get('start_url')
        if not _valid_url(url):
            fail('CODEGEN_START_REQUIRED');return result
        u=urlsplit(url)
        base=f'{u.scheme}://{u.netloc}{u.path or "/"}'
        if any(c in base for c in '*{}[]\\'):
            fail('CODEGEN_START_REQUIRED');return result
        # Runtime target IDs belong to that runtime only. Resolve the saved
        # page identity and require an unambiguous match before any writes.
        prefix=ast.parse(
            f"recording_pages = await ctx.call('playwright.page_targets', {{'role': {role!r}}})\n"
            "if recording_pages['truncated']:\n"
            "    raise ValueError('页面列表不完整，无法唯一定位录制页面')\n"
            f"recording_matches = [recording_page['target_id'] for recording_page in recording_pages['targets'] if recording_page['url'] == {base!r}]\n"
            "if len(recording_matches) != 1:\n"
            "    raise ValueError('请在该角色会话中准备唯一匹配的录制页面，再执行步骤')\n"
            "recording_target = recording_matches[0]\n"
        ).body
        result['value_references']={'recording_target':{'type':'string'}}
    if options.get('start','continue')=='open':
        if 'url_input' in options:
            url_node=ast.Subscript(ast.Name('inputs',ast.Load()),ast.Constant(options['url_input']),ast.Load())
        elif _valid_url(options.get('url')):
            url_node=ast.Constant(options['url'])
        else:
            fail('CODEGEN_START_REQUIRED');return result
        calls.append(('playwright.page_open',{'url':url_node,'role':role}))
    else:
        url=evidence.get('start_url')
        if not _valid_url(url):
            fail('CODEGEN_START_REQUIRED');return result
        u=urlsplit(url)
        base=f'{u.scheme}://{u.netloc}{u.path or "/"}'
        if any(c in base for c in '*{}[]\\'):
            fail('CODEGEN_START_REQUIRED');return result
        calls.append(('playwright.page_assert_url',{'url':base+'{,?**,#**}','role':role}))
    # Validate the same locator schema used by fixed execution, without using a browser.
    from .schemas import LOCATOR
    locator_validator=Draft202012Validator({'$defs':{'locator':LOCATOR},**LOCATOR})
    for seq, action in enumerate(actions,1):
        if not isinstance(action,dict):
            fail('RECORDING_INVALID',seq);continue
        operation=action.get('operation');selector=action.get('selector')
        result['operations'].append({'sequence':seq,'label':{
            'fill':'填写控件','click':'点击控件','select':'选择选项','check':'设置勾选状态'
        }.get(operation,'未支持操作')})
        if (type(action.get('sequence')) is not int or action['sequence']!=seq
                or action.get('document_id') not in document_ids or action.get('verified') is not True
                or not locator_validator.is_valid(selector)):
            fail('RECORDING_UNSUPPORTED',seq);continue
        params={'selector':selector,'role':role}
        if operation in {'fill','select'}:
            sid=f'action:{seq}:value';slot_ids.add(sid)
            state=action.get('value_state','missing')
            if state not in {'complete','missing','redacted','truncated'}:
                fail('RECORDING_INVALID',seq);continue
            result['input_slots'].append({'id':sid,'sequence':seq,'parameter':'value','type':'string',
                'value_state':state,'allow_constant':state=='complete','label':f'操作 {seq} 的输入值','masked_value':'••••••'})
            binding=bindings.get(sid)
            value=None
            if isinstance(binding,dict) and set(binding)=={'input'} and isinstance(binding['input'],str) and binding['input'].strip():
                value=ast.Subscript(ast.Name('inputs',ast.Load()),ast.Constant(binding['input']),ast.Load())
            elif binding=={'constant':True} and state=='complete' and isinstance(action.get('value'),str):
                value=action['value']
            elif isinstance(binding,dict) and set(binding)=={'value'} and isinstance(binding['value'],str) and state!='redacted':
                value=binding['value']
            else:
                fail('CODEGEN_VALUE_REQUIRED',seq);continue
            params['value' if operation=='fill' else 'option']=value if operation=='fill' else {'value':value}
            name='page_fill' if operation=='fill' else 'page_select_option'
        elif operation=='click':
            name='page_click'
        elif operation=='check' and type(action.get('checked')) is bool:
            params['checked']=action['checked'];name='page_check'
        else:
            fail('RECORDING_UNSUPPORTED',seq);continue
        calls.append(('playwright.'+name,params))
    if set(bindings)-slot_ids:
        fail('CODEGEN_BINDING_INVALID')
    if result['diagnostics']:
        return result
    if prefix:
        for _,params in calls:
            params['target_id']=ast.Name('recording_target',ast.Load())
    def node(value):
        if isinstance(value,ast.AST): return value
        if isinstance(value,dict): return ast.Dict([ast.Constant(k) for k in value],[node(v) for v in value.values()])
        if isinstance(value,list): return ast.List([node(v) for v in value],ast.Load())
        return ast.Constant(value)
    statements=prefix+[ast.Expr(ast.Await(ast.Call(ast.Attribute(ast.Name('ctx',ast.Load()),'call',ast.Load()),
                  [ast.Constant(name),node(params)],[]))) for name,params in calls]
    result['body_fragment']='\n'.join(ast.unparse(ast.fix_missing_locations(s)) for s in statements)
    result['source']='async def run(ctx, inputs):\n'+''.join('    '+s+'\n' for s in result['body_fragment'].splitlines())+'    return ctx.result(data=inputs)\n'
    result['required_capabilities']=sorted({name for name,_ in calls}|({'playwright.page_targets'} if prefix else set()))
    result['applicable']=True
    return result
