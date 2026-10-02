"""Pause-time input validation can recover after required values are entered."""

import unittest
from types import SimpleNamespace

from taskweave.desktop.components.run_inputs import input_validation
from taskweave.desktop.components.run_inputs import RunInputDialog
from unittest.mock import AsyncMock
import asyncio
import tempfile
import json
from taskweave.desktop.state import RunInputState


class RunInputValidationTests(unittest.TestCase):
    def test_viewing_paused_run_registers_manual_entry_without_building_or_opening_dialog(self):
        async def scenario():
            dialog, state, entries, forms, identity, controller, run = self.input_fixture()
            await dialog.show(run)
            self.assertEqual(list(entries), ['补充必录参数'])
            self.assertIsNone(state.dialog)
            forms.assert_not_awaited()
            controller.call.assert_not_awaited()
        self.in_client(scenario)

    def test_paused_run_switch_and_repaint_keep_incomplete_draft_without_reopening(self):
        async def scenario():
            dialog, state, entries, forms, identity, controller, run = self.input_fixture()
            await dialog.show(run)
            await self.open_entry(entries)
            self.assertTrue(state.dialog.value)
            form = forms.return_value
            form.task_form.controls['settings'][1].value = '{incomplete'
            state.dialog.close()
            old = state.dialog
            identity[0] += 1
            await dialog.show({**run, 'run_id': 'other'})
            identity[0] += 1
            await dialog.show(run)
            self.assertFalse(state.dialog.value)
            await self.open_entry(entries)
            self.assertEqual(forms.return_value.task_form.controls['settings'][1].value, '{incomplete')
            self.assertTrue(old.is_deleted)
            controller.call.assert_not_awaited()
        self.in_client(scenario)

    def test_pending_inputs_dialog_lives_outside_refreshable_content(self):
        async def scenario():
            dialog, state, entries, forms, identity, controller, run = self.input_fixture()
            await dialog.show(run)
            await self.open_entry(entries)
            dialog.content().clear()
            self.assertFalse(state.dialog.is_deleted)
            self.assertTrue(state.dialog.value)
        self.in_client(scenario)

    def test_stale_input_request_cannot_resume_replacement_request(self):
        async def scenario():
            dialog, state, entries, forms, identity, controller, run = self.input_fixture()
            await dialog.show(run)
            await self.open_entry(entries)
            request = controller.run_request.return_value
            request['waiting_input']['id'] = 'replacement'
            self.assertFalse(await dialog.resume_inputs(run, {'org': 'value'}, expected_request=('run-a', 'request-a', 'task', 'step-a')))
            controller.call.assert_not_awaited()
        self.in_client(scenario)

    def test_submit_failure_retains_draft_and_displays_error(self):
        async def scenario():
            from taskweave.core.validation import TaskError
            dialog, state, entries, forms, identity, controller, run = self.input_fixture()
            await dialog.show(run)
            await self.open_entry(entries)
            forms.return_value.task_form.controls['org'][1].value = '草稿'
            controller.call.side_effect = TaskError('INPUT_INVALID', '临时保存失败')
            submit = next(el for el in state.dialog.descendants() if getattr(el, 'text', None) == '提交输入并继续')
            callback = submit._test_click
            await callback()
            labels = [getattr(el, 'text', '') for el in state.dialog.descendants()]
            self.assertTrue(any('临时保存失败' in text for text in labels))
            self.assertEqual(state.drafts[('run-a', 'request-a', 'task', 'step-a')]['task']['org'], '草稿')
            self.assertTrue(state.dialog.value)
        self.in_client(scenario)

    def test_slow_double_submit_writes_and_resumes_only_once(self):
        async def scenario():
            dialog, state, entries, forms, identity, controller, run = self.input_fixture()
            await dialog.show(run)
            await self.open_entry(entries)
            forms.return_value.task_form.controls['org'][1].value = '草稿'
            entered, release = asyncio.Event(), asyncio.Event()
            async def call(operation, **kwargs):
                if operation == 'run.inputs':
                    entered.set()
                    await release.wait()
            controller.call.side_effect = call
            submit = next(el for el in state.dialog.descendants() if getattr(el, 'text', None) == '提交输入并继续')
            callback = submit._test_click
            first = asyncio.create_task(callback())
            await entered.wait()
            await callback()
            release.set()
            await first
            self.assertEqual([c.args[0] for c in controller.call.await_args_list], ['run.inputs', 'run.start'])
            self.assertFalse(state.dialog.value)
            self.assertEqual(state.drafts, {})
        self.in_client(scenario)

    @staticmethod
    async def open_entry(entries):
        result = entries['补充必录参数']()
        if asyncio.iscoroutine(result):
            await result

    @staticmethod
    def in_client(scenario):
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page
        from unittest.mock import patch
        original_button = ui.button
        def button(*args, **kwargs):
            control = original_button(*args, **kwargs)
            control._test_click = kwargs.get('on_click')
            return control
        client = Client(page('/run-input-lifecycle'))
        try:
            async def run():
                with client, patch('taskweave.desktop.components.run_inputs.ui.button', side_effect=button):
                    await scenario()
            asyncio.run(run())
        finally:
            client.delete()

    @staticmethod
    def input_fixture():
        from nicegui import ui
        from taskweave.desktop.components.trial_inputs import _apply_draft
        from taskweave.desktop.forms import ValueForm
        identity, entries = [1], {}
        schema = {'type': 'object', 'properties': {'org': {'type': 'string'}, 'settings': {'type': 'object'}}, 'required': ['org']}
        step = {'step_id': 'step-a', 'input_schema': {'type': 'object', 'properties': {}}, 'bindings': {}}
        run = {'run_id': 'run-a', 'status': 'PAUSED', 'environment_id': None, 'definition_json': json.dumps({'steps': [step]})}
        controller = SimpleNamespace(run_request=AsyncMock(return_value={
            'waiting_input': {'id': 'request-a', 'scope': 'task', 'step_id': 'step-a', 'schema': schema, 'values': {}},
            'last_command': {'mode': 'ALL'},
        }), call=AsyncMock())
        forms = AsyncMock()
        async def build(*args, **kwargs):
            task_form = ValueForm(schema)
            step_form = ValueForm(step['input_schema'])
            form = SimpleNamespace(task_form=task_form, step_form=step_form,
                task_values=task_form.values, step_values=step_form.values,
                apply_task_values=lambda values: _apply_draft(task_form, values),
                apply_step_values=lambda values: _apply_draft(step_form, values))
            forms.return_value = form
            return form
        forms.side_effect = build
        content = ui.column()
        state = RunInputState()
        dialog = RunInputDialog(controller, state,
            lambda title, callback, **kwargs: entries.__setitem__(title, callback),
            forms, lambda: content, identity=lambda rid: (identity[0], rid),
            apply_inputs=AsyncMock(), invalidate_signatures=AsyncMock())
        return dialog, state, entries, forms, identity, controller, run

    def test_real_paused_run_input_submission_resumes_original_target(self):
        from taskweave.application.service import Application
        from taskweave.desktop.controller import DesktopController

        async def submit(app, run):
            identity = ("executions", 7, run["run_id"])
            controller = DesktopController(app)
            dialog = RunInputDialog(
                controller, SimpleNamespace(dialog_token=None, dialog=None), AsyncMock(),
                AsyncMock(), lambda: None, identity=lambda _run_id=None: identity,
                apply_inputs=AsyncMock(), invalidate_signatures=AsyncMock(),
            )
            self.assertTrue(await dialog.resume_inputs(run, {"org": "local-org"}, expected_identity=identity))
            return await asyncio.to_thread(app.coordinator.wait, run["run_id"], timeout=10)

        with tempfile.TemporaryDirectory(prefix="taskweave-home-input-") as home:
            app = Application(home)
            try:
                task = app.repo.create_task("frozen input", {"type": "object", "properties": {"org": {"type": "string"}}, "required": ["org"]})
                step = app.repo.save_step(task["task_id"], {"name": "local", "step_content": 'async def run(ctx, inputs):\n    return ctx.result(data={"org": inputs["org"]})\n'})
                app.confirm_step_manual(step["step_id"], step["content_hash"])
                run = app.create_run(task["task_id"], defer_inputs=True)
                app.coordinator.start(run["run_id"], "pause-for-input", mode="UNTIL", target_step_id=step["step_id"])
                self.assertEqual(app.coordinator.wait(run["run_id"], timeout=10)["status"], "PAUSED")
                result = asyncio.run(submit(app, app.repo.run_details(run["run_id"])))
                self.assertEqual(result["status"], "SUCCEEDED")
                request = app.runs.request(run["run_id"])
                self.assertEqual(request["last_command"]["mode"], "UNTIL")
                self.assertEqual(request["last_command"]["target"], step["step_id"])
                self.assertEqual(app.runs.input_values(run["run_id"])["task"]["org"], "local-org")
            finally:
                app.close()

    def test_run_input_dialog_owns_resume_call_order_and_editor_apply(self):
        async def scenario():
            identity = ["editor", 3, "task", "step", 2]
            events = []
            controller = SimpleNamespace(
                run_request=AsyncMock(return_value={
                    "waiting_input": {
                        "scope":"task", "step_id":"step", "schema":{
                            "type":"object", "properties":{"org":{"type":"string"}}, "required":["org"],
                        },
                    },
                    "last_command":{"mode":"ONE", "target":"step"},
                }),
                call=AsyncMock(side_effect=lambda action, **kwargs: events.append((action, kwargs))),
            )
            async def apply(waiting, values, captured_identity):
                events.append(("apply", waiting["step_id"], values, captured_identity))
            async def invalidate(captured_identity): events.append(("invalidate", captured_identity))
            dialog = RunInputDialog(
                controller, SimpleNamespace(dialog_token=None, dialog=None), AsyncMock(),
                AsyncMock(), lambda: None,
                identity=lambda _run_id=None: tuple(identity), apply_inputs=apply, invalidate_signatures=invalidate,
            )
            run = {"run_id":"run-1"}
            self.assertTrue(await dialog.resume_inputs(run, {"org":"org-1"}, {"step":{"x":1}}, expected_identity=tuple(identity)))
            self.assertEqual([event[0] for event in events], ["run.inputs", "apply", "run.start", "invalidate"])
            self.assertEqual(events[0][1]["step_inputs"], {"step":{"x":1}})
            self.assertEqual(events[2][1]["mode"], "ONE")
            self.assertEqual(events[2][1]["target_step_id"], "step")
        asyncio.run(scenario())

    def test_run_input_dialog_stops_after_identity_changes_during_request(self):
        async def scenario():
            entered, release = asyncio.Event(), asyncio.Event()
            identity = ["editor", 3, "task", "step-a", 2]
            async def get_request(_run_id):
                entered.set()
                await release.wait()
                return {"waiting_input":{"scope":"step", "step_id":"step-a", "schema":{"type":"object"}}}
            controller = SimpleNamespace(run_request=get_request, call=AsyncMock())
            dialog = RunInputDialog(
                controller, SimpleNamespace(dialog_token=None, dialog=None), AsyncMock(),
                AsyncMock(), lambda: None,
                identity=lambda _run_id=None: tuple(identity), apply_inputs=AsyncMock(), invalidate_signatures=AsyncMock(),
            )
            pending = asyncio.create_task(dialog.resume_inputs({"run_id":"run-1"}, {}, expected_identity=tuple(identity)))
            await entered.wait()
            identity[:] = ["editor", 4, "task", "step-b", 3]
            release.set()
            self.assertFalse(await pending)
            dialog.controller.call.assert_not_awaited()
        asyncio.run(scenario())

    def test_run_input_write_finishes_original_run_after_page_changes(self):
        async def scenario():
            identity = ["editor", 3, "task", "step-a", 2]
            events = []
            async def call(action, **kwargs):
                events.append((action, kwargs))
                if action == "run.inputs":
                    identity[:] = ["editor", 4, "task", "step-b", 3]
            controller = SimpleNamespace(
                run_request=AsyncMock(return_value={
                    "waiting_input":{"scope":"step", "step_id":"step-a", "schema":{"type":"object"}},
                    "last_command":{"mode":"ONE", "target":"step-a"},
                }), call=call,
            )
            apply = AsyncMock()
            invalidate = AsyncMock()
            dialog = RunInputDialog(
                controller, SimpleNamespace(dialog_token=None, dialog=None), AsyncMock(),
                AsyncMock(), lambda: None, identity=lambda _run_id=None: tuple(identity),
                apply_inputs=apply, invalidate_signatures=invalidate,
            )
            self.assertFalse(await dialog.resume_inputs({"run_id":"run-a"}, {"x":1}))
            self.assertEqual([action for action, _ in events], ["run.inputs", "run.start"])
            self.assertEqual(events[1][1]["run_id"], "run-a")
            apply.assert_not_awaited()
            invalidate.assert_not_awaited()
        asyncio.run(scenario())

    def test_missing_value_is_reported_without_revalidating_through_the_form(self):
        control = SimpleNamespace(value="")
        form = SimpleNamespace(
            task_form=SimpleNamespace(controls={"org": ("string", control)}),
            step_form=SimpleNamespace(controls={}),
            task_values=lambda: (_ for _ in ()).throw(ValueError("org required")) if not control.value else {"org": control.value},
            step_values=lambda: {},
        )
        schema = {"type": "object", "properties": {"org": {"type": "string"}}, "required": ["org"]}

        self.assertEqual(input_validation(form, "task", schema), ["org"])
        control.value = "org-1"
        self.assertEqual(input_validation(form, "task", schema, {"type": "object", "properties": {}, "required": []}), [])


if __name__ == "__main__":
    unittest.main()
