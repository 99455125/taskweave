"""TaskWeave design prototype. Sample data only; never imports the product core."""
from pathlib import Path
from html import escape
import argparse
from nicegui import ui

from widgets import TASKS, STEPS, TASK_STEPS, RUN_TASKS, RUNS, STATES, box, text, button, tag, status, symbol, progress, table, message, demo_action, go
from detail_dialogs import DetailDialogs
from secondary_pages import SecondaryPages


class Prototype:
    def __init__(self, view, task, run):
        self.view = view if view in {'home', 'tasks', 'editor', 'runs', 'planning', 'plugins', 'market', 'env', 'settings'} else 'home'
        self.task = max(0, min(task, len(TASKS) - 1))
        self.run = max(0, min(run, len(RUNS) - 1))
        self.step = 0
        self.run_step = RUNS[self.run][4] if RUNS[self.run][1] != '成功' else 6
        self.run_state = RUNS[self.run][1]
        self.search = ''
        self.favorites = {0, 1}
        self.only_favorites = False
        self.category = '全部分类'
        self.task_tab = '步骤详情' if view == 'editor' else '任务概览'
        self.run_tab = '执行详情'
        self.debug_open = True
        self.saved = True
        self.long_steps = False
        self.drafts = {}
        self.saved_drafts = {}
        self.dialogs = DetailDialogs()
        self.secondary = SecondaryPages(self.dialogs)

    def render(self):
        ui.add_css(Path(__file__).with_name('style.css').read_text())
        with box('pilot'):
            text('DESIGN PREVIEW  /  TaskWeave UI · 02')
            text('交互原型 · 示例数据 · 不执行真实操作')
        with box('topbar'):
            with box('brand'):
                ui.icon('layers', size='24px').classes('brand-mark')
                text('TaskWeave')
            with box('nav'):
                for key, label, icon in [('home', '工作台', 'space_dashboard'), ('planning', '规划', 'assignment'), ('tasks', '任务', 'checklist'), ('runs', '执行', 'play_circle_outline'), ('plugins', '插件', 'extension'), ('market', '市集', 'storefront'), ('env', '环境', 'dns'), ('settings', '设置', 'tune')]:
                    selected = key == self.view or key == 'tasks' and self.view == 'editor'
                    b = button(label, lambda k=key: self.navigate(k), icon, 'navbtn' + (' active' if selected else ''))

            with box('toptools'):
                with box('local'):
                    ui.icon('circle', size='7px').classes('text-green-500')
                    text('本地工作空间')
                button('执行实例', self.dialogs.instances, style='ghost small')
                button('服务日志', self.dialogs.logs, style='ghost small')
                button('设计说明', self.design_notes, 'info_outline', 'ghost small')
        with box('page'):
            if self.view == 'home':
                self.home()
            elif self.view in {'tasks', 'editor'}:
                self.tasks()
            elif self.view == 'runs':
                self.runs()
            else:
                self.secondary.render(self.view)
        text('TaskWeave  ·  本地优先，让重复的工作更简单', 'footer-note')

    def navigate(self, view):
        if not self.saved:
            self.leave_dialog(lambda: go(view))
        else:
            go(view)

    def design_notes(self):
        message('这版设计可以体验什么', '可以切换三个主页面、任务内部页签和步骤，搜索任务、筛选收藏与分类，展开调试面板，切换执行状态以及查看 30 步长流程。收藏与分类仅演示候选交互；持久化、复制分享规则尚待确认。除明确标注的预览操作外，不连接任何业务服务。')

    def quick_action(self, label):
        actions = {'新建规划': lambda: self.secondary.new_entry('planning'), '新建任务': self.dialogs.task_config, '导入任务': lambda: self.dialogs.transfer(True), '新建执行': self.dialogs.new_run}
        actions[label]()

    def home(self):
        with box('rowline between wrap'):
            with box('stack'):
                text('工作台', 'heading')
                text('从这里继续工作，或开始一次新的执行。', 'sub')
            button('新建执行', self.dialogs.new_run, 'add', 'primary')
        with box('stats'):
            for title, value, icon, note, color in [('任务总数', '6', 'inventory_2', '4 个任务已确认', 'blue'), ('活跃执行', '3', 'play_circle_outline', '1 个等待输入', 'green'), ('今日执行', '4', 'calendar_today', '按开始时间统计', 'purple'), ('待处理', '2', 'inbox', '1 个输入 · 1 个失败', 'amber')]:
                with box('panel stat'):
                    symbol(icon, color)
                    with box('grow'):
                        text(title, 'muted')
                        text(value, 'stat-number')
                        text(note, 'muted')
        with box('home-grid'):
            with box('panel pad'):
                with box('section-head'):
                    text('最近更新任务', 'h2')
                    button('查看全部', lambda: go('tasks'), 'arrow_forward', 'ghost small')
                for i, (name, category, label, icon, color, date) in enumerate(TASKS[:4]):
                    with box('item'):
                        symbol(icon, color)
                        with box('grow'):
                            text(name, 'item-title')
                            with box('rowline wrap'):
                                tag(category)
                                text(date, 'muted')
                        with box('actions'):
                            button('打开', lambda t=i: go('tasks', t), style='small')
                            button('执行', lambda n=name: self.dialogs.new_run(n), 'play_arrow', 'small primary')
            with box('panel pad'):
                with box('section-head'):
                    text('活跃执行', 'h2')
                    button('查看全部', lambda: go('runs'), 'arrow_forward', 'ghost small')
                for i in [2, 1, 0]:
                    name, state, rid, date, done = RUNS[i]
                    with box('run-item'):
                        with box('rowline between'):
                            text(name, 'h3')
                            status(state)
                        progress(done)
                        with box('rowline between wrap'):
                            with box('stack'):
                                text(f'步骤 {done + 1}/7 · {TASK_STEPS[RUN_TASKS[i]][done]}', 'muted')
                                text('uat 环境  ·  ' + date, 'muted')
                            with box('actions'):
                                label = '填写输入' if state == '等待输入' else '查看'
                                button(label, lambda r=i: go('runs', run=r), style='primary small')
                                button('结束', lambda: self.end_dialog(), style='small')
        with box('home-bottom'):
            with box('panel pad'):
                with box('section-head'):
                    text('最近执行结果', 'h2')
                    button('全部记录', lambda: go('runs'), 'arrow_forward', 'ghost small')
                table(['任务名称', '执行时间', '状态', '结果摘要'], [['查询保单', '今天 09:30', '成功', '已查询 1 条记录'], ['生成测试数据', '昨天 16:20', '已结束', '用户结束执行']])
                button('查看查询结果', lambda: go('runs', run=3), 'open_in_new', 'ghost small').classes('mt-3')
            with box('panel pad'):
                with box('section-head'):
                    text('快速开始', 'h2')
                    ui.icon('bolt', size='19px').classes('text-blue-400')
                with box('quick-grid'):
                    for label, icon in [('新建规划', 'assignment'), ('新建任务', 'add_box'), ('导入任务', 'file_upload'), ('新建执行', 'play_arrow')]:
                        button(label, lambda l=label: self.quick_action(l), icon, 'quick')
                text('从规划整理思路，用任务沉淀可重复执行的步骤。', 'muted mt-4')

    def tasks(self):
        with box('workspace'):
            with box('sidebar'):
                with box('sidebar-head'):
                    text('任务', 'h2')
                    button('', self.dialogs.task_config, 'add', 'iconbtn').tooltip('新建任务')
                with box('search'):
                    search = ui.input(placeholder='搜索任务名称…').props('outlined dense clearable').classes('w-full')
                    search.on_value_change(lambda e: self.set_search(e.value))
                with box('filter-row'):
                    button('全部任务', lambda: self.filter_favorites(False), style='small')
                    button('我的收藏', lambda: self.filter_favorites(True), 'star_outline', 'small')
                with box('search'):
                    ui.select(['全部分类'] + sorted({t[1] for t in TASKS}), value=self.category, on_change=lambda e: self.set_category(e.value)).props('outlined dense').classes('w-full')
                button('管理分类', self.dialogs.categories, 'folder_open', 'ghost small')
                self.task_list()
                text('收藏 / 分类为候选交互，仅保存在本页', 'sidebar-note')
            with box('detail'):
                self.task_detail()

    def set_search(self, value):
        self.search = value or ''
        self.task_list.refresh()

    def filter_favorites(self, value):
        self.only_favorites = value
        self.task_list.refresh()

    def set_category(self, value):
        self.category = value
        self.task_list.refresh()

    @ui.refreshable
    def task_list(self):
        matches = [(i, t) for i, t in enumerate(TASKS) if self.search.casefold() in t[0].casefold() and (not self.only_favorites or i in self.favorites) and (self.category == '全部分类' or t[1] == self.category)]
        if not matches:
            text('没有匹配的任务', 'empty')
        for i, (name, category, label, icon, color, date) in matches:
            with box('master-item' + (' selected' if i == self.task else '')).on('click', lambda t=i: self.select_task(t)).props('tabindex=0 role=button').on('keydown.enter', lambda t=i: self.select_task(t)):
                with box('rowline between'):
                    text(name, 'master-title')
                    if i in self.favorites:
                        ui.icon('star', size='14px').classes('text-amber-400')
                with box('rowline'):
                    tag(category)
                    tag(label, color)
                with box('master-meta'):
                    text('7 个步骤')
                    text(date)

    def select_task(self, task):
        if not self.saved:
            self.leave_dialog(lambda: self.apply_task(task))
        else:
            self.apply_task(task)

    def apply_task(self, task):
        self.task = task
        self.step = 0
        self.saved = True
        self.task_detail.refresh()
        self.task_list.refresh()

    def leave_dialog(self, action):
        with ui.dialog() as dialog, ui.card():
            text('保留当前修改？', 'h2')
            text('原型中的草稿尚未保存。选择继续编辑，或舍弃本页示例修改后切换。', 'description')
            with box('actions'):
                button('继续编辑', dialog.close)
                def discard():
                    key = (self.task, self.step)
                    self.drafts[key] = dict(self.saved_drafts.get(key, self.default_draft()))
                    self.saved = True
                    dialog.close()
                    action()
                button('舍弃并切换', discard, style='danger')
        dialog.open()

    @ui.refreshable
    def task_detail(self):
        name, category, label, icon, color, _ = TASKS[self.task]
        with box('detail-header'):
            with box('rowline'):
                symbol(icon, color, True)
                with box('stack'):
                    text(name, 'detail-title')
                    with box('rowline wrap'):
                        tag(category)
                        tag(label, color)
                        text('uat 环境', 'muted')
            with box('actions'):
                button('', self.toggle_favorite, 'star' if self.task in self.favorites else 'star_outline', 'iconbtn').tooltip('切换收藏')
                button('新建执行', lambda: self.dialogs.new_run(name), 'play_arrow', 'primary')
                button('', lambda: self.dialogs.task_actions(name), 'more_horiz', 'iconbtn').tooltip('更多任务操作')
        with box('tabs'):
            for tab in ['任务概览', '步骤详情', '执行历史', '调试历史']:
                button(tab, lambda t=tab: self.change_tab(t), style='tabbtn' + (' selected' if self.task_tab == tab else ''))
        if self.task_tab == '任务概览':
            self.overview()
        elif self.task_tab == '步骤详情':
            self.editor()
        elif self.task_tab == '调试历史':
            with box('panel pad'):
                text('调试历史', 'h2 mb-4')
                table(['调试', '开始时间', '状态', '环境'], [['示例调试 · 0012', '今天 10:30', '成功', 'uat']])
                button('查看调试记录', self.dialogs.history, 'history', 'ghost mt-4')
        else:
            with box('panel pad'):
                text('执行历史', 'h2 mb-4')
                table(['运行', '开始时间', '状态', '环境'], [['示例运行 · 0009', '今天 09:30', '成功', 'uat']])
                button('打开执行详情', lambda: go('runs', run=3), 'arrow_forward', 'ghost mt-4')

    def toggle_favorite(self):
        self.favorites.symmetric_difference_update({self.task})
        self.task_list.refresh()
        self.task_detail.refresh()

    def change_tab(self, tab):
        def apply():
            self.task_tab = tab
            self.task_detail.refresh()
        if not self.saved:
            self.leave_dialog(apply)
        else:
            apply()

    def overview(self):
        with box('panel pad'):
            with box('section-head'):
                text('任务说明', 'h2')
                button('编辑', lambda: self.dialogs.task_config(TASKS[self.task][0]), 'edit', 'small')
            text('在业务系统中完成信息查询与核对，将可重复的操作保存为任务。运行前选择环境并填写必要输入，执行结束后查看结果和生成文件。', 'description')
            with box('rowline mt-4 wrap'):
                tag('步骤已确认', 'green')
                text('最近更新：今天 10:30', 'muted')
        with box('panel pad mt-4'):
            with box('section-head'):
                text('任务变量', 'h2')
                button('新增变量', self.dialogs.schema, 'add', 'small')
            table(['名称', '类型', '必填', '默认值', '说明'], [['policy_no', 'string', '是', '—', '保单号'], ['query_date', 'string', '否', '—', '查询日期'], ['need_detail', 'boolean', '否', 'false', '是否查询详细信息']])
        with box('overview-grid'):
            with box('panel pad'):
                text('执行情况', 'h2')
                with box('numbers'):
                    for v, label in [('12', '执行总数'), ('9', '成功'), ('2', '失败'), ('1', '运行中')]:
                        with box('stack'):
                            text(v, 'mini-number')
                            text(label, 'muted')
                progress(9, 12, 'green')
                text('最近成功：今天 09:30 · 已查询 1 条记录', 'muted')
            with box('panel pad'):
                with box('section-head'):
                    text('最近调试', 'h2')
                    status('成功')
                text('步骤 1 · 打开登录页面', 'h3')
                text('uat 环境 · 今天 09:22', 'muted mt-2')
                text('页面已打开，可继续编写下一步骤。', 'description mt-3')
                button('进入步骤详情', lambda: self.change_tab('步骤详情'), 'arrow_forward', 'ghost small mt-3')

    def default_draft(self):
        return {'name': TASK_STEPS[self.task][self.step], 'description': '打开业务系统登录页面，检查页面是否可用，为后续操作保存页面上下文。', 'plugin': ['playwright'], 'code': 'async def run(ctx, inputs):\n    return ctx.result(data=inputs)'}

    def edit_field(self, key, value):
        self.drafts.setdefault((self.task, self.step), self.default_draft())[key] = value
        self.mark_dirty()

    def editor(self):
        draft = self.drafts.setdefault((self.task, self.step), self.default_draft())
        with box('steps-layout'):
            with box('panel step-list'):
                with box('rowline between mb-3 px-2'):
                    text('步骤 · 7', 'h3')
                    button('', self.dialogs.step_actions, 'add', 'iconbtn').tooltip('添加步骤')
                for i, name in enumerate(TASK_STEPS[self.task]):
                    with box('step-entry' + (' selected' if self.step == i else '')).on('click', lambda s=i: self.pick_edit_step(s)).props('role=button tabindex=0').on('keydown.enter', lambda s=i: self.pick_edit_step(s)):
                        text(str(i + 1), 'num')
                        text(name, 'grow')
                        if i > 0:
                            ui.icon('check', size='14px').classes('text-green-500')
            with box('editor-grid' if self.debug_open else 'stack'):
                with box('panel editor-form'):
                    with box('section-head'):
                        text('步骤配置', 'h2')
                        button('调试面板', self.toggle_debug, 'bug_report', 'ghost small')
                    text('步骤名称', 'field-label')
                    ui.input(value=draft['name'], on_change=lambda e: self.edit_field('name', e.value)).props('outlined dense').classes('w-full')
                    button('AI 生成步骤描述', lambda: self.dialogs.ai('生成步骤描述'), 'auto_awesome', 'ghost small mt-2')
                    text('步骤说明', 'field-label')
                    ui.textarea(value=draft['description'], on_change=lambda e: self.edit_field('description', e.value)).props('outlined autogrow').classes('w-full')
                    text('补充说明（可选）', 'field-label')
                    ui.textarea(value='', placeholder='步骤规则与补充约束').props('outlined autogrow').classes('w-full')
                    text('使用插件', 'field-label')
                    ui.select(['playwright', 'ocr', 'tidb', 'utility'], value=draft['plugin'], multiple=True, on_change=lambda e: self.edit_field('plugin', e.value)).props('outlined dense use-chips').classes('w-full')
                    with box('rowline mt-3 wrap'):
                        button('插入动作', self.dialogs.action_form, 'add', 'small')
                        button('AI 编写', lambda: self.dialogs.ai('编写步骤'), 'auto_awesome', 'small')
                    with ui.expansion('变量与输入依赖', icon='data_object').classes('w-full mt-4'):
                        button('编辑变量定义', self.dialogs.schema, style='small')
                        button('编辑输入依赖', self.dialogs.bindings, style='small')
                    self.dialogs.context_summary('步骤', f'{self.task}:{self.step}')
                    button('时间设置', lambda: self.dialogs.timing(self.step), 'schedule', 'ghost small mt-3')
                    button('步骤排序与确认', self.dialogs.step_actions, 'checklist', 'ghost small mt-3')
                    text('执行代码', 'field-label')
                    ui.codemirror(draft['code'], language='Python', on_change=lambda e: self.edit_field('code', e.value), line_wrapping=True).classes('w-full border rounded-lg').style('min-height:180px;max-height:420px')
                    with box('editor-footer'):
                        self.save_label = text('已保存 · 示例' if self.saved else '有未保存修改 · 示例', 'muted')
                        with box('actions wrap'):
                            button('保存步骤', self.save, style='small')
                            button('校验内容', self.dialogs.lint, style='small')
                            button('确认验证并保存', self.dialogs.confirm_step, 'check', 'primary small')
                if self.debug_open:
                    self.dialogs.debug_panel(self.step, self.toggle_debug)

    def mark_dirty(self):
        self.saved = False
        self.save_label.set_text('有未保存修改 · 示例')

    def save(self):
        self.saved_drafts[(self.task, self.step)] = dict(self.drafts[(self.task, self.step)])
        self.saved = True
        self.save_label.set_text('已保存 · 仅本次演示')
        ui.notify('已演示保存反馈，未写入业务数据', type='positive')

    def pick_edit_step(self, step):
        def apply():
            self.step = step
            self.saved = True
            self.task_detail.refresh()
        if not self.saved:
            self.leave_dialog(apply)
        else:
            apply()

    def toggle_debug(self):
        self.debug_open = not self.debug_open
        self.task_detail.refresh()

    def runs(self):
        with box('rowline between wrap mb-5'):
            with box('stack'):
                text('执行', 'heading')
                text('跟踪每次执行，查看步骤、输入与结果。', 'sub')
            button('新建执行', self.dialogs.new_run, 'add', 'primary')
        with box('workspace'):
            with box('sidebar'):
                with box('sidebar-head'):
                    text('执行列表', 'h2')
                    text('5 条', 'muted')
                with box('search'):
                    self.run_query = ui.input(placeholder='搜索任务或运行编号…', on_change=lambda _: self.run_list.refresh()).props('outlined dense clearable').classes('w-full')
                    self.run_task_filter = ui.select([r[0] for r in RUNS], value=[], multiple=True, label='任务筛选（多选）', on_change=lambda _: self.run_list.refresh()).props('outlined dense use-chips').classes('w-full mt-2')
                    self.run_filter = ui.select(list(STATES), value=[], multiple=True, label='状态筛选（多选）', on_change=lambda _: self.run_list.refresh()).props('outlined dense use-chips').classes('w-full mt-2')
                    button('清除筛选', self.clear_run_filters, style='ghost small')
                self.run_list()
                text('按创建时间排序 · 最新在前', 'sidebar-note')
            with box('detail'):
                self.run_detail()

    def clear_run_filters(self):
        self.run_query.value = ''
        self.run_task_filter.value = []
        self.run_filter.value = []
        self.run_list.refresh()

    @ui.refreshable
    def run_list(self):
        query = self.run_query.value or ''
        count = 0
        for i, (name, state, rid, date, done) in enumerate(RUNS):
            actual_state = self.run_state if i == self.run else state
            total = 30 if i == self.run and self.long_steps else 7
            if actual_state == '成功':
                done = total
            if query not in name + rid or (self.run_filter.value and actual_state not in self.run_filter.value) or (self.run_task_filter.value and name not in self.run_task_filter.value):
                continue
            count += 1
            with box('master-item' + (' selected' if i == self.run else '')).on('click', lambda r=i: self.select_run(r)).props('tabindex=0 role=button').on('keydown.enter', lambda r=i: self.select_run(r)):
                text(name, 'master-title')
                with box('rowline between'):
                    text('#20260926-' + rid, 'muted')
                    status(actual_state)
                progress(done, total, color='green' if actual_state == '成功' else '')
                with box('master-meta'):
                    text('uat · ' + date)
                    text(f'{done}/{total} 完成')
        if not count:
            text('没有匹配的执行', 'empty')

    def select_run(self, run):
        self.run = run
        self.run_state = RUNS[run][1]
        self.run_step = min(RUNS[run][4], 6)
        self.run_detail.refresh()
        self.run_list.refresh()

    def change_state(self, state):
        self.run_state = state
        self.run_detail.refresh()
        self.run_list.refresh()

    async def choose_run_step(self, index):
        offset = await ui.run_javascript('document.querySelector(".track")?.scrollLeft || 0')
        self.run_step = index
        self.run_detail.refresh()
        await ui.run_javascript(f'document.querySelector(".track").scrollLeft = {float(offset)}')

    def end_dialog(self):
        with ui.dialog() as dialog, ui.card():
            text('结束这次执行？', 'h2')
            text('结束后释放本次执行占用的资源。已有结果和历史记录保留。', 'description')
            text('原型仅展示确认方式，不会真正结束任何任务。', 'muted')
            with box('actions'):
                button('取消', dialog.close)
                button('确认结束 · 演示', lambda: (dialog.close(), ui.notify('已演示结束确认，未发送命令')), style='danger')
        dialog.open()

    @ui.refreshable
    def run_detail(self):
        name, _, rid, date, done = RUNS[self.run]
        total = 30 if self.long_steps else 7
        if self.run_state == '成功':
            done = total
        base_steps = TASK_STEPS[RUN_TASKS[self.run]]
        steps = base_steps + [f'校验并归档第 {i} 批业务资料' for i in range(8, 31)] if self.long_steps else base_steps
        with box('detail-header'):
            with box('stack'):
                with box('rowline wrap'):
                    text(name, 'detail-title')
                    status(self.run_state)
                with box('run-summary'):
                    text('运行 #20260926-' + rid)
                    text('uat 环境')
                    text('开始于 ' + date)
            with box('actions'):
                if self.run_state == '执行中':
                    button('暂停', lambda: demo_action('暂停执行'), 'pause', 'small')
                elif self.run_state == '等待输入':
                    button('填写输入', self.dialogs.pending_input, 'edit_note', 'primary small')
                elif self.run_state == '待核对':
                    button('核对结果', self.dialogs.reconcile, 'fact_check', 'primary small')
                elif self.run_state in {'失败', '已暂停'}:
                    button('继续执行', lambda: self.dialogs.run_control(self.run_step), 'play_arrow', 'primary small')
                if self.run_state not in {'成功', '已结束'}:
                    button('结束', self.end_dialog, 'stop', 'small')
                else:
                    button('以本次参数新建', self.dialogs.new_run, 'replay', 'small')
                button('删除执行', lambda: self.dialogs.confirm('删除这次执行？', '仅删除本次运行及日志、结果；任务和其他运行保留。'), 'delete_outline', 'ghost small')
        with box('panel run-progress'):
            with box('rowline between wrap'):
                text('步骤进度', 'h3')
                text(f'{done} / {total} 已完成 · 点击节点查看详情', 'muted')
            with box('track'):
                for i, label in enumerate(steps):
                    done_node = i < done
                    current = i == done
                    state_class = 'done' if done_node else ('error' if self.run_state == '失败' else 'wait' if self.run_state in {'待核对', '等待输入', '已暂停'} else 'running') if current and self.run_state != '已结束' else ''
                    with box('node ' + state_class + (' chosen' if self.run_step == i else '')):
                        b = button('' if done_node else str(i + 1), lambda s=i: self.choose_run_step(s), 'check' if done_node else None, 'node-button')
                        b.props(f'aria-label="查看步骤{i + 1}：{label}"').tooltip(label)
                        text(label, 'node-name')
                        text('成功' if done_node else self.run_state if current else '待执行', 'node-status')
        with box('tabs'):
            for tab in ['执行详情', '本次结果', '历史记录']:
                button(tab, lambda t=tab: self.run_tab_change(t), style='tabbtn' + (' selected' if self.run_tab == tab else ''))
        if self.run_tab == '执行详情':
            idx = min(self.run_step, len(steps) - 1)
            selected_state = '成功' if idx < done else self.run_state if idx == done else '待执行'
            if self.run_state == '成功' and idx < 7:
                selected_state = '成功'
            with box('panel run-body'):
                with box('section-head'):
                    with box('step-info'):
                        with box('step-info-icon'):
                            ui.icon('article', size='20px')
                        with box('stack'):
                            text(f'{idx + 1:02d}  /  {steps[idx]}', 'h2')
                            text('正在查看此步骤，选择节点不会触发执行。', 'muted')
                    status(selected_state)
                with box('actions wrap mb-3'):
                    button('执行至此 / 重跑', lambda: self.dialogs.run_control(idx), 'play_arrow', 'small')
                    button('查看结果', self.dialogs.result, 'visibility', 'small')
                    button('前往此步骤调试', lambda: go('editor', task=RUN_TASKS[self.run]), 'bug_report', 'small')
                if selected_state == '失败':
                    with box('hint amber'):
                        text('验证码未通过校验。请先查看错误与输入，再决定是否重新执行。')
                    with box('actions mt-3'):
                        button('查看错误', lambda: message('步骤错误 · 示例', 'CAPTCHA_INVALID：验证码未通过业务系统校验。'), 'error_outline', 'small')
                        button('从此步骤重跑', lambda: self.dialogs.run_control(self.run_step), 'replay', 'small')
                elif selected_state == '待核对':
                    text('外部操作结果不确定，核对完成前不能按普通失败重试。', 'hint amber')
                elif selected_state == '等待输入':
                    text('执行已暂停，等待填写本次步骤所需输入。', 'hint amber')
                elif selected_state == '待执行':
                    text('该步骤尚未开始，暂无输入、输出或执行日志。', 'hint')
                else:
                    text('显示本步骤最近一次有效尝试；历史尝试独立保留。', 'hint')
                if selected_state != '待执行':
                    with box('run-two-col'):
                        with box('stack'):
                            text('有效输入', 'h3 mb-2')
                            ui.html('<pre class="code-box">{\n  "org_code": "DEMO_ORG",\n  "captcha": "••••",\n  "need_detail": true\n}</pre>')
                        with box('stack'):
                            text('执行信息', 'h3 mb-2')
                            table(['项目', '值'], [['尝试次数', '1'], ['耗时', '12 秒'], ['执行环境', 'uat'], ['有效性', '当前有效']])
                    with box('info-section'):
                        with box('section-head'):
                            text('执行日志', 'h3')
                            button('查看完整日志', self.dialogs.logs, 'open_in_new', 'ghost small')
                        ui.html('<pre class="code-box dark">10:12:06  INFO   开始执行当前步骤\n10:12:07  INFO   已读取步骤输入\n10:12:18  ' + ('ERROR  验证码未通过校验' if selected_state == '失败' else 'INFO   ' + escape(selected_state)) + '</pre>')
                    with ui.expansion('历史尝试 · 1', icon='history').classes('w-full mt-3'):
                        text('尝试 1 · 当前有效。重跑后，旧尝试仍保留并标记为已失效。', 'muted')
        elif self.run_tab == '本次结果':
            with box('panel pad'):
                text('本次结果', 'h2')
                if self.run_state == '成功':
                    table(['类型', '名称', '摘要'], [['数据', '查询结果', '1 条记录'], ['文件', '备份报告.json', '12 KB']])
                    button('查看结果', self.dialogs.result, style='small mt-3')
                else:
                    text('暂无可展示的结果', 'empty')
                    text('正式界面只展示已保存且声明了展示方式的结果。', 'muted')
        else:
            with box('panel pad'):
                text('运行历史', 'h2 mb-4')
                table(['时间', '事件', '说明'], [['10:12:06', '执行开始', '已加载运行快照'], ['10:12:18', self.run_state, '查看对应步骤详情']])
        with box('rowline wrap mt-5'):
            text('原型状态预览', 'eyebrow')
            ui.select(list(STATES), value=self.run_state, on_change=lambda e: self.change_state(e.value)).props('outlined dense').classes('w-36')
            button('预览 7 步' if self.long_steps else '预览 30 步', self.toggle_long, 'route', 'ghost small')
            text('仅用于审阅边界状态', 'muted')

    def run_tab_change(self, value):
        self.run_tab = value
        self.run_detail.refresh()

    def toggle_long(self):
        self.long_steps = not self.long_steps
        self.run_step = min(self.run_step, 6)
        self.run_detail.refresh()
        self.run_list.refresh()


@ui.page('/')
def index(view: str = 'home', task: int = 0, run: int = 0):
    Prototype(view, task, run).render()


if __name__ in {'__main__', '__mp_main__'}:
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8768)
    args = parser.parse_args()
    ui.run(host='127.0.0.1', port=args.port, title='TaskWeave · UI 设计预览', show=False, reload=False, language='zh-CN')
