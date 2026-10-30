"""One-line scene selection and explicit history selection feed actual trials."""
import asyncio
import json
import tempfile
import unittest
from nicegui import ui
from nicegui.client import Client
from nicegui.page import page as page_route
from taskweave.application.service import Application
from taskweave.desktop.controller import DesktopController
from taskweave.presentation.state import DebugState


class DebugSources(unittest.TestCase):
    def test_new_or_existing_scene_is_an_explicit_selection(self):
        from taskweave.desktop.components.debug_sources import DebugSources
        async def scenario():
            with tempfile.TemporaryDirectory() as home, Application(home) as app:
                a = app.tasks.create('A')['task_id']
                step = app.steps.save(a, {'name': 'step'})
                state = DebugState()
                with Client(page_route('/debug-sources')):
                    sources = DebugSources(DesktopController(app), state, step, lambda: None, lambda: True)
                    await sources.render()
                    self.assertEqual(state.scene, {})
                    self.assertIn('新建现场', sources.scene.options.values())
        asyncio.run(scenario())

    def test_expired_selection_is_visible_and_is_not_silently_new(self):
        from taskweave.desktop.components.debug_sources import DebugSources
        async def scenario():
            with tempfile.TemporaryDirectory() as home, Application(home) as app:
                task = app.tasks.create('A')['task_id']
                step = app.steps.save(task, {'name': 'step'})
                state = DebugState(scene={'run_id': 'old', 'session_id': 'expired'})
                with Client(page_route('/debug-sources')):
                    sources = DebugSources(DesktopController(app), state, step, lambda: None, lambda: True)
                    await sources.render()
                    self.assertEqual(sources.scene.value, 'expired')
                    self.assertIn('已结束', sources.scene.options['expired'])
                    self.assertEqual(state.scene['run_id'], 'old')
        asyncio.run(scenario())


    def test_loop_result_selection_is_visible_after_restore(self):
        from taskweave.desktop.components.debug_sources import DebugSources
        class Metadata:
            async def call(self, operation, **params):
                if operation == 'run.list': return [{'run_id': 'source'}]
                return {'run_id': 'source', 'environment_id': None, 'attempts': [
                    {'step_id': 'producer', 'valid': 1, 'status': 'SUCCEEDED', 'execution_path': '/root/loop/0/producer'},
                    {'step_id': 'producer', 'valid': 1, 'status': 'SUCCEEDED', 'execution_path': '/root/loop/1/producer'}]}
        async def scenario():
            state = DebugState(source_run_id='source', source_paths={'producer': '/root/loop/1/producer'})
            step = {'step_id': 'consumer', 'task_id': 'task',
                    'bindings': {'x': {'ref': {'source': 'step', 'step_id': 'producer', 'pointer': ''}}}}
            client = Client(page_route('/debug-loop-result'))
            try:
                with client:
                    sources = DebugSources(Metadata(), state, step, lambda: None, lambda: True)
                    await sources.render_results()
                    control = next(el for el in client.elements.values() if isinstance(el, ui.select)
                                   and (el._props.get('label') or '').startswith('结果实例'))
                    self.assertEqual(control.value, '/root/loop/1/producer')
            finally:
                client.delete()
        asyncio.run(scenario())


if __name__ == '__main__': unittest.main()
