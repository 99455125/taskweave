"""Recorded decisions, rather than inferred business conditions, color execution paths."""
import json
import unittest

from taskweave.presentation.execution_paths import ExecutionPaths
from taskweave.core.validation import TaskError


def action(sid):
    return {'id': sid, 'kind': 'action', 'step_id': sid}


def sequence(nid, *children):
    return {'id': nid, 'kind': 'sequence', 'children': list(children)}


def branch(nid='gate'):
    return {'id': nid, 'kind': 'if',
            'cases': [{'id': 'then', 'condition': {'op': 'eq', 'left': {'literal': True}, 'right': {'literal': True}},
                       'body': sequence('yes', action('a'))}], 'default': {'id': 'else', 'body': sequence('no', action('b'))}}


def visit(path, nid, kind='if', status='RUNNING', **payload):
    return {'execution_path': path, 'node_id': nid, 'kind': kind, 'status': status,
            'payload_json': json.dumps(payload)}


def attempt(sid, status='SUCCEEDED', path=None, aid='attempt', valid=True):
    return {'step_id': sid, 'status': status, 'execution_path': path, 'attempt_id': aid, 'valid': valid}


class ExecutionPathsTests(unittest.TestCase):
    def project(self, root, instances=(), attempts=(), status='RUNNING', scope=None):
        return ExecutionPaths({'version': 2, 'root': root},
                              {'status': status, 'flow_instances': list(instances), 'attempts': list(attempts)}, scope=scope)

    def test_chosen_branch_before_first_action_is_reached_and_other_is_skipped(self):
        view = self.project(sequence('root', branch()), [visit('/root/gate', 'gate', selected=['else'])])
        self.assertEqual(view.branches['yes'].state, 'skipped')
        self.assertEqual(view.branches['no'].state, 'taken')
        self.assertEqual(view.branches['no'].completed, 0)
        self.assertEqual(view.nodes['a'].state, 'skipped')
        self.assertEqual(view.nodes['b'].state, 'pending')

    def test_failure_before_decision_leaves_both_branches_pending(self):
        view = self.project(sequence('root', action('first'), branch()),
                            attempts=[attempt('first', 'FAILED', '/main/first')], status='FAILED')
        self.assertEqual(view.branches['yes'].state, 'pending')
        self.assertEqual(view.branches['no'].state, 'pending')
        self.assertEqual(view.nodes['root'].completed, 0)

    def test_condition_error_is_not_a_branch_miss(self):
        view = self.project(sequence('root', branch()), [visit('/root/gate', 'gate', status='FAILED')], status='FAILED')
        self.assertEqual(view.nodes['gate'].state, 'taken')
        self.assertEqual(view.branches['yes'].state, 'pending')
        self.assertEqual(view.branches['no'].state, 'pending')

    def test_real_control_error_suffix_marks_arrival_without_inventing_decision(self):
        view = self.project(sequence('root', action('first'), branch()),
                            [visit('/root/gate/$error', 'gate', 'control', status='FAILED')],
                            [attempt('first', path='/root/first')], status='FAILED')
        self.assertEqual(view.nodes['gate'].state, 'taken')
        self.assertEqual(view.edges[('first', 'gate')].state, 'taken')
        self.assertEqual(view.nodes['gate'].completed, 0)
        self.assertEqual(view.branches['yes'].state, 'pending')
        self.assertEqual(view.branches['no'].state, 'pending')

    def test_cursor_arrival_before_control_evaluation_is_not_a_decision(self):
        flow = {'version': 2, 'root': sequence('root', branch())}
        cursor = {'frames': [{'node_id': 'root', 'kind': 'sequence', 'path': '/root', 'index': 0},
                             {'node_id': 'gate', 'kind': 'if', 'path': '/root/gate'}]}
        view = ExecutionPaths(flow, {'flow_cursor_json': json.dumps(cursor), 'status': 'RUNNING'})
        self.assertEqual(view.nodes['gate'].state, 'taken')
        self.assertEqual(view.branches['yes'].state, 'pending')

    def test_completed_empty_branch_has_traversed_exit(self):
        gate = branch()
        gate['cases'][0]['body'] = sequence('yes')
        view = self.project(sequence('root', gate),
                            [visit('/root/gate', 'gate', status='SUCCEEDED', selected=['then'])], status='SUCCEEDED')
        self.assertEqual(view.branches['yes'].completed, 1)
        self.assertEqual(view.nodes['root'].completed, 1)
        self.assertEqual(view.branches['no'].state, 'skipped')

    def test_loop_overview_and_round_selection_keep_different_decisions_and_attempts(self):
        each = {'id': 'each', 'kind': 'foreach', 'items': {'literal': [1, 2]}, 'body': sequence('body', branch())}
        instances = [visit('/root/each', 'each', 'foreach', items=[1, 2]),
                     visit('/root/each/0/body/gate', 'gate', status='SUCCEEDED', selected=['then']),
                     visit('/root/each/0', 'each', 'iteration', status='SUCCEEDED'),
                     visit('/root/each/1/body/gate', 'gate', selected=['else'])]
        attempts = [attempt('a', path='/root/each/0/body/gate/then/yes/a', aid='round-a'),
                    attempt('b', 'FAILED', '/root/each/1/body/gate/else/no/b', aid='round-b')]
        root = sequence('root', each)
        view = self.project(root, instances, attempts)
        self.assertEqual(view.branches['yes'].reached, 1)
        self.assertEqual(view.branches['yes'].skipped, 1)
        self.assertEqual(view.branches['no'].reached, 1)
        self.assertEqual(view.branches['no'].completed, 0)
        self.assertEqual(view.returns['each'].state, 'taken')
        self.assertEqual(set(view.scopes), {'/root/each/0', '/root/each/1'})
        first = self.project(root, instances, attempts, scope='/root/each/0')
        second = self.project(root, instances, attempts, scope='/root/each/1')
        self.assertEqual(first.branches['no'].state, 'skipped')
        self.assertEqual(second.branches['yes'].state, 'skipped')
        self.assertEqual([a['attempt_id'] for a in first.attempts('a')], ['round-a'])
        self.assertEqual(second.attempts('a'), [])
        self.assertEqual([a['attempt_id'] for a in second.attempts('b')], ['round-b'])
        self.assertEqual(first.returns['each'].state, 'taken')
        self.assertEqual(second.returns['each'].state, 'pending')

    def test_zero_iteration_loop_body_is_not_entered(self):
        each = {'id': 'each', 'kind': 'foreach', 'items': {'literal': []}, 'body': sequence('body', branch())}
        view = self.project(sequence('root', each),
                            [visit('/root/each', 'each', 'foreach', status='SUCCEEDED', items=[])], status='SUCCEEDED')
        self.assertEqual(view.nodes['a'].state, 'not-entered')
        self.assertEqual(view.branches['yes'].state, 'not-entered')
        self.assertNotEqual(view.returns['each'].state, 'taken')

    def test_nested_round_selection_excludes_other_parent_rounds(self):
        inner = {'id': 'inner', 'kind': 'foreach', 'items': {'literal': [1, 2]}, 'body': sequence('ib', branch())}
        outer = {'id': 'outer', 'kind': 'foreach', 'items': {'literal': [1, 2]}, 'body': sequence('ob', inner)}
        instances = [visit('/root/outer', 'outer', 'foreach', items=[1, 2])]
        for outer_index in range(2):
            parent = f'/root/outer/{outer_index}/ob/inner'
            instances.append(visit(parent, 'inner', 'foreach', items=[1, 2]))
            for inner_index in range(2):
                instances.append(visit(f'{parent}/{inner_index}/ib/gate', 'gate',
                                       selected=['then' if inner_index == 0 else 'else']))
        root = sequence('root', outer)
        overview = self.project(root, instances)
        self.assertEqual(len(overview.scopes), 6)
        view = self.project(root, instances, scope='/root/outer/0/ob/inner/1')
        self.assertEqual(view.branches['yes'].reached, 0)
        self.assertEqual(view.branches['yes'].skipped, 1)
        self.assertEqual(view.branches['no'].reached, 1)

    def test_first_round_failure_does_not_highlight_return(self):
        each = {'id': 'each', 'kind': 'foreach', 'items': {'literal': [1, 2]}, 'body': sequence('body', action('a'))}
        view = self.project(sequence('root', each), [visit('/root/each', 'each', 'foreach', items=[1, 2])],
                            [attempt('a', 'FAILED', '/root/each/0/body/a')], status='FAILED')
        self.assertEqual(view.returns['each'].state, 'pending')
        self.assertEqual(view.nodes['each'].completed, 0)

    def test_linear_legacy_attempts_do_not_highlight_failed_exit_or_invalid_attempt(self):
        view = self.project(sequence('root', action('a'), action('b')),
                            attempts=[attempt('a', 'FAILED'), attempt('b', valid=False)], status='FAILED')
        self.assertEqual(view.nodes['a'].state, 'taken')
        self.assertEqual(view.nodes['a'].completed, 0)
        self.assertEqual(view.nodes['b'].state, 'pending')
        self.assertEqual(view.nodes['root'].completed, 0)

    def test_starting_at_later_step_does_not_invent_transition_from_previous_step(self):
        view = self.project(sequence('root', action('a'), action('b')),
                            attempts=[attempt('b', path='/main/b')], status='SUCCEEDED')
        self.assertEqual(view.entries['root'].state, 'pending')
        self.assertEqual(view.edges[('a', 'b')].state, 'pending')
        self.assertEqual(view.nodes['b'].state, 'taken')

    def test_successful_partial_run_does_not_highlight_unreached_flow_end(self):
        view = self.project(sequence('root', action('a'), action('b')),
                            attempts=[attempt('a', path='/main/a')], status='SUCCEEDED')
        self.assertEqual(view.nodes['root'].completed, 0)

    def test_escaped_control_ids_and_numeric_step_ids_are_not_rounds(self):
        gate = branch('gate/x~y')
        gate['cases'][0]['body'] = sequence('yes', action('123'))
        view = self.project(sequence('root', gate),
                            [visit('/root/gate~1x~0y', 'gate/x~y', selected=['then'])],
                            [attempt('123', path='/root/gate~1x~0y/then/yes/123')])
        self.assertEqual(view.nodes['123'].state, 'taken')
        self.assertEqual(view.scopes, {})

    def test_unselected_default_propagates_misses_to_nested_paths(self):
        gate = branch('outer')
        gate['default']['body'] = sequence('continuation', branch('inner'))
        gate['cases'][0]['body'] = sequence('first', action('c'))
        view = self.project(sequence('root', gate), [visit('/root/outer', 'outer', selected=['then'])])
        self.assertEqual(view.branches['first'].state, 'taken')
        self.assertEqual(view.branches['yes'].state, 'skipped')
        self.assertEqual(view.branches['no'].state, 'skipped')

    def test_historical_string_selection_requires_explicit_maintenance(self):
        with self.assertRaises(TaskError) as error:
            self.project(sequence('root', branch()), [visit('/root/gate', 'gate', selected='then')])
        self.assertEqual(error.exception.code, 'FLOW_INVALID')
