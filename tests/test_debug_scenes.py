"""Explicit scene reuse keeps resources, result ownership and serial execution."""
import asyncio
import json
import tempfile
import unittest
from taskweave.application.service import Application
from taskweave.core.validation import TaskError
from taskweave.desktop.controller import DesktopController
from taskweave.infrastructure.storage import uid


class DebugScenes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='taskweave-scenes-')
        self.app = Application(self.tmp.name, registry_factory='tests._debug_scene_plugin:build_registry')

    def tearDown(self):
        self.app.close()
        self.tmp.cleanup()

    def step(self, name):
        task = self.app.tasks.create(name)['task_id']
        return self.app.steps.save(task, {'name': name, 'capabilities': ['demo.counter'],
            'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data=await ctx.call("demo.counter", inputs))'})

    def trial(self, step, **options):
        run = self.app.dispatch('step.trial', {'step_id': step['step_id'], 'inputs': {}, 'command_id': uid(), **options})
        done = self.app.coordinator.wait(run['run_id'])
        self.assertEqual(done['status'], 'SUCCEEDED', done)
        return run

    def scene(self, step):
        rows = self.app.dispatch('step.trial.sessions', {'step_id': step['step_id']})
        self.assertTrue(rows)
        return rows[-1]

    def test_cross_task_reuse_keeps_resource_and_new_result_ownership(self):
        a, b = self.step('A'), self.step('B')
        original = self.trial(a)
        scene = self.scene(b)
        reused = self.trial(b, session_run_id=scene['run_id'], expected_session_id=scene['session_id'])
        self.assertEqual(self.app.runs.output(original['run_id'], a['step_id']), {'count': 1})
        self.assertEqual(self.app.runs.output(reused['run_id'], b['step_id']), {'count': 2})
        self.assertEqual(self.app.runs.get(reused['run_id'])['task_id'], b['task_id'])
        request = self.app.runs.runs.private_run_request(reused['run_id'])
        self.assertEqual(request['debug_scene']['run_id'], original['run_id'])

    def test_reused_formal_scene_can_continue_original_run(self):
        first = self.step('A')
        second = self.app.steps.save(first['task_id'], {'name': 'second', 'capabilities': ['demo.counter'],
            'step_content': first['step_content']})
        self.app.steps.confirm_manual(first['step_id'], first['content_hash'])
        self.app.steps.confirm_manual(second['step_id'], second['content_hash'])
        self.app.tasks.confirm_flow(first['task_id'], self.app.tasks.definition_hash(first['task_id']))
        source = self.app.runs.create(first['task_id'])
        self.app.coordinator.start(source['run_id'], uid(), mode='NEXT')
        self.assertEqual(self.app.coordinator.wait(source['run_id'])['status'], 'PAUSED')
        b = self.step('B')
        scene = self.scene(b)
        self.trial(b, session_run_id=scene['run_id'], expected_session_id=scene['session_id'])
        self.app.coordinator.start(source['run_id'], uid())
        self.assertEqual(self.app.coordinator.wait(source['run_id'])['status'], 'SUCCEEDED')
        self.assertEqual(self.app.runs.output(source['run_id'], second['step_id']), {'count': 3})

    def test_flow_trial_honors_selected_cross_task_scene(self):
        a, b = self.step('A'), self.step('B')
        controlled = {'version': 2, 'root': {'id': 'root', 'kind': 'sequence', 'children': [
            {'id': b['step_id'], 'kind': 'action', 'step_id': b['step_id']},
            {'id': 'gate', 'kind': 'if', 'parallel': False, 'cases': [
                {'id': 'yes', 'condition': {'op': 'eq', 'left': {'literal': True}, 'right': {'literal': True}},
                 'body': {'id': 'yes-body', 'kind': 'sequence', 'children': []}}],
             'default': {'id': 'no', 'body': {'id': 'no-body', 'kind': 'sequence', 'children': []}}}]}}
        self.app.tasks.save_flow(b['task_id'], controlled, self.app.tasks.definition_hash(b['task_id']))
        self.trial(a)
        scene = self.scene(b)
        run = self.app.dispatch('step.trial.flow', {'step_id': b['step_id'], 'inputs': {}, 'command_id': uid(),
            'session_run_id': scene['run_id'], 'expected_session_id': scene['session_id']})
        self.assertEqual(self.app.coordinator.wait(run['run_id'])['status'], 'SUCCEEDED')
        self.assertEqual(self.app.runs.output(run['run_id'], b['step_id']), {'count': 2})

    def test_new_scene_leaves_previous_scene_available(self):
        step = self.step('A')
        first = self.trial(step)
        scene = self.scene(step)
        fresh = self.trial(step, new_session=True)
        self.assertEqual(self.app.runs.output(fresh['run_id'], step['step_id']), {'count': 1})
        third = self.trial(step, session_run_id=scene['run_id'], expected_session_id=scene['session_id'])
        self.assertEqual(self.app.runs.output(third['run_id'], step['step_id']), {'count': 2})
        self.assertEqual(self.app.runs.output(first['run_id'], step['step_id']), {'count': 1})

    def test_invalid_scene_options_are_rejected_before_creating_runs(self):
        step = self.step('A')
        for options in ({'new_session': 'false'}, {'session_run_id': 1, 'expected_session_id': True},
                        {'session_run_id': '', 'expected_session_id': ''}):
            with self.subTest(options=options), self.assertRaises(TaskError):
                self.trial(step, **options)
        self.assertEqual(self.app.runs.list(), [])

    def test_stale_scene_rejected_before_run_creation(self):
        a, b = self.step('A'), self.step('B')
        self.trial(a)
        scene = self.scene(b)
        before = len(self.app.runs.list())
        with self.assertRaises(TaskError) as error:
            self.trial(b, session_run_id=scene['run_id'], expected_session_id='expired')
        self.assertEqual(error.exception.code, 'CONTEXT_SESSION_CHANGED')
        self.assertEqual(len(self.app.runs.list()), before)

    def test_shared_scene_rejects_concurrent_run_and_context_mutation(self):
        a, b = self.step('A'), self.step('B')
        self.trial(a)
        scene = self.scene(b)
        run = self.app.dispatch('step.trial', {'step_id': b['step_id'], 'inputs': {'seconds': 1},
            'command_id': uid(), 'session_run_id': scene['run_id'], 'expected_session_id': scene['session_id']})
        before = len(self.app.runs.list())
        with self.assertRaises(TaskError) as error:
            self.trial(a, session_run_id=scene['run_id'], expected_session_id=scene['session_id'])
        self.assertEqual(error.exception.code, 'RUN_BUSY')
        self.assertEqual(len(self.app.runs.list()), before)
        with self.assertRaises(TaskError):
            self.app.coordinator.control(scene['run_id'], uid(), 'abandon')
        with self.assertRaises(TaskError):
            self.app.coordinator.delete_run(scene['run_id'])
        with self.assertRaises(TaskError):
            self.app.coordinator.clear_task_runs(a['task_id'])
        self.assertFalse(self.app.coordinator.release_completed_run(scene['run_id']))
        self.assertEqual(self.app.coordinator.wait(run['run_id'])['status'], 'SUCCEEDED')

    def test_controlled_trial_first_step_is_valid_and_midpoint_rejected_before_write(self):
        first = self.step('flow')
        second = self.app.steps.save(first['task_id'], {'name': 'second',
            'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data=inputs)'})
        flow = {'version': 2, 'root': {'id': 'root', 'kind': 'sequence', 'children': [
            {'id': first['step_id'], 'kind': 'action', 'step_id': first['step_id']},
            {'id': 'choice', 'kind': 'if', 'parallel': False, 'cases': [
                {'id': 'yes', 'condition': {'op': 'eq', 'left': {'literal': True}, 'right': {'literal': True}},
                 'body': {'id': 'yes-body', 'kind': 'sequence', 'children': [
                    {'id': second['step_id'], 'kind': 'action', 'step_id': second['step_id']}]}}],
             'default': {'id': 'no', 'body': {'id': 'no-body', 'kind': 'sequence', 'children': []}}}]}}
        self.app.tasks.save_flow(first['task_id'], flow, self.app.tasks.definition_hash(first['task_id']))
        run = self.app.steps.trial_flow(second['step_id'], {}, uid(), start_step_id=first['step_id'])
        self.assertEqual(self.app.coordinator.wait(run['run_id'])['status'], 'SUCCEEDED')
        before = len(self.app.runs.list())
        with self.assertRaises(TaskError) as error:
            self.app.steps.trial_flow(second['step_id'], {}, uid(), start_step_id=second['step_id'])
        self.assertEqual(error.exception.code, 'FLOW_INSTANCE_REQUIRED')
        self.assertEqual(len(self.app.runs.list()), before)

    def test_explicit_result_source_never_falls_back_to_recent_run(self):
        a = self.step('A')
        source = self.trial(a)
        self.trial(a, new_session=True)
        b = self.app.steps.save(a['task_id'], {'name': 'B',
            'bindings': {'selected': {'ref': {'source': 'step', 'step_id': a['step_id'], 'pointer': '/count'}}},
            'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data=inputs)'})
        async def execute():
            return await DesktopController(self.app).trial(b, {}, source_run_id=source['run_id'])
        selected = asyncio.run(execute())
        self.app.coordinator.wait(selected['run_id'])
        self.assertEqual(self.app.runs.output(selected['run_id'], b['step_id'])['selected'], 1)
        with self.assertRaises(TaskError):
            asyncio.run(DesktopController(self.app).trial(b, {}, source_run_id=selected['run_id']))


from tests.test_flow_parallel import ParallelFixture


class BranchScenes(ParallelFixture):
    def test_borrowed_branch_blocks_parent_lifecycle(self):
        task = self.task()
        first, second = [self.confirmed_step(task) for _ in range(2)]
        self.install_group(task, [('a', [first]), ('b', [second])])
        source = self.app.create_run(task)
        self.app.coordinator.start(source['run_id'], uid(), mode='NEXT')
        self.app.coordinator.wait(source['run_id'])
        b_task = self.task()
        b = self.app.steps.save(b_task, {'name': 'borrow', 'capabilities': ['demo.timed'],
            'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data=await ctx.call("demo.timed", inputs))'})
        scene = self.app.steps.trial_sessions(b['step_id'])[0]
        reused = self.app.steps.trial(b['step_id'], {'seconds': .5}, uid(),
            session_run_id=scene['run_id'], expected_session_id=scene['session_id'])
        for operation in (lambda: self.app.coordinator.control(source['run_id'], uid(), 'abandon'),
                          lambda: self.app.coordinator.delete_run(source['run_id']),
                          lambda: self.app.coordinator.clear_task_runs(task),
                          lambda: self.app.coordinator.start(source['run_id'], uid())):
            with self.assertRaises(TaskError) as error:
                operation()
            self.assertEqual(error.exception.code, 'RUN_BUSY')
        self.assertEqual(self.app.coordinator.wait(reused['run_id'])['status'], 'SUCCEEDED')


if __name__ == '__main__': unittest.main()
