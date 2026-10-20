"""Task sequence desktop route and draft state use the real application."""

import asyncio
import json
import time
import unittest

from nicegui.client import Client
from nicegui.page import page

from tests._core_fixture import CoreFixture
from taskweave.desktop.controller import DesktopController
from taskweave.desktop.workbench import Workbench
from taskweave.presentation.sequences import SequenceDraft


class SequenceDraftTests(unittest.TestCase):
    def test_order_and_repeated_task_identity(self):
        draft = SequenceDraft()
        draft.add("same-task")
        draft.add("same-task")
        first, second = [item["node_id"] for item in draft.nodes]
        self.assertNotEqual(first, second)
        draft.move(1, -1)
        self.assertEqual([item["node_id"] for item in draft.nodes], [second, first])
        draft.remove(0)
        self.assertEqual(draft.nodes[0]["node_id"], first)


class SequencesPageTests(CoreFixture):
    def _task(self, name):
        task = self.app.repo.create_task(name, {
            "type": "object", "properties": {"value": {"type": "integer"}},
            "required": ["value"],
        })["task_id"]
        step = self.step(task,
            source="async def run(ctx, inputs):\n    return ctx.result(data={'value': inputs['value']})\n",
            bindings={"value": {"ref": {"source": "task", "pointer": "/value"}}},
            input_schema={"type": "object", "properties": {"value": {"type": "integer"}}, "required": ["value"]},
        )
        self.confirm(step, {"value": 1})
        return task, step["step_id"]

    def test_edit_save_start_leave_and_return(self):
        first, first_step = self._task("First")
        second, second_step = self._task("Second")
        third, _ = self._task("Third")
        client = Client(page("/sequence-page-test"))
        try:
            async def scenario():
                with client:
                    workbench = Workbench(DesktopController(self.app))
                    await workbench.navigate("sequences")
                    self.assertIn("sequences", workbench.nav_buttons)
                    draft = workbench.sequences_page.draft
                    draft.name = "Three tasks"
                    for task_id in (first, second, third):
                        draft.add(task_id)
                    draft.nodes[0]["inputs"]["value"] = {"kind": "literal", "value": 4}
                    for node in draft.nodes[1:]:
                        node["inputs"]["value"] = {"kind": "output", "node_id": draft.nodes[0]["node_id"],
                            "step_id": first_step, "output": "data", "pointer": "/value"}
                    await workbench.sequences_page.save()
                    self.assertEqual(len(self.app.sequences.list()), 1)
                    draft.nodes[0]["inputs"]["value"]["value"] = 6
                    await workbench.sequences_page.start()
                    run_id = draft.selected_run_id
                    await workbench.navigate("home")
                    deadline = time.monotonic() + 15
                    while time.monotonic() < deadline:
                        run = self.app.sequences.run_get(run_id)
                        if run["status"] == "SUCCEEDED":
                            break
                        await asyncio.sleep(0.05)
                    self.assertEqual(run["status"], "SUCCEEDED", run)
                    self.assertEqual(self.app.runs.output(run["nodes"][1]["run_id"], second_step)["value"], 6)
                    await workbench.navigate("sequences")
                    self.assertEqual(workbench.sequences_page.draft.selected_run_id, run_id)
                    self.assertEqual([member["status"] for member in run["nodes"]], ["SUCCEEDED"] * 3)
                    await workbench.sequences_page.delete_definition()
                    self.assertEqual(workbench.sequences_page.draft.selected_run_id, run_id)
                    workbench.sequences_page.dispose()
            asyncio.run(scenario())
        finally:
            client.delete()
