"""Serialized editor commands, independent of controls and page rendering."""
from copy import deepcopy
from typing import Awaitable, Callable
from taskweave.core.validation import TaskError, normalize_step
from taskweave.presentation.state import StepEditorState


class EditorSession:
    def __init__(self, state: StepEditorState, save_draft: Callable[[str, dict, dict | None], Awaitable[dict]],
                 page_generation: Callable[[], int]):
        self.state, self.save_draft, self.page_generation = state, save_draft, page_generation

    def identity(self):
        return self.state.task_id, self.state.step_id, self.state.generation, self.page_generation()

    async def save(self, document: dict) -> dict:
        identity = self.identity()
        document = deepcopy(document)
        async with self.state.save_lock:
            if self.identity() != identity:
                raise TaskError('EDITOR_CHANGED', '步骤已切换，请重新保存当前草稿。')
            saved = await self.save_draft(identity[0], document, self.state.old_step)
            if self.identity() == identity:
                self.state.old_step = saved
                self.state.step_id = saved['step_id']
            return saved


def is_dirty(document: dict, baseline: dict) -> bool:
    try:
        return normalize_step(document) != normalize_step(baseline)
    except (TaskError, ValueError, TypeError):
        return True


def document_from_draft(baseline: dict, draft: dict) -> dict:
    import json
    from taskweave.presentation.forms import schema_from_rows
    from taskweave.presentation.result_fields import result_fields
    fields = draft['fields']
    doc = normalize_step(baseline)
    doc.update(
        name=fields['name'], step_description=fields['step_description'],
        step_notes=fields['step_notes'], step_content=fields['code'],
        capabilities=sorted({action for plugin in (fields['caps'] or [])
                             for action in draft['plugin_actions'].get(plugin, [])}),
        input_schema=schema_from_rows(draft['schema_original'], draft['schema']),
        delay_after_previous_seconds=(int(fields['delay'] or 0)
                                      if float(fields['delay'] or 0).is_integer() else fields['delay']),
        timeout_ms=int(fields['timeout'] or 60) * 1000,
    )
    doc['bindings'] = {}
    for name, source, value, source_step, output, pointer in draft['bindings']:
        key = name.strip()
        if not key or key in doc['bindings']:
            raise TaskError('FORM_INVALID', '输入绑定名称不能为空或重复')
        if source == 'literal':
            try:
                literal = json.loads(value)
            except ValueError:
                literal = value
            doc['bindings'][key] = {'literal': literal}
        else:
            ref = {'source': source, 'pointer': pointer}
            if source == 'step':
                if not source_step:
                    raise TaskError('FORM_INVALID', '请选择前序步骤')
                ref.update(step_id=source_step, output=output or 'data')
            doc['bindings'][key] = {'ref': ref}
    properties = (doc['input_schema'].setdefault('properties', {}) if doc['bindings']
                  else doc['input_schema'].get('properties', {}))
    for key, binding in doc['bindings'].items():
        if key not in properties:
            kind = (result_fields(binding['literal'])['']['type'] if 'literal' in binding
                    else draft['field_types'].get(key, {}).get(binding['ref']['pointer'], 'string'))
            properties[key] = {'type': kind}
    return doc


class LeaveDecision:
    """Resolve leaving an editor after serialized saves and user choice."""
    def __init__(self, state, identity):
        self.state, self.identity = state, identity
        self.origin = identity()

    async def begin(self, dirty):
        self.origin = self.identity()
        async with self.state.save_lock:
            pass
        if self.identity() != self.origin:
            return 'stay'
        return 'ask' if dirty() else 'save'

    def resolve(self, choice):
        if self.identity() != self.origin:
            return 'stay'
        return choice if choice in {'save', 'discard'} else 'stay'
