"""Environment form drafts, save ownership and leave decisions without widgets."""
import asyncio
from copy import deepcopy
from dataclasses import dataclass
import json
from typing import Awaitable, Callable, Literal, Protocol, TypedDict
from taskweave.core.json_types import JSON

from taskweave.core.validation import TaskError


class EnvironmentRecord(TypedDict):
    environment_id: str


class EnvironmentOperation(Protocol):
    async def __call__(self, operation: Literal['environment.save'], *, name: str,
                       public_config: dict[str, JSON], secret_refs: dict[str, str],
                       descriptions: dict[str, str], environment_id: str | None) -> EnvironmentRecord: ...


@dataclass(eq=False)
class EnvironmentRow:
    key: str = ''
    value: str = ''
    description: str = ''
    secret_reference: str | None = None


class EnvironmentDraft:
    def __init__(self, selected=None):
        self.environment_id = selected['environment_id'] if selected else None
        self.name = selected['name'] if selected else ''
        self.rows = []
        if selected:
            values = json.loads(selected['public_config_json'])
            secrets = json.loads(selected.get('secret_refs_json') or '{}')
            descriptions = json.loads(selected.get('descriptions_json') or '{}')
            values.update(secrets)
            for key, value in values.items():
                self.add(key, value if isinstance(value, str) else json.dumps(value, ensure_ascii=False),
                         descriptions.get(key, ''), secrets.get(key))
        self.baseline = self.snapshot()

    def add(self, key='', value='', description='', secret_reference=None):
        row = EnvironmentRow(key, value, description, secret_reference)
        self.rows.append(row)
        return row

    def remove(self, row):
        self.rows.remove(row)

    def snapshot(self):
        return self.name, tuple((row.key, row.value, row.description) for row in self.rows)

    @property
    def dirty(self):
        return self.snapshot() != self.baseline

    def secret_refs(self):
        refs = {}
        for row in self.rows:
            if row.secret_reference is None:
                continue
            key = (row.key or '').strip()
            if not key:
                raise TaskError('FORM_INVALID', 'Key 不能为空或重复')
            if row.value != row.secret_reference and not (
                    isinstance(row.value, str) and row.value.startswith('env:')):
                raise TaskError('FORM_INVALID', '密钥变量必须保留环境变量引用')
            refs[key] = row.value
        return refs


@dataclass(frozen=True)
class EnvironmentSave:
    saved: dict
    current: bool


def environment_values(name, rows, environment_id=None, secret_refs=None):
    if not (name or '').strip():
        raise TaskError('FORM_INVALID', '请填写环境名称')
    values, descriptions = {}, {}
    for key, value, description in rows:
        field = (key or '').strip()
        if not field or field in values:
            raise TaskError('FORM_INVALID', 'Key 不能为空或重复')
        try:
            values[field] = json.loads(value)
        except (ValueError, TypeError):
            values[field] = value
        if description and description.strip():
            descriptions[field] = description.strip()
    return dict(name=name.strip(), public_config=values, secret_refs=secret_refs or {},
                descriptions=descriptions, environment_id=environment_id)


class EnvironmentSession:
    def __init__(self, call: EnvironmentOperation, page_identity: Callable[[], object]):
        self.call, self.page_identity = call, page_identity
        self.selected_environment_id = None
        self.search_query = ''
        self.creating = False
        self.generation = 0
        self.form_token = None
        self.draft = EnvironmentDraft()
        self.save_lock = asyncio.Lock()

    def view_identity(self):
        return self.page_identity(), self.generation, self.selected_environment_id

    def form_identity(self):
        if self.form_token is None:
            return None
        return self.page_identity(), self.generation, self.form_token

    def form_current(self, identity):
        return identity is not None and identity == self.form_identity()

    def view_current(self, identity):
        return identity == self.view_identity()

    def begin_render(self):
        self.generation += 1
        self.form_token = self.generation

    def choose_initial(self, environments, default):
        ids = {item['environment_id'] for item in environments}
        if self.selected_environment_id not in ids and not self.creating:
            self.selected_environment_id = default if default in ids else (environments[0]['environment_id'] if environments else None)
        return next((item for item in environments if item['environment_id'] == self.selected_environment_id), None)

    def mount(self, selected):
        self.draft = EnvironmentDraft(selected)
        if selected:
            self.selected_environment_id = selected['environment_id']

    def create(self, expected_view=None):
        if expected_view is not None and not self.same_render(expected_view):
            return False
        self.selected_environment_id, self.creating = None, True
        return True

    def select(self, environment_id, expected_view=None):
        if expected_view is not None and not self.same_render(expected_view):
            return False
        self.selected_environment_id, self.creating = environment_id, False
        return True

    def same_render(self, identity):
        return identity[:2] == self.view_identity()[:2]

    async def save_values(self, name, rows, *, environment_id=None, secret_refs=None, form_identity=None):
        form = form_identity or self.form_identity()
        origin = self.view_identity()
        creating = self.creating
        saved = await self.call('environment.save', **environment_values(name, rows, environment_id, secret_refs))
        current = (self.form_current(form) and self.selected_environment_id == origin[2]
                   and self.creating == creating) if form is not None else self.view_current(origin)
        if current:
            self.selected_environment_id = saved['environment_id']
            self.creating = False
        return EnvironmentSave(saved, current)

    async def save_draft(self):
        draft, identity = self.draft, self.form_identity()
        async with self.save_lock:
            name, rows = deepcopy(draft.snapshot())
            result = await self.save_values(name, rows, environment_id=draft.environment_id,
                                           secret_refs=draft.secret_refs(), form_identity=identity)
            if result.current and draft is self.draft:
                draft.environment_id = result.saved['environment_id']
                draft.baseline = (name, rows)
            return result

    def leave_decision(self, identity):
        if not self.form_current(identity):
            return 'stay'
        return 'ask' if self.draft.dirty else 'allow'

    async def leave(self, identity, choice):
        if not self.form_current(identity) or choice not in {'save', 'discard'}:
            return False
        if choice == 'discard':
            return True
        result = await self.save_draft()
        return result.current and self.form_current(identity)

    async def set_default(self, environment_id, identity, save: Callable[[str | None], Awaitable[None]]):
        await save(environment_id)
        return self.view_current(identity) and environment_id == self.selected_environment_id
