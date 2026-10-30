"""Manual startup drafts for one task and its steps; automatic inputs stay runtime-owned."""
from copy import deepcopy

from taskweave.presentation.debug import InputScopeDraft


class StartupInputDraft:
    def __init__(self):
        self.task = InputScopeDraft()
        self.steps = {}
        self.environment_id = None
        self.task_schema = {}
        self.step_schemas = {}
        self.expanded = {}

    @staticmethod
    def _configure(scope, schema, defaults):
        existing_edits = set(scope.edits)
        scope.configure(schema, defaults)
        for name in set(scope.edits) - existing_edits:
            scope.edits.pop(name, None)
        # An untouched checkbox must not manufacture False for an absent input.
        for name, spec in schema.get('properties', {}).items():
            if spec.get('type') == 'boolean' and name not in defaults and 'default' not in spec and name not in scope.edits:
                scope.raw[name] = None
                scope.data['defaults'][name] = None

    def configure(self, task_schema, steps, environment_config, environment_id=None):
        self.environment_id = environment_id
        self.task_schema = deepcopy(task_schema)
        task_properties = {name: spec for name, spec in task_schema.get('properties', {}).items()
            if name not in environment_config or 'default' in spec or name in self.task.edits}
        manual_task = {**task_schema, 'properties': task_properties,
                       'required': [name for name in task_schema.get('required', []) if name in task_properties]}
        self._configure(self.task, manual_task, {})
        for step in steps:
            step_id, schema = step['step_id'], step.get('input_schema', {'type': 'object'})
            self.step_schemas[step_id] = deepcopy(schema)
            scope = self.steps.setdefault(step_id, InputScopeDraft())
            properties = {name: spec for name, spec in schema.get('properties', {}).items()
                if name not in step.get('bindings', {}) and
                ('default' in spec or name in scope.edits or
                 (name not in task_schema.get('properties', {}) and name not in environment_config))}
            manual = {**schema, 'properties': properties,
                      'required': [name for name in schema.get('required', []) if name in properties]}
            self._configure(scope, manual, {})

    @staticmethod
    def _values(scope):
        # Runtime applies inherited/default values. Only edits belong to this request.
        data = {'schema': scope.data['schema'], 'raw': deepcopy(scope.edits), 'defaults': {}, 'edits': {}}
        return InputScopeDraft(data).values(partial=True)

    def task_values(self):
        return self._values(self.task)

    def step_values(self, step_ids=None):
        selected = self.steps if step_ids is None else step_ids
        values = {}
        for step_id in selected:
            if step_id not in self.steps:
                continue
            supplied = self._values(self.steps[step_id])
            if supplied:
                values[step_id] = supplied
        return values
