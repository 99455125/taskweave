"""Top-level combinations stay in executions and own their child controls."""
import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from nicegui import ui
from nicegui.client import Client
from nicegui.page import page
from taskweave.desktop.components.execution_details import ExecutionDetails
from taskweave.desktop.pages.executions import ExecutionsPage
from taskweave.desktop.pages.sequences import SequencesPage
from taskweave.desktop.state import ExecutionPageState


class UnifiedExecutionsTests(unittest.TestCase):
    def test_interrupted_cleanup_offers_retry_delete(self):
        from taskweave.desktop.components.sequence_execution import SequenceExecution
        client = Client(page('/retry-combination-cleanup'))
        async def scenario():
            with client:
                labels = []
                def button(title, cb, **kw):
                    labels.append(title)
                    return ui.button(title, on_click=cb)
                view = SequenceExecution(SimpleNamespace(), button, AsyncMock(), identity=lambda: 'current')
                await view._run_controls({'sequence_run_id': 'run', 'status': 'DELETING'})
                self.assertIn('重试删除', labels)
        try:
            asyncio.run(scenario())
        finally:
            client.delete()

    def test_control_dialogs_discard_response_after_selection_changes(self):
        from taskweave.desktop.components.sequence_execution import SequenceExecution
        client = Client(page('/unified-stale-controls'))
        async def scenario():
            with client:
                selection = ['first']
                async def stale(*args, **kwargs):
                    selection[0] = 'second'
                    return {}
                view = SequenceExecution(SimpleNamespace(call=stale, run_request=stale),
                    lambda title, cb, **kw: ui.button(title, on_click=cb), AsyncMock(),
                    identity=lambda: tuple(selection))
                run = {'sequence_run_id': 'first'}
                member = {'run_id': 'child'}
                for operation in (view._inputs_dialog, view._retry_dialog, view._reconcile_dialog):
                    selection[0] = 'first'
                    await operation(run, member)
                    self.assertFalse(any(isinstance(item, ui.dialog) and item.value
                                         for item in client.elements.values()))
        try:
            asyncio.run(scenario())
        finally:
            client.delete()

    def test_only_combination_renders_in_executions_and_child_is_nested(self):
        client = Client(page('/unified-combination'))
        calls = []
        combo = {'sequence_run_id': 'combo-run', 'sequence_id': 'definition',
                 'status': 'BLOCKED', 'created_at': '2026-10-29', 'error_code': 'CHILD_FAILED',
                 'current_node_id': 'node', 'current_execution_path': '/root/node', 'stop_intent': None,
                 'snapshot': {'name': '组合A', 'nodes': [], 'mode': 'EXECUTION'},
                 'nodes': [{'position': 0, 'task_id': 't', 'node_id': 'node', 'run_id': 'child',
                            'execution_path': '/root/node', 'status': 'BLOCKED'}]}
        async def call(operation, **params):
            calls.append((operation, params))
            return {'task.list': [{'task_id': 't', 'name': '子任务'}],
                    'sequence.list': [{'sequence_id': 'definition', 'name': '组合A'}],
                    'run.list': [{'run_id': 'child', 'task_id': 't', 'mode': 'EXECUTION',
                                  'status': 'FAILED', 'sequence_run_id': 'combo-run'}],
                    'sequence.run.list': [combo], 'environment.list': []}[operation]
        async def scenario():
            with client:
                state = ExecutionPageState()
                button = lambda title, cb, **kw: ui.button(title, on_click=cb)
                details = ExecutionDetails(SimpleNamespace(call=call), state, button,
                    lambda: 'executions', lambda: 1, *[AsyncMock() for _ in range(6)])
                async def render_runs():
                    state.execution_rows = ui.column()
                    await details.render_rows()
                screen = ExecutionsPage(SimpleNamespace(call=call), state, button, render_runs)
                await screen.render()
                rows = list(state.execution_list_area.descendants())
                self.assertIn('组合A', [item.text for item in rows if isinstance(item, ui.button)])
                self.assertNotIn('子任务', [item.text for item in rows if isinstance(item, ui.button)])
                main = list(state.execution_rows.descendants())
                labels = [getattr(item, 'text', '') for item in main]
                self.assertTrue(any('子任务' in label for label in labels))
                self.assertIn('重试步骤', labels)
                self.assertIn('删除执行', labels)
                self.assertFalse(any(op == 'run.get' for op, _ in calls))
                await details.refresh()
                self.assertFalse(any(op == 'run.get' for op, _ in calls))
                details.dispose()
        try:
            asyncio.run(scenario())
        finally:
            client.delete()

    def test_combination_editor_offers_debug_only_and_start_calls_trial(self):
        client = Client(page('/combination-debug-only'))
        async def scenario():
            with client:
                async def call(operation, **params):
                    self.assertEqual(operation, 'sequence.trial')
                    return {'sequence_run_id': 'debug-run'}
                editor = SequencesPage(SimpleNamespace(call=call),
                    lambda title, cb, **kw: ui.button(title, on_click=cb), AsyncMock(), identity=lambda: 'sequences')
                editor.draft.load({'sequence_id': 'saved', 'revision': 1, 'name': '组合',
                                   'description': '', 'input_schema': {}, 'nodes': []})
                await editor._render_editor()
                labels = [getattr(item, 'text', '') for item in client.elements.values()]
                self.assertIn('调试组合', labels)
                self.assertNotIn('执行组合', labels)
                self.assertNotIn('运行历史', [item.label for item in client.elements.values() if isinstance(item, ui.tab)])
                await editor.start()
                self.assertEqual(editor.active_section, 'debug')
        try:
            asyncio.run(scenario())
        finally:
            client.delete()
