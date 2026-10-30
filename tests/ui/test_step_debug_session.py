"""Debug session actions cannot attach late runs to another editor."""

import asyncio
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from taskweave.desktop.components.step_debug import StepDebugPanel, StepDebugSession
from taskweave.application.service import Application
from taskweave.desktop.controller import DesktopController
from taskweave.desktop.state import DebugState
from taskweave.desktop.workbench import Workbench


def input_draft(values=None, environment_id=None):
    from taskweave.presentation.debug import TrialInputDraft
    draft = TrialInputDraft()
    draft.task.configure({'properties': {key: {'type': 'integer' if isinstance(value, int) else 'string'} for key, value in (values or {}).items()}}, values or {})
    draft.step.configure({'properties': {}}, {})
    draft.set_environment(environment_id)
    return draft


class StepDebugSessionTests(unittest.TestCase):
    def test_real_local_debug_entry_and_trial_submission(self):
        with tempfile.TemporaryDirectory() as home, Application(
            home, registry_factory="tests.test_context_targets_runtime:build_registry"
        ) as app:
            task_id = app.repo.create_task("本地调试入口")['task_id']
            step = app.repo.save_step(task_id, {
                "name": "本地步骤", "step_content": "async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n",
                "capabilities": ["demo.echo"],
            })
            controller = DesktopController(app)
            identity = (task_id, step['step_id'], 0, 1)
            trials, events = {}, []
            form = SimpleNamespace(input_draft=input_draft())
            session = StepDebugSession(
                controller=controller, identity=lambda: identity, task_id=lambda: task_id,
                save_editor=AsyncMock(return_value=step), trial_form=lambda: form,
                trial_environment=lambda: SimpleNamespace(value=None), environment_select=AsyncMock(),
                trial_variables=AsyncMock(), trials=trials, button=AsyncMock(),
                confirm_end=AsyncMock(), resume_inputs=AsyncMock(),
                refresh_trial=AsyncMock(side_effect=lambda: events.append("refresh")),
                refresh_trial_inputs=AsyncMock(), update_environment=AsyncMock(),
                reset_feedback=MagicMock(), trial_start_status=lambda: None, debug_state=form.input_draft.state,
            )
            async def scenario():
                await session.enter_debug()
                await session.start_trial(continue_session=True)
                run_id = trials[step['step_id']]
                await asyncio.to_thread(app.coordinator.wait, run_id)
                self.assertEqual(app.dispatch("run.get", {"run_id": run_id})['status'], "SUCCEEDED")
                self.assertEqual(app.dispatch("run.list", {"task_id": task_id})[0]['mode'], "TRIAL")
            asyncio.run(scenario())

    def test_session_owns_enter_debug_and_trial_start_settlement(self):
        async def scenario():
            identity = ["task", "step", 2, 3]
            status = SimpleNamespace(is_deleted=False, text="")
            state = DebugState(supplements={"step":"keep me"}, trial_signature="old")
            events = []
            controller = SimpleNamespace(
                call=AsyncMock(side_effect=[
                    {"status":"SUCCEEDED", "attempts":[]},
                    {"waiting_input":None},
                ]),
                reset_debug_conversation=MagicMock(side_effect=lambda step: events.append(("reset", step))),
                run_request=AsyncMock(return_value={"waiting_input":None}),
            )
            session = StepDebugSession(
                controller=controller, identity=lambda: tuple(identity), task_id=lambda: "task",
                save_editor=AsyncMock(return_value={"step_id":"step"}),
                trial_form=lambda: None, trial_environment=lambda: None,
                environment_select=AsyncMock(), trial_variables=AsyncMock(), trials={"step":"run-1"}, button=AsyncMock(),
                confirm_end=AsyncMock(), resume_inputs=AsyncMock(), refresh_trial=AsyncMock(side_effect=lambda: events.append(("refresh",))),
                update_environment=AsyncMock(), reset_feedback=AsyncMock(),
                trial_start_status=lambda: status, debug_state=state,
                refresh_trial_inputs=AsyncMock(side_effect=lambda step: events.append(("refresh_inputs", step))),
            )
            await session.enter_debug()
            self.assertEqual(events, [("refresh_inputs", {"step_id":"step"}), ("reset", "step"), ("refresh",)])
            self.assertTrue(state.fresh_round)
            self.assertIsNone(state.feedback)
            self.assertIsNone(state.feedback_run_id)
            self.assertEqual(state.removed_feedback, set())
            self.assertNotIn("step", state.supplements)

            await session.settle_trial_start("run-1", timeout=0.02)
            self.assertIsNone(state.trial_signature)
            self.assertEqual(status.text, "")
            self.assertEqual(controller.call.await_args_list[0].args[0], "run.get")
            controller.run_request.assert_awaited_once_with("run-1")
            self.assertEqual(session.refresh_trial.await_count, 2)
        asyncio.run(scenario())

    def test_session_settlement_ignores_stale_run_and_editor(self):
        async def scenario():
            entered, release = asyncio.Event(), asyncio.Event()
            identity = ["task", "step-a", 2, 3]
            status = SimpleNamespace(is_deleted=False, text="waiting")
            state = DebugState(trial_signature="old")
            async def get_run(*_args, **_kwargs):
                entered.set()
                await release.wait()
                return {"status":"RUNNING", "attempts":[]}
            controller = SimpleNamespace(call=get_run, run_request=AsyncMock(return_value={"waiting_input":None}))
            session = StepDebugSession(
                controller=controller, identity=lambda: tuple(identity), task_id=lambda: "task",
                save_editor=AsyncMock(), trial_form=lambda: None, trial_environment=lambda: None,
                environment_select=AsyncMock(), trial_variables=AsyncMock(), trials={"step-a":"run-a"}, button=AsyncMock(),
                confirm_end=AsyncMock(), resume_inputs=AsyncMock(), refresh_trial=AsyncMock(), refresh_trial_inputs=AsyncMock(),
                update_environment=AsyncMock(), reset_feedback=AsyncMock(),
                trial_start_status=lambda: status, debug_state=state,
            )
            pending = asyncio.create_task(session.settle_trial_start("run-a", timeout=0.02))
            await entered.wait()
            identity[:] = ["task", "step-b", 3, 4]
            release.set()
            await pending
            controller.run_request.assert_not_awaited()
            session.refresh_trial.assert_not_awaited()
            self.assertEqual(state.trial_signature, "old")
        asyncio.run(scenario())

    def test_workbench_sync_environment_callback_keeps_started_repeat_tracked(self):
        async def scenario():
            controller = SimpleNamespace(
                call=AsyncMock(return_value={"run_id":"previous", "environment_id":"uat", "can_end":True, "status":"SUCCEEDED", "attempts":[]}),
                run_request=AsyncMock(return_value={}),
                repeat_trial=AsyncMock(return_value={"run_id":"new-run"}),
                trial=AsyncMock(),
                plugin_contributions=MagicMock(return_value=[]),
                reset_debug_conversation=MagicMock(),
            )
            with patch("taskweave.desktop.workbench.ui", MagicMock()):
                workbench = Workbench(controller)
            workbench.page = "editor"
            workbench.page_generation = 1
            workbench.task_id, workbench.step_id = "task", "step"
            workbench.step_state.task_id, workbench.step_state.step_id = "task", "step"
            workbench.trials["step"] = "previous"
            form = SimpleNamespace(input_draft=input_draft({"x":1}, "uat"))
            environment = SimpleNamespace(value="uat")
            workbench.step_debug_session.save_editor = AsyncMock(return_value={"step_id":"step"})
            form.input_draft.bind(workbench.step_debug_session.debug_state, ("task", "step"))
            workbench.step_editor.view.update(trial_form=form, trial_environment=environment)
            workbench.step_debug_session.settle_trial_start = AsyncMock()
            self.assertIs(workbench.step_debug_session.trial_environment(), environment)
            await workbench.step_debug_session.start_trial(continue_session=True)
            controller.repeat_trial.assert_awaited_once()
            self.assertEqual(workbench.environment_id, "uat")
            self.assertEqual(workbench.trials["step"], "new-run")
            self.assertEqual(workbench.step_ai_editor.trials.get("step"), "new-run")
            self.assertEqual(workbench.step_debug_panel.trials.get("step"), "new-run")
            workbench.step_debug_session.settle_trial_start.assert_awaited_once_with("new-run")
            controller.repeat_trial.assert_awaited_once_with({"step_id":"step"}, "previous", overrides={"x":1})

        asyncio.run(scenario())

    def test_workbench_empty_trial_mapping_is_shared_with_run_recovery_panel(self):
        async def scenario():
            run = {"run_id":"restored-run", "status":"SUCCEEDED", "can_end":False, "request_json":"{}", "attempts":[], "results":[]}
            controller = SimpleNamespace(
                call=AsyncMock(side_effect=[
                    [{"run_id":"restored-run", "trial_step_id":"step", "status":"SUCCEEDED"}],
                    run,
                    [],
                    [],
                ]),
                plugin_contributions=MagicMock(return_value=[]),
                reset_debug_conversation=MagicMock(),
            )
            with patch("taskweave.desktop.workbench.ui", MagicMock()):
                workbench = Workbench(controller)
            workbench.page = "editor"
            workbench.page_generation = 1
            workbench.task_id, workbench.step_id = "task", "step"
            workbench.step_state.task_id, workbench.step_state.step_id = "task", "step"
            workbench.edit_controls = {"code": object()}
            workbench.step_debug_panel.trial_area = MagicMock(is_deleted=False)
            workbench.step_debug_panel.trial_area.__enter__ = MagicMock(return_value=workbench.step_debug_panel.trial_area)
            workbench.step_debug_panel.trial_area.__exit__ = MagicMock(return_value=False)
            workbench.step_debug_panel.logs_area = MagicMock(is_deleted=False)
            workbench.step_debug_panel.pending_inputs = AsyncMock()
            self.assertIs(workbench.step_debug_panel.trials, workbench.trials)
            with patch("taskweave.desktop.components.step_debug.ui", MagicMock()), \
                    patch("taskweave.desktop.components.step_debug.LiveRunLogs", MagicMock()):
                await workbench.step_debug_panel.refresh_trial()
            self.assertEqual(workbench.trials, {"step":"restored-run"})
            self.assertEqual([call.args[0] for call in controller.call.await_args_list], ["run.list", "run.get", "step.list"])

        asyncio.run(scenario())

    def test_history_choices_filter_step_and_show_frozen_code_without_overwrite(self):
        import json
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page
        client = Client(page('/debug-history-choices'))
        async def scenario():
            with client:
                identity = ('task', 'step', 0, 0)
                rows = [
                    {'run_id': 'older', 'trial_step_id': 'step', 'status': 'FAILED', 'started_at': '2026-10-23T01:00:00Z'},
                    {'run_id': 'other-step', 'trial_step_id': 'other', 'status': 'FAILED', 'started_at': ''},
                    {'run_id': 'formal', 'trial_step_id': None, 'status': 'SUCCEEDED', 'started_at': ''},
                    {'run_id': 'latest', 'trial_step_id': 'step', 'status': 'SUCCEEDED', 'started_at': '2026-10-24T01:00:00Z'}]
                controller = SimpleNamespace(call=AsyncMock(return_value=rows))
                code = ui.textarea(value='unsaved draft')
                panel = StepDebugPanel(MagicMock(), controller, lambda: identity, lambda _: 'latest', lambda: None,
                    page=lambda: 'editor', edit_controls=lambda: {'code': code}, state=DebugState())
                panel.history_control = ui.select({})
                run = {'run_id': 'latest', 'status': 'SUCCEEDED', 'definition_hash': 'actual-hash',
                       'definition_json': json.dumps({'steps': [{'step_id': 'step', 'step_content': 'frozen source'}]})}
                await panel.refresh_history_options(identity, run)
                self.assertEqual(list(panel.history_control.options), ['latest', 'older'])
                self.assertEqual(panel.history_control.value, 'latest')
                await panel.refresh_history_options(identity, run)
                controller.call.assert_awaited_once_with('run.list', task_id='task')
                panel.render_execution_baseline(run, 'step')
                self.assertTrue(any(isinstance(e, ui.code) and e.content == 'frozen source' for e in client.elements.values()))
                self.assertEqual(code.value, 'unsaved draft')
        try:
            asyncio.run(scenario())
        finally:
            client.delete()

    def test_history_selection_preserves_draft_and_uses_existing_run_only(self):
        async def scenario():
            identity = ('task', 'step', 0, 0)
            trials = {'step': 'latest'}
            code = SimpleNamespace(value='unsaved draft')
            controller = SimpleNamespace(call=AsyncMock(return_value={'task_id': 'task', 'trial_step_id': 'step', 'run_id': 'older'}))
            state = DebugState(feedback={'attempt_id': 'latest-attempt'}, feedback_run_id='latest', removed_feedback={'failed_action'})
            panel = StepDebugPanel(MagicMock(), controller, lambda: identity, lambda key: trials.get(key), lambda: None,
                page=lambda: 'editor', edit_controls=lambda: {'code': code}, trials=trials, state=state)
            panel.refresh_trial = AsyncMock()
            await panel.select_history_run('older')
            self.assertEqual(trials['step'], 'older')
            self.assertEqual(code.value, 'unsaved draft')
            self.assertIsNone(state.feedback)
            self.assertEqual(state.removed_feedback, set())
            controller.call.assert_awaited_once_with('run.get', run_id='older')
            panel.refresh_trial.assert_awaited_once()
            controller.call.return_value = {'task_id': 'other', 'trial_step_id': 'step', 'run_id': 'foreign'}
            from taskweave.core.validation import TaskError
            with self.assertRaises(TaskError):
                await panel.select_history_run('foreign')
            self.assertEqual(trials['step'], 'older')
        asyncio.run(scenario())

    def test_selecting_current_history_record_cancels_an_older_pending_choice(self):
        async def scenario():
            release, entered = asyncio.Event(), asyncio.Event()
            trials = {'step': 'current'}
            async def lookup(operation, run_id):
                entered.set()
                await release.wait()
                return {'task_id': 'task', 'trial_step_id': 'step', 'run_id': run_id}
            panel = StepDebugPanel(MagicMock(), SimpleNamespace(call=lookup), lambda: ('task','step',0,0),
                lambda key: trials.get(key), lambda: None, page=lambda: 'editor',
                edit_controls=lambda: {'code': object()}, trials=trials, state=DebugState())
            panel.refresh_trial = AsyncMock()
            pending = asyncio.create_task(panel.select_history_run('older'))
            await entered.wait()
            await panel.select_history_run('current')
            release.set()
            await pending
            self.assertEqual(trials['step'], 'current')
            panel.refresh_trial.assert_not_awaited()
        asyncio.run(scenario())

    def test_late_history_selection_cannot_replace_newer_selection(self):
        async def scenario():
            release, entered = asyncio.Event(), asyncio.Event()
            trials = {'step': 'latest'}
            async def lookup(operation, run_id):
                if run_id == 'slow':
                    entered.set()
                    await release.wait()
                return {'task_id': 'task', 'trial_step_id': 'step', 'run_id': run_id}
            panel = StepDebugPanel(MagicMock(), SimpleNamespace(call=lookup), lambda: ('task','step',0,0),
                lambda key: trials.get(key), lambda: None, page=lambda: 'editor',
                edit_controls=lambda: {'code': object()}, trials=trials, state=DebugState())
            panel.refresh_trial = AsyncMock()
            pending = asyncio.create_task(panel.select_history_run('slow'))
            await entered.wait()
            await panel.select_history_run('chosen')
            release.set()
            await pending
            self.assertEqual(trials['step'], 'chosen')
            panel.refresh_trial.assert_awaited_once()
        asyncio.run(scenario())

    def test_inline_evidence_can_exclude_and_restore_parts_without_touching_code(self):
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page
        identity = ('task', 'step', 0, 0)
        state = DebugState()
        client = Client(page('/inline-repair-evidence'))
        try:
            with client:
                code = ui.textarea(value='current code')
                panel = StepDebugPanel(MagicMock(), SimpleNamespace(), lambda: identity, lambda _: 'run', lambda: None,
                    page=lambda: 'editor', edit_controls=lambda: {'code': code}, state=state)
                panel.repair_evidence_area = ui.column()
                panel.repair_button = ui.button('生成修复建议')
                panel.render_repair_evidence(identity, 'run')
                self.assertTrue(panel.repair_button.enabled)
                feedback = {'attempt_id': 'attempt', 'executed_step_content': 'old code',
                            'failed_action': {'id': 'demo.echo'}, 'failure_snapshots': [{'path': 'local.png'}]}
                panel.render_repair_evidence(identity, 'run', feedback)
                self.assertTrue(panel.repair_button.enabled)
                checkbox = next(e for e in panel.repair_evidence_area.descendants()
                                if isinstance(e, ui.checkbox) and e.text == '失败快照')
                checkbox.set_value(False)
                self.assertEqual(state.removed_feedback, {'failure_snapshots'})
                checkbox.set_value(True)
                self.assertEqual(state.removed_feedback, set())
                self.assertEqual(code.value, 'current code')
                baseline = next(e for e in panel.repair_evidence_area.descendants()
                                if getattr(e, 'text', '') == '失败代码与当前代码不同')
                self.assertTrue(baseline.visible)
                code.set_value('old code')
                self.assertFalse(baseline.visible)
                code.set_value('new draft')
                self.assertTrue(baseline.visible)
                panel.render_repair_evidence(identity, 'run')
                self.assertTrue(panel.repair_button.enabled)
                self.assertFalse(any(isinstance(e, ui.checkbox) for e in panel.repair_evidence_area.descendants()))
        finally:
            client.delete()

    def test_poll_stops_after_terminal_run_and_explicit_refresh_still_works(self):
        async def scenario():
            run = dict(run_id="run", status="SUCCEEDED", attempts=[], results=[])
            controller = SimpleNamespace(call=AsyncMock(side_effect=lambda op, **kw: run if op == "run.get" else []))
            panel = StepDebugPanel(MagicMock(), controller, lambda:("task", "step"), lambda _:"run", lambda:None,
                                  page=lambda:"editor", edit_controls=lambda:True, state=DebugState(), pending_inputs=AsyncMock())
            panel.trial_area = MagicMock(is_deleted=False)
            with patch("taskweave.desktop.components.step_debug.ui", MagicMock()):
                await panel.poll()
                count = controller.call.await_count
                for _ in range(5): await panel.poll()
                self.assertEqual(controller.call.await_count, count)
                await panel.refresh_trial()
                self.assertEqual(controller.call.await_count, count + 1)
        asyncio.run(scenario())

    def test_poll_does_not_overlap_pending_refresh(self):
        async def scenario():
            entered, release = asyncio.Event(), asyncio.Event()
            async def call(op, **kwargs):
                if op == "run.get":
                    entered.set()
                    await release.wait()
                    return dict(run_id="run", status="RUNNING", attempts=[], results=[])
                return []
            controller = SimpleNamespace(call=AsyncMock(side_effect=call))
            panel = StepDebugPanel(MagicMock(), controller, lambda:("task", "step"), lambda _:"run", lambda:None,
                                  page=lambda:"editor", edit_controls=lambda:True, state=DebugState(), pending_inputs=AsyncMock())
            panel.trial_area = MagicMock(is_deleted=False)
            with patch("taskweave.desktop.components.step_debug.ui", MagicMock()):
                pending = asyncio.create_task(panel.refresh_trial())
                await entered.wait()
                await panel.poll()
                self.assertEqual(controller.call.await_count, 1)
                release.set()
                await pending
        asyncio.run(scenario())

    def test_success_output_uses_each_attempt_execution_path(self):
        from taskweave.core.validation import TaskError
        async def scenario():
            attempts = [dict(step_id='step', attempt_id=f'a{i}', attempt_no=1, valid=True,
                             execution_path=f'/root/each/{i}/body/step', status='SUCCEEDED',
                             error_code=None, error_summary=None) for i in (0, 1)]
            run = dict(run_id='run', status='SUCCEEDED', attempts=attempts, results=[])
            async def call(command, **params):
                if command == 'run.get': return run
                if command == 'step.list': return [dict(step_id='step', name='逐项处理')]
                if command == 'run.output':
                    if params.get('execution_path') is None:
                        raise TaskError('RESULT_NOT_FOUND')
                    return {'path': params['execution_path']}
                raise AssertionError(command)
            controller = SimpleNamespace(call=AsyncMock(side_effect=call))
            panel = StepDebugPanel(MagicMock(), controller, lambda: ('task', 'step', 1, 1),
                lambda _: 'run', lambda: None, page=lambda: 'editor', edit_controls=lambda: True,
                state=DebugState(), pending_inputs=AsyncMock())
            panel.trial_area = MagicMock(is_deleted=False)
            with patch('taskweave.desktop.components.step_debug.ui', MagicMock()) as ui:
                await panel.refresh_trial()
                outputs = [item.kwargs['value'] for item in ui.textarea.call_args_list]
                self.assertEqual(len(outputs), 2)
                self.assertIn('/root/each/0/body/step', outputs[0])
                self.assertIn('/root/each/1/body/step', outputs[1])
        asyncio.run(scenario())

    def test_success_without_data_does_not_hide_later_failure(self):
        from taskweave.core.validation import TaskError

        async def scenario():
            attempts = [
                dict(step_id="first", attempt_id="a", attempt_no=1, valid=True,
                     status="SUCCEEDED", error_code=None, error_summary=None),
                dict(step_id="second", attempt_id="b", attempt_no=1, valid=True,
                     status="FAILED", error_code="BUSINESS_ASSERTION_FAILED", error_summary="Expected URL"),
            ]
            run = dict(run_id="run", status="FAILED", attempts=attempts, results=[])
            async def call(command, **kwargs):
                if command == "run.get": return run
                if command == "step.list":
                    return [dict(step_id="first", name="登录"), dict(step_id="second", name="新增页面")]
                if command == "run.output": raise TaskError("OUTPUT_NOT_AVAILABLE")
                raise AssertionError(command)
            controller = SimpleNamespace(call=AsyncMock(side_effect=call), trial_feedback=AsyncMock(return_value={}))
            state = DebugState()
            panel = StepDebugPanel(
                MagicMock(), controller, lambda:("task", "second", 1, 1), lambda _:"run", lambda:None,
                page=lambda:"editor", edit_controls=lambda:True, state=state,
                pending_inputs=AsyncMock(), step_result_dialog=AsyncMock(), navigate_step_debug=AsyncMock(),
            )
            panel.trial_area = MagicMock(is_deleted=False)
            with patch("taskweave.desktop.components.step_debug.ui", MagicMock()) as ui:
                await panel.refresh_trial()
                labels = [c.args[0] for c in ui.label.call_args_list]
                self.assertTrue(any("BUSINESS_ASSERTION_FAILED" in text for text in labels))
                self.assertFalse(any("无业务数据输出" in text for text in labels))
            controller.trial_feedback.assert_awaited_once_with("run", "second")
            self.assertEqual(state.feedback_run_id, "run")
        asyncio.run(scenario())

    def test_late_trial_feedback_does_not_replace_feedback_for_next_step(self):
        async def scenario():
            entered, release = asyncio.Event(), asyncio.Event()
            identity = ["task", "step-a", 2, 4]
            trials = {"step-a":"run-a"}
            state = DebugState()
            controller = SimpleNamespace(
                call=AsyncMock(side_effect=[
                    {"run_id":"run-a", "status":"FAILED", "attempts":[{"valid":True,"status":"FAILED","step_id":"step-a","attempt_no":1,"error_code":"E","error_summary":"failed","attempt_id":"attempt-a"}], "results":[]},
                    [{"step_id":"step-a","name":"Old step"}],
                ]),
                trial_feedback=AsyncMock(),
            )
            async def wait_feedback(*_args):
                entered.set()
                await release.wait()
                return {"run_id":"run-a", "summary":"OLD STEP A"}
            controller.trial_feedback.side_effect = wait_feedback
            area = MagicMock(is_deleted=False)
            area.__enter__ = MagicMock(return_value=area)
            area.__exit__ = MagicMock(return_value=False)
            panel = StepDebugPanel(
                MagicMock(), controller, lambda:tuple(identity), lambda step:trials.get(step), lambda:None,
                page=lambda:"editor", task_id=lambda:identity[0], step_id=lambda:identity[1],
                edit_controls=lambda:{"code":object()}, trials=trials, state=state,
                pending_inputs=AsyncMock(), step_result_dialog=AsyncMock(),
                navigate_step_debug=AsyncMock(), debug_round_fresh=lambda:False,
            )
            panel.trial_area = area
            state.feedback = {"run_id":"run-b", "summary":"NEW STEP B"}
            state.feedback_run_id = "run-b"
            with patch("taskweave.desktop.components.step_debug.ui", MagicMock()):
                pending = asyncio.create_task(panel.refresh_trial())
                await entered.wait()
                identity[:] = ["task", "step-b", 3, 5]
                release.set()
                await pending
            self.assertEqual(state.feedback, {"run_id":"run-b", "summary":"NEW STEP B"})
            self.assertEqual(state.feedback_run_id, "run-b")
            self.assertEqual([call.args[0] for call in controller.call.await_args_list], ["run.get", "step.list"])
            self.assertNotIn("run.events", [call.args[0] for call in controller.call.await_args_list])

        asyncio.run(scenario())

    def test_late_trial_feedback_is_ignored_after_run_replacement_or_page_leave(self):
        async def scenario(change_identity):
            entered, release = asyncio.Event(), asyncio.Event()
            identity = ["task", "step-a", 2, 4]
            page = ["editor"]
            trials = {"step-a":"run-a"}
            state = DebugState(feedback={"run_id":"run-new", "summary":"CURRENT"}, feedback_run_id="run-new")
            controller = SimpleNamespace(
                call=AsyncMock(side_effect=[
                    {"run_id":"run-a", "status":"FAILED", "attempts":[{"valid":True,"status":"FAILED","step_id":"step-a","attempt_no":1,"error_code":"E","error_summary":"failed","attempt_id":"attempt-a"}], "results":[]},
                    [{"step_id":"step-a","name":"Step"}],
                ]),
                trial_feedback=AsyncMock(),
            )
            async def wait_feedback(*_args):
                entered.set()
                await release.wait()
                return {"run_id":"run-a", "summary":"STALE"}
            controller.trial_feedback.side_effect = wait_feedback
            area = MagicMock(is_deleted=False)
            area.__enter__ = MagicMock(return_value=area)
            area.__exit__ = MagicMock(return_value=False)
            panel = StepDebugPanel(
                MagicMock(), controller, lambda:tuple(identity), lambda step:trials.get(step), lambda:None,
                page=lambda:page[0], task_id=lambda:identity[0], step_id=lambda:identity[1],
                edit_controls=lambda:{"code":object()}, trials=trials, state=state,
                pending_inputs=AsyncMock(), step_result_dialog=AsyncMock(),
                navigate_step_debug=AsyncMock(), debug_round_fresh=lambda:False,
            )
            panel.trial_area = area
            with patch("taskweave.desktop.components.step_debug.ui", MagicMock()):
                pending = asyncio.create_task(panel.refresh_trial())
                await entered.wait()
                change_identity(identity, page, trials)
                release.set()
                await pending
            self.assertEqual(state.feedback, {"run_id":"run-new", "summary":"CURRENT"})
            self.assertEqual(state.feedback_run_id, "run-new")
            self.assertNotIn("run.events", [call.args[0] for call in controller.call.await_args_list])

        async def run_all():
            await scenario(lambda identity, page, trials: trials.__setitem__("step-a", "run-new"))
            await scenario(lambda identity, page, trials: page.__setitem__(0, "tasks"))
        asyncio.run(run_all())

    def test_late_trial_start_does_not_attach_run_to_next_step(self):
        async def scenario():
            entered, release = asyncio.Event(), asyncio.Event()
            identity = ["task", "step-a", 1, 2]
            trials = {}

            async def trial(*args, **kwargs):
                entered.set()
                await release.wait()
                return {"run_id": "run-a"}

            controller = SimpleNamespace(trial=AsyncMock(side_effect=trial))
            form = SimpleNamespace(input_draft=input_draft({"a":1}, "dev"))
            environment = SimpleNamespace(value="dev")
            session = StepDebugSession(
                controller=controller,
                identity=lambda: tuple(identity),
                task_id=lambda: identity[0],
                save_editor=AsyncMock(return_value={"step_id": "step-a"}),
                trial_form=lambda: form,
                trial_environment=lambda: environment,
                environment_select=AsyncMock(),
                trial_variables=AsyncMock(),
                trials=trials,
                button=AsyncMock(),
                confirm_end=AsyncMock(),
                resume_inputs=AsyncMock(),
                refresh_trial=AsyncMock(),
                update_environment=AsyncMock(),
                reset_feedback=AsyncMock(),
                trial_start_status=lambda: None,
                debug_state=form.input_draft.state,
                refresh_trial_inputs=AsyncMock(),
            )
            session.settle_trial_start = AsyncMock()
            pending = asyncio.create_task(session.start_trial(continue_session=True))
            await entered.wait()
            identity[:] = ["task", "step-b", 2, 3]
            release.set()
            await pending

            self.assertEqual(trials, {})
            session.settle_trial_start.assert_not_awaited()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
