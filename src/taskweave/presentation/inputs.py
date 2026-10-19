"""Paused-run input submission, without dialogs or framework callbacks."""
from dataclasses import dataclass
from typing import Callable, Literal, Protocol, overload
from taskweave.core.data_contracts import CommandResult, ExecutionRequest
from taskweave.core.json_types import JSON
from uuid import uuid4
from taskweave.core.validation import TaskError, validate
from copy import deepcopy

InputRequestKey = tuple[str, str | None, str, str | None]
InputIdentity = tuple[str | int | None, ...] | str | int


class RunInputApplication(Protocol):
    async def run_request(self, run_id: str) -> ExecutionRequest: ...

    @overload
    async def call(self, operation: Literal['run.inputs'], *, run_id: str, command_id: str,
                   inputs: dict[str, JSON], step_inputs: dict[str, JSON] | None = None,
                   expected_input_id: str | None = None) -> CommandResult: ...
    @overload
    async def call(self, operation: Literal['run.start'], *, run_id: str, command_id: str,
                   mode: str, target_step_id: str | None) -> CommandResult: ...


def request_key(run_id, waiting):
    return run_id, waiting.get('id'), waiting['scope'], waiting.get('step_id')


@dataclass(frozen=True)
class ResumeResult:
    current: bool
    waiting: dict | None = None
    phase: str = "complete"


def decode_raw_values(raw, kinds):
    import json
    values = {}
    for name, value in raw.items():
        if value is None or value == '': continue
        if kinds.get(name) in {'object', 'array'}:
            try: value = json.loads(value)
            except (ValueError, TypeError): pass
        values[name] = value
    return values


def missing_required(schema, values):
    return [key for key in (schema or {}).get('required', []) if key not in values or values[key] in (None, '')]


class InputSubmission:
    """One request's ordinary raw inputs, validation and recoverable snapshot."""
    def __init__(self, drafts, key, waiting, draft, editable_schema=None):
        self.drafts, self.key, self.waiting = drafts, key, waiting
        self.draft, self.editable_schema = draft, editable_schema

    def remember(self):
        self.drafts[self.key] = deepcopy({'task': self.draft.task.raw, 'step': self.draft.step.raw})

    def submission(self):
        if self.waiting['scope'] == 'task':
            steps = self.draft.step.values()
            if self.editable_schema is not None:
                validate(steps, {**self.editable_schema, 'additionalProperties': True})
            return self.draft.task.values(), {self.waiting['step_id']: steps}
        return self.draft.step.values(), None

    def issues(self):
        try:
            scope = self.draft.task if self.waiting['scope'] == 'task' else self.draft.step
            validate(scope.values(), self.waiting['schema'])
            if self.waiting['scope'] == 'task' and self.editable_schema is not None:
                validate(self.draft.step.values(), {**self.editable_schema, 'additionalProperties': True})
            return []
        except (TaskError, ValueError, TypeError) as exc:
            scope = self.draft.task if self.waiting['scope'] == 'task' else self.draft.step
            missing = missing_required(self.waiting['schema'], scope.raw)
            if self.waiting['scope'] == 'task' and self.editable_schema is not None:
                missing.extend(missing_required(self.editable_schema, self.draft.step.raw))
            return missing or [str(exc)]


class RunInputs:
    def __init__(self, port: RunInputApplication, drafts: dict[InputRequestKey, dict],
                 identity: Callable[[str], InputIdentity]):
        self.port, self.drafts, self.identity = port, drafts, identity
        self.opening = False
        self.submitting = set()

    def begin_open(self):
        if self.opening: return False
        self.opening = True
        return True

    def end_open(self):
        self.opening = False

    def begin_submit(self, key):
        if key in self.submitting: return False
        self.submitting.add(key)
        return True

    def end_submit(self, key):
        self.submitting.discard(key)

    def bind(self, run_id, waiting, draft, editable_schema=None):
        return InputSubmission(self.drafts, request_key(run_id, waiting), waiting, draft, editable_schema)

    async def resume(self, run_id, values, step_inputs=None, *, expected_identity=None, expected_request=None):
        result = ResumeResult(False)
        async for result in self.resume_events(run_id, values, step_inputs,
                expected_identity=expected_identity, expected_request=expected_request):
            pass
        return result

    async def resume_events(self, run_id, values, step_inputs=None, *, expected_identity=None, expected_request=None):
        identity = expected_identity if expected_identity is not None else self.identity(run_id)
        if self.identity(run_id) != identity:
            yield ResumeResult(False)
            return
        request = await self.port.run_request(run_id)
        if self.identity(run_id) != identity:
            yield ResumeResult(False)
            return
        waiting = request.get('waiting_input')
        if not waiting or (expected_request is not None and request_key(run_id, waiting) != expected_request):
            yield ResumeResult(False)
            return
        validate(values, waiting['schema'])
        await self.port.call('run.inputs', run_id=run_id, command_id=str(uuid4()), inputs=values,
                             **({'step_inputs': step_inputs} if step_inputs is not None else {}),
                             **({'expected_input_id': waiting['id']} if expected_request is not None and waiting.get('id') else {}))
        yield ResumeResult(self.identity(run_id) == identity, waiting, 'accepted')
        command = request.get('last_command', {})
        await self.port.call('run.start', run_id=run_id, command_id=str(uuid4()),
                             mode=command.get('mode', 'ALL'), target_step_id=command.get('target'))
        self.drafts.pop(request_key(run_id, waiting), None)
        yield ResumeResult(self.identity(run_id) == identity, waiting)
