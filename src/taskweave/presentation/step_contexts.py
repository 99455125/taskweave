"""Context group commands and late-result guards for one step selection."""
from copy import deepcopy
from typing import Callable, Literal, Protocol, TypedDict, overload
from taskweave.core.data_contracts import CommandResult
from taskweave.core.json_types import JSON
from taskweave.presentation.state import ContextPageState
from taskweave.presentation.context_collection import context_ai_items


class ContextBatchResult(TypedDict):
    group: dict[str, JSON]


class StepContextOperations(Protocol):
    @overload
    async def __call__(self, operation: Literal['context.list'], *, step_id: str) -> list[dict[str, JSON]]: ...
    @overload
    async def __call__(self, operation: Literal['context.save_batch'], *, step_id: str,
                       context_id: str | None, expected_revision: int | None, provider_id: str,
                       name: str, context_notes: str, captures: list[dict[str, JSON]]) -> ContextBatchResult: ...
    @overload
    async def __call__(self, operation: Literal['context.reorder'], *, step_id: str,
                       context_id: str, direction: Literal['up', 'down'], expected_revision: int | None) -> list[dict[str, JSON]]: ...
    @overload
    async def __call__(self, operation: Literal['context.delete'], *, step_id: str,
                       context_id: str, expected_revision: int | None) -> CommandResult: ...


class StepContexts:
    def __init__(self, call: StepContextOperations, state: ContextPageState,
                 identity: Callable[[], tuple[int, str | None, str | None]]):
        self.call, self.state, self.identity = call, state, identity

    def refresh_ai(self):
        self.state.ai_contexts = context_ai_items(self.state.entries)

    async def save_batch(self, step_id, existing, provider, name, notes, captures):
        identity = self.identity()
        result = await self.call('context.save_batch', step_id=step_id,
            context_id=(existing or {}).get('context_id'), expected_revision=(existing or {}).get('revision'),
            provider_id=provider, name=name, context_notes=notes, captures=deepcopy(captures))
        group = result['group']
        current = self.identity() == identity
        if current:
            previous = next((item for item in self.state.entries if item['context_id'] == group['context_id']), None)
            if previous: previous.update(group)
            else: self.state.entries.append(group)
            self.refresh_ai()
        return group, current

    async def reload(self, step_id):
        identity = self.identity()
        entries = await self.call('context.list', step_id=step_id)
        if self.identity() != identity:
            return False
        self.state.entries = entries
        self.refresh_ai()
        return True

    async def reorder(self, step_id, entry, direction):
        identity = self.identity()
        updated = await self.call('context.reorder', context_id=entry['context_id'], direction=direction,
                                  expected_revision=entry.get('revision'), step_id=step_id)
        if self.identity() != identity:
            return False
        latest = {row['context_id']: row for row in updated}
        for current in self.state.entries: current.update(latest.get(current['context_id'], {}))
        return True

    async def remove(self, step_id, entry):
        identity = self.identity()
        await self.call('context.delete', context_id=entry['context_id'], expected_revision=entry.get('revision'), step_id=step_id)
        if self.identity() != identity:
            return False
        if entry in self.state.entries: self.state.entries.remove(entry)
        self.refresh_ai()
        return True
