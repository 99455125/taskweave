"""Navigation routes render their owning page and retain multi-select filters."""

import asyncio
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from taskweave.core.validation import TaskError
from taskweave.desktop.pages.executions import ExecutionsPage
from taskweave.desktop.state import ExecutionPageState, StepEditorState
from taskweave.desktop.workbench import MAIN_NAV_ITEMS, Workbench


class NavigationTests(unittest.TestCase):
    def test_cross_task_navigation_resets_workspace_after_leave_guard_before_paint(self):
        async def scenario():
            workbench = object.__new__(Workbench)
            workbench.page = "tasks"
            workbench.page_generation = 3
            workbench.step_state = StepEditorState(task_id="old", step_id=None, generation=0)
            workbench.task_id = "old"
            workbench.step_id = None
            workbench.run_id = None
            workbench.contexts = []
            workbench.context_entries = []
            workbench.edit_controls = None
            workbench.tasks_page = SimpleNamespace(workspace_tab="steps")
            workbench.planning_page = SimpleNamespace(state=SimpleNamespace(save_callback=None))
            workbench.prepare_step_editor_leave = AsyncMock(return_value="save")
            workbench._step_editor_is_dirty = lambda: False
            workbench._dispose_page = MagicMock()
            painted = []
            async def paint():
                painted.append(workbench.tasks_page.workspace_tab)
            workbench.paint = AsyncMock(side_effect=paint)

            navigated = await workbench.navigate("tasks", task_id="new")

            self.assertTrue(navigated)
            workbench.prepare_step_editor_leave.assert_awaited_once_with()
            self.assertEqual(painted, ["overview"])

        asyncio.run(scenario())

    def test_leave_waits_for_inflight_autosave_before_checking_dirty_state(self):
        from nicegui.client import Client
        from nicegui.page import page
        from taskweave.application.service import Application
        from taskweave.desktop.controller import DesktopController

        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task("leave during autosave")
            step = app.repo.save_step(task['task_id'], {
                'name': 'original',
                'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n',
            })
            client = Client(page('/ui2-autosave-leave-wait'))
            async def scenario():
                with client:
                    workbench = Workbench(DesktopController(app))
                    await workbench.navigate('editor', task_id=task['task_id'], step_id=step['step_id'])
                    entered, release = asyncio.Event(), asyncio.Event()
                    original_save = workbench.controller.save_draft
                    async def delayed_save(*args):
                        entered.set()
                        await release.wait()
                        return await original_save(*args)
                    workbench.controller.save_draft = delayed_save
                    workbench.edit_controls['name'].value = 'saved before leave'
                    timer = workbench._step_editor().timers[-1]
                    autosaving = asyncio.create_task(timer.callback())
                    await entered.wait()
                    workbench.paint = AsyncMock()
                    with patch('taskweave.desktop.workbench.ui') as fake_ui:
                        fake_ui.dialog.side_effect = AssertionError('clean autosaved form must not prompt')
                        leaving = asyncio.create_task(workbench.navigate('home'))
                        await asyncio.sleep(0)
                        self.assertTrue(workbench.step_state.autosave_paused)
                        self.assertFalse(leaving.done())
                        release.set()
                        await asyncio.gather(autosaving, leaving)
                    self.assertEqual(workbench.page, 'home')
                    self.assertEqual(app.repo.step(step['step_id'])['name'], 'saved before leave')
                    self.assertFalse(workbench.step_state.autosave_paused)
            try:
                asyncio.run(scenario())
            finally:
                client.delete()

    def test_discard_leaves_only_changes_not_already_autosaved(self):
        from nicegui.client import Client
        from nicegui.page import page
        from taskweave.application.service import Application
        from taskweave.desktop.controller import DesktopController

        class ChoiceDialog:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def __await__(self):
                async def result(): return "discard"
                return result().__await__()

        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task("autosave then discard")
            step = app.repo.save_step(task['task_id'], {
                'name': 'original', 'step_description': 'stored description',
                'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n',
            })
            client = Client(page('/ui2-autosave-discard'))
            async def scenario():
                with client:
                    workbench = Workbench(DesktopController(app))
                    await workbench.navigate('editor', task_id=task['task_id'], step_id=step['step_id'])
                    original_save = workbench.controller.save_draft
                    workbench.controller.save_draft = AsyncMock(wraps=original_save)
                    workbench.edit_controls['name'].value = 'autosaved-name'
                    timer = workbench._step_editor().timers[-1]
                    await timer.callback()
                    self.assertEqual(app.repo.step(step['step_id'])['name'], 'autosaved-name')
                    workbench.edit_controls['step_description'].value = 'unsaved description'
                    workbench.paint = AsyncMock()
                    with patch('taskweave.desktop.workbench.ui') as fake_ui:
                        fake_ui.dialog.return_value = ChoiceDialog()
                        self.assertTrue(await workbench.navigate('home'))
                    saved = app.repo.step(step['step_id'])
                    self.assertEqual(saved['name'], 'autosaved-name')
                    self.assertEqual(saved['step_description'], 'stored description')
                    workbench.controller.save_draft.assert_awaited_once()
            try:
                asyncio.run(scenario())
            finally:
                client.delete()

    def test_failed_step_save_blocks_task_workspace_switch(self):
        class ChoiceDialog:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def __await__(self):
                async def result(): return "save"
                return result().__await__()

        async def scenario():
            workbench = object.__new__(Workbench)
            workbench.page, workbench.page_generation = "editor", 5
            workbench.step_state = StepEditorState(task_id="task-a", step_id="step-a", generation=2)
            workbench.edit_controls = {"name": object()}
            workbench.old_step = {"name": "saved"}
            workbench.document = lambda: {"name": "draft"}
            workbench.save_editor = AsyncMock(side_effect=TaskError("EDIT_CONFLICT"))
            workbench.planning_page = SimpleNamespace(state=SimpleNamespace(save_callback=None))
            workbench._dispose_page = MagicMock()
            with patch("taskweave.desktop.workbench.ui") as fake_ui:
                fake_ui.dialog.return_value = ChoiceDialog()
                self.assertFalse(await workbench.navigate("tasks"))
            self.assertEqual(workbench.page, "editor")
            self.assertEqual(workbench.page_generation, 5)
            workbench.save_editor.assert_awaited_once_with()
            workbench._dispose_page.assert_not_called()
            fake_ui.notify.assert_called_once()
        asyncio.run(scenario())

    def test_dirty_editor_cancel_leave_keeps_draft_and_page(self):
        class ChoiceDialog:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def __await__(self):
                async def result(): return "stay"
                return result().__await__()

        async def scenario():
            workbench = object.__new__(Workbench)
            workbench.page, workbench.page_generation = "editor", 5
            workbench.step_state = StepEditorState(task_id="task-a", step_id="step-a", generation=2)
            workbench.edit_controls = {"name": object()}
            workbench.old_step = {"name": "saved"}
            workbench.document = lambda: {"name": "draft"}
            workbench.save_editor = AsyncMock()
            workbench.planning_page = SimpleNamespace(state=SimpleNamespace(save_callback=None))
            workbench._dispose_page = MagicMock()
            workbench.paint = AsyncMock()
            with patch("taskweave.desktop.workbench.normalize_step", side_effect=lambda value: value), \
                    patch("taskweave.desktop.workbench.ui") as fake_ui:
                fake_ui.dialog.return_value = ChoiceDialog()
                navigated = await workbench.navigate("home")
            self.assertFalse(navigated)
            self.assertEqual(workbench.page, "editor")
            self.assertEqual(workbench.page_generation, 5)
            workbench.save_editor.assert_not_awaited()
            workbench._dispose_page.assert_not_called()
            workbench.paint.assert_not_awaited()

        asyncio.run(scenario())

    def test_dirty_editor_discard_leaves_without_saving(self):
        class ChoiceDialog:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def __await__(self):
                async def result(): return "discard"
                return result().__await__()

        async def scenario():
            workbench = object.__new__(Workbench)
            workbench.page, workbench.page_generation = "editor", 5
            workbench.step_state = StepEditorState(task_id="task-a", step_id="step-a", generation=2)
            workbench.edit_controls = {"name": object()}
            workbench.old_step = {"name": "saved"}
            workbench.document = lambda: {"name": "draft"}
            workbench.save_editor = AsyncMock()
            workbench.planning_page = SimpleNamespace(state=SimpleNamespace(save_callback=None))
            workbench._dispose_page = MagicMock()
            workbench.paint = AsyncMock()
            with patch("taskweave.desktop.workbench.normalize_step", side_effect=lambda value: value), \
                    patch("taskweave.desktop.workbench.ui") as fake_ui:
                fake_ui.dialog.return_value = ChoiceDialog()
                navigated = await workbench.navigate("home")
            self.assertTrue(navigated)
            self.assertEqual(workbench.page, "home")
            workbench.save_editor.assert_not_awaited()
            workbench.paint.assert_awaited_once_with()

        asyncio.run(scenario())

    def test_dirty_editor_explicit_save_failure_blocks_navigation(self):
        class ChoiceDialog:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def __await__(self):
                async def result(): return "save"
                return result().__await__()

        async def scenario():
            workbench = object.__new__(Workbench)
            workbench.page, workbench.page_generation = "editor", 5
            workbench.step_state = StepEditorState(task_id="task-a", step_id="step-a", generation=2)
            workbench.edit_controls = {"name": object()}
            workbench.old_step = {"name": "saved"}
            workbench.document = lambda: {"name": "draft"}
            workbench.save_editor = AsyncMock(side_effect=TaskError("EDIT_CONFLICT"))
            workbench.planning_page = SimpleNamespace(state=SimpleNamespace(save_callback=None))
            workbench._dispose_page = MagicMock()
            workbench.paint = AsyncMock()
            with patch("taskweave.desktop.workbench.normalize_step", side_effect=lambda value: value), \
                    patch("taskweave.desktop.workbench.ui") as fake_ui:
                fake_ui.dialog.return_value = ChoiceDialog()
                navigated = await workbench.navigate("home")
            self.assertFalse(navigated)
            self.assertEqual(workbench.page, "editor")
            self.assertEqual(workbench.page_generation, 5)
            workbench.save_editor.assert_awaited_once_with()
            workbench._dispose_page.assert_not_called()
            workbench.paint.assert_not_awaited()
            fake_ui.notify.assert_called_once()

        asyncio.run(scenario())

    def test_late_home_list_does_not_append_home_to_new_page(self):
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page

        async def scenario():
            started, release = asyncio.Event(), asyncio.Event()

            async def call(operation, **kwargs):
                if operation == "task.list":
                    started.set()
                    await release.wait()
                    return []
                if operation == "run.list":
                    return []
                return []

            workbench = Workbench.__new__(Workbench)
            workbench.controller = SimpleNamespace(call=call)
            workbench.page = "home"
            workbench.page_generation = 1
            workbench.tasks_page = SimpleNamespace(task_dialog=AsyncMock())
            workbench.button = lambda title, callback, **kwargs: ui.button(title, on_click=callback)
            workbench.navigate = AsyncMock()

            with ui.column() as content:
                async def render_home():
                    with content:
                        await workbench.workbench_home()

                pending = asyncio.create_task(render_home())
                await started.wait()
                workbench.page = "tasks"
                workbench.page_generation += 1
                content.clear()
                ui.label("NEW TASK PAGE")
                release.set()
                await pending

            labels = [getattr(element, "text", None) for element in content.descendants()]
            self.assertIn("NEW TASK PAGE", labels)
            self.assertNotIn("工作台", labels)
            self.assertNotIn("最近任务", labels)

        client = Client(page("/workbench-home-race"))
        try:
            async def within_client():
                with client:
                    await scenario()
            asyncio.run(within_client())
        finally:
            client.delete()

    def test_dirty_editor_explicit_save_before_leaving_task_workspace(self):
        async def scenario():
            workbench = object.__new__(Workbench)
            workbench.page, workbench.page_generation = "editor", 1
            workbench.step_state = StepEditorState(task_id="task", step_id="step", generation=3)
            workbench.edit_controls = {"name": object()}
            workbench.old_step = {"name":"old"}
            workbench.document = lambda:{"name":"new"}
            workbench.planning_page = SimpleNamespace(state=SimpleNamespace(save_callback=None))
            workbench._dispose_page = MagicMock()
            workbench.save_editor = AsyncMock(return_value={"step_id":"step"})
            workbench.paint = AsyncMock()
            class ChoiceDialog:
                def __enter__(self): return self
                def __exit__(self, *_args): return False
                def __await__(self):
                    async def result(): return "save"
                    return result().__await__()
            with patch("taskweave.desktop.workbench.normalize_step", side_effect=lambda value:value), \
                    patch("taskweave.desktop.workbench.ui") as fake_ui:
                fake_ui.dialog.return_value = ChoiceDialog()
                allowed = await workbench.navigate("tasks")
            self.assertTrue(allowed)
            self.assertEqual(workbench.page, "tasks")
            self.assertEqual(workbench.page_generation, 2)
            workbench.save_editor.assert_awaited_once_with()
            workbench._dispose_page.assert_called_once_with("editor")
            workbench.paint.assert_awaited_once_with()

        asyncio.run(scenario())

    def test_planning_save_failure_keeps_route_callback_and_page_resources(self):
        async def scenario():
            workbench = object.__new__(Workbench)
            callback = AsyncMock(side_effect=RuntimeError("save failed"))
            workbench.page, workbench.page_generation = "planning", 3
            workbench.planning_page = SimpleNamespace(state=SimpleNamespace(save_callback=callback))
            workbench.edit_controls, workbench.old_step = {}, None
            workbench.task_id, workbench.step_id = None, None
            workbench._dispose_page = MagicMock()
            with self.assertRaisesRegex(RuntimeError, "save failed"):
                await workbench.navigate("tasks")
            self.assertEqual(workbench.page, "planning")
            self.assertEqual(workbench.page_generation, 3)
            self.assertIs(workbench.planning_page.state.save_callback, callback)
            workbench._dispose_page.assert_not_called()

        asyncio.run(scenario())

    def test_marketplace_remains_in_primary_navigation_and_paint_dispatches_to_page(self):
        async def scenario():
            self.assertIn(("marketplace", "集市"), MAIN_NAV_ITEMS)
            workbench = object.__new__(Workbench)
            workbench.page = "marketplace"
            workbench.page_generation = 0
            workbench.content = MagicMock()
            workbench.step_state = MagicMock()
            workbench.step_editor = MagicMock()
            workbench.execution_details = MagicMock()
            for name in ("planning_page", "tasks_page", "executions_page", "run_page", "history_page", "plugins_page", "marketplace_page", "environment_page", "settings_page"):
                page = MagicMock()
                page.render = AsyncMock()
                setattr(workbench, name, page)
            workbench.planning_page.state.save_callback = None
            with patch("taskweave.desktop.workbench.ui"):
                await workbench.paint()
            workbench.marketplace_page.render.assert_awaited_once_with()
            workbench.marketplace_page.dispose.assert_called_once_with()

        asyncio.run(scenario())

    def test_execution_task_filter_accepts_multiple_searchable_tasks(self):
        async def scenario():
            controller = AsyncMock()
            controller.call.side_effect = [[{"task_id": "a", "name": "Alpha"}, {"task_id": "b", "name": "Beta"}]]
            selects = [MagicMock(), MagicMock()]
            for select in selects:
                select.props.return_value = select
                select.classes.return_value = select
            ui = MagicMock()
            ui.select.side_effect = selects
            page = ExecutionsPage(controller, ExecutionPageState(), MagicMock(), AsyncMock())
            with patch("taskweave.desktop.pages.executions.ui", ui):
                await page.render()
            self.assertEqual(ui.select.call_args_list[0].kwargs["multiple"], True)
            self.assertEqual(ui.select.call_args_list[0].kwargs["label"], "任务筛选（可多选）")
            self.assertIn("use-input", selects[0].props.call_args.args[0])

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
