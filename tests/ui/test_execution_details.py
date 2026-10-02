"""Execution details discard refresh replies after leaving their page."""

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from taskweave.desktop.components.execution_details import ExecutionDetails
from taskweave.desktop.state import ExecutionPageState


class ExecutionDetailsTests(unittest.TestCase):
    def test_poll_reuses_unchanged_run_details_and_invalidates_on_new_event(self):
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page
        async def scenario():
            revision, queries = [1], []
            run = {'run_id': 'r', 'mode': 'EXECUTION', 'task_id': 't', 'environment_id': None,
                'request_json': '{}', 'definition_json': json.dumps({'steps': [{'step_id': 's', 'name': 's'}]}),
                'status': 'PAUSED', 'attempts': [], 'started_at': None}
            async def call(operation, **kwargs):
                queries.append(operation)
                if operation == 'run.list': return [{**run, 'event_revision': revision[0]}]
                if operation == 'run.get': return dict(run)
                if operation == 'environment.list': return []
                if operation == 'task.list': return [{'task_id': 't', 'name': '任务'}]
                raise AssertionError(operation)
            state = ExecutionPageState(run_id='r', execution_rows=ui.column(), execution_list_area=ui.column())
            details = ExecutionDetails(SimpleNamespace(call=call), state,
                lambda title, cb, **kw: ui.button(title, on_click=cb), lambda: 'executions', lambda: 1,
                *[AsyncMock() for _ in range(6)])
            await details.render_rows(force=False)
            area = state.run_area
            await details.render_rows(force=False)
            self.assertEqual(queries.count('run.get'), 1)
            self.assertIs(state.run_area, area)
            revision[0] += 1
            await details.render_rows(force=False)
            self.assertEqual(queries.count('run.get'), 2)
        client = Client(page('/execution-summary-poll'))
        try:
            async def run():
                with client:
                    await scenario()
            asyncio.run(run())
        finally:
            client.delete()

    def test_live_log_host_survives_status_refresh_and_is_disposed_on_run_switch(self):
        import tempfile
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page
        from taskweave.application.service import Application
        from taskweave.desktop.controller import DesktopController
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task('stable logs')['task_id']
            step = app.repo.save_step(task, {'name': 'first',
                'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data=None)'})
            app.confirm_step_manual(step['step_id'], step['content_hash'])
            a, b = app.create_run(task), app.create_run(task)
            client = Client(page('/execution-stable-live-log'))
            async def scenario():
                with client:
                    state = ExecutionPageState(run_id=a['run_id'], execution_rows=ui.column(), execution_list_area=ui.column())
                    details = ExecutionDetails(DesktopController(app), state,
                        lambda title, cb, **kw: ui.button(title, on_click=cb), lambda: 'executions', lambda: 1,
                        *[AsyncMock() for _ in range(6)])
                    await details.refresh(force=False)
                    viewer, host = details._live_logs, details._logs_host
                    await viewer.toggle()
                    previous = viewer.output.value
                    app.runs.runs.event(a['run_id'], 'Changed', {'message': 'new event'})
                    await details.refresh(force=False)
                    self.assertIs(details._live_logs, viewer)
                    self.assertIs(details._logs_host, host)
                    self.assertEqual(viewer.output.value, previous)
                    await details.select_run(b['run_id'])
                    self.assertTrue(viewer.timer.is_deleted)
                    self.assertIsNot(details._live_logs, viewer)
                    self.assertEqual(details._live_logs.run_id, b['run_id'])
                    details.dispose()
            try:
                asyncio.run(scenario())
            finally:
                client.delete()

    def test_poll_skips_hidden_and_overlapping_requests(self):
        async def scenario():
            entered, release = asyncio.Event(), asyncio.Event()
            async def refresh(**kwargs):
                entered.set()
                await release.wait()
            details = ExecutionDetails(AsyncMock(), ExecutionPageState(), MagicMock(),
                lambda: 'executions', lambda: 1, *[AsyncMock() for _ in range(6)])
            details.refresh = AsyncMock(side_effect=refresh)
            details.visible = False
            await details.poll()
            details.refresh.assert_not_awaited()
            details.visible = True
            pending = asyncio.create_task(details.poll())
            await entered.wait()
            await details.poll()
            self.assertEqual(details.refresh.await_count, 1)
            release.set()
            await pending
        asyncio.run(scenario())

    def test_execution_detail_tabs_keep_step_results_and_default_removed_result_tab_to_details(self):
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page

        async def scenario():
            run = {
                "run_id": "run-a", "mode": "EXECUTION", "task_id": "task-a", "environment_id": None,
                "request_json": "{}", "definition_json": json.dumps({"steps": [
                    {"step_id": "step-a", "name": "步骤一：长中文结果标题验收"},
                    {"step_id": "step-b", "name": "步骤二：审核说明与结果引用"},
                ]}), "status": "SUCCEEDED", "attempts": [
                    {"attempt_id": "attempt-a", "step_id": "step-a", "attempt_no": 1, "valid": True, "status": "SUCCEEDED"},
                    {"attempt_id": "attempt-b", "step_id": "step-b", "attempt_no": 1, "valid": True, "status": "SUCCEEDED"},
                ], "results": [
                    {"attempt_id": "attempt-a", "step_id": "step-a", "kind": "json", "state": "AVAILABLE"},
                    {"attempt_id": "attempt-b", "step_id": "step-b", "kind": "json", "state": "AVAILABLE"},
                ], "started_at": None,
            }
            async def call(operation, **kwargs):
                if operation == "run.list": return [run]
                if operation == "run.get": return run
                if operation == "environment.list": return []
                if operation == "task.list": return [{"task_id": "task-a", "name": "临时执行任务"}]
                raise AssertionError(operation)

            state = ExecutionPageState(run_id="run-a")
            panels = {}
            tab_labels = []
            tab_objects = {}
            from unittest.mock import patch
            original_tab_panels = ui.tab_panels
            original_tab = ui.tab
            def track_tab(*args, **kwargs):
                label = args[0] if args else kwargs.get("label")
                tab_labels.append(label)
                tab_objects[label] = original_tab(*args, **kwargs)
                return tab_objects[label]
            def track_tab_panels(*args, **kwargs):
                panels["default"] = kwargs.get("value")
                return original_tab_panels(*args, **kwargs)
            details = ExecutionDetails(
                SimpleNamespace(call=call), state,
                lambda title, callback, **kwargs: ui.button(title, on_click=callback),
                lambda: "executions", lambda: 1, *[AsyncMock() for _ in range(6)],
            )
            state.execution_rows = ui.column()
            state.execution_list_area = ui.column()
            with patch("taskweave.desktop.components.execution_details.ui.tab", side_effect=track_tab), \
                 patch("taskweave.desktop.components.execution_details.ui.tab_panels", side_effect=track_tab_panels):
                await details.render_rows()
            elements = list(ui.context.client.elements.values())
            self.assertEqual(tab_labels, ["执行详情", "历史记录"])
            self.assertIs(panels["default"], tab_objects["执行详情"])
            self.assertEqual(sum(getattr(element, "text", None) == "查看结果" for element in elements), 4)

        client = Client(page("/execution-result-tab-regression"))
        try:
            async def within_client():
                with client:
                    with ui.column():
                        await scenario()
            asyncio.run(within_client())
        finally:
            client.delete()

    def test_late_run_list_does_not_render_into_a_new_page(self):
        async def scenario():
            started, release = asyncio.Event(), asyncio.Event()
            controller = AsyncMock()

            async def list_runs():
                started.set()
                await release.wait()
                return []

            async def call(operation, **kwargs):
                if operation == "run.list":
                    return await list_runs()
                return None

            controller.call.side_effect = call
            page = ["executions"]
            generation = [1]
            state = ExecutionPageState()
            state.execution_rows = MagicMock()
            details = ExecutionDetails(
                controller, state, MagicMock(), lambda: page[0], lambda: generation[0],
                AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock(),
            )
            pending = asyncio.create_task(details.render_rows())
            await started.wait()
            page[0] = "tasks"
            generation[0] += 1
            release.set()
            await pending
            state.execution_rows.clear.assert_not_called()

        asyncio.run(scenario())


    def test_dispose_deletes_timers_owned_by_execution_details(self):
        from types import SimpleNamespace

        details = ExecutionDetails(
            AsyncMock(), ExecutionPageState(), MagicMock(), lambda: "executions", lambda: 1,
            AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock(),
        )
        timer = SimpleNamespace(is_deleted=False, delete=MagicMock())
        details.own_timer(timer)
        details.dispose()
        details.dispose()

        timer.delete.assert_called_once_with()
        self.assertEqual(details.timers, [])


    def test_selecting_step_only_changes_view_and_never_starts_execution(self):
        async def scenario():
            controller = AsyncMock()
            choose = AsyncMock()
            state = ExecutionPageState()
            details = ExecutionDetails(
                controller, state, MagicMock(), lambda: "executions", lambda: 1,
                AsyncMock(), choose, AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock(),
            )
            details.refresh = AsyncMock()
            await details.select_step("run-a", "step-b")
            self.assertEqual(state.run_id, "run-a")
            self.assertEqual(state.selected_step_id, "step-b")
            controller.call.assert_not_awaited()
            choose.assert_not_awaited()
            details.refresh.assert_awaited_once()
        asyncio.run(scenario())

    def test_step_selection_is_scoped_to_run_and_ignores_invalid_attempts(self):
        details = ExecutionDetails(
            AsyncMock(), ExecutionPageState(), MagicMock(), lambda: "executions", lambda: 1,
            AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock(),
        )
        steps = [{"step_id": "one"}, {"step_id": "two"}]
        run = {"run_id": "a", "attempts": [
            {"step_id": "one", "valid": 1, "status": "SUCCEEDED"},
            {"step_id": "two", "valid": 0, "status": "FAILED"},
        ]}
        self.assertEqual(details.selected_step(run, steps), "one")
        details.state.selected_step_run_id = "a"
        details.state.selected_step_id = "two"
        self.assertEqual(details.selected_step(run, steps), "two")
        run["run_id"] = "b"
        self.assertEqual(details.selected_step(run, steps), "one")

    def test_late_step_list_from_previous_run_does_not_replace_current_run_area(self):
        from types import SimpleNamespace
        from nicegui import ui

        async def scenario():
            started, release = asyncio.Event(), asyncio.Event()
            blocked = False

            def run(run_id):
                return {
                    "run_id": run_id, "mode": "EXECUTION", "task_id": run_id,
                    "environment_id": "env", "request_json": "{}", "definition_json": None,
                    "status": "READY", "attempts": [], "started_at": None,
                }

            async def call(operation, **kwargs):
                nonlocal blocked
                if operation == "run.list":
                    return [run("a"), run("b")]
                if operation == "run.get":
                    return run(kwargs["run_id"])
                if operation == "environment.list":
                    return []
                if operation == "task.list":
                    return [{"task_id": value, "name": value} for value in ("a", "b")]
                if operation == "step.list":
                    if kwargs["task_id"] == "a" and not blocked:
                        blocked = True
                        started.set()
                        await release.wait()
                    return [{"step_id": kwargs["task_id"] + "-step", "name": kwargs["task_id"] + " step"}]
                return None

            state = ExecutionPageState(run_id="a")
            with ui.column() as rows:
                pass
            state.execution_rows = rows
            details = ExecutionDetails(
                SimpleNamespace(call=call), state,
                lambda title, callback, **kwargs: ui.button(title, on_click=callback),
                lambda: "executions", lambda: 1, *[AsyncMock() for _ in range(6)],
            )

            pending_a = asyncio.create_task(details.render_rows())
            await started.wait()
            state.run_id = "b"
            state.signature = None
            await details.render_rows()
            b_area = state.run_area
            self.assertIsNotNone(b_area)

            release.set()
            await pending_a

            self.assertIs(state.run_area, b_area)
            self.assertFalse(b_area.is_deleted)

        asyncio.run(scenario())

    def test_selection_change_invalidates_a_pending_detail_render(self):
        from types import SimpleNamespace
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page

        async def scenario():
            started, release = asyncio.Event(), asyncio.Event()

            def run(run_id):
                return {
                    "run_id": run_id, "mode": "EXECUTION", "task_id": run_id,
                    "environment_id": "env", "request_json": "{}", "definition_json": None,
                    "status": "READY", "attempts": [], "started_at": None,
                }

            async def call(operation, **kwargs):
                if operation == "run.list": return [run("a"), run("b")]
                if operation == "run.get": return run(kwargs["run_id"])
                if operation == "environment.list": return []
                if operation == "task.list": return [{"task_id": value, "name": value} for value in ("a", "b")]
                if operation == "step.list":
                    if kwargs["task_id"] == "a":
                        started.set()
                        await release.wait()
                    return [{"step_id": kwargs["task_id"] + "-step", "name": kwargs["task_id"] + " step"}]
                return None

            state = ExecutionPageState(run_id="a")
            with ui.column() as rows:
                pass
            state.execution_rows = rows
            details = ExecutionDetails(
                SimpleNamespace(call=call), state,
                lambda title, callback, **kwargs: ui.button(title, on_click=callback),
                lambda: "executions", lambda: 1, *[AsyncMock() for _ in range(6)],
            )
            pending = asyncio.create_task(details.render_rows())
            await started.wait()
            state.run_id = "b"
            state.selected_step_run_id = "b"
            state.selected_step_id = "b-step"
            release.set()
            await pending
            self.assertIsNone(state.run_area)
            self.assertEqual(state.run_id, "b")

        client = Client(page("/execution-details-selection-stale"))
        try:
            async def within_client():
                with client:
                    await scenario()
            asyncio.run(within_client())
        finally:
            client.delete()

    def test_old_run_get_response_cannot_replace_newer_same_run_detail(self):
        from types import SimpleNamespace
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page

        async def scenario():
            old_started, release_old = asyncio.Event(), asyncio.Event()
            get_count = 0
            steps = [{"step_id": "one", "name": "one"}, {"step_id": "two", "name": "two"}]

            def run(status):
                return {"run_id": "r", "task_id": "t", "mode": "EXECUTION", "environment_id": "e",
                        "request_json": "{}", "definition_json": json.dumps({"steps": steps}),
                        "attempts": [], "status": status, "wait_until": None, "waiting_step_id": None,
                        "started_at": None, "results": []}

            async def call(operation, **kwargs):
                nonlocal get_count
                if operation == "run.list": return [run("READY")]
                if operation == "run.get":
                    get_count += 1
                    if get_count == 2:
                        old_started.set()
                        await release_old.wait()
                        return run("READY")
                    return run("SUCCEEDED")
                if operation == "environment.list": return []
                if operation == "task.list": return [{"task_id": "t", "name": "task"}]
                if operation == "run.events": return []
                raise AssertionError(operation)

            state = ExecutionPageState(run_id="r", selected_step_run_id="r", selected_step_id="one")
            with ui.column() as rows: pass
            state.execution_rows = rows
            details = ExecutionDetails(SimpleNamespace(call=call), state,
                lambda title, cb, **kw: ui.button(title, on_click=cb), lambda: "executions", lambda: 1,
                *[AsyncMock() for _ in range(6)])
            old_refresh = asyncio.create_task(details.refresh())
            await old_started.wait()
            await details.select_step("r", "two")
            committed_area, committed_signature = state.run_area, state.run_signature
            release_old.set()
            await old_refresh
            self.assertIs(state.run_area, committed_area)
            self.assertEqual(state.run_signature, committed_signature)
            self.assertIn("运行状态：成功", [getattr(el, "text", None) for el in state.run_area.descendants()])

        client = Client(page("/execution-details-refresh-generation"))
        try:
            async def within_client():
                with client:
                    await scenario()
            asyncio.run(within_client())
        finally:
            client.delete()

    def test_late_run_events_do_not_write_into_deleted_log_expansion(self):
        from types import SimpleNamespace
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page

        async def scenario():
            events_started, release_events = asyncio.Event(), asyncio.Event()
            get_count = 0
            steps = [{"step_id": "one", "name": "one"}, {"step_id": "two", "name": "two"}]

            def run(status):
                return {"run_id": "r", "task_id": "t", "mode": "EXECUTION", "environment_id": "e",
                        "request_json": "{}", "definition_json": json.dumps({"steps": steps}), "attempts": [],
                        "status": status, "wait_until": None, "waiting_step_id": None, "started_at": None,
                        "results": []}

            async def call(operation, **kwargs):
                nonlocal get_count
                if operation == "run.list": return [run("READY")]
                if operation == "run.get":
                    get_count += 1
                    return run("SUCCEEDED" if get_count > 1 else "READY")
                if operation == "run.events":
                    if not events_started.is_set():
                        events_started.set()
                        await release_events.wait()
                    return []
                if operation == "environment.list": return []
                if operation == "task.list": return [{"task_id": "t", "name": "task"}]
                raise AssertionError(operation)

            state = ExecutionPageState(run_id="r", selected_step_run_id="r", selected_step_id="one")
            with ui.column() as rows: pass
            state.execution_rows = rows
            details = ExecutionDetails(SimpleNamespace(call=call), state,
                lambda title, callback, **kwargs: ui.button(title, on_click=callback), lambda: "executions", lambda: 1,
                *[AsyncMock() for _ in range(6)])
            await details.refresh()
            root = ui.context.client.layout
            async def load():
                with root:
                    await details.load_run_logs()
            old_refresh = asyncio.create_task(load())
            await asyncio.wait_for(events_started.wait(), 2)
            await details.select_step("r", "two")
            release_events.set()
            await old_refresh

            orphaned_code = []
            for element in list(ui.context.client.elements.values()):
                if type(element).__name__ != "Code":
                    continue
                try:
                    parent = element.parent_slot.parent
                except RuntimeError as exc:
                    orphaned_code.append(str(exc))
                    continue
                if parent.is_deleted:
                    orphaned_code.append("deleted parent")
            self.assertEqual(orphaned_code, [])

        client = Client(page("/execution-details-late-events"))
        try:
            async def within_client():
                with client:
                    await scenario()
            asyncio.run(within_client())
        finally:
            client.delete()

    def test_dispose_invalidates_refresh_waiting_for_run_events(self):
        from types import SimpleNamespace
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page

        async def scenario():
            events_started, release_events = asyncio.Event(), asyncio.Event()
            run = {"run_id": "r", "task_id": "t", "mode": "EXECUTION", "environment_id": "e",
                   "request_json": "{}", "definition_json": json.dumps({"steps": [{"step_id": "one", "name": "one"}]}),
                   "attempts": [], "status": "SUCCEEDED", "wait_until": None, "waiting_step_id": None,
                   "started_at": None, "results": []}

            async def call(operation, **kwargs):
                if operation == "run.list": return [run]
                if operation == "run.get": return run
                if operation == "run.events":
                    events_started.set()
                    await release_events.wait()
                    return []
                if operation == "environment.list": return []
                if operation == "task.list": return [{"task_id": "t", "name": "task"}]
                raise AssertionError(operation)

            state = ExecutionPageState(run_id="r", selected_step_run_id="r", selected_step_id="one")
            with ui.column() as rows: pass
            state.execution_rows = rows
            details = ExecutionDetails(SimpleNamespace(call=call), state,
                lambda title, callback, **kwargs: ui.button(title, on_click=callback), lambda: "executions", lambda: 1,
                *[AsyncMock() for _ in range(6)])
            await details.refresh()
            root = ui.context.client.layout
            async def load():
                with root:
                    await details.load_run_logs()
            pending = asyncio.create_task(load())
            await asyncio.wait_for(events_started.wait(), 2)
            old_area = state.run_area
            details.dispose()
            rows.clear()
            release_events.set()
            await pending
            self.assertTrue(old_area.is_deleted)
            orphaned_code = []
            for element in list(ui.context.client.elements.values()):
                if type(element).__name__ != "Code":
                    continue
                try:
                    parent = element.parent_slot.parent
                except RuntimeError as exc:
                    orphaned_code.append(str(exc))
                    continue
                if parent.is_deleted:
                    orphaned_code.append("deleted parent")
            self.assertEqual(orphaned_code, [])

        client = Client(page("/execution-details-dispose-events"))
        try:
            async def within_client():
                with client:
                    await scenario()
            asyncio.run(within_client())
        finally:
            client.delete()

if __name__ == "__main__":
    unittest.main()
