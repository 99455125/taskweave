"""StepList owns step-row actions and preserves local list interactions."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from taskweave.core.validation import TaskError
from taskweave.desktop.components.step_list import StepList


class StepListTests(unittest.TestCase):
    def test_confirm_all_surfaces_save_failure_and_does_not_validate_or_confirm(self):
        async def scenario():
            controller = SimpleNamespace(call=AsyncMock())
            save = AsyncMock(side_effect=TaskError("EDIT_CONFLICT", "保存版本冲突"))
            page = StepList(controller, MagicMock(), lambda: "task", lambda: "step", lambda: ("task", "step", 1),
                            save, AsyncMock(), MagicMock(), AsyncMock(), AsyncMock(), AsyncMock())
            ui = MagicMock()
            with patch("taskweave.desktop.components.step_list.ui", ui):
                await page.render([{"step_id": "step", "name": "步骤", "validation_state": "DRAFT"}],
                                  {"actions": [], "tools": [], "result_handlers": [], "resource_providers": []}, MagicMock(), MagicMock())
                with self.assertRaisesRegex(TaskError, "保存版本冲突"):
                    await page.actions["confirm_all"]()
            controller.call.assert_not_awaited()
            ui.notify.assert_called_once()
            self.assertIn("草稿已保留", ui.notify.call_args.args[0])
            self.assertIn("保存版本冲突", ui.notify.call_args.args[0])
        asyncio.run(scenario())

    def test_confirm_all_stale_save_failure_does_not_report_into_new_step(self):
        async def scenario():
            identity = ["task-old", "step-old", 1, 5]
            save_started, fail_save = asyncio.Event(), asyncio.Event()
            async def save():
                save_started.set()
                await fail_save.wait()
                raise TaskError("EDIT_CONFLICT", "旧步骤保存失败")
            controller = SimpleNamespace(call=AsyncMock())
            paint = AsyncMock()
            page = StepList(controller, MagicMock(), lambda: identity[0], lambda: identity[1],
                            lambda: tuple(identity), save, AsyncMock(), MagicMock(), paint,
                            AsyncMock(), AsyncMock())
            ui = MagicMock()
            with patch("taskweave.desktop.components.step_list.ui", ui):
                await page.render([{"step_id":"step-old","name":"旧步骤","validation_state":"DRAFT"}],
                                  {"actions":[],"tools":[],"result_handlers":[],"resource_providers":[]}, MagicMock(), MagicMock())
                pending = asyncio.create_task(page.actions["confirm_all"]())
                await save_started.wait()
                identity[:] = ["task-new", "step-new", 2, 6]
                fail_save.set()
                await pending
            ui.notify.assert_not_called()
            controller.call.assert_not_awaited()
            paint.assert_not_awaited()

        asyncio.run(scenario())

    def test_confirm_all_does_not_suppress_unexpected_validation_exception(self):
        async def scenario():
            step = {"step_id": "step", "name": "步骤", "content_hash": "hash", "validation_state": "DRAFT"}
            async def call(operation, **params):
                if operation == "step.list": return [step]
                if operation == "step.validate": raise RuntimeError("unexpected validator crash")
                raise AssertionError(operation)
            controller = SimpleNamespace(call=AsyncMock(side_effect=call))
            page = StepList(controller, MagicMock(), lambda: "task", lambda: "step", lambda: ("task", "step", 1),
                            AsyncMock(), AsyncMock(), MagicMock(), AsyncMock(), AsyncMock(), AsyncMock())
            ui = MagicMock()
            with patch("taskweave.desktop.components.step_list.ui", ui):
                await page.render([step], {"actions": [], "tools": [], "result_handlers": [], "resource_providers": []}, MagicMock(), MagicMock())
                with self.assertRaisesRegex(RuntimeError, "unexpected validator crash"):
                    await page.actions["confirm_all"]()
            self.assertFalse(any(call.args[0] == "step.confirm.manual" for call in controller.call.await_args_list))

        asyncio.run(scenario())

    def test_confirm_all_reports_returned_and_raised_validation_failures_without_confirming(self):
        async def scenario():
            for invalid_kind in ("returned", "raised"):
                with self.subTest(invalid_kind=invalid_kind):
                    steps = [
                        {"step_id": "valid", "name": "有效步骤", "content_hash": "hash-valid", "validation_state": "DRAFT", "capabilities": []},
                        {"step_id": "invalid", "name": "无效步骤", "content_hash": "hash-invalid", "validation_state": "DRAFT", "capabilities": []},
                        {"step_id": "invalid-2", "name": "第二个无效步骤", "content_hash": "hash-invalid-2", "validation_state": "DRAFT", "capabilities": []},
                    ]
                    calls = []
                    async def call(operation, **params):
                        calls.append((operation, params))
                        if operation == "step.list": return [dict(step) for step in steps]
                        if params["step_id"] == "valid": return {"valid": True, "diagnostics": []}
                        if invalid_kind == "returned":
                            return {"valid": False, "diagnostics": [{"code": "CONTENT_INVALID", "severity": "error", "message": "步骤代码语法错误"}]}
                        raise TaskError("CONTENT_INVALID", "步骤代码必须是有效 Python")

                    controller = SimpleNamespace(call=AsyncMock(side_effect=call))
                    save = AsyncMock(return_value=steps[0])
                    identity = ["task", "valid", 1, 7]
                    selected = MagicMock(side_effect=lambda step_id: identity.__setitem__(1, step_id))
                    async def paint(): identity.__setitem__(3, identity[3] + 1)
                    page = StepList(controller, MagicMock(), lambda: "task", lambda: identity[1], lambda: tuple(identity),
                                    save, AsyncMock(), selected, paint, AsyncMock(), AsyncMock())
                    page.button.side_effect = lambda *args, **kwargs: MagicMock()
                    ui = MagicMock()
                    with patch("taskweave.desktop.components.step_list.ui", ui):
                        await page.render(steps, {"actions": [], "tools": [], "result_handlers": [], "resource_providers": []}, MagicMock(), MagicMock())
                        await page.actions["confirm_all"]()

                    save.assert_awaited_once()
                    self.assertEqual([op for op, _ in calls], ["step.list", "step.validate", "step.validate", "step.validate"])
                    self.assertEqual(selected.call_args.args, ("invalid",))
                    self.assertEqual(identity[1], "invalid")
                    self.assertEqual(identity[3], 8)
                    ui.notify.assert_called_once()
                    message = ui.notify.call_args.args[0]
                    self.assertIn("批量确认未执行", message)
                    labels = " ".join(str(call.args[0]) for call in ui.label.call_args_list if call.args)
                    self.assertIn("第 2 步「无效步骤」", labels)
                    self.assertIn("第 3 步「第二个无效步骤」", labels)
                    self.assertIn("语法错误" if invalid_kind == "returned" else "有效 Python", labels)
                    self.assertEqual([op for op, _ in calls].count("step.confirm.manual"), 0)
        asyncio.run(scenario())

    def test_confirm_all_reports_persisted_partial_count_on_manual_confirmation_failure(self):
        async def scenario():
            steps = [
                {"step_id": "first", "name": "第一步", "content_hash": "hash-1", "validation_state": "DRAFT", "capabilities": []},
                {"step_id": "second", "name": "第二步", "content_hash": "hash-2", "validation_state": "DRAFT", "capabilities": []},
            ]
            calls = []
            async def call(operation, **params):
                calls.append((operation, params))
                if operation == "step.list": return [dict(step) for step in steps]
                if operation == "step.validate": return {"valid": True, "diagnostics": []}
                if operation == "step.confirm.manual":
                    if params["step_id"] == "first":
                        steps[0]["validation_state"] = "VALIDATED"
                        return dict(steps[0])
                    raise TaskError("EDIT_CONFLICT", "第二步在校验后已被修改")
                raise AssertionError(operation)

            controller = SimpleNamespace(call=AsyncMock(side_effect=call))
            identity = ["task", "first", 1, 4]
            selected = MagicMock(side_effect=lambda step_id: identity.__setitem__(1, step_id))
            async def paint(): identity[3] += 1
            page = StepList(controller, MagicMock(), lambda: "task", lambda: identity[1], lambda: tuple(identity),
                            AsyncMock(return_value=steps[0]), AsyncMock(), selected, paint, AsyncMock(), AsyncMock())
            page.button.side_effect = lambda *args, **kwargs: MagicMock()
            ui = MagicMock()
            with patch("taskweave.desktop.components.step_list.ui", ui):
                await page.render(steps, {"actions": [], "tools": [], "result_handlers": [], "resource_providers": []}, MagicMock(), MagicMock())
                await page.actions["confirm_all"]()

            self.assertEqual([op for op, _ in calls], [
                "step.list", "step.validate", "step.validate",
                "step.confirm.manual", "step.confirm.manual", "step.list",
            ])
            self.assertEqual(steps[0]["validation_state"], "VALIDATED")
            self.assertEqual(steps[1]["validation_state"], "DRAFT")
            self.assertEqual(selected.call_args.args, ("second",))
            ui.notify.assert_called_once()
            message = ui.notify.call_args.args[0]
            self.assertIn("已确认 1/2 步", message)
            self.assertIn("第 2 步「第二步」确认失败", message)
            self.assertIn("已被修改", message)

        asyncio.run(scenario())

    def test_confirm_all_persists_manual_confirmations_and_reentry_marks_each_step(self):
        import tempfile
        from taskweave.application.service import Application
        from taskweave.desktop.controller import DesktopController

        async def scenario(app, task_id, steps):
            controller = DesktopController(app)
            identity = ["task", task_id, steps[0]["step_id"], 1]
            async def paint(): identity[3] += 1
            def make_page():
                page = StepList(controller, lambda *args, **kwargs: MagicMock(), lambda: task_id,
                                lambda: steps[0]["step_id"], lambda: tuple(identity),
                                AsyncMock(return_value=app.repo.step(steps[0]["step_id"])),
                                AsyncMock(), MagicMock(), paint, AsyncMock(), AsyncMock())
                page.button.side_effect = lambda *args, **kwargs: MagicMock()
                return page
            ui = MagicMock()
            with patch("taskweave.desktop.components.step_list.ui", ui):
                first_render = make_page()
                await first_render.render(steps, {"actions": [], "tools": [], "result_handlers": [], "resource_providers": []}, MagicMock(), MagicMock())
                await first_render.actions["confirm_all"]()
                saved = app.repo.steps(task_id)
                self.assertEqual([item["validation_state"] for item in saved], ["VALIDATED", "VALIDATED"])
                self.assertIn("全部步骤已确认", ui.notify.call_args.args[0])
                self.assertEqual(identity[3], 2)

                check_controls = []
                def button(title, callback, **kwargs):
                    control = MagicMock()
                    control.props.return_value = control
                    control.classes.return_value = control
                    check_controls.append((title, control))
                    return control
                second_render = StepList(controller, button, lambda: task_id, lambda: None, lambda: tuple(identity),
                                         AsyncMock(), AsyncMock(), MagicMock(), AsyncMock(), AsyncMock(), AsyncMock())
                await second_render.render(saved, {"actions": [], "tools": [], "result_handlers": [], "resource_providers": []}, MagicMock(), MagicMock())
                for step in saved:
                    control = next(control for title, control in check_controls if title.endswith(step["name"]))
                    self.assertTrue(any("icon-right=check" in str(call) for call in control.props.call_args_list))

        with tempfile.TemporaryDirectory(prefix="step-list-confirm-all-") as home, Application(home) as app:
            task = app.repo.create_task("确认全部真实临时任务", {"type": "object"})
            steps = [
                app.repo.save_step(task["task_id"], {"name": f"步骤 {index}", "step_content": "async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n"})
                for index in (1, 2)
            ]
            asyncio.run(scenario(app, task["task_id"], steps))

    def test_adjacent_reorder_persists_then_moves_existing_controls(self):
        async def scenario():
            steps = [
                {"step_id": "a", "name": "A", "validation_state": "DRAFT", "capabilities": []},
                {"step_id": "b", "name": "B", "validation_state": "DRAFT", "capabilities": []},
                {"step_id": "c", "name": "C", "validation_state": "VALIDATED", "capabilities": []},
            ]
            calls = []
            async def call(operation, **params):
                calls.append((operation, params))
                return [dict(step) for step in steps]

            controller = MagicMock()
            controller.call = AsyncMock(side_effect=call)
            callbacks, controls = {}, {}
            def button(title, callback, **kwargs):
                callbacks[title] = callback
                control = MagicMock()
                control.props.return_value = control
                control.classes.return_value = control
                control.style.return_value = control
                control.tooltip.return_value = control
                controls[title] = control
                return control

            page_identity = ("task", "b", 2, 7)
            page = StepList(
                controller, button, lambda: "task", lambda: "b", lambda: page_identity,
                AsyncMock(), AsyncMock(), MagicMock(), AsyncMock(), AsyncMock(), AsyncMock(),
            )
            list_area = MagicMock()
            with patch("taskweave.desktop.components.step_list.ui", MagicMock()):
                await page.render(steps, {"actions": [], "tools": [], "result_handlers": [], "resource_providers": []}, MagicMock(), list_area)
                up_item, down_item = MagicMock(is_deleted=False), MagicMock(is_deleted=False)
                page.bind_move_menu_items(up_item, down_item)
                await page.actions["move_up"]()
                self.assertFalse(page.actions["can_move_up"])
                self.assertTrue(page.actions["can_move_down"])
                await page.actions["move_down"]()
                await page.actions["move_down"]()
                self.assertTrue(page.actions["can_move_up"])
                self.assertFalse(page.actions["can_move_down"])
                await page.actions["move_up"]()
                await page.actions["move_up"]()
                await callbacks["1. A"]()

            self.assertEqual([step["step_id"] for step in steps], ["b", "a", "c"])
            self.assertEqual([operation for operation, _ in calls].count("step.reorder"), 5)
            self.assertEqual(calls[-1][1]["step_ids"], ["b", "a", "c"])
            self.assertEqual(controls["2. B"].text, "1. B")
            page.navigate_step.assert_awaited_once_with("a")
            self.assertEqual(up_item.set_enabled.call_args.args, (False,))
            self.assertEqual(down_item.set_enabled.call_args.args, (True,))
            self.assertIs(controls["2. B"].move.call_args.args[0], list_area)
            self.assertEqual(controls["2. B"].move.call_args.args[1], 0)
            controls["1. A"].move.assert_not_called()
            self.assertIn(unittest.mock.call("aria-label=添加步骤 title=添加步骤"), controls[""].props.call_args_list)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
