"""ResultViewer keeps table validation and display wiring isolated."""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace

from taskweave.desktop.components.result_viewer import ResultViewer


class ResultViewerTests(unittest.TestCase):
    def test_output_backed_image_view_uses_saved_file_without_reading_business_pointer(self):
        async def scenario():
            async def call(operation, **params):
                if operation == 'run.get':
                    return {'results': [{'attempt_id': 'attempt', 'result_id': 'data', 'locator': 'data'},
                                        {'attempt_id': 'attempt', 'result_id': 'image', 'locator': 'capture'}]}
                if params['result_id'] == 'data':
                    return {'name': 'data', 'data': [1, 2], 'views': [
                        {'title': '步骤截图', 'renderer': 'playwright.screenshot', 'output': 'capture'}]}
                return {'name': 'capture', 'path': '/saved/capture.png', 'media_type': 'image/png'}
            viewer = ResultViewer(SimpleNamespace(call=call, result_renderers={
                'playwright.screenshot': {'type': 'image'}}), MagicMock())
            viewer.render_result_view = AsyncMock()
            with patch('taskweave.desktop.components.result_viewer.ui', MagicMock()):
                await viewer.step_result_dialog({'run_id': 'run'}, {'name': 'Step'}, 'attempt')
            args = viewer.render_result_view.await_args.args
            self.assertEqual(args[:2], ('image', {'output': 'capture'}))
            self.assertEqual(args[2]['capture']['path'], '/saved/capture.png')
        asyncio.run(scenario())

    def test_table_renderer_builds_columns_and_rows(self):
        async def scenario():
            ui = MagicMock()
            viewer = ResultViewer(MagicMock(), MagicMock())
            payload = {"columns": [{"key": "name", "label": "名称"}], "rows": [{"name": "alpha"}]}
            with patch("taskweave.desktop.components.result_viewer.ui", ui):
                await viewer.render_result_view("table", payload, {})
            kwargs = ui.table.call_args.kwargs
            self.assertEqual(kwargs["columns"][0]["label"], "名称")
            self.assertEqual(kwargs["rows"][0]["name"], "alpha")

        asyncio.run(scenario())

    def test_invalid_table_shape_fails_before_render(self):
        async def scenario():
            ui = MagicMock()
            viewer = ResultViewer(MagicMock(), MagicMock())
            with patch("taskweave.desktop.components.result_viewer.ui", ui):
                with self.assertRaisesRegex(ValueError, "columns 和 rows"):
                    await viewer.render_result_view("table", {"rows": "bad"}, {})
            ui.table.assert_not_called()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
