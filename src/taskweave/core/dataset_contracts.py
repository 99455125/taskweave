"""Public, storage-independent dataset port and value validation."""
import json
import math
from typing import Protocol
from taskweave.core.validation import TaskError

MAX_ROWS = 100000
MAX_COLUMNS = 256
MAX_CELLS = 1000000
MAX_BYTES = 16 * 1024 * 1024
TYPES = ('any', 'text', 'integer', 'number', 'boolean')


class DatasetStore(Protocol):
    def create(self, name, columns, rows): ...
    def describe(self, ref): ...
    def read(self, ref, offset=0, limit=1000): ...
    def query(self, sources, sql, params=(), name='查询结果'): ...
    def execute(self, ref, sql, params=(), name='处理结果'): ...


def table_values(name, columns, rows):
    if not isinstance(name, str) or not name.strip() or len(name) > 128:
        raise TaskError('DATASET_NAME_INVALID')
    if not isinstance(columns, (list, tuple)) or not 1 <= len(columns) <= MAX_COLUMNS:
        raise TaskError('DATASET_COLUMNS_INVALID')
    normalized, seen = [], set()
    for col in columns:
        if not isinstance(col, dict) or set(col) - {'name', 'type'}:
            raise TaskError('DATASET_COLUMNS_INVALID')
        key, kind = col.get('name'), col.get('type', 'any')
        if (not isinstance(key, str) or not key.strip() or len(key) > 128 or '\x00' in key
                or key.lower() in seen or kind not in TYPES):
            raise TaskError('DATASET_COLUMNS_INVALID', '列名须非空且唯一，类型须有效')
        seen.add(key.lower())
        normalized.append({'name': key, 'type': kind})
    if not isinstance(rows, (list, tuple)) or len(rows) > MAX_ROWS or len(rows) * len(columns) > MAX_CELLS:
        raise TaskError('DATASET_LIMIT', '数据集超过行数或单元格上限')
    copied = []
    size = len(json.dumps(normalized, ensure_ascii=False).encode('utf-8'))
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) != len(columns):
            raise TaskError('DATASET_ROW_INVALID')
        for col, value in zip(normalized, row):
            kind = col['type']
            valid = value is None or (
                (type(value) is str and kind in ('any', 'text') and len(value.encode('utf-8')) <= 1024 * 1024 and '\x00' not in value)
                or (type(value) is bool and kind in ('any', 'boolean'))
                or (type(value) is int and kind in ('any', 'integer', 'number') and -(2**63) <= value < 2**63)
                or (type(value) is float and kind in ('any', 'number') and math.isfinite(value)))
            if not valid:
                raise TaskError('DATASET_VALUE_INVALID', '单元格类型或大小无效；精确金额使用文本或整数')
        size += len(json.dumps(row, ensure_ascii=False, allow_nan=False).encode('utf-8')) + 2
        if size > MAX_BYTES:
            raise TaskError('DATASET_LIMIT', '数据集超过 16 MiB')
        copied.append(list(row))
    return normalized, copied, size
