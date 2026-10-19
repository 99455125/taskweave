"""Query results are accepted by ordinary interaction state."""
import unittest
from taskweave.presentation.execution import ExecutionInteraction
from taskweave.presentation.state import ExecutionPageState


class ExecutionQueriesTests(unittest.IsolatedAsyncioTestCase):
    async def test_rows_reject_late_filters_before_cache_or_selection_update(self):
        state = ExecutionPageState()
        flow = ExecutionInteraction(state)
        async def call(operation, **params):
            state.search_query = 'changed'
            return [{'run_id': 'r', 'task_id': 't', 'mode': 'EXECUTION', 'status': 'RUNNING'}]
        self.assertIsNone(await flow.load_rows(call, lambda: (1, 'executions')))
        self.assertEqual(flow.current_runs, {})
        self.assertIsNone(state.run_id)

    async def test_rows_fetch_and_select_same_data_without_view(self):
        state = ExecutionPageState()
        flow = ExecutionInteraction(state)
        row = {'run_id': 'r', 'task_id': 't', 'mode': 'EXECUTION', 'status': 'PAUSED', 'definition_json': None}
        async def call(operation, **params):
            return {'run.list': [row], 'run.get': row, 'environment.list': [], 'task.list': [{'task_id': 't', 'name': 'Task'}], 'step.list': [{'step_id': 's'}]}[operation]
        result = await flow.load_rows(call, lambda: (1, 'executions'))
        self.assertEqual(state.run_id, 'r')
        self.assertEqual(result.definition_steps, [{'step_id': 's'}])
        self.assertEqual(result.active_run, row)

    async def test_refresh_token_rejects_new_request_selection_and_dispose(self):
        flow = ExecutionInteraction(ExecutionPageState())
        page = (1, 'executions')
        first = flow.begin_refresh(page)
        second = flow.begin_refresh(page)
        self.assertFalse(flow.accepts_refresh(first, page))
        token = flow.detail_token(second, page)
        flow.select_run('another')
        self.assertFalse(flow.accepts_detail(token, page))
        flow.dispose()
        self.assertFalse(flow.accepts_refresh(second, page))
        self.assertTrue(flow.polling.visible)

    async def test_rows_dispose_during_definition_query_rejects_response(self):
        state = ExecutionPageState()
        flow = ExecutionInteraction(state)
        row = {'run_id': 'r', 'task_id': 't', 'mode': 'EXECUTION', 'status': 'PAUSED', 'definition_json': None}
        async def call(operation, **params):
            if operation == 'step.list':
                flow.dispose()
                return [{'step_id': 'old'}]
            return {'run.list': [row], 'run.get': row, 'environment.list': [], 'task.list': []}[operation]
        self.assertIsNone(await flow.load_rows(call, lambda: (1, 'executions')))
        self.assertIsNone(state.signature)
        self.assertTrue(flow.polling.visible)

    def test_execution_and_history_run_without_gui_imports(self):
        import subprocess
        import sys
        result = subprocess.run([sys.executable, '-c', """
import importlib.abc
import sys
import unittest
class Boundary(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.startswith(('taskweave.desktop', 'taskweave.infrastructure', 'nicegui', 'webview')):
            raise AssertionError('Forbidden dependency: ' + fullname)
sys.meta_path.insert(0, Boundary())
from tests.presentation.test_execution_queries import ExecutionQueriesTests
from tests.presentation.test_history import HistoryLoadTests
names = [name for name in unittest.defaultTestLoader.getTestCaseNames(ExecutionQueriesTests)
         if name != 'test_execution_and_history_run_without_gui_imports']
suite = unittest.TestSuite(ExecutionQueriesTests(name) for name in names)
suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(HistoryLoadTests))
result = unittest.TextTestRunner().run(suite)
sys.exit(not result.wasSuccessful())
"""], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
