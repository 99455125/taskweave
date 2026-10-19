"""Step list commands and outcomes, independent of controls and rendering."""
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol, TypedDict, overload
from taskweave.core.json_types import JSON
from taskweave.core.data_contracts import StepRecord, CommandResult

from taskweave.core.validation import TaskError


class StepValidation(TypedDict):
    step_id: str
    valid: bool
    diagnostics: list[dict[str, JSON]]


class StepApplication(Protocol):
    @overload
    async def __call__(self, operation: Literal['step.list'], *, task_id: str) -> list[StepRecord]: ...
    @overload
    async def __call__(self, operation: Literal['step.save'], *, task_id: str, document: dict[str, JSON]) -> StepRecord: ...
    @overload
    async def __call__(self, operation: Literal['step.reorder'], *, task_id: str, step_ids: list[str]) -> list[StepRecord]: ...
    @overload
    async def __call__(self, operation: Literal['step.delete'], *, step_id: str) -> CommandResult: ...
    @overload
    async def __call__(self, operation: Literal['step.validate'], *, step_id: str) -> StepValidation: ...
    @overload
    async def __call__(self, operation: Literal['step.confirm.manual'], *, step_id: str,
                       expected_hash: str, environment_id: str | None) -> StepRecord: ...


def reordered_ids(values, index, delta):
    target = index + delta
    if not 0 <= index < len(values) or not 0 <= target < len(values):
        return None
    result = list(values)
    result[index], result[target] = result[target], result[index]
    return result


@dataclass(frozen=True)
class StepActionResult:
    selected_step_id: str | None = None
    status: str = 'complete'
    steps: list[dict] = field(default_factory=list)
    index: int = -1
    target: int = -1
    failures: list[dict] = field(default_factory=list)
    confirmed_count: int = 0
    total: int = 0


class StepActions:
    def __init__(self, call: StepApplication, task_id: str, selected_step_id: str | None,
                 identity: Callable[[], tuple]):
        self.call, self.task_id, self.selected_step_id = call, task_id, selected_step_id
        self.identity = identity
        self.origin = identity()

    def is_current(self):
        return self.identity() == self.origin

    def accepts_repaint(self, expected):
        current = self.identity()
        return (len(expected) >= 4 and current[:3] == expected[:3]
                and isinstance(expected[-1], int) and current[-1] == expected[-1] + 1)

    async def add(self, catalog):
        if not self.is_current(): return None
        current = await self.call('step.list', task_id=self.task_id)
        if not self.is_current(): return None
        previous = current[-1]['capabilities'] if current else []
        plugins = {cap.split('.', 1)[0] for cap in previous}
        available = ([item['id'] for item in catalog['actions'] + catalog['tools']]
                     + catalog['result_handlers'] + catalog['resource_providers'])
        inherited = sorted(set(previous) | {cap for cap in available if cap.split('.', 1)[0] in plugins})
        saved = await self.call('step.save', task_id=self.task_id, document={
            'name': '新步骤', 'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n',
            'capabilities': inherited})
        return StepActionResult(selected_step_id=saved['step_id']) if self.is_current() else None

    async def reorder(self, delta):
        if not self.is_current(): return None
        current = await self.call('step.list', task_id=self.task_id)
        if not self.is_current(): return None
        ids = [step['step_id'] for step in current]
        index = ids.index(self.selected_step_id)
        updated = reordered_ids(ids, index, delta)
        if updated is None: return None
        await self.call('step.reorder', task_id=self.task_id, step_ids=updated)
        return StepActionResult(self.selected_step_id, steps=current, index=index, target=index + delta) if self.is_current() else None

    async def delete(self, steps, *, confirmed):
        if not confirmed or not self.is_current(): return None
        ids = [step['step_id'] for step in steps]
        index = ids.index(self.selected_step_id)
        await self.call('step.delete', step_id=self.selected_step_id)
        if not self.is_current(): return None
        remaining = [step_id for step_id in ids if step_id != self.selected_step_id]
        selected = remaining[index - 1] if index > 0 else (remaining[0] if remaining else None)
        return StepActionResult(selected_step_id=selected)

    async def confirm_all(self):
        if not self.is_current(): return None
        current = await self.call('step.list', task_id=self.task_id)
        if not self.is_current(): return None
        failures = []
        for index, candidate in enumerate(current, 1):
            try:
                validation = await self.call('step.validate', step_id=candidate['step_id'])
            except TaskError as exc:
                if not self.is_current(): return None
                failures.append(dict(index=index, step=candidate, reason=str(exc)))
                continue
            if not self.is_current(): return None
            if not validation['valid']:
                diagnostics = [item for item in validation.get('diagnostics', []) if item.get('severity') == 'error']
                reason = '；'.join(item.get('message') or item.get('code', '') for item in diagnostics)
                failures.append(dict(index=index, step=candidate, reason=reason or '校验未通过'))
        if failures:
            return StepActionResult(failures[0]['step']['step_id'], 'invalid', failures=failures)
        for index, candidate in enumerate(current, 1):
            if candidate['validation_state'] == 'VALIDATED': continue
            try:
                await self.call('step.confirm.manual', step_id=candidate['step_id'], expected_hash=candidate['content_hash'], environment_id=None)
            except TaskError as exc:
                if not self.is_current(): return None
                refreshed = await self.call('step.list', task_id=self.task_id)
                if not self.is_current(): return None
                ids = {item['step_id'] for item in current}
                count = sum(item['validation_state'] == 'VALIDATED' for item in refreshed if item['step_id'] in ids)
                return StepActionResult(candidate['step_id'], 'partial', failures=[dict(index=index, step=candidate, reason=str(exc))], confirmed_count=count, total=len(current))
            if not self.is_current(): return None
        return StepActionResult()
