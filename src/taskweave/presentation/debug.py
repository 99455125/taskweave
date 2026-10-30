"""Debug workflow decisions and result ownership, without dialog or widget access."""
from dataclasses import dataclass
from typing import Protocol
from taskweave.presentation.state import DebugState


class DebugApplicationPort(Protocol):
    async def trial(self, step: dict, inputs: dict, environment_id: str | None) -> dict: ...
    async def repeat_trial(self, step: dict, run_id: str, *, overrides: dict) -> dict: ...


@dataclass(frozen=True)
class TrialContinuation:
    action: str
    scope: str | None = None
    needs_confirmation: bool = False


class DebugInteraction:
    def __init__(self, state: DebugState, trials: dict, application: DebugApplicationPort):
        self.state, self.trials, self.application = state, trials, application

    def fresh_round(self, step_id):
        self.state.fresh_round = True
        self.state.feedback = self.state.feedback_run_id = None
        self.state.removed_feedback = set()
        self.state.supplements.pop(step_id, None)
        self.state.trial_signature = None

    def accept_run(self, expected_identity, current_identity, step_id, run):
        if expected_identity != current_identity or expected_identity[1] != step_id:
            return False
        self.trials[step_id] = run['run_id']
        return True

    def owns(self, expected_identity, current_identity, run_id):
        return expected_identity == current_identity and self.trials.get(expected_identity[1]) == run_id

    @staticmethod
    def settled(run, request):
        return run['status'] != 'RUNNING' or bool(request.get('waiting_input')) or bool(run.get('attempts'))

    @staticmethod
    def continuation(previous, request, environment_id, step_id):
        if previous.get('can_end') and previous['environment_id'] != environment_id:
            return TrialContinuation('abandon', needs_confirmation=True)
        if not previous.get('can_end') or previous['status'] == 'CANCELLED':
            return TrialContinuation('new')
        waiting = request.get('waiting_input')
        if waiting:
            if waiting['scope'] == 'step' and waiting['step_id'] != step_id:
                return TrialContinuation('other_step', scope='step')
            return TrialContinuation('resume', scope=waiting['scope'])
        uncertain = any(a['valid'] and (a['status'] == 'UNKNOWN' or
                        (a['status'] == 'FAILED' and a['effect_state'] in {'UNKNOWN', 'SUCCEEDED'}))
                        for a in previous['attempts'])
        return TrialContinuation('repeat', needs_confirmation=uncertain)

    async def launch(self, step, inputs, environment_id, *, previous_run_id=None):
        if previous_run_id is not None:
            return await self.application.repeat_trial(step, previous_run_id, overrides=inputs)
        return await self.application.trial(step, inputs, environment_id)


class InputScopeDraft:
    """One schema's raw values, defaults and explicit overrides; no controls."""
    def __init__(self, data=None):
        self.data = data if data is not None else {}
        for key in ('schema', 'raw', 'defaults', 'edits'):
            self.data.setdefault(key, {})

    @property
    def raw(self): return self.data['raw']
    @property
    def edits(self): return self.data['edits']

    def configure(self, schema, defaults):
        from copy import deepcopy
        self.data['schema'] = deepcopy(schema)
        normalized = {}
        for name, spec in schema.get('properties', {}).items():
            value = defaults.get(name, spec.get('default'))
            kind = spec.get('type', 'string')
            if 'enum' not in spec:
                if kind == 'string': value = '' if value is None else str(value)
                elif kind == 'boolean': value = bool(value)
                else: value = self._raw_value(name, value)
            normalized[name] = value
        self.data['defaults'] = deepcopy(normalized)
        self.data['raw'] = deepcopy(normalized)
        for name, value in self.edits.items():
            if name in schema.get('properties', {}):
                self.raw[name] = self._raw_value(name, value)
        for name in schema.get('required', []):
            if name in self.raw and self.raw[name] in (None, ''):
                self.edits[name] = self.raw[name]

    def _raw_value(self, name, value):
        import json
        spec = self.data['schema'].get('properties', {}).get(name, {})
        kind = spec.get('type', 'string')
        if kind in {'object', 'array'} and not isinstance(value, str):
            return '' if value is None else json.dumps(value, ensure_ascii=False)
        return value

    def change(self, name, value):
        from copy import deepcopy
        self.raw[name] = deepcopy(value)
        required_blank = name in self.data['schema'].get('required', []) and value in (None, '')
        if required_blank or value != self.data['defaults'].get(name):
            self.edits[name] = deepcopy(value)
        else:
            self.edits.pop(name, None)

    def apply(self, values):
        for name, value in values.items():
            if name in self.data['schema'].get('properties', {}):
                self.change(name, self._raw_value(name, value))

    def replace_edits(self, values):
        from copy import deepcopy
        self.edits.clear()
        self.edits.update(deepcopy(values or {}))

    def update_defaults(self, values):
        for name, spec in self.data['schema'].get('properties', {}).items():
            value = values.get(name, spec.get('default'))
            kind = spec.get('type', 'string')
            if kind == 'string': value = '' if value is None else str(value)
            elif kind == 'boolean': value = bool(value)
            else: value = self._raw_value(name, value)
            update = self.raw.get(name) == self.data['defaults'].get(name) or self.raw.get(name) in (None, '')
            self.data['defaults'][name] = value
            if update: self.change(name, value)

    def values(self, *, partial=False):
        import json
        from taskweave.core.validation import TaskError, validate
        schema, result = self.data['schema'], {}
        for name, spec in schema.get('properties', {}).items():
            value = self.raw.get(name)
            if value in (None, ''):
                if not partial and name in schema.get('required', []):
                    raise TaskError('FORM_INVALID', f'{name} 为必录项')
                continue
            kind = spec.get('type', 'string')
            from taskweave.presentation.array_inputs import supports_row_input, row_values
            if supports_row_input(spec):
                value = row_values(value, spec, name)
            elif kind in {'object', 'array'}:
                try:
                    value = json.loads(value)
                except (TypeError, ValueError) as exc:
                    if not partial:
                        raise TaskError('FORM_INVALID', f'{name} 需要有效 JSON') from exc
            elif kind == 'integer' and not partial:
                if value != int(value):
                    raise TaskError('FORM_INVALID', f'{name} 需要整数')
                value = int(value)
            result[name] = value
        if partial:
            validate(dict(result), {**schema, 'required': []})
            for name, spec in schema.get('properties', {}).items():
                if spec.get('type') == 'integer' and name in result:
                    result[name] = int(result[name])
        return result


class TrialInputDraft:
    """Task and step raw inputs shared by rendering, submission and recovery."""
    def __init__(self, state=None):
        self.state = state if state is not None else DebugState()
        if self.state.task_inputs is None: self.state.task_inputs = {}
        if self.state.step_inputs is None: self.state.step_inputs = {}
        self.task = InputScopeDraft(self.state.task_inputs)
        self.step = InputScopeDraft(self.state.step_inputs)

    def bind(self, state: DebugState, identity):
        state.task_inputs, state.step_inputs = self.task.data, self.step.data
        state.environment_id = self.state.environment_id
        state.input_identity = tuple(identity)
        self.state = state

    def set_environment(self, environment_id):
        self.state.environment_id = environment_id

    def values(self):
        return {**self.task.values(), **self.step.values()}

    def snapshot(self, task_id, step_id):
        from copy import deepcopy
        return deepcopy({'task_id': task_id, 'step_id': step_id,
                         'environment_id': self.state.environment_id,
                         'task': self.task.edits, 'step': self.step.edits})

    def restore(self, snapshot):
        self.task.apply(snapshot.get('task', {}))
        self.step.apply(snapshot.get('step', {}))
        self.set_environment(snapshot.get('environment_id'))
