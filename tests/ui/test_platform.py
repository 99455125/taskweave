"""Desktop platform adapters keep side effects explicit and path confined."""
import asyncio
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class PlatformTests(unittest.TestCase):
    def adapter(self):
        self.assertIsNotNone(importlib.util.find_spec('taskweave.desktop.platform'))
        from taskweave.desktop import platform
        return platform

    def test_open_path_rejects_outside_workspace_before_launch(self):
        platform = self.adapter()
        from taskweave.core.validation import TaskError
        with tempfile.TemporaryDirectory() as root:
            home = Path(root) / 'workspace'; home.mkdir()
            outside = Path(root) / 'outside'; outside.write_text('private')
            with patch.object(platform.subprocess, 'Popen') as launch:
                with self.assertRaises(TaskError) as caught:
                    asyncio.run(platform.open_path(outside, workspace_home=home))
                self.assertEqual(caught.exception.code, 'LOCAL_PATH_INVALID')
                launch.assert_not_called()

    def test_native_clipboard_failure_keeps_public_error(self):
        platform = self.adapter()
        from taskweave.core.validation import TaskError
        with patch.object(platform.sys, 'platform', 'darwin'), patch.object(platform.subprocess, 'run', side_effect=OSError()):
            with self.assertRaises(TaskError) as caught:
                asyncio.run(platform.copy_text('text', native=True))
        self.assertEqual(caught.exception.code, 'CLIPBOARD_FAILED')


class HomeBoundaryTests(unittest.TestCase):
    def test_home_stops_after_navigation_before_query_response(self):
        self.assertIsNotNone(importlib.util.find_spec('taskweave.desktop.pages.home'))
        from taskweave.desktop.pages.home import HomePage
        from types import SimpleNamespace

        async def scenario():
            identity = [1, 'home']
            calls = []
            async def query(operation, **params):
                calls.append(operation)
                identity[:] = [2, 'tasks']
                return []
            page = HomePage(
                SimpleNamespace(call=query), actions=None,
                button=lambda *args, **kwargs: self.fail('stale render'),
                page_identity=lambda: tuple(identity), status_labels={},
            )
            await page.render()
            self.assertEqual(calls, ['task.list'])
        asyncio.run(scenario())
