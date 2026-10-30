"""Lossless raw object-array drafts and typed submission conversion."""
from copy import deepcopy
import json
import math
from decimal import Decimal, InvalidOperation

from taskweave.core.validation import TaskError, validate


def supports_row_input(schema):
    """Homogeneous object rows support scalar fields and simple string lists."""
    array_keys = {'type', 'items', 'title', 'description', 'default', 'minItems', 'maxItems', 'uniqueItems'}
    object_keys = {'type', 'properties', 'required', 'additionalProperties', 'title', 'description'}
    scalar_keys = {'type', 'title', 'description', 'default', 'enum', 'const', 'minLength',
                   'maxLength', 'pattern', 'format', 'minimum', 'maximum', 'exclusiveMinimum',
                   'exclusiveMaximum', 'multipleOf'}
    if not isinstance(schema, dict) or schema.get('type') != 'array' or set(schema) - array_keys:
        return False
    item = schema.get('items')
    if not isinstance(item, dict) or item.get('type') != 'object' or set(item) - object_keys:
        return False
    if item.get('additionalProperties', False) not in (True, False):
        return False
    def supported_field(field):
        if not isinstance(field, dict):
            return False
        if field.get('type') == 'array':
            strings = field.get('items')
            return (not set(field) - array_keys and isinstance(strings, dict)
                    and strings.get('type') == 'string' and not set(strings) - scalar_keys
                    and ('enum' not in strings or all(isinstance(value, str) for value in strings['enum'])))
        return (field.get('type') in {'string', 'integer', 'number', 'boolean'}
                and not set(field) - scalar_keys
                and ('enum' not in field or all(not isinstance(value, (list, dict)) for value in field['enum'])))

    properties = item.get('properties')
    return isinstance(properties, dict) and bool(properties) and all(supported_field(field) for field in properties.values())


def raw_json(value):
    return value if isinstance(value, str) else '' if value is None else json.dumps(value, ensure_ascii=False)


def row_values(value, schema, name):
    """Convert numeric text without modifying drafts; validate every row constraint."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError as exc:
            raise TaskError('FORM_INVALID', f'{name} 需要有效 JSON') from exc
    result = deepcopy(value)
    if isinstance(result, list):
        for index, row in enumerate(result):
            if not isinstance(row, dict):
                continue
            for key, field in schema['items']['properties'].items():
                raw = row.get(key)
                if raw is None or raw == '':
                    row.pop(key, None)
                    continue
                if field['type'] in {'integer', 'number'} and isinstance(raw, str):
                    try:
                        number = Decimal(raw)
                        if not number.is_finite() or (field['type'] == 'integer' and number != number.to_integral_value()):
                            raise ValueError()
                        row[key] = int(number) if field['type'] == 'integer' else float(number)
                        if field['type'] == 'number' and not math.isfinite(row[key]):
                            raise ValueError()
                    except (ValueError, InvalidOperation, OverflowError) as exc:
                        raise TaskError('FORM_INVALID', f'{name} 第 {index + 1} 行 {key} 需要有效数值') from exc
            for key in schema['items'].get('required', []):
                if key not in row:
                    raise TaskError('FORM_INVALID', f'{name} 第 {index + 1} 行 {key} 为必录项')
    try:
        validate(result, schema)
    except TaskError as exc:
        raise TaskError('FORM_INVALID', f'{name}: {exc}') from exc
    return result
