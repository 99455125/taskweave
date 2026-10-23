"""Shared recording draft lifecycle, independent of modal presentation.

Browser/plugin commands never commit captures. The owning dialog explicitly
persists the whole context group, then confirms the returned recording cursor.
"""
from taskweave.core.validation import TaskError
from taskweave.presentation.context_collection import ContextCaptureDraft, CollectionSession, RecordingDraft


def collection_workspace(owner, key, captures):
    cache = getattr(owner, '_collection_workspaces', None)
    if cache is None:
        owner._collection_workspaces = cache = {}
    if key not in cache:
        cache[key] = CollectionWorkspace(cache, key, ContextCaptureDraft(captures))
    return cache[key]


class CollectionWorkspace:
    """Client-owned draft survives ESC/hidden dialogs without consuming evidence."""
    def __init__(self, cache, key, draft):
        self.cache, self.key = cache, key
        self.interaction = CollectionSession(draft)
        self.dialog = None
        self.capture_fields = None

    @property
    def draft(self): return self.interaction.draft

    @property
    def fields(self): return self.interaction.fields

    @property
    def recording(self): return self.interaction.recording

    @property
    def busy(self): return self.interaction.busy
    @busy.setter
    def busy(self, value): self.interaction.busy = value

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
        self.interaction.bind(invoke, source_page=source_page, source_session_id=source_session_id)

    async def hide(self):
        await self.interaction.hide()

    def forget(self):
        self.cache.pop(self.key, None)


class RecordingControls:
    """One control bar and command guard for planning and step collection."""
    def __init__(self, workspace, dialog, start_options, lock_inputs, changed):
        from nicegui import ui
        self.workspace, self.dialog = workspace, dialog
        self.start_options, self.lock_inputs, self.changed = start_options, lock_inputs, changed
        with ui.column().classes('tw-context-recording gap-2') as self.area:
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
            {'RECORDING':'正在录制',
             'PAUSED':'录制已暂停',
             'STOPPED':'录制已停止'}.get(state.state, ''))
        self.status.set_visibility(bool(self.status.text))
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
        if not self.workspace.interaction.begin_operation():
            return
        self.sync()
        try:
            result = await operation()
            return result
        except Exception as exc:
            ui.notify(f'操作失败，草稿和未确认录制仍保留：{exc}', type='negative')
        finally:
            self.workspace.interaction.finish_operation()
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
        with ui.dialog() as confirm, ui.card().classes('tw-confirm-dialog'):
            ui.label('丢弃录制？').classes('tw-confirm-title')
            ui.label('录制内容将被丢弃，已发生的浏览器操作会保留。').classes('tw-confirm-description')
            with ui.row().classes('tw-confirm-actions'):
                ui.button('保留录制', on_click=lambda:confirm.submit(False)).props('outline').classes('tw-confirm-cancel')
                ui.button('丢弃录制', on_click=lambda:confirm.submit(True)).props('outline color=negative').classes('tw-confirm-danger')
        if await confirm:
            await self.run(self.workspace.recording.discard)
