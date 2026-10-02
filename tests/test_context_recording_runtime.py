"""Retained worker recording must keep its event loop alive while idle."""
import asyncio
import json
import tempfile
import time
import unittest
from taskweave.application.service import Application
from taskweave.core.ports import ContextRecordingBatch, ContextCollection, ContextItem
from taskweave.core.validation import TaskError
from taskweave.infrastructure.storage import uid
from tests.test_context_targets_runtime import TargetPlugin
from taskweave.plugins.registry import Registry


class RecordingPlugin(TargetPlugin):
    def __init__(self):
        self.state = 'RECORDING'
        self.ticks = 0
        self.acked = 0
        self.timer = None

    async def record_context(self, provider_id, ctx, command, request, *, include_view=True):
        if command.operation == 'start':
            async def ticks():
                while self.state in {'RECORDING', 'PAUSED'}:
                    if self.state == 'RECORDING': self.ticks += 1
                    await asyncio.sleep(.02)
            self.state = 'RECORDING'
            self.timer = asyncio.create_task(ticks())
        elif command.operation == 'stop': self.state = 'STOPPED'
        elif command.operation == 'ack': self.acked = command.through
        elif command.operation == 'discard': self.state, self.acked = 'DISCARDED', 1
        collection = ContextCollection((ContextItem('text','application/json',json.dumps({'ticks':self.ticks}),'demo.record'),)) if command.operation == 'read' and not self.acked else ContextCollection(())
        return ContextRecordingBatch('record-worker', self.state, 1, collection, available_after=self.acked)


def build_registry(): return Registry([RecordingPlugin()])


class RuntimeRecordingTests(unittest.TestCase):
    def test_independent_step_observation_reuses_resources_and_protects_pending_recording(self):
        with tempfile.TemporaryDirectory() as home, Application(home, registry_factory=f'{__name__}:build_registry') as app:
            task=app.repo.create_task('Independent observation')['task_id']
            step=app.repo.save_step(task, {'name':'Observe','capabilities':['demo.echo']})
            environment=app.repo.save_environment('Observation',{})['environment_id']
            params={'step_id':step['step_id'],'provider_id':'demo.page'}
            first=app.dispatch('context.read',{**params,'environment_id':environment})
            self.assertTrue(first['items'])
            targets=app.dispatch('context.targets',params)
            self.assertTrue(targets['targets'])
            started=app.dispatch('context.record',{**params,'operation':'start','environment_id':environment,'expected_session_id':targets['session_id']})
            options={**params,'recording_id':started['recording_id'],'expected_session_id':started['session_id']}
            time.sleep(.15)
            read=app.dispatch('context.record',{**options,'operation':'read'})
            self.assertGreaterEqual(json.loads(read['capture']['items'][0]['content'])['ticks'],3)
            instances=app.dispatch('instance.list',{})
            instance=next(item for item in instances if item['instance_type']=='step')
            self.assertEqual(instance['owner_id'],step['step_id'])
            self.assertEqual(instance['environment_id'],environment)
            with self.assertRaises(TaskError) as locked:
                app.dispatch('environment.delete',{'environment_id':environment})
            self.assertEqual(locked.exception.code,'ENVIRONMENT_LOCKED')
            with self.assertRaises(TaskError) as pending:
                app.dispatch('instance.end',{'instance_type':'step','owner_id':step['step_id']})
            self.assertEqual(pending.exception.code,'CONTEXT_RECORDING_PENDING')
            for operation, arguments in [('step.delete',{'step_id':step['step_id']}),('task.delete',{'task_id':task})]:
                with self.assertRaises(TaskError) as pending:
                    app.dispatch(operation,arguments)
                self.assertEqual(pending.exception.code,'CONTEXT_RECORDING_PENDING')
            app.dispatch('context.record',{**options,'operation':'stop'})
            app.dispatch('context.record',{**options,'operation':'ack','through':read['cursor']})
            app.dispatch('instance.end',{'instance_type':'step','owner_id':step['step_id']})
            self.assertFalse(app.dispatch('context.targets',params)['targets'])
            app.dispatch('environment.delete',{'environment_id':environment})

    def test_idle_recording_non_consuming_read_and_session_guards(self):
        with tempfile.TemporaryDirectory() as home, Application(home, registry_factory=f'{__name__}:build_registry') as app:
            task = app.repo.create_task('Temporary recording')['task_id']
            step = app.repo.save_step(task, {'name':'Record','step_content':'async def run(ctx, inputs):\n    return ctx.result(data={})\n','capabilities':['demo.echo']})
            run = app.trial_step(step['step_id'], {}, uid())
            self.assertEqual(app.coordinator.wait(run['run_id'])['status'], 'SUCCEEDED')
            params = {'step_id':step['step_id'],'provider_id':'demo.page','run_id':run['run_id']}
            started = app.dispatch('context.record', {**params,'operation':'start'})
            options = {**params,'recording_id':started['recording_id'],'expected_session_id':started['session_id']}
            time.sleep(.25)
            read = app.dispatch('context.record', {**options,'operation':'read'})
            self.assertGreaterEqual(json.loads(read['capture']['items'][0]['content'])['ticks'], 5)
            self.assertEqual(app.repo.list_step_contexts(step['step_id']), [])
            with self.assertRaises(TaskError) as stale:
                app.dispatch('context.record', {**options,'operation':'read','expected_session_id':'stale'})
            self.assertEqual(stale.exception.code, 'CONTEXT_SESSION_CHANGED')
            with self.assertRaises(TaskError) as pending:
                app.dispatch('run.control', {'run_id':run['run_id'],'command_id':uid(),'operation':'abandon'})
            self.assertEqual(pending.exception.code, 'CONTEXT_RECORDING_PENDING')
            with self.assertRaises(TaskError) as clear:
                app.clear_task_runs(task)
            self.assertEqual(clear.exception.code, 'CONTEXT_RECORDING_PENDING')
            # Editing capabilities cannot strand evidence in the original
            # provider. Continuation commands use its captured authority;
            # starting a new recording still uses the current step.
            current=app.repo.step(step['step_id'])
            app.repo.save_step(task, {**current,'capabilities':[]}, step_id=step['step_id'], expected_hash=current['content_hash'])
            app.dispatch('context.record', {**options,'operation':'stop'})
            with self.assertRaises(TaskError) as unavailable:
                app.dispatch('context.record', {**params,'operation':'start'})
            self.assertEqual(unavailable.exception.code, 'CONTEXT_PROVIDER_UNAVAILABLE')
            with self.assertRaises(TaskError): app.coordinator.delete_run(run['run_id'])
            app.dispatch('context.record', {**options,'operation':'ack','through':read['cursor']})
            app.dispatch('context.record', {**options,'operation':'ack','through':read['cursor']})
            app.dispatch('run.control', {'run_id':run['run_id'],'command_id':uid(),'operation':'abandon'})
