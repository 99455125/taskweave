"""Host-owned immutable dataset snapshots, committed with step results."""
import copy
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from taskweave.core.dataset_contracts import table_values, MAX_ROWS
from taskweave.core.validation import TaskError, valid_id


def table_name(dataset_id):
    return 'p_dataset_' + valid_id(dataset_id).replace('-', '')


def stored_snapshot(db, locator, run_id, step_id, attempt_id):
    if not re.fullmatch(r'p_dataset_[0-9a-f]{32}', locator):
        raise TaskError('DATASET_REFERENCE_INVALID')
    meta = db.execute('SELECT payload_json FROM step_outputs WHERE run_id=? AND step_id=? AND attempt_id=? AND name=?',
                      (run_id, step_id, attempt_id, '__dataset_' + locator[10:])).fetchone()
    if meta is None:
        raise TaskError('DATASET_UNAVAILABLE')
    snapshot = json.loads(meta[0])
    columns = snapshot['columns']
    names = ','.join('"c' + str(i) + '"' for i in range(len(columns)))
    rows = db.execute(f'SELECT {names} FROM "{locator}" WHERE run_id=? AND step_id=? AND attempt_id=? ORDER BY row_index',
                      (run_id, step_id, attempt_id)).fetchall()
    if len(rows) != snapshot['row_count']:
        raise TaskError('DATASET_UNAVAILABLE')
    snapshot['rows'] = [[bool(v) if col['type'] == 'boolean' and v is not None else v
                         for col, v in zip(columns, row)] for row in rows]
    for row_index, col_index in snapshot.pop('boolean_cells', []):
        snapshot['rows'][row_index][col_index] = bool(snapshot['rows'][row_index][col_index])
    return snapshot


def table_view(snapshot, offset=0, limit=1000):
    columns = snapshot['columns']
    rows = snapshot['rows'][offset:offset + limit]
    return {'name': snapshot['name'], 'columns': [{'key': c['name'], 'label': c['name'], 'type': c['type']} for c in columns],
            'rows': [dict(zip([c['name'] for c in columns], row)) for row in rows],
            'row_count': len(rows), 'total': len(snapshot['rows']), 'offset': offset,
            'truncated': offset > 0 or offset + len(rows) < len(snapshot['rows'])}


class Datasets:
    def __init__(self, home, scope):
        self.home, self.scope = Path(home), scope
        self.pending = {}
        self.authorized = set()
        self.size = 0
        self.cancelled = lambda: False

    def check_cancelled(self):
        if self.cancelled():
            raise TaskError('CANCELLED')

    def authorize_inputs(self, value):
        if isinstance(value, dict):
            if value.get('kind') == 'dataset':
                self.authorized.add(json.dumps(value, sort_keys=True))
            for child in value.values():
                self.authorize_inputs(child)
        elif isinstance(value, list):
            for child in value:
                self.authorize_inputs(child)

    def create(self, name, columns, rows):
        self.check_cancelled()
        columns, rows, size = table_values(name, columns, rows)
        if len(self.pending) >= 16 or self.size + size > 32 * 1024 * 1024:
            raise TaskError('DATASET_LIMIT', '单步骤数据集暂存超过上限')
        ref = {'kind': 'dataset', 'version': 1, 'dataset_id': str(uuid4()),
               **{key: getattr(self.scope, key) for key in ('task_id', 'run_id', 'step_id', 'attempt_id')}}
        snapshot = {'ref': ref, 'name': name, 'columns': columns, 'rows': rows, 'row_count': len(rows)}
        self.check_cancelled()
        self.pending[ref['dataset_id']] = snapshot
        self.size += size
        return copy.deepcopy(ref)

    def snapshot(self, ref):
        self.check_cancelled()
        keys = {'kind', 'version', 'dataset_id', 'task_id', 'run_id', 'step_id', 'attempt_id'}
        if (not isinstance(ref, dict) or set(ref) != keys or ref['kind'] != 'dataset'
                or type(ref['version']) is not int or ref['version'] != 1):
            raise TaskError('DATASET_REFERENCE_INVALID')
        for key in keys - {'kind', 'version'}:
            valid_id(ref[key])
        if ref['task_id'] != self.scope.task_id or ref['run_id'] != self.scope.run_id:
            raise TaskError('DATASET_SCOPE_DENIED')
        current = self.pending.get(ref['dataset_id'])
        if current and current['ref'] == ref:
            return copy.deepcopy(current)
        if json.dumps(ref, sort_keys=True) not in self.authorized:
            raise TaskError('DATASET_INPUT_REQUIRED', '只可访问本步骤绑定的输入数据集')
        control = self.home / 'taskweave.db'
        path = self.home / 'tasks' / ref['task_id'] / 'data.db'
        if not control.is_file() or not path.is_file():
            raise TaskError('DATASET_UNAVAILABLE')
        with closing(sqlite3.connect(control.as_uri() + '?mode=ro', uri=True)) as db:
            row = db.execute("SELECT 1 FROM step_attempts a JOIN result_refs r ON r.attempt_id=a.attempt_id WHERE a.attempt_id=? AND a.run_id=? AND a.step_id=? AND a.valid=1 AND a.status='SUCCEEDED' AND r.result_id=? AND r.task_id=? AND r.state='AVAILABLE' AND r.handler_id='dataset.table'",
                             (ref['attempt_id'], ref['run_id'], ref['step_id'], ref['dataset_id'], ref['task_id'])).fetchone()
        if row is None:
            raise TaskError('DATASET_UNAVAILABLE', '来源执行已失效或结果不可用')
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
            return stored_snapshot(db, table_name(ref['dataset_id']), ref['run_id'], ref['step_id'], ref['attempt_id'])

    def describe(self, ref):
        snapshot = self.snapshot(ref)
        return {key: snapshot[key] for key in ('name', 'columns', 'row_count')}

    def read(self, ref, offset=0, limit=1000):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= MAX_ROWS:
            raise TaskError('DATASET_PAGE_INVALID')
        return table_view(self.snapshot(ref), offset, limit)

    def query(self, sources, sql, params=(), name='查询结果'):
        from taskweave.infrastructure.dataset_sql import run_sql
        return run_sql(self, sources, sql, params, name)

    def execute(self, ref, sql, params=(), name='处理结果'):
        from taskweave.infrastructure.dataset_sql import run_sql
        return run_sql(self, {'data': ref}, sql, params, name, write=True)

    def persist(self, db, results):
        refs = []
        for dataset_id, snapshot in self.pending.items():
            self.check_cancelled()
            table = table_name(dataset_id)
            columns = snapshot['columns']
            definitions = ','.join('"c' + str(i) + '"' for i in range(len(columns)))
            db.execute(f'CREATE TABLE "{table}" (run_id TEXT, step_id TEXT, attempt_id TEXT, row_index INTEGER, {definitions})')
            values = (self.scope.run_id, self.scope.step_id, self.scope.attempt_id)
            marks = ','.join('?' for _ in range(len(columns) + 4))
            db.executemany(f'INSERT INTO "{table}" VALUES({marks})',
                           ((*values, i, *row) for i, row in enumerate(snapshot['rows'])))
            db.execute('INSERT INTO plugin_table_schemas(table_name) VALUES(?)', (table,))
            metadata = {k: v for k, v in snapshot.items() if k != 'rows'}
            metadata['boolean_cells'] = [[i, j] for i, row in enumerate(snapshot['rows']) for j, value in enumerate(row)
                                         if type(value) is bool and columns[j]['type'] == 'any']
            results._json(db, '__dataset_' + dataset_id.replace('-', ''), metadata)
            refs.append({'result_id': dataset_id, 'handler_id': 'dataset.table', 'kind': 'table',
                         'locator': table, 'name': 'dataset_' + dataset_id.replace('-', ''), 'media_type': 'application/json'})
        return refs
