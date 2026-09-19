"""Bounded server log history and a separate native live-log viewer."""

from collections import deque
import logging
from pathlib import Path
import threading

from taskweave.infrastructure.privacy import redact


class ServerLogs(logging.Handler):
    def __init__(self, home):
        super().__init__()
        self.rows = deque(maxlen=2000)
        self.sequence = 0
        self.guard = threading.Lock()
        self.secrets = set()
        self.path = Path(home) / 'logs' / 'server.log'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))

    def protect(self, value):
        if value:
            with self.guard:
                self.secrets.add(value)

    def emit(self, record):
        try:
            # Do not copy exception bodies, request payloads or credentials into logs.
            clean = logging.makeLogRecord(record.__dict__.copy())
            clean.exc_info = clean.exc_text = None
            text = self.format(clean)
            if record.exc_info:
                text += ' [' + record.exc_info[0].__name__ + ']'
            with self.guard:
                for secret in self.secrets:
                    text = text.replace(secret, '[REDACTED]')
                text = redact(text)
                self.sequence += 1
                self.rows.append((self.sequence, record.levelno, text))
                if self.path.exists() and self.path.stat().st_size > 5 * 1024 * 1024:
                    self.path.replace(self.path.with_suffix('.log.1'))
                with self.path.open('a', encoding='utf-8') as stream:
                    stream.write(text + '\n')
        except Exception:
            self.handleError(record)

    def after(self, sequence=0, minimum=logging.INFO):
        with self.guard:
            return [(seq, text) for seq, level, text in self.rows if seq > sequence and level >= minimum], self.sequence


def log_window(url):
    import webview
    webview.create_window('TaskWeave · 服务实时日志', url, width=1050, height=650)
    webview.start()


def render_logs(logs, open_path=None):
    from nicegui import ui
    ui.add_css('.nicegui-log, .nicegui-log > div {user-select: text !important; -webkit-user-select: text !important; white-space: pre-wrap !important; overflow-wrap: anywhere; word-break: break-word;} .nicegui-log {overflow-x: hidden !important; min-width: 0;}')
    ui.colors(primary='#345adb')
    ui.add_css('.q-btn {box-shadow:none; border-radius:6px;} .q-btn.bg-primary {background:white !important; color:#345adb !important; border:1px solid #cbd5e1;}')
    ui.label('服务实时日志').classes('text-xl font-medium')
    ui.label('本地服务、AI 请求和后台异常；关闭此窗口不会结束任务。')
    level = ui.select({'20': 'INFO 及以上', '30': 'WARNING 及以上', '40': 'ERROR'}, value='20', label='级别')
    paused = ui.switch('暂停显示')
    output = ui.log(max_lines=2000).classes('w-full h-[70vh] font-mono')
    cursor = 0

    def refresh():
        nonlocal cursor
        if paused.value:
            return
        rows, cursor = logs.after(cursor, int(level.value))
        for _, text in rows:
            output.push(text)

    def reset():
        nonlocal cursor
        cursor = 0
        output.clear()
        refresh()

    level.on_value_change(lambda _: reset())
    def clear():
        output.clear()

    with ui.row():
        ui.button('清空显示', on_click=clear)
        if open_path:
            ui.button('打开日志目录', on_click=lambda: open_path(logs.path.parent))
    ui.label('日志自动保存为 server.log；可暂停显示后选中文字复制。')
    refresh()
    ui.timer(0.5, refresh)
