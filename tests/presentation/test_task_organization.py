"""Task metadata changes serialize and reject stale view updates."""
import asyncio
import unittest
from unittest.mock import AsyncMock


class TaskOrganizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_queued_toggle_preserves_latest_category_and_failure_keeps_cache(self):
        from taskweave.presentation.tasks import TaskOrganization
        task = {'task_id': 't', 'is_favorite': False, 'category_id': None}
        call = AsyncMock()
        session = TaskOrganization(call, lambda: 'page')
        session.remember([task])
        await asyncio.gather(session.update(task, toggle_favorite=True), session.update(task, category_id='c'))
        self.assertEqual(session.metadata(task), {'is_favorite': True, 'category_id': 'c'})
        call.side_effect = RuntimeError('failed')
        with self.assertRaises(RuntimeError): await session.update(task, toggle_favorite=True)
        self.assertTrue(session.metadata(task)['is_favorite'])

    async def test_accepted_write_finishes_after_leaving_but_old_queued_write_does_not_start(self):
        from taskweave.presentation.tasks import TaskOrganization
        started, release = asyncio.Event(), asyncio.Event()
        page = ['old']
        async def call(*args, **kwargs):
            started.set(); await release.wait()
        session = TaskOrganization(call, lambda: page[0])
        task = {'task_id': 't'}
        running = asyncio.create_task(session.update(task, toggle_favorite=True))
        await started.wait()
        queued = asyncio.create_task(session.update(task, category_id='c'))
        await asyncio.sleep(0)
        page[0] = 'new'; release.set()
        result = await running
        self.assertTrue(result.saved)
        self.assertFalse(result.current)
        self.assertFalse((await queued).saved)
        self.assertEqual(session.metadata(task), {'is_favorite': True, 'category_id': None})


class TaskDraftTests(unittest.TestCase):
    def test_unedited_task_schema_preserves_root_and_field_constraints(self):
        import json
        from taskweave.presentation.tasks import TaskDraft
        schema = {'type': 'object', 'additionalProperties': False, 'title': 'inputs',
                  'properties': {'count': {'type': 'integer', 'minimum': 1, 'default': 2}}, 'required': ['count']}
        draft = TaskDraft({'name': 'task', 'description': '', 'input_schema_json': json.dumps(schema)})
        self.assertEqual(draft.schema(), schema)

    def test_changed_schema_retains_root_constraints_without_promoting_field_constraints(self):
        from taskweave.presentation.forms import schema_from_rows
        schema = {'type': 'object', 'additionalProperties': False,
                  'properties': {'count': {'type': 'integer', 'minimum': 1}}, 'required': []}
        result = schema_from_rows(schema, [['count', 'integer', '2', '', False, schema['properties']['count']]])
        self.assertFalse(result['additionalProperties'])
        self.assertNotIn('minimum', result)
        self.assertEqual(result['properties']['count'], {'type': 'integer', 'minimum': 1, 'default': 2})


class CategorySessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_plain_category_drafts_and_failed_rename_are_retained(self):
        from taskweave.presentation.organization import CategorySession
        call = AsyncMock(return_value=[{'category_id': 'a', 'name': 'old'}])
        session = CategorySession(call)
        await session.load()
        session.names['a'] = 'new'
        call.side_effect = RuntimeError('offline')
        with self.assertRaises(RuntimeError): await session.rename('a')
        self.assertEqual(session.names['a'], 'new')
        call.side_effect = None
        await session.rename('a')
        call.assert_awaited_with('organization.category.rename', category_id='a', name='new')
        session.new_name = 'another'
        await session.create()
        call.assert_awaited_with('organization.category.create', name='another')
        await session.delete('a')
        call.assert_awaited_with('organization.category.delete', category_id='a')
