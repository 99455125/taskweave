"""Tab-scoped recovery of plain drafts and selected debug evidence."""
from copy import deepcopy
from dataclasses import asdict, dataclass


class RecoveryState:
    @staticmethod
    def capture(target, draft, drafts, trials, debug, inputs):
        if draft:
            target['step'] = deepcopy(draft)
        else:
            target.pop('step', None)
        target['input_drafts'] = deepcopy(drafts)
        target['debug'] = deepcopy({'trials': trials, 'state': asdict(debug), 'inputs': inputs})

    @staticmethod
    def restore(source, editor, debug, trials, drafts):
        editor.reload_draft = deepcopy(source.get('step'))
        drafts.clear()
        drafts.update(deepcopy(source.get('input_drafts', {})))
        saved = source.get('debug', {})
        trials.update(deepcopy(saved.get('trials', {})))
        for key, value in saved.get('state', {}).items():
            if key != 'trial_signature':
                setattr(debug, key, deepcopy(value))
        editor.reload_debug = deepcopy(saved.get('inputs'))


class TaskWorkspace:
    """Own tab selection and invalidate pending transitions on a newer choice."""
    def __init__(self):
        self.tab = 'overview'
        self.generation = 0
        self.switch_generation = 0

    def begin(self, value):
        self.switch_generation += 1
        return self.switch_generation

    def commit(self, token, value):
        if token != self.switch_generation:
            return False
        self.tab = value
        return True


from taskweave.core.validation import TaskError
from taskweave.presentation.editor import is_dirty


@dataclass
class RouteState:
    page: str = 'home'
    generation: int = 0
    debug_open: bool = False


@dataclass(frozen=True)
class WorkspaceFailure:
    message: str
    code: str = ''


@dataclass(frozen=True)
class WorkspaceAction:
    kind: str
    value: object = None


class WorkspaceNavigation:
    """Own route/selection transitions; adapters satisfy explicit UI actions.

    Async generators suspend at confirmation, persistence and rendering boundaries.
    Their input and output values contain no framework objects or rendering callbacks.
    """
    def __init__(self, route, editor, execution, contexts, tabs):
        self.route, self.editor, self.execution, self.contexts, self.tabs = route, editor, execution, contexts, tabs

    def identity(self):
        return self.route.generation, self.editor.task_id, self.editor.step_id, self.editor.generation

    async def leave_editor(self):
        origin = self.identity()
        self.editor.autosave_paused = True
        try:
            async with self.editor.save_lock:
                pass
            if origin != self.identity():
                yield WorkspaceAction('done', 'stay')
                return
            snapshot = yield WorkspaceAction('inspect_editor')
            dirty = isinstance(snapshot, WorkspaceFailure) or bool(snapshot and is_dirty(*snapshot))
            if not dirty:
                yield WorkspaceAction('done', 'save')
                return
            choice = yield WorkspaceAction('ask_leave')
            if origin != self.identity() or choice not in {'save', 'discard'}:
                yield WorkspaceAction('done', 'stay')
                return
            if choice == 'discard':
                yield WorkspaceAction('done', 'discard')
                return
            failure = yield WorkspaceAction('save_editor')
            if failure is not None:
                if origin == self.identity():
                    yield WorkspaceAction('save_failed', failure.message)
                yield WorkspaceAction('done', 'stay')
                return
            yield WorkspaceAction('done', 'save' if origin == self.identity() else 'stay')
        finally:
            self.editor.autosave_paused = False

    async def navigate(self, page, task_id=None, step_id=None, *, planning_save=False, environment_guard=False):
        origin = self.identity()
        if self.route.page == 'planning' and planning_save:
            yield WorkspaceAction('save_planning')
        if self.route.page == 'environment' and environment_guard:
            allowed = yield WorkspaceAction('leave_environment')
            if not allowed:
                yield WorkspaceAction('done', False)
                return
        decision = yield WorkspaceAction('leave_editor')
        if decision == 'stay' or origin != self.identity():
            yield WorkspaceAction('done', False)
            return
        next_task = task_id if task_id is not None else self.editor.task_id
        next_step = step_id if step_id is not None else self.editor.step_id
        task_changed = task_id is not None and task_id != self.editor.task_id
        if (next_task, next_step) != (self.editor.task_id, self.editor.step_id):
            self.editor.generation += 1
        self.route.generation += 1
        yield WorkspaceAction('dispose', self.route.page)
        self.route.page = page
        if task_id is not None:
            if task_changed:
                self.editor.step_id = self.execution.run_id = None
                self.contexts.entries = []
                self.contexts.ai_contexts = []
            self.editor.task_id = task_id
            if task_changed and page == 'tasks':
                self.tabs.tab = 'overview'
        if step_id is not None:
            if self.editor.step_id != step_id:
                self.contexts.entries = []
                self.contexts.ai_contexts = []
            self.editor.step_id = step_id
            self.tabs.tab = 'steps'
        elif page == 'history':
            self.tabs.tab = 'debug_history'
        yield WorkspaceAction('render')
        self.route.debug_open = False
        yield WorkspaceAction('done', True)

    async def restore(self, view='home', task_id=None, step_id=None, debug=False):
        if view not in {'home', 'planning', 'tasks', 'editor', 'sequences', 'executions', 'plugins', 'marketplace', 'environment', 'settings'}:
            yield WorkspaceAction('done', False)
            return
        if task_id:
            yield WorkspaceAction('read_task', task_id)
        if step_id:
            step = yield WorkspaceAction('read_step', step_id)
            if task_id and step['task_id'] != task_id:
                raise TaskError('CONTEXT_MISMATCH', '页面任务与步骤不匹配')
            task_id = step['task_id']
        self.route.page, self.editor.task_id, self.editor.step_id = view, task_id, step_id
        if view == 'editor':
            self.tabs.tab = 'steps'
        self.route.debug_open = debug
        yield WorkspaceAction('done', True)

    def capture(self, target, draft, drafts, trials, debug, inputs):
        RecoveryState.capture(target, draft if self.route.page == 'editor' else None,
                              drafts, trials, debug, inputs if self.route.page == 'editor' else None)

    def restore_snapshot(self, source, debug, trials, drafts):
        RecoveryState.restore(source, self.editor, debug, trials, drafts)
        if self.editor.reload_debug:
            debug.environment_id = self.editor.reload_debug['environment_id']


class TaskTabTransition:
    """A tab choice and its leave decision share one versioned transition."""
    allowed = frozenset({'overview', 'steps', 'execution_history', 'debug_history'})

    def __init__(self, workspace, value, *, page):
        self.workspace, self.value = workspace, value
        self.previous = workspace.tab
        self.token = workspace.begin(value)
        self.page = page

    def begin(self):
        if self.value not in self.allowed:
            return WorkspaceAction('done', False)
        if self.value == 'steps' and self.page != 'editor':
            self.workspace.tab = self.value
            return WorkspaceAction('route_editor')
        if self.previous == 'steps' and self.value != 'steps':
            return WorkspaceAction('leave_editor')
        return self.resolve('save')

    def resolve(self, choice):
        if self.token != self.workspace.switch_generation:
            return WorkspaceAction('done', False)
        if choice not in {'save', 'discard'}:
            self.workspace.tab = self.previous
            return WorkspaceAction('restore_tab', self.previous)
        self.workspace.commit(self.token, self.value)
        return WorkspaceAction('discard_render' if choice == 'discard' else 'render', self.value)

    def route_result(self, accepted):
        if self.token != self.workspace.switch_generation:
            return WorkspaceAction('done', False)
        if accepted is False:
            self.workspace.tab = self.previous
            return WorkspaceAction('restore_tab', self.previous)
        return WorkspaceAction('done', accepted)
