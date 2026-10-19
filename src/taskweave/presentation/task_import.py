"""Task import draft, parsing limits and ownership of asynchronous file reads."""
import json
from typing import Awaitable, Callable
from taskweave.core.validation import TaskError

TASK_IMPORT_LIMIT_BYTES = 32 * 1024 * 1024


class TaskImportSession:
    def __init__(self, import_package: Callable[[dict], Awaitable[dict]]):
        self.import_package = import_package
        self.mode = 'file'
        self.source = ''
        self.package = None
        self.file_ready = False
        self.generation = 0
        self.active = True
        self.submitting = False

    def clear_file(self):
        self.generation += 1
        self.file_ready = False
        self.package = None

    def close(self):
        self.active = False
        self.clear_file()

    def begin_file(self, size: int):
        self.clear_file()
        if size > TASK_IMPORT_LIMIT_BYTES:
            raise ValueError('任务 JSON 文件超过 32 MiB')
        return self.generation

    def accept_file(self, token: int, content: bytes):
        if not self.active or token != self.generation:
            return False
        if len(content) > TASK_IMPORT_LIMIT_BYTES:
            raise ValueError('任务 JSON 文件超过 32 MiB')
        package = json.loads(content.decode('utf-8-sig'))
        self.package, self.file_ready = package, True
        return True

    def selected_package(self):
        if self.mode == 'file':
            if not self.file_ready:
                raise TaskError('TASK_PACKAGE_INVALID', '请先选择有效的任务 JSON 文件')
            return self.package
        if len(self.source or '') > 2 * 1024 * 1024:
            raise TaskError('TASK_PACKAGE_INVALID', '大任务包请选择 JSON 文件导入')
        try:
            return json.loads(self.source or '')
        except ValueError as exc:
            raise TaskError('TASK_PACKAGE_INVALID', '请粘贴有效 JSON') from exc

    async def submit(self):
        if not self.active or self.submitting:
            return None
        self.submitting = True
        try:
            saved = await self.import_package(self.selected_package())
            # Closing the dialog never cancels an accepted write, but its result
            # must not repaint or notify a replacement view.
            return saved if self.active else None
        finally:
            self.submitting = False
