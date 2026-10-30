"""Schema-driven inputs and editable parameter definitions."""

import json
from html import escape
from nicegui import ui
from taskweave.core.validation import TaskError
from taskweave.presentation.array_inputs import supports_row_input, raw_json, row_values


def compact_field(control, *, description="", label_container=None):
    """External accessible label and compact input for opt-in dense forms."""
    label = control.label or ""
    container = label_container or control.parent_slot.parent
    input_id = f"tw-field-{control.id}"
    with container:
        caption = ui.html(escape(label), tag="label").props(f"for={input_id}").classes("tw-compact-label")
    caption.move(target_index=0)
    control.set_label(None).props(f'dense outlined for={input_id} aria-label={json.dumps(label, ensure_ascii=False)}')
    if description:
        control.tooltip(description)
    return control


class ValueForm:
    def __init__(self, schema, values=None, *, compact=False):
        self.compact = compact
        self.schema, self.controls, self.fields = schema, {}, {}
        self.defaults = {}
        values = values or {}
        properties = schema.get("properties", {})
        if not properties and not compact:
            ui.label("无需输入参数").classes("text-gray-500")
        for name, spec in properties.items():
            field = ui.column().classes("w-full gap-0")
            self.fields[name] = field
            with field:
                self._add_control(name, spec, values)

    def _add_control(self, name, spec, values):
        label = name + (" · 必录" if name in self.schema.get("required", []) else "")
        value = values.get(name, spec.get("default"))
        kind = spec.get("type", "string")
        description = spec.get("description", "").strip()
        if description and not self.compact:
            ui.label(description).classes("text-xs text-gray-500 mb-0")
        row_input = supports_row_input(spec)
        if row_input:
            from taskweave.desktop.components.array_input import ArrayInput
            control = ArrayInput(label, spec, value)
        elif "enum" in spec:
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
                value=raw_json(value),
            )
        else:
            control = ui.input(label, value="" if value is None else str(value))
        if self.compact and not row_input:
            if kind == "boolean":
                control.props("dense")
                if description:
                    control.tooltip(description)
            else:
                compact_field(control, description=description)
                if kind in {"object", "array"}:
                    control.props("autogrow")
        if kind != "boolean" and not row_input:
            control.props('placeholder="未配置默认值，请录入"')
        control.classes("w-full")
        self.controls[name] = (kind, control)
        self.defaults[name] = control.value

    def hide_fields(self, names):
        hidden = set(names)
        for name, field in self.fields.items():
            field.set_visibility(name not in hidden)

    def apply_defaults(self, values):
        for name, (kind, control) in self.controls.items():
            value = values.get(name, self.schema.get('properties', {}).get(name, {}).get('default'))
            if kind in {'object', 'array'}:
                value = raw_json(value)
            elif kind == 'string':
                value = '' if value is None else str(value)
            elif kind == 'boolean':
                value = bool(value)
            if control.value == self.defaults.get(name) or (control.value is None or control.value == ''):
                control.value = value
            self.defaults[name] = value

    def values(self, exclude=()):
        result = {}
        excluded = set(exclude)
        for name, (kind, control) in self.controls.items():
            if name in excluded:
                continue
            value = control.value
            if name in self.schema.get("required", []) and (
                value is None or value == ""
            ):
                raise TaskError("FORM_INVALID", f"{name} 为必录项")
            spec = self.schema.get("properties", {}).get(name, {})
            if supports_row_input(spec) and value not in (None, ""):
                value = row_values(value, spec, name)
            elif kind in {"object", "array"}:
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
    def __init__(self, schema=None, *, on_change=None):
        self.original = schema or {"type": "object", "properties": {}}
        self.on_change = None
        self.rows = []
        ui.label("参数定义").classes("font-medium")
        self.container = ui.column().classes("w-full")
        for name, spec in self.original.get("properties", {}).items():
            self.add(name, spec, name in self.original.get("required", []))
        self.on_change = on_change
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
                def changed(_=None):
                    if self.on_change:
                        self.on_change()
                for control in record[:-1]:
                    control.on_value_change(changed)

                def remove():
                    self.rows.remove(record)
                    row.delete()
                    changed()

                ui.button("移除", on_click=remove).props("flat size=sm")
        if self.on_change:
            self.on_change()

    def schema(self):
        from taskweave.presentation.forms import schema_from_rows
        return schema_from_rows(self.original, self.raw_rows())

    def raw_rows(self):
        """Keep even incomplete/invalid parameter edits for connection recovery."""
        from copy import deepcopy
        return [deepcopy([*(control.value for control in row[:-1]), row[-1]]) for row in self.rows]

    def restore_rows(self, rows):
        changed, self.on_change = self.on_change, None
        try:
            self.container.clear()
            self.rows.clear()
            for name, kind, default, description, required, original in rows:
                self.add(name, original, required)
                for control, value in zip(self.rows[-1][:-1], (name, kind, default, description, required)):
                    control.value = value
        finally:
            self.on_change = changed


class StepSchemaEditor(SchemaEditor):
    """A complete step Schema with lossless field/JSON editing and reload state."""
    def __init__(self, title, schema, *, on_change=None, on_mode_change=None):
        from copy import deepcopy
        from taskweave.presentation.forms import schema_supports_fields
        self._changing = True
        self.title = title
        self.on_mode_change = on_mode_change
        self._active_mode = 'form' if schema_supports_fields(schema) else 'json'
        ui.label(title).classes('font-semibold')
        self.edit_mode = ui.toggle({'form': '字段表单', 'json': '高级 JSON'}, value=self._active_mode)
        self.edit_mode.props['aria-label'] = title + ' 编辑方式'
        with ui.column().classes('w-full') as self.form_area:
            super().__init__(schema if self._active_mode == 'form' else {}, on_change=None)
        self.original = deepcopy(schema)
        with ui.column().classes('w-full') as self.json_area:
            self.json_editor = ui.textarea(title + ' JSON', value=json.dumps(schema, ensure_ascii=False, indent=2)).props(
                'outlined rows=14').classes('tw-schema-json w-full font-mono')
        self.on_change = on_change
        self.json_editor.on_value_change(self._json_changed)
        self.edit_mode.on_value_change(self._change_mode)
        self._show_mode()
        self._changing = False

    def _show_mode(self):
        self.form_area.set_visibility(self._active_mode == 'form')
        self.json_area.set_visibility(self._active_mode == 'json')

    def _json_changed(self, _):
        if not self._changing and self.on_change:
            self.on_change()

    def _change_mode(self, event):
        from copy import deepcopy
        from taskweave.presentation.forms import schema_from_editor, schema_supports_fields
        if self._changing or event.value == self._active_mode:
            return
        callback, self.on_change = self.on_change, None
        self._changing = True
        try:
            schema = schema_from_editor(self.original, self.raw_rows(), self._active_mode, self.json_editor.value)
            if event.value == 'form':
                if not schema_supports_fields(schema):
                    raise TaskError('FORM_INVALID', '此 Schema 含复杂结构，请继续使用高级 JSON 编辑。')
                self.original = deepcopy(schema)
                self.container.clear()
                self.rows.clear()
                for name, spec in schema.get('properties', {}).items():
                    self.add(name, spec, name in schema.get('required', []))
            else:
                self.json_editor.set_value(json.dumps(schema, ensure_ascii=False, indent=2))
            self._active_mode = event.value
            self._show_mode()
        except TaskError as exc:
            self.edit_mode.set_value(self._active_mode)
            ui.notify(self.title + '：' + str(exc), type='negative')
        finally:
            self.on_change, self._changing = callback, False
        if self.on_mode_change:
            self.on_mode_change()

    def schema(self):
        from taskweave.presentation.forms import schema_from_editor
        return schema_from_editor(self.original, self.raw_rows(), self._active_mode, self.json_editor.value)

    def restore_editor(self, *, rows, mode=None, json_text=None):
        self._changing = True
        try:
            self.restore_rows(rows)
            if json_text is not None:
                self.json_editor.set_value(json_text)
            if mode is not None:
                self._active_mode = mode
                self.edit_mode.set_value(mode)
            self._show_mode()
        finally:
            self._changing = False


def arrange_context_fields(schema, group, form, host_fields, hidden=()):
    """Reuse controls and bindings while applying declarative plugin form rows."""
    from taskweave.presentation.forms import context_form_rows
    controls = {**{key: value for key, value in host_fields.items() if key != '$preview'}, **form.fields}
    if '$preview' in host_fields:
        controls['$preview'] = host_fields['$preview']
    visible = [name for name in controls if name not in hidden]
    rows = context_form_rows(schema, visible)
    containers = getattr(group, '_tw_form_rows', None)
    if containers is None:
        containers = group._tw_form_rows = []
    while len(containers) < len(rows):
        with group:
            containers.append(ui.row().classes('tw-context-form-row w-full'))
    for index, container in enumerate(containers):
        container.set_visibility(index < len(rows))
        if index >= len(rows):
            continue
        row = rows[index]
        container.style('grid-template-columns:' + ' '.join(f'minmax(0,{width}fr)' for _, width in row))
        for name, _ in row:
            controls[name].move(container)
