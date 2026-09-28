"""Task page operations use explicit navigation and save callbacks."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from taskweave.core.validation import TaskError
from taskweave.desktop.pages.tasks import TasksPage


class TasksPageTests(unittest.TestCase):
    def test_direct_steps_tab_enters_guarded_editor_route(self):
        async def scenario():
            current_route = ["tasks"]
            async def navigate(route, task_id=None):
                current_route[0] = route
                return True
            page = TasksPage(
                AsyncMock(), AsyncMock(), navigate, AsyncMock(),
                task_id=lambda: "task-1", page_identity=lambda: (current_route[0], 4),
            )
            tabs = SimpleNamespace(is_deleted=False, value="overview", update=MagicMock())
            result = await page.select_workspace_tab("steps", tabs)
            self.assertTrue(result)
            self.assertEqual(current_route[0], "editor")
            self.assertEqual(page.workspace_tab, "steps")
        asyncio.run(scenario())

    def test_same_task_rail_click_uses_step_leave_guard(self):
        async def scenario():
            page = TasksPage(AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock(), task_id=lambda: "task-a",
                prepare_step_leave=AsyncMock(return_value="stay"))
            page.workspace_tab = "steps"
            page.workspace_views = {}
            page.workspace_loaded = set()
            page._workspace_tabs = MagicMock(value="steps", is_deleted=False)
            with patch("taskweave.desktop.pages.tasks.ui"):
                result = await page.select_task({"task_id": "task-a"})
            self.assertFalse(result)
            page.prepare_step_leave.assert_awaited_once_with()
            self.assertEqual(page.workspace_tab, "steps")
        with patch("taskweave.desktop.pages.tasks.ui"):
            asyncio.run(scenario())

    def test_cross_task_cancel_does_not_change_workspace_tab(self):
        async def scenario():
            navigate = AsyncMock(return_value=False)
            page = TasksPage(AsyncMock(), AsyncMock(), navigate, AsyncMock(), task_id=lambda: "task-a")
            page.workspace_tab = "steps"
            self.assertFalse(await page.select_task({"task_id": "task-b"}))
            self.assertEqual(page.workspace_tab, "steps")
            navigate.assert_awaited_once_with("tasks", task_id="task-b")
        asyncio.run(scenario())

    def test_same_task_click_save_failure_keeps_workspace_and_draft(self):
        async def scenario():
            prepare = AsyncMock(side_effect=TaskError("EDIT_CONFLICT"))
            page = TasksPage(AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock(), task_id=lambda: "task-a",
                prepare_step_leave=prepare)
            page.workspace_tab = "steps"
            page.workspace_views = {}
            page.workspace_loaded = set()
            draft = SimpleNamespace(value="未保存步骤草稿")
            page.edit_controls = {"name": draft}
            tabs = MagicMock(value="overview", is_deleted=False)
            page._workspace_tabs = tabs
            with patch("taskweave.desktop.pages.tasks.ui"):
                result = await page.select_task({"task_id": "task-a"})
            self.assertFalse(result)
            prepare.assert_awaited_once_with()
            self.assertEqual(page.workspace_tab, "steps")
            self.assertEqual(tabs.value, "steps")
            self.assertEqual(page.edit_controls["name"].value, "未保存步骤草稿")
            tabs.update.assert_called_once_with()
        asyncio.run(scenario())

    def test_organization_failure_keeps_live_task_controls_and_metadata(self):
        async def scenario():
            controller = AsyncMock()
            controller.call.side_effect = OSError("organization store unavailable")
            page_generation = [4]
            page = TasksPage(controller, MagicMock(), AsyncMock(), AsyncMock(), task_id=lambda: "task-a",
                             page_generation=lambda: page_generation[0], page_identity=lambda: ("tasks", page_generation[0]))
            task = {"task_id": "task-a", "is_favorite": 0, "category_id": None}
            page._remember_task_organizations([task])
            favorite = MagicMock(is_deleted=False)
            with patch("taskweave.desktop.pages.tasks.ui.notify") as notify:
                result = await page.set_organization(task, favorite=True, favorite_control=favorite)
            self.assertFalse(result)
            self.assertFalse(favorite.is_deleted)
            self.assertEqual(page._task_organization(task), {"is_favorite": 0, "category_id": None})
            page.navigate.assert_not_awaited()
            page.repaint.assert_not_awaited()
            notify.assert_called_once()
        asyncio.run(scenario())

    def test_favorite_and_category_management_preserve_unsaved_step_draft(self):
        import tempfile
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page as nice_page
        from taskweave.application.service import Application
        from taskweave.desktop.controller import DesktopController
        from taskweave.desktop.workbench import Workbench

        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task("草稿保护任务", {"type": "object"})
            step = app.repo.save_step(task["task_id"], {
                "name": "原步骤", "step_content": "async def run(ctx, inputs):\n    return ctx.result(data=inputs)",
            })
            client = Client(nice_page("/task-organization-draft"))
            try:
                async def scenario():
                    with client:
                        workbench = Workbench(DesktopController(app))
                        callbacks = {}

                        def button(title, callback, **kwargs):
                            callbacks.setdefault(title, []).append(callback)
                            return ui.button(title, on_click=callback)

                        workbench.tasks_page.button = button
                        workbench.tasks_page.category_manager.button = button
                        await workbench.navigate("editor", task_id=task["task_id"], step_id=step["step_id"])
                        controls = workbench.edit_controls
                        controls["name"].value = "未保存的新步骤名"
                        controls["code"].value = "async def run(ctx, inputs):\n    return ctx.result(data={\"draft\": True})"
                        dirty_generation = workbench.page_generation

                        await callbacks["☆"][0]()

                        self.assertEqual(workbench.page, "editor")
                        self.assertEqual(workbench.page_generation, dirty_generation)
                        self.assertIs(workbench.edit_controls, controls)
                        self.assertFalse(controls["name"].is_deleted)
                        self.assertTrue(workbench._step_editor_is_dirty())
                        self.assertEqual(controls["name"].value, "未保存的新步骤名")
                        self.assertEqual(app.repo.step(step["step_id"])["name"], "原步骤")
                        saved_task = next(row for row in app.dispatch("task.list", {}) if row["task_id"] == task["task_id"])
                        self.assertEqual(saved_task["is_favorite"], 1)

                        await callbacks["分类管理"][0]()
                        name_control = next(
                            element for element in client.elements.values()
                            if getattr(element, "label", None) == "新分类名称" and not element.is_deleted
                        )
                        name_control.value = "草稿保护分类"
                        await callbacks["新建分类"][0]()

                        self.assertEqual(workbench.page, "editor")
                        self.assertEqual(workbench.page_generation, dirty_generation)
                        self.assertIs(workbench.edit_controls, controls)
                        self.assertTrue(workbench._step_editor_is_dirty())
                        self.assertEqual(controls["name"].value, "未保存的新步骤名")
                        self.assertEqual(app.repo.step(step["step_id"])["name"], "原步骤")
                        workbench._dispose_page(workbench.page)

                asyncio.run(scenario())
            finally:
                client.delete()

    def test_add_first_step_delegates_to_guarded_editor_flow(self):
        async def scenario():
            create_first_step = AsyncMock(return_value=True)
            page = TasksPage(AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock(), task_id=lambda: "task-1", create_first_step=create_first_step)

            result = await page.create_first_step("task-1")

            self.assertTrue(result)
            self.assertEqual(page.workspace_tab, "steps")
            create_first_step.assert_awaited_once_with("task-1")

        asyncio.run(scenario())

    def test_task_workspace_composes_overview_steps_execution_and_debug_history(self):
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page as nice_page

        async def scenario():
            calls = []
            async def call(operation, **kwargs):
                calls.append((operation, kwargs))
                if operation == "task.get":
                    return {"task_id": "task-a", "name": "保单任务", "description": "查询保单", "input_schema_json": '{"type":"object","properties":{}}', "updated_at": "today"}
                if operation == "task.list":
                    return [{"task_id": "task-a", "name": "保单任务", "description": "查询保单"}, {"task_id": "task-b", "name": "其他任务", "description": "另一个"}]
                if operation == "organization.category.list":
                    return []
                if operation == "step.list":
                    return [{"step_id": "step-a", "name": "查询", "validation_state": "VALIDATED"}]
                if operation == "run.list":
                    return [{"run_id": "exec-a", "task_id": "task-a", "mode": "EXECUTION", "status": "SUCCEEDED", "started_at": "today"}, {"run_id": "debug-a", "task_id": "task-a", "mode": "TRIAL", "status": "FAILED", "started_at": "today"}]
                raise AssertionError(operation)

            async def render_steps(): ui.label("步骤编辑视图")
            async def render_execution(task_id): ui.label("执行历史视图 " + task_id)
            async def render_debug(task_id): ui.label("调试历史视图 " + task_id)
            page = TasksPage(SimpleNamespace(call=call), lambda title, callback, **kwargs: ui.button(title, on_click=callback), AsyncMock(), AsyncMock(),
                task_id=lambda: "task-a", step_id=lambda: "step-a", page_generation=lambda: 3,
                render_step_details=render_steps, render_execution_history=render_execution,
                render_debug_history=render_debug, page_identity=lambda: ("editor", 3))
            with ui.column():
                await page.render_task_workspace()
            tabs = page._workspace_tabs
            await page.select_workspace_tab("steps", tabs)
            self.assertEqual(tabs.value, "steps")
            await page.select_workspace_tab("execution_history", tabs)
            self.assertEqual(tabs.value, "execution_history")
            await page.select_workspace_tab("debug_history", tabs)
            self.assertEqual(tabs.value, "debug_history")
            labels = [value for element in ui.context.client.elements.values() for value in (getattr(element, "text", None), getattr(element, "label", None))]
            self.assertIn("任务概览", labels)
            self.assertIn("步骤管理", labels)
            self.assertIn("执行历史", labels)
            self.assertIn("调试历史", labels)
            self.assertIn("保单任务", labels)
            self.assertIn("步骤编辑视图", labels)
            self.assertIn("执行历史视图 task-a", labels)
            self.assertIn("调试历史视图 task-a", labels)
            self.assertTrue(any(operation == "task.get" and params == {"task_id": "task-a"} for operation, params in calls))

        client = Client(nice_page("/task-workspace-composition"))
        try:
            async def within_client():
                with client:
                    await scenario()
            asyncio.run(within_client())
        finally:
            client.delete()

    def test_workspace_stays_on_steps_when_saving_fails_before_tab_switch(self):
        async def scenario():
            page = TasksPage(AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock(),
                task_id=lambda: "task-a", step_id=lambda: "step-a", page_generation=lambda: 3,
                save_step=AsyncMock(side_effect=TaskError("EDIT_CONFLICT")))
            page.workspace_tab = "steps"
            tabs = MagicMock(value="overview", is_deleted=False)
            switched = await page.select_workspace_tab("overview", tabs)
            self.assertFalse(switched)
            self.assertEqual(page.workspace_tab, "steps")
            self.assertEqual(tabs.value, "steps")
            tabs.update.assert_called_once_with()
        with patch("taskweave.desktop.pages.tasks.ui.notify") as notify:
            asyncio.run(scenario())
        notify.assert_called_once_with("步骤保存失败，仍停留在步骤详情：EDIT_CONFLICT", type="negative", timeout=8000)

    def test_workspace_dirty_leave_choices_do_not_duplicate_save(self):
        async def scenario():
            for choice, expected, save_count, discard_count in (
                ("stay", False, 0, 0), ("discard", False, 0, 1), ("save", True, 1, 0),
            ):
                prepare = AsyncMock(return_value=choice)
                discard = AsyncMock()
                page = TasksPage(AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock(),
                    task_id=lambda: "task-a", step_id=lambda: "step-a", page_generation=lambda: 3,
                    prepare_step_leave=prepare, discard_step_for_tab=discard)
                page.workspace_tab = "steps"
                page.workspace_views = {}
                page.workspace_loaded = set()
                page._workspace_tabs = None
                tabs = MagicMock(value="overview", is_deleted=False)
                with patch("taskweave.desktop.pages.tasks.ui"):
                    switched = await page.select_workspace_tab("overview", tabs)
                self.assertEqual(switched, expected)
                self.assertEqual(page.workspace_tab, "overview" if choice != "stay" else "steps")
                prepare.assert_awaited_once_with()
                discard.assert_awaited_once_with("overview") if discard_count else discard.assert_not_awaited()
                self.assertEqual(discard.await_count, discard_count)
                self.assertEqual(tabs.value, "steps" if choice == "stay" else "overview")

        asyncio.run(scenario())

    def test_render_keeps_task_search_and_omits_manual_reorder_actions(self):
        async def scenario():
            controller = AsyncMock()
            controller.call.side_effect = [
                [{"task_id": "task", "name": "合同任务", "description": "对账"}], [],
            ]
            titles = []
            def button(title, callback, **kwargs):
                titles.append(title)
                return MagicMock()
            page = TasksPage(controller, button, AsyncMock(), AsyncMock())
            with patch("taskweave.desktop.pages.tasks.ui") as fake_ui:
                fake_ui.input.return_value.props.return_value.classes.return_value.value = ""
                fake_ui.select.return_value.value = ""
                fake_ui.select.return_value.classes.return_value.value = ""
                await page.task_list()
                self.assertEqual(fake_ui.input.call_args.args[0], "搜索任务")
                self.assertEqual(fake_ui.label.call_args_list[0].args[0], "任务")
            self.assertIn("打开", titles)
            self.assertNotIn("上移", titles)
            self.assertNotIn("下移", titles)
            self.assertNotIn("排序", titles)
            controller.call.assert_any_await("task.list")

        asyncio.run(scenario())

    def test_open_task_enters_steps_workspace_and_keeps_overview_tab_available(self):
        async def scenario():
            navigate = AsyncMock(return_value=True)
            page = TasksPage(AsyncMock(), AsyncMock(), navigate, AsyncMock())

            await page.open_task({"task_id": "task"})

            navigate.assert_awaited_once_with("editor", task_id="task")
            self.assertEqual(page.workspace_tab, "steps")

        asyncio.run(scenario())

    def test_task_update_failure_does_not_run_completion_or_refresh(self):
        async def scenario():
            controller = AsyncMock()
            controller.call.side_effect = TaskError("TASK_LOCKED")
            before = AsyncMock()
            repaint = AsyncMock()
            page = TasksPage(controller, AsyncMock(), AsyncMock(), repaint)

            with self.assertRaises(TaskError):
                await page.save_task(
                    {"task_id": "task"}, "Renamed", {"type": "object"}, "description",
                    before_update=before,
                )

            before.assert_awaited_once()
            page.navigate.assert_not_awaited()
            repaint.assert_not_awaited()

        asyncio.run(scenario())

    def test_create_saves_then_navigates_only_after_persistence(self):
        async def scenario():
            order = []
            controller = AsyncMock()
            async def call(operation, **params):
                order.append(operation)
                return {"task_id": "created"}
            controller.call.side_effect = call
            navigate = AsyncMock(side_effect=lambda *args, **kwargs: order.append("navigate"))
            page = TasksPage(controller, AsyncMock(), navigate, AsyncMock())
            await page.create_and_open_task("New", {"type": "object"}, "desc")
            self.assertEqual(order, ["task.create", "navigate"])
            navigate.assert_awaited_once_with("editor", task_id="created")

        asyncio.run(scenario())
