"""TiDB action and context assembly; legacy database imports remain available."""
import asyncio
import json
from taskweave.plugins.sdk import AuthoringContribution, CapabilitySpec, ContextCollection, ContextItem, ContextView, PluginError
from .database import configuration, select_sql, wire_value, query_database


class DatabaseAction:
    def __init__(self, operation):
        self.operation = operation
        props = {}
        required = []
        if operation == 'query':
            props = {'sql': {'type': 'string', 'minLength': 1}, 'params': {'type': 'array'}, 'title': {'type': 'string'}, 'max_rows': {'type': 'integer', 'minimum': 1, 'maximum': 10000}}
            required = ['sql']
        elif operation == 'describe_table':
            props = {'table': {'type': 'string', 'minLength': 1}, 'database': {'type': 'string'}}
            required = ['table']
        output = {'type':'object','properties':{'title':{'type':'string'},'columns':{'type':'array','items':{'type':'object','properties':{'key':{'type':'string'},'label':{'type':'string'}},'required':['key','label']}},'rows':{'type':'array','items':{'type':'object'}},'row_count':{'type':'integer'},'truncated':{'type':'boolean'},'query_info':{'type':'object','properties':{'sql':{'type':'string'},'parameter_count':{'type':'integer'},'database':{'type':'string'},'elapsed_ms':{'type':'number'}},'required':['sql','parameter_count','database','elapsed_ms']}},'required':['title','columns','rows','row_count','truncated','query_info']}
        self.spec = CapabilitySpec('tidb.' + operation, {'query': '参数化只读查询，返回可展示的表格和查询信息', 'describe_table': '读取表字段、类型、默认值与注释', 'test_connection': '测试数据库连接，返回版本与当前数据库'}[operation], {'type': 'object', 'properties': props, 'required': required, 'additionalProperties': False}, output, 'READ', timeout_ms=65000, retry_safe=True)

    async def preflight(self, ctx, inputs):
        configuration(ctx)
        if self.operation == 'query': select_sql(inputs['sql'])
        return []

    async def execute(self, ctx, inputs):
        config = configuration(ctx)
        if ctx.cancelled(): raise PluginError('CANCELLED')
        if self.operation == 'query':
            sql = inputs['sql']; select_sql(sql)
            params = inputs.get('params', [])
            title = inputs.get('title', '查询结果')
        elif self.operation == 'describe_table':
            sql = 'SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT, COLUMN_COMMENT FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s ORDER BY ORDINAL_POSITION'
            params = [inputs.get('database') or config['database'], inputs['table']]
            title = inputs['table'] + ' · 表结构'
        else:
            sql = 'SELECT VERSION() AS version, DATABASE() AS database_name'
            params = []; title = '连接信息'
        return await asyncio.to_thread(query_database, config, sql, params, title, min(inputs.get('max_rows', config['max_rows']), config['max_rows']))

    async def verify(self, ctx, inputs, output): return []


class TiDBPlugin:
    def manifest(self):
        variables = [('connection_url', 'string', False, '可选 mysql://账号:密码@主机:4000/数据库；也可分项配置'), ('host', 'string', False, '数据库主机；不用连接串时必填'), ('port', 'integer', False, '端口，默认 4000'), ('database', 'string', False, '数据库名称；不用连接串时必填'), ('username', 'string', False, '数据库账号；不用连接串时必填'), ('password', 'string', False, '数据库密码，本地变量配置'), ('tls', 'boolean', False, 'TLS，默认 true；本地未启用 TLS 的数据库可设置 false'), ('ssl_ca', 'string', False, '可选 CA 证书路径'), ('timeout_seconds', 'integer', False, '连接及读写超时，默认 15 秒，最大 60'), ('max_rows', 'integer', False, '最多保存行数，默认 1000，最大 10000')]
        return {'id': 'tidb', 'api_version': 1, 'package_version': '0.2.0', 'core_requires': '>=0.1,<1', 'context_requests': {'tidb.schema': {'type': 'object', 'properties': {'table': {'type': 'string'}, 'database': {'type': 'string'}}, 'required': ['table'], 'x-taskweave-context-view': {'default': True}}}, 'config_variables': [{'key': 'tidb_' + key, 'type': kind, 'required': required, 'description': description} for key, kind, required, description in variables]}
    def actions(self):
        from .execution import ExecuteSQL
        return {**{'tidb.' + op: DatabaseAction(op) for op in ('query', 'describe_table', 'test_connection')}, 'tidb.execute_sql': ExecuteSQL()}
    def tools(self): return {'tidb.describe_table': DatabaseAction('describe_table')}
    def result_handlers(self): return {}
    def resource_providers(self): return {}
    def result_views(self): return {'tidb.table': {'type': 'table', 'description': '查询结果表格：columns 和 rows'}, 'tidb.verification': {'type': 'report', 'description': '核对报告：passed/message/tables，每个表有 title/columns/rows；可选 query_info'}}
    def authoring(self, selected_ids):
        example = '''async def run(ctx, inputs):
    table = await ctx.call("tidb.query", {"sql": "SELECT order_no, status FROM orders WHERE order_no = %s", "params": [inputs["order_no"]], "title": "通用示例信息"})
    passed = not table["truncated"] and len(table["rows"]) == 1 and table["rows"][0]["status"] == "SUBMITTED"
    report = {"passed": passed, "message": "通用示例核对通过" if passed else "通用示例核对未通过", "tables": [table], "query_info": table["query_info"]}
    return ctx.result(data={"order_no": inputs["order_no"], "verified": passed, "report": report}, views=[{"title": "通用示例核对", "renderer": "tidb.verification", "pointer": "/report"}])'''
        instructions = 'TiDB 连接由运行时提供，不把账号、密码、连接串放入参数、源码、返回或报告。tidb.query 使用 sql、params 及可选 title/max_rows；业务值用 %s 和 params 绑定，禁止字符串拼接。只允许单条只读 SELECT。表和字段必须来自结构上下文或结构工具。结果含 title、columns、rows、row_count、truncated、query_info；Decimal 为字符串、日期为 ISO 字符串。核对遵循步骤规格，区分零行、多行和 truncated。后续数据放 data；用户需要查看时用 tidb.table 或 tidb.verification 并提供明确标题。是否将不匹配视为失败由步骤规格决定；连接或查询异常不能伪装为核对成功。'
        examples = [example]
        if 'tidb.execute_sql' in selected_ids:
            instructions += ' 写操作使用独立 tidb.execute_sql，不扩大 tidb.query 的只读权限。execute_sql 接收 sql，单条 params 或按语句对应的 statement_params，默认 mode=transaction 全部成功才提交；CREATE/ALTER/DROP/TRUNCATE 必须由用户明确要求并使用 mode=autocommit，不能声称 DDL 可回滚。SQL 文件读取的完整 content 通过步骤绑定传入，插件不直接调用文件插件。业务值仍用 %s 绑定。禁止在脚本中自带 BEGIN/COMMIT/ROLLBACK/SET/DELIMITER，可执行注释不支持。每个脚本最大1MB/100条，查询行数上限在整批共享；truncated 必须如实处理。返回 commit_state、statement_count、affected_rows 和逐条 statements（含可选 table），不回传 SQL/参数值。写入异常、提交结果未知或部分提交时必须核对外部结果，不能盲目自动重试；成功表示数据库提交成功，业务目标仍需按规格查询核对。'
            examples.append('''async def run(ctx, inputs):
    result = await ctx.call("tidb.execute_sql", {"sql": inputs["sql_text"], "mode": "transaction"})
    return ctx.result(data=result)''')
        return AuthoringContribution(instructions, tuple(examples), tool_ids=('tidb.describe_table',), context_provider_ids=('tidb.schema',), channel_overrides={'web_chat': {'instructions': '本渠道不能访问本地数据库。只使用已提供的表结构和业务要求生成代码；缺少必要结构时指出具体缺项，不声称已经查询。'}})
    async def lint(self, document): return []
    async def collect_context(self, provider_id, ctx, request, *, include_view=True):
        if provider_id != 'tidb.schema': raise PluginError('CONTEXT_PROVIDER_UNAVAILABLE')
        if not isinstance(request.get('table'), str) or not request['table']:
            raise PluginError('TIDB_CONFIG_INVALID', '采集表结构需要填写 table')
        result = await DatabaseAction('describe_table').execute(ctx, request)
        views = (ContextView(result['title'], 'tidb.table', result),) if include_view else ()
        return ContextCollection((ContextItem('text', 'application/json', json.dumps(result, ensure_ascii=False), 'tidb.schema'),), views)
    async def diagnose(self, error, refs): return []
