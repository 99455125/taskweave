"""TiDB read-only queries and saved reports, using the MySQL protocol."""
import asyncio
import base64
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import json
import re
import time as clock
from urllib.parse import urlsplit, unquote, parse_qs
from taskweave.plugins.sdk import AuthoringContribution, CapabilitySpec, ContextItem, PluginError


def configuration(ctx):
    values = {**ctx.environment, **ctx.task_parameters}
    config = {}
    if values.get('tidb_connection_url'):
        try:
            url = urlsplit(values['tidb_connection_url'])
            if url.scheme not in {'mysql', 'mysql+pymysql', 'tidb'} or not url.hostname:
                raise ValueError()
            config = {'host': url.hostname, 'port': url.port or 4000, 'username': unquote(url.username or ''), 'password': unquote(url.password or ''), 'database': unquote(url.path.lstrip('/'))}
            query = parse_qs(url.query)
            for key in ('tls', 'ssl_verify_cert', 'ssl_verify_identity'):
                if key in query:
                    config['tls'] = query[key][-1].lower() in {'1', 'true', 'yes'}
            if 'ssl_ca' in query:
                config['ssl_ca'] = query['ssl_ca'][-1]
        except (ValueError, TypeError) as exc:
            raise PluginError('TIDB_CONFIG_INVALID', 'TiDB 连接串格式无效') from exc
    for key in ('host', 'port', 'username', 'password', 'database', 'tls', 'ssl_ca', 'timeout_seconds', 'max_rows'):
        if 'tidb_' + key in values:
            config[key] = values['tidb_' + key]
    for key in ('host', 'username', 'database'):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise PluginError('TIDB_CONFIG_INVALID', '缺少变量 tidb_' + key)
    if not isinstance(config.get('password', ''), str):
        raise PluginError('TIDB_CONFIG_INVALID', 'tidb_password 必须是文本')
    try:
        config['port'] = int(config.get('port', 4000))
        config['timeout_seconds'] = int(config.get('timeout_seconds', 15))
        config['max_rows'] = int(config.get('max_rows', 1000))
        if not 1 <= config['port'] <= 65535 or not 1 <= config['timeout_seconds'] <= 60 or not 1 <= config['max_rows'] <= 10000:
            raise ValueError()
    except (ValueError, TypeError) as exc:
        raise PluginError('TIDB_CONFIG_INVALID', '端口、超时或最大行数无效') from exc
    if not isinstance(config.get('tls', True), bool):
        raise PluginError('TIDB_CONFIG_INVALID', 'tidb_tls 需要 true 或 false')
    config.setdefault('tls', True)
    return config


def select_sql(sql):
    from sqlglot import parse, exp
    try:
        # Driver placeholders are expressions; substituting parser-only markers
        # never changes the SQL actually sent with bound parameters.
        statements = parse(sql.replace('%s', '?'), read='mysql')
        if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.Union, exp.Intersect, exp.Except)):
            raise ValueError()
        for node in statements[0].walk():
            if isinstance(node, (exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop, exp.Alter, exp.Into, exp.Lock, exp.Command)):
                raise ValueError()
    except Exception as exc:
        raise PluginError('TIDB_READ_ONLY', '仅支持单条只读 SELECT 查询，不支持写入、锁定或导出文件') from exc


def wire_value(value):
    if isinstance(value, Decimal): return str(value)
    if isinstance(value, (datetime, date, time)): return value.isoformat()
    if isinstance(value, timedelta): return str(value)
    if isinstance(value, bytes): return {'base64': base64.b64encode(value).decode()}
    if isinstance(value, dict): return {key: wire_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)): return [wire_value(item) for item in value]
    return value


def query_database(config, sql, params, title, max_rows):
    import certifi
    import pymysql
    settings = {'host': config['host'], 'port': config['port'], 'user': config['username'], 'password': config.get('password', ''), 'database': config['database'], 'charset': 'utf8mb4', 'cursorclass': pymysql.cursors.SSCursor, 'autocommit': False, 'connect_timeout': config['timeout_seconds'], 'read_timeout': config['timeout_seconds'], 'write_timeout': config['timeout_seconds']}
    if config['tls']:
        settings.update(ssl_ca=config.get('ssl_ca') or certifi.where(), ssl_verify_cert=True, ssl_verify_identity=True)
    started = clock.monotonic()
    connection = None
    try:
        connection = pymysql.connect(**settings)
        with connection.cursor() as cursor:
            cursor.execute('SET TRANSACTION READ ONLY')
            connection.begin()
            cursor.execute(sql, params)
            fields = [item[0] for item in cursor.description or []]
            if len(fields) != len(set(fields)):
                raise PluginError('TIDB_COLUMNS_AMBIGUOUS', '查询包含重名字段，请使用 AS 指定不同名称')
            fetched = cursor.fetchmany(max_rows + 1)
            rows = [dict(zip(fields, wire_value(row))) for row in fetched[:max_rows]]
            return {'title': title, 'columns': [{'key': field, 'label': field} for field in fields], 'rows': rows, 'row_count': len(rows), 'truncated': len(fetched) > max_rows, 'query_info': {'sql': sql, 'parameter_count': len(params), 'database': config['database'], 'elapsed_ms': round((clock.monotonic() - started) * 1000)}}
    except PluginError:
        raise
    except pymysql.MySQLError as exc:
        code = exc.args[0] if exc.args and isinstance(exc.args[0], int) else 'unknown'
        raise PluginError('TIDB_QUERY_FAILED', 'TiDB 连接或查询失败，数据库错误码：' + str(code)) from exc
    finally:
        if connection is not None:
            try: connection.rollback()
            finally: connection.close()


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
        return {'id': 'tidb', 'api_version': 1, 'package_version': '0.1.0', 'core_requires': '>=0.1,<1', 'context_requests': {'tidb.schema': {'type': 'object', 'properties': {'table': {'type': 'string'}, 'database': {'type': 'string'}}, 'required': ['table']}}, 'config_variables': [{'key': 'tidb_' + key, 'type': kind, 'required': required, 'description': description} for key, kind, required, description in variables]}
    def actions(self): return {'tidb.' + op: DatabaseAction(op) for op in ('query', 'describe_table', 'test_connection')}
    def tools(self): return {'tidb.describe_table': DatabaseAction('describe_table')}
    def result_handlers(self): return {}
    def resource_providers(self): return {}
    def result_views(self): return {'tidb.table': {'type': 'table', 'description': '查询结果表格：columns 和 rows'}, 'tidb.verification': {'type': 'report', 'description': '核对报告：passed/message/tables，每个表有 title/columns/rows；可选 query_info'}}
    def authoring(self, selected_ids):
        example = '''async def run(ctx, inputs):
    table = await ctx.call("tidb.query", {"sql": "SELECT order_no, status FROM orders WHERE order_no = %s", "params": [inputs["order_no"]], "title": "订单信息"})
    passed = not table["truncated"] and len(table["rows"]) == 1 and table["rows"][0]["status"] == "SUBMITTED"
    report = {"passed": passed, "message": "订单核对通过" if passed else "订单核对未通过", "tables": [table], "query_info": table["query_info"]}
    return ctx.result(data={"order_no": inputs["order_no"], "verified": passed, "report": report}, views=[{"title": "订单核对", "renderer": "tidb.verification", "pointer": "/report"}])'''
        instructions = 'TiDB 连接由运行时提供，不把账号、密码、连接串放入参数、源码、返回或报告。tidb.query 使用 sql、params 及可选 title/max_rows；业务值用 %s 和 params 绑定，禁止字符串拼接。只允许单条只读 SELECT。表和字段必须来自结构上下文或结构工具。结果含 title、columns、rows、row_count、truncated、query_info；Decimal 为字符串、日期为 ISO 字符串。核对遵循步骤规格，区分零行、多行和 truncated。后续数据放 data；用户需要查看时用 tidb.table 或 tidb.verification 并提供明确标题。是否将不匹配视为失败由步骤规格决定；连接或查询异常不能伪装为核对成功。'
        return AuthoringContribution(instructions, (example,), tool_ids=('tidb.describe_table',), context_provider_ids=('tidb.schema',), channel_overrides={'web_chat': {'instructions': '本渠道不能访问本地数据库。只使用已提供的表结构和业务要求生成代码；缺少必要结构时指出具体缺项，不声称已经查询。'}})
    async def lint(self, document): return []
    async def collect_context(self, provider_id, ctx, request):
        if provider_id != 'tidb.schema': raise PluginError('CONTEXT_PROVIDER_UNAVAILABLE')
        if not isinstance(request.get('table'), str) or not request['table']:
            raise PluginError('TIDB_CONFIG_INVALID', '采集表结构需要填写 table')
        result = await DatabaseAction('describe_table').execute(ctx, request)
        return [ContextItem('text', 'application/json', json.dumps(result, ensure_ascii=False), 'tidb.schema')]
    async def diagnose(self, error, refs): return []
