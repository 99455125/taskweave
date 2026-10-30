"""Execution entry opens a separate combination launcher, preserving editor work."""
import asyncio
import tempfile
import unittest
from types import SimpleNamespace
from nicegui import ui
from nicegui.client import Client
from nicegui.page import page
from taskweave.application.service import Application
from taskweave.desktop.controller import DesktopController
from taskweave.desktop.workbench import Workbench
from taskweave.presentation.sequences import SequenceDraft
from taskweave.desktop.state import ExecutionPageState


class SequenceExecutionEntry(unittest.TestCase):
    def test_launch_uses_selected_combination_without_replacing_editor_draft(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as home, Application(home) as app:
                task = app.tasks.create('task')['task_id']
                step = app.steps.save(task, {'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data={})'})
                await asyncio.to_thread(app.steps.confirm_manual, step['step_id'], step['content_hash'])
                app.tasks.confirm_flow(task, app.tasks.definition_hash(task))
                definition = app.sequences.save(name='combo', input_schema={}, nodes=[{'node_id': 'call', 'task_id': task, 'environment_id': None, 'inputs': {}, 'step_inputs': {}}])
                host = object.__new__(Workbench)
                host.controller = DesktopController(app)
                host.page, host.page_generation = 'executions', 1
                host.execution_state = ExecutionPageState()
                host.sequences_page = SimpleNamespace(draft=SequenceDraft())
                host.sequences_page.draft.name = 'keep unsaved editor'
                host.button = lambda label, callback, **options: ui.button(label, on_click=callback)
                routes = []
                async def navigate(route): routes.append(route)
                host.navigate = navigate
                client = Client(page('/sequence-launch-entry'))
                try:
                    with client:
                        await host.open_sequence_execution(definition['sequence_id'])
                        launch = host._sequence_execution_launchers[definition['sequence_id']]
                        self.assertEqual(launch.draft.sequence_id, definition['sequence_id'])
                        self.assertEqual(host.sequences_page.draft.name, 'keep unsaved editor')
                        await launch.start()
                        self.assertEqual(routes, ['executions'])
                        self.assertEqual(host.sequences_page.draft.name, 'keep unsaved editor')
                        self.assertIsNone(host.sequences_page.draft.selected_run_id)
                        self.assertEqual(host.execution_state.run_id, launch.draft.selected_run_id)
                        self.assertEqual(app.sequences.run_get(host.execution_state.run_id)['snapshot']['mode'], 'EXECUTION')
                finally:
                    client.delete()
        asyncio.run(scenario())
