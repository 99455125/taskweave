import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from nicegui import ui
from nicegui.client import Client
from nicegui.page import page
from taskweave.desktop.contexts import ContextCards
from taskweave.desktop.components.step_contexts import StepContextPanel
from taskweave.core.validation import TaskError


class ContextTransferUITests(unittest.TestCase):
    def test_group_and_capture_have_transfer_actions(self):
        client = Client(page('/transfer-test'))
        try:
            with client:
                cards = ContextCards([{'context_id': 'g', 'captures': [{'capture_id': 'c'}]}], AsyncMock(), AsyncMock(), transfer=AsyncMock())
                texts = [getattr(e, 'text', '') for e in cards.panel.descendants()]
                self.assertIn('移动采集项…', texts)
                self.assertIn('复制采集项…', texts)
                self.assertIn('移动整组材料…', texts)
        finally:
            client.delete()

    def test_pending_collection_draft_blocks_transfer(self):
        controller = SimpleNamespace(_collection_workspaces={('step', 's', 'g'): object()})
        panel = StepContextPanel(controller, None, lambda: 's', None, None, None, AsyncMock())
        with self.assertRaises(TaskError):
            panel.ensure_transfer_ready('s', 'g')

    def test_dialog_submits_real_copy_with_multiselect(self):
        import tempfile
        from taskweave.application.service import Application
        from taskweave.desktop.controller import DesktopController
        from taskweave.desktop.state import ContextPageState
        with tempfile.TemporaryDirectory() as home, Application(home, registry_factory='tests.test_context_targets_runtime:build_registry') as app:
            task = app.repo.create_task('Transfer')
            step = app.repo.save_step(task['task_id'], {'name': 'Source', 'step_content': 'pass', 'capabilities': ['demo.echo']})
            target = app.repo.save_step(task['task_id'], {'name': 'Target', 'step_content': 'pass', 'capabilities': ['demo.echo']})
            group = app.contexts.save_batch(step['step_id'], None, None, 'demo.page', 'Evidence', '', [
                {'capture': {'items': [{'content': str(n)}]}, 'label': str(n)} for n in range(2)])['group']
            controller = DesktopController(app)
            state = ContextPageState()
            state.entries = [group]
            panel = StepContextPanel(controller, state, lambda: step['step_id'], None, None, None, AsyncMock(), task_id=lambda: task['task_id'])
            client = Client(page('/transfer-integration'))
            async def scenario():
                with client:
                    await panel.transfer_dialog(group, mode='copy')
                    dialog = panel._dialogs[-1]
                    destination = next(e for e in dialog.descendants() if e._props.get('label') == '目标步骤')
                    destination.value = target['step_id']
                    await asyncio.sleep(0.05)
                    button = next(e for e in dialog.descendants() if getattr(e, 'text', '') == '确认复制')
                    import inspect
                    handler = next(e.handler for e in button._event_listeners.values() if e.type == 'click')
                    callback = inspect.getclosurevars(handler).nonlocals['callback']
                    original_call = controller.call
                    entered, release = asyncio.Event(), asyncio.Event()
                    calls = []
                    async def blocked(operation, **params):
                        if operation == 'context.capture.transfer':
                            calls.append(params)
                            entered.set()
                            await release.wait()
                        return await original_call(operation, **params)
                    controller.call = blocked
                    async def invoke():
                        with client: await callback()
                    pending = asyncio.create_task(invoke())
                    await entered.wait()
                    duplicate = asyncio.create_task(invoke())
                    await asyncio.sleep(0)
                    release.set()
                    await asyncio.gather(pending, duplicate)
                    self.assertEqual(len(calls), 1, 'Queued clicks must create only one copy')
                    copied = app.contexts.list(target['step_id'])
                    self.assertEqual(len(copied), 1)
                    self.assertEqual(len(copied[0]['captures']), 2)
                    self.assertEqual(len(app.contexts.list(step['step_id'])[0]['captures']), 2)
            try:
                asyncio.run(scenario())
            finally:
                client.delete()
