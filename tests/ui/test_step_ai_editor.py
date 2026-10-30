"""StepAIEditor ignores generation and adoption responses for stale editors."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from taskweave.core.validation import TaskError
from taskweave.desktop.components.step_ai import StepAIEditor
from taskweave.desktop.state import StepEditorState
from taskweave.desktop.workbench import Workbench


class _Dialog:
    def __init__(self, result=None):
        self.result = result
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def __await__(self):
        async def result(): return self.result
        return result().__await__()
    def open(self): pass
    def close(self): pass


class StepAIEditorTests(unittest.TestCase):
    def test_adopt_and_debug_saves_before_start_and_keeps_saved_code_on_start_failure(self):
        async def scenario():
            events = []
            code = SimpleNamespace(value='baseline', is_deleted=False)
            async def save():
                events.append('save')
                return {'step_id': 'step', 'step_content': code.value}
            async def start(saved, identity):
                events.append('debug')
                self.assertEqual(saved['step_content'], 'candidate')
                raise RuntimeError('executor unavailable')
            editor = StepAIEditor(SimpleNamespace(), MagicMock(), save, lambda: None,
                                  lambda: {'code': code}, lambda: ('task', 'step', 1, 1))
            editor.start_debug = start
            self.assertTrue(hasattr(editor, '_adopt_content'), 'Both channels need one guarded adoption sequence')
            validate = AsyncMock(return_value='candidate')
            repaint = AsyncMock()
            with self.assertRaisesRegex(TaskError, '代码已采纳并保存.*调试启动失败'):
                await editor._adopt_content(validate, editor.identity(), lambda: events.append('close'),
                                            repaint, debug=True)
            self.assertEqual(events, ['save', 'close', 'debug'])
            self.assertEqual(code.value, 'candidate')
            repaint.assert_not_awaited()
        asyncio.run(scenario())

    def test_adopt_save_failure_rolls_back_draft_and_never_starts_debug(self):
        async def scenario():
            code = SimpleNamespace(value='baseline', is_deleted=False)
            editor = StepAIEditor(SimpleNamespace(), MagicMock(), AsyncMock(side_effect=TaskError('EDIT_CONFLICT')),
                                  lambda: None, lambda: {'code': code}, lambda: ('task', 'step', 1, 1))
            editor.start_debug = AsyncMock()
            self.assertTrue(hasattr(editor, '_adopt_content'))
            close, repaint = MagicMock(), AsyncMock()
            with self.assertRaises(TaskError):
                await editor._adopt_content(AsyncMock(return_value='candidate'), editor.identity(), close,
                                            repaint, debug=True)
            self.assertEqual(code.value, 'baseline')
            editor.start_debug.assert_not_awaited()
            close.assert_not_called()
        asyncio.run(scenario())

    def test_adopt_late_save_or_newer_draft_never_starts_debug(self):
        async def scenario(change_step, fail_save=False):
            entered, release = asyncio.Event(), asyncio.Event()
            identity = ['task', 'step', 1, 1]
            code = SimpleNamespace(value='baseline', is_deleted=False)
            async def save():
                entered.set()
                await release.wait()
                if fail_save:
                    raise TaskError('EDIT_CONFLICT')
                return {'step_id': 'step', 'step_content': 'candidate'}
            editor = StepAIEditor(SimpleNamespace(), MagicMock(), save, lambda: None,
                                  lambda: {'code': code}, lambda: tuple(identity))
            editor.start_debug = AsyncMock()
            self.assertTrue(hasattr(editor, '_adopt_content'))
            close, repaint = MagicMock(), AsyncMock()
            with patch('taskweave.desktop.components.step_ai.ui', MagicMock()):
                pending = asyncio.create_task(editor._adopt_content(AsyncMock(return_value='candidate'),
                    tuple(identity), close, repaint, debug=True))
                await entered.wait()
                if change_step:
                    identity[:] = ['task', 'other', 2, 2]
                else:
                    code.value = 'newer draft'
                release.set()
                if fail_save:
                    with self.assertRaises(TaskError):
                        await pending
                else:
                    await pending
            editor.start_debug.assert_not_awaited()
            repaint.assert_not_awaited()
            if not change_step:
                self.assertEqual(code.value, 'newer draft')
        asyncio.run(scenario(True))
        asyncio.run(scenario(False))
        asyncio.run(scenario(False, fail_save=True))

    def test_code_assistant_exports_saved_code_and_supplement_without_model_call(self):
        import tempfile
        from taskweave.application.service import Application
        from taskweave.desktop.controller import DesktopController
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task('code assistant')
            code = 'async def run(ctx, inputs):\n    return ctx.result(data={"contract_id": "DEMO-100"})\n'
            saved = app.repo.save_step(task['task_id'], {'name': 'query', 'step_content': code})
            controller = DesktopController(app)
            editor = StepAIEditor(controller, MagicMock(), AsyncMock(return_value=saved),
                                  lambda: None, lambda: {}, lambda: ('task', saved['step_id'], 0, 0),
                                  author_step=controller.author_step, authoring_request=controller.authoring_request)
            editor._present_generation_result = AsyncMock()
            async def scenario():
                self.assertTrue(hasattr(editor, 'generate_from_form'), 'Code assistant needs a guarded generation entry')
                with patch('taskweave.desktop.components.step_ai.ui', MagicMock()):
                    await editor.generate_from_form('chat', '保留通用示例编号，增加金额输出', repaint=AsyncMock())
                request = controller.authoring_request(saved['step_id'])
                self.assertTrue(request['params']['export_only'])
                prompt = request['task'].result()['prompt']
                self.assertIn('DEMO-100', prompt)
                self.assertIn('保留通用示例编号，增加金额输出', prompt)
                current = await controller.call('step.get', step_id=saved['step_id'])
                self.assertEqual(current['step_content'], code)
            asyncio.run(scenario())

    def test_goal_generation_after_reload_accepts_empty_default_environment(self):
        import tempfile
        from taskweave.application.service import Application
        from taskweave.desktop.controller import DesktopController
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task('default environment')
            saved = app.repo.save_step(task['task_id'], {'name': 'goal',
                'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n'})
            controller = DesktopController(app)
            editor = StepAIEditor(controller, MagicMock(), AsyncMock(return_value=saved),
                                  lambda: '', lambda: {}, lambda: ('task', saved['step_id'], 0, 0),
                                  author_step=controller.author_step, authoring_request=controller.authoring_request)
            editor._present_goal_result = AsyncMock()
            async def scenario():
                with patch('taskweave.desktop.components.step_ai.ui', MagicMock()) as fake_ui:
                    fake_ui.dialog.return_value = _Dialog(('chat', '中文目标'))
                    await editor.generate_goal_dialog()
                editor._present_goal_result.assert_awaited_once()
                request = controller.authoring_request(saved['step_id'])
                self.assertIsNone(request['params']['environment_id'])
                self.assertIn('中文目标', request['task'].result()['prompt'])
            asyncio.run(scenario())

    def test_recovered_candidate_rechecks_attempt_at_adoption(self):
        async def scenario():
            saved = {'step_id': 'step', 'content_hash': 'original', 'step_content': 'code'}
            proposal = {'proposed_content': 'candidate', 'explanation': 'repair',
                        'stale': False, 'diagnostics': []}
            result = asyncio.create_task(asyncio.sleep(0, result=proposal))
            await result
            request = {'task': result, 'saved': saved, 'operation': 'step.generate',
                       'params': {'feedback': {'run_id': 'run', 'attempt_id': 'old-attempt'}}}
            attempts = [{'step_id': 'step', 'valid': True, 'status': 'FAILED', 'attempt_id': 'old-attempt'}]
            async def call(operation, **params):
                return saved if operation == 'step.get' else {'attempts': attempts}
            callbacks = {}
            def button(title, callback, **kwargs):
                callbacks[title] = callback
                return MagicMock()
            code = SimpleNamespace(value='code')
            editor = StepAIEditor(SimpleNamespace(call=AsyncMock(side_effect=call), diff=lambda *_: 'diff'),
                                  button, AsyncMock(), lambda: None, lambda: {'code': code},
                                  lambda: ('task', 'step', 0, 0), trials={'step': 'run'},
                                  authoring_request=lambda _: request)
            with patch('taskweave.desktop.components.step_ai.ui', MagicMock()):
                await editor.present_content_candidate(saved, proposal, editor.identity(), AsyncMock())
                attempts[0]['attempt_id'] = 'later-attempt'
                with self.assertRaises(TaskError) as stale:
                    await callbacks['采纳到编辑器']()
                self.assertEqual(stale.exception.code, 'VALIDATION_EVIDENCE_INVALID')
            self.assertEqual(code.value, 'code')
            editor.save_editor.assert_not_awaited()
        asyncio.run(scenario())

    def test_recovery_uses_retained_result_and_rejects_changed_step_or_attempt(self):
        async def scenario():
            saved = {'step_id': 'step', 'content_hash': 'original', 'step_content': 'code'}
            proposal = {'proposed_content': 'candidate'}
            result = asyncio.create_task(asyncio.sleep(0, result=proposal))
            request = {'task': result, 'saved': saved, 'operation': 'step.generate',
                       'params': {'feedback': {'run_id': 'run', 'attempt_id': 'attempt'}}}
            latest = dict(saved)
            attempts = [{'step_id': 'step', 'valid': True, 'status': 'FAILED', 'attempt_id': 'attempt'}]
            async def call(operation, **params):
                if operation == 'step.get': return latest
                if operation == 'run.get': return {'attempts': attempts}
                raise AssertionError('Recovery must not generate: ' + operation)
            controller = SimpleNamespace(call=AsyncMock(side_effect=call))
            editor = StepAIEditor(controller, MagicMock(), AsyncMock(), lambda: None,
                                  lambda: {'code': SimpleNamespace(value='code')},
                                  lambda: ('task', 'step', 0, 0), trials={'step': 'run'},
                                  authoring_request=lambda _: request)
            editor._present_generation_result = AsyncMock()
            with patch('taskweave.desktop.components.step_ai.ui', MagicMock()):
                await editor.recover_generation(repaint=AsyncMock())
                editor._present_generation_result.assert_awaited_once()
                editor.save_editor.assert_not_awaited()
                editor._present_generation_result.reset_mock()
                latest['content_hash'] = 'other-version'
                with self.assertRaises(TaskError) as conflict:
                    await editor.recover_generation(repaint=AsyncMock())
                self.assertEqual(conflict.exception.code, 'EDIT_CONFLICT')
                latest['content_hash'] = 'original'
                attempts[0]['attempt_id'] = 'new-attempt'
                with self.assertRaises(TaskError) as changed:
                    await editor.recover_generation(repaint=AsyncMock())
                self.assertEqual(changed.exception.code, 'VALIDATION_EVIDENCE_INVALID')
                editor._present_generation_result.assert_not_awaited()
        asyncio.run(scenario())

    def test_inline_repair_uses_visible_evidence_and_selected_options_without_modal(self):
        async def scenario():
            identity = ('task', 'step', 0, 0)
            feedback = {'run_id': 'run', 'attempt_id': 'attempt', 'executed_step_content': 'failed code'}
            state = SimpleNamespace(feedback=feedback, feedback_run_id='run', supplements={}, removed_feedback={'failure_snapshots'})
            editor = StepAIEditor(SimpleNamespace(), MagicMock(), AsyncMock(), lambda: None,
                                  lambda: {}, lambda: identity, debug_state=state, trials={'step': 'run'})
            flow = SimpleNamespace(repair_evidence=AsyncMock(return_value=feedback), recheck_repair=AsyncMock(return_value='current'))
            editor._flow = lambda: flow
            editor.generate_content = AsyncMock(return_value=None)
            editor._present_generation_result = AsyncMock()
            with patch('taskweave.desktop.components.step_ai.ui', MagicMock()) as fake_ui:
                await editor.repair_from_form('chat', 2, False, '保留校验', expected_evidence=('run', 'attempt'), repaint=AsyncMock())
                fake_ui.dialog.assert_not_called()
                options = editor.generate_content.await_args.kwargs
                self.assertTrue(options['web_chat'])
                self.assertEqual(options['history_rounds'], 2)
                self.assertFalse(options['deduplicate_history'])
                self.assertEqual(options['feedback_override'], feedback)
                self.assertEqual(options['removed_feedback'], {'failure_snapshots'})
                self.assertEqual(state.supplements['step'], '保留校验')
                editor.generate_content.reset_mock()
                await editor.repair_from_form('api', -1, True, '', expected_evidence=('run', 'older-attempt'), repaint=AsyncMock())
                editor.generate_content.assert_not_awaited()
                fake_ui.notify.assert_called()
        asyncio.run(scenario())

    def test_repair_without_failure_exports_selected_history_and_user_requirement(self):
        import tempfile
        from taskweave.application.service import Application
        from taskweave.desktop.controller import DesktopController
        from taskweave.presentation.state import DebugState
        for rounds in (-1, 0, 1):
            with self.subTest(rounds=rounds), tempfile.TemporaryDirectory() as home, Application(home) as app:
                task = app.repo.create_task('repair without failure')
                code = 'async def run(ctx, inputs):\n    return ctx.result()\n'
                saved = app.repo.save_step(task['task_id'], {'name': 'step', 'step_content': code})
                app.authoring.conversations[saved['step_id']] = [
                    {'role': 'user', 'content': 'earlier requirement'},
                    {'role': 'assistant', 'content': 'earlier candidate'},
                    {'role': 'user', 'content': 'latest requirement'},
                    {'role': 'assistant', 'content': 'latest candidate'},
                ]
                controller = DesktopController(app)
                editor = StepAIEditor(controller, MagicMock(), AsyncMock(return_value=saved),
                    lambda: None, lambda: {'code': SimpleNamespace(value=code)}, lambda: ('task', saved['step_id'], 0, 0),
                    debug_state=DebugState(), author_step=controller.author_step,
                    authoring_request=controller.authoring_request)
                editor._present_generation_result = AsyncMock()
                async def scenario():
                    with patch('taskweave.desktop.components.step_ai.ui', MagicMock()):
                        await editor.repair_from_form('chat', rounds, False, '成功但不符合要求，请补充输入',
                            expected_evidence=(None, None), repaint=AsyncMock())
                    request = controller.authoring_request(saved['step_id'])
                    self.assertIsNotNone(request)
                    exported = request['task'].result()
                    self.assertIn('成功但不符合要求，请补充输入', exported['prompt'])
                    self.assertEqual('earlier candidate' in exported['prompt'], rounds == -1)
                    self.assertEqual('latest candidate' in exported['prompt'], rounds != 0)
                    self.assertFalse(request['params']['feedback'])
                    self.assertEqual(request['params']['history_rounds'], rounds)
                    current = await controller.call('step.get', step_id=saved['step_id'])
                    self.assertEqual(current['step_content'], code)
                    if rounds != 0:
                        editor._present_generation_result.reset_mock()
                        with patch('taskweave.desktop.components.step_ai.ui', MagicMock()):
                            await editor.recover_generation(repaint=AsyncMock())
                        self.assertTrue(editor._present_generation_result.await_args.args[1])
                asyncio.run(scenario())

    def test_reloaded_editor_cannot_open_new_ai_flow_while_request_is_active(self):
        async def scenario():
            release = asyncio.Event()
            pending = asyncio.create_task(release.wait())
            editor = StepAIEditor(SimpleNamespace(), MagicMock(), AsyncMock(), lambda: None,
                                  lambda: {}, lambda: ('task', 'step', 0, 0),
                                  authoring_request=lambda _: {'task': pending})
            with patch('taskweave.desktop.components.step_ai.ui', MagicMock()) as fake_ui:
                await editor.choose_generation_mode(repaint=AsyncMock())
                await editor.choose_repair_mode(repaint=AsyncMock())
                await editor.generate_goal_dialog()
                await editor.generate_from_form('chat', 'supplement', repaint=AsyncMock())
                fake_ui.dialog.assert_not_called()
                self.assertEqual(fake_ui.notify.call_count, 4)
                editor.save_editor.assert_not_awaited()
            release.set()
            await pending
        asyncio.run(scenario())

    def test_controller_retains_inflight_ai_across_waiter_cancel_and_rejects_duplicate(self):
        import tempfile
        import threading
        from taskweave.application.service import Application
        from taskweave.desktop.controller import DesktopController
        from taskweave.core.ports import ModelReply

        entered, release = threading.Event(), threading.Event()
        class SlowModel:
            def __init__(self): self.requests = 0
            def capabilities(self): return {'images': False}
            async def complete(self, *args, **kwargs):
                self.requests += 1
                entered.set()
                await asyncio.to_thread(release.wait)
                return ModelReply('async def run(ctx, inputs):\n    return ctx.result(data={"new": True})\n', 'local delayed result')

        model = SlowModel()
        with tempfile.TemporaryDirectory() as home, Application(home, model) as app:
            task = app.repo.create_task('retained AI')
            step = app.repo.save_step(task['task_id'], {'name': 'original',
                'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n'})
            controller = DesktopController(app)
            async def scenario():
                params = {'step_id': step['step_id'], 'expected_hash': step['content_hash']}
                pending = asyncio.create_task(controller.author_step('step.generate', step, **params))
                self.assertTrue(await asyncio.to_thread(entered.wait, 10), 'Model request did not start')
                pending.cancel()
                with self.assertRaises(asyncio.CancelledError): await pending
                with self.assertRaises(TaskError) as raised:
                    await controller.author_step('step.generate', step, **params)
                self.assertEqual(raised.exception.code, 'AUTHORING_BUSY')
                request = controller.authoring_request(step['step_id'])
                self.assertFalse(request['task'].done())
                release.set()
                proposal = await asyncio.shield(request['task'])
                self.assertIn('"new": True', proposal['proposed_content'])
                self.assertEqual(model.requests, 1)
                self.assertEqual(app.repo.step(step['step_id'])['step_content'], step['step_content'])
                self.assertEqual(request['saved']['content_hash'], step['content_hash'])
            try:
                asyncio.run(scenario())
            finally:
                release.set()

    def test_late_content_generation_is_discarded_after_editor_switch(self):
        async def scenario():
            entered, release = asyncio.Event(), asyncio.Event()
            identity = ["task", "step-a", 4, 3]
            async def call(operation, **params):
                if operation != "context.ai": raise AssertionError(operation)
                entered.set()
                await release.wait()
                return []
            controller = SimpleNamespace(call=AsyncMock(side_effect=call))
            save = AsyncMock(return_value={"task_id": "task", "step_id": "step-a", "content_hash": "h", "step_description": "goal", "step_content": "code"})
            editor = StepAIEditor(controller, MagicMock(), save, lambda: None, lambda: {}, lambda: tuple(identity))
            fake_ui = MagicMock()
            with patch("taskweave.desktop.components.step_ai.ui", fake_ui):
                pending = asyncio.create_task(editor.generate_content())
                await entered.wait()
                identity[:] = ["task", "step-b", 5, 4]
                release.set()
                result = await pending
            self.assertIsNone(result)
            controller.call.assert_awaited_once_with("context.ai", step_id="step-a")
            fake_ui.dialog.assert_not_called()

        asyncio.run(scenario())

    def test_content_generation_discards_context_reply_after_step_switch(self):
        async def scenario():
            entered, release = asyncio.Event(), asyncio.Event()
            identity = ["task", "step-a", 1, 2]
            controller = SimpleNamespace()
            async def call(operation, **params):
                if operation == "context.ai":
                    entered.set()
                    await release.wait()
                    return []
                raise AssertionError(operation)
            controller.call = AsyncMock(side_effect=call)
            save = AsyncMock(return_value={"step_id": "step-a", "content_hash": "h", "step_description": "goal", "step_content": "code"})
            editor = StepAIEditor(controller, MagicMock(), save, lambda: None, lambda: {}, lambda: tuple(identity))
            pending = asyncio.create_task(editor.generate_content())
            await entered.wait()
            identity[:] = ["task", "step-b", 2, 3]
            release.set()
            result = await pending
            self.assertIsNone(result)
            controller.call.assert_awaited_once_with("context.ai", step_id="step-a")

        asyncio.run(scenario())

    def test_stale_content_candidate_cannot_overwrite_new_editor(self):
        async def scenario():
            identity = ["task", "step-a", 1, 2]
            controls = {"code": SimpleNamespace(value="original")}
            callbacks = {}
            def button(title, callback, **kwargs):
                callbacks[title] = callback
                return MagicMock()
            page = StepAIEditor(SimpleNamespace(diff=lambda *_: "diff", call=AsyncMock()), button, AsyncMock(), lambda: None, lambda: controls, lambda: tuple(identity))
            fake_ui = MagicMock()
            with patch("taskweave.desktop.components.step_ai.ui", fake_ui):
                await page.present_content_candidate(
                    {"step_id": "step-a", "step_content": "original"},
                    {"explanation": "explain", "proposed_content": "candidate", "stale": False, "diagnostics": []},
                    tuple(identity), AsyncMock(),
                )
                identity[:] = ["task", "step-b", 2, 3]
                with self.assertRaises(TaskError) as raised:
                    await callbacks["采纳到编辑器"]()
            self.assertEqual(raised.exception.code, "EDIT_CONFLICT")
            self.assertEqual(controls["code"].value, "original")
        asyncio.run(scenario())

    def test_late_goal_generation_is_discarded_after_step_switch(self):
        async def scenario():
            entered, release = asyncio.Event(), asyncio.Event()
            identity = ["task", "step-a", 1, 2]
            controller = MagicMock()
            async def call(operation, **params):
                if operation == "context.ai": return []
                if operation == "step.generate_goal":
                    entered.set()
                    await release.wait()
                    return {"step_description": "late", "step_notes": "", "prompt": ""}
                raise AssertionError(operation)
            controller.call = AsyncMock(side_effect=call)
            page = StepAIEditor(controller, MagicMock(), AsyncMock(return_value={"step_id": "step-a", "content_hash": "h"}), lambda: None, lambda: {}, lambda: tuple(identity))
            fake_ui = MagicMock()
            fake_ui.dialog.return_value = _Dialog(("api", "requirement"))
            with patch("taskweave.desktop.components.step_ai.ui", fake_ui):
                pending = asyncio.create_task(page.generate_goal_dialog())
                await entered.wait()
                identity[:] = ["task", "step-b", 2, 3]
                release.set()
                await pending
            self.assertEqual(fake_ui.dialog.call_count, 1)
            controller.call.assert_any_await("step.generate_goal", step_id="step-a", expected_hash="h", supplement="requirement", contexts=[], environment_id=None, export_only=False)

        asyncio.run(scenario())

    def test_stale_goal_candidate_cannot_mutate_current_step_controls(self):
        async def scenario():
            identity = ["task", "step-a", 1, 2]
            controller = MagicMock()
            controller.call = AsyncMock(return_value={"content_hash": "h"})
            controls = {"step_description": SimpleNamespace(value="old"), "step_notes": SimpleNamespace(value="old note")}
            callbacks = {}
            def button(title, callback, **kwargs):
                callbacks[title] = callback
                return MagicMock()
            page = StepAIEditor(controller, button, AsyncMock(), lambda: None, lambda: controls, lambda: tuple(identity))
            fake_ui = MagicMock()
            fake_ui.dialog.return_value = _Dialog()
            with patch("taskweave.desktop.components.step_ai.ui", fake_ui):
                await page.preview_goal({"step_id": "step-a", "content_hash": "h"}, "new", "new note")
                identity[:] = ["task", "step-b", 2, 3]
                with self.assertRaises(TaskError) as raised:
                    await callbacks["采纳步骤描述"]()
            self.assertEqual(raised.exception.code, "EDIT_CONFLICT")
            self.assertEqual(controls["step_description"].value, "old")
            self.assertEqual(controls["step_notes"].value, "old note")

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()


class ConcurrentAIFlowTests(unittest.TestCase):
    def test_busy_guard_spans_await_and_releases_after_failure(self):
        from taskweave.desktop.components.step_ai import exclusive_ai_flow
        async def scenario():
            entered, release = asyncio.Event(), asyncio.Event()
            calls = []
            class Editor:
                def __init__(self):
                    from taskweave.presentation.authoring import AIInteraction
                    self.interaction = AIInteraction()
                @exclusive_ai_flow
                async def run(self):
                    calls.append(1)
                    entered.set()
                    await release.wait()
                    raise RuntimeError("model failed")
            editor = Editor()
            with patch("taskweave.desktop.components.step_ai.ui", MagicMock()):
                first = asyncio.create_task(editor.run())
                await entered.wait()
                await editor.run()
                self.assertEqual(len(calls), 1)
                release.set()
                with self.assertRaises(RuntimeError): await first
                self.assertFalse(editor.interaction.active)
                with self.assertRaises(RuntimeError): await editor.run()
                self.assertEqual(len(calls), 2)
        asyncio.run(scenario())

    def test_mode_buttons_accept_first_click_even_when_duplicate_events_are_queued(self):
        from taskweave.desktop.components.step_ai import submit_ai_choice
        callbacks, controls = [], []
        def make_button(title, on_click):
            callbacks.append(on_click)
            control = MagicMock()
            control.props.return_value = control
            controls.append(control)
            return control
        dialog = MagicMock()
        api, chat = MagicMock(return_value="api"), MagicMock(return_value="chat")
        with patch("taskweave.desktop.components.step_ai.ui.button", side_effect=make_button):
            submit_ai_choice(dialog, [("API", api), ("Chat", chat)])
        callbacks[1]()
        callbacks[1]()
        callbacks[0]()
        dialog.submit.assert_called_once_with("chat")
        chat.assert_called_once_with()
        api.assert_not_called()
        for control in controls:
            control.disable.assert_called_once_with()


class AIPlainDraftWiringTests(unittest.TestCase):
    def test_real_reply_input_updates_plain_draft_before_preview(self):
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page as page_route
        client = Client(page_route('/plain-ai-reply'))
        callbacks, drafts = {}, []
        def button(label, callback, **kwargs):
            callbacks[label] = callback
            return ui.button(label, on_click=callback)
        editor = StepAIEditor(SimpleNamespace(), button, AsyncMock(), lambda: None,
                              lambda: {}, lambda: ('task', 'step', 0, 0))
        editor.preview_goal = AsyncMock()
        original = editor.interaction.choice
        def remember(*args, **kwargs):
            draft = original(*args, **kwargs)
            drafts.append(draft)
            return draft
        editor.interaction.choice = remember
        async def scenario():
            with client:
                await editor._present_goal_result({'step_id': 'step'}, {'prompt': 'fixture'},
                                                 editor.identity(), web_chat=True)
                control = next(element for element in client.elements.values()
                               if element._props.get('label') == '粘贴网页回复')
                control.value = '{"step_description":"typed goal","step_notes":"typed note"}'
                self.assertEqual(drafts[0].reply, control.value)
                # Plain draft remains the command source after rendering.
                drafts[0].reply = '{"step_description":"plain goal","step_notes":"plain note"}'
                await callbacks['解析并预览']()
                self.assertEqual(editor.preview_goal.call_args.args[1:3], ('plain goal', 'plain note'))
        try:
            asyncio.run(scenario())
        finally:
            client.delete()
