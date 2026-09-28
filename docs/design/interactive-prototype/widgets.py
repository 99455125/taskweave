"""Shared sample fixtures and visual controls for the standalone prototype."""
from html import escape
from nicegui import ui

TASKS = [
    ('查询保单', '保险平台', '查询', 'search', 'blue', '今天 10:30'),
    ('再保平台 · 合约账单备份', '保险平台', '备份', 'inventory_2', 'purple', '今天 09:42'),
    ('批量导入客户', '客户运营', '导入', 'group_add', 'green', '昨天 16:20'),
    ('清算单据回归', '财务对账', '回归', 'fact_check', 'blue', '昨天 14:10'),
    ('生成测试数据', '数据处理', '测试', 'data_object', 'amber', '09-23 11:06'),
    ('登录并进入系统', '系统运维', '基础', 'login', 'purple', '09-22 08:45'),
]
STEPS = ['打开登录页面', '保存验证码', '解析验证码', '输入验证码', '登录系统', '核对合约信息', '生成备份报告']
TASK_STEPS = {
    0: ['打开登录页面', '保存验证码', '解析验证码', '输入验证码', '登录系统', '查询保单信息', '保存查询结果'],
    1: STEPS,
    2: ['读取客户文件', '校验文件格式', '补充导入参数', '连接业务系统', '导入客户信息', '核对导入数量', '生成导入报告'],
    3: ['读取测试用例', '登录业务系统', '准备清算单据', '提交测试单据', '核对清算结果', '比对预期数据', '生成回归报告'],
    4: ['读取数据模板', '校验字段定义', '生成示例数据', '补全关联数据', '校验生成结果', '导出数据文件', '生成汇总报告'],
    5: ['打开登录页面', '保存验证码', '解析验证码', '输入验证码', '提交登录', '检查登录状态', '打开工作页面'],
}
RUN_TASKS = [1, 2, 3, 0, 4]
STATES = {'失败': ('red', 'error_outline'), '执行中': ('blue', 'play_circle'), '等待输入': ('amber', 'edit_note'), '已暂停': ('amber', 'pause_circle'), '待核对': ('amber', 'help_outline'), '成功': ('green', 'check_circle'), '已结束': ('', 'stop_circle')}
RUNS = [('再保平台 · 合约账单备份', '失败', '0012', '今天 10:12', 3), ('批量导入客户', '等待输入', '0011', '今天 10:08', 2), ('清算单据回归', '执行中', '0010', '今天 09:54', 1), ('查询保单', '成功', '0009', '今天 09:30', 7), ('生成测试数据', '已结束', '0008', '昨天 16:20', 2)]


def box(classes):
    return ui.element('div').classes(classes)


def text(value, classes=''):
    return ui.label(value).classes(classes)


def button(label, callback=None, icon=None, style=''):
    b = ui.button(label, on_click=callback, icon=icon, color=None).props('flat no-caps').classes('btn ' + style)
    if not label and icon:
        b.props(f'aria-label="{icon}"')
    return b


def tag(value, color=''):
    return text(value, 'badge ' + color)


def status(value):
    color, icon = STATES.get(value, ('', 'circle'))
    with box('badge ' + color):
        ui.icon(icon, size='13px')
        text(value)


def symbol(icon, color='blue', hero=False):
    with box('square-icon ' + color + (' hero' if hero else '')):
        ui.icon(icon, size='24px' if hero else '20px')


def progress(done, total=7, color=''):
    ui.html(f'<div class="progress {color}"><i style="width:{done / total * 100:.2f}%"></i></div>')


def table(headers, rows):
    html = '<table class="data-table"><thead><tr>' + ''.join(f'<th>{escape(h)}</th>' for h in headers) + '</tr></thead><tbody>'
    html += ''.join('<tr>' + ''.join(f'<td>{escape(str(c))}</td>' for c in row) + '</tr>' for row in rows)
    ui.html(html + '</tbody></table>').classes('table-scroll')


def message(title, body):
    with ui.dialog() as dialog, ui.card():
        text(title, 'h2')
        text(body, 'description')
        button('知道了', dialog.close, style='primary').classes('self-end')
    dialog.open()


def demo_action(title):
    message(title, '这是交互设计预览。正式版本将使用现有确认与输入流程；本原型不会启动任务、调用插件、连接模型或写入业务数据。')


def go(view, task=0, run=0):
    ui.navigate.to(f'/?view={view}&task={task}&run={run}')
