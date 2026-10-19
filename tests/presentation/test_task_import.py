import unittest
from unittest.mock import AsyncMock
from taskweave.core.validation import TaskError


class TaskImportTests(unittest.IsolatedAsyncioTestCase):
    async def test_latest_file_wins_and_failed_or_closed_read_cannot_import(self):
        from taskweave.presentation.task_import import TaskImportSession
        call = AsyncMock()
        draft = TaskImportSession(call)
        old = draft.begin_file(10)
        new = draft.begin_file(10)
        self.assertFalse(draft.accept_file(old, b'{"old":true}'))
        self.assertTrue(draft.accept_file(new, b'{"new":true}'))
        await draft.submit()
        call.assert_awaited_once_with({'new': True})
        draft.clear_file()
        with self.assertRaises(TaskError): await draft.submit()
        token = draft.begin_file(10)
        draft.close()
        self.assertFalse(draft.accept_file(token, b'{}'))

    async def test_limits_parsing_and_failed_submit_preserve_text_draft(self):
        from taskweave.presentation.task_import import TaskImportSession, TASK_IMPORT_LIMIT_BYTES
        draft = TaskImportSession(AsyncMock(side_effect=RuntimeError('offline')))
        with self.assertRaises(ValueError): draft.begin_file(TASK_IMPORT_LIMIT_BYTES + 1)
        token = draft.begin_file(1)
        with self.assertRaises(ValueError): draft.accept_file(token, b'{broken')
        draft.mode, draft.source = 'text', '{"kept":true}'
        with self.assertRaises(RuntimeError): await draft.submit()
        self.assertEqual(draft.source, '{"kept":true}')
        draft.source = '{broken'
        with self.assertRaises(TaskError): await draft.submit()

    async def test_duplicate_submit_and_close_do_not_cancel_accepted_import(self):
        import asyncio
        from taskweave.presentation.task_import import TaskImportSession
        entered, release = asyncio.Event(), asyncio.Event()
        saved = []
        async def import_package(package):
            entered.set()
            await release.wait()
            saved.append(package)
            return {'task_id': 'new'}
        draft = TaskImportSession(import_package)
        draft.mode, draft.source = 'text', '{"name":"task"}'
        pending = asyncio.create_task(draft.submit())
        await entered.wait()
        duplicate = asyncio.create_task(draft.submit())
        await asyncio.sleep(0)
        duplicate_was_ignored = duplicate.done()
        draft.close()
        release.set()
        original, repeated = await asyncio.gather(pending, duplicate)
        self.assertTrue(duplicate_was_ignored)
        self.assertIsNone(original)
        self.assertIsNone(repeated)
        self.assertEqual(saved, [{'name': 'task'}])
        self.assertIsNone(await draft.submit())
        self.assertFalse(draft.submitting)

    async def test_failed_submit_releases_guard_for_retry(self):
        from taskweave.presentation.task_import import TaskImportSession
        call = AsyncMock(side_effect=[RuntimeError('offline'), {'task_id': 'new'}])
        draft = TaskImportSession(call)
        draft.mode, draft.source = 'text', '{}'
        with self.assertRaisesRegex(RuntimeError, 'offline'):
            await draft.submit()
        self.assertFalse(draft.submitting)
        self.assertEqual(await draft.submit(), {'task_id': 'new'})

    def test_submit_workflow_with_gui_imports_forbidden(self):
        import subprocess
        import sys
        result = subprocess.run([sys.executable, '-c', """
import importlib.abc, sys, unittest
class Boundary(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.startswith(('taskweave.desktop', 'nicegui', 'webview')):
            raise AssertionError(fullname)
sys.meta_path.insert(0, Boundary())
from tests.presentation.test_task_import import TaskImportTests
names = [name for name in unittest.defaultTestLoader.getTestCaseNames(TaskImportTests)
         if name != 'test_submit_workflow_with_gui_imports_forbidden']
result = unittest.TextTestRunner().run(unittest.TestSuite(TaskImportTests(name) for name in names))
sys.exit(not result.wasSuccessful())
"""], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
