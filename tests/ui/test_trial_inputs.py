"""Environment refresh treats input controls as drafts, not submissions."""

import unittest
from types import SimpleNamespace

from taskweave.desktop.components.trial_inputs import _apply_draft, _draft_edits, _validated_partial_values
from taskweave.core.validation import TaskError


class TrialInputDraftTests(unittest.TestCase):
    def test_real_controls_restore_raw_draft_and_submit_without_reading_widgets(self):
        import asyncio
        import json
        from nicegui.client import Client
        from nicegui.page import page
        from taskweave.presentation.state import DebugState
        from taskweave.desktop.components.trial_inputs import TrialInputPanel
        from taskweave.desktop.components.step_editor import StepEditor

        async def scenario():
            schema = {'properties': {'org': {'type': 'string'}, 'settings': {'type': 'object'}}, 'required': ['org']}
            async def call(operation, **kwargs):
                if operation == 'task.get': return {'input_schema_json': json.dumps(schema)}
                if operation == 'environment.list':
                    return [{'environment_id': name, 'public_config_json': json.dumps({'org': name, 'settings': {}})} for name in ('old', 'new')]
                raise AssertionError(operation)
            panel = TrialInputPanel(SimpleNamespace(call=call), lambda: 'task', str)
            handlers = []
            environment = SimpleNamespace(value='old', on_value_change=handlers.append)
            step = {'step_id': 'step', 'input_schema': {'properties': {}}, 'bindings': {}}
            form = await panel.render(step, environment)
            state = DebugState()
            form.input_draft.bind(state, ('task', 'step'))
            form.task_form.controls['org'][1].value = ''
            form.task_form.controls['settings'][1].value = '{"unfinished":'
            self.assertEqual(state.task_inputs['raw']['settings'], '{"unfinished":')
            await handlers[0](SimpleNamespace(value='new'))
            self.assertEqual(form.task_form.controls['org'][1].value, '')
            self.assertEqual(form.task_form.controls['settings'][1].value, '{"unfinished":')
            editor = SimpleNamespace(view={'trial_form': form}, state=SimpleNamespace(task_id='task', step_id='step'))
            snapshot = StepEditor.snapshot_debug_inputs(editor)
            self.assertEqual(snapshot['environment_id'], 'new')
            restored = await panel.render(step, SimpleNamespace(value='new', on_value_change=lambda _: None))
            restored.apply_task_values(snapshot['task'])
            self.assertEqual(restored.task_form.controls['settings'][1].value, '{"unfinished":')
            self.assertEqual(restored.task_form.controls['org'][1].value, '')
            restored.task_form.controls['org'][1].value = 'fixed'
            restored.task_form.controls['settings'][1].value = '{"ok":true}'
            restored.task_form.values = lambda: self.fail('submission read widgets')
            restored.task_form.controls.clear()
            self.assertEqual(restored.values(), {'org': 'fixed', 'settings': {'ok': True}})

        client = Client(page('/trial-input-state-owner'))
        try:
            async def within_client():
                with client: await scenario()
            asyncio.run(within_client())
        finally:
            client.delete()

    def test_paused_run_uses_its_frozen_task_schema_and_task_id(self):
        import asyncio
        import json
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page
        from taskweave.desktop.components.trial_inputs import TrialInputPanel

        async def scenario():
            calls = []
            async def call(operation, **kwargs):
                calls.append((operation, kwargs))
                if operation == "environment.list": return []
                raise AssertionError(f"unexpected {operation}")
            panel = TrialInputPanel(SimpleNamespace(call=call, execution_inputs=lambda _run_id: asyncio.sleep(0, result={"task": {}, "steps": {}})), lambda: None, str)
            task_snapshot = {"task_id": "deleted-or-unselected", "input_schema_json": json.dumps({
                "type": "object", "properties": {"frozen": {"type": "string"}}, "required": ["frozen"]
            })}
            run = {"run_id": "run", "task_id": "deleted-or-unselected", "environment_id": None,
                   "definition_json": json.dumps({"task": task_snapshot, "steps": [{
                       "step_id": "step", "name": "step", "input_schema": {"type": "object", "properties": {}},
                       "bindings": {},
                   }]})}
            environment = SimpleNamespace(value=None, on_value_change=lambda *_: None)
            form = await panel.render(json.loads(run["definition_json"])["steps"][0], environment, run=run, focus="task")
            self.assertIn("frozen", form.task_form.controls)
            self.assertFalse(any(operation == "task.get" for operation, _ in calls))

        client = Client(page("/trial-input-frozen-run"))
        try:
            async def within_client():
                with client:
                    await scenario()
            asyncio.run(within_client())
        finally:
            client.delete()

    def test_environment_refresh_preserves_blank_required_and_incomplete_json_raw(self):
        before = SimpleNamespace(
            schema={"required": ["org"]},
            controls={
                "org": ("string", SimpleNamespace(value="")),
                "settings": ("object", SimpleNamespace(value='{"unfinished":')),
            },
            defaults={"org": "old-default", "settings": "{}"},
        )
        edits = _draft_edits(before)
        self.assertEqual(edits, {"org": "", "settings": '{"unfinished":'})

        after = SimpleNamespace(
            schema={"required": ["org"]},
            controls={
                "org": ("string", SimpleNamespace(value="new-default")),
                "settings": ("object", SimpleNamespace(value='{"new": true}')),
            },
            defaults={"org": "new-default", "settings": '{"new": true}'},
        )
        _apply_draft(after, edits)
        self.assertEqual(after.controls["org"][1].value, "")
        self.assertEqual(after.controls["settings"][1].value, '{"unfinished":')
        self.assertEqual(_draft_edits(after, edits), edits)

    def test_user_can_discard_a_preserved_override_by_restoring_current_default(self):
        form = SimpleNamespace(
            schema={"required": ["org"]},
            controls={"org": ("string", SimpleNamespace(value="new-default"))},
            defaults={"org": "new-default"},
        )
        self.assertEqual(_draft_edits(form, {"org": "typed-value"}), {})

    def test_empty_required_value_overrides_a_new_environment_default(self):
        form = SimpleNamespace(
            schema={"required": ["org"]},
            controls={"org": ("string", SimpleNamespace(value=""))},
            defaults={"org": "environment-org"},
        )
        self.assertEqual(_draft_edits(form), {"org": ""})

    def test_deferred_run_draft_allows_missing_required_but_validates_supplied_values(self):
        form = SimpleNamespace(
            schema={"type": "object", "properties": {"org": {"type": "string"}, "count": {"type": "integer"}}, "required": ["org"]},
            controls={
                "org": ("string", SimpleNamespace(value="")),
                "count": ("integer", SimpleNamespace(value=3.0)),
            },
        )
        self.assertEqual(_validated_partial_values(form), {"count": 3})
        form.controls["count"][1].value = 3.5
        with self.assertRaises(TaskError):
            _validated_partial_values(form)


if __name__ == "__main__":
    unittest.main()
