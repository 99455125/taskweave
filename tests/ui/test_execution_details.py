"""Execution details discard refresh replies after leaving their page."""

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from taskweave.desktop.components.execution_details import ExecutionDetails
from taskweave.desktop.state import ExecutionPageState


class ExecutionDetailsTests(unittest.TestCase):
    def test_reconciliation_action_only_appears_for_reconcilable_run_states(self):
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page

        client = Client(page('/execution-reconciliation-states'))
        async def scenario():
            run = {'run_id': 'r', 'task_id': 't', 'status': 'INTERRUPTED',
                   'wait_until': None, 'waiting_step_id': None,
                   'definition_json': json.dumps({'steps': [{'step_id': 's', 'name': '超时步骤'}]}),
                   'attempts': [{'attempt_id': 'a', 'step_id': 's', 'attempt_no': 1,
                                 'valid': True, 'status': 'UNKNOWN', 'effect_state': 'UNKNOWN',
                                 'started_at': None, 'finished_at': None,
                                 'error_code': 'WORKER_TIMEOUT', 'error_summary': ''}], 'results': []}
            async def call(operation, **kwargs):
                if operation == 'run.get': return run
                raise AssertionError(operation)
            with client:
                state = ExecutionPageState(run_id='r', execution_rows=ui.column(), run_area=ui.column())
                details = ExecutionDetails(SimpleNamespace(call=call), state,
                    lambda title, callback, **kwargs: ui.button(title, on_click=callback),
                    lambda: 'executions', lambda: 1, *[AsyncMock() for _ in range(6)])
                details.render_rows = AsyncMock()
                for status, expected in [('INTERRUPTED', True), ('FAILED', True),
                                         ('CANCELLED', False), ('SUCCEEDED', False)]:
                    run['status'] = status
                    await details.refresh()
                    actions = [el for el in state.run_area.descendants()
                               if isinstance(el, ui.button) and el.text == '核对外部业务结果']
                    self.assertEqual(bool(actions), expected, status)
                details.dispose()
        try:
            asyncio.run(scenario())
        finally:
            client.delete()

    def test_reused_page_polling_survives_dispose_and_preserves_hidden_document(self):
        async def scenario():
            details = ExecutionDetails(MagicMock(), ExecutionPageState(), MagicMock(),
                lambda: 'executions', lambda: 1, *[AsyncMock() for _ in range(6)])
            details.refresh = AsyncMock()
            # Workbench.paint disposes the reusable page before rendering it.
            details.dispose()
            await details.poll()
            details.refresh.assert_awaited_once_with(force=False)
            details.set_visible(False)
            details.dispose()
            await details.poll()
            self.assertEqual(details.refresh.await_count, 1)
            details.set_visible(True)
            await details.poll()
            self.assertEqual(details.refresh.await_count, 2)
        asyncio.run(scenario())

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
                if operation == 'sequence.run.list': return []
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
                    tabs = next(el for el in client.elements.values() if isinstance(el, ui.tabs))
                    self.assertFalse(host.visible)
                    tabs.set_value('logs')
                    self.assertTrue(host.visible)
                    await viewer.toggle()
                    previous = viewer.output.value
                    app.runs.runs.event(a['run_id'], 'Changed', {'message': 'new event'})
                    await details.refresh(force=False)
                    self.assertIs(details._live_logs, viewer)
                    self.assertIs(details._logs_host, host)
                    self.assertEqual(viewer.output.value, previous)
                    tabs = next(el for el in client.elements.values() if isinstance(el, ui.tabs))
                    self.assertEqual(tabs.value, 'logs')
                    tabs.set_value('inputs')
                    self.assertFalse(host.visible)
                    self.assertFalse(viewer.allowed())
                    await details.select_run(b['run_id'])
                    self.assertTrue(viewer.timer.is_deleted)
                    self.assertIsNot(details._live_logs, viewer)
                    self.assertEqual(details._live_logs.run_id, b['run_id'])
                    tabs = next(el for el in client.elements.values() if isinstance(el, ui.tabs))
                    self.assertEqual(tabs.value, 'progress')
                    await details.select_run(a['run_id'])
                    tabs = next(el for el in client.elements.values() if isinstance(el, ui.tabs))
                    self.assertEqual(tabs.value, 'inputs')
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

    def test_execution_sections_keep_frozen_snapshot_redacted_inputs_and_attempt_results(self):
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page

        async def scenario():
            run = {
                "run_id": "run-a", "mode": "EXECUTION", "task_id": "task-a", "environment_id": None,
                "request_json": "{}", "input_summary_json": '{"token":"[REDACTED]"}',
                "inputs_json": '{"token":"never-render-raw-secret"}',
                "definition_json": json.dumps({"task": {"name": "冻结时的任务名称", "description": "冻结的任务说明"}, "steps": [
                    {"step_id": "step-a", "name": "步骤一：长中文结果标题验收", "step_content": "frozen_step_code",
                     "step_description": "冻结的步骤描述", "step_notes": "冻结的步骤说明"},
                    {"step_id": "step-b", "name": "步骤二：审核说明与结果引用"},
                ]}), "status": "SUCCEEDED", "attempts": [
                    {"attempt_id": "attempt-a", "step_id": "step-a", "attempt_no": 1, "valid": True, "status": "SUCCEEDED"},
                    {"attempt_id": "attempt-b", "step_id": "step-b", "attempt_no": 1, "valid": True, "status": "SUCCEEDED"},
                ], "results": [
                    {"attempt_id": "attempt-a", "step_id": "step-a", "kind": "json", "state": "AVAILABLE"},
                    {"attempt_id": "attempt-b", "step_id": "step-b", "kind": "json", "state": "AVAILABLE"},
                ], "started_at": None,
            }
            run['attempts'].insert(0, {"attempt_id": "attempt-old", "step_id": "step-a", "attempt_no": 0,
                                      "valid": False, "status": "SUCCEEDED"})
            run['results'].append({"attempt_id": "attempt-old", "step_id": "step-a", "kind": "json", "state": "AVAILABLE"})
            run['results'].append({"attempt_id": "attempt-a", "step_id": "step-a", "kind": "json", "state": "FUTURE_STATE", "media_type": "application/json"})
            queries, opened = [], []
            async def open_result(source, step, attempt_id=None):
                opened.append((source['run_id'], step['step_id'], attempt_id))
            async def call(operation, **kwargs):
                queries.append(operation)
                if operation == "sequence.run.list": return []
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
                label = kwargs.get("label") or (args[0] if args else None)
                tab_labels.append(label)
                tab_objects[label] = original_tab(*args, **kwargs)
                return tab_objects[label]
            def track_tab_panels(*args, **kwargs):
                panels["default"] = kwargs.get("value")
                return original_tab_panels(*args, **kwargs)
            details = ExecutionDetails(
                SimpleNamespace(call=call), state,
                lambda title, callback, **kwargs: ui.button(title, on_click=callback),
                lambda: "executions", lambda: 1,
                AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock(), open_result, AsyncMock(),
            )
            state.execution_rows = ui.column()
            state.execution_list_area = ui.column()
            with patch("taskweave.desktop.components.execution_details.ui.tab", side_effect=track_tab), \
                 patch("taskweave.desktop.components.execution_details.ui.tab_panels", side_effect=track_tab_panels):
                await details.render_rows()
            elements = list(ui.context.client.elements.values())
            self.assertEqual(tab_labels, ["执行进度", "日志", "结果", "输入", "执行快照"])
            result_panel = next(el for el in elements if isinstance(el, ui.tab_panel) and el.props['name'] == 'results')
            input_panel = next(el for el in elements if isinstance(el, ui.tab_panel) and el.props['name'] == 'inputs')
            snapshot_panel = next(el for el in elements if isinstance(el, ui.tab_panel) and el.props['name'] == 'snapshot')
            result_buttons = [el for el in result_panel.descendants() if isinstance(el, ui.button) and el.text == '查看结果']
            self.assertEqual(len(result_buttons), 2)
            for button in result_buttons:
                handler = next(event.handler for event in button._event_listeners.values() if event.type == 'click')
                await handler()
            self.assertEqual(opened, [('run-a', 'step-a', 'attempt-a'), ('run-a', 'step-b', 'attempt-b')])
            self.assertEqual(set(queries), {'run.list', 'sequence.run.list', 'run.get', 'environment.list', 'task.list'})
            self.assertIn('[REDACTED]', ''.join(str(getattr(el, 'content', '')) for el in input_panel.descendants()))
            self.assertNotIn('never-render-raw-secret', ''.join(str(getattr(el, 'content', '')) for el in elements))
            snapshot_elements = list(snapshot_panel.descendants())
            self.assertIn('冻结时的任务名称', [getattr(el, 'text', None) for el in snapshot_elements])
            self.assertNotIn('临时执行任务', [getattr(el, 'text', None) for el in snapshot_elements])
            raw = next(el for el in snapshot_elements if isinstance(el, ui.expansion) and el.props.get('label') == '完整原始定义')
            self.assertFalse(raw.value)
            self.assertEqual(next(el.content for el in raw.descendants() if isinstance(el, ui.code)), run['definition_json'])
            frozen_step = next(el for el in snapshot_elements if isinstance(el, ui.expansion) and '长中文结果标题' in el.props.get('label', ''))
            self.assertEqual(next(el.content for el in frozen_step.descendants() if isinstance(el, ui.code)), 'frozen_step_code')
            self.assertIn('冻结的步骤说明', [getattr(el, 'text', None) for el in frozen_step.descendants()])
            history = next(el for el in elements if isinstance(el, ui.expansion) and el.props.get('label') == '历史尝试')
            for container in (result_panel, history):
                summaries = [getattr(el, 'text', '') for el in container.descendants()]
                self.assertTrue(any('json · 可查看' in text for text in summaries))
                self.assertTrue(any('FUTURE_STATE' in text for text in summaries))
                self.assertFalse(any(' · AVAILABLE' in text for text in summaries))

        client = Client(page("/execution-result-tab-regression"))
        try:
            async def within_client():
                from unittest.mock import patch
                def capture_click(button, callback):
                    button.on('click', callback)
                    return button
                with client, patch.object(ui.button, 'on_click', capture_click):
                    with ui.column():
                        await scenario()
            asyncio.run(within_client())
        finally:
            client.delete()

    def test_delete_confirmation_cancel_and_accept_keep_original_run_identity(self):
        import tempfile
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page
        from taskweave.application.service import Application
        from taskweave.desktop.controller import DesktopController

        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task('确认删除测试')['task_id']
            step = app.repo.save_step(task, {'name': 'first',
                'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data=None)'})
            app.confirm_step_manual(step['step_id'], step['content_hash'])
            first, second = app.create_run(task), app.create_run(task)
            client = Client(page('/execution-delete-confirmation'))
            callbacks = {}

            def button(title, callback, **kwargs):
                callbacks[title] = callback
                return ui.button(title, on_click=callback)

            async def scenario():
                with client:
                    state = ExecutionPageState(run_id=first['run_id'], execution_rows=ui.column(), execution_list_area=ui.column())
                    details = ExecutionDetails(DesktopController(app), state, button,
                        lambda: 'executions', lambda: 1, *[AsyncMock() for _ in range(6)])
                    await details.refresh()

                    async def decide(label, change_selection=False):
                        async def open_dialog():
                            with client:
                                await callbacks['删除执行']()
                        pending = asyncio.create_task(open_dialog())
                        await asyncio.sleep(0)
                        dialog = next(el for el in client.elements.values() if isinstance(el, ui.dialog) and el.value)
                        if change_selection:
                            state.run_id = second['run_id']
                        control = next(el for el in dialog.descendants() if isinstance(el, ui.button) and el.text == label)
                        next(event.handler for event in control._event_listeners.values() if event.type == 'click')(None)
                        await pending

                    await decide('取消')
                    self.assertEqual({row['run_id'] for row in app.repo.list_runs()}, {first['run_id'], second['run_id']})
                    self.assertEqual(state.run_id, first['run_id'])
                    await decide('确认删除执行', change_selection=True)
                    self.assertEqual([row['run_id'] for row in app.repo.list_runs()], [second['run_id']])
                    self.assertEqual(state.run_id, second['run_id'])
                    details.dispose()
            try:
                asyncio.run(scenario())
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
                if operation == "sequence.run.list": return []
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
        from nicegui.client import Client
        from nicegui.page import page

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
                if operation == "sequence.run.list": return []
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

        client = Client(page('/execution-details-late-step-list'))
        try:
            async def within_client():
                with client:
                    await scenario()
            asyncio.run(within_client())
        finally:
            client.delete()

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
                if operation == "sequence.run.list": return []
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
                if operation == "sequence.run.list": return []
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
                if operation == "sequence.run.list": return []
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
                if operation == "sequence.run.list": return []
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

class ExecutionFlowCanvasTests(unittest.TestCase):
    def setUp(self):
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page
        # Geometry is verified in the browser; these component tests have no socket/event loop.
        javascript = patch('nicegui.ui.run_javascript')
        javascript.start()
        self.addCleanup(javascript.stop)
        self.client = Client(page('/execution-flow-canvas'))
        self.steps = [{'step_id': 'a', 'name': '快照查询'}, {'step_id': 'b', 'name': '快照更新'}]
        self.run = {'run_id': 'history-run', 'definition_json': json.dumps({'steps': self.steps}),
                    'attempts': [], 'flow_instances': []}
        self.errors, self.results, self.selected = [], [], []
        self.details = ExecutionDetails(SimpleNamespace(), ExecutionPageState(),
            lambda title, callback, **kw: ui.button(title, on_click=callback),
            lambda: 'executions', lambda: 1, None, None, None,
            lambda *args: self.errors.append(args), lambda *args: self.results.append(args), None)
        self.details.select_step = lambda *args: self.selected.append(args)

    def tearDown(self):
        self.client.delete()

    def render(self, flow=None):
        if flow is not None:
            self.run['definition_json'] = json.dumps({'steps': self.steps, 'flow': flow})
        with self.client:
            self.details.render_progress(self.run, self.steps)
        return list(self.client.elements.values())

    @staticmethod
    def click(element):
        next(iter(element._event_listeners.values())).handler(None)

    def test_historical_steps_use_shared_canvas_and_keep_result_error_and_selection_identity(self):
        self.run['attempts'] = [
            {'attempt_id': 'obsolete', 'step_id': 'a', 'valid': False, 'status': 'FAILED'},
            {'attempt_id': 'ok', 'step_id': 'a', 'valid': True, 'status': 'SUCCEEDED'},
            {'attempt_id': 'bad', 'step_id': 'b', 'valid': True, 'status': 'FAILED'}]
        elements = self.render()
        self.assertTrue(any('tw-flow-canvas' in e.classes for e in elements))
        self.assertEqual(sum('tw-flow-connector' in e.classes for e in elements), 3)
        names = [e for e in elements if 'tw-flow-node-title' in e.classes]
        self.assertEqual([e.text for e in names], ['快照查询', '快照更新'])
        self.click(names[1])
        self.click(next(e for e in elements if getattr(e, 'text', '') == '查看结果'))
        self.click(next(e for e in elements if getattr(e, 'text', '') == '查看错误'))
        self.assertEqual(self.selected, [('history-run', 'b')])
        self.assertEqual(self.results, [(self.run, self.steps[0])])
        self.assertEqual(self.errors, [(self.run['attempts'][2], self.steps[1])])
        self.assertFalse(any('tw-flow-menu' in e.classes for e in elements))

    def test_snapshot_flow_order_wins_over_step_list_order(self):
        flow = {'version': 2, 'root': {'id': 'root', 'kind': 'sequence', 'children': [
            {'id': 'node-b', 'kind': 'action', 'step_id': 'b'},
            {'id': 'node-a', 'kind': 'action', 'step_id': 'a'}]}}
        elements = self.render(flow)
        self.assertEqual([e.text for e in elements if 'tw-flow-node-title' in e.classes],
                         ['快照更新', '快照查询'])

    def test_failure_highlights_only_reached_edges(self):
        self.run['status'] = 'FAILED'
        self.run['attempts'] = [{'attempt_id': 'failed', 'step_id': 'a', 'valid': True, 'status': 'FAILED'}]
        elements = self.render()
        edges = [e for e in elements if 'tw-flow-connector' in e.classes]
        self.assertIn('is-path-taken', edges[0].classes)
        self.assertNotIn('is-path-taken', edges[1].classes)
        self.assertNotIn('is-path-taken', edges[2].classes)

    def test_round_view_changes_branch_marks_and_keeps_exact_result_and_error_attempts(self):
        from nicegui import ui
        flow = {'version': 2, 'root': {'id': 'root', 'kind': 'sequence', 'children': [{
            'id': 'each', 'kind': 'foreach', 'items': {'literal': [1, 2]},
            'body': {'id': 'body', 'kind': 'sequence', 'children': [{
                'id': 'gate', 'kind': 'if', 'cases': [{'id': 'then',
                'condition': {'op': 'eq', 'left': {'literal': 1}, 'right': {'literal': 1}},
                'body': {'id': 'yes', 'kind': 'sequence', 'children': [
                    {'id': 'a', 'kind': 'action', 'step_id': 'a'}]}}],
                'default': {'id': 'else', 'body': {'id': 'no', 'kind': 'sequence', 'children': [
                    {'id': 'b', 'kind': 'action', 'step_id': 'b'}]}}}]}}]}}
        self.run['status'] = 'FAILED'
        self.run['flow_instances'] = [
            {'node_id': 'each', 'kind': 'foreach', 'status': 'RUNNING', 'execution_path': '/root/each',
             'payload_json': '{"items": [1, 2]}'},
            {'node_id': 'gate', 'kind': 'if', 'status': 'SUCCEEDED', 'execution_path': '/root/each/0/body/gate',
             'payload_json': '{"selected": ["then"]}'},
            {'node_id': 'gate', 'kind': 'if', 'status': 'RUNNING', 'execution_path': '/root/each/1/body/gate',
             'payload_json': '{"selected": ["else"]}'}]
        self.run['attempts'] = [
            {'attempt_id': 'round-ok', 'step_id': 'a', 'valid': True, 'status': 'SUCCEEDED',
             'execution_path': '/root/each/0/body/gate/then/yes/a'},
            {'attempt_id': 'round-fail', 'step_id': 'b', 'valid': True, 'status': 'FAILED',
             'execution_path': '/root/each/1/body/gate/else/no/b'}]
        elements = self.render(flow)
        selector = next(e for e in elements if isinstance(e, ui.select) and e._props.get('label') == '路径轮次')
        with self.client:
            selector.set_value('/root/each/0')
        elements = list(self.client.elements.values())
        no = next(e for e in elements if e._props.get('data-branch-id') == 'no')
        self.assertEqual(no._props['data-path-state'], 'skipped')
        self.assertTrue(any('tw-flow-path-overlay' in e.classes for e in elements))
        self.assertIn('未命中', [getattr(e, 'text', '') for e in no.descendants()])
        self.click(next(e for e in elements if getattr(e, 'text', '') == '查看结果'))
        self.assertEqual(self.results[-1], (self.run, self.steps[0], 'round-ok'))
        with self.client:
            selector.set_value('/root/each/1')
        elements = list(self.client.elements.values())
        yes = next(e for e in elements if e._props.get('data-branch-id') == 'yes')
        no = next(e for e in elements if e._props.get('data-branch-id') == 'no')
        self.assertEqual(yes._props['data-path-state'], 'skipped')
        self.assertEqual(no._props['data-path-state'], 'taken')
        self.assertNotIn('is-path-exited', no.classes)
        self.click(next(e for e in elements if getattr(e, 'text', '') == '查看错误'))
        self.assertEqual(self.errors[-1], (self.run['attempts'][1], self.steps[1]))
        self.assertEqual(self.details._path_scopes[self.run['run_id']], '/root/each/1')

    def test_unknown_and_pending_states_and_selected_step_remain_distinct(self):
        self.run['attempts'] = [{'attempt_id': 'unknown', 'step_id': 'a', 'valid': True, 'status': 'UNKNOWN'}]
        self.details.state.selected_step_run_id = self.run['run_id']
        self.details.state.selected_step_id = 'b'
        elements = self.render()
        cards = [e for e in elements if 'tw-flow-node' in e.classes]
        self.assertIn('is-unknown', cards[0].classes)
        self.assertIn('is-pending', cards[1].classes)
        self.assertIn('is-selected', cards[1].classes)
        self.assertNotIn('is-selected', cards[0].classes)
        self.assertIn('尚未执行', [getattr(e, 'text', '') for e in cards[1].descendants()])

    def test_each_loop_round_result_keeps_its_attempt_identity(self):
        flow = {'version': 2, 'root': {'id': 'root', 'kind': 'sequence', 'children': [{
            'id': 'repeat', 'kind': 'foreach', 'items': {'literal': [1, 2]},
            'body': {'id': 'body', 'kind': 'sequence', 'children': [
                {'id': 'node-a', 'kind': 'action', 'step_id': 'a'},
                {'id': 'node-b', 'kind': 'action', 'step_id': 'b'}]}}]}}
        self.run['attempts'] = [
            {'attempt_id': f'round-{i}', 'step_id': 'a', 'valid': True, 'status': 'SUCCEEDED'}
            for i in (1, 2)]
        self.run['flow_instances'] = [
            {'kind': 'action', 'node_id': 'a', 'attempt_id': f'round-{i}', 'status': 'SUCCEEDED',
             'execution_path': f'root/repeat/{i - 1}/a', 'payload_json': '{}'} for i in (1, 2)]
        elements = self.render(flow)
        buttons = [e for e in elements if getattr(e, 'text', '') == '查看本轮结果']
        self.assertEqual(len(buttons), 2)
        for button in buttons:
            self.click(button)
        self.assertEqual(self.results, [(self.run, self.steps[0], 'round-1'),
                                       (self.run, self.steps[0], 'round-2')])

    def test_branch_and_loop_paths_are_read_only_and_round_status_is_explicit(self):
        flow = {'version': 2, 'root': {'id': 'root', 'kind': 'sequence', 'children': [{
            'id': 'gate', 'kind': 'if', 'cases': [{'id': 'then',
            'condition': {'op': 'eq', 'left': {'literal': 1}, 'right': {'literal': 1}},
            'body': {'id': 'yes', 'kind': 'sequence', 'children': [{
                'id': 'repeat', 'kind': 'loop', 'mode': 'while', 'max_iterations': 2,
                'condition': {'op': 'eq', 'left': {'literal': 1}, 'right': {'literal': 1}},
                'body': {'id': 'body', 'kind': 'sequence', 'children': [
                    {'id': 'node-a', 'kind': 'action', 'step_id': 'a'}]}}]}}],
            'default': {'id': 'else', 'body': {'id': 'no', 'kind': 'sequence', 'children': [
                {'id': 'node-b', 'kind': 'action', 'step_id': 'b'}]}}}]}}
        self.run['attempts'] = [
            {'attempt_id': 'round-1', 'step_id': 'a', 'valid': True, 'status': 'SUCCEEDED'},
            {'attempt_id': 'round-2', 'step_id': 'a', 'valid': True, 'status': 'FAILED'}]
        elements = self.render(flow)
        texts = [getattr(e, 'text', '') for e in elements]
        for text in ('分支 1', '否则', '条件循环', '继续循环', '尚未执行', '流程路径与逐轮结果'):
            self.assertIn(text, texts)
        self.assertIn('最近一次：失败 · 有效尝试 2 次', texts)
        self.assertTrue(any('tw-flow-return' in e.classes for e in elements))
        self.assertFalse(any('tw-flow-menu' in e.classes for e in elements))
        self.assertFalse(any(str(e._props.get('aria-label', '')).startswith('配置') for e in elements))


if __name__ == "__main__":
    unittest.main()
