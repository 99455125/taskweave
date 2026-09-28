"""Planning, plugins, environment, settings and marketplace design views."""
import json
from pathlib import Path
from nicegui import ui
from widgets import box, text, button, tag, table, status, symbol, message


class SecondaryPages:
    def __init__(self, dialogs):
        self.dialogs = dialogs
        self.selected = 0
        self.section = '规划配置'
        self.query = ''
        self.view = ''

    def render(self, view):
        self.view = view
        if view == 'market':
            self.market()
            return
        self.names = {
            'planning': ['再保平台 · 合约录入', '合同详情信息提取', '网页数据采集', '清算回归测试'],
            'plugins': ['playwright', 'ocr', 'tidb', 'utility'],
            'env': ['uat 环境', 'test 环境', 'dev 环境'],
            'settings': ['AI 连接与请求', '脱敏设置', '执行设置', '工作空间'],
        }[view]
        title = {'planning': '规划', 'plugins': '插件', 'env': '环境', 'settings': '设置'}[view]
        with box('workspace'):
            with box('sidebar'):
                with box('sidebar-head'):
                    text(title, 'h2')
                    if view in {'planning', 'env'}:
                        button('新建', lambda: self.new_entry(view), 'add', 'ghost small')
                if view != 'settings':
                    with box('search'):
                        ui.input(placeholder='搜索' + title + '…', on_change=lambda e: self.search(e.value)).props('outlined dense clearable').classes('w-full')
                if view == 'planning':
                    text('收藏 / 分类：范围待确认', 'muted px-2 mb-3')
                self.sidebar()
            with box('detail'):
                self.body()

    def search(self, query):
        self.query = query or ''
        self.sidebar.refresh()

    @ui.refreshable
    def sidebar(self):
        found = False
        for i, name in enumerate(self.names):
            if self.query.casefold() not in name.casefold():
                continue
            found = True
            with box('master-item' + (' selected' if self.selected == i else '')).on('click', lambda j=i: self.select(j)).props('role=button tabindex=0').on('keydown.enter', lambda j=i: self.select(j)):
                text(name, 'master-title')
                if self.view == 'planning':
                    tag('uat', 'blue')
                    text('今天 10:20 更新 · 2 个上下文组', 'muted mt-2')
                elif self.view == 'plugins':
                    tag('已启用' if i < 3 else '未启用', 'green' if i < 3 else '')
                    text('本地插件 · 示例', 'muted mt-2')
                elif self.view == 'env':
                    tag('默认' if i == 0 else '未设为默认', 'green' if i == 0 else '')
        if not found:
            text('没有匹配项', 'empty')

    def select(self, index):
        self.selected = index
        self.sidebar.refresh()
        self.body.refresh()

    def new_entry(self, view):
        d, c = self.dialogs.panel('新建规划' if view == 'planning' else '新建环境')
        with c:
            self.dialogs.field('名称')
            button('创建 · 演示', d.close, style='primary')
        d.open()

    @ui.refreshable
    def body(self):
        {'planning': self.planning, 'plugins': self.plugins, 'env': self.environment, 'settings': self.settings}[self.view]()

    def planning(self):
        with box('detail-header'):
            with box('stack'):
                text(self.names[self.selected], 'detail-title')
                text('组织目标、插件与上下文，再生成任务候选。', 'sub')
            with box('actions wrap'):
                button('复制', lambda: self.dialogs.confirm('复制规划？', '复制规划及有序上下文，保留独立所有权。'), 'content_copy', 'small')
                button('删除', lambda: self.dialogs.confirm('删除规划？', '删除规划及其采集内容；已导入任务保持独立。'), 'delete_outline', 'small danger')
                button('保存规划', lambda: ui.notify('已演示保存反馈；正式保存核对 revision'), 'check', 'primary small')
        with box('tabs'):
            for title in ['规划配置', '能力与上下文素材', '生成记录']:
                button(title, lambda t=title: self.change_section(t), style='tabbtn' + (' selected' if self.section == title else ''))
        with box('plan-layout'):
            with box('panel pad'):
                if self.section == '规划配置':
                    text('基础信息', 'h2 mb-4')
                    self.dialogs.field('规划名称', self.names[self.selected])
                    ui.textarea('规划描述', value='录入合约信息，完成保存、提交，并核对处理结果。').props('outlined autogrow').classes('w-full mt-3')
                    ui.textarea('操作说明（可选）', value='明确角色、处理顺序和特殊业务规则。').props('outlined autogrow').classes('w-full mt-3')
                    ui.select(['uat', 'test', '不指定环境'], value='uat', label='运行环境').props('outlined dense').classes('w-full mt-3')
                elif self.section == '能力与上下文素材':
                    text('所用插件能力与上下文素材', 'h2 mb-4')
                    ui.select(['playwright', 'ocr', 'tidb'], value=['playwright'], multiple=True, label='所用插件能力').props('outlined dense use-chips').classes('w-full mb-4')
                    self.dialogs.context_summary('规划', str(self.selected))
                else:
                    text('生成记录', 'h2 mb-4')
                    table(['时间', '渠道', '结果', '备注'], [['今天 10:25', '大模型api调用', '可导入', '1 个任务 · 7 个步骤'], ['昨天 16:00', '大模型网页chat调用', '待解析', '等待粘贴回复']])
                    button('查看候选与诊断', lambda: self.dialogs.candidate('生成任务'), 'visibility', 'mt-4')
                    button('打开网页回复流程', lambda: self.dialogs.chat('生成任务'), 'forum', 'mt-3')
            with box('panel pad plan-assist'):
                text('AI 生成任务', 'h2')
                text('使用当前规划配置与上下文快照生成候选；生成不等于执行。', 'muted mt-3')
                button('大模型api调用', lambda: self.dialogs.candidate('生成任务'), 'auto_awesome', 'primary w-full mt-4')
                button('大模型网页chat调用', lambda: self.dialogs.chat('生成任务'), 'forum', 'w-full mt-2')
                text('候选预览', 'h3 mt-6 mb-3')
                text('1 个任务 · 7 个步骤', 'badge blue')
                for i, title in enumerate(['打开登录页面', '录入合约信息', '核对并提交']):
                    with box('rowline mt-3'):
                        text(str(i + 1), 'num')
                        text(title, 'muted')
                button('预览完整候选', lambda: self.dialogs.candidate('生成任务'), 'arrow_forward', 'ghost small mt-3')
                with box('hint amber mt-4'):
                    text('允许待编写步骤导入；校验失败的候选需先修正。')
                button('导入为任务', self.dialogs.import_candidate, 'download', 'primary w-full mt-4')
                text('每次导入创建独立新任务，候选预览保留，可反复导入。', 'muted mt-2')
                button('结束采集实例', lambda: self.dialogs.confirm('结束规划采集实例？', '仅释放本规划的采集资源，已保存上下文与生成记录保留。'), 'stop', 'w-full mt-4')

    def change_section(self, value):
        self.section = value
        self.body.refresh()

    def plugins(self):
        name = self.names[self.selected]
        with box('detail-header'):
            with box('rowline'):
                symbol('extension', 'blue', True)
                with box('stack'):
                    text(name, 'detail-title')
                    text('本地插件 · 版本信息由已安装清单提供', 'muted')
            button('停用' if self.selected < 3 else '启用', lambda: self.dialogs.confirm('修改插件启用状态？', '沿用 plugin.configure，显示失败反馈；不提供安装升级入口。'), style='primary small')
        with box('panel pad'):
            text('能力与动作', 'h2 mb-4')
            catalog = json.loads(Path(__file__).with_name('plugin-catalog.json').read_text())[name]
            text('完整动作契约快照：用途、参数、返回值、影响范围与调用示例。', 'muted mb-3')
            for spec in catalog['actions']:
                with ui.expansion(spec['id'], icon='code').classes('w-full border rounded-lg mb-2'):
                    text('用途说明', 'h3')
                    text(spec['description'], 'description')
                    text('输入参数', 'h3 mt-3')
                    schema = spec['input_schema']
                    rows = []
                    for key, prop in schema.get('properties', {}).items():
                        rows.append([key, str(prop.get('type', '见契约')), '是' if key in schema.get('required', []) else '否', json.dumps(prop.get('default', '未声明'), ensure_ascii=False), prop.get('description', '契约未提供文字说明；类型和约束见下方完整定义')])
                    table(['参数', '类型', '必填', '默认值', '说明'], rows)
                    ui.code(json.dumps(schema, ensure_ascii=False, indent=2), language='json').classes('w-full')
                    text('返回结果', 'h3 mt-3')
                    text('返回空值，无结构化结果。' if spec['output_schema'].get('type') == 'null' else '返回结构与字段约束如下。', 'muted')
                    ui.code(json.dumps(spec['output_schema'], ensure_ascii=False, indent=2), language='json').classes('w-full')
                    text('执行约束', 'h3 mt-3')
                    text(f"契约效果类别：{spec['effect']} · 超时：{spec['timeout_ms']} ms · 安全重试：{'是' if spec['retry_safe'] else '否'} · 资源：{', '.join(spec['resource_ids']) or '无声明'}", 'description')
                    text('效果类别来自插件声明，不代表动作不会改变页面或外部状态；执行前仍须遵守当前会话和确认规则。', 'muted')
                    text('调用示例', 'h3 mt-3')
                    example = {key: f'<填写 {key}>' for key in schema.get('required', [])}
                    ui.code('result = await ctx.call(' + repr(spec['id']) + ', ' + repr(example) + ')', language='python').classes('w-full')
                    text('示例占位值须按参数类型和约束替换；本页面不执行动作。', 'muted')
            for capability, schema in catalog['manifest'].get('context_requests', {}).items():
                with ui.expansion('上下文采集能力 · ' + capability, icon='collections_bookmark').classes('w-full border rounded-lg mb-2'):
                    text('采集当前提供方的上下文证据；按组暂存并确认保存，用户预览与 AI 证据分开。', 'description')
                    ui.code(json.dumps(schema, ensure_ascii=False, indent=2), language='json').classes('w-full')
        with box('panel pad mt-4'):
            text('配置变量说明', 'h2 mb-4')
            table(['变量', '类型', '必填', '默认值', '说明'], [[v['key'], v['type'], '是' if v.get('required') else '否', json.dumps(v.get('default', '未声明'), ensure_ascii=False), v.get('description', '')] for v in catalog['manifest'].get('config_variables', [])])
            text('配置在环境或任务参数中维护；此处不另建一套独立插件配置。', 'hint mt-3')
        with box('panel pad mt-4'):
            text('加载状态', 'h2 mb-3')
            tag('正常加载', 'green')
            button('预览加载失败', lambda: message('插件加载失败', '显示 plugin.error / load_errors 的真实错误，并保留启用控制和版本信息。'), style='ghost small mt-3')
            text('独立“使用中的任务”和插件诊断日志不是现行页面能力，不能照原图冒充已实现。', 'muted mt-3')

    def environment(self):
        with box('detail-header'):
            with box('stack'):
                text('环境详情', 'detail-title')
                text('变量保存在 TaskWeave 本地，不修改系统环境变量。', 'sub')
            button('删除环境', lambda: self.dialogs.confirm('删除环境？', '保留现有任务与历史引用兼容处理；在途运行等限制由核心校验。'), 'delete_outline', 'danger small')
        with box('panel pad'):
            self.dialogs.field('环境名称', self.names[self.selected])
            text('环境变量', 'h2 mt-6 mb-3')
            text('普通值直接填写；对象、数组、数字和布尔值可用 JSON。输入优先级沿用当前规则。', 'hint mb-4')
            rows = ui.column().classes('w-full')
            def add(key='', value='', note=''):
                with rows:
                    with box('env-row w-full') as row:
                        ui.input('Key', value=key).props('outlined dense')
                        ui.input('Value', value=value, password='password' in key, password_toggle_button='password' in key).props('outlined dense')
                        ui.input('说明', value=note).props('outlined dense')
                        button('移除', row.delete, style='danger small')
            add('login_url', 'https://example.test/login', '登录入口')
            add('org_password', 'demo-only', '组织密码 · 示例')
            add('timeout', '30', '请求超时秒数')
            button('添加变量', add, 'add', 'mt-3')
            with box('actions mt-6 wrap'):
                button('保存环境', lambda: ui.notify('已演示保存反馈，未写入实际配置'), 'check', 'primary')
                button('设为默认', lambda: ui.notify('演示默认环境操作'))
            text('非默认不等于不可用。移除变量只改本页草稿，保存后才提交。', 'muted mt-3')

    def settings(self):
        title = self.names[self.selected]
        with box('detail-header'):
            text(title, 'detail-title')
        with box('panel pad'):
            if self.selected == 0:
                text('AI 编写连接', 'h2 mb-4')
                self.dialogs.field('完整 Chat Completions 接口地址', 'https://example.test/v1/chat/completions')
                self.dialogs.field('模型名称', 'your-model')
                ui.input('API Key（留空保留当前密钥）', password=True, password_toggle_button=True).props('outlined dense').classes('w-full mt-3')
                self.dialogs.field('API Key 所在环境变量名', 'TASKWEAVE_MODEL_API_KEY')
                text('本地保存连接；固定步骤执行不调用模型。', 'muted mt-3')
                with box('actions wrap mt-4'):
                    button('保存连接', lambda: ui.notify('原型不保存连接'), style='primary')
                    button('测试连接', lambda: self.dialogs.confirm('测试模型连接', '正式产品保存当前连接配置并实际调用一次模型；本原型不联网。'))
                text('AI 请求大小', 'h2 mt-6 mb-4')
                ui.number('请求上限（KiB）', value=2048, min=1, max=4096).props('outlined dense').classes('w-full')
                text('范围 1–4096，默认 2048；不是模型 token 上限。', 'muted')
                button('保存 AI 请求设置', lambda: ui.notify('原型不写入设置'), style='primary mt-3')
            elif self.selected == 1:
                text('数据脱敏', 'h2 mb-4')
                ui.checkbox('展示插件上下文时脱敏', value=True)
                ui.checkbox('发送给 AI 时脱敏', value=True)
                text('两项独立，保留既有隐私处理规则。', 'muted mt-3')
                button('保存脱敏设置', lambda: ui.notify('原型不写入隐私设置'), style='primary mt-4')
            elif self.selected == 2:
                text('执行并发', 'h2 mb-4')
                ui.number('最大并发执行线程数', value=8, min=1, max=8).props('outlined dense').classes('w-full')
                text('单条运行内步骤顺序执行；不同运行最多并行 8 条。超限时新运行直接报错。', 'hint mt-3')
                button('保存执行器设置', lambda: ui.notify('原型不修改执行器'), style='primary mt-4')
            else:
                text('本地工作空间', 'h2 mb-4')
                text('示例：用户应用数据目录 / TaskWeave', 'description')
                self.dialogs.field('新的工作空间目录')
                with box('actions wrap mt-4'):
                    button('迁移工作空间', lambda: self.dialogs.confirm('迁移工作空间？', '迁移前结束全部实例；复制校验后，下次启动使用新目录并删除旧目录。保持现有迁移流程。'), style='primary')
                    button('打开数据目录', lambda: ui.notify('原型不打开真实目录'))
                text('迁移成功后提示重启；失败需显示错误，不宣称数据已迁移。', 'hint mt-4')

    def market(self):
        text('市集', 'heading')
        text('发现可复用的任务、规划与插件资源。', 'sub')
        with box('market-hero panel mt-6'):
            with box('stack'):
                tag('建设中', 'blue')
                text('把好的工作方式，分享给更多人。', 'heading mt-4')
                text('市集暂未开放，当前版本不提供浏览、下载或安装服务。', 'description mt-4')
            symbol('storefront', 'blue', True)
        with box('result-grid'):
            for title, description, icon in [('任务模板', '复用验证过的任务配置', 'checklist'), ('规划模板', '从目标整理到步骤设计', 'assignment'), ('插件资源', '连接工具与外部服务', 'extension')]:
                with box('panel pad'):
                    symbol(icon)
                    text(title, 'h2 mt-4')
                    text(description, 'muted mt-2')
                    tag('尚未开放', '')
        text('AI 和插件也可能联网；不宣称市集是唯一联网模块。', 'muted mt-5')
