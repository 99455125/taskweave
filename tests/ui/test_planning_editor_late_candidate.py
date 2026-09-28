"""A stale planning editor render must not replace the current editor callbacks."""
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from nicegui import ui
from nicegui.client import Client
from nicegui.page import page as nice_page

from taskweave.desktop.planning import PlanningPage
from taskweave.desktop.state import PlanningPageState


class PlanningEditorLateCandidateTests(unittest.TestCase):
    def test_environment_selector_lives_before_plugins_in_materials_and_saves_same_field(self):
        async def scenario(root):
            state = PlanningPageState(plan_id="plan", generation=4)
            calls = []

            class Controller:
                async def call(self, operation, **kwargs):
                    calls.append((operation, kwargs))
                    if operation == "capabilities": return {"manifests": {}}
                    if operation == "environment.list": return [{"environment_id": "env-1", "name": "采集验收环境"}]
                    if operation == "plan.generation.list": return []
                    if operation == "plan.update": return {"plan_id": "plan", "revision": 2, **kwargs}
                    raise AssertionError(operation)

                def privacy_settings(self): return {"redact_on_display": False}
                def plugin_context_requests(self): return {}

            controller = Controller()
            button_labels = []
            def button(title, callback, **kwargs):
                button_labels.append(title)
                return ui.button(title, on_click=callback)
            page = PlanningPage(controller, state, button,
                                AsyncMock(), AsyncMock(), AsyncMock(),
                                page_identity=lambda: ("planning", 9))
            plan = {"plan_id": "plan", "name": "规划", "plan_description": "", "plan_notes": "",
                    "plugin_ids": [], "contexts": [], "environment_id": None, "revision": 1}
            selects = {}
            original_select = ui.select
            def track_select(*args, **kwargs):
                control = original_select(*args, **kwargs)
                selects[kwargs.get("label")] = control
                return control

            from unittest.mock import patch
            with patch("taskweave.desktop.planning.ui.select", side_effect=track_select):
                with root:
                    await page.editor(plan)

            def ancestor_with_class(element, css_class):
                parent = element
                while parent is not None:
                    slot = getattr(parent, "parent_slot", None)
                    parent = slot._parent() if slot is not None else None
                    if parent is not None and css_class in getattr(parent, "_classes", []):
                        return parent
                return None

            environment = selects["采集环境（可选）"]
            plugins = selects["所用插件"]
            materials = ancestor_with_class(environment, "tw-plan-materials")
            self.assertIsNotNone(materials)
            self.assertIs(materials, ancestor_with_class(plugins, "tw-plan-materials"))
            self.assertLess(materials.default_slot.children.index(environment), materials.default_slot.children.index(plugins))
            self.assertNotIn("查看生成记录", button_labels)
            environment.value = "env-1"
            await state.save_callback()
            update = next(params for operation, params in calls if operation == "plan.update")
            self.assertEqual(update["environment_id"], "env-1")
            root.clear()

        client = Client(nice_page("/planning-environment-selector-placement"))
        try:
            with client:
                with ui.column() as root:
                    asyncio.run(scenario(root))
        finally:
            client.delete()

    def test_late_candidate_detail_cannot_replace_completed_editor_callbacks_or_draft(self):
        async def scenario(root):
            entered_a_detail, release_a_detail = asyncio.Event(), asyncio.Event()
            calls = []
            state = PlanningPageState(plan_id="plan-a", generation=1)
            page_generation = [1]

            class Controller:
                async def call(self, operation, **kwargs):
                    calls.append((operation, kwargs))
                    if operation == "capabilities":
                        return {"manifests": {}}
                    if operation == "environment.list":
                        return []
                    if operation == "plan.generation.list":
                        if kwargs["plan_id"] == "plan-a":
                            return [{"generation_id": "generation-a"}]
                        return []
                    if operation == "plan.generation.get":
                        entered_a_detail.set()
                        await release_a_detail.wait()
                        return {"generation_id": "generation-a", "status": "READY", "candidate": {}}
                    if operation == "plan.update":
                        return {"plan_id": kwargs["plan_id"], "revision": 2, **kwargs}
                    raise AssertionError(f"Unexpected controller call: {operation}")

                def privacy_settings(self):
                    return {"redact_on_display": False}

                def plugin_context_requests(self):
                    return {}

            controller = Controller()
            inputs = []

            def button(title, callback, **kwargs):
                primary = kwargs.pop("primary", False)
                flat = kwargs.pop("flat", False)
                element = ui.button(title, on_click=callback, **kwargs)
                if primary:
                    element.props("unelevated color=primary")
                elif flat:
                    element.props("flat")
                return element

            page = PlanningPage(controller, state, button, AsyncMock(), AsyncMock(), AsyncMock(),
                                page_identity=lambda: ("planning", page_generation[0]))
            plans = {
                "plan-a": {"plan_id": "plan-a", "name": "A", "plan_description": "", "plan_notes": "", "plugin_ids": [], "contexts": [], "revision": 1},
                "plan-b": {"plan_id": "plan-b", "name": "B", "plan_description": "", "plan_notes": "", "plugin_ids": [], "contexts": [], "revision": 1},
            }
            original_input = ui.input
            def track_input(*args, **kwargs):
                element = original_input(*args, **kwargs)
                inputs.append((args[0] if args else "", element))
                return element

            from unittest.mock import patch
            with patch("taskweave.desktop.planning.ui.input", side_effect=track_input):
                async def render_plan_a():
                    with root:
                        await page.editor(plans["plan-a"])
                render_a = asyncio.create_task(render_plan_a())
                await asyncio.wait_for(entered_a_detail.wait(), timeout=3)

                root.clear()
                state.plan_id, state.generation = "plan-b", 2
                page_generation[0] = 2
                with root:
                    await page.editor(plans["plan-b"])

                candidate_callback_b = page._refresh_candidate_summary
                history_callback_b = page._refresh_generation_history
                save_callback_b = state.save_callback
                b_name = next(element for label, element in reversed(inputs) if label == "规划名称")
                b_name.value = "B draft"

                release_a_detail.set()
                await asyncio.wait_for(render_a, timeout=3)

                self.assertIs(page._refresh_candidate_summary, candidate_callback_b)
                self.assertIs(page._refresh_generation_history, history_callback_b)
                self.assertIs(state.save_callback, save_callback_b)
                self.assertFalse(b_name.is_deleted)
                self.assertEqual(b_name.value, "B draft")
                self.assertTrue(await page._refresh_candidate_summary())
                self.assertTrue(await page._refresh_generation_history())
                await state.save_callback()
                update_calls = [(op, args) for op, args in calls if op == "plan.update"]
                self.assertEqual(len(update_calls), 1)
                self.assertEqual(update_calls[0][1]["plan_id"], "plan-b")
                self.assertEqual(update_calls[0][1]["name"], "B draft")
            root.clear()

        client = Client(nice_page("/planning-editor-late-candidate-detail"))
        try:
            with client:
                with ui.column() as root:
                    asyncio.run(scenario(root))
        finally:
            client.delete()


if __name__ == "__main__":
    unittest.main()
