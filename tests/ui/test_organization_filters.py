"""Desktop organization filters compose search, favorite and category values."""

import unittest
from unittest.mock import AsyncMock, MagicMock

from taskweave.desktop.components.organization import CategoryManager
from taskweave.desktop.pages.tasks import filter_tasks
from taskweave.desktop.planning import filter_plans


class OrganizationFilterTests(unittest.TestCase):
    def test_category_manager_uses_local_refresh_when_provided(self):
        async def scenario():
            repaint = AsyncMock()
            refresh = AsyncMock()
            manager = CategoryManager(AsyncMock(), MagicMock(), repaint, after_change=refresh)
            dialog = MagicMock()

            await manager._refresh_after_change(dialog)

            refresh.assert_awaited_once_with()
            repaint.assert_not_awaited()
            dialog.close.assert_called_once_with()

        import asyncio
        asyncio.run(scenario())

    def test_task_and_plan_filters_combine_search_favorites_and_category(self):
        rows = [
            {"task_id": "a", "plan_id": "a", "name": "合同", "description": "登录", "is_favorite": 1, "category_id": "work"},
            {"task_id": "b", "plan_id": "b", "name": "合同备份", "description": "登录", "is_favorite": 0, "category_id": "work"},
        ]
        self.assertEqual(
            [row["task_id"] for row in filter_tasks(rows, "合同", favorite=True, category_id="work")],
            ["a"],
        )
        self.assertEqual(
            [row["plan_id"] for row in filter_plans(rows, "合同", favorite=True, category_id="work")],
            ["a"],
        )
