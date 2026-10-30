"""Context draft ordering, request defaults and recording acknowledgement state."""
import copy
import json
from datetime import datetime
from typing import Awaitable, Callable, Literal, Protocol, TypedDict
from taskweave.core.json_types import JSON
from taskweave.core.validation import TaskError
from taskweave.core.context_collection import capture_ai_payload


class RecordingBatch(TypedDict):
    recording_id: str
    session_id: str
    state: str
    cursor: int
    available_after: int
    dropped_count: int
    has_more: bool
    capture: dict[str, JSON]


class RecordingOperation(Protocol):
    async def __call__(self, operation: Literal['start', 'pause', 'resume', 'stop', 'read', 'ack', 'discard'], *,
                       provider_id: str, request: dict[str, JSON] | None = None,
                       recording_id: str | None = None, expected_session_id: str | None = None,
                       run_id: str | None = None, environment_id: str | None = None,
                       execution_path: str | None = None,
                       include_view: bool = True, after: int = 0, limit: int = 100,
                       through: int | None = None) -> RecordingBatch: ...


class ContextCaptureDraft:
    """Mutable modal-only ordering and tombstones for one context group."""

    def __init__(self, captures=()):
        self.entries = [{"capture_id": item["capture_id"], "label": item.get("label", ""), "original_label": item.get("label", ""),
                         "captured_at": item.get("captured_at"), "source_page": item.get("source_page"),
                         "operation_notes": item.get("operation_notes", ""), "send_preview": bool(item.get("send_preview")),
                         "original_notes": item.get("operation_notes", ""), "original_send": bool(item.get("send_preview")),
                         "has_preview": bool(item.get("has_preview") or item.get("views")),
                         "is_new": False} for item in captures]
        self.original_order = tuple(item['capture_id'] for item in self.entries)
        self.deleted = []

    @property
    def dirty(self):
        order = tuple(item['capture_id'] for item in self.entries if not item.get('is_new'))
        return bool(self.deleted or order != self.original_order or any(item.get("operation_notes", "") != item.get("original_notes", "") or bool(item.get("send_preview")) != bool(item.get("original_send")) or item.get("is_new") or item.get("label") != item.get("original_label", item.get("label")) for item in self.entries))

    def append(self, capture, request, include_view, source_session_id=None, source_page="planning", label=""):
        if not capture.get("items") and not capture.get("views"):
            raise TaskError("CONTEXT_EMPTY", "插件没有返回上下文内容或预览")
        item = {"capture": capture, "request": request or {}, "include_view": include_view,
                "source_session_id": source_session_id, "source_page": source_page,
                "captured_at": datetime.now().astimezone().isoformat(timespec='seconds'),
                "label": label, "operation_notes": "", "send_preview": False, "is_new": True}
        self.entries.append(item)
        return item

    def remove(self, item):
        index = self.entries.index(item)
        if not item.get('is_new'):
            item['_before_item'] = self.entries[index - 1] if index else None
            item['_after_item'] = self.entries[index + 1] if index + 1 < len(self.entries) else None
            item['_delete_index'] = index
        self.entries.remove(item)
        if not item.get("is_new"):
            self.deleted.append(item)

    def undo_delete(self, item):
        self.deleted.remove(item)
        after_item, before_item = item.pop('_after_item', None), item.pop('_before_item', None)
        delete_index = item.pop('_delete_index', len(self.entries))
        after_index = next((index for index, entry in enumerate(self.entries) if entry is after_item), None)
        before_index = next((index for index, entry in enumerate(self.entries) if entry is before_item), None)
        if after_index is not None:
            index = after_index
        elif before_index is not None:
            index = before_index + 1
        else:
            index = min(delete_index, len(self.entries))
        self.entries.insert(index, item)

    def move(self, item, direction):
        index = self.entries.index(item)
        other = index + (-1 if direction == "up" else 1)
        if 0 <= other < len(self.entries):
            self.entries[index], self.entries[other] = self.entries[other], self.entries[index]

    def payload(self):
        return [{key: item[key] for key in ("capture_id", "label", "operation_notes", "send_preview")} if not item.get("is_new") else
                {key: item[key] for key in ("capture", "request", "include_view", "source_session_id", "source_page", "captured_at", "label", "operation_notes", "send_preview")}
                for item in self.entries]


def context_target_options(request_schema):
    """Return plugin-owned target picker behavior, or None for plain forms."""
    options = request_schema.get("x-taskweave-context-targets")
    if not isinstance(options, dict):
        return None
    return {
        "selector_label": options.get("selector_label", "上下文实例"),
        "parameter_mode_label": options.get("parameter_mode_label", "使用插件参数"),
        "auto_select_single": bool(options.get("auto_select_single", False)),
        "hide_parameters_when_selected": bool(
            options.get("hide_parameters_when_selected", False)
        ),
        "keep_parameters_when_selected": tuple(options.get("keep_parameters_when_selected", ())),
    }


def context_hidden_parameters(request_schema, target_selected):
    """Return form fields supplied by a selected target rather than by the user."""
    if not target_selected:
        return set()
    options = context_target_options(request_schema)
    if not options or not options["hide_parameters_when_selected"]:
        return set()
    properties = request_schema.get("properties", {})
    return set(properties) - set(options["keep_parameters_when_selected"])


def context_view_default(request_schema):
    options = request_schema.get("x-taskweave-context-view")
    return bool(options.get("default", True)) if isinstance(options, dict) else None


def context_surface_defaults(request_schema, surface):
    """Plugin-provided form defaults for a specific authoring surface."""
    surfaces = request_schema.get("x-taskweave-context-surface-defaults", {})
    values = surfaces.get(surface, {}) if isinstance(surfaces, dict) else {}
    properties = request_schema.get("properties", {})
    return {key: value for key, value in values.items() if key in properties} if isinstance(values, dict) else {}


def context_advanced_overrides(request_schema, request):
    """Return persisted plugin parameters that have no generated form control."""
    properties = request_schema.get("properties", {})
    known = set(properties) if isinstance(properties, dict) else set()
    return {
        key: value for key, value in (request or {}).items()
        if key not in known and key != "target_id"
    }


def merge_context_request(form_values, advanced_overrides, target_request=None):
    """Merge plugin form, advanced and selected-target values in UI precedence order."""
    if not isinstance(advanced_overrides, dict):
        raise TaskError("FORM_INVALID", "高级参数需要 JSON 对象")
    request = dict(form_values)
    request.update(advanced_overrides)
    request.update(target_request or {})
    return request


class RecordingDraft:
    def __init__(self, draft: ContextCaptureDraft, invoke: RecordingOperation, *, source_page='planning', source_session_id=None):
        self.draft, self.invoke = draft, invoke
        self.source_page, self.source_session_id = source_page, source_session_id
        self.options = {}
        self.recording_id = self.session_id = None
        self.state = None
        self.entry = None
        self.cursor = 0
        self.busy = False
        self.committed = False
        self.saved_result = None

    @property
    def pending(self):
        return self.recording_id is not None

    async def _command(self, operation, **parameters):
        options = {**self.options, **parameters}
        if self.recording_id is not None:
            options.update(recording_id=self.recording_id, expected_session_id=self.session_id)
        result = await self.invoke(operation, **options)
        if self.recording_id is not None and (
                result['recording_id'] != self.recording_id or result['session_id'] != self.session_id):
            raise TaskError('CONTEXT_SESSION_CHANGED', '录制返回了不同实例，未消费证据')
        self.recording_id, self.session_id = result['recording_id'], result['session_id']
        self.state = result['state']
        return result

    def _enter(self):
        if self.busy:
            raise TaskError('CONTEXT_SESSION_BUSY', '录制操作尚未完成')
        self.busy = True

    async def start(self, options, *, include_view):
        self._enter()
        try:
            if self.pending:
                raise TaskError('CONTEXT_RECORDING_PENDING', '请先处理已有录制')
            self.options = copy.deepcopy(options)
            self.source_session_id = self.options.get('run_id') or self.source_session_id
            if self.options.get('run_id') and self.options.get('execution_path'):
                self.source_session_id = self.options['run_id'] + '|' + self.options['execution_path']
            self.options['include_view'] = bool(include_view)
            # The first selected instance is used for start; all subsequent
            # commands freeze the identity returned by the provider.
            selected_session = self.options.pop('expected_session_id', None)
            await self._command('start', **({'expected_session_id': selected_session} if selected_session else {}))
            self.committed = False
            self.saved_result = self.entry = None
        finally:
            self.busy = False

    async def set_paused(self, paused):
        self._enter()
        try:
            if not self.pending or self.state not in {'RECORDING', 'PAUSED'}:
                raise TaskError('CONTEXT_RECORDING_STATE_INVALID')
            await self._command('pause' if paused else 'resume')
        finally:
            self.busy = False

    async def stage(self):
        self._enter()
        try:
            if self.entry is not None:
                return self.entry
            if not self.pending:
                raise TaskError('CONTEXT_RECORDING_UNAVAILABLE')
            await self._command('stop')
            items, views, after = [], [], 0
            dropped, available_after = 0, 0
            # Provider/host limits guard each batch; an explicit upper bound
            # also prevents an erroneous provider from an infinite read loop.
            for _ in range(100):
                last_after = after
                batch = await self._command('read', after=after, limit=100, include_view=False)
                cursor = batch['cursor']
                if cursor < after or (batch.get('has_more') and cursor <= after):
                    raise TaskError('CONTEXT_RECORDING_CURSOR_INVALID', '录制读取未推进，缓冲仍保留')
                items.extend(batch['capture']['items'])
                if batch['capture'].get('views'):
                    views = batch['capture']['views']
                dropped = max(dropped, batch.get('dropped_count', 0))
                available_after = max(available_after, batch.get('available_after', 0))
                after = cursor
                if not batch.get('has_more'):
                    if self.options['include_view']:
                        preview = await self._command('read', after=last_after, limit=100, include_view=True)
                        if preview['cursor'] != cursor or preview.get('has_more'):
                            raise TaskError('CONTEXT_RECORDING_CURSOR_INVALID', '已停止录制在读取预览时变化，缓冲仍保留')
                        views = preview['capture'].get('views', [])
                    break
            else:
                raise TaskError('CONTEXT_RECORDING_RESULT_INVALID', '录制分批过多，缓冲仍保留')
            metadata = {'recording_id': self.recording_id, 'session_id': self.session_id,
                        'through': after, 'available_after': available_after,
                        'dropped_count': dropped}
            items.insert(0, {'kind': 'text', 'mime_type': 'application/json',
                             'source': 'context.recording', 'content': json.dumps(metadata),
                             'truncated': dropped > 0})
            self.entry = self.draft.append({'items': items, 'views': views},
                self.options.get('request', {}), self.options['include_view'],
                self.source_session_id or self.session_id, self.source_page, '人工操作录制')
            self.cursor = after
            return self.entry
        finally:
            self.busy = False

    async def persist(self, save: Callable[[], Awaitable[dict | None]]):
        self._enter()
        try:
            if self.pending and (self.state != 'STOPPED' or self.entry is None
                                 or not any(entry is self.entry for entry in self.draft.entries)):
                raise TaskError('CONTEXT_RECORDING_PENDING', '请先停止并暂存录制；移除的录制请明确丢弃')
            if not self.committed:
                result = await save()
                if result is None:
                    raise TaskError('CONTEXT_RECORDING_PENDING', '保存未提交，录制证据仍保留，请重新保存')
                self.saved_result = result
                self.committed = True
            if self.pending:
                await self._command('ack', through=self.cursor)
                self.recording_id = None
            return self.saved_result
        finally:
            self.busy = False

    async def discard(self):
        self._enter()
        try:
            if self.committed:
                raise TaskError('CONTEXT_RECORDING_PENDING', '录制已保存，请重试确认；丢弃不会撤销已保存内容')
            if self.pending:
                await self._command('discard')
                self.recording_id = None
            if self.entry is not None:
                self.draft.entries[:] = [entry for entry in self.draft.entries if entry is not self.entry]
                self.entry = None
        finally:
            self.busy = False


class CollectionSession:
    """Plain shared collection state; a view separately owns its dialog and controls."""
    def __init__(self, draft: ContextCaptureDraft):
        self.draft = draft
        self.fields = {}
        self.recording = None
        self.busy = False

    def bind(self, invoke: RecordingOperation, *, source_page: str, source_session_id: str | None = None):
        if self.recording is None:
            self.recording = RecordingDraft(self.draft, invoke, source_page=source_page,
                                            source_session_id=source_session_id)
        else:
            self.recording.invoke = invoke

    def begin_operation(self, *, capture=False):
        if self.busy or (capture and self.recording.committed):
            return False
        self.busy = True
        return True

    def finish_operation(self):
        self.busy = False

    def metadata_changed(self, initial_name, initial_notes):
        return (self.fields.get('name') or '') != initial_name or (self.fields.get('notes') or '') != initial_notes

    def save_decision(self, existing, initial_name, initial_notes):
        if self.busy:
            return 'busy'
        if existing and not self.recording.pending and not self.recording.committed and not self.draft.dirty and not self.metadata_changed(initial_name, initial_notes):
            return 'unchanged'
        return 'save'

    def cancel_decision(self, initial_name, initial_notes):
        if self.busy:
            return 'busy'
        if self.recording.committed:
            return 'committed'
        if self.recording.pending or self.draft.dirty or self.metadata_changed(initial_name, initial_notes):
            return 'confirm'
        return 'close'

    async def cancel(self, initial_name, initial_notes, *, approved=False):
        decision = self.cancel_decision(initial_name, initial_notes)
        if decision in {'busy', 'committed'} or (decision == 'confirm' and not approved):
            return False
        await self.recording.discard()
        return True

    async def hide(self):
        if self.recording and self.recording.pending and not self.recording.busy and self.recording.state == 'RECORDING':
            await self.recording.set_paused(True)


def context_ai_items(entries, renderers=None):
    """Preserve group and capture order while keeping plugin items intact."""
    groups=[{
        "context_id": group["context_id"], "provider_id": group["provider_id"],
        "name": group["name"], "context_notes": group.get("context_notes", ""),
        "order_index": group.get("order_index", order),
        "captures": [capture_ai_payload(capture, index, renderers or {})
                     for index, capture in enumerate(group.get("captures", []))
                     if capture.get("items") or (capture.get("send_preview") and capture.get("views"))],
    } for order, group in enumerate(entries) if any(c.get("items") or (c.get("send_preview") and c.get("views")) for c in group.get("captures", []))]

    if groups or not entries:
        return groups
    # In-memory callers may pass a newly collected response before refreshing summaries.
    return [{**item,"context_name":group['name'],"context_notes":group.get('context_notes',''),"order_index":group.get('order_index',index)} for index,group in enumerate(entries) for item in (group.get('item') if isinstance(group.get('item'),list) else [group.get('item')]) if item]
