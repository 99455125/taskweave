"""Opt-in incremental log display shared by execution and step debugging."""
import asyncio
import json
from nicegui import ui
from taskweave.desktop.display import readable_metadata


def render_log_text(controller, button, text):
    """Retain the full document on the server; render one plain-text page."""
    page_size, index = 24000, 0
    pages = max(1, (len(text) + page_size - 1) // page_size)
    output = ui.textarea('日志内容', value=text[:page_size]).props('readonly rows=12').classes('w-full font-mono')
    status = ui.label().classes('text-xs text-gray-500')

    def show(offset=0):
        nonlocal index
        index = max(0, min(pages - 1, index + offset))
        output.value = text[index * page_size:(index + 1) * page_size]
        status.text = f'第 {index + 1} / {pages} 页 · 共 {len(text)} 字符'
        previous.set_enabled(index > 0)
        following.set_enabled(index + 1 < pages)

    async def copy():
        await controller.copy_text(text)
        ui.notify('完整日志已复制')

    with ui.row().classes('w-full items-center gap-2 flex-wrap'):
        previous = ui.button('上一页', on_click=lambda: show(-1)).props('flat')
        following = ui.button('下一页', on_click=lambda: show(1)).props('flat')
        button('复制完整日志', copy, flat=True)
    show()


class LiveRunLogs:
    def __init__(self, controller, run_id, current, *, allowed=lambda: True, names=None, own_timer=None):
        self.controller, self.run_id = controller, run_id
        self.current, self.allowed, self.names = current, allowed, names or {}
        self.cursor, self.enabled, self.loading = 0, False, False
        self.text = ''
        self.button = ui.button('实时日志', on_click=self.toggle).props('flat')
        self.area = ui.column().classes('w-full min-w-0')
        with self.area:
            ui.label('仅增量显示最近日志；完整内容可用查看 / 刷新日志及复制功能。').classes('text-xs text-gray-500')
            self.output = ui.textarea('实时日志').props('readonly rows=10').classes('w-full font-mono')
            self.status = ui.label().classes('text-xs text-gray-500')
        self.area.set_visibility(False)
        self.timer = ui.timer(1, self.poll, active=False)
        if own_timer:
            own_timer(self.timer)

    def valid(self):
        return not self.area.is_deleted and self.current()

    async def toggle(self):
        if not self.valid():
            return
        self.enabled = not self.enabled
        self.area.set_visibility(self.enabled)
        self.button.text = '收起实时日志' if self.enabled else '实时日志'
        if self.enabled:
            self.timer.activate()
            await self.poll()
        else:
            self.timer.deactivate()

    async def poll(self):
        if not self.valid():
            self.timer.deactivate()
            return
        if not self.enabled or not self.allowed() or self.loading:
            return
        self.loading = True
        try:
            result = await self.controller.call('run.events.page', run_id=self.run_id, after=self.cursor, limit=100)
            def format_events():
                chunks = []
                for event in result['events']:
                    clean = {key: value for key, value in event.items() if key != 'sequence'}
                    text = json.dumps(readable_metadata(clean, self.names), ensure_ascii=False, indent=2, default=str)
                    chunks.append(text[:12000] + ('\n[单条摘要已截短，请查看完整日志]' if len(text) > 12000 or event.get('payload_truncated') else ''))
                return '\n'.join(chunks)
            addition = await asyncio.to_thread(format_events)
            if not self.valid() or not self.enabled:
                return
            if result.get('reset'):
                self.text = ''
            self.cursor = result['cursor']
            if addition:
                updated = (self.text + '\n' + addition).strip()
                self.text = updated[-24000:]
                if self.output.value != self.text:
                    self.output.value = self.text
            status = '正在读取后续日志…' if result['has_more'] else '已更新至最新日志'
            if not result['has_more'] and result['status'] != 'RUNNING':
                self.timer.deactivate()
                # The panel remains open even when following has stopped.
                # Keep the toggle tied to visibility so one click can close it.
                status += ' · 运行已停止；重新打开可更新'
            if self.status.text != status:
                self.status.text = status
        except Exception as exc:
            if self.valid():
                self.timer.deactivate()
                self.status.text = f"日志读取失败：{getattr(exc, 'code', type(exc).__name__)}；关闭后重新打开可重试"
        finally:
            self.loading = False

    def dispose(self):
        self.enabled = False
        if not self.timer.is_deleted:
            self.timer.delete()
