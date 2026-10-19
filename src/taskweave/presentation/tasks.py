"""Task editing and workspace transition policy, independent of visual panels."""
from typing import Callable, Literal, Protocol, overload
from taskweave.core.data_contracts import TaskRecord
from taskweave.core.json_types import JSON
from taskweave.core.validation import TaskError


class TaskApplication(Protocol):
    @overload
    async def __call__(self, operation: Literal['task.create'], *, name: str,
                       input_schema: dict[str, JSON], description: str) -> TaskRecord: ...
    @overload
    async def __call__(self, operation: Literal['task.update'], *, task_id: str, name: str,
                       input_schema: dict[str, JSON], description: str) -> TaskRecord: ...
    @overload
    async def __call__(self, operation: Literal['organization.metadata.set'], *, entity: Literal['task'],
                       entity_id: str, is_favorite: bool, category_id: str | None) -> dict[str, JSON]: ...


class TaskCommands:
    def __init__(self, call: TaskApplication):
        self.call = call

    async def save(self, task: dict | None, name: str, input_schema: dict, description: str) -> dict:
        if not name.strip():
            raise TaskError('FORM_INVALID', '请填写任务名称')
        saved = await self.call('task.update' if task else 'task.create',
            **({'task_id': task['task_id']} if task else {}), name=name.strip(),
            input_schema=input_schema, description=description)
        return task if task is not None else saved


from dataclasses import dataclass
import asyncio

UNSET = object()


@dataclass(frozen=True)
class OrganizationResult:
    saved: bool
    current: bool
    metadata: dict | None = None


class TaskOrganization:
    """Serialize metadata edits against the latest successful values for a task."""
    def __init__(self, call: TaskApplication, identity: Callable[[], tuple[str | int | None, ...]]):
        self.call, self.identity = call, identity
        self.records = {}
        self.locks = {}

    def remember(self, tasks):
        for task in tasks:
            self.records[task['task_id']] = {
                'is_favorite': bool(task.get('is_favorite')), 'category_id': task.get('category_id')}

    def metadata(self, task):
        return self.records.setdefault(task['task_id'], {
            'is_favorite': bool(task.get('is_favorite')), 'category_id': task.get('category_id')})

    async def update(self, task, *, favorite=UNSET, category_id=UNSET, toggle_favorite=False):
        origin, task_id = self.identity(), task['task_id']
        async with self.locks.setdefault(task_id, asyncio.Lock()):
            if origin != self.identity():
                return OrganizationResult(False, False)
            current = self.metadata(task).copy()
            if toggle_favorite:
                current['is_favorite'] = not current['is_favorite']
            elif favorite is not UNSET:
                current['is_favorite'] = bool(favorite)
            if category_id is not UNSET:
                current['category_id'] = category_id
            await self.call('organization.metadata.set', entity='task', entity_id=task_id, **current)
            self.records[task_id] = current
            task.update(current)
            return OrganizationResult(True, origin == self.identity(), current.copy())


class TaskDraft:
    def __init__(self, task=None):
        import json
        self.name = task['name'] if task else ''
        self.description = task['description'] if task else ''
        self.schema_original = json.loads(task['input_schema_json']) if task else {'type': 'object', 'properties': {}}
        from copy import deepcopy
        self.schema_rows = [
            [name, spec.get('type', 'string'),
             (json.dumps(spec['default'], ensure_ascii=False) if 'default' in spec and spec.get('type') != 'string'
              else spec.get('default', '')), spec.get('description', ''),
             name in self.schema_original.get('required', []), deepcopy(spec)]
            for name, spec in self.schema_original.get('properties', {}).items()
        ]

    def schema(self):
        from taskweave.presentation.forms import schema_from_rows
        return schema_from_rows(self.schema_original, self.schema_rows)
