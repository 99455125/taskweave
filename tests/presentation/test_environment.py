"""Environment drafts and leave decisions work with ordinary application ports."""
import asyncio
import importlib.util
import unittest

from taskweave.core.validation import TaskError


class EnvironmentInteractionTests(unittest.IsolatedAsyncioTestCase):
    def session(self, call):
        self.assertIsNotNone(importlib.util.find_spec('taskweave.presentation.environment'),
                             'Environment interaction must be independent of desktop')
        from taskweave.presentation.environment import EnvironmentSession
        return EnvironmentSession(call, lambda: ('environment', 1))

    async def test_failed_save_retains_raw_draft_and_blocks_leave(self):
        async def call(operation, **params):
            raise TaskError('ENVIRONMENT_LOCKED', 'busy')
        session = self.session(call)
        session.begin_render()
        session.mount(None)
        session.draft.name = 'draft'
        session.draft.add('count', '03', 'raw')
        origin = session.form_identity()
        self.assertEqual(session.leave_decision(origin), 'ask')
        with self.assertRaises(TaskError):
            await session.leave(origin, 'save')
        self.assertEqual(session.draft.rows[0].value, '03')
        self.assertTrue(session.draft.dirty)
        self.assertFalse(await session.leave(origin, 'stay'))
        self.assertTrue(await session.leave(origin, 'discard'))

    async def test_secret_rename_delete_and_reference_validation(self):
        calls = []
        async def call(operation, **params):
            calls.append(params)
            return {'environment_id': 'a'}
        session = self.session(call)
        session.begin_render()
        session.mount({'environment_id': 'a', 'name': 'A', 'public_config_json': '{"keep": 2}',
                       'secret_refs_json': '{"token":"env:TOKEN"}', 'descriptions_json': '{}'})
        secret = session.draft.rows[-1]
        secret.key = 'renamed'
        await session.save_draft()
        self.assertEqual(calls[-1]['secret_refs'], {'renamed': 'env:TOKEN'})
        secret.value = 'plaintext'
        with self.assertRaises(TaskError):
            await session.save_draft()
        self.assertEqual(len(calls), 1)
        session.draft.remove(secret)
        await session.save_draft()
        self.assertEqual(calls[-1]['secret_refs'], {})
        self.assertEqual(calls[-1]['public_config'], {'keep': 2})

    async def test_late_save_does_not_replace_new_draft_or_selection(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def call(operation, **params):
            entered.set()
            await release.wait()
            return {'environment_id': 'a'}
        session = self.session(call)
        session.begin_render()
        session.mount({'environment_id': 'a', 'name': 'A', 'public_config_json': '{}'})
        session.draft.name = 'A changed'
        pending = asyncio.create_task(session.save_draft())
        await entered.wait()
        session.select('b')
        session.begin_render()
        session.mount({'environment_id': 'b', 'name': 'B', 'public_config_json': '{}'})
        session.draft.name = 'B draft'
        release.set()
        self.assertFalse((await pending).current)
        self.assertEqual(session.selected_environment_id, 'b')
        self.assertEqual(session.draft.name, 'B draft')

    async def test_new_draft_saved_on_leave_reuses_id_and_stale_choice_is_rejected(self):
        ids = []
        async def call(operation, **params):
            ids.append(params['environment_id'])
            return {'environment_id': 'created'}
        session = self.session(call)
        session.create()
        session.begin_render()
        session.mount(None)
        session.draft.name = 'new'
        origin = session.form_identity()
        self.assertTrue(await session.leave(origin, 'save'))
        session.draft.name = 'renamed'
        await session.save_draft()
        self.assertEqual(ids, [None, 'created'])
        session.begin_render()
        self.assertFalse(await session.leave(origin, 'discard'))
