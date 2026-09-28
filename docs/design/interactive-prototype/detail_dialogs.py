"""Detailed design flows with disposable, in-memory sample state only."""
from copy import deepcopy
from nicegui import ui
from widgets import box, text, button, tag, status, table, message, demo_action, go, TASKS, STEPS


class DetailDialogs:
    def __init__(self):
        self.contexts = {}

    def panel(self, title, wide=False):
        dialog = ui.dialog().props('persistent')
        with dialog:
            card = ui.card().classes('dialog-body' + (' wide-dialog' if wide else ''))
        with card:
            with box('section-head w-full'):
                text(title, 'h2')
                button('关闭', dialog.close, 'close', 'ghost small')
            text('交互原型 · 所有提交仅演示，不调用业务服务', 'muted mb-3')
        return dialog, card

    def confirm(self, title, explanation):
        d, c = self.panel(title)
        with c:
            text(explanation, 'description')
            with box('actions mt-4'):
                button('取消', d.close)
                button('确认 · 演示', lambda: (d.close(), ui.notify('已演示确认，未修改业务数据')), style='danger')
        d.open()

    def field(self, name, value=''):
        return ui.input(name, value=value).props('outlined dense').classes('w-full')

    def schema(self):
        d, c = self.panel('变量定义', True)
        with c:
            text('用于任务变量或步骤输入；保留类型、必填、默认值、说明及枚举。', 'hint w-full')
            with box('form-grid w-full'):
                self.field('变量名称', 'policy_no')
                ui.select(['string', 'integer', 'number', 'boolean', 'object', 'array', 'null'], value='string', label='类型').props('outlined dense')
                self.field('默认值（对象 / 数组使用 JSON）')
                self.field('说明', '需要查询的保单号')
            ui.checkbox('必填', value=True)
            text('已有 schema 的枚举约束需保留，运行输入按枚举渲染选择控件。', 'muted')
            with box('actions wrap'):
                button('添加变量', lambda: ui.notify('演示：新增一条变量定义'))
                button('删除变量', lambda: self.confirm('删除变量？', '正式接入时需检查依赖与任务配置变化。'), style='danger')
                button('保存变量 · 演示', d.close, style='primary')
        d.open()

    def task_config(self, name=''):
        d, c = self.panel('任务配置' if name else '新建任务', True)
        with c:
            self.field('任务名称', name)
            ui.textarea('任务说明', value='描述任务目标、输入及预期结果').props('outlined').classes('w-full')
            table(['变量', '类型', '必填', '说明'], [['policy_no', 'string', '是', '保单号']])
            button('管理任务变量', self.schema, 'tune')
            button('保存任务 · 演示', d.close, style='primary')
        d.open()

    def task_actions(self, name):
        d, c = self.panel('任务操作 · ' + name)
        with c:
            button('任务配置', lambda: self.task_config(name), 'tune')
            button('复制任务', lambda: self.confirm('复制任务？', '创建独立任务；历史运行不复制。'), 'content_copy')
            button('导出任务 JSON', lambda: self.transfer(False), 'file_download')
            button('导入任务', lambda: self.transfer(True), 'file_upload')
            button('清理运行', lambda: self.confirm('清理此任务的运行？', '清理运行记录及结果，保留任务和步骤定义；保留现行在途运行限制。'), 'cleaning_services')
            button('删除任务', lambda: self.confirm('删除任务及其数据？', '包含步骤、上下文及所属运行；保留依赖与活跃资源限制。'), 'delete_outline', 'danger')
        d.open()

    def transfer(self, importing):
        d, c = self.panel('导入任务' if importing else '导出任务', True)
        with c:
            ui.textarea('任务包 JSON', value='{"format": "示例，仅展示导入导出区域", "task": {"name": "查询保单"}}').props('outlined').classes('w-full')
            if importing:
                text('按现行任务包校验；导入为独立新任务，不覆盖已有任务。', 'hint')
                button('导入为新任务 · 演示', d.close, style='primary')
            else:
                with box('actions'):
                    button('复制 JSON', lambda: ui.notify('原型未写入剪贴板'))
                    button('下载 JSON', lambda: ui.notify('原型未下载任务包'))
        d.open()

    def inputs(self):
        for title in ['环境变量 · 只读', '任务变量 · 本次运行输入', '步骤变量与依赖 · 本次步骤输入']:
            with ui.expansion(title, value=title.startswith('任务变量')).classes('w-full border rounded-lg'):
                if title.startswith('环境'):
                    table(['变量', '值', '来源'], [['login_url', 'https://example.test/login', '环境'], ['org_code', 'DEMO_ORG', '环境']])
                else:
                    self.field('policy_no' if title.startswith('任务') else 'captcha')
                    text('展示变量来源与被覆盖提示；实际合并优先级沿用现有核心规则。', 'muted')
                    if title.startswith('步骤'):
                        text('前序结果依赖在单步调试时填写实际值；连续调试由本次结果传递。', 'muted')

    def new_run(self, name=None):
        d, c = self.panel('新建执行', True)
        with c:
            ui.select([x[0] for x in TASKS], value=name if name in [x[0] for x in TASKS] else TASKS[0][0], label='任务').props('outlined dense').classes('w-full')
            ui.select(['uat', 'test'], value='uat', label='运行环境').props('outlined dense').classes('w-full')
            ui.select(STEPS, value=STEPS[0], label='开始步骤').props('outlined dense').classes('w-full')
            self.inputs()
            text('正式运行前保留现有步骤确认、起点与输入校验；不能因有按钮就跳过验证。', 'hint')
            button('创建并执行 · 演示', d.close, 'play_arrow', 'primary')
        d.open()

    def debug_panel(self, step, close):
        with box('panel debug'):
            with box('section-head'):
                text('步骤调试', 'h2')
                button('收起', close, 'close', 'ghost small')
            ui.select(['uat 环境', 'test 环境'], value='uat 环境', label='运行环境').props('outlined dense').classes('w-full')
            with ui.expansion('环境与本次输入', icon='tune').classes('w-full mt-3'):
                self.inputs()
            text('操作', 'field-label')
            button('调试当前步骤', lambda: self.single_trial(step), 'play_arrow', 'primary w-full')
            button('从选定步骤调试', lambda: self.flow_trial(step), 'playlist_play', 'w-full mt-2')
            button('结束调试', lambda: self.confirm('结束当前调试？', '释放当前调试资源，保留运行记录；可用性由 can_end 决定。'), 'stop', 'w-full mt-2')
            text('同环境有存活会话时可继续使用；切换环境或外部结果不确定时保留现有确认流程。', 'muted mt-3')
            with box('debug-result'):
                status('失败')
                text('最近尝试 · 1 · 示例', 'muted mt-2')
                text('元素暂不可见', 'h3 mt-2')
                button('查看结果', self.result, 'visibility', 'small mt-2')
                button('打开失败步骤', lambda: message('切换到失败步骤', '连续调试若停在其他步骤，跳到该步骤并保留本轮修复上下文。'), style='small mt-2')
            with ui.expansion('本次报错上下文', icon='error_outline').classes('w-full'):
                text('移除仅影响本轮 AI 请求，不删除运行记录。', 'muted')
                for part in ['本次实际执行内容', '失败动作', '失败快照', '调试日志']:
                    with box('rowline between w-full') as row:
                        text(part, 'muted')
                        button('移除', lambda r=row: r.set_visibility(False), style='ghost small')
            with ui.expansion('尝试与调试日志', icon='terminal').classes('w-full'):
                table(['步骤', '尝试', '状态'], [[STEPS[step], '1', '失败']])
                ui.code('[ERROR] ELEMENT_NOT_VISIBLE\n[INFO] 浏览器会话保留', language='text').classes('w-full')
            ui.textarea('本轮 AI 补充说明', placeholder='例如：点击后会打开新的标签页').props('outlined autogrow').classes('w-full mt-3')
            button('AI 修复', lambda: self.ai('修复步骤'), 'auto_awesome', 'primary w-full mt-2')
            button('清空 AI 修复上下文', lambda: self.confirm('清空 AI 修复上下文？', '只重置 AI 修复对话与补充说明，调试实例、插件资源及运行记录继续保留。'), style='ghost small w-full mt-2')
            button('补充必录参数', self.pending_input, 'edit_note', 'small w-full mt-2')

    def single_trial(self, step):
        d, c = self.panel('调试当前步骤', True)
        with c:
            text(f'仅执行：{step + 1}. {STEPS[step]}', 'h3')
            self.inputs()
            ui.checkbox('演示上次结果不确定的状态', on_change=lambda e: warning.set_visibility(e.value))
            warning = text('先检查当前页面；再次执行可能重复点击或提交。调试保留会话的确认例外不扩展到正式执行。', 'hint amber')
            warning.set_visibility(False)
            button('开始调试 · 演示', d.close, style='primary')
        d.open()

    def flow_trial(self, step):
        d, c = self.panel('从选定步骤调试到当前步骤')
        with c:
            ui.select(STEPS[:step + 1], value=STEPS[0], label='开始步骤').props('outlined dense').classes('w-full')
            text(f'结束于当前步骤：{step + 1}. {STEPS[step]}', 'h3')
            text('起点只能选择当前步骤及其前面的步骤；不是从选定步骤一直执行到任务末尾。默认从第一步开始。', 'hint')
            button('开始调试 · 演示', d.close, style='primary')
        d.open()

    def lint(self):
        d, c = self.panel('内容校验')
        with c:
            status('成功')
            table(['检查', '示例结果'], [['语法', '通过'], ['插件能力', '通过'], ['输入依赖', '通过']])
            text('校验通过不等于业务已执行成功，也不等于已确认步骤。', 'hint')
        d.open()

    def confirm_step(self):
        d, c = self.panel('确认验证并保存')
        with c:
            text('优先使用与当前内容匹配的调试证据；证据无效或不存在时，沿用明确的手动确认。', 'description')
            text('当前示例没有真实调试证据，需手动确认。', 'hint amber')
            button('确认验证通过并保存 · 演示', d.close, style='primary')
        d.open()

    def step_actions(self):
        d, c = self.panel('步骤管理')
        with c:
            for label in ['添加步骤', '上移', '下移']:
                button(label, lambda l=label: ui.notify(l + '：演示入口'))
            button('删除当前步骤', lambda: self.confirm('删除当前步骤？', '其他步骤引用此步骤时阻止删除。'), style='danger')
            button('一键确认全部步骤', lambda: self.confirm('确认全部步骤', '逐步校验；发现不通过项先定位到该步骤，不能跳过失败校验。'))
        d.open()

    def action_form(self):
        d, c = self.panel('插件动作表单', True)
        with c:
            ui.select(['playwright.page_open', 'playwright.page_inspect', 'ocr.recognize'], value='playwright.page_open', label='插件动作').props('outlined dense').classes('w-full')
            self.field('url', 'https://example.test/login')
            ui.code('await ctx.call("playwright.page_open", {"url": inputs["login_url"]})', language='python').classes('w-full')
            text('表单按动作 input_schema 渲染；插入步骤内容后仍需校验与调试。', 'hint')
            button('插入到步骤内容 · 演示', d.close, style='primary')
        d.open()

    def bindings(self):
        d, c = self.panel('步骤变量与输入依赖', True)
        with c:
            self.field('步骤输入名称', 'captcha')
            ui.select(['固定值', '前序结果', '任务参数', '环境配置'], value='前序结果', label='来源').props('outlined dense').classes('w-full')
            ui.select(STEPS[:3], value=STEPS[2], label='前序步骤（只能引用前序）').props('outlined dense').classes('w-full')
            self.field('固定值（文本或 JSON）')
            self.field('结果容器', 'data')
            self.field('结果字段 / JSON Pointer', '/text')
            text('示例值来自最近成功运行；正式执行仍从本次运行读取有效前序输出。没有历史结果也可手动输入字段路径。', 'hint')
            with box('actions wrap'):
                button('添加绑定', lambda: ui.notify('演示：增加依赖绑定'))
                button('移除此绑定', lambda: self.confirm('移除绑定？', '只移除此输入的引用关系。'), style='danger')
                button('保存依赖 · 演示', d.close, style='primary')
        d.open()

    def timing(self, step=0):
        d, c = self.panel('时间设置')
        with c:
            ui.number('上一步成功后等待（秒）', value=0, min=0, max=86400).props('outlined').classes('w-full').set_enabled(step > 0)
            text('首步骤此项禁用；单步和继续也遵守间隔，已等待足够时间则立即执行。', 'muted')
            ui.number('步骤执行超时（秒，不包含间隔）', value=60, min=1, max=3600).props('outlined').classes('w-full')
            button('保存步骤设置 · 演示', d.close, style='primary')
        d.open()

    def ai(self, purpose):
        d, c = self.panel('AI · ' + purpose, True)
        with c:
            text('选择渠道，生成候选后预览差异，再采纳。', 'hint')
            if purpose == '修复步骤':
                ui.select(['全部历史', '不带历史'] + [f'最近 {i} 轮' for i in range(1, 11)], value='全部历史', label='本轮携带的历史会话').props('outlined dense').classes('w-full')
                ui.checkbox('精简重复静态字段', value=True)
                ui.textarea('本轮补充说明').props('outlined').classes('w-full')
                text('依据当前步骤的实际执行内容、失败动作、快照和日志；遵守移除项与脱敏设置。', 'muted')
            with box('actions wrap'):
                button('大模型api调用', lambda: self.candidate(purpose), 'auto_awesome', 'primary')
                button('大模型网页chat调用', lambda: self.chat(purpose), 'forum')
        d.open()

    def chat(self, purpose):
        d, c = self.panel('大模型网页chat调用 · ' + purpose, True)
        with c:
            text('请求大小：12 KB / 2048 KB · 示例；超限时提示，不静默丢弃选中历史。', 'hint')
            ui.textarea('完整提示词', value='【示例】当前目标、插件契约、上下文证据和用户选择的历史内容…').props('outlined readonly').classes('w-full')
            with box('actions'):
                button('复制提示词', lambda: ui.notify('原型不写入剪贴板'))
                button('下载提示词', lambda: ui.notify('原型不下载文件'))
            ui.textarea('粘贴网页回复 JSON').props('outlined').classes('w-full')
            button('解析并预览', lambda: self.candidate(purpose), style='primary')
        d.open()

    def import_candidate(self):
        d, c = self.panel('导入为任务')
        with c:
            text('使用所选生成记录的候选和冻结上下文；导入后保留预览，可再次发起导入。', 'description')
            text('每次确认导入都创建独立新任务，不覆盖之前导入的任务；沿用本次生成的冻结上下文。本原型不写入任务。', 'hint amber')
            button('确认导入 · 演示', lambda: (d.close(), ui.notify('已演示创建独立新任务，候选仍保留')), style='primary')
        d.open()

    def candidate(self, purpose):
        d, c = self.panel('候选预览 · ' + purpose, True)
        with c:
            text('未采纳 · 不会自动运行', 'badge amber')
            if purpose == '生成任务':
                text('1 个任务 · 7 个步骤', 'h2')
                for i, name in enumerate(STEPS):
                    with ui.expansion(f'{i + 1}. {name} · ' + ('待编写' if i > 4 else '已编写')).classes('w-full'):
                        text('关联上下文：登录页面组 · 来自本次生成的冻结快照', 'muted')
                        ui.code('async def run(ctx, inputs):\n    return ctx.result(data=inputs)', language='python').classes('w-full')
                button('导入为任务', self.import_candidate, style='primary')
            else:
                with box('form-grid w-full'):
                    ui.textarea('当前内容', value='当前步骤描述 / 代码').props('outlined readonly')
                    ui.textarea('候选内容', value='生成或修复后的步骤描述 / 代码').props('outlined readonly')
                button('采纳步骤描述 · 演示' if purpose == '生成步骤描述' else '采纳到编辑器 · 演示', d.close, style='primary')
            button('预览校验失败状态', lambda: message('候选校验未通过', '显示结构/能力校验诊断，阻止采纳或导入，保留原草稿。'), style='ghost')
            button('舍弃', d.close)
        d.open()

    def _groups(self, owner):
        return self.contexts.setdefault(owner, [dict(name='登录页面与导航', notes='用于确认登录入口及后续导航位置', provider='playwright.page', items=['登录页面', '业务首页']), dict(name='业务规则说明', notes='用于补充业务约束', provider='tidb', items=['字段说明'])])

    @ui.refreshable
    def context_summary(self, owner='步骤', identity=''):
        scope = f'{owner}:{identity}' if identity else owner
        with box('context-block w-full mt-4'):
            with box('section-head'):
                text('上下文素材', 'h2')
                button('采集上下文', lambda: self.collect(scope), 'add', 'small')
            text('按组顺序与组内采集项顺序组织 AI 证据；预览仅供用户查看。', 'muted mb-3')
            groups = self._groups(scope)
            for idx, group in enumerate(groups):
                with box('context-group'):
                    with box('rowline between wrap'):
                        with box('rowline'):
                            text(str(idx + 1), 'num')
                            text(group['name'], 'h3')
                            tag(group['provider'], 'blue')
                        with box('actions wrap'):
                            button('编辑 / 继续采集', lambda g=group: self.collect(scope, g), style='small')
                            button('↑', lambda i=idx: self.move_group(scope, i, -1), style='small').set_enabled(idx > 0)
                            button('↓', lambda i=idx: self.move_group(scope, i, 1), style='small').set_enabled(idx + 1 < len(groups))
                            button('删除', lambda g=group: self.delete_group(scope, g), style='small danger')
                    text(group['notes'], 'muted mt-2')
                    for j, name in enumerate(group['items']):
                        with box('rowline between capture-summary'):
                            with box('stack'):
                                text(f'{j + 1}. {name}', 'h3')
                                text('来源：' + owner + ' · 今天 10:20 · 已保存', 'muted')
                            button('内容 / 预览', lambda n=name: self.context_preview(n), 'visibility', 'ghost small')
            if not groups:
                text('暂无上下文组，可采集一组材料。', 'empty')

    def move_group(self, owner, index, delta):
        groups = self._groups(owner)
        other = index + delta
        if 0 <= other < len(groups):
            groups[index], groups[other] = groups[other], groups[index]
        self.context_summary.refresh()

    def delete_group(self, owner, group):
        d, c = self.panel('删除上下文组？')
        with c:
            text('删除组及其采集项。步骤上下文变更会使原确认失效。', 'hint amber')
            def apply():
                self._groups(owner).remove(group)
                d.close()
                self.context_summary.refresh()
            button('确认删除示例组', apply, style='danger')
        d.open()

    def context_preview(self, name):
        d, c = self.panel('采集内容 · ' + name, True)
        with c:
            with ui.tabs() as tabs:
                evidence = ui.tab('AI 证据')
                preview = ui.tab('用户预览')
                meta = ui.tab('采集信息')
            with ui.tab_panels(tabs, value=evidence).classes('w-full'):
                with ui.tab_panel(evidence):
                    ui.code('{"source":"示例页面","items":[{"text":"登录入口与输入框"}]}', language='json').classes('w-full')
                with ui.tab_panel(preview):
                    text('预览按 renderer 展示图片、表格或 JSON；预览不会自动成为发给 AI 的证据。', 'hint')
                    table(['元素', '内容'], [['标题', '业务登录'], ['输入', '组织代码 / 验证码']])
                with ui.tab_panel(meta):
                    table(['字段', '示例'], [['采集时间', '今天 10:20'], ['来源页面', '当前步骤'], ['会话', '独立观察'], ['请求', 'target_id=demo-tab']])
        d.open()

    def collect(self, owner='步骤', existing=None):
        initial = deepcopy(existing or dict(name='新上下文组', notes='', provider='playwright.page', items=[]))
        staged = deepcopy(initial['items'])
        deleted = []
        d = ui.dialog().props('persistent')
        with d, ui.card().classes('wide-dialog dialog-body'):
            text('编辑与采集上下文 · ' + owner.split(':')[0], 'h2')
            text('修改先暂存，确认保存时整组一次提交；取消不写库。', 'hint w-full')
            with box('form-grid w-full'):
                name = self.field('上下文组名称', initial['name'])
                provider = ui.select(['playwright.page', 'ocr', 'tidb'], value=initial['provider'], label='插件采集器').props('outlined dense')
                if existing:
                    provider.disable()
            notes = ui.textarea('操作说明', value=initial['notes']).props('outlined autogrow').classes('w-full')
            with box('form-grid w-full'):
                ui.select(['独立观察', '保留的调试会话', '保留的正式运行会话'] if owner.startswith('步骤') else ['当前规划采集实例'], value='独立观察' if owner.startswith('步骤') else '当前规划采集实例', label='观察会话').props('outlined dense')
                ui.select(['业务登录页 · tab-1', '业务首页 · tab-2', '使用参数指定'], value='业务登录页 · tab-1', label='当前实例已有目标').props('outlined dense')
            button('刷新目标', lambda: ui.notify('演示：仅刷新已有资源，不新开浏览器'), 'refresh', 'small')
            with ui.expansion('采集参数与高级 JSON', icon='tune').classes('w-full'):
                self.field('url / 文件路径 / SQL（按插件 schema 显示）', 'https://example.test/login')
                ui.textarea('高级参数 JSON', value='{}').props('outlined').classes('w-full')
                text('目标会话已变化时拒绝旧请求；支持的预览选项随采集器变化。', 'muted')
            ui.checkbox('同时生成用户预览', value=True)
            area = ui.column().classes('w-full')
            def render():
                area.clear()
                with area:
                    text(f'保留采集项 · {len(staged)}', 'h3')
                    if not staged:
                        text('可继续采集；已有组允许保存为空组。', 'muted')
                    for i, label in enumerate(staged):
                        with box('capture-draft w-full'):
                            control = self.field('采集项标题', label)
                            control.on_value_change(lambda e, j=i: staged.__setitem__(j, e.value))
                            with box('actions wrap'):
                                button('内容 / 预览', lambda n=label: self.context_preview(n), style='small')
                                def move(j, delta):
                                    staged[j], staged[j + delta] = staged[j + delta], staged[j]
                                    render()
                                button('上移', lambda j=i: move(j, -1), style='small').set_enabled(i > 0)
                                button('下移', lambda j=i: move(j, 1), style='small').set_enabled(i + 1 < len(staged))
                                def remove(j):
                                    deleted.append((j, staged.pop(j)))
                                    render()
                                button('删除采集项', lambda j=i: remove(j), style='danger small')
                    for entry in deleted:
                        with box('rowline'):
                            text('待删除：' + entry[1], 'muted')
                            def undo(item):
                                staged.insert(min(item[0], len(staged)), item[1])
                                deleted.remove(item)
                                render()
                            button('撤销删除', lambda item=entry: undo(item), style='small')
            def capture():
                staged.append(f'新采集页面 {len(staged) + 1}')
                render()
                ui.notify('示例项已暂存，尚未保存')
            def save():
                value = dict(name=name.value, notes=notes.value, provider=provider.value, items=list(staged))
                if existing:
                    existing.update(value)
                else:
                    self._groups(owner).append(value)
                d.close()
                self.context_summary.refresh()
                ui.notify('已保存本页示例组；未写入业务数据')
            def cancel():
                dirty = staged != initial['items'] or name.value != initial['name'] or notes.value != initial['notes']
                if not dirty:
                    d.close()
                    return
                confirm, card = self.panel('丢弃本次未保存修改？')
                with card:
                    text('已保存的原组保持不变。外部浏览器操作不会因取消自动回滚。', 'description')
                    button('继续编辑', confirm.close)
                    button('丢弃并关闭', lambda: (confirm.close(), d.close()), style='danger')
                confirm.open()
            render()
            with box('actions wrap'):
                button('采集一项', capture, 'add', 'primary')
                button('模拟采集失败', lambda: ui.notify('采集失败：已有记录和暂存项保留', type='negative'), style='ghost')
            with box('actions wrap'):
                button('取消', cancel)
                button('确认保存', save, 'check', 'primary')
        d.open()

    def run_control(self, step=3):
        d, c = self.panel('执行到指定步骤', True)
        with c:
            text('目标：' + STEPS[min(step, 6)], 'h3')
            ui.select(STEPS[:min(step, 6) + 1], value=STEPS[0], label='重跑开始步骤').props('outlined dense').classes('w-full')
            text('重跑使起点及后续结果失效，保留更早结果和历史尝试。实际可用项由有效尝试、前序条件和外部结果确定。', 'hint amber')
            button('从所选步骤重新执行到此步', lambda: self.confirm('确认重跑范围', '仅在所需前序条件满足后提交重跑。'))
            button('从前面未执行的步骤继续到此步', lambda: self.confirm('继续到指定步骤', '保持原执行实例，遇到缺少输入时进入补录。'))
            button('清理本次结果，从头执行到此步', lambda: self.confirm('从头重跑到指定步骤？', '本次结果失效并重建资源，历史尝试保留。'), style='danger')
        d.open()

    def pending_input(self):
        d, c = self.panel('补充必录参数', True)
        with c:
            tag('等待输入', 'amber')
            self.inputs()
            text('提交后继续原运行；稍后填写保持暂停，不新建执行。', 'hint')
            button('提交输入并继续 · 演示', d.close, style='primary')
            button('稍后填写', d.close)
        d.open()

    def reconcile(self):
        d, c = self.panel('核对外部业务结果')
        with c:
            text('先在业务系统查询，再记录核对结论。', 'hint amber')
            ui.select(['确认已完成', '确认未完成'], label='业务结果').props('outlined dense').classes('w-full')
            ui.textarea('说明（可选）').props('outlined').classes('w-full')
            button('保存核对结果 · 演示', d.close, style='primary')
        d.open()

    def result(self):
        d, c = self.panel('步骤结果', True)
        with c:
            with ui.tabs() as tabs:
                names = [ui.tab(x) for x in ['数据', '表格', '图片', '核对报告', '文件']]
            with ui.tab_panels(tabs, value=names[0]).classes('w-full'):
                with ui.tab_panel(names[0]):
                    ui.code('{"status":"SUCCESS","count":1}', language='json').classes('w-full')
                with ui.tab_panel(names[1]):
                    table(['保单号', '状态'], [['DEMO001', '有效']])
                with ui.tab_panel(names[2]):
                    text('图片预览区域 · 只按实际声明的 image renderer 显示', 'empty')
                with ui.tab_panel(names[3]):
                    status('成功')
                    table(['检查项', '结果'], [['记录数量', '一致']])
                with ui.tab_panel(names[4]):
                    text('report.json · 本地文件引用', 'h3')
                    button('打开文件', lambda: ui.notify('原型不打开真实文件'))
                    button('打开所在目录', lambda: ui.notify('原型不打开真实目录'))
            text('以上页签为各 renderer 的设计示例；正式页面仅展示结果契约实际声明的类型。', 'hint')
        d.open()

    def instances(self):
        d, c = self.panel('执行实例', True)
        with c:
            text('调试、正式运行、规划采集分开标识；关闭页面不会结束实例。', 'hint')
            for name, kind in [('合约备份', '调试'), ('客户导入', '正式运行'), ('登录素材采集', '规划')]:
                with box('rowline between w-full panel pad'):
                    with box('stack'):
                        text(name, 'h3')
                        text(kind + ' · uat · 保留资源', 'muted')
                    button('结束实例', lambda k=kind: self.confirm('结束' + k + '实例？', '只结束所选实例及其资源，保留历史记录。'))
        d.open()

    def logs(self):
        d, c = self.panel('服务实时日志', True)
        with c:
            text('本地服务、AI 请求和后台异常；关闭窗口不会结束任务。', 'hint')
            with box('actions wrap'):
                ui.select(['INFO 及以上', 'WARNING 及以上', 'ERROR'], value='INFO 及以上', label='级别').props('outlined dense')
                ui.switch('暂停显示')
            output = ui.code('[INFO] 服务已启动\n[INFO] 当前没有后台异常', language='text').classes('w-full')
            button('清空显示', lambda: output.set_content(''))
            button('打开日志目录', lambda: ui.notify('原型不打开真实目录'))
            text('日志写入 server.log；清空显示不删除日志文件。', 'muted')
        d.open()

    def history(self):
        d, c = self.panel('历史调试详情', True)
        with c:
            text('执行时任务：合约备份 · 运行快照', 'h3')
            for label in ['尝试 1 · 失败 · 已失效', '尝试 2 · 成功 · 当前有效']:
                with ui.expansion(label).classes('w-full'):
                    ui.code('{"step":"打开登录页面","attempt":"示例"}', language='json').classes('w-full')
                    button('查看结果', self.result)
                    button('查看错误', lambda: message('步骤错误', '显示历史错误，不把当前步骤配置当作当时运行快照。'))
                    button('前往该步骤调试', lambda: go('editor', task=1))
            ui.code('[INFO] 历史事件按运行快照展示', language='text').classes('w-full')
        d.open()

    def categories(self):
        d, c = self.panel('分类管理 · 候选交互')
        with c:
            text('分类已获授权；这里按一级单分类演示，范围与复制分享规则仍待确认。', 'hint amber')
            self.field('分类名称', '保险平台')
            with box('actions wrap'):
                button('新建分类', lambda: ui.notify('演示入口，未新增业务分类'))
                button('重命名', lambda: ui.notify('演示入口，未写入业务分类'))
                button('删除分类', lambda: self.confirm('删除分类？', '建议内容移至未分类，不删除任务；此规则待确认。'), style='danger')
        d.open()
