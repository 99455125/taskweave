"""Pure parameter schema composition from editable raw rows."""
import json
from taskweave.core.validation import TaskError

def schema_from_rows(original: dict, rows: list) -> dict:
    properties, required = {}, []
    for name, kind, default, description, req, field_original in rows:
        key = name.strip()
        if not key and not default and not req:
            continue
        if not key:
            raise TaskError("FORM_INVALID", "填写了默认值的参数需要名称")
        if key in properties:
            raise TaskError("FORM_INVALID", "参数名称重复：" + key)
        spec = {**field_original, "type": kind}
        spec.pop("default", None)
        spec.pop("description", None)
        if description and description.strip():
            spec["description"] = description.strip()
        if default != "":
            try:
                spec["default"] = (
                    default
                    if kind == "string"
                    else json.loads(default)
                )
            except ValueError as exc:
                raise TaskError(
                    "FORM_INVALID", "非文本默认值需要有效 JSON 值"
                ) from exc
        properties[key] = spec
        if req:
            required.append(key)
    result = {
        **original,
        "type": "object",
        "properties": properties,
        "required": required,
    }
    if properties == original.get("properties", {}) and set(required) == set(
        original.get("required", [])
    ):
        return original.copy()
    return result


def context_form_rows(schema, visible):
    """Resolve plugin-owned rows into visible field/width pairs, without UI code.

    Reserved host fields are optional on each collection surface. Unlisted new
    parameters remain visible, so extending a schema never loses an input.
    """
    properties = schema.get('properties', {})
    host = {'$provider', '$session', '$target', '$preview'}
    visible = list(visible)
    layout = schema.get('x-taskweave-context-form')
    declared, seen = [], set()
    if layout is not None:
        if not isinstance(layout, dict) or not isinstance(layout.get('rows'), list):
            raise TaskError('CONTEXT_FORM_LAYOUT_INVALID', '采集表单 rows 必须是数组')
        for row in layout['rows']:
            if not isinstance(row, list) or not row:
                raise TaskError('CONTEXT_FORM_LAYOUT_INVALID', '采集表单每行必须包含字段')
            parsed = []
            for cell in row:
                key = cell if isinstance(cell, str) else cell.get('field') if isinstance(cell, dict) else None
                width = cell.get('width', 1) if isinstance(cell, dict) else 1
                if (not isinstance(key, str) or key not in {*properties, *host} or key in seen
                        or type(width) is not int or not 1 <= width <= 12):
                    raise TaskError('CONTEXT_FORM_LAYOUT_INVALID', f'无效或重复的采集布局字段：{key}')
                seen.add(key)
                parsed.append((key, width))
            declared.append(parsed)
    rows = [[cell for cell in row if cell[0] in visible] for row in declared]
    rows = [row for row in rows if row]
    # Host selectors omitted by a plugin remain accessible above its fields.
    selectors = [key for key in ('$provider', '$session', '$target') if key in visible and key not in seen]
    if layout is not None and selectors:
        rows.insert(0, [(key, 1) for key in selectors])
        seen.update(selectors)
    pending = []
    for key in visible:
        if key in seen:
            continue
        if properties.get(key, {}).get('type') in {'object', 'array'}:
            if pending:
                rows.append(pending)
                pending = []
            rows.append([(key, 1)])
        else:
            pending.append((key, 1))
            if len(pending) == 4:
                rows.append(pending)
                pending = []
    if pending:
        rows.append(pending)
    return rows
