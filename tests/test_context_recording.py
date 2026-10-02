"""Optional recording lifecycle preserves read-only snapshots and unsaved buffers."""
import asyncio
import tempfile
import unittest
from dataclasses import replace
from taskweave.core.validation import TaskError
from taskweave.infrastructure.context_sessions import ContextSessions
from taskweave.infrastructure.plan_repository import PlanRepository
from taskweave.infrastructure.repository import Repository
from tests.test_context_sessions import Registry, Provider, Plugin


class ContextRecordingTests(unittest.TestCase):
    def test_old_provider_remains_collectable_without_recording(self):
        with tempfile.TemporaryDirectory() as home:
            repo = Repository(home); plans = PlanRepository(repo); provider = Provider()
            sessions = ContextSessions(Registry(provider), repo, plans, repo.home / 'plans')
            plan = plans.create('P'); plan = plans.update(plan['plan_id'], 1, 'P', plugin_ids=['fake'])
            try:
                with self.assertRaises(TaskError) as error:
                    sessions.record(plan['plan_id'], 'fake.page', 'start', expected_revision=2)
                self.assertEqual(error.exception.code, 'CONTEXT_RECORDING_UNAVAILABLE')
                self.assertEqual(provider.opens, 0)
                self.assertEqual(sessions.sessions, {})
                self.assertTrue(sessions.collect(plan['plan_id'], 2, 'fake.page')['capture']['items'])
            finally:
                sessions.close()

    def test_recording_read_does_not_persist_or_consume_and_pending_buffers_protect_session(self):
        from taskweave.plugins.sdk import ContextRecordingBatch, ContextCollection, ContextItem
        class Recorder(Plugin):
            def __init__(self): self.state, self.acked = 'RECORDING', 0
            async def record_context(self, provider_id, ctx, command, request, *, include_view=True):
                await ctx.resources.acquire('fake.browser', 'main')
                if command.operation == 'stop': self.state = 'STOPPED'
                elif command.operation == 'ack': self.acked = command.through
                elif command.operation == 'discard': self.state, self.acked = 'DISCARDED', 1
                collection = ContextCollection((ContextItem('text','application/json','{"sequence":1,"target":"真实点击"}','fake'),)) if command.operation == 'read' and not self.acked else ContextCollection(())
                return ContextRecordingBatch('record-1', self.state, 1, collection,
                                             available_after=self.acked)
        with tempfile.TemporaryDirectory() as home:
            repo = Repository(home); plans = PlanRepository(repo); provider = Provider()
            registry = Registry(provider); registry.plugins = [Recorder()]
            sessions = ContextSessions(registry, repo, plans, repo.home / 'plans')
            plan = plans.create('P'); plan = plans.update(plan['plan_id'], 1, 'P', plugin_ids=['fake'])
            try:
                start = sessions.record(plan['plan_id'], 'fake.page', 'start', expected_revision=2)
                options = {'recording_id': start['recording_id'], 'expected_session_id':start['session_id']}
                with self.assertRaises(TaskError) as unread:
                    sessions.record(plan['plan_id'], 'fake.page', 'ack', through=1, **options)
                self.assertEqual(unread.exception.code, 'CONTEXT_RECORDING_REQUEST_INVALID')
                first = sessions.record(plan['plan_id'], 'fake.page', 'read', **options)
                self.assertEqual(first, sessions.record(plan['plan_id'], 'fake.page', 'read', **options))
                self.assertEqual(plans.contexts(plan['plan_id']), [])
                with self.assertRaises(TaskError): sessions.end(plan['plan_id'])
                with self.assertRaises(TaskError): sessions.change_configuration(plan['plan_id'], lambda:None)
                sessions.record(plan['plan_id'], 'fake.page', 'stop', **options)
                with self.assertRaises(TaskError): sessions.end(plan['plan_id'])
                with self.assertRaises(TaskError) as error:
                    sessions.record(plan['plan_id'], 'fake.page', 'read', **{**options,'expected_session_id':'old-session'})
                self.assertEqual(error.exception.code, 'CONTEXT_SESSION_CHANGED')
                sessions.record(plan['plan_id'], 'fake.page', 'ack', through=1, **options)
                sessions.record(plan['plan_id'], 'fake.page', 'ack', through=1, **options)
                self.assertTrue(sessions.end(plan['plan_id'])['ended'])
                self.assertEqual(provider.closes, 1)
            finally:
                sessions.close()

    def test_optional_hook_output_and_command_are_bounded_and_validated(self):
        from taskweave.plugins.sdk import ContextRecordingBatch, ContextCollection, ContextItem
        from taskweave.core.context_recording import recording_command, serialize_recording_batch
        for operation, options in [('bad',{}), ('start',{'recording_id':'old'}), ('read',{}), ('ack',{'recording_id':'id'}), ('read',{'recording_id':'id','after':True}), ('read',{'recording_id':'id','limit':101})]:
            with self.assertRaises(TaskError): recording_command(operation, **options)
        batch = ContextRecordingBatch('id', 'PAUSED', 3, ContextCollection(()))
        self.assertEqual(serialize_recording_batch(batch,{})['state'], 'PAUSED')
        for bad in [replace(batch,state='invalid'), replace(batch,cursor=-1), replace(batch,available_after=4), replace(batch,recording_id=''), replace(batch,collection=ContextCollection((ContextItem('text','text/plain','x'*2100000,'fake'),)))]:
            with self.assertRaises(TaskError): serialize_recording_batch(bad,{})
