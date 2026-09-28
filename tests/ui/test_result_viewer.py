"""ResultViewer keeps table validation and display wiring isolated."""

import asyncio
import unittest
from unittest.mock import MagicMock, patch

from taskweave.desktop.components.result_viewer import ResultViewer


class ResultViewerTests(unittest.TestCase):
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
