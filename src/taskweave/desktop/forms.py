"""Schema-driven inputs and editable parameter definitions."""

import json
from nicegui import ui
from taskweave.core.validation import TaskError


class ValueForm:
    def __init__(self, schema, values=None):
        self.schema, self.controls = schema, {}
        self.defaults = {}
        values = values or {}
        properties = schema.get("properties", {})
        if not properties:
            ui.label("无需输入参数").classes("text-gray-500")
        for name, spec in properties.items():
            label = name + (" · 必录" if name in schema.get("required", []) else "")
            value = values.get(name, spec.get("default"))
            kind = spec.get("type", "string")
            if "enum" in spec:
                control = ui.select(spec["enum"], label=label, value=value)
            elif kind == "boolean":
                control = ui.checkbox(label, value=bool(value))
            elif kind in {"integer", "number"}:
                control = ui.number(
                    label,
                    value=value,
                    min=spec.get("minimum"),
                    max=spec.get("maximum"),
                    step=1 if kind == "integer" else None,
                )
            elif kind in {"object", "array"}:
                control = ui.textarea(
                    label,
                    value="" if value is None else json.dumps(value, ensure_ascii=False),
                )
            else:
                control = ui.input(label, value="" if value is None else str(value))
            if kind != "boolean":
                control.props('placeholder="未配置默认值，请录入"')
            control.classes("w-full")
            description = spec.get("description", "").strip()
            if description:
                ui.label(description).classes("text-xs text-gray-500 -mt-2")
            self.controls[name] = (kind, control)
            self.defaults[name] = control.value

    def apply_defaults(self, values):
        for name, (kind, control) in self.controls.items():
            value = values.get(name, self.schema.get('properties', {}).get(name, {}).get('default'))
            if kind in {'object', 'array'}:
                value = '' if value is None else json.dumps(value, ensure_ascii=False)
            elif kind == 'string':
                value = '' if value is None else str(value)
            elif kind == 'boolean':
                value = bool(value)
            if control.value == self.defaults.get(name) or (control.value is None or control.value == ''):
                control.value = value
            self.defaults[name] = value

    def values(self):
        result = {}
        for name, (kind, control) in self.controls.items():
            value = control.value
            if kind in {"object", "array"}:
                if value is None or value == "":
                    continue
                try:
                    value = json.loads(value)
                except ValueError as exc:
                    raise TaskError("FORM_INVALID", f"{name} 需要有效 JSON") from exc
            elif kind == "integer" and value is not None:
                if value != int(value):
                    raise TaskError("FORM_INVALID", f"{name} 需要整数")
                value = int(value)
            if value is None or (
                value == "" and name not in self.schema.get("required", [])
            ):
                continue
            result[name] = value
        return result


class SchemaEditor:
    def __init__(self, schema=None):
        self.original = schema or {"type": "object", "properties": {}}
        self.rows = []
        ui.label("参数定义").classes("font-medium")
        self.container = ui.column().classes("w-full")
        for name, spec in self.original.get("properties", {}).items():
            self.add(name, spec, name in self.original.get("required", []))
        ui.button("添加参数", on_click=lambda: self.add()).props("outline size=sm")

    def add(self, name="", spec=None, required=False):
        spec = spec or {"type": "string"}
        with self.container:
            with ui.row().classes("w-full items-center flex-wrap") as row:
                name_control = ui.input("名称", value=name).classes("w-36")
                kind = ui.select(
                    ["string", "integer", "number", "boolean", "object", "array", "null"],
                    label="类型",
                    value=spec.get("type", "string"),
                ).classes("w-28")
                default = ui.input(
                    "默认值",
                    value=json.dumps(spec["default"], ensure_ascii=False)
                    if "default" in spec and spec.get("type") != "string"
                    else spec.get("default", ""),
                ).classes("grow")
                description = ui.input(
                    "说明（可选）",
                    value=spec.get("description", ""),
                    placeholder="说明变量用途或录入要求",
                ).classes("grow")
                required_control = ui.checkbox("必填", value=required)
                record = (name_control, kind, default, description, required_control, spec)
                self.rows.append(record)

                def remove():
                    self.rows.remove(record)
                    row.delete()

                ui.button("移除", on_click=remove).props("flat size=sm")

    def schema(self):
        properties, required = {}, []
        for name, kind, default, description, req, original in self.rows:
            key = name.value.strip()
            if not key and not default.value and not req.value:
                continue
            if not key:
                raise TaskError("FORM_INVALID", "填写了默认值的参数需要名称")
            if key in properties:
                raise TaskError("FORM_INVALID", "参数名称重复：" + key)
            spec = {**original, "type": kind.value}
            spec.pop("default", None)
            spec.pop("description", None)
            if description.value and description.value.strip():
                spec["description"] = description.value.strip()
            if default.value != "":
                try:
                    spec["default"] = (
                        default.value
                        if kind.value == "string"
                        else json.loads(default.value)
                    )
                except ValueError as exc:
                    raise TaskError(
                        "FORM_INVALID", "非文本默认值需要有效 JSON 值"
                    ) from exc
            properties[key] = spec
            if req.value:
                required.append(key)
        result = {
            **self.original,
            "type": "object",
            "properties": properties,
            "required": required,
        }
        if properties == self.original.get("properties", {}) and set(required) == set(
            self.original.get("required", [])
        ):
            return self.original.copy()
        return result
