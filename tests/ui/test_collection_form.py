"""Real NiceGUI collection controls bind shared plain request drafts."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from nicegui import ui
from nicegui.client import Client
from nicegui.page import page
from taskweave.desktop.forms import ValueForm
from taskweave.desktop.components.step_contexts import StepContextPanel
from taskweave.desktop.components.planning_collection import PlanningCollectionView
from taskweave.presentation.state import ContextPageState


class CollectionFormViewTests(unittest.TestCase):
    def exercise(self, planning, targets=False):
        async def scenario():
            calls, actions = [], {}
            schema = {'properties': {'count': {'type': 'integer', 'default': 1}},
                      'x-taskweave-context-view': {'default': True}}
            if targets:
                schema['x-taskweave-context-targets'] = {}
            capture = {'items': [{'kind': 'text', 'source': 'fixture', 'content': 'captured'}], 'views': []}
            async def call(operation, **params):
                calls.append((operation, params))
                if operation == 'run.context.sessions': return []
                if operation in {'context.targets', 'plan.context.targets'}:
                    return {'session_id': 'session', 'targets': [{'target_id': 'tab', 'label': 'Tab', 'request': {'target_id': 'tab'}}]}
                if operation == 'context.read': return capture
                if operation == 'plan.context.read': return {'capture': capture, 'session_id': 'session'}
                raise AssertionError(operation)
            def button(label, action, **kwargs):
                actions[label] = action
                return ui.button(label)
            controller = SimpleNamespace(call=call, plugin_context_requests=lambda: {'p.page': schema})
            if targets:
                from taskweave.desktop.context_recording import collection_workspace
                workspace = collection_workspace(controller, ('plan', 'plan', None) if planning else ('step', 'step', None), [])
                workspace.fields['target'] = 'tab'
            if planning:
                view = PlanningCollectionView()
                view.controller, view.button = controller, button
                view._planning_identity = lambda: ('plan', 1)
                view._identity_is_current = lambda _: True
                await view.collect_dialog({'plan_id': 'plan', 'revision': 1, 'plugin_ids': ['p']})
            else:
                view = StepContextPanel(controller, ContextPageState(), lambda: 'step', None, None, None, AsyncMock(),
                    save_editor=AsyncMock(return_value={'step_id': 'step', 'capabilities': ['p']}),
                    plugin_contributions=lambda _: [SimpleNamespace(context_provider_ids=['p.page'])],
                    task_id=lambda: 'task', environment_id=lambda: 'env', button=button)
                await view.collect()
            workspace = next(iter(controller._collection_workspaces.values()))
            count = next(e for e in ui.context.client.elements.values() if getattr(e, '_props', {}).get('label') == 'count')
            count.value = 4
            name = next(e for e in ui.context.client.elements.values() if getattr(e, '_props', {}).get('label') == '上下文名称')
            name.value = 'Changed'
            self.assertEqual(workspace.fields['name'], 'Changed')
            self.assertEqual(workspace.fields['forms']['p.page']['count'], 4)
            with patch.object(ValueForm, 'values', side_effect=AssertionError('read controls at submit')):
                await actions['采集一项']()
            self.assertEqual(calls[-1][1]['request'], {'count': 4, **({'target_id': 'tab'} if targets else {})})
            if targets:
                self.assertEqual(calls[-1][1]['expected_session_id'], 'session')
            self.assertTrue(calls[-1][1]['include_view'])
            self.assertEqual(len(workspace.draft.entries), 1)

        client = Client(page('/collection-plain-' + str(planning)))
        try:
            async def mounted():
                with client: await scenario()
            asyncio.run(mounted())
        finally:
            client.delete()

    def test_step_collection_uses_event_owned_raw_inputs(self): self.exercise(False)
    def test_plan_collection_uses_event_owned_raw_inputs(self): self.exercise(True)

    def test_plan_restores_target_before_refresh_events_update_fields(self): self.exercise(True, True)
    def test_step_restores_target_before_refresh_events_update_fields(self): self.exercise(False, True)
