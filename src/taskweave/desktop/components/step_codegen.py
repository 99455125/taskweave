"""Local generation uses the same saved recordings as AI authoring."""
from copy import deepcopy
import json
from nicegui import ui
from taskweave.core.validation import TaskError


class StepCodeGenerator:
    def __init__(self, flow, controller, host, preview_host, code_control, *, step_id,
                 document, current, changed, show_contexts):
        self.flow,self.controller,self.host=flow,controller,host
        self.preview_host,self.code=preview_host,code_control
        self.step_id,self.document,self.current=step_id,document,current
        self.changed,self.show_contexts=changed,show_contexts
        self.error='';self.previewing=False;self.refreshing=False
        ui.add_css('.tw-local-codegen pre, .tw-codegen-full-preview pre { white-space:pre-wrap; overflow-wrap:anywhere; }')

    async def open(self):
        if await self.flow.load(self.step_id,self.document()) and self.current():
            self.hide_preview()
            self.render()

    async def refresh(self):
        if self.refreshing:
            return
        self.refreshing=True
        self.render()
        try:
            if await self.flow.load(self.step_id,self.document()) and self.current():
                self.error=''
                self.hide_preview()
                ui.notify(f'上下文已刷新，可用录制 {len(self.flow.sources)} 条。')
        except TaskError as exc:
            self.error=str(exc)
        finally:
            self.refreshing=False
            if self.current():self.render()

    async def generate(self):
        self.error=''
        try:
            accepted=await self.flow.generate(self.step_id,self.document())
            if accepted and self.current():
                self.hide_preview()
                self.render()
        except TaskError as exc:
            self.error=str(exc)
            self.flow.result=None
            self.hide_preview()
            if self.current():self.render()

    def hide_preview(self):
        if self.previewing:
            self.previewing=False
            if not self.preview_host.is_deleted:self.preview_host.clear();self.preview_host.set_visibility(False)
            if not self.code.is_deleted:self.code.set_visibility(True)

    def preview(self):
        self.flow.check(self.document());self.preview_host.clear()
        with self.preview_host:
            with ui.row().classes('w-full items-center justify-between'):
                ui.label('生成候选 · 只读预览').classes('font-semibold')
                ui.button('返回当前代码',on_click=self.hide_preview).props('flat dense')
            ui.code(self.flow.result['source'],language='python').classes('w-full tw-codegen-full-preview')
        self.code.set_visibility(False);self.preview_host.set_visibility(True);self.previewing=True

    async def apply(self,mode,*,confirmed=False):
        doc=self.document();self.flow.check(doc)
        if mode=='replace' and not confirmed:
            with ui.dialog() as dialog,ui.card().classes('tw-confirm-dialog w-full max-w-5xl'):
                ui.label('替换步骤代码').classes('text-lg font-semibold')
                ui.code(self.flow.diff(doc),language='diff').classes('w-full')
                async def accept():
                    try:await self.apply('replace',confirmed=True)
                    except TaskError as exc:ui.notify(str(exc),type='negative');return
                    dialog.close()
                with ui.row().classes('w-full justify-end gap-2'):
                    ui.button('保留当前代码',on_click=dialog.close).props('outline')
                    ui.button('确认替换',on_click=accept).props('color=primary')
            dialog.open();return
        position=None
        if mode=='insert':
            cursor=await ui.run_javascript(f'''return (()=>{{
                const view=getElement({self.code.id})?.editor;if(!view)return null;
                const source=view.state.doc.toString();return {{source,position:Array.from(source.slice(0,view.state.selection.main.head)).length}};
            }})()''')
            if not self.current():return
            if not cursor or cursor.get('source')!=doc['step_content']:
                raise TaskError('EDIT_CONFLICT','代码正在变化，请重新定位光标。')
            position=cursor['position']
        source=await self.flow.apply(self.step_id,doc,mode,position)
        if not self.current():return
        self.flow.check(self.document())
        candidate={**doc,'step_content':source}
        diagnostics=await self.controller.validate_step_candidate(candidate)
        if not self.current():return
        self.flow.check(self.document())
        if any(d.get('severity','error')=='error' for d in diagnostics):
            raise TaskError('CODEGEN_VALIDATION_FAILED','合并后的步骤未通过校验，请调整后再应用。')
        self.hide_preview();self.code.set_value(source);self.changed()
        ui.notify('已应用到草稿，待保存与调试。源上下文保持不变。')

    def invalidate(self):
        if self.flow.result:self.flow.result['applicable']=False
        self.hide_preview()

    def render(self):
        self.host.clear()
        with self.host:
            selected_source = next((s for s in self.flow.sources if s['capture_id']==self.flow.selected), {})
            ui.label(selected_source.get('generator_name', '插件')+' · 本地生成').classes('text-xs text-gray-500')
            ui.label('① 选择上下文 → ② 预览代码 → ③ 应用草稿').classes('text-xs text-gray-500')
            choices={s['capture_id']:s['name'] for s in self.flow.sources}
            with ui.row().classes('w-full items-center gap-2 flex-nowrap'):
                selection=ui.select(choices,label='录制上下文',value=self.flow.selected).props('outlined dense').classes('flex-1 min-w-0')
                ui.button('刷新上下文',icon='refresh',on_click=self.refresh).props('outline dense no-caps').classes('shrink-0').set_enabled(not self.refreshing)
            def select(event):
                self.flow.select(event.value);self.hide_preview();self.render()
            selection.on_value_change(select)
            with ui.row().classes('w-full items-center gap-2'):
                ui.button('生成代码',on_click=self.generate).props('color=primary').set_enabled(bool(choices) and not self.flow.busy)
                ui.button('查看上下文',on_click=self.show_contexts).props('flat dense')
            if not choices:ui.label('请先在上下文中录制并保存。').classes('text-sm text-gray-500')
            if self.error:ui.label(self.error).classes('text-sm text-red-700')
            result=self.flow.result
            if result:
                applicable=result['applicable'] and bool(result.get('source'))
                if applicable:
                    ui.label('静态校验通过 · 待调试').classes('text-sm font-semibold')
                    ui.label('未自动添加业务断言。').classes('text-xs text-gray-500')
                else:
                    ui.label('未生成可用代码').classes('tw-codegen-error text-sm font-semibold text-red-700')
                    for d in result['diagnostics']:
                        ui.label((f"操作 {d['sequence']}：" if d.get('sequence') else '')+d['message']).classes('tw-codegen-error text-sm')
                    if not result['diagnostics']:
                        ui.label('参数已变化，请点击“生成代码”重新生成。').classes('tw-codegen-error text-sm')
                panels={}
                def show_result(name):
                    for key,panel in panels.items():panel.set_visibility(key==name)
                with ui.row().classes('w-full gap-1 flex-wrap'):
                    for key,label in [('code','TaskWeave 代码'),('events','录制动作'),('issues','转换问题')]:
                        ui.button(label,on_click=lambda _,key=key:show_result(key)).props('flat dense size=sm no-caps')
                for key in ('code','events','issues'):
                    panels[key]=ui.column().classes('w-full gap-2')
                    panels[key].set_visibility(key==('code' if applicable else 'issues'))
                with panels['code']:
                    if applicable:
                        ui.code(result['source'],language='python').classes('tw-codegen-source w-full')
                        ui.button('在左侧预览',on_click=self.preview).props('flat dense')
                    else:
                        ui.label('当前没有可预览或应用的代码。请先处理上述问题，原步骤代码保持不变。').classes('text-sm text-gray-500')
                with panels['events']:
                    ui.label('来源：'+choices.get(self.flow.selected,''))
                    for operation in result.get('operations',[]):
                        ui.label(f"{operation['sequence']}. {operation['label']}").classes('text-sm')
                    for slot in result['input_slots']:
                        ui.label(slot['label']+' · '+slot.get('masked_value','••••••')).classes('text-sm')
                with panels['issues']:
                    if not result['diagnostics']:ui.label('转换问题：0')
                    for d in result['diagnostics']:
                        ui.label((f"操作 {d['sequence']}：" if d.get('sequence') else '')+d['message']).classes('text-sm')
                for warning in result.get('warnings',[]):ui.label(warning).classes('text-xs text-amber-700')
                if result['input_slots']:
                    ui.separator();ui.label('参数补充').classes('font-semibold')
                    properties=self.document()['input_schema'].get('properties',{})
                    for slot in result['input_slots']:
                        sid=slot['id'];values={'':'请选择使用方式'}
                        values.update({'input:'+k:'绑定已有输入：'+k for k,s in properties.items() if s.get('type')=='string'})
                        if slot['allow_constant']:values['constant']='保留为代码常量'
                        if slot.get('value_state')!='redacted':values['manual']='补充常量值'
                        binding=self.flow.bindings.get(sid,{})
                        selected=('input:'+binding['input'] if 'input' in binding else 'constant' if binding.get('constant') else 'manual' if 'value' in binding else '')
                        field=ui.select(values,value=selected,label=slot['label']+' · ••••••').props('outlined dense').classes('w-full')
                        def bind(event,sid=sid):
                            value=event.value or ''
                            self.flow.bindings[sid]=({'input':value[6:]} if value.startswith('input:') else {'constant':True} if value=='constant' else {'value':''} if value=='manual' else {})
                            self.invalidate();self.render()
                        field.on_value_change(bind)
                        if selected=='manual':
                            manual=ui.input('补充值',value=binding.get('value','')).props('outlined dense').classes('w-full')
                            manual.on_value_change(lambda event,sid=sid:(self.flow.bindings.update({sid:{'value':event.value}}),self.invalidate()))
                    ui.label('录制常量将随步骤保存。修改参数后点击“生成代码”更新候选。').classes('text-xs text-gray-500')
                with ui.expansion('执行起点与角色',icon='tune').classes('w-full'):
                    if result.get('target_mode') == 'selected':
                        ui.label('先唯一定位录制时所选页面；“打开地址”也仅在该页面导航，不替换会话主页面。').classes('text-xs text-gray-500')
                    role=ui.input('浏览器角色（留空沿用录制）',value=self.flow.options.get('role','')).props('outlined dense').classes('w-full')
                    def role_changed(event):
                        if event.value:self.flow.options['role']=event.value
                        else:self.flow.options.pop('role',None)
                        self.invalidate()
                    role.on_value_change(role_changed)
                    start=ui.select({'continue':'继续已有页面','open':'先打开指定地址'},value=self.flow.options.get('start','continue'),label='执行起点').props('outlined dense').classes('w-full')
                    start.on_value_change(lambda event:(self.flow.options.update(start=event.value),self.invalidate(),self.render()))
                    if self.flow.options.get('start')=='open':
                        url=ui.input('完整地址（或下方绑定已有输入）',value=self.flow.options.get('url','')).props('outlined dense').classes('w-full')
                        url.on_value_change(lambda event:(self.flow.options.update(url=event.value),self.invalidate()))
                        values={'':'不绑定'};values.update({k:k for k,s in self.document()['input_schema'].get('properties',{}).items() if s.get('type')=='string'})
                        url_input=ui.select(values,value=self.flow.options.get('url_input',''),label='地址输入').props('outlined dense').classes('w-full')
                        def bind_url(event):
                            if event.value:self.flow.options['url_input']=event.value
                            else:self.flow.options.pop('url_input',None)
                            self.invalidate()
                        url_input.on_value_change(bind_url)
                with ui.row().classes('w-full gap-2'):
                    ui.button('插入光标处',on_click=lambda:self.apply('insert')).props('color=primary').set_enabled(result['applicable'])
                    ui.button('替换步骤代码',on_click=lambda:self.apply('replace')).props('outline').set_enabled(result['applicable'])
