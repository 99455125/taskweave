"""Automatic evidence follows touched pages and preserves declared result metadata."""
import importlib.util
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from taskweave.core.ports import StepResult, ResultRequest


@unittest.skipUnless(importlib.util.find_spec('taskweave_playwright'), 'Browser extra is unavailable')
class PlaywrightResultArtifactsTests(unittest.IsolatedAsyncioTestCase):
    def context(self, pages):
        async def allocate(name):
            return SimpleNamespace(local_path='/staging/' + name, token=name)
        return SimpleNamespace(_playwright_result_pages=pages, allocate_file=allocate,
                               log=Mock(), emit=Mock())

    async def test_names_and_titles_do_not_overwrite_explicit_results(self):
        from taskweave_playwright.results import result_artifacts
        page = SimpleNamespace(screenshot=AsyncMock())
        result = StepResult(data=[1, 2], outputs=[ResultRequest('playwright.image', 'page_capture_1', {})],
                            views=[{'title': '步骤结束页面截图 · operator · 1'}])
        artifacts = await result_artifacts(self.context([('operator', page)]), result)
        self.assertIsNone(artifacts.data)
        self.assertEqual(result.data, [1, 2])
        self.assertNotEqual(artifacts.outputs[0].name, 'page_capture_1')
        self.assertNotEqual(artifacts.views[0]['title'], result.views[0]['title'])
        self.assertEqual(artifacts.views[0]['output'], artifacts.outputs[0].name)

    async def test_failure_captures_touched_popup_and_returns_views(self):
        from taskweave_playwright.results import failure_results
        popup = SimpleNamespace(screenshot=AsyncMock(), is_closed=lambda: False)
        ctx = self.context([('operator', popup)])
        with patch('taskweave_playwright.results.snapshot', AsyncMock(return_value={'title': 'Popup'})):
            artifacts = await failure_results(ctx, None)
        popup.screenshot.assert_awaited_once()
        self.assertEqual(artifacts.views[0]['renderer'], 'playwright.screenshot')
        self.assertIn('失败页面截图', artifacts.views[0]['title'])

    async def test_closed_or_unavailable_page_reports_warning_and_keeps_business_result(self):
        from taskweave_playwright.results import result_artifacts
        page = SimpleNamespace(screenshot=AsyncMock(side_effect=RuntimeError('page closed')))
        ctx = self.context([('operator', page)])
        artifacts = await result_artifacts(ctx, StepResult(data=7))
        self.assertEqual(artifacts.outputs, [])
        self.assertEqual(artifacts.views, [])
        ctx.emit.assert_called_once_with('ScreenshotCaptureFailed', {'role': 'operator', 'error_code': 'RuntimeError'})
        self.assertEqual(ctx.log.call_args.args[0], 'WARNING')

    async def test_no_page_actions_do_not_capture_a_retained_page(self):
        from taskweave_playwright.results import result_artifacts
        artifacts = await result_artifacts(self.context([]), StepResult(data={}))
        self.assertEqual(artifacts.views, [])
