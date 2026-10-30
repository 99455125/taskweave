"""Schema-shaped rows with a JSON-string value compatible with shared drafts."""
from copy import deepcopy
import json

from nicegui import ui
from nicegui.events import ValueChangeEventArguments, handle_event
from taskweave.presentation.array_inputs import raw_json


class StringListInput(ui.column):
    """Edit list entries independently while retaining malformed raw field drafts."""
    def __init__(self, label, value=None):
        super().__init__()
        self._value = deepcopy(value)
        self._handlers = []
        with self:
            ui.label(label).classes('text-sm')
            self.body = ui.column().classes('w-full gap-1')
        self._render()

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, value):
        previous = self._value
        self._value = deepcopy(value)
        self._render()
        self._notify(previous)

    def set_value(self, value):
        self.value = value
        return self

    def on_value_change(self, callback):
        self._handlers.append(callback)
        return self

    def _notify(self, previous):
        event = ValueChangeEventArguments(sender=self, client=self.client, value=deepcopy(self.value), previous_value=previous)
        for callback in self._handlers:
            handle_event(callback, event)

    def _render(self):
        self.body.clear()
        self.entries = []
        with self.body:
            if self.value is not None and (not isinstance(self.value, list) or
                                          any(not isinstance(entry, str) for entry in self.value)):
                ui.textarea('字段 JSON', value=json.dumps(self.value, ensure_ascii=False)).classes('w-full').on_value_change(self._json_changed)
                return
            for index, value in enumerate(self.value or []):
                with ui.row().classes('w-full items-center flex-nowrap'):
                    entry = ui.input(f'第 {index + 1} 项', value=value).props('dense outlined').classes('grow')
                    self.entries.append(entry)
                    entry.on_value_change(self._changed)
                    ui.button('移除此项', on_click=lambda _, index=index: self.remove_entry(index)).props('flat size=sm')
            ui.button('添加一项', on_click=lambda: self.add_entry()).props('outline size=sm')

    def _changed(self, _):
        previous, self._value = self._value, [entry.value for entry in self.entries]
        self._notify(previous)

    def _json_changed(self, event):
        previous = self._value
        try:
            self._value = json.loads(event.value)
        except ValueError:
            self._value = event.value
        self._notify(previous)

    def add_entry(self, value=''):
        self.value = [*(self.value or []), value]

    def remove_entry(self, index):
        values = list(self.value)
        del values[index]
        self.value = values


class ArrayInput(ui.column):
    def __init__(self, label, schema, value=None):
        super().__init__()
        self.schema, self.rows = schema, []
        self._handlers, self._value = [], raw_json(value)
        self._rendering = False
        self.enabled = True
        with self:
            ui.label(label).classes('font-medium')
            self.body = ui.column().classes('w-full gap-2')
            self.add_button = ui.button('添加一行', on_click=lambda: self.add_row()).props('outline size=sm')
        self._render()

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, value):
        previous = self._value
        self._value = raw_json(value)
        self._render()
        if previous != self._value:
            self._notify(previous)

    def set_value(self, value):
        self.value = value
        return self

    def on_value_change(self, callback):
        self._handlers.append(callback)
        return self

    def disable(self):
        self.enabled = False
        for element in self.descendants():
            if hasattr(element, 'disable'):
                element.disable()
        return self

    def enable(self):
        self.enabled = True
        for element in self.descendants():
            if hasattr(element, 'enable'):
                element.enable()
        return self

    def _notify(self, previous):
        event = ValueChangeEventArguments(sender=self, client=self.client, value=self.value, previous_value=previous)
        for handler in self._handlers:
            handle_event(handler, event)

    def _render(self):
        self._rendering = True
        self.body.clear()
        self.rows.clear()
        try:
            values = json.loads(self._value) if self._value else []
        except ValueError:
            values = None
        try:
            with self.body:
                if not isinstance(values, list) or any(not isinstance(row, dict) for row in values):
                    control = ui.textarea('JSON', value=self._value).classes('w-full').props('autogrow outlined')
                    control.on_value_change(lambda e: self._json_changed(e.value))
                    self.add_button.set_visibility(False)
                    return
                self.add_button.set_visibility(True)
                for value in values:
                    self._append_row(value)
                if not values:
                    ui.label('暂无记录，添加一行开始录入').classes('text-xs text-gray-500')
        finally:
            self._rendering = False
            if not self.enabled:
                self.disable()

    def _json_changed(self, value):
        previous, self._value = self._value, value
        self._notify(previous)

    def _append_row(self, value):
        item = self.schema['items']
        with ui.row().classes('w-full items-start flex-wrap border rounded p-2') as container:
            record = {'container': container, 'controls': {}, 'original': deepcopy(value), 'initial': {}}
            self.rows.append(record)
            ui.label(f'第 {len(self.rows)} 行').classes('text-xs text-gray-500 w-full')
            for name, field in item['properties'].items():
                label = name + (' · 必录' if name in item.get('required', []) else ' · 可选')
                raw = value.get(name)
                if field['type'] == 'array':
                    options = field['items'].get('enum')
                    if options is not None and (raw is None or
                            isinstance(raw, list) and all(isinstance(entry, str) for entry in raw)):
                        choices = list(options)
                        choices.extend(entry for entry in (raw or []) if entry not in choices)
                        control = ui.select(choices, label=label, value=raw, multiple=True).props('clearable use-chips')
                    else:
                        control = StringListInput(label, raw)
                elif 'enum' in field:
                    options = list(field['enum'])
                    if raw is not None and raw not in options:
                        options.append(raw)
                    control = ui.select(options, label=label, value=raw).props('clearable')
                elif field['type'] == 'boolean':
                    options = {True: '是', False: '否'}
                    if raw is not None and type(raw) is not bool:
                        options = [True, False, raw]
                    control = ui.select(options, label=label, value=raw).props('clearable')
                else:
                    control = ui.input(label, value='' if raw is None else str(raw))
                    if field['type'] in {'number', 'integer'}:
                        control.props('inputmode=decimal')
                control.classes('grow min-w-32').props('dense outlined')
                if field.get('description'):
                    control.tooltip(field['description'])
                if field['type'] in {'number', 'integer'}:
                    bounds = []
                    if 'minimum' in field: bounds.append(f"最小 {field['minimum']}")
                    if 'maximum' in field: bounds.append(f"最大 {field['maximum']}")
                    hint = '整数' if field['type'] == 'integer' else '数值'
                    control.props['hint'] = '；'.join([hint, *bounds])
                record['controls'][name] = control
                record['initial'][name] = deepcopy(control.value)
                control.on_value_change(lambda _: self._changed())
            ui.button('移除此行', on_click=lambda: self.remove_row(record)).props('flat size=sm')

    def _changed(self):
        if self._rendering:
            return
        values = []
        for row in self.rows:
            value = deepcopy(row['original'])
            value.update({name: control.value for name, control in row['controls'].items()
                          if name in value or control.value != row['initial'][name]})
            values.append(value)
        previous, self._value = self._value, raw_json(values)
        self._notify(previous)

    def add_row(self):
        value = {key: deepcopy(field['default']) for key, field in self.schema['items']['properties'].items()
                 if 'default' in field}
        values = json.loads(self.value) if self.value else []
        self.value = [*values, value]

    def remove_row(self, row):
        index = self.rows.index(row)
        values = json.loads(self.value)
        del values[index]
        self.value = values
