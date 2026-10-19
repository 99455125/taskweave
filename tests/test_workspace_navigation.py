"""Navigation coordinates plain states and explicit adapter responses."""
import unittest
from taskweave.presentation.state import StepEditorState, ExecutionPageState, ContextPageState


class WorkspaceNavigationTests(unittest.IsolatedAsyncioTestCase):
    async def test_cross_task_transition_clears_only_selected_context_and_run(self):
        from taskweave.presentation.workspace import WorkspaceNavigation, RouteState, TaskWorkspace
        editor = StepEditorState(task_id='old', step_id='s')
        execution = ExecutionPageState(run_id='r')
        contexts = ContextPageState(entries=[{'source': 'old'}], ai_contexts=[{'text': 'old'}])
        route, tabs = RouteState(page='editor'), TaskWorkspace()
        navigation = WorkspaceNavigation(route, editor, execution, contexts, tabs)
        flow = navigation.navigate('tasks', task_id='new')
        action = await flow.__anext__()
        self.assertEqual(action.kind, 'leave_editor')
        action = await flow.asend('discard')
        self.assertEqual(action.kind, 'dispose')
        self.assertEqual(action.value, 'editor')
        action = await flow.asend(None)
        self.assertEqual((editor.task_id, editor.step_id, execution.run_id), ('new', None, None))
        self.assertEqual(contexts.entries, [])
        self.assertEqual(tabs.tab, 'overview')
        self.assertEqual(action.kind, 'render')
        action = await flow.asend(None)
        self.assertEqual(action.kind, 'done')
        self.assertTrue(action.value)
        await flow.aclose()

    async def test_failed_or_stale_leave_preserves_route(self):
        from taskweave.presentation.workspace import WorkspaceNavigation, RouteState, TaskWorkspace
        editor = StepEditorState(task_id='t', step_id='s')
        route = RouteState(page='editor')
        navigation = WorkspaceNavigation(route, editor, ExecutionPageState(), ContextPageState(), TaskWorkspace())
        flow = navigation.navigate('home')
        await flow.__anext__()
        result = await flow.asend('stay')
        self.assertFalse(result.value)
        self.assertEqual(route.page, 'editor')
        await flow.aclose()

    async def test_leave_failure_preserves_draft_and_releases_autosave_pause(self):
        from taskweave.presentation.workspace import WorkspaceNavigation, RouteState, TaskWorkspace
        editor = StepEditorState(task_id='t', step_id='s', old_step={'name': 'old'})
        navigation = WorkspaceNavigation(RouteState(page='editor'), editor, ExecutionPageState(), ContextPageState(), TaskWorkspace())
        flow = navigation.leave_editor()
        self.assertEqual((await flow.__anext__()).kind, 'inspect_editor')
        self.assertTrue(editor.autosave_paused)
        self.assertEqual((await flow.asend(({'name': 'draft'}, editor.old_step))).kind, 'ask_leave')
        self.assertEqual((await flow.asend('save')).kind, 'save_editor')
        from taskweave.presentation.workspace import WorkspaceFailure
        failure = await flow.asend(WorkspaceFailure('EDIT_CONFLICT'))
        self.assertEqual(failure.kind, 'save_failed')
        self.assertEqual((await flow.asend(None)).value, 'stay')
        await flow.aclose()
        self.assertFalse(editor.autosave_paused)
        self.assertEqual(editor.old_step, {'name': 'old'})

    async def test_recovery_is_tab_scoped_and_restores_into_same_plain_states(self):
        from taskweave.presentation.workspace import WorkspaceNavigation, RouteState, TaskWorkspace
        from taskweave.presentation.state import DebugState
        first, second = {}, {}
        editor, debug = StepEditorState(), DebugState(environment_id='e')
        navigation = WorkspaceNavigation(RouteState(page='editor'), editor, ExecutionPageState(), ContextPageState(), TaskWorkspace())
        navigation.capture(first, {'step_id': 's'}, {'r': {'count': 0}}, {'s': 'r'}, debug,
                           {'environment_id': 'e', 'task': {}, 'step': {}})
        self.assertEqual(second, {})
        trials, drafts = {}, {}
        navigation.restore_snapshot(first, debug, trials, drafts)
        self.assertEqual(editor.reload_draft, {'step_id': 's'})
        self.assertEqual(trials, {'s': 'r'})
        self.assertEqual(drafts, {'r': {'count': 0}})

    async def test_new_tab_choice_supersedes_old_leave_response(self):
        from taskweave.presentation.workspace import TaskTabTransition, TaskWorkspace
        state = TaskWorkspace()
        state.tab = 'steps'
        old = TaskTabTransition(state, 'overview', page='editor')
        self.assertEqual(old.begin().kind, 'leave_editor')
        new = TaskTabTransition(state, 'debug_history', page='editor')
        new.begin()
        self.assertEqual(new.resolve('save').kind, 'render')
        self.assertFalse(old.resolve('discard').value)
        self.assertEqual(state.tab, 'debug_history')

    async def test_navigation_runs_with_gui_imports_blocked(self):
        import subprocess
        import sys
        code = '''
import importlib.abc, sys, asyncio
class BlockGUI(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'nicegui', 'webview'} or fullname.startswith('taskweave.desktop'):
            raise AssertionError(fullname)
sys.meta_path.insert(0, BlockGUI())
from taskweave.presentation.workspace import WorkspaceNavigation, RouteState, TaskWorkspace
from taskweave.presentation.state import StepEditorState, ExecutionPageState, ContextPageState
async def main():
    editor = StepEditorState(task_id='old', step_id='s')
    route = RouteState(page='editor')
    navigation = WorkspaceNavigation(route, editor, ExecutionPageState(), ContextPageState(), TaskWorkspace())
    flow = navigation.navigate('tasks', task_id='new')
    assert (await flow.__anext__()).kind == 'leave_editor'
    assert (await flow.asend('save')).kind == 'dispose'
    assert (await flow.asend(None)).kind == 'render'
    assert (await flow.asend(None)).value is True
    assert editor.task_id == 'new' and route.page == 'tasks'
    await flow.aclose()
asyncio.run(main())
'''
        result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
