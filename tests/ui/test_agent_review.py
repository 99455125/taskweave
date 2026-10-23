"""Real NiceGUI acceptance controls bind the displayed report fingerprint."""
import asyncio
from nicegui import ui
from nicegui.client import Client
from nicegui.page import page
from tests._core_fixture import CoreFixture
from taskweave.desktop.controller import DesktopController


class AgentReviewUITests(CoreFixture):
    def test_sequence_zero_iteration_control_facts_are_visible_without_action_attempts(self):
        from taskweave.desktop.components.agent_review import ReviewDialog
        task = self.task()
        step = self.step(task)
        self.app.steps.confirm_manual(step['step_id'], step['content_hash'])
        flow = {'version': 2, 'root': {'id': 'root', 'kind': 'sequence', 'children': [{'id': 'each', 'kind': 'foreach', 'items': {'literal': []}, 'body': {'id': 'body', 'kind': 'sequence', 'children': [{'id': 'action', 'kind': 'action', 'step_id': step['step_id']}]}}]}}
        self.app.tasks.save_flow(task, flow, self.app.tasks.definition_hash(task))
        self.app.tasks.confirm_flow(task, self.app.tasks.definition_hash(task))
        sequence = self.app.sequences.save('空循环组合', [{'node_id': 'one', 'task_id': task, 'environment_id': None, 'inputs': {}, 'step_inputs': {}}], {'type': 'object'})
        run = self.app.agent.execute('sequence.start', {'sequence_id': sequence['sequence_id'], 'inputs': {}}, 'ui-zero-loop')
        self.assertEqual(self.app.agent.wait(run['sequence_run_id'], kind='sequence', timeout=10)['status'], 'SUCCEEDED')
        client = Client(page('/acceptance-sequence-zero'))
        async def scenario():
            with client:
                dialog = ReviewDialog(DesktopController(self.app), lambda label, callback, **options: ui.button(label, on_click=callback))
                await dialog.open('sequence', run['sequence_run_id'])
                self.assertEqual(dialog._attempts, [])
                self.assertTrue(any(visit['kind'] == 'foreach' for visit in dialog._flows))
                self.assertTrue(all(visit['node_id'] == 'one' for visit in dialog._flows))
        try:
            asyncio.run(scenario())
        finally:
            client.delete()
    def test_open_read_and_human_decision(self):
        from taskweave.desktop.components.agent_review import ReviewDialog
        task = self.task()
        step = self.step(task)
        self.confirm(step)
        run = self.run_task(task)
        client = Client(page('/acceptance-test'))
        buttons = {}
        def button(label, callback, **kwargs):
            buttons[label] = callback
            return ui.button(label, on_click=callback)
        async def scenario():
            with client:
                dialog = ReviewDialog(DesktopController(self.app), button)
                await dialog.open('run', run['run_id'])
                self.assertEqual(dialog.report['automatic_status'], 'UNCONFIGURED')
                self.assertIn('查看原始结果', buttons)
                dialog.note.value = '已打开结果并人工核对'
                await buttons['验收通过']()
                self.assertEqual(dialog.report['human_status'], 'ACCEPTED')
                self.assertEqual(self.app.agent.reviews.read('run', run['run_id'])['human_decision']['source'], 'desktop_user')
        try:
            asyncio.run(scenario())
        finally:
            client.delete()
