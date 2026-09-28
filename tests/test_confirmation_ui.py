"""One confirmation action chooses trial evidence or explicit manual approval."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from taskweave.core.validation import TaskError
from taskweave.desktop.components.step_ai import StepAIEditor
from taskweave.desktop.state import DebugState


class ConfirmationUi(unittest.TestCase):
    def test_ai_repair_override_is_bound_to_attempt_after_editor_save(self):
        async def scenario():
            saved = {
                "step_id": "step", "content_hash": "hash", "step_description": "goal",
                "step_content": "code", "task_id": "task", "capabilities": [],
            }
            bound = {"run_id": "run", "attempt_id": "attempt-old", "trial_logs": ["old log"], "summary": "old"}
            scenarios = [
                ("attempt-old", "attempt-old", None, True),
                ("attempt-new", "attempt-new", None, False),
                # run.get still reports the old attempt, but the feedback read
                # after it sees a newer attempt. The chooser's override is stale.
                ("attempt-old", "attempt-new", None, False),
                ("attempt-old", "attempt-old", "active_run", False),
                ("attempt-old", "attempt-old", "editor_identity", False),
            ]
            for latest_attempt, refreshed_feedback_attempt, invalidate_after_feedback, should_generate in scenarios:
                with self.subTest(latest_attempt=latest_attempt, refreshed_feedback_attempt=refreshed_feedback_attempt,
                                  invalidate_after_feedback=invalidate_after_feedback):
                    generated = []
                    reads = 0
                    feedback_reads = 0
                    current_attempt = "attempt-old"
                    saving = False
                    identity = ["task", "step", 1, 1]
                    async def call(operation, **params):
                        nonlocal reads, current_attempt
                        if operation == "run.get":
                            reads += 1
                            current_attempt = latest_attempt if saving and reads >= 3 else "attempt-old"
                            return {
                                "run_id": "run", "definition_json": '{"steps":[]}',
                                "attempts": [{
                                    "valid": True, "status": "FAILED", "step_id": "step",
                                    "attempt_id": current_attempt,
                                }],
                            }
                        if operation == "context.ai":
                            return []
                        if operation == "step.generate":
                            generated.append(params)
                            return {"proposal": "local"}
                        raise AssertionError(operation)
                    async def save_editor():
                        nonlocal saving
                        saving = True
                        return saved
                    async def trial_feedback(_run_id, _step_id):
                        nonlocal feedback_reads
                        feedback_reads += 1
                        if feedback_reads == 1:
                            return dict(bound)
                        if invalidate_after_feedback == "active_run":
                            editor.trials["step"] = "run-new"
                        elif invalidate_after_feedback == "editor_identity":
                            identity[1] = "step-new"
                        return {
                            "run_id": "run", "attempt_id": refreshed_feedback_attempt,
                            "trial_logs": ["fresh log"], "summary": "fresh",
                        }
                    controller = SimpleNamespace(
                        call=AsyncMock(side_effect=call),
                        trial_feedback=AsyncMock(side_effect=trial_feedback),
                        repair_contexts=AsyncMock(return_value=([], {"available": True})),
                    )
                    editor = StepAIEditor(
                        controller, AsyncMock(), save_editor, lambda: None,
                        lambda: {"code": SimpleNamespace(value="code")},
                        lambda: tuple(identity), debug_state=DebugState(removed_feedback={"trial_logs"}),
                        trials={"step": "run"},
                    )
                    editor._present_generation_result = AsyncMock()
                    class Dialog:
                        def __enter__(self): return self
                        def __exit__(self, *args): pass
                        def __await__(self):
                            async def answer(): return ("api", 0, True, "note")
                            return answer().__await__()
                    with patch("taskweave.desktop.components.step_ai.ui", MagicMock()) as ui:
                        ui.dialog.return_value = Dialog()
                        await editor.choose_repair_mode(repaint=AsyncMock())
                    if should_generate:
                        self.assertEqual(len(generated), 1)
                        self.assertEqual(generated[0]["feedback"]["attempt_id"], bound["attempt_id"])
                        self.assertEqual(generated[0]["feedback"]["summary"], bound["summary"])
                        self.assertNotIn("trial_logs", generated[0]["feedback"])
                        self.assertFalse(any(
                            "当前调试尝试已变化" in str(call)
                            for call in ui.notify.call_args_list
                        ))
                    else:
                        self.assertEqual(generated, [])
                        ui.notify.assert_called_once_with(
                            "当前调试尝试已变化，请重新打开 AI 修复并核对最新证据。", type="warning",
                        )
                    self.assertEqual(reads, 3)

        asyncio.run(scenario())

    def test_success_missing_stale_evidence_and_cancel(self):
        async def scenario():
            for evidence, approval in [('success', True), ('missing', True), ('stale', True), ('missing', False)]:
                with self.subTest(evidence=evidence, approval=approval):
                    saved = {'step_id': 'step', 'content_hash': 'current'}
                    controller = SimpleNamespace(confirm=AsyncMock(return_value=saved), call=AsyncMock(return_value=saved))
                    if evidence == 'stale':
                        controller.confirm.side_effect = TaskError('VALIDATION_EVIDENCE_INVALID')
                    trials = {} if evidence == 'missing' else {'step': 'trial'}
                    repaint = AsyncMock()
                    class Dialog:
                        def __enter__(self): return self
                        def __exit__(self, *args): pass
                        def __await__(self):
                            async def answer(): return approval
                            return answer().__await__()
                    editor = StepAIEditor(
                        controller, AsyncMock(), AsyncMock(return_value=saved), lambda: 'uat',
                        lambda: {'code': 'current'}, lambda: ('task', 'step', 1, 1), trials=trials,
                    )
                    with patch('taskweave.desktop.components.step_ai.ui', MagicMock()) as ui:
                        ui.dialog.return_value = Dialog()
                        await editor.confirm_step(repaint)
                        self.assertEqual(ui.dialog.call_count, 0 if evidence == 'success' else 1)
                    if evidence != 'success' and approval:
                        controller.call.assert_awaited_once_with('step.confirm.manual', step_id='step', expected_hash='current', environment_id='uat')
                    else:
                        controller.call.assert_not_awaited()
                    self.assertEqual(repaint.await_count, 1 if evidence == 'success' or approval else 0)
        asyncio.run(scenario())

    def test_ai_repair_selects_transport_or_cancels_and_requires_current_feedback(self):
        async def scenario():
            feedback = {"run_id":"run-current-full-id", "attempt_id":"attempt-current-full-id", "summary":"failure"}
            for choice in [("api", -1, True, "note"), ("chat", 3, False, "note"), None]:
                state = DebugState(feedback=feedback, feedback_run_id="run-current-full-id",
                                   supplements={"step":"prior"}, removed_feedback={"trial_logs"})
                controller = SimpleNamespace(
                    call=AsyncMock(return_value={"attempts": [{"valid": True, "step_id": "step", "status": "FAILED", "attempt_id": "attempt-current-full-id"}]}),
                    trial_feedback=AsyncMock(return_value=feedback),
                )
                editor = StepAIEditor(
                    controller, AsyncMock(), AsyncMock(), lambda: None, lambda: {},
                    lambda: ("task", "step", 1, 1), debug_state=state, trials={"step":"run-current-full-id"},
                )
                editor.generate_content = AsyncMock(return_value=None)
                class Dialog:
                    def __enter__(self): return self
                    def __exit__(self, *args): pass
                    def __await__(self):
                        async def answer(): return choice
                        return answer().__await__()
                with patch("taskweave.desktop.components.step_ai.ui", MagicMock()) as ui:
                    button_controls = []
                    def make_button(*args, **kwargs):
                        control = MagicMock()
                        control.props.return_value = control
                        button_controls.append((args[0] if args else "", control))
                        return control
                    ui.button.side_effect = make_button
                    ui.dialog.return_value = Dialog()
                    await editor.choose_repair_mode(repaint=AsyncMock())
                    displayed = " ".join(str(call) for call in ui.input.call_args_list)
                    self.assertIn("run-current-full-id", displayed)
                    self.assertIn("attempt-current-full-id", displayed)
                    labels = [label for label, _ in button_controls]
                    self.assertIn("关闭", labels)
                    self.assertIn("取消", labels)
                    self.assertIn("大模型api调用", labels)
                    self.assertIn("大模型网页chat调用", labels)
                if choice is None:
                    editor.generate_content.assert_not_awaited()
                    controller.call.assert_awaited_once_with("run.get", run_id="run-current-full-id")
                    controller.trial_feedback.assert_awaited_once_with("run-current-full-id", "step")
                else:
                    editor.generate_content.assert_awaited_once_with(
                        fix_logs=True, web_chat=choice[0] == "chat", supplement="note",
                        run_id="run-current-full-id", history_rounds=choice[1],
                        deduplicate_history=choice[2], feedback_override=feedback,
                        feedback_run_id="run-current-full-id", removed_feedback={"trial_logs"},
                    )
            state = DebugState(feedback=None, feedback_run_id=None)
            controller = SimpleNamespace(
                call=AsyncMock(return_value={"attempts": [{"valid": True, "step_id": "step", "status": "FAILED", "attempt_id": "attempt-current-full-id"}]}),
                trial_feedback=AsyncMock(return_value={**feedback, "run_id": "new-run"}),
            )
            editor = StepAIEditor(
                controller, AsyncMock(), AsyncMock(), lambda: None, lambda: {},
                lambda: ("task", "step", 1, 1), debug_state=state, trials={"step":"new-run"},
            )
            editor.generate_content = AsyncMock(return_value=None)
            class Dialog:
                def __enter__(self): return self
                def __exit__(self, *args): pass
                def __await__(self):
                    async def answer(): return ("api", -1, True, "")
                    return answer().__await__()
            with patch("taskweave.desktop.components.step_ai.ui", MagicMock()) as ui:
                button_controls = []
                def make_button(*args, **kwargs):
                    control = MagicMock()
                    control.props.return_value = control
                    button_controls.append((args[0] if args else "", control))
                    return control
                ui.button.side_effect = make_button
                ui.dialog.return_value = Dialog()
                await editor.choose_repair_mode(repaint=AsyncMock())
                self.assertEqual(ui.input.call_count, 2)
                self.assertFalse(next(control for label, control in button_controls if label == "大模型api调用").disable.called)
                self.assertFalse(next(control for label, control in button_controls if label == "大模型网页chat调用").disable.called)
            editor.generate_content.assert_awaited_once()
            self.assertEqual(controller.call.await_args_list, [
                unittest.mock.call("run.get", run_id="new-run"),
                unittest.mock.call("run.get", run_id="new-run"),
            ])
            controller.trial_feedback.assert_awaited_once_with("new-run", "step")

            # A dialog opened for one attempt must not submit its evidence if a
            # newer attempt becomes current while the user is choosing a mode.
            identity = ("task", "step", 1, 1)
            attempts = [
                {"valid": True, "step_id": "step", "status": "FAILED", "attempt_id": "attempt-current-full-id"},
                {"valid": True, "step_id": "step", "status": "FAILED", "attempt_id": "attempt-new-full-id"},
            ]
            controller = SimpleNamespace(
                call=AsyncMock(side_effect=[
                    {"attempts": attempts[:1]}, {"attempts": attempts},
                ]),
                trial_feedback=AsyncMock(return_value=feedback),
            )
            editor = StepAIEditor(controller, AsyncMock(), AsyncMock(), lambda: None, lambda: {},
                                  lambda: identity, debug_state=DebugState(), trials={"step":"run-current-full-id"})
            editor.generate_content = AsyncMock(return_value=None)
            class ChangedAttemptDialog:
                def __enter__(self): return self
                def __exit__(self, *args): pass
                def __await__(self):
                    async def answer(): return ("api", -1, True, "")
                    return answer().__await__()
            with patch("taskweave.desktop.components.step_ai.ui", MagicMock()) as ui:
                ui.dialog.return_value = ChangedAttemptDialog()
                await editor.choose_repair_mode(repaint=AsyncMock())
                ui.notify.assert_called_once()
            editor.generate_content.assert_not_awaited()

            # Keep the cross-step guard aligned with generate_content: the
            # latest valid failure controls which step can be repaired.
            controller = SimpleNamespace(
                call=AsyncMock(return_value={"attempts": [{"valid": True, "step_id": "other-step", "status": "FAILED", "attempt_id": "attempt-other"}]}),
                trial_feedback=AsyncMock(),
            )
            editor = StepAIEditor(controller, AsyncMock(), AsyncMock(), lambda: None, lambda: {},
                                  lambda: identity, debug_state=DebugState(), trials={"step":"run-current-full-id"})
            editor.generate_content = AsyncMock()
            with patch("taskweave.desktop.components.step_ai.ui", MagicMock()) as ui:
                ui.dialog.return_value = ChangedAttemptDialog()
                await editor.choose_repair_mode(repaint=AsyncMock())
                ui.notify.assert_not_called()
            controller.trial_feedback.assert_not_awaited()
            editor.generate_content.assert_not_awaited()
        asyncio.run(scenario())
