"""Step editor saves keep the identity they started with."""

import asyncio
import tempfile
import unittest
from unittest.mock import AsyncMock

from taskweave.desktop.state import StepEditorState
from taskweave.desktop.workbench import Workbench


class StepEditorStateTests(unittest.TestCase):
    def test_step_editor_autosave_persists_dirty_document(self):
        from nicegui.client import Client
        from nicegui.page import page
        from taskweave.application.service import Application
        from taskweave.desktop.controller import DesktopController

        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task("autosave")
            step = app.repo.save_step(task['task_id'], {
                'name': 'original',
                'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n',
            })
            client = Client(page('/ui2-autosave-success'))
            async def scenario():
                with client:
                    workbench = Workbench(DesktopController(app))
                    self.assertTrue(await workbench.navigate('editor', task_id=task['task_id'], step_id=step['step_id']))
                    workbench.edit_controls['name'].value = 'edited-name'
                    timer = workbench._step_editor().timers[-1]
                    result = timer.callback()
                    if asyncio.iscoroutine(result):
                        await result
                    self.assertEqual(timer.interval, 1.0)
                    self.assertEqual(app.repo.step(step['step_id'])['name'], 'edited-name')
                    self.assertEqual(workbench._editor_view('save_state').text, '已保存')
            try:
                asyncio.run(scenario())
            finally:
                client.delete()

    def test_step_editor_autosave_failure_keeps_dirty_draft(self):
        from nicegui.client import Client
        from nicegui.page import page
        from taskweave.application.service import Application
        from taskweave.core.validation import TaskError
        from taskweave.desktop.controller import DesktopController

        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task("autosave failure")
            step = app.repo.save_step(task['task_id'], {
                'name': 'original',
                'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n',
            })
            client = Client(page('/ui2-autosave-failure'))
            async def scenario():
                with client:
                    workbench = Workbench(DesktopController(app))
                    await workbench.navigate('editor', task_id=task['task_id'], step_id=step['step_id'])
                    workbench.edit_controls['name'].value = 'draft-after-failure'
                    workbench.controller.save_draft = AsyncMock(side_effect=TaskError('EDIT_CONFLICT'))
                    result = workbench._step_editor().timers[-1].callback()
                    if asyncio.iscoroutine(result):
                        await result
                    self.assertEqual(app.repo.step(step['step_id'])['name'], 'original')
                    self.assertEqual(workbench._editor_view('save_state').text, '保存失败，点击重试')
                    self.assertTrue(workbench._step_editor_is_dirty())
            try:
                asyncio.run(scenario())
            finally:
                client.delete()

    def test_late_autosave_response_cannot_mutate_next_editor(self):
        from types import SimpleNamespace
        from nicegui.client import Client
        from nicegui.page import page
        from taskweave.application.service import Application
        from taskweave.desktop.controller import DesktopController

        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task("late autosave")
            first = app.repo.save_step(task['task_id'], {
                'name': 'first', 'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n',
            })
            second = app.repo.save_step(task['task_id'], {
                'name': 'second', 'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n',
            })
            client = Client(page('/ui2-autosave-late'))
            async def scenario():
                with client:
                    workbench = Workbench(DesktopController(app))
                    await workbench.navigate('editor', task_id=task['task_id'], step_id=first['step_id'])
                    entered, release = asyncio.Event(), asyncio.Event()
                    original_save = workbench.controller.save_draft
                    async def delayed_save(*args):
                        entered.set()
                        await release.wait()
                        return await original_save(*args)
                    workbench.controller.save_draft = delayed_save
                    workbench.edit_controls['name'].value = 'first autosaved'
                    timer = workbench._step_editor().timers[-1]
                    pending = asyncio.create_task(timer.callback())
                    await entered.wait()
                    new_state_control = SimpleNamespace(text='second saved', is_deleted=False)
                    workbench.step_state.step_id = second['step_id']
                    workbench.step_state.old_step = second
                    workbench.step_state.generation += 1
                    workbench._step_editor().view['save_state'] = new_state_control
                    release.set()
                    await pending
                    self.assertEqual(app.repo.step(first['step_id'])['name'], 'first autosaved')
                    self.assertEqual(app.repo.step(second['step_id'])['name'], 'second')
                    self.assertEqual(workbench.step_state.old_step['step_id'], second['step_id'])
                    self.assertEqual(new_state_control.text, 'second saved')
            try:
                asyncio.run(scenario())
            finally:
                client.delete()

    def test_late_step_context_list_cannot_publish_into_next_editor(self):
        async def scenario():
            from dataclasses import MISSING, fields
            from types import SimpleNamespace
            from taskweave.desktop.components.step_editor import StepEditor, StepEditorRenderContext

            entered, release = asyncio.Event(), asyncio.Event()
            identity = {"page_generation": 1}
            state = StepEditorState(task_id="task-a", step_id="step-a", generation=1)
            context_state = SimpleNamespace(entries=["old-a"], ai_contexts=["old-ai-a"])
            async def call(operation, **kwargs):
                if operation == "step.list":
                    return [{"step_id": "step-a", "name": "A", "position": 0}]
                if operation == "context.list":
                    entered.set()
                    await release.wait()
                    return ["late-a"]
                raise AssertionError(operation)

            required = {
                item.name: None for item in fields(StepEditorRenderContext)
                if item.default is MISSING and item.default_factory is MISSING
            }
            required.update(
                state=state,
                context_state=context_state,
                controller=SimpleNamespace(call=call),
                page_getter=lambda: "editor",
                page_generation_getter=lambda: identity["page_generation"],
            )
            context = StepEditorRenderContext(**required)
            editor = StepEditor(context.controller, state, lambda: identity["page_generation"])
            rendering = asyncio.create_task(editor.render(context))
            await entered.wait()
            state.task_id, state.step_id = "task-b", "step-b"
            state.generation += 1
            identity["page_generation"] += 1
            context_state.entries = ["current-b"]
            context_state.ai_contexts = ["current-ai-b"]
            release.set()
            await rendering

            self.assertEqual(context_state.entries, ["current-b"])
            self.assertEqual(context_state.ai_contexts, ["current-ai-b"])

        asyncio.run(scenario())

    def test_step_editor_owns_pending_state_refresh_and_input_apply(self):
        async def scenario():
            from types import SimpleNamespace
            from taskweave.desktop.components.step_editor import StepEditor

            identity = ["task", "step", 3, 4]
            saved = {"step_id": "step", "input_schema": {}}
            calls = []
            class Control:
                is_deleted = False
                def __init__(self): self.text = "已保存"
                def props(self, *args, **kwargs): calls.append(("props", args, kwargs))
                def style(self, value): calls.append(("style", value))
            class Area:
                is_deleted = False
                def clear(self): calls.append(("clear",))
                def __enter__(self): return self
                def __exit__(self, *_): pass
            class Form:
                def task_edits(self): return {"a": "draft"}
                def step_edits(self): return {"b": 2}
                async def refresh(self, step, environment, task_edits, step_edits):
                    calls.append(("refresh", step, environment, task_edits, step_edits))
                def apply_task_values(self, values): calls.append(("task_values", values))
                def apply_step_values(self, values): calls.append(("step_values", values))
            state = StepEditorState(task_id="task", step_id="step", old_step={"step_id":"step"}, generation=3)
            controller = SimpleNamespace(call=AsyncMock(return_value={"step_id":"step", "name":"Step"}))
            editor = StepEditor(controller, state, lambda: identity[3])
            form = Form()
            editor.view.update(
                save_state=Control(), selected_step_control=Control(),
                trial_variables_area=Area(), trial_form=form,
                trial_environment=SimpleNamespace(value="uat"),
            )

            result = await editor.mark_step_pending()
            self.assertEqual(result["step_id"], "step")
            self.assertEqual(state.old_step["name"], "Step")
            self.assertEqual(editor.view["save_state"].text, "已保存 · 待确认")
            self.assertEqual(calls[-2][0], "props")

            await editor.refresh_trial_inputs(saved)
            self.assertEqual(calls[-1], ("refresh", saved, "uat", {"a":"draft"}, {"b":2}))
            self.assertTrue(editor.apply_trial_values({"scope":"task"}, {"x":1}, editor.identity()))
            self.assertEqual(calls[-1], ("task_values", {"x":1}))

        asyncio.run(scenario())

    def test_step_editor_pending_read_ignores_stale_editor_identity(self):
        async def scenario():
            from types import SimpleNamespace
            from taskweave.desktop.components.step_editor import StepEditor
            entered, release = asyncio.Event(), asyncio.Event()
            identity = ["task-a", "step-a", 1, 2]
            async def get_step(*_args, **_kwargs):
                entered.set()
                await release.wait()
                return {"step_id":"step-a", "name":"A"}
            state = StepEditorState(task_id="task-a", step_id="step-a", old_step={"step_id":"step-a"}, generation=1)
            editor = StepEditor(SimpleNamespace(call=get_step), state, lambda: identity[3])
            from unittest.mock import MagicMock
            original = dict(state.old_step)
            editor.view.update(save_state=SimpleNamespace(is_deleted=False, text="已保存"), selected_step_control=SimpleNamespace(is_deleted=False, props=MagicMock(), style=MagicMock()))
            pending = asyncio.create_task(editor.mark_step_pending())
            await entered.wait()
            identity[:] = ["task-b", "step-b", 2, 3]
            state.task_id, state.step_id, state.generation = "task-b", "step-b", 2
            release.set()
            await pending
            self.assertEqual(state.old_step, original)
            self.assertEqual(editor.view["save_state"].text, "已保存")
        asyncio.run(scenario())

    def test_trial_input_rebuild_clears_container_before_factory_renders(self):
        async def scenario():
            from types import SimpleNamespace
            from taskweave.desktop.components.step_editor import StepEditor
            events = []
            class Area:
                is_deleted = False
                active = False
                def clear(self): events.append("clear")
                def __enter__(self):
                    self.active = True
                    events.append("enter")
                    return self
                def __exit__(self, *_): self.active = False
            area = Area()
            state = StepEditorState(task_id="task", step_id="step", generation=2)
            async def factory(step, environment, values=None):
                events.append(("factory", area.active))
                return object()
            editor = StepEditor(SimpleNamespace(), state, lambda: 4, trial_variables=factory)
            editor.view.update(
                trial_variables_area=area, trial_form=None,
                trial_environment=SimpleNamespace(value="uat"),
            )
            await editor.refresh_trial_inputs({"step_id":"step"}, preserve_values=False)
            self.assertEqual(events, ["clear", "enter", ("factory", True)])
            self.assertIsNotNone(editor.view["trial_form"])
        asyncio.run(scenario())

    def test_queued_save_rechecks_identity_after_acquiring_the_serial_lock(self):
        async def scenario():
            from taskweave.core.validation import TaskError

            state = StepEditorState(task_id="task-a", step_id="step-a", old_step={"step_id": "step-a"})
            workbench = object.__new__(Workbench)
            workbench.step_state = state
            workbench.page_generation = 1
            workbench.controller = AsyncMock()
            workbench.document = lambda: {"name": "draft A"}
            await state.save_lock.acquire()
            queued = asyncio.create_task(workbench.save_editor())
            await asyncio.sleep(0)
            state.task_id, state.step_id = "task-b", "step-b"
            state.old_step = {"step_id": "step-b"}
            state.generation += 1
            workbench.page_generation += 1
            state.save_lock.release()

            with self.assertRaises(TaskError) as raised:
                await queued
            self.assertEqual(raised.exception.code, "EDITOR_CHANGED")
            workbench.controller.save_draft.assert_not_awaited()
            self.assertEqual(state.old_step, {"step_id": "step-b"})

        asyncio.run(scenario())

    def test_queued_save_uses_latest_old_step_and_keeps_triggered_document_snapshot(self):
        async def scenario():
            from taskweave.desktop.components.step_editor import StepEditor

            entered, release = asyncio.Event(), asyncio.Event()
            calls = []
            async def save_draft(task_id, document, old_step):
                calls.append((document, old_step))
                if len(calls) == 1:
                    entered.set()
                    await release.wait()
                    return {"step_id": "step-a", "content_hash": "h1"}
                return {"step_id": "step-a", "content_hash": "h2"}

            state = StepEditorState(task_id="task-a", step_id="step-a", old_step={"step_id": "step-a", "content_hash": "h0"})
            editor = StepEditor(SimpleNamespace(save_draft=save_draft), state, lambda: 1)
            first = asyncio.create_task(editor.save({"draft": "first"}))
            await entered.wait()
            second = asyncio.create_task(editor.save({"draft": "second"}))
            await asyncio.sleep(0)
            release.set()
            await asyncio.gather(first, second)

            self.assertEqual([item[1]["content_hash"] for item in calls], ["h0", "h1"])
            self.assertEqual([item[0] for item in calls], [{"draft": "first"}, {"draft": "second"}])
            self.assertEqual(state.old_step["content_hash"], "h2")

        from types import SimpleNamespace
        from unittest.mock import MagicMock
        asyncio.run(scenario())

    def test_non_endable_debug_run_disables_stale_end_action(self):
        async def scenario():
            from unittest.mock import MagicMock

            workbench = object.__new__(Workbench)
            workbench.page = "editor"
            workbench.page_generation = 2
            workbench.step_state = StepEditorState(task_id="task", step_id="step", old_step={"step_id": "step"})
            workbench.trials = {"step": "run"}
            panel = MagicMock()
            panel.end = AsyncMock()
            panel.refresh_trial = AsyncMock()
            workbench.step_debug_panel = panel
            workbench.controller = SimpleNamespace(call=AsyncMock(return_value={"can_end": False, "status": "SUCCEEDED", "request_json": "{}"}))
            workbench.confirm_end = AsyncMock()

            await workbench.end_trial()

            panel.end.assert_awaited_once_with(workbench.confirm_end, panel.refresh_trial)
            workbench.confirm_end.assert_not_awaited()

        from types import SimpleNamespace
        from unittest.mock import MagicMock
        asyncio.run(scenario())

    def test_late_debug_end_lookup_does_not_change_next_editor_button(self):
        async def scenario():
            from unittest.mock import MagicMock
            from taskweave.desktop.components.step_debug import StepDebugPanel

            entered, release = asyncio.Event(), asyncio.Event()
            async def get_run(*args, **kwargs):
                entered.set()
                await release.wait()
                return {"can_end": True}

            identity = ["task", "step-a", 8, 4]
            end_button = MagicMock(is_deleted=False)
            callbacks = {}
            def button(title, callback, **kwargs):
                callbacks[title] = kwargs
                return end_button if title == "结束调试" else MagicMock(is_deleted=False)
            panel = StepDebugPanel(button, SimpleNamespace(call=AsyncMock(side_effect=get_run)), lambda: tuple(identity), lambda step: "run-a", lambda: None)
            panel.render_actions(MagicMock(), AsyncMock(), AsyncMock(), AsyncMock())

            pending = asyncio.create_task(callbacks["结束调试"]["on_settled"]())
            await entered.wait()
            identity[:] = ["task", "step-b", 9, 5]
            release.set()
            await pending
            end_button.set_enabled.assert_not_called()

        from types import SimpleNamespace
        from unittest.mock import MagicMock
        asyncio.run(scenario())

    def test_late_save_persists_original_step_without_mutating_new_editor(self):
        async def scenario():
            entered = asyncio.Event()
            release = asyncio.Event()
            controller = AsyncMock()

            async def save(task_id, document, old_step):
                entered.set()
                await release.wait()
                return {"task_id": task_id, "step_id": old_step["step_id"], "document": document}

            controller.save_draft.side_effect = save
            workbench = object.__new__(Workbench)
            workbench.step_state = StepEditorState(
                task_id="task-a", step_id="step-a", old_step={"step_id": "step-a"},
            )
            workbench.controller = controller
            workbench.document = lambda: {"name": "A draft"}

            pending = asyncio.create_task(workbench.save_editor())
            await entered.wait()
            workbench.step_state.task_id = "task-b"
            workbench.step_state.step_id = "step-b"
            workbench.step_state.old_step = {"step_id": "step-b"}
            workbench.step_state.generation += 1
            release.set()
            saved = await pending

            controller.save_draft.assert_awaited_once_with("task-a", {"name": "A draft"}, {"step_id": "step-a"})
            self.assertEqual(saved["step_id"], "step-a")
            self.assertEqual(workbench.old_step, {"step_id": "step-b"})
            self.assertEqual(workbench.step_id, "step-b")

        asyncio.run(scenario())


    def test_debug_panel_owns_end_run_state_transition(self):
        async def scenario():
            from types import SimpleNamespace
            from taskweave.desktop.components.step_debug import StepDebugPanel
            from unittest.mock import MagicMock

            identity = ("task", "step", 1, 2)
            controller = SimpleNamespace(call=AsyncMock(return_value={"can_end": False, "status": "SUCCEEDED", "request_json": "{}"}))
            panel = StepDebugPanel(MagicMock(), controller, lambda: identity, lambda step: "run", lambda: None)
            panel.actions = {"end": MagicMock(is_deleted=False)}
            confirm = AsyncMock()
            refresh = AsyncMock()
            await panel.end(confirm, refresh)
            confirm.assert_not_awaited()
            refresh.assert_not_awaited()
            panel.actions["end"].set_enabled.assert_called_once_with(False)

        asyncio.run(scenario())

    def test_step_editor_disposes_owned_refresh_timers_on_navigation(self):
        from taskweave.desktop.components.step_editor import StepEditor
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        state = StepEditorState(task_id="task", step_id="step")
        editor = StepEditor(SimpleNamespace(), state, lambda: 1)
        timer = SimpleNamespace(is_deleted=False, delete=MagicMock())
        editor.own_timer(timer)
        editor.dispose()
        editor.dispose()

        timer.delete.assert_called_once_with()
        self.assertEqual(editor.timers, [])


if __name__ == "__main__":
    unittest.main()


class RouteRestoreTests(unittest.TestCase):
    def test_restore_editor_checks_identity_and_remembers_debug(self):
        async def scenario():
            from unittest.mock import AsyncMock, MagicMock, patch
            from types import SimpleNamespace
            controller = SimpleNamespace(call=AsyncMock(side_effect=[{"task_id": "t"}, {"task_id": "t", "step_id": "s"}]), plugin_contributions=MagicMock(return_value=[]), reset_debug_conversation=MagicMock())
            writer = MagicMock()
            with patch("taskweave.desktop.workbench.ui", MagicMock()):
                workbench = Workbench(controller, route_writer=writer)
            await workbench.restore_route("editor", "t", "s", True)
            self.assertEqual((workbench.page, workbench.task_id, workbench.step_id), ("editor", "t", "s"))
            self.assertTrue(workbench._open_debug_on_navigation)
            workbench.debug_visibility_changed(True)
            self.assertEqual(writer.call_args.args[0]["debug"], "true")
        asyncio.run(scenario())
