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
            page = StepAIEditor(SimpleNamespace(diff=lambda *_: "diff"), button, AsyncMock(), lambda: None, lambda: controls, lambda: tuple(identity))
            fake_ui = MagicMock()
            with patch("taskweave.desktop.components.step_ai.ui", fake_ui):
                await page.present_content_candidate(
                    {"step_id": "step-a", "step_content": "original"},
                    {"explanation": "explain", "proposed_content": "candidate", "stale": False, "diagnostics": []},
                    tuple(identity), AsyncMock(), lambda: None,
                )
                identity[:] = ["task", "step-b", 2, 3]
                with self.assertRaises(TaskError) as raised:
                    await callbacks["采纳到编辑器"]()
            self.assertEqual(raised.exception.code, "EDIT_CONFLICT")
            self.assertEqual(controls["code"].value, "original")

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
                self.assertFalse(editor._ai_flow_active)
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
