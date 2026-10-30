"""Collapsed manual inputs shared by task and task-combination launch dialogs."""
from copy import deepcopy
import json

from nicegui import ui
from taskweave.desktop.forms import ValueForm
from taskweave.presentation.startup_inputs import StartupInputDraft


class StartupInputs:
    def __init__(self, controller):
        self.controller = controller
        self.task_form = None
        self.step_forms, self.step_expansions = {}, {}

    async def render(self, steps, environment, *, task_id=None, task_schema=None, draft=None, environments=None):
        self.input_draft = draft if draft is not None else StartupInputDraft()
        self.steps, self.environment = steps, environment
        if task_schema is None:
            task = await self.controller.call('task.get', task_id=task_id)
            task_schema = json.loads(task['input_schema_json'])
        self.task_schema = task_schema
        self.environments = environments if environments is not None else await self.controller.call('environment.list')
        self.area = ui.column().classes('w-full gap-1')
        self._refresh()
        environment.on_value_change(lambda _: self._refresh() if not self.area.is_deleted else None)
        return self

    def _refresh(self):
        environment_id = self.environment.value or None
        selected = next((item for item in self.environments if item['environment_id'] == environment_id), None)
        config = json.loads(selected['public_config_json']) if selected else {}
        draft = self.input_draft
        draft.configure(self.task_schema, self.steps, config, environment_id)
        self.area.clear()
        self.step_forms, self.step_expansions = {}, {}
        with self.area:
            ui.label('可预填本次执行参数；未填写的必录项会在执行时提示补充。').classes('text-xs text-gray-500')
            self.task_form = None
            if draft.task.data['schema'].get('properties'):
                with self._expansion('任务输入 · 各步骤共用', '$task'):
                    self.task_form = self._form(draft.task)
            for index, step in enumerate(self.steps):
                step_id = step['step_id']
                expansion = self._expansion(f'{index + 1}. {step["name"]}', step_id)
                self.step_expansions[step_id] = expansion
                with expansion:
                    scope = draft.steps[step_id]
                    self.step_forms[step_id] = self._form(scope)

    def _expansion(self, title, key):
        draft = self.input_draft
        expansion = ui.expansion(title, value=draft.expanded.get(key, False)).classes('w-full border rounded')
        expansion.props('dense expand-icon=arrow_right expanded-icon=arrow_drop_down')
        expansion.on_value_change(lambda event: draft.expanded.__setitem__(key, event.value))
        return expansion

    @staticmethod
    def _form(scope):
        schema = deepcopy(scope.data['schema'])
        for spec in schema.get('properties', {}).values():
            if spec.get('type') == 'boolean' and 'enum' not in spec:
                spec['enum'] = [True, False]
        form = ValueForm(schema, scope.raw)
        required = scope.data['schema'].get('required', [])
        for name, (_kind, control) in form.controls.items():
            if isinstance(control, ui.select):
                control.props('clearable')
            if name not in required:
                if hasattr(control, 'set_label'):
                    control.set_label(name + ' · 可选')
                else:
                    label = next((item for item in control.default_slot.children if isinstance(item, ui.label)), None)
                    if label:
                        label.set_text(name + ' · 可选')
            control.on_value_change(lambda event, field=name: scope.change(field, event.value))
        return form

    def task_values(self):
        return self.input_draft.task_values()

    def step_values(self, step_ids=None):
        return self.input_draft.step_values(step_ids)
