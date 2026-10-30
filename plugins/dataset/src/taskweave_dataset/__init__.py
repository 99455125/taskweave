"""Internal dataset actions; persistence and SQL belong to the host port."""
import asyncio
from taskweave.plugins.sdk import AuthoringContribution, CapabilitySpec, PluginError


REF = {'type': 'object', 'properties': {
    'kind': {'const': 'dataset'}, 'version': {'const': 1},
    **{k: {'type': 'string'} for k in ('dataset_id', 'task_id', 'run_id', 'step_id', 'attempt_id')}},
    'required': ['kind', 'version', 'dataset_id', 'task_id', 'run_id', 'step_id', 'attempt_id'], 'additionalProperties': False}
NAME = {'type': 'string', 'minLength': 1, 'maxLength': 128}
COLUMNS = {'type': 'array', 'minItems': 1, 'maxItems': 256, 'items': {'type': 'object',
    'properties': {'name': NAME, 'type': {'enum': ['any', 'text', 'integer', 'number', 'boolean']}},
    'required': ['name'], 'additionalProperties': False}}
SCALAR = {'type': ['string', 'number', 'boolean', 'null']}
ROWS = {'type': 'array', 'maxItems': 100000, 'items': {'type': 'array', 'maxItems': 256, 'items': SCALAR}}
SQL = {'type': 'string', 'minLength': 1, 'maxLength': 65536}
PARAMS = {'type': 'array', 'items': SCALAR}


class DatasetAction:
    def __init__(self, operation):
        self.operation = operation
        props, required, output = {'dataset': REF}, ['dataset'], {'type': 'object'}
        if operation == 'create':
            props, required, output = {'name': NAME, 'columns': COLUMNS, 'rows': ROWS}, ['name', 'columns', 'rows'], REF
        elif operation == 'read':
            props.update(offset={'type': 'integer', 'minimum': 0}, limit={'type': 'integer', 'minimum': 1, 'maximum': 100000})
        elif operation in ('query', 'execute'):
            props = {'sql': SQL, 'params': PARAMS, 'name': NAME}
            if operation == 'query':
                props['sources'] = {'type': 'object', 'minProperties': 1, 'maxProperties': 16, 'additionalProperties': REF}
                required = ['sources', 'sql']
            else:
                props['dataset'] = REF
                required = ['dataset', 'sql']
            output = REF
        descriptions = {'create': '创建内部数据集，步骤成功时保存', 'describe': '查看数据集列结构与行数',
                        'read': '分页读取内部数据集', 'query': '对输入数据集执行只读 SQL，保存为新数据集',
                        'execute': '以 data 为表名执行单条增删改 SQL，保存副本并保留源数据集'}
        self.spec = CapabilitySpec('dataset.' + operation, descriptions[operation],
            {'type': 'object', 'properties': props, 'required': required, 'additionalProperties': False},
            output, 'READ' if operation in ('read', 'describe') else 'WRITE', timeout_ms=30000,
            retry_safe=operation in ('read', 'describe'))

    async def preflight(self, ctx, inputs):
        if not hasattr(ctx, 'datasets'):
            raise PluginError('DATASET_HOST_REQUIRED')
        return []

    async def execute(self, ctx, inputs):
        store, op = ctx.datasets, self.operation
        if op == 'create':
            return await asyncio.to_thread(store.create, inputs['name'], inputs['columns'], inputs['rows'])
        if op == 'describe':
            return await asyncio.to_thread(store.describe, inputs['dataset'])
        if op == 'read':
            return await asyncio.to_thread(store.read, inputs['dataset'], inputs.get('offset', 0), inputs.get('limit', 1000))
        if op == 'query':
            return await asyncio.to_thread(store.query, inputs['sources'], inputs['sql'], inputs.get('params', []), inputs.get('name', '查询结果'))
        return await asyncio.to_thread(store.execute, inputs['dataset'], inputs['sql'], inputs.get('params', []), inputs.get('name', '处理结果'))

    async def verify(self, ctx, inputs, output):
        return []


class DatasetResult:
    def schema(self):
        return {}

    def prepare(self, request):
        raise PluginError('DATASET_HOST_REQUIRED', '数据集由宿主提交，不接受手工 ctx.output')

    def parse(self, stored):
        return stored

    def preview(self, parsed):
        return parsed


class DatasetPlugin:
    def manifest(self):
        return {'id': 'dataset', 'name': '内部数据集', 'api_version': 1, 'package_version': '0.1.0', 'core_requires': '>=0.1,<1'}

    def actions(self):
        return {'dataset.' + op: DatasetAction(op) for op in ('create', 'describe', 'read', 'query', 'execute')}

    def tools(self):
        return {}

    def result_handlers(self):
        return {'dataset.table': DatasetResult()}

    def resource_providers(self):
        return {}

    def authoring(self, selected_ids):
        return AuthoringContribution(
            'dataset 是任务内部数据集，无连接地址/账号。create 输入 name、columns（name/type）、二维 rows，返回引用。'
            '步骤 data 保存引用并通过绑定传递；只可使用本步输入或本步新建引用，禁止伪造/跨运行复用。'
            'describe 查看列结构；read 返回 columns/rows/total/offset/truncated，预览默认1000行，截断不能用于完整导出。'
            'query 输入 sources 别名到引用的映射、单条 SELECT/CTE、params，返回新引用。execute 输入 dataset、'
            '对 data 表的单条 INSERT/UPDATE/DELETE、params，返回修改后的副本；不改变源。SQL参数用 ?；中文列名用双引号。'
            '不支持DDL/ATTACH/PRAGMA/扩展/外部库，行数超限报错；精确金额使用文本或整数。'
            '数据集在步骤成功时落库，read结果可用core.table展示。Excel读取/导出复用同一引用。',
            examples=('''async def run(ctx, inputs):
    result = await ctx.call("dataset.query", {"sources": {"items": inputs["dataset"]}, "sql": "SELECT * FROM items WHERE amount > ?", "params": [0]})
    return ctx.result(data={"dataset": result})''',))

    async def collect_context(self, provider_id, ctx, request, *, include_view=True):
        raise PluginError('CONTEXT_PROVIDER_UNAVAILABLE')

    async def lint(self, document):
        return []

    async def diagnose(self, error, refs):
        return []
