"""Framework-independent planning drafts, candidate requests and collection commits."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass
from typing import Literal, Protocol, TypedDict, overload
from taskweave.core.json_types import JSON

from taskweave.presentation.context_collection import ContextCaptureDraft, RecordingDraft, RecordingBatch
from taskweave.presentation.state import PlanningPageState

PlanningOperation = Literal[
    'organization.metadata.set',
    'plan.get', 'plan.create', 'plan.copy', 'plan.delete', 'capabilities', 'environment.list',
    'plan.update', 'plan.generate', 'plan.generation.list', 'plan.generation.get',
    'plan.generation.parse', 'plan.generation.import', 'plan.generation.imports',
    'plan.context.read', 'plan.context.record', 'plan.context.save_batch',
    'plan.context.update', 'plan.context.delete', 'plan.context.reorder',
    'plan.context.capture.delete', 'plan.context.capture.reorder',
    'plan.context.capture.label', 'plan.context.list', 'instance.end',
]


ORGANIZATION_UNSET = object()


class _PlanRecordOptional(TypedDict, total=False):
    contexts: list[dict[str, JSON]]
    is_favorite: bool | int
    category_id: str | None
    created_at: str
    updated_at: str


class PlanRecord(_PlanRecordOptional):
    plan_id: str
    revision: int
    name: str
    plan_description: str
    plan_notes: str
    environment_id: str | None
    plugin_ids: list[str]


class PlanImportResult(TypedDict):
    task_id: str
    already_imported: bool


class PlanDeleteResult(TypedDict):
    deleted: bool
    plan_id: str


class PlanCaptureResult(TypedDict):
    capture: dict[str, JSON]
    session_id: str | None


class PlanContextSaveResult(TypedDict):
    plan: PlanRecord
    group: dict[str, JSON]


class PlanInstanceEndResult(TypedDict):
    ended: bool
    owner_id: str


class PlanningApplication(Protocol):
    @overload
    async def call(self, api_operation: Literal['organization.metadata.set'], *, entity: Literal['plan'],
                   entity_id: str, is_favorite: int | bool, category_id: str | None) -> dict[str, JSON]: ...
    @overload
    async def call(self, api_operation: Literal['plan.get'], *, plan_id: str) -> PlanRecord: ...
    @overload
    async def call(self, api_operation: Literal['plan.create'], *, name: str) -> PlanRecord: ...
    @overload
    async def call(self, api_operation: Literal['plan.copy'], *, plan_id: str, expected_revision: int) -> PlanRecord: ...
    @overload
    async def call(self, api_operation: Literal['plan.delete'], *, plan_id: str, expected_revision: int) -> PlanDeleteResult: ...
    @overload
    async def call(self, api_operation: Literal['capabilities']) -> dict[str, JSON]: ...
    @overload
    async def call(self, api_operation: Literal['environment.list']) -> list[dict[str, JSON]]: ...
    @overload
    async def call(self, api_operation: Literal['plan.update'], *, plan_id: str, expected_revision: int,
                   name: str, plan_description: str, plan_notes: str, environment_id: str | None,
                   plugin_ids: list[str]) -> PlanRecord: ...
    @overload
    async def call(self, api_operation: Literal['plan.generate'], *, plan_id: str, expected_revision: int,
                   channel: str) -> dict[str, JSON]: ...
    @overload
    async def call(self, api_operation: Literal['plan.generation.list'], *, plan_id: str) -> list[dict[str, JSON]]: ...
    @overload
    async def call(self, api_operation: Literal['plan.generation.get'], *, generation_id: str) -> dict[str, JSON]: ...
    @overload
    async def call(self, api_operation: Literal['plan.generation.parse'], *, generation_id: str,
                   response_text: str) -> dict[str, JSON]: ...
    @overload
    async def call(self, api_operation: Literal['plan.generation.import'], *, generation_id: str) -> PlanImportResult: ...
    @overload
    async def call(self, api_operation: Literal['plan.generation.imports'], *, generation_id: str) -> list[dict[str, JSON]]: ...
    @overload
    async def call(self, api_operation: Literal['plan.context.read'], *, plan_id: str, expected_revision: int,
                   provider_id: str, request: dict[str, JSON], expected_session_id: str | None,
                   include_view: bool) -> PlanCaptureResult: ...
    @overload
    async def call(self, api_operation: Literal['plan.context.record'], *, plan_id: str, expected_revision: int,
                   provider_id: str, operation: Literal['start', 'pause', 'resume', 'stop', 'read', 'ack', 'discard'],
                   request: dict[str, JSON] | None = None, recording_id: str | None = None,
                   after: int = 0, through: int | None = None, limit: int = 100,
                   expected_session_id: str | None = None, include_view: bool = True) -> RecordingBatch: ...
    @overload
    async def call(self, api_operation: Literal['plan.context.save_batch'], *, plan_id: str, expected_revision: int,
                   context_id: str | None, provider_id: str, name: str, context_notes: str,
                   captures: list[dict[str, JSON]]) -> PlanContextSaveResult: ...
    @overload
    async def call(self, api_operation: Literal['plan.context.update'], *, plan_id: str, expected_revision: int,
                   context_id: str, name: str, context_notes: str) -> PlanRecord: ...
    @overload
    async def call(self, api_operation: Literal['plan.context.delete'], *, plan_id: str, expected_revision: int,
                   context_id: str) -> PlanRecord: ...
    @overload
    async def call(self, api_operation: Literal['plan.context.reorder'], *, plan_id: str, expected_revision: int,
                   context_id: str, direction: Literal['up', 'down']) -> PlanRecord: ...
    @overload
    async def call(self, api_operation: Literal['plan.context.capture.delete'], *, plan_id: str,
                   expected_revision: int, context_id: str, capture_id: str) -> PlanRecord: ...
    @overload
    async def call(self, api_operation: Literal['plan.context.capture.reorder'], *, plan_id: str,
                   expected_revision: int, context_id: str, capture_id: str,
                   direction: Literal['up', 'down']) -> PlanRecord: ...
    @overload
    async def call(self, api_operation: Literal['plan.context.capture.label'], *, plan_id: str,
                   expected_revision: int, context_id: str, capture_id: str, label: str,
                   operation_notes: str | None = None, send_preview: bool | None = None) -> PlanRecord: ...
    @overload
    async def call(self, api_operation: Literal['plan.context.list'], *, plan_id: str) -> list[dict[str, JSON]]: ...
    @overload
    async def call(self, api_operation: Literal['instance.end'], *, instance_type: Literal['plan'], owner_id: str) -> PlanInstanceEndResult: ...

class PlanningInteraction:
    """Own request identity and accept candidates only for the selected planning session."""
    def __init__(self, application: PlanningApplication, state: PlanningPageState):
        self.application = application
        self.state = state
        self._candidate = None
        self._candidate_identity = None
        self._latest_request = 0
        self.history_revision = 0
        self.view_identity = ("planning", 0)
        self.editor_session = None
        self.organization = {}
        self.organization_locks = {}
        self.organization_refresh_lock = asyncio.Lock()

    def identity(self):
        return self.state.plan_id, self.state.generation, *self.view_identity

    @property
    def candidate(self):
        return self._candidate if self._candidate_identity == self.identity() else None

    def edit(self, plan: dict) -> PlanEditorSession:
        editor = PlanEditorSession(self.application, plan)
        if plan['plan_id'] == self.state.plan_id:
            self.editor_session = editor
        return editor

    def initialize_selection(self, plans):
        if self.state.plan_id is None and plans:
            self._select(plans[0]['plan_id'], new_generation=True)

    def set_view(self, name, generation):
        self.view_identity = (name, generation)

    def sync_organizations(self, plans):
        self.organization.clear()
        self.organization.update({item['plan_id']: {
            'is_favorite': int(bool(item.get('is_favorite'))),
            'category_id': item.get('category_id'),
        } for item in plans})

    async def set_organization(self, plan, favorite=None, category_id=ORGANIZATION_UNSET):
        plan_id = plan['plan_id']
        lock = self.organization_locks.setdefault(plan_id, asyncio.Lock())
        async with self.organization_refresh_lock, lock:
            current = self.organization.setdefault(plan_id, {
                'is_favorite': int(bool(plan.get('is_favorite'))),
                'category_id': plan.get('category_id'),
            })
            metadata = {
                'is_favorite': int(bool(current['is_favorite'] if favorite is None else favorite)),
                'category_id': current['category_id'] if category_id is ORGANIZATION_UNSET else category_id,
            }
            await self.application.call('organization.metadata.set', entity='plan', entity_id=plan_id, **metadata)
            current.update(metadata)
            plan.update(metadata)
            return metadata

    def is_current(self, identity):
        return identity == self.identity() and self.view_identity[0] == 'planning'

    def view_session(self):
        return PlanningViewSession(self, self.identity())

    async def save_current(self):
        origin = self.identity()
        editor = self.editor_session
        if editor is not None and editor.plan['plan_id'] == origin[0]:
            await editor.save()
        return self.is_current(origin)

    def _select(self, plan_id, *, new_generation=False):
        if new_generation or self.state.plan_id != plan_id:
            self.state.generation += 1
        self.state.plan_id = plan_id
        self.editor_session = None

    async def open(self, plan_id):
        if not await self.save_current():
            return False
        self._select(plan_id)
        return True

    async def create(self):
        if not await self.save_current():
            return None
        origin = self.identity()
        plan = await self.application.call('plan.create', name='新规划')
        if self.is_current(origin):
            self._select(plan['plan_id'], new_generation=True)
        return plan

    async def copy_plan(self, plan):
        if self.state.plan_id == plan['plan_id'] and not await self.save_current():
            return None
        origin = self.identity()
        current = await self.application.call('plan.get', plan_id=plan['plan_id'])
        copied = await self.application.call('plan.copy', plan_id=plan['plan_id'], expected_revision=current['revision'])
        if self.is_current(origin):
            self.state.search = ''
            self._select(copied['plan_id'], new_generation=True)
        return copied

    async def prepare_delete(self, plans, plan):
        if self.state.plan_id == plan['plan_id'] and not await self.save_current():
            return None
        origin = self.identity()
        current = await self.application.call('plan.get', plan_id=plan['plan_id'])
        if not self.is_current(origin):
            return None
        return PlanDeletion(origin, plan['plan_id'], current['revision'], next_plan_id(plans, plan['plan_id']))

    async def delete_plan(self, deletion, *, approved):
        if not approved or deletion is None or not self.is_current(deletion.identity):
            return False
        await self.application.call('plan.delete', plan_id=deletion.plan_id, expected_revision=deletion.revision)
        if not self.is_current(deletion.identity):
            return False
        if self.state.plan_id == deletion.plan_id:
            self._select(deletion.replacement, new_generation=True)
        return True

    def _accept(self, identity, candidate):
        if self.is_current(identity):
            self._candidate_identity, self._candidate = identity, candidate
            return True
        return False

    async def latest_generation(self, plan_id: str):
        identity = self.identity()
        if identity[0] != plan_id:
            return False, None
        self._latest_request += 1
        request = self._latest_request
        rows = await self.application.call('plan.generation.list', plan_id=plan_id)
        if identity != self.identity() or request != self._latest_request:
            return False, None
        candidate = (await self.application.call('plan.generation.get', generation_id=rows[0]['generation_id'])) if rows else None
        if request != self._latest_request:
            return False, None
        return self._accept(identity, candidate), candidate

    async def generate(self, plan: dict, channel: str):
        identity = self.identity()
        if plan['plan_id'] != identity[0]:
            return None
        try:
            result = await self.application.call('plan.generate', plan_id=plan['plan_id'], expected_revision=plan['revision'], channel=channel)
        finally:
            self.history_revision += 1
        self._accept(identity, result)
        return result

    async def parse_generation(self, generation_id: str, response_text: str, *, identity=None):
        identity = self.identity() if identity is None else identity
        try:
            result = await self.application.call('plan.generation.parse', generation_id=generation_id, response_text=response_text)
        finally:
            self.history_revision += 1
        self._accept(identity, result)
        return result

    async def import_generation(self, generation_id: str):
        result = await self.application.call('plan.generation.import', generation_id=generation_id)
        self.history_revision += 1
        return result

    async def generate_action(self, plan, channel):
        identity = self.identity()
        if not await self.save_current():
            return CandidateAction(identity, None, 'stale')
        result = await self.generate(plan, channel)
        return CandidateAction(identity, result, 'web_chat' if channel == 'web_chat' else 'preview')

    async def parse_action(self, generation_id, response_text, identity):
        value = await self.parse_generation(generation_id, response_text, identity=identity)
        return CandidateAction(identity, value, 'preview')

    async def import_action(self, generation_id, identity):
        value = await self.import_generation(generation_id)
        return CandidateAction(identity, value, 'import')

    async def select_action(self, generation_id, identity):
        if not self.is_current(identity):
            return CandidateAction(identity, None, 'stale')
        value = await self.generation(generation_id)
        self._accept(identity, value)
        return CandidateAction(identity, value, 'selected')

    def failed_action(self, identity):
        return CandidateAction(identity, None, 'failed')

    def effects(self, action):
        if not self.is_current(action.identity):
            return ()
        return {
            'preview': ('history', 'summary', 'preview'),
            'web_chat': ('history', 'summary', 'web_chat'),
            'import': ('receipts', 'history', 'summary', 'notify'),
            'selected': ('preview',),
            'failed': ('history', 'summary'),
        }.get(action.kind, ())

    async def generation(self, generation_id: str):
        return await self.application.call('plan.generation.get', generation_id=generation_id)

    async def history(self, plan_id: str):
        return await self.application.call('plan.generation.list', plan_id=plan_id)

    async def imports(self, generation_id: str):
        return await self.application.call('plan.generation.imports', generation_id=generation_id)

    async def end_collection(self, plan_id: str):
        return await self.application.call('instance.end', instance_type='plan', owner_id=plan_id)


@dataclass(frozen=True)
class CandidateAction:
    identity: tuple
    value: dict | None
    kind: Literal['preview', 'web_chat', 'import', 'selected', 'failed', 'stale']


@dataclass(frozen=True)
class PlanDeletion:
    identity: tuple
    plan_id: str
    revision: int
    replacement: str | None


def next_plan_id(plans, deleted_id):
    ids = [plan['plan_id'] for plan in plans]
    if deleted_id not in ids or len(ids) <= 1:
        return None
    index = ids.index(deleted_id)
    return ids[index + 1] if index + 1 < len(ids) else ids[index - 1]


class PlanningViewSession:
    """Lazy tab data and cache invalidation owned by one selected plan view."""
    def __init__(self, interaction: PlanningInteraction, identity: tuple):
        self.interaction, self.identity = interaction, identity
        self.selected_tab = '基础配置'
        self.history_loaded_revision = -1
        self.history_rows = []
        self.history_lock = asyncio.Lock()
        self.materials_lock = asyncio.Lock()
        self.materials = None

    @property
    def current(self):
        return self.interaction.is_current(self.identity)

    def select_tab(self, tab):
        if not self.current or tab not in {'基础配置', '能力与素材', '生成记录'}:
            return False
        self.selected_tab = tab
        return True

    def invalidate_history(self):
        if not self.current:
            return False
        self.interaction.history_revision += 1
        return self.selected_tab == '生成记录'

    async def load_history(self):
        async with self.history_lock:
            if not self.current:
                return False, None
            revision = self.interaction.history_revision
            if revision == self.history_loaded_revision:
                return True, None
            rows = await self.interaction.history(self.identity[0])
            if not self.current:
                return False, None
            self.history_rows = rows
            self.history_loaded_revision = revision
            return True, rows

    async def load_materials(self):
        async with self.materials_lock:
            if not self.current:
                return None
            if self.materials is None:
                result = await asyncio.gather(self.interaction.application.call('capabilities'),
                                              self.interaction.application.call('environment.list'))
                if not self.current:
                    return None
                self.materials = tuple(result)
            return self.materials


class PlanEditorSession:
    """One plan's saved revision and unsaved values, shared by all its operations."""
    def __init__(self, application: PlanningApplication, plan: dict):
        self.application, self.plan = application, plan
        self.lock = asyncio.Lock()
        self.draft = deepcopy({
            'name': plan.get('name', '新规划'),
            'plan_description': plan.get('plan_description', ''),
            'plan_notes': plan.get('plan_notes', ''),
            'environment_id': plan.get('environment_id'),
            'plugin_ids': plan.get('plugin_ids', []),
        })

    def change(self, field: str, value: object):
        if field not in self.draft:
            raise ValueError(field)
        self.draft[field] = deepcopy(value)

    def values(self):
        values = deepcopy(self.draft)
        values['name'] = (values['name'] or '').strip() or '新规划'
        return values

    @property
    def dirty(self):
        return any(self.plan.get(key) != value for key, value in self.values().items())

    async def save(self):
        async with self.lock:
            current = self.values()
            if not any(self.plan.get(key) != value for key, value in current.items()):
                return self.plan
            updated = await self.application.call('plan.update', plan_id=self.plan['plan_id'], expected_revision=self.plan['revision'], **current)
            self.plan.update(updated)
            return self.plan

    async def mutate_context(self, operation: PlanningOperation, context_id: str, **params: object):
        async with self.lock:
            updated = await self.application.call(operation, plan_id=self.plan['plan_id'], expected_revision=self.plan['revision'], context_id=context_id, **params)
            self.plan.update(updated)
            return updated


    async def prepare_capture_change(self, operation: PlanningOperation, context_id: str, capture_id: str, **params: object):
        """Return persisted data; the owner accepts it only while its session is current."""
        return await self.application.call(operation, plan_id=self.plan['plan_id'], expected_revision=self.plan['revision'], context_id=context_id, capture_id=capture_id, **params)

    async def capture_group(self, updated: dict, context_id: str):
        groups = updated.get('contexts')
        if groups is None:
            groups = await self.application.call('plan.context.list', plan_id=self.plan['plan_id'])
        return next((item for item in groups if item.get('context_id') == context_id), None)

    def sync_group(self, group):
        contexts = self.plan.setdefault('contexts', [])
        current = next((item for item in contexts if item['context_id'] == group['context_id']), None)
        if current is not None:
            current.update(group)
        else:
            contexts.append(group)

    def accept(self, updated: dict):
        self.plan.update(updated)


class PlanningCollection:
    """Stage collected evidence and commit once before acknowledging recording data."""
    def __init__(self, application: PlanningApplication, plan: dict, draft: ContextCaptureDraft, context_id: str | None = None):
        self.application, self.plan, self.draft = application, plan, draft
        self.context_id = context_id

    async def record(self, operation: str, **options: object):
        return await self.application.call('plan.context.record', plan_id=self.plan['plan_id'], expected_revision=self.plan['revision'], operation=operation, **options)

    async def collect(self, provider_id: str, request: dict, session_id: str | None, include_view: bool):
        result = await self.application.call('plan.context.read', plan_id=self.plan['plan_id'], expected_revision=self.plan['revision'], provider_id=provider_id, request=request, expected_session_id=session_id, include_view=include_view)
        capture = result['capture']
        label = (capture.get('items') or [{}])[0].get('source') or f'采集 {len(self.draft.entries) + 1}'
        return self.draft.append(capture, request, include_view, result.get('session_id'), 'planning', label)

    async def save(self, recording: RecordingDraft, provider_id: str, name: str, notes: str):
        async def commit():
            result = await self.application.call('plan.context.save_batch', plan_id=self.plan['plan_id'], expected_revision=self.plan['revision'], context_id=self.context_id, provider_id=provider_id, name=name, context_notes=notes, captures=self.draft.payload())
            self.plan.update(result['plan'])
            return result
        return await recording.persist(commit)
