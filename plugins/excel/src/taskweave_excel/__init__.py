"""Optional XLSX actions backed by the host's internal dataset port."""
import asyncio
import threading
from types import SimpleNamespace
from taskweave.plugins.sdk import AuthoringContribution, CapabilitySpec, PluginError
from taskweave_dataset import REF, NAME, COLUMNS, ROWS


class ExcelAction:
    def __init__(self, operation):
        self.operation = operation
        props = {'path': {'type': 'string', 'minLength': 1}}
        if operation != 'inspect':
            props['sheet'] = {'type': 'string', 'minLength': 1, 'maxLength': 31}
        if operation == 'read':
            props.update({'range': {'type': 'string'}, 'header': {'type': 'boolean'}, 'columns': COLUMNS,
                          'formula_mode': {'enum': ['values', 'formulas']}, 'name': NAME})
        if operation in ('create', 'write'):
            props.update({'values': {**ROWS, 'maxItems': 100001}, 'dataset': REF,
                          'include_header': {'type': 'boolean'}, 'formulas': {'type': 'boolean'},
                          'start_cell': {'type': 'string'}})
        if operation == 'write':
            props.update({'output_path': {'type': 'string'}, 'overwrite': {'type': 'boolean'}, 'create_sheet': {'type': 'boolean'}})
        descriptions = {'inspect': '查看工作簿的工作表与范围', 'read': '将工作表区域导入内部数据集',
                        'create': '新建 XLSX，可写入二维数据或内部数据集', 'write': '向 XLSX 指定工作表区域写入数据，可另存新文件'}
        self.spec = CapabilitySpec('excel.' + operation, descriptions[operation],
            {'type': 'object', 'properties': props, 'required': ['path'], 'additionalProperties': False},
            {'type': 'object'}, 'READ' if operation == 'inspect' else 'WRITE', timeout_ms=120000,
            retry_safe=operation == 'inspect')

    async def preflight(self, ctx, inputs):
        from .files import path_for
        path_for(ctx, inputs['path'], existing=self.operation != 'create', writing=self.operation in ('create', 'write'))
        return []

    async def execute(self, ctx, inputs):
        from . import workbooks
        stopped = threading.Event()
        local = SimpleNamespace(environment=ctx.environment, task_parameters=ctx.task_parameters,
                                datasets=ctx.datasets, cancelled=lambda: stopped.is_set() or ctx.cancelled())
        try:
            return await asyncio.to_thread(getattr(workbooks, self.operation), local, inputs)
        except asyncio.CancelledError:
            stopped.set()
            raise

    async def verify(self, ctx, inputs, output):
        return []


class ExcelPlugin:
    def manifest(self):
        return {'id': 'excel', 'name': 'Excel', 'api_version': 1, 'package_version': '0.1.0', 'core_requires': '>=0.1,<1',
                'dependencies': {'dataset': '>=0.1,<1'},
                'config_variables': [{'key': 'excel_root', 'type': 'string', 'required': True,
                                      'description': '允许读取、新建和写入 Excel 的本地目录'}]}

    def actions(self):
        return {'excel.' + op: ExcelAction(op) for op in ('inspect', 'read', 'create', 'write')}

    def tools(self):
        return {}

    def result_handlers(self):
        return {}

    def resource_providers(self):
        return {}

    def authoring(self, selected_ids):
        return AuthoringContribution(
            'excel 处理 excel_root 内的 .xlsx，依赖内部 dataset 插件，不连接数据库。inspect 查看工作表；'
            'read 输入 path/sheet/range，默认首行为表头，返回 dataset 引用供后续步骤绑定。header=false 需 columns。'
            '默认读取公式缓存，缺缓存报错；formula_mode=formulas 读取公式文本，不计算公式。'
            'create 新建文件，可带 values 二维数组或 dataset 引用（不能同时提供）；write 写入既有文件，'
            'start_cell 默认 A1，sheet 不存在需 create_sheet=true；include_header 默认 true。'
            '原地 write 需用户目标要求并传 overwrite=true，另存使用 output_path；新建/另存目标存在即报错。'
            '默认字符串按文本写，明确需要公式时才 formulas=true；长编号/精确金额用文本。'
            '图表/宏/外部链接等复杂工作簿拒绝修改。超限失败，不以截断数据导出。'
            '返回相对路径、写入行列数、大小；读取的 dataset 在步骤成功时保存，不能跨运行复用。',
            examples=('''async def run(ctx, inputs):
    result = await ctx.call("excel.read", {"path": inputs["path"], "sheet": inputs["sheet"]})
    return ctx.result(data=result)''',))

    async def collect_context(self, provider_id, ctx, request, *, include_view=True):
        raise PluginError('CONTEXT_PROVIDER_UNAVAILABLE')

    async def lint(self, document):
        return []

    async def diagnose(self, error, refs):
        return []
