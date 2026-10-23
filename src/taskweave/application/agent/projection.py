"""Small JSON projections with explicit bounds, never silent evidence clipping."""

import base64
import json
from copy import deepcopy

from taskweave.core.validation import TaskError, fingerprint


MAX_RESULT_BYTES = 32768
SCHEMA_FIELDS = frozenset({"input_schema", "output_schema", "parameters", "schema", "step_schema", "task_package_schemas", 'context_requests', 'request_contract'})


def contract_projection(value, sanitize):
    """Redact instance values while preserving schema keys and variable metadata."""
    protected = []

    def schema_value(value, sensitive=False):
        if isinstance(value, list):
            return [schema_value(item, sensitive) for item in value]
        if not isinstance(value, dict):
            return sanitize(value)
        result = {}
        for key, child in value.items():
            if sensitive and key in {"default", "examples"}:
                continue
            if key == "properties" and isinstance(child, dict):
                result[key] = {name: schema_value(spec, sanitize({name: "probe"}).get(name) != "probe")
                               for name, spec in child.items()}
            else:
                result[key] = schema_value(child, sensitive)
        return result

    def extract(node, path=()):
        if isinstance(node, list):
            return [extract(child, path + (index,)) for index, child in enumerate(node)]
        if not isinstance(node, dict):
            return node
        result = {}
        for key, child in node.items():
            location = path + (key,)
            if key in SCHEMA_FIELDS and isinstance(child, (dict, bool)):
                protected.append((location, schema_value(child)))
                result[key] = None
            elif key == "secret" and type(child) is bool:
                protected.append((location, child))
                result[key] = None
            else:
                result[key] = extract(child, location)
        return result

    cleaned = sanitize(extract(deepcopy(value)))
    for path, child in protected:
        parent = cleaned
        for segment in path[:-1]:
            if not isinstance(parent, (dict, list)):
                break
            parent = parent[segment]
        else:
            if isinstance(parent, (dict, list)):
                parent[path[-1]] = child
    return cleaned


def textual_evidence(value):
    """Keep image references/metadata, never send opaque image bytes by default."""
    if isinstance(value, list):
        return [textual_evidence(item) for item in value]
    if not isinstance(value, dict):
        return value
    image = value.get("kind") == "image" or value.get("renderer") == "core.image"
    result = {key: child if key in SCHEMA_FIELDS else textual_evidence(child) for key, child in value.items()
              if key != "image_base64" and not (image and key in {"content", "data", "image_url"})}
    if "image_base64" in value or image:
        result["image_omitted"] = True
    return result


def contextual_value(value, source, project):
    """Retain field-name context when a persisted check has already selected a leaf."""
    segments = [source.get('output', 'data')]
    for path in (source.get('item_pointer', ''), source.get('pointer', '')):
        segments.extend(part.replace('~1', '/').replace('~0', '~') for part in path.split('/')[1:])
    wrapped = value
    for segment in reversed(segments):
        wrapped = {segment: wrapped}
    result = project(wrapped)
    for segment in segments:
        if not isinstance(result, dict):
            return result
        if segment not in result:
            return {'image_omitted': True}
        result = result[segment]
    return result


def snapshot_view(snapshot, identity, sections=None, cursor=None, limit=20):
    """A large immutable snapshot remains readable one section/page at a time."""
    if sections:
        if not isinstance(sections, list) or any(key not in snapshot for key in sections):
            raise TaskError("AGENT_SECTION_INVALID")
        result = {"bundle_id": identity}
        for key in sections:
            if isinstance(snapshot[key], list):
                paging = page(snapshot[key], {"bundle_id": identity, "section": key}, cursor, limit)
                result[key] = paging.pop("items")
                result[key + "_page"] = paging
            else:
                result[key] = snapshot[key]
        return bounded(result)
    if len(json.dumps(snapshot, ensure_ascii=False).encode()) <= MAX_RESULT_BYTES:
        return snapshot
    return {"bundle_id": identity, "baseline": snapshot.get("baseline"), "truncated": True,
            "sections": {key: {"kind": type(value).__name__, "items": len(value) if isinstance(value, list) else None}
                         for key, value in snapshot.items() if key != "bundle_id"},
            "next_action": "inspect_bundle_sections"}


def selected_view(document, scope, selected_pointer='', cursor=None, limit=20, text_offset=None):
    """Every large leaf remains addressable; previews never masquerade as full values."""
    from taskweave.core.validation import pointer
    value = pointer(document, selected_pointer)
    def child_path(base, key):
        return base + '/' + str(key).replace('~', '~0').replace('/', '~1')
    def entry(child, path):
        return {'pointer': path, 'type': type(child).__name__, 'fingerprint': fingerprint(child),
                'size': len(child) if isinstance(child, (str, list, dict)) else None}
    if text_offset is not None and (type(text_offset) is not int or not isinstance(value, str) or not 0 <= text_offset <= len(value)):
        raise TaskError('AGENT_ARGUMENT_INVALID')
    result = {**scope, 'pointer': selected_pointer}
    if isinstance(value, str) and (text_offset is not None or len(value.encode()) > 24000):
        start = text_offset or 0
        text = value[start:start + 6000]
        result['data'] = {'text': text, 'offset': start, 'characters': len(value),
                          'next_offset': start + len(text) if start + len(text) < len(value) else None,
                          'fingerprint': fingerprint(value), 'truncated': start > 0 or start + len(text) < len(value)}
    elif isinstance(value, list):
        items = [item if len(json.dumps(item, ensure_ascii=False).encode()) <= 1000 else
                 {**entry(item, child_path(selected_pointer, index)), 'truncated': True, 'next_action': 'inspect_pointer'}
                 for index, item in enumerate(value)]
        result['data'] = page(items, {**scope, 'pointer': selected_pointer}, cursor, limit)
    elif isinstance(value, dict) and len(json.dumps(value, ensure_ascii=False).encode()) > 24000:
        result['children'] = page([{'key': key, **entry(child, child_path(selected_pointer, key))} for key, child in value.items()],
                                  {**scope, 'pointer': selected_pointer}, cursor, limit)
        result.update(truncated=True, next_action='inspect_pointer')
    else:
        schema_path = any(segment in SCHEMA_FIELDS for segment in selected_pointer.split('/'))
        result['schema' if schema_path and isinstance(value, (dict, bool)) else 'data'] = value
    return bounded(result)


def compact_record(record, list_limit=10, text_limit=1500):
    """Nested report details have explicit truncation markers and remain local."""
    if not isinstance(record, dict):
        return record
    result = {}
    for key, value in record.items():
        if isinstance(value, list):
            result[key] = [compact_record(item, list_limit, text_limit) for item in value[:list_limit]]
            if len(value) > list_limit:
                result[key + "_total"] = len(value)
                result[key + "_truncated"] = True
        elif isinstance(value, dict):
            result[key] = compact_record(value, list_limit, text_limit)
        elif isinstance(value, str) and len(value) > text_limit:
            result[key] = value[:text_limit]
            result[key + "_truncated"] = True
        else:
            result[key] = value
    return result


def review_view(report, sections=None, cursor=None, limit=10, selected_pointer=None):
    result = fields(report, ("kind", "identity", "fingerprint", "review_spec_id", "title", "goal",
                             "run_status", "automatic_status", "human_status", "human_decision"))
    result = compact_record(result)
    result["check_count"] = len(report["checks"])
    result["path_count"] = len(report["path"])
    if selected_pointer is not None:
        from taskweave.core.validation import pointer
        value = pointer(report, selected_pointer)
        result["data"] = page(value, {"report": report["fingerprint"], "pointer": selected_pointer}, cursor, limit) if isinstance(value, list) else value
        return bounded(result)
    sections = ["checks"] if sections is None else sections
    if not isinstance(sections, list) or not sections or set(sections) - {"checks", "path", "flow", "result_state", "inputs"}:
        raise TaskError("AGENT_SECTION_INVALID")
    if cursor is not None and len(sections) != 1:
        raise TaskError("AGENT_CURSOR_INVALID", "分页时一次读取一个部分")
    for key in sections:
        value = report.get(key, [])
        if isinstance(value, list):
            paging = page([compact_record(item) for item in value], {"report": report["fingerprint"], "section": key}, cursor, limit)
            result[key] = paging.pop("items")
            result[key + "_page"] = paging
        else:
            result[key] = value
    return bounded(result)


def fields(record, names):
    return {name: record[name] for name in names if name in record}


def bounded(value, limit=MAX_RESULT_BYTES):
    if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode()) > limit:
        raise TaskError("AGENT_RESULT_TOO_LARGE", "结果超过返回预算，请缩小查询范围、分页或指定 JSON Pointer；完整证据仍保存在本地")
    return value


def page(items, scope, cursor=None, limit=20):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise TaskError("AGENT_LIMIT_INVALID", "每页必须为 1–100 条")
    revision = fingerprint(items)
    start = 0
    if cursor is not None:
        try:
            decoded = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
            if decoded["scope"] != scope or type(decoded["offset"]) is not int or decoded["offset"] < 0:
                raise ValueError()
            start = decoded["offset"]
        except (ValueError, TypeError, KeyError, UnicodeError, AttributeError) as exc:
            raise TaskError("AGENT_CURSOR_INVALID", "游标不适用于当前查询") from exc
        if decoded.get("revision") != revision:
            raise TaskError("AGENT_CURSOR_STALE", "查询结果已变化，请从第一页读取")
    selected = items[start:start + limit]
    offset = start + len(selected)
    next_cursor = base64.urlsafe_b64encode(json.dumps({
        "scope": scope, "revision": revision, "offset": offset,
    }).encode()).decode() if offset < len(items) else None
    return bounded({"items": selected, "total": len(items), "next_cursor": next_cursor,
                    "truncated": next_cursor is not None, "revision": revision})
