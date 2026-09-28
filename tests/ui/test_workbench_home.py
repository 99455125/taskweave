"""The workbench only renders current-page data and exposes real run actions."""

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, call

from nicegui import ui

from taskweave.desktop.state import ExecutionPageState
from taskweave.desktop.workbench import Workbench


class WorkbenchHomeTests(unittest.TestCase):
    def test_home_shows_active_actions_pending_reconciliation_and_recent_results(self):
        from nicegui.client import Client
        from nicegui.page import page

        async def scenario():
            running = {"run_id": "running", "task_id": "task-a", "mode": "EXECUTION", "status": "RUNNING", "can_end": True, "attempts": []}
            waiting = {"run_id": "waiting", "task_id": "task-a", "mode": "EXECUTION", "status": "PAUSED", "can_end": True, "attempts": []}
            paused = {"run_id": "paused", "task_id": "task-a", "mode": "EXECUTION", "status": "PAUSED", "can_end": True, "attempts": []}
            retained = {"run_id": "retained", "task_id": "task-a", "mode": "EXECUTION", "status": "SUCCEEDED", "can_end": True, "attempts": []}
            unknown_attempt = {"attempt_id": "attempt-unknown", "step_id": "step-a", "valid": True, "status": "UNKNOWN", "effect_state": "UNKNOWN", "error_summary": "结果需要人工核对"}
            uncertain = {"run_id": "uncertain", "task_id": "task-a", "mode": "EXECUTION", "status": "INTERRUPTED", "can_end": True, "instance_type": "execution", "attempts": [unknown_attempt]}
            history = {"run_id": "history", "task_id": "task-a", "mode": "EXECUTION", "status": "SUCCEEDED", "can_end": False, "attempts": []}

            async def run_request(run_id):
                if run_id == "waiting":
                    return {"waiting_input": {"id": "input-1", "scope": "task"}}
                return {"last_command": {"mode": "UNTIL", "target": "step-a", "retry": None, "from": None}}

            async def call(operation, **kwargs):
                if operation == "task.list": return [{"task_id": "task-a", "name": "投保任务", "updated_at": "2026-09-26", "description": ""}]
                if operation == "organization.category.list": return []
                if operation == "environment.list": return []
                if operation == "run.list": return [running, waiting, paused, retained, uncertain, history]
                if operation == "run.instances": return [running, waiting, paused, retained, uncertain]
                if operation == "step.list": return [{"step_id": "step-a", "name": "录入信息", "validation_state": "VALIDATED"}]
                if operation == "run.get": return uncertain
                if operation == "step.list": return []
                raise AssertionError(operation)

            workbench = Workbench.__new__(Workbench)
            workbench.controller = SimpleNamespace(call=call, run_request=run_request)
            workbench.page = "home"
            workbench.page_generation = 1
            workbench.tasks_page = SimpleNamespace(
                task_dialog=AsyncMock(), import_task_dialog=AsyncMock(),
                open_task=AsyncMock(),
            )
            workbench.planning_page = SimpleNamespace(create=AsyncMock())
            workbench.button = lambda title, callback, **kwargs: ui.button(title, on_click=callback)
            with ui.column():
                await workbench.workbench_home()

            elements = list(ui.context.client.elements.values())
            texts = {getattr(element, "text", None) for element in elements}
            self.assertTrue({"活跃执行", "继续执行", "填写输入", "待核对结果", "核对结果", "查看查询结果", "结束"}.issubset(texts))
            self.assertTrue({"任务总数", "活跃执行", "今日执行", "待处理", "最近执行结果", "快速开始"}.issubset(texts))
            self.assertEqual(sum(getattr(element, "text", None) == "结果需要人工核对" for element in elements), 1)
            section_panels = {}
            for element in elements:
                title = getattr(element, "text", None)
                if title not in {"最近更新任务", "最近执行结果", "快速开始", "活跃执行"}:
                    continue
                if "tw-section-title" not in str(getattr(element, "_classes", "")):
                    continue
                parent = element
                while parent is not None:
                    slot = getattr(parent, "parent_slot", None)
                    parent = slot._parent() if slot is not None else None
                    if parent is not None and "tw-home-panel" in getattr(parent, "_classes", []):
                        section_panels[title] = parent
                        break
            self.assertEqual(set(section_panels), {"最近更新任务", "最近执行结果", "快速开始", "活跃执行"})
            top_row = section_panels["最近更新任务"].parent_slot._parent()
            self.assertIs(top_row, section_panels["最近执行结果"].parent_slot._parent())
            bottom_row = section_panels["快速开始"].parent_slot._parent()
            self.assertIs(bottom_row, section_panels["活跃执行"].parent_slot._parent())
            dashboard = top_row.parent_slot._parent()
            self.assertIs(dashboard, bottom_row.parent_slot._parent())
            self.assertLess(dashboard.default_slot.children.index(top_row), dashboard.default_slot.children.index(bottom_row))
            self.assertLess(top_row.default_slot.children.index(section_panels["最近更新任务"]),
                            top_row.default_slot.children.index(section_panels["最近执行结果"]))
            self.assertLess(bottom_row.default_slot.children.index(section_panels["快速开始"]),
                            bottom_row.default_slot.children.index(section_panels["活跃执行"]))

        client = Client(page("/workbench-home-actions"))
        try:
            async def within_client():
                with client:
                    await scenario()
            asyncio.run(within_client())
        finally:
            client.delete()

    def test_home_resume_uses_last_core_command_and_end_respects_can_end(self):
        async def scenario():
            controller = SimpleNamespace(call=AsyncMock())
            workbench = Workbench.__new__(Workbench)
            workbench.controller = controller
            workbench.paint = AsyncMock()
            workbench.confirm_end = AsyncMock(return_value=True)
            run = {"run_id": "paused", "status": "PAUSED", "can_end": True}
            request = {"last_command": {"mode": "UNTIL", "target": "step-2", "retry": "step-1", "from": None}}
            await workbench.resume_home_run(run, request)
            self.assertEqual(controller.call.await_args.args[0], "run.start")
            self.assertEqual(controller.call.await_args.kwargs["mode"], "UNTIL")
            self.assertEqual(controller.call.await_args.kwargs["target_step_id"], "step-2")
            self.assertEqual(controller.call.await_args.kwargs["retry_step_id"], "step-1")

            controller.call.reset_mock()
            await workbench.end_home_run({"run_id": "stale", "status": "PAUSED", "can_end": False})
            controller.call.assert_not_awaited()
            workbench.confirm_end.assert_not_awaited()

            await workbench.end_home_run({"run_id": "running", "status": "RUNNING", "can_end": True})
            self.assertEqual(controller.call.await_args.args[0], "run.control")
            self.assertEqual(controller.call.await_args.kwargs["operation"], "cancel")

        asyncio.run(scenario())

    def test_home_reconciliation_opens_existing_run_review_flow(self):
        async def scenario():
            workbench = Workbench.__new__(Workbench)
            workbench.execution_state = ExecutionPageState()
            workbench.run_id = None
            workbench.navigate = AsyncMock(return_value=True)
            workbench.reconcile_dialog = AsyncMock()
            run = {"run_id": "unknown-run"}
            attempt = {"attempt_id": "attempt-unknown"}
            await workbench.reconcile_home_run(run, attempt)
            self.assertEqual(workbench.run_id, "unknown-run")
            workbench.navigate.assert_awaited_once_with("executions")
            workbench.reconcile_dialog.assert_awaited_once_with(attempt)

        asyncio.run(scenario())

    def test_home_continue_end_and_reconcile_submit_to_real_temporary_application(self):
        import tempfile
        from taskweave.application.service import Application
        from taskweave.desktop.controller import DesktopController

        async def exercise(app, run_id):
            controller = DesktopController(app)
            workbench = Workbench.__new__(Workbench)
            workbench.controller = controller
            workbench.paint = AsyncMock()
            workbench.confirm_end = AsyncMock(return_value=True)
            workbench.page = "home"
            workbench.run_id = None
            workbench.execution_state = ExecutionPageState()

            request = await controller.run_request(run_id)
            await workbench.resume_home_run(await controller.call("run.get", run_id=run_id), request)
            resumed = await asyncio.to_thread(app.coordinator.wait, run_id, timeout=10)
            self.assertIn(resumed["status"], {"PAUSED", "SUCCEEDED"})

            if resumed["status"] == "PAUSED":
                await workbench.end_home_run(resumed)
                ended = await controller.call("run.get", run_id=run_id)
                self.assertEqual(ended["status"], "CANCELLED")

            attempt = resumed["attempts"][0]
            app.repo.execute("UPDATE step_attempts SET status='UNKNOWN', effect_state='UNKNOWN' WHERE attempt_id=?", (attempt["attempt_id"],))
            app.repo.execute("UPDATE task_runs SET status='INTERRUPTED' WHERE run_id=?", (run_id,))
            result = await controller.call("run.reconcile", attempt_id=attempt["attempt_id"], decision="not_completed", evidence={"source": "local fixture"}, command_id="local-reconcile")
            self.assertEqual(result["decision"], "not_completed")
            self.assertEqual((await controller.call("run.get", run_id=run_id))["status"], "PAUSED")

        with tempfile.TemporaryDirectory(prefix="taskweave-home-actions-") as home:
            app = Application(home)
            try:
                task = app.repo.create_task("local action fixture", {"type": "object", "properties": {}})
                first = app.repo.save_step(task["task_id"], {"name": "one", "step_content": 'async def run(ctx, inputs):\n    return ctx.result(data={"ok": True})\n'})
                second = app.repo.save_step(task["task_id"], {"name": "two", "step_content": 'async def run(ctx, inputs):\n    return ctx.result(data={"ok": True})\n'})
                app.confirm_step_manual(first["step_id"], first["content_hash"])
                app.confirm_step_manual(second["step_id"], second["content_hash"])
                run = app.create_run(task["task_id"])
                app.coordinator.start(run["run_id"], "local-next", mode="NEXT")
                self.assertEqual(app.coordinator.wait(run["run_id"], timeout=10)["status"], "PAUSED")
                asyncio.run(exercise(app, run["run_id"]))
            finally:
                app.close()

    def test_late_home_responses_do_not_append_to_the_next_page(self):
        from nicegui.client import Client
        from nicegui.page import page

        async def scenario():
            home_started, home_release = asyncio.Event(), asyncio.Event()
            steps_started, steps_release = asyncio.Event(), asyncio.Event()
            task_list_calls = 0

            async def call(operation, **kwargs):
                nonlocal task_list_calls
                if operation == "task.list":
                    task_list_calls += 1
                    if task_list_calls == 1:
                        home_started.set()
                        await home_release.wait()
                        return []
                    return [{"task_id": "task-a", "name": "任务 A", "updated_at": "2026-09-26"}]
                if operation in {"run.list", "run.instances"}:
                    return []
                if operation in {"organization.category.list", "environment.list"}:
                    return []
                if operation == "step.list":
                    steps_started.set()
                    await steps_release.wait()
                    return []
                raise AssertionError(operation)

            workbench = Workbench.__new__(Workbench)
            workbench.controller = type("Controller", (), {"call": staticmethod(call)})()
            workbench.page = "home"
            workbench.page_generation = 1
            workbench.tasks_page = type("TasksPage", (), {"task_dialog": AsyncMock()})()
            workbench.button = lambda title, callback, **kwargs: ui.button(title, on_click=callback)

            with ui.column() as content:
                pending = asyncio.create_task(workbench.workbench_home())
                await home_started.wait()
                workbench.page = "tasks"
                workbench.page_generation += 1
                content.clear()
                ui.label("新任务页")
                home_release.set()
                await pending
                texts = [getattr(element, "text", None) for element in content.descendants()]
                self.assertIn("新任务页", texts)
                self.assertNotIn("工作台", texts)

                workbench.page = "home"
                workbench.page_generation += 1
                pending = asyncio.create_task(workbench.workbench_home())
                await steps_started.wait()
                workbench.page = "tasks"
                workbench.page_generation += 1
                content.clear()
                ui.label("下一任务页")
                steps_release.set()
                await pending
                texts = [getattr(element, "text", None) for element in content.descendants()]
                self.assertIn("下一任务页", texts)
                self.assertNotIn("工作台", texts)
                self.assertNotIn("最近任务", texts)

        client = Client(page("/workbench-home-event-race"))
        try:
            async def within_client():
                with client:
                    await scenario()
            asyncio.run(within_client())
        finally:
            client.delete()
