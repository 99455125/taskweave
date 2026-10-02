"""Explicit write SQL execution; existing read-only actions stay independent."""
import asyncio
import json
import time
from taskweave.plugins.sdk import CapabilitySpec, PluginError
from . import configuration, wire_value

MAX_SQL_BYTES = 1024 * 1024
MAX_STATEMENTS = 100


def script_plan(inputs):
    """Parse for classification, but send original text and bound values to SQL."""
    from sqlglot import exp, parse_one, tokenize
    from sqlglot.tokens import TokenType
    sql = inputs.get('sql')
    mode = inputs.get('mode', 'transaction')
    if not isinstance(sql, str) or not sql.strip() or len(sql.encode('utf-8')) > MAX_SQL_BYTES:
        raise PluginError('TIDB_SQL_INVALID', 'SQL 不能为空且不得超过 1MB')
    if mode not in {'transaction', 'autocommit'}:
        raise PluginError('TIDB_SQL_INVALID', 'mode 只能是 transaction 或 autocommit')
    try:
        tokens = tokenize(sql, read='mysql')
        # MySQL/TiDB executable comments must not evade the DDL/control check.
        if any(comment.lstrip().startswith(('!', 'T!', 't!')) for token in tokens for comment in token.comments):
            raise ValueError()
        ends = [token.start for token in tokens if token.token_type == TokenType.SEMICOLON] + [len(sql)]
        parts, start = [], 0
        for end in ends:
            text = sql[start:end].strip()
            start = end + 1
            local_tokens = tokenize(text, read='mysql')
            if not local_tokens:
                continue
            parser_sql = text.replace('%s', '?')
            first = local_tokens[0]
            # sqlglot's MySQL parser treats REPLACE as an opaque command.
            # Classify its INSERT-equivalent structure; never rewrite driver SQL.
            if first.text.upper() == 'REPLACE':
                parser_sql = parser_sql[:first.start] + 'INSERT' + parser_sql[first.end + 1:]
            tree = parse_one(parser_sql, read='mysql', error_message_context=0)
            transactional = isinstance(tree, (exp.Select, exp.Union, exp.Intersect, exp.Except,
                                               exp.Insert, exp.Update, exp.Delete, exp.Show, exp.Describe))
            ddl = isinstance(tree, (exp.Create, exp.Alter, exp.Drop, exp.TruncateTable))
            if not transactional and not ddl or tree.find(exp.Into):
                raise ValueError()
            if mode == 'transaction' and ddl:
                raise PluginError('TIDB_DDL_REQUIRES_AUTOCOMMIT', 'DDL 无法事务回滚；请显式选择 mode=autocommit，失败时可能已部分提交')
            parts.append((text, first.text.upper(), len(list(tree.find_all(exp.Placeholder)))))
        if not 1 <= len(parts) <= MAX_STATEMENTS:
            raise ValueError()
    except PluginError:
        raise
    except Exception:
        # Parser diagnostics may contain SQL literals; suppress chained details.
        raise PluginError('TIDB_SQL_INVALID', '支持 SELECT/SHOW/EXPLAIN、INSERT/REPLACE/UPDATE/DELETE 与显式 autocommit 的 CREATE/ALTER/DROP/TRUNCATE；禁止事务控制、可执行注释和客户端 DELIMITER，最多 100 条') from None
    if 'params' in inputs and 'statement_params' in inputs:
        raise PluginError('TIDB_PARAMS_INVALID', 'params 和 statement_params 不能同时提供')
    if 'params' in inputs:
        if len(parts) != 1:
            raise PluginError('TIDB_PARAMS_INVALID', '多语句请使用一条 SQL 对应一组的 statement_params')
        groups = [inputs['params']]
    else:
        groups = inputs.get('statement_params', [[] for _ in parts])
    if not isinstance(groups, list) or len(groups) != len(parts):
        raise PluginError('TIDB_PARAMS_INVALID', 'statement_params 数量须与有效 SQL 条数相同')
    for index, ((_, _, count), values) in enumerate(zip(parts, groups), 1):
        if not isinstance(values, list) or len(values) != count or any(type(value) not in (str, int, float, bool, type(None)) for value in values):
            raise PluginError('TIDB_PARAMS_INVALID', f'第 {index} 条 SQL 的 %s 占位符与标量参数数量不符')
    return mode, [(text, command, values or None) for (text, command, _), values in zip(parts, groups)]


def execute_script(ctx, inputs, config, mode, plan):
    import certifi
    import pymysql
    settings = {'host': config['host'], 'port': config['port'], 'user': config['username'],
        'password': config.get('password', ''), 'database': config['database'], 'charset': 'utf8mb4',
        'cursorclass': pymysql.cursors.SSCursor, 'autocommit': mode == 'autocommit',
        'connect_timeout': config['timeout_seconds'], 'read_timeout': config['timeout_seconds'],
        'write_timeout': config['timeout_seconds']}
    if config['tls']:
        settings.update(ssl_ca=config.get('ssl_ca') or certifi.where(), ssl_verify_cert=True, ssl_verify_identity=True)
    connection = None
    completed, index, phase = 0, 0, 'connect'
    started = time.monotonic()
    max_rows = min(inputs.get('max_rows', config['max_rows']), config['max_rows'])
    remaining_rows = max_rows
    results = []
    try:
        if ctx.cancelled():
            raise PluginError('CANCELLED')
        connection = pymysql.connect(**settings)
        if mode == 'transaction':
            connection.begin()
        with connection.cursor() as cursor:
            for index, (sql, command, params) in enumerate(plan, 1):
                phase = 'execute'
                if ctx.cancelled():
                    raise PluginError('CANCELLED')
                if time.monotonic() - started >= 60:
                    raise PluginError('TIDB_EXECUTION_TIMEOUT', 'SQL 脚本超过执行时间，停止后续语句')
                cursor.execute(sql, params)
                # In autocommit mode the statement can already be committed,
                # even if reading or encoding its output fails afterwards.
                completed += 1
                result = {'index': index, 'command': command, 'affected_rows': 0, 'table': None}
                if cursor.description:
                    fields = [item[0] for item in cursor.description]
                    if len(fields) != len(set(fields)):
                        raise PluginError('TIDB_COLUMNS_AMBIGUOUS', '查询包含重名字段，请使用 AS 指定不同名称')
                    fetched = cursor.fetchmany(remaining_rows + 1)
                    rows = [dict(zip(fields, wire_value(row))) for row in fetched[:remaining_rows]]
                    result['table'] = {'columns': [{'key': field, 'label': field} for field in fields],
                        'rows': rows, 'row_count': len(rows), 'truncated': len(fetched) > remaining_rows}
                    remaining_rows -= len(rows)
                else:
                    result['affected_rows'] = max(0, cursor.rowcount)
                results.append(result)
            # Validate JSON before committing: a broken report must not commit
            # writes and then fail only when the worker serializes its output.
            json.dumps(results, allow_nan=False)
            if ctx.cancelled():
                raise PluginError('CANCELLED')
            if mode == 'transaction':
                phase = 'commit'
                connection.commit()
        return {'mode': mode, 'commit_state': 'COMMITTED', 'statement_count': len(results),
            'affected_rows': sum(item['affected_rows'] for item in results), 'statements': results,
            'database': config['database'], 'elapsed_ms': round((time.monotonic() - started) * 1000)}
    except Exception as exc:
        code = exc.args[0] if isinstance(exc, pymysql.MySQLError) and exc.args and isinstance(exc.args[0], int) else getattr(exc, 'code', type(exc).__name__)
        if connection is None:
            if isinstance(exc, PluginError):
                raise
            raise PluginError('TIDB_EXECUTE_FAILED', f'TiDB 连接失败，数据库错误码：{code}；未提交 SQL') from None
        if mode == 'autocommit':
            raise PluginError('TIDB_EXECUTE_PARTIAL_OR_UNKNOWN', f'第 {index} 条 SQL 未完整完成，已完成 {completed} 条；错误码：{code}。可能已部分提交，请核对数据库后再决定，不能自动重试') from None
        rolled_back = False
        try:
            connection.rollback()
            rolled_back = True
        except Exception:
            pass
        if phase == 'commit' or not rolled_back:
            raise PluginError('TIDB_EXECUTE_UNKNOWN', f'SQL 提交/回滚结果未知，错误码：{code}；请核对数据库，不能自动重试') from None
        if isinstance(exc, PluginError) and exc.code == 'CANCELLED':
            raise PluginError('CANCELLED', 'SQL 执行已取消，事务已回滚') from None
        raise PluginError('TIDB_EXECUTE_FAILED', f'第 {index} 条 SQL 失败，事务已回滚；错误码：{code}') from None
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                # Closing a connection after commit must not turn an observed
                # committed transaction into an apparent failed transaction.
                pass


class ExecuteSQL:
    spec = CapabilitySpec('tidb.execute_sql',
        '显式执行参数化 SQL 或脚本；默认整批事务提交，DDL 需显式 autocommit，写入不自动重试',
        {'type': 'object', 'properties': {
            'sql': {'type': 'string', 'minLength': 1, 'maxLength': MAX_SQL_BYTES},
            'mode': {'enum': ['transaction', 'autocommit']},
            'params': {'type': 'array', 'items': {'type': ['string', 'number', 'boolean', 'null']}},
            'statement_params': {'type': 'array', 'maxItems': MAX_STATEMENTS,
                                 'items': {'type': 'array', 'items': {'type': ['string', 'number', 'boolean', 'null']}}},
            'max_rows': {'type': 'integer', 'minimum': 1, 'maximum': 10000},
        }, 'required': ['sql'], 'additionalProperties': False},
        {'type': 'object', 'properties': {
            'mode': {'enum': ['transaction', 'autocommit']}, 'commit_state': {'const': 'COMMITTED'},
            'statement_count': {'type': 'integer'}, 'affected_rows': {'type': 'integer'},
            'statements': {'type': 'array', 'items': {'type': 'object', 'properties': {
                'index': {'type': 'integer'}, 'command': {'type': 'string'}, 'affected_rows': {'type': 'integer'},
                'table': {'type': ['object', 'null']},
            }, 'required': ['index', 'command', 'affected_rows', 'table'], 'additionalProperties': False}},
            'database': {'type': 'string'}, 'elapsed_ms': {'type': 'number'},
        }, 'required': ['mode', 'commit_state', 'statement_count', 'affected_rows', 'statements', 'database', 'elapsed_ms'],
            'additionalProperties': False}, 'WRITE', timeout_ms=65000, retry_safe=False)

    async def preflight(self, ctx, inputs):
        configuration(ctx)
        await asyncio.to_thread(script_plan, inputs)
        return []

    async def execute(self, ctx, inputs):
        config = configuration(ctx)
        mode, plan = await asyncio.to_thread(script_plan, inputs)
        return await asyncio.to_thread(execute_script, ctx, inputs, config, mode, plan)

    async def verify(self, ctx, inputs, output): return []
