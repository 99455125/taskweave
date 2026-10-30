"""SQL runs only over explicitly supplied snapshots in a private memory DB."""
import re
import json
import math
import sqlite3
import time
from contextlib import closing
from taskweave.core.dataset_contracts import MAX_ROWS, MAX_CELLS, MAX_BYTES
from taskweave.core.validation import TaskError


FUNCTIONS = {'abs', 'avg', 'char', 'coalesce', 'count', 'date', 'datetime', 'dense_rank', 'first_value',
             'glob', 'hex', 'ifnull', 'iif', 'instr', 'julianday', 'lag', 'last_value', 'lead', 'length',
             'like', 'lower', 'ltrim', 'max', 'min', 'nullif', 'rank', 'round', 'row_number', 'rtrim',
             'strftime', 'substr', 'substring', 'sum', 'time', 'total', 'trim', 'typeof', 'unicode', 'upper'}


def quoted(value):
    return '"' + value.replace('"', '""') + '"'


def run_sql(store, sources, sql, params, name, write=False):
    store.check_cancelled()
    if (not isinstance(sources, dict) or not 1 <= len(sources) <= 16
            or any(not isinstance(k, str) or not re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,63}', k)
                   or k.lower().startswith('sqlite_') for k in sources)
            or len({k.lower() for k in sources}) != len(sources)):
        raise TaskError('DATASET_SOURCES_INVALID')
    if not isinstance(sql, str) or not sql.strip() or len(sql.encode('utf-8')) > 65536:
        raise TaskError('DATASET_SQL_INVALID')
    if not isinstance(params, (list, tuple)) or any(v is not None and type(v) not in (str, int, float, bool) for v in params):
        raise TaskError('DATASET_PARAMETERS_INVALID')
    if any((type(v) is float and not math.isfinite(v)) or (type(v) is int and not -(2**63) <= v < 2**63)
           or (type(v) is str and len(v.encode('utf-8')) > 1024 * 1024) for v in params):
        raise TaskError('DATASET_PARAMETERS_INVALID')
    snapshots = {alias: store.snapshot(ref) for alias, ref in sources.items()}
    identity = None
    if write:
        existing_names = {c['name'].lower() for c in snapshots['data']['columns']}
        identity = next((key for key in ('_rowid_', 'oid', 'rowid') if key not in existing_names), None)
        if identity is None:
            raise TaskError('DATASET_COLUMNS_INVALID', 'execute 需要至少一个未占用的 SQLite 行号别名：rowid、_rowid_、oid')
    deadline = time.monotonic() + 10
    with closing(sqlite3.connect(':memory:')) as db:
        if hasattr(db, 'setlimit'):
            # SQLite applies LENGTH to entire rows as well as individual cells.
            db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_BYTES + 4096)
            db.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 65536)
            db.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, 257)
            db.setlimit(sqlite3.SQLITE_LIMIT_EXPR_DEPTH, 100)
        db.execute('PRAGMA temp_store=MEMORY')
        db.execute('PRAGMA max_page_count=8192')
        db.set_progress_handler(lambda: int(store.cancelled() or time.monotonic() > deadline), 1000)
        try:
            for alias, snapshot in snapshots.items():
                store.check_cancelled()
                fields = ','.join(quoted(c['name']) for c in snapshot['columns'])
                db.execute(f'CREATE TABLE {quoted(alias)} ({fields})')
                marks = ','.join('?' for _ in snapshot['columns'])
                db.executemany(f'INSERT INTO {quoted(alias)} VALUES({marks})', snapshot['rows'])
            db.commit()
        except sqlite3.Error as exc:
            store.check_cancelled()
            if time.monotonic() > deadline:
                raise TaskError('DATASET_SQL_TIMEOUT') from exc
            raise TaskError('DATASET_SQL_FAILED', '输入数据集装载失败：' + str(exc)) from exc
        writes = []

        def authorize(op, arg1, arg2, database, trigger):
            if op in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_RECURSIVE):
                return sqlite3.SQLITE_OK
            if op == sqlite3.SQLITE_READ and arg1 in snapshots:
                return sqlite3.SQLITE_OK
            if op == sqlite3.SQLITE_FUNCTION and (arg2 or '').lower() in FUNCTIONS:
                return sqlite3.SQLITE_OK
            if write and op in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE) and arg1 == 'data':
                if op == sqlite3.SQLITE_UPDATE and arg2.lower() not in existing_names:
                    return sqlite3.SQLITE_DENY
                writes.append(op)
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY

        db.set_progress_handler(lambda: int(store.cancelled() or time.monotonic() > deadline), 1000)
        try:
            db.execute('BEGIN')
            db.set_authorizer(authorize)
            cursor = db.execute(sql, params)
            if write:
                if not writes or cursor.description is not None:
                    raise TaskError('DATASET_SQL_INVALID', 'execute 需要单条 INSERT/UPDATE/DELETE，且不使用 RETURNING')
                db.set_authorizer(None)
                cursor = db.execute(f'SELECT {quoted(identity)}, * FROM data ORDER BY {quoted(identity)}')
                columns = snapshots['data']['columns']
            else:
                if cursor.description is None:
                    raise TaskError('DATASET_SQL_INVALID', 'query 需要单条只读查询')
                columns = [{'name': d[0], 'type': 'any'} for d in cursor.description]
            rows, size = [], 0
            while True:
                store.check_cancelled()
                batch = cursor.fetchmany(1000)
                if not batch:
                    break
                size += len(json.dumps(batch, ensure_ascii=False).encode('utf-8'))
                if size > MAX_BYTES:
                    raise TaskError('DATASET_LIMIT', 'SQL 结果超过 16 MiB')
                rows.extend(batch)
                if len(rows) > MAX_ROWS or len(rows) * len(columns) > MAX_CELLS:
                    raise TaskError('DATASET_LIMIT', 'SQL 结果超过上限，未返回部分数据')
            if time.monotonic() > deadline:
                raise TaskError('DATASET_SQL_TIMEOUT')
            if write:
                restored = []
                original = snapshots['data']['rows']
                for identity_value, *row in rows:
                    prior = original[identity_value - 1] if 1 <= identity_value <= len(original) else [None] * len(columns)
                    restored.append([bool(v) if type(v) is int and v in (0, 1)
                                     and (c['type'] == 'boolean' or type(old) is bool) else v
                                     for c, v, old in zip(columns, row, prior)])
                rows = restored
            return store.create(name, columns, rows)
        except (sqlite3.Error, OverflowError) as exc:
            store.check_cancelled()
            if time.monotonic() > deadline:
                raise TaskError('DATASET_SQL_TIMEOUT') from exc
            raise TaskError('DATASET_SQL_FAILED', str(exc)) from exc
