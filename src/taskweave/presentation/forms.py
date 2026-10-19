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
