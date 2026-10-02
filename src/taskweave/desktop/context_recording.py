"""Shared recording draft lifecycle, independent of modal presentation.

Browser/plugin commands never commit captures. The owning dialog explicitly
persists the whole context group, then confirms the returned recording cursor.
"""
import copy
import json
from taskweave.core.validation import TaskError


def collection_workspace(owner, key, captures):
    cache = getattr(owner, '_collection_workspaces', None)
    if cache is None:
        owner._collection_workspaces = cache = {}
    if key not in cache:
        from taskweave.desktop.contexts import ContextCaptureDraft
        cache[key] = CollectionWorkspace(cache, key, ContextCaptureDraft(captures))
    return cache[key]


class CollectionWorkspace:
    """Client-owned draft survives ESC/hidden dialogs without consuming evidence."""
    def __init__(self, cache, key, draft):
        self.cache, self.key, self.draft = cache, key, draft
        self.fields = {}
        self.recording = self.dialog = None
        self.busy = False
        self.capture_fields = None

    async def prepare_dialog(self, client):
        old = self.dialog
        if old and not old.is_deleted and old.client is client and old.value:
            old.open()
            return False
        if self.busy or (self.recording and self.recording.busy):
            raise TaskError('CONTEXT_SESSION_BUSY', '采集操作尚未完成，请稍后重新打开')
        if self.capture_fields:
            self.capture_fields()
        await self.hide()
        # Old hide events must not overwrite controls from the new client.
        self.dialog = None
        if old and not old.is_deleted:
            old.delete()
        return True

    def bind(self, invoke, *, source_page, source_session_id=None):
        if self.recording is None:
            self.recording = RecordingDraft(self.draft, invoke, source_page=source_page,
                                            source_session_id=source_session_id)
        else:
            self.recording.invoke = invoke

    async def hide(self):
        if self.recording and self.recording.pending and not self.recording.busy and self.recording.state == 'RECORDING':
            await self.recording.set_paused(True)

    def forget(self):
        self.cache.pop(self.key, None)


class RecordingControls:
    """One control bar and command guard for planning and step collection."""
    def __init__(self, workspace, dialog, start_options, lock_inputs, changed):
        from nicegui import ui
        self.workspace, self.dialog = workspace, dialog
        self.start_options, self.lock_inputs, self.changed = start_options, lock_inputs, changed
        with ui.column().classes('tw-context-recording w-full gap-2') as self.area:
            self.status = ui.label().classes('text-sm text-gray-600')
            with ui.row().classes('gap-2 items-center'):
                self.start = ui.button('开始录制', icon='fiber_manual_record', on_click=self.begin).props('outline')
                self.pause = ui.button('暂停录制', icon='pause', on_click=self.toggle_pause).props('flat')
                self.stop = ui.button('停止并暂存', icon='stop', on_click=lambda:self.run(workspace.recording.stage)).props('outline')
                self.discard = ui.button('丢弃录制', icon='delete_outline', on_click=self.confirm_discard).props('flat color=negative')
        self.supported = False
        self.sync()

    def sync(self, supported=None):
        if supported is not None:
            self.supported = supported
        state = self.workspace.recording
        self.area.set_visibility(self.supported or state.pending)
        self.status.text = ('已保存，等待确认；请重试确认保存' if state.committed else
            {'RECORDING':'正在录制人工操作；关闭弹窗会暂停，草稿仍保留',
             'PAUSED':'录制已暂停，可继续或停止并暂存',
             'STOPPED':'录制已停止，暂存后确认保存'}.get(state.state, '录制人工操作；快照采集仍可使用'))
        self.start.set_visibility(not state.pending)
        self.pause.set_visibility(state.pending and state.state in {'RECORDING','PAUSED'})
        self.pause.text = '继续录制' if state.state == 'PAUSED' else '暂停录制'
        self.stop.set_visibility(state.pending and state.entry is None)
        self.discard.set_visibility(state.pending and not state.committed)
        for button in (self.start,self.pause,self.stop,self.discard):
            button.set_enabled(not self.workspace.busy and not state.busy)
        self.lock_inputs(state.pending or self.workspace.busy or state.committed)

    async def run(self, operation):
        from nicegui import ui
        if self.workspace.busy:
            return
        self.workspace.busy = True
        self.sync()
        try:
            result = await operation()
            return result
        except Exception as exc:
            ui.notify(f'操作失败，草稿和未确认录制仍保留：{exc}', type='negative')
        finally:
            self.workspace.busy = False
            if not self.dialog.value:
                try:
                    await self.workspace.hide()
                except Exception as exc:
                    ui.notify(f'暂停录制失败，仍保留原实例：{exc}', type='negative')
            if not self.dialog.is_deleted:
                self.changed()
                self.sync()

    async def begin(self):
        async def start():
            options, include_view = self.start_options()
            await self.workspace.recording.start(options, include_view=include_view)
        await self.run(start)

    async def toggle_pause(self):
        await self.run(lambda:self.workspace.recording.set_paused(self.workspace.recording.state != 'PAUSED'))

    async def confirm_discard(self):
        from nicegui import ui
        with ui.dialog() as confirm, ui.card():
            ui.label('丢弃此录制？不会撤销已发生的浏览器操作。')
            with ui.row():
                ui.button('保留', on_click=lambda:confirm.submit(False)).props('outline')
                ui.button('丢弃录制', on_click=lambda:confirm.submit(True)).props('color=negative')
        if await confirm:
            await self.run(self.workspace.recording.discard)


class RecordingDraft:
    def __init__(self, draft, invoke, *, source_page='planning', source_session_id=None):
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

    async def persist(self, save):
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
