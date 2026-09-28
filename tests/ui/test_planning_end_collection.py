"""Planning assistant end-instance action stays scoped to its captured plan."""
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from taskweave.desktop.planning import PlanningPage
from taskweave.desktop.state import PlanningPageState


class PlanningEndCollectionTests(unittest.TestCase):
    def test_calls_end_for_current_plan_and_ignores_stale_identity(self):
        async def scenario():
            controller = AsyncMock()
            page = PlanningPage(controller, PlanningPageState(plan_id="p1"), MagicMock(), AsyncMock(), AsyncMock(), AsyncMock())
            identity = page._planning_identity()

            result = await page.end_collection_instance("p1", identity)
            self.assertTrue(result)
            controller.call.assert_awaited_once_with("instance.end", instance_type="plan", owner_id="p1")

            controller.call.reset_mock()
            page.state.plan_id = "p2"
            result = await page.end_collection_instance("p1", identity)
            self.assertFalse(result)
            controller.call.assert_not_awaited()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
