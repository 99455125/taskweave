"""Explicit, path-based changes to JSON-compatible configuration objects."""
from copy import deepcopy
from taskweave.plugins.sdk import PluginError


def apply_operations(value, operations):
    result = deepcopy(value)
    if not isinstance(result, dict) or not isinstance(operations, list) or not operations:
        raise PluginError('NACOS_OPERATION_INVALID', '配置须为对象且操作不能为空')
    for operation in operations:
        if not isinstance(operation, dict):
            raise PluginError('NACOS_OPERATION_INVALID')
        op, path = operation.get('op'), operation.get('path')
        if op not in ('set', 'remove', 'list_add', 'list_remove', 'csv_add', 'csv_remove') or not isinstance(path, list) or not path or any(not isinstance(k, str) or not k for k in path):
            raise PluginError('NACOS_OPERATION_INVALID', '操作或字段路径无效')
        if set(operation) != ({'op', 'path'} if op == 'remove' else {'op', 'path', 'value'}):
            raise PluginError('NACOS_OPERATION_INVALID', '操作参数无效')
        parent = result
        for key in path[:-1]:
            if not isinstance(parent, dict) or key not in parent:
                raise PluginError('NACOS_PATH_MISSING', '字段路径不存在')
            parent = parent[key]
        if not isinstance(parent, dict):
            raise PluginError('NACOS_PATH_INVALID', '字段父节点必须是对象')
        key = path[-1]
        if op == 'set':
            parent[key] = _yaml_value(operation['value']) if hasattr(parent, 'ca') else deepcopy(operation['value'])
            continue
        if key not in parent:
            raise PluginError('NACOS_PATH_MISSING', '字段不存在')
        if op == 'remove':
            _preserve_yaml_comments(parent, key)
            del parent[key]
            continue
        current, item = parent[key], operation['value']
        if op.startswith('list_'):
            if not isinstance(current, list):
                raise PluginError('NACOS_TYPE_MISMATCH', '目标字段不是列表')
            if op == 'list_add':
                current.append(_yaml_value(item) if hasattr(current, 'ca') else deepcopy(item))
            else:
                matches = [i for i, val in enumerate(current) if _same_json_value(val, item)]
                if len(matches) != 1:
                    raise PluginError('NACOS_ITEM_AMBIGUOUS', '待删除元素不存在或重复')
                _preserve_yaml_comments(current, matches[0])
                del current[matches[0]]
            continue
        if not isinstance(current, str) or not isinstance(item, str) or not item or ',' in item or item != item.strip():
            raise PluginError('NACOS_TYPE_MISMATCH', '逗号分隔字段及元素必须是有效字符串')
        parts = current.split(',') if current else []
        if any(not part.strip() for part in parts):
            raise PluginError('NACOS_CSV_INVALID', '逗号分隔字符串包含空项')
        if op == 'csv_add':
            parts.append(item)
        else:
            matches = [i for i, val in enumerate(parts) if val.strip() == item]
            if len(matches) != 1:
                raise PluginError('NACOS_ITEM_AMBIGUOUS', '待删除元素不存在或重复')
            del parts[matches[0]]
        joined = ','.join(parts)
        parent[key] = _yaml_value(joined) if hasattr(parent, 'ca') else joined
    return result




def _yaml_value(value):
    from ruamel.yaml.scalarstring import DoubleQuotedScalarString
    if isinstance(value, str):
        return DoubleQuotedScalarString(value)
    if isinstance(value, list):
        return [_yaml_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _yaml_value(item) for key, item in value.items()}
    return deepcopy(value)

def _same_json_value(left, right):
    import json
    try:
        a = json.loads(json.dumps(left, ensure_ascii=False, allow_nan=False))
        b = json.loads(json.dumps(right, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError):
        raise PluginError('NACOS_VALUE_UNSUPPORTED', '列表值无法安全比较') from None
    def same(x, y):
        if type(x) is not type(y):
            return False
        if isinstance(x, list):
            return len(x) == len(y) and all(same(a, b) for a, b in zip(x, y))
        if isinstance(x, dict):
            return x.keys() == y.keys() and all(same(x[k], y[k]) for k in x)
        return x == y
    return same(a, b)


def _preserve_yaml_comments(parent, key):
    if not hasattr(parent, 'ca'):
        return
    comments = parent.ca.items.get(key)
    if not comments:
        return
    token = comments[0] if isinstance(parent, list) else comments[2]
    if token is None:
        return
    lines = [line.strip()[1:].lstrip() for line in token.value.splitlines() if line.strip().startswith('#')]
    if not lines:
        return
    keys = list(range(len(parent))) if isinstance(parent, list) else list(parent)
    index = keys.index(key)
    if index + 1 < len(keys):
        parent.yaml_set_comment_before_after_key(keys[index + 1], before='\n'.join(lines))
    else:
        raise PluginError('NACOS_YAML_COMMENT_UNSUPPORTED', '删除此字段会丢失 YAML 注释，请先人工确认')

def load_document(content, format):
    from .json_update import parse_json
    if format == 'json':
        return parse_json(content), None
    if format != 'yaml':
        raise PluginError('NACOS_FORMAT_UNSUPPORTED', '仅支持 JSON 或 YAML 增量操作')
    from ruamel.yaml import YAML
    from ruamel.yaml.tokens import AliasToken, AnchorToken
    from ruamel.yaml.error import YAMLError
    yaml = YAML(typ='rt')
    yaml.preserve_quotes = True
    try:
        if any(isinstance(token, (AliasToken, AnchorToken)) for token in yaml.scan(content)):
            raise PluginError('NACOS_YAML_ANCHOR_UNSUPPORTED', '带锚点或别名的 YAML 暂不支持增量更新')
        document = yaml.load(content)
        if not isinstance(document, dict):
            raise PluginError('NACOS_YAML_INVALID', 'YAML 根节点必须是对象')
        return document, yaml
    except PluginError:
        raise
    except (YAMLError, TypeError, ValueError, RecursionError):
        raise PluginError('NACOS_YAML_INVALID', 'YAML 格式无效、存在重复字段或无法安全处理') from None


def update_document(content, format, operations):
    import io
    import json
    document, yaml = load_document(content, format)
    updated = apply_operations(document, operations)
    try:
        if format == 'json':
            return json.dumps(updated, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
        out = io.StringIO()
        yaml.dump(updated, out)
        return out.getvalue()
    except (TypeError, ValueError, RecursionError):
        raise PluginError('NACOS_DOCUMENT_INVALID', '配置无法安全序列化') from None


def selected_fields(content, format, paths):
    import json
    document, _ = load_document(content, format)
    legacy = None
    if format == 'yaml':
        from ruamel.yaml import YAML
        from ruamel.yaml.error import YAMLError
        parser = YAML(typ='safe')
        parser.version = (1, 1)
        try:
            legacy = parser.load(content)
        except (YAMLError, TypeError, ValueError, RecursionError):
            raise PluginError('NACOS_YAML_INVALID', 'YAML 1.1 解析失败，无法安全提取字段') from None
    if not isinstance(paths, list) or not paths:
        raise PluginError('NACOS_PATH_INVALID', '必须指定要复制的字段')
    result = []
    for path in paths:
        if not isinstance(path, list) or not path or any(not isinstance(k, str) or not k for k in path):
            raise PluginError('NACOS_PATH_INVALID', '字段路径无效')
        value = document
        for key in path:
            if not isinstance(value, dict) or key not in value:
                raise PluginError('NACOS_PATH_MISSING', '来源字段不存在')
            value = value[key]
        if legacy is not None:
            legacy_value = legacy
            for key in path:
                if not isinstance(legacy_value, dict) or key not in legacy_value:
                    raise PluginError('NACOS_YAML_AMBIGUOUS', 'YAML 版本对字段解释不同')
                legacy_value = legacy_value[key]
            if not _same_json_value(value, legacy_value):
                raise PluginError('NACOS_YAML_AMBIGUOUS', 'YAML 1.1 与 1.2 对字段值解释不同，请明确类型')
        try:
            value = json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
        except (TypeError, ValueError, RecursionError):
            raise PluginError('NACOS_VALUE_UNSUPPORTED', '来源字段无法转换为 JSON 值') from None
        result.append({'op': 'set', 'path': path, 'value': value})
    return result
