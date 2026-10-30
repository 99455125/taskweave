"""Query results are accepted by ordinary interaction state."""
import unittest
from taskweave.presentation.execution import ExecutionInteraction
from taskweave.presentation.state import ExecutionPageState


class ExecutionQueriesTests(unittest.IsolatedAsyncioTestCase):
    async def test_top_level_list_merges_combinations_and_hides_owned_children_and_trials(self):
        state = ExecutionPageState(run_id='child')
        flow = ExecutionInteraction(state)
        task = {'run_id': 'task-run', 'task_id': 't', 'mode': 'EXECUTION',
                'status': 'PAUSED', 'definition_json': None, 'started_at': '2026-10-28'}
        child = {**task, 'run_id': 'child', 'sequence_run_id': 'combination'}
        combo = {'sequence_run_id': 'combination', 'sequence_id': 'definition',
                 'status': 'BLOCKED', 'created_at': '2026-10-29', 'nodes': [],
                 'snapshot': {'name': '业务组合', 'nodes': [], 'mode': 'EXECUTION'}}
        async def call(operation, **params):
            return {'run.list': [task, child, {**task, 'run_id': 'trial', 'mode': 'TRIAL'}],
                    'sequence.run.list': [combo, {**combo, 'sequence_run_id': 'debug',
                         'snapshot': {**combo['snapshot'], 'mode': 'TRIAL'}}],
                    'run.get': task, 'environment.list': [], 'task.list': [], 'step.list': []}[operation]
        result = await flow.load_rows(call, lambda: (1, 'executions'))
        self.assertEqual([row['run_id'] for row in result.details], ['combination', 'task-run'])
        self.assertEqual(state.run_id, 'combination')
        self.assertEqual(result.active_run['execution_kind'], 'sequence')
        state.task_ids = ['sequence:definition']
        result = await flow.load_rows(call, lambda: (1, 'executions'))
        self.assertEqual([row['run_id'] for row in result.details], ['combination'])
        state.search_query = '业务'
        result = await flow.load_rows(call, lambda: (1, 'executions'))
        self.assertEqual(len(result.details), 1)
        state.statuses = ['SUCCEEDED']
        result = await flow.load_rows(call, lambda: (1, 'executions'))
        self.assertEqual(result.details, [])

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
            return {'sequence.run.list': [], 'run.list': [row], 'run.get': row, 'environment.list': [], 'task.list': [{'task_id': 't', 'name': 'Task'}], 'step.list': [{'step_id': 's'}]}[operation]
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
            return {'sequence.run.list': [], 'run.list': [row], 'run.get': row, 'environment.list': [], 'task.list': []}[operation]
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
