"""DEBUG paths use recorded decisions and the run's immutable scope."""
import asyncio
import json
import unittest

from nicegui import ui
from nicegui.client import Client
from nicegui.page import page


def action(sid):
    return {'id': sid, 'kind': 'action', 'step_id': sid}


def sequence(nid, *children):
    return {'id': nid, 'kind': 'sequence', 'children': list(children)}


def attempt(sid, path, status='SUCCEEDED'):
    return {'attempt_id': path, 'step_id': sid, 'execution_path': path,
            'valid': True, 'status': status}


def visit(path, nid, kind, status='SUCCEEDED', **payload):
    return {'execution_path': path, 'node_id': nid, 'kind': kind,
            'status': status, 'payload_json': json.dumps(payload)}


class DebugPathsTests(unittest.TestCase):
    def render(self, root, *, attempts=(), instances=(), status='SUCCEEDED', single=False, steps=None):
        from taskweave.desktop.components import debug_paths
        run = {'run_id': 'debug', 'mode': 'TRIAL', 'status': status,
               'request_json': json.dumps({'flow_trial': not single}),
               'definition_json': json.dumps({'flow': {'version': 2, 'root': root},
                   'steps': [{'step_id': sid, 'name': name} for sid, name in
                             [('a', '冻结动作 A'), ('b', '冻结动作 B')]]}),
               'attempts': list(attempts), 'flow_instances': list(instances)}
        debug_paths.render_debug_paths(run, steps or [{'step_id': 'a', 'name': '当前草稿'}])

    def within_client(self, callback):
        client = Client(page('/debug-paths-' + self._testMethodName))
        async def scenario():
            with client:
                await callback(client)
        try:
            asyncio.run(scenario())
        finally:
            client.delete()

    @staticmethod
    def nodes(client):
        return {el.props['data-node-id']: el for el in client.elements.values()
                if 'tw-flow-node' in el.classes and 'data-node-id' in el.props}

    def test_frozen_definition_and_pending_actions_survive_current_draft_changes(self):
        # Rendering the editor's steps or treating success as full completion loses B.
        async def scenario(client):
            self.render(sequence('main', action('a'), action('b')),
                        attempts=[attempt('a', '/main/a')])
            nodes = self.nodes(client)
            self.assertEqual(set(nodes), {'a', 'b'})
            self.assertIn('is-path-taken', nodes['a'].classes)
            self.assertIn('is-path-pending', nodes['b'].classes)
            texts = [getattr(el, 'text', '') for el in client.elements.values()]
            self.assertIn('冻结动作 A', texts)
            self.assertNotIn('当前草稿', texts)
            connectors = [el for el in client.elements.values() if 'tw-flow-connector' in el.classes]
            self.assertIn('is-path-pending', connectors[-1].classes)
            self.assertFalse(next(el for el in client.elements.values() if isinstance(el, ui.expansion)).value)
        self.within_client(scenario)

    def test_empty_chosen_branch_is_taken_and_other_branch_is_skipped(self):
        async def scenario(client):
            gate = {'id': 'gate', 'kind': 'if', 'cases': [
                {'id': 'yes', 'condition': {'op': 'eq', 'left': {'literal': 1}, 'right': {'literal': 1}},
                 'body': sequence('empty')}], 'default': {'id': 'no', 'body': sequence('other', action('b'))}}
            self.render(sequence('main', gate), instances=[visit('/main/gate', 'gate', 'if', selected=['yes'])])
            branches = {el.props['data-branch-id']: el for el in client.elements.values()
                        if 'data-branch-id' in el.props}
            self.assertEqual(branches['empty'].props['data-path-state'], 'taken')
            self.assertIn('is-path-exited', branches['empty'].classes)
            self.assertEqual(branches['other'].props['data-path-state'], 'skipped')
            self.assertIn('is-path-skipped', self.nodes(client)['b'].classes)
        self.within_client(scenario)

    def test_undecided_branch_remains_pending_after_failure(self):
        async def scenario(client):
            gate = {'id': 'gate', 'kind': 'if', 'cases': [
                {'id': 'yes', 'condition': {'op': 'eq', 'left': {'literal': 1}, 'right': {'literal': 1}},
                 'body': sequence('one', action('a'))}], 'default': {'id': 'no', 'body': sequence('two', action('b'))}}
            self.render(sequence('main', gate), status='FAILED',
                        instances=[visit('/main/gate', 'gate', 'if', status='FAILED')])
            branches = [el for el in client.elements.values() if 'data-branch-id' in el.props]
            self.assertEqual([el.props['data-path-state'] for el in branches], ['pending', 'pending'])
        self.within_client(scenario)

    def test_loop_scope_selection_renders_actual_attempt_for_that_round(self):
        async def scenario(client):
            root = sequence('main', {'id': 'loop', 'kind': 'foreach', 'body': sequence('body', action('a'))})
            self.render(root, attempts=[attempt('a', '/main/loop/0/body/a'),
                                       attempt('a', '/main/loop/1/body/a', 'FAILED')],
                        instances=[visit('/main/loop', 'loop', 'foreach', status='FAILED'),
                                   visit('/main/loop/0', 'loop', 'iteration'),
                                   visit('/main/loop/1', 'loop', 'iteration', status='FAILED')], status='FAILED')
            selector = next(el for el in client.elements.values() if isinstance(el, ui.select))
            self.assertEqual(set(selector.options), {'', '/main/loop/0', '/main/loop/1'})
            self.assertIn('is-failed', self.nodes(client)['a'].classes)
            selector.set_value('/main/loop/0')
            self.assertIn('is-succeeded', self.nodes(client)['a'].classes)
            self.assertNotIn('is-failed', self.nodes(client)['a'].classes)
            selector.set_value('/main/loop/1')
            self.assertIn('is-failed', self.nodes(client)['a'].classes)
        self.within_client(scenario)

    def test_single_trial_contains_only_executed_action_and_its_actual_path(self):
        async def scenario(client):
            # A succeeded single trial does not mark its frozen task's other nodes done.
            self.render(sequence('frozen-root', action('a'), action('b')), single=True,
                        attempts=[attempt('b', '/main/executed-node')])
            nodes = self.nodes(client)
            self.assertEqual(set(nodes), {'executed-node'})
            self.assertIn('is-path-taken', nodes['executed-node'].classes)
            self.assertIn('is-succeeded', nodes['executed-node'].classes)
            self.assertFalse(any(isinstance(el, ui.select) for el in client.elements.values()))
        self.within_client(scenario)
