"""Desktop exports persist UTF-8 data and report clipboard failures."""
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from taskweave.desktop.controller import DesktopController
from taskweave.core.validation import TaskError


class ExportIOTests(unittest.IsolatedAsyncioTestCase):
    async def test_export_saves_unique_json_and_opens_directory(self):
        with tempfile.TemporaryDirectory() as home:
            controller = DesktopController(SimpleNamespace(home=Path(home)))
            controller.open_path = AsyncMock()
            text = json.dumps({'任务': '中文', 'steps': ['a\nb']}, ensure_ascii=False)
            first = await controller.save_task_export(text)
            second = await controller.save_task_export(text)
            self.assertNotEqual(first, second)
            self.assertEqual(json.loads(first.read_text()), json.loads(text))
            self.assertEqual(second.read_text(), text)
            controller.open_path.assert_awaited_with(Path(home) / 'exports')

    async def test_native_clipboard_utf8_and_failure(self):
        controller = DesktopController(None)
        controller.native = True
        with patch('taskweave.desktop.controller.sys.platform', 'darwin'), patch('taskweave.desktop.controller.subprocess.run') as run:
            await controller.copy_text('中文 JSON\n{}')
            self.assertEqual(run.call_args.kwargs['input'].decode('utf-8'), '中文 JSON\n{}')
            run.side_effect = subprocess.CalledProcessError(1, 'pbcopy')
            with self.assertRaises(TaskError) as error:
                await controller.copy_text('{}')
            self.assertEqual(error.exception.code, 'CLIPBOARD_FAILED')

    async def test_browser_waits_for_copy_and_rejects_failure(self):
        controller = DesktopController(None)
        with patch('nicegui.ui.run_javascript', new_callable=AsyncMock) as javascript:
            javascript.return_value = True
            await controller.copy_text('中文 JSON')
            javascript.assert_awaited_once()
            javascript.return_value = False
            with self.assertRaises(TaskError):
                await controller.copy_text('JSON')
