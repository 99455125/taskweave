"""A real context panel collects from the selected retained branch worker."""

import asyncio
from unittest.mock import AsyncMock

from nicegui import ui
from nicegui.client import Client
from nicegui.page import page

from tests.test_flow_parallel import ParallelFixture
from tests import test_flow_parallel_context as parallel_context
from taskweave.application.service import Application
from taskweave.desktop.controller import DesktopController
from taskweave.desktop.components.step_contexts import StepContextPanel
from taskweave.desktop.state import ContextPageState


class BranchContextPanelTests(ParallelFixture):
    paused_group = parallel_context.ParallelContextTests.paused_group

    def setUp(self):
        super().setUp()
        self.app.close()
        self.app = Application(self.home, registry_factory='tests.test_context_recording_runtime:build_registry')

    def test_selected_branch_identity_reaches_real_capture(self):
        task, run, step, _ = self.paused_group()
        client = Client(page('/branch-context-source'))
        controller = DesktopController(self.app)
        callbacks = {}
        def button(label, callback, **kwargs):
            callbacks[label] = callback
            return ui.button(label, on_click=callback)
        async def scenario():
            with client:
                panel = StepContextPanel(controller, ContextPageState(), lambda: step['step_id'], None, None, None, AsyncMock(),
                    save_editor=AsyncMock(return_value=step), plugin_contributions=controller.plugin_contributions,
                    task_id=lambda: task, environment_id=lambda: None, button=button)
                await panel.collect()
                selector = next(element for element in client.elements.values() if isinstance(element, ui.select)
                                and any(isinstance(key, str) and key.startswith(run['run_id'] + '|') for key in element.options))
                keys = [key for key in selector.options if key]
                self.assertEqual(len(keys), 1, 'A different step branch must not be offered as this step session')
                selector.set_value(keys[0])
                await asyncio.sleep(0)
                await callbacks['采集一项']()
                workspace = next(iter(controller._collection_workspaces.values()))
                self.assertEqual(len(workspace.draft.entries), 1)
                capture = workspace.draft.entries[0]
                self.assertEqual(capture['source_session_id'], keys[0])
                self.assertTrue(capture['capture']['execution_path'].startswith('/root/choose/a/'))
                self.assertEqual(capture['capture']['items'][0]['content'], 'main')
                panel.dispose()
        try:
            asyncio.run(scenario())
        finally:
            client.delete()
