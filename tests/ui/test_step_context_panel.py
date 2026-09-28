"""StepContextPanel saves group metadata through explicit callbacks."""

import asyncio
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from taskweave.desktop.components.step_contexts import StepContextPanel
from taskweave.desktop.contexts import ContextCards
from taskweave.desktop.state import ContextPageState
from taskweave.application.service import Application
from taskweave.desktop.controller import DesktopController


class StepContextPanelTests(unittest.TestCase):
    def test_real_local_context_entry_and_submission(self):
        with tempfile.TemporaryDirectory() as home, Application(
            home, registry_factory="tests.test_context_targets_runtime:build_registry"
        ) as app:
            task_id = app.repo.create_task("本地上下文")['task_id']
            step = app.repo.save_step(task_id, {
                "name": "本地步骤", "step_content": "async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n",
                "capabilities": ["demo.echo"],
            })
            controller = DesktopController(app)
            state = ContextPageState()
            pending = AsyncMock()
            panel = StepContextPanel(controller, state, lambda: step['step_id'], None, None, None, pending)
            draft = MagicMock()
            draft.payload.return_value = [{
                "capture": {"items": [{"kind": "text", "source": "demo.page", "content": "local fixture capture"}], "views": []},
                "request": {"fixture": True}, "label": "本地夹具",
            }]
            async def scenario():
                await panel.save_batch(None, "demo.page", "本地上下文组", "", draft)
                entries = await controller.call("context.list", step_id=step['step_id'])
                self.assertEqual(entries[0]['captures'][0]['label'], "本地夹具")
                capture = await controller.call("context.capture.get", context_id=entries[0]['context_id'], capture_id=entries[0]['captures'][0]['capture_id'], step_id=step['step_id'])
                self.assertEqual(capture['items'][0]['content'], "local fixture capture")
                self.assertEqual(app.dispatch("step.get", {"step_id": step['step_id']})['validation_state'], "DRAFT")
            asyncio.run(scenario())

    def test_capture_reorder_reloads_component_state_and_marks_pending(self):
        async def scenario():
            group = {"context_id":"ctx", "name":"Group", "provider_id":"p", "captures":[{"capture_id":"c", "items":[{"value":1}]}], "revision":3}
            controller = MagicMock()
            controller.call = AsyncMock(side_effect=[None, [group]])
            state = ContextPageState(entries=[{"context_id":"ctx", "captures":[{"capture_id":"cap"}]}])
            mark_pending = AsyncMock()
            page = StepContextPanel(controller, state, lambda:"step", None, None, None, mark_pending)
            await page.move_capture(state.entries[0], state.entries[0]["captures"][0], "up")
            controller.call.assert_has_awaits([
                unittest.mock.call("context.capture.reorder", context_id="ctx", capture_id="cap", direction="up", expected_revision=None, step_id="step"),
                unittest.mock.call("context.list", step_id="step"),
            ])
            self.assertEqual(state.entries, [group])
            self.assertEqual(state.ai_contexts[0]["provider_id"], "p")
            mark_pending.assert_awaited_once_with()

        asyncio.run(scenario())

    def test_batch_save_keeps_new_capture_order_in_component_state(self):
        async def scenario():
            group = {"context_id":"ctx", "name":"Group", "provider_id":"p", "captures":[{"capture_id":"b"},{"capture_id":"a"}], "revision":1}
            controller = MagicMock()
            controller.call = AsyncMock(return_value={"group":group})
            state = ContextPageState()
            page = StepContextPanel(controller, state, lambda:"step", None, None, None, AsyncMock())
            draft = MagicMock()
            draft.payload.return_value = [{"capture_id":"b"},{"capture_id":"a"}]
            await page.save_batch(None, "p", "Group", "notes", draft)
            self.assertEqual(state.entries, [group])
            controller.call.assert_awaited_once_with(
                "context.save_batch", step_id="step", context_id=None, expected_revision=None,
                provider_id="p", name="Group", context_notes="notes", captures=draft.payload.return_value,
            )

        asyncio.run(scenario())

    def test_group_save_updates_local_state_and_marks_step_pending(self):
        async def scenario():
            controller = MagicMock()
            controller.privacy_settings.return_value = {"redact_on_display": True}
            controller.call = AsyncMock(return_value={"context_id": "ctx", "name": "Renamed", "revision": 2})
            state = ContextPageState(entries=[{"context_id": "ctx", "revision": 1, "captures": []}])
            mark_pending = AsyncMock()
            page = StepContextPanel(controller, state, lambda: "step", AsyncMock(), AsyncMock(), AsyncMock(), mark_pending)
            panel = MagicMock(is_deleted=False)
            with patch("taskweave.desktop.components.step_contexts.ContextCards", return_value="cards") as cards:
                page.render(panel)
                save = cards.call_args.args[1]
                await save(state.entries[0], "Renamed", "notes")
            self.assertEqual(page.cards, "cards")
            self.assertEqual(state.entries[0]["revision"], 2)
            self.assertEqual(state.ai_contexts, [])
            controller.call.assert_awaited_once_with(
                "context.group.update", step_id="step", context_id="ctx",
                name="Renamed", context_notes="notes", expected_revision=1,
            )
            mark_pending.assert_awaited_once_with()

        asyncio.run(scenario())

    def test_failed_batch_save_keeps_capture_draft_for_one_retry(self):
        async def scenario():
            group = {"context_id":"ctx", "name":"Group", "provider_id":"p", "captures":[{"capture_id":"cap"}], "revision":1}
            controller = MagicMock()
            controller.call = AsyncMock(side_effect=[RuntimeError("save failed"), {"group":group}])
            state = ContextPageState()
            page = StepContextPanel(controller, state, lambda:"step", None, None, None, AsyncMock())
            draft = MagicMock()
            draft.payload.return_value = [{"capture_id":"cap", "label":"one"}]
            with self.assertRaisesRegex(RuntimeError, "save failed"):
                await page.save_batch(None, "p", "Group", "", draft)
            self.assertEqual(state.entries, [])
            self.assertEqual(draft.payload(), [{"capture_id":"cap", "label":"one"}])
            await page.save_batch(None, "p", "Group", "", draft)
            self.assertEqual(state.entries, [group])
            self.assertEqual(controller.call.await_count, 2)

        asyncio.run(scenario())

    def test_dispose_releases_panel_and_cards_handles(self):
        page = StepContextPanel(MagicMock(), ContextPageState(), lambda:"step", None, None, None, AsyncMock())
        page.panel = MagicMock()
        page.cards = MagicMock()
        page.dispose()
        self.assertIsNone(page.panel)
        self.assertIsNone(page.cards)

    def test_cancel_confirmation_keeps_staged_capture_when_user_continues_editing(self):
        async def scenario():
            page = StepContextPanel(MagicMock(), ContextPageState(), lambda:"step", None, None, None, AsyncMock())
            draft = MagicMock(dirty=True)
            confirm = AsyncMock(return_value=False)
            may_discard = await page.may_discard_draft(draft, "Group", "notes", "Group", "", confirm)
            self.assertFalse(may_discard)
            confirm.assert_awaited_once_with()
            self.assertTrue(draft.dirty)

        asyncio.run(scenario())

    def test_late_context_card_reorder_cannot_mutate_shared_entries_after_dispose(self):
        async def scenario():
            entered, release = asyncio.Event(), asyncio.Event()
            entries = [
                {"context_id":"a", "name":"A", "provider_id":"p", "captures":[], "revision":1},
                {"context_id":"b", "name":"B", "provider_id":"p", "captures":[], "revision":1},
            ]
            controller = MagicMock()
            async def reorder(*_args, **_kwargs):
                entered.set(); await release.wait(); return [{**entries[0], "order_index":1}, {**entries[1], "order_index":0}]
            controller.call = AsyncMock(side_effect=reorder)
            page = StepContextPanel(controller, ContextPageState(entries=entries), lambda:"step", None, None, None, AsyncMock())
            cards = object.__new__(ContextCards)
            cards.entries, cards.move, cards.panel, cards.cards = page.state.entries, page.move_group, MagicMock(), {}
            cards.is_active = lambda: page._active(0)
            panel = MagicMock(is_deleted=False)
            panel.text = "before"
            cards.panel = panel
            with patch("taskweave.desktop.components.step_contexts.ContextCards", return_value=cards):
                page.render(panel)
            operation = asyncio.create_task(cards.move_entry(entries[0], "down"))
            await entered.wait()
            page.dispose()
            release.set()
            await operation
            self.assertEqual([entry["context_id"] for entry in page.state.entries], ["a", "b"])
            self.assertEqual(cards.panel.text, "before")

        asyncio.run(scenario())

    def test_late_context_card_delete_cannot_mutate_shared_entries_after_dispose(self):
        class ConfirmDialog:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def __await__(self):
                async def result(): return True
                return result().__await__()

        async def scenario():
            entered, release = asyncio.Event(), asyncio.Event()
            entry = {"context_id":"a", "name":"A", "provider_id":"p", "captures":[], "revision":1}
            controller = MagicMock()
            async def delete(*_args, **_kwargs):
                entered.set(); await release.wait()
            controller.call = AsyncMock(side_effect=delete)
            page = StepContextPanel(controller, ContextPageState(entries=[entry]), lambda:"step", None, None, None, AsyncMock())
            cards = object.__new__(ContextCards)
            cards.entries, cards.delete, cards.panel = page.state.entries, page.remove_group, MagicMock()
            card_control = MagicMock()
            cards.cards = {"a":{"card":card_control}}
            cards.empty = MagicMock()
            cards.is_active = lambda: page._active(0)
            panel = MagicMock(is_deleted=False)
            with patch("taskweave.desktop.components.step_contexts.ContextCards", return_value=cards):
                page.render(panel)
            with patch("taskweave.desktop.contexts.ui") as fake_ui:
                fake_ui.dialog.return_value = ConfirmDialog()
                fake_ui.card.return_value.classes.return_value = MagicMock(__enter__=MagicMock(), __exit__=MagicMock(return_value=False))
                operation = asyncio.create_task(cards.remove(entry))
                await entered.wait()
                page.dispose()
                release.set()
                await operation
            self.assertEqual(page.state.entries, [entry])
            self.assertIn("a", cards.cards)
            card_control.delete.assert_not_called()

        asyncio.run(scenario())

    def test_rendered_context_confirm_button_suppresses_overlapping_submissions(self):
        class Widget:
            def __init__(self, value=None): self.value, self.enabled, self.is_deleted = value, True, False
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def classes(self, *_args): return self
            def props(self, *_args, **_kwargs): return self
            def style(self, *_args, **_kwargs): return self
            def on_value_change(self, *_args, **_kwargs): return self
            def disable(self): self.enabled = False
            def set_enabled(self, value): self.enabled = value
            def set_visibility(self, _value): return self
            def open(self): return self
            def close(self): return self
            def clear(self): return self

        async def scenario():
            from taskweave.desktop.workbench import Workbench
            started, release = asyncio.Event(), asyncio.Event()
            persisted = []
            buttons = {}
            ui = MagicMock()
            for name in ("dialog", "card", "row", "column", "input", "textarea", "select", "checkbox", "label", "expansion"):
                getattr(ui, name).side_effect = lambda *args, **kwargs: Widget(kwargs.get("value"))
            def make_button(*args, **kwargs):
                button = Widget()
                if args:
                    buttons[args[0]] = kwargs.get("on_click")
                return button
            ui.button.side_effect = make_button
            async def call(operation, **kwargs):
                if operation == "run.context.sessions": return []
                if operation == "context.save_batch":
                    persisted.append(kwargs)
                    started.set()
                    await release.wait()
                    return {"group":{"context_id":"ctx", "provider_id":"p", "name":"Group", "captures":[]}}
                raise AssertionError(operation)
            controller = MagicMock()
            controller.call = AsyncMock(side_effect=call)
            controller.plugin_context_requests.return_value = {"p":{"type":"object","properties":{}}}
            workbench = object.__new__(Workbench)
            workbench.busy, workbench._buttons = False, []
            page = StepContextPanel(
                controller, ContextPageState(), lambda:"step", None, None, None, AsyncMock(),
                save_editor=AsyncMock(return_value={"step_id":"step", "capabilities":["p"]}),
                plugin_contributions=lambda _caps:[SimpleNamespace(context_provider_ids=["p"])],
                task_id=lambda:"task", environment_id=lambda:"env", button=workbench.button,
                render_result_view=AsyncMock(),
            )
            with patch("taskweave.desktop.components.step_contexts.ui", ui), patch(
                "taskweave.desktop.components.step_contexts.ValueForm",
                return_value=SimpleNamespace(hide_fields=MagicMock(), values=MagicMock(return_value={})),
            ):
                await page.collect()
                click = buttons["确认保存"]
                first = asyncio.create_task(click())
                await started.wait()
                second = asyncio.create_task(click())
                await asyncio.sleep(0)
                release.set()
                await asyncio.gather(first, second)
            self.assertEqual(len(persisted), 1)
            self.assertEqual([group["context_id"] for group in page.state.entries], ["ctx"])

        from nicegui.client import Client
        from nicegui.page import page
        client = Client(page("/step-context-busy-client"))
        try:
            async def within_client():
                with client:
                    await scenario()
            asyncio.run(within_client())
        finally:
            client.delete()

    def test_stale_context_dialog_confirmation_cannot_write_into_new_step(self):
        class Widget:
            def __init__(self, value=None): self.value, self.enabled, self.is_deleted = value, True, False
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def classes(self, *_args): return self
            def props(self, *_args, **_kwargs): return self
            def style(self, *_args, **_kwargs): return self
            def on_value_change(self, *_args, **_kwargs): return self
            def disable(self): self.enabled = False
            def set_enabled(self, value): self.enabled = value
            def set_visibility(self, _value): return self
            def open(self): return self
            def close(self): return self
            def clear(self): return self

        async def scenario():
            from types import SimpleNamespace
            current_step = ["step-a"]
            buttons, operations = {}, []
            ui = MagicMock()
            for name in ("dialog", "card", "row", "column", "input", "textarea", "select", "checkbox", "label", "expansion"):
                getattr(ui, name).side_effect = lambda *args, **kwargs: Widget(kwargs.get("value"))
            def make_button(*args, **kwargs):
                button = Widget()
                if args: buttons[args[0]] = kwargs.get("on_click")
                return button
            ui.button.side_effect = make_button
            controller = MagicMock()
            async def call(operation, **kwargs):
                operations.append((operation, kwargs.get("step_id") or kwargs.get("task_id")))
                if operation == "run.context.sessions": return []
                if operation == "context.save_batch":
                    return {"group":{"context_id":"late", "provider_id":"p", "name":"Late", "captures":[]}}
                raise AssertionError(operation)
            controller.call = AsyncMock(side_effect=call)
            controller.plugin_context_requests.return_value = {"p":{"type":"object","properties":{}}}
            page = StepContextPanel(
                controller, ContextPageState(), lambda:current_step[0], None, None, None, AsyncMock(),
                save_editor=AsyncMock(return_value={"step_id":"step-a", "capabilities":["p"]}),
                plugin_contributions=lambda _caps:[SimpleNamespace(context_provider_ids=["p"])],
                task_id=lambda:"task", environment_id=lambda:"env",
                button=lambda title, callback, **_kwargs: ui.button(title, on_click=callback),
                render_result_view=AsyncMock(),
            )
            with patch("taskweave.desktop.components.step_contexts.ui", ui), patch(
                "taskweave.desktop.components.step_contexts.ValueForm",
                return_value=SimpleNamespace(hide_fields=MagicMock(), values=MagicMock(return_value={})),
            ):
                await page.collect()
                confirm = buttons["确认保存"]
                page.dispose()
                current_step[0] = "step-b"
                await confirm()
            self.assertEqual(operations, [("run.context.sessions", "task")])
            self.assertEqual(page.state.entries, [])

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
