"""Pure recursive object updates; arrays and scalar values replace."""
from copy import deepcopy
from taskweave.plugins.sdk import PluginError


def merge_json(original, changes):
    if not isinstance(original, dict) or not isinstance(changes, dict):
        raise PluginError('NACOS_JSON_OBJECT_REQUIRED', '配置和增量内容必须是 JSON 对象')
    result = deepcopy(original)
    for key, value in changes.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_json(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def parse_json(content):
    import json

    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate key')
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError('non-finite number')

    try:
        value = json.loads(content, object_pairs_hook=unique_pairs, parse_constant=invalid_constant)
        if not isinstance(value, dict):
            raise ValueError('object required')
        return value
    except (TypeError, ValueError, RecursionError):
        raise PluginError('NACOS_JSON_INVALID', '配置或增量内容不是有效且无重复字段的 JSON') from None


def patch_json(content, changes):
    import json
    try:
        return json.dumps(merge_json(parse_json(content), changes), ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    except (TypeError, ValueError, RecursionError):
        raise PluginError('NACOS_JSON_INVALID', '增量内容不是有效 JSON') from None
