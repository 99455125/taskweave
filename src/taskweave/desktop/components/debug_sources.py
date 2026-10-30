"""Compact explicit resource scene and optional result-sample selection."""
from nicegui import ui


class DebugSources:
    def __init__(self, controller, state, step, environment_id, current):
        self.controller, self.state, self.step = controller, state, step
        self.environment_id, self.current = environment_id, current
        self.scene = self.results = None
        self.rows = {}

    async def refresh(self):
        rows = await self.controller.call('step.trial.sessions', step_id=self.step['step_id'],
                                          environment_id=self.environment_id())
        if not self.current() or self.scene.is_deleted:
            return
        self.rows = {row['session_id']: row for row in rows}
        options = {'new': '新建现场', **{key: f"{row['task_name']} · {row['step_name']} · {key[:8]}"
                                       for key, row in self.rows.items()}}
        selected = (self.state.scene or {}).get('session_id', 'new')
        if selected not in options:
            options[selected] = '所选现场已结束 · 请重新选择'
        self.scene.set_options(options, value=selected)

    async def render(self):
        with ui.row().classes('w-full items-center gap-2 flex-nowrap'):
            self.scene = ui.select({'new': '新建现场'}, value='new', label='调试现场').props(
                'dense outlined options-dense').classes('min-w-0 flex-1')
            ui.button(icon='refresh', on_click=self.refresh).props('flat round dense').tooltip('刷新现场')
        if self.state.scene is None:
            self.state.scene = {}
        await self.refresh()
        self.scene.on_value_change(self._select_scene)
        return self

    def _select_scene(self, event):
        if not self.current():
            return
        if event.value == 'new':
            self.state.scene = {}
        elif event.value in self.rows:
            row = self.rows[event.value]
            self.state.scene = {'run_id': row['run_id'], 'session_id': row['session_id']}

    async def render_results(self):
        dependencies = {binding['ref']['step_id'] for binding in self.step.get('bindings', {}).values()
                        if binding.get('ref', {}).get('source') == 'step'}
        if not dependencies:
            return
        rows = await self.controller.call('run.list', task_id=self.step['task_id'])
        if not self.current():
            return
        details = []
        for row in rows:
            run = await self.controller.call('run.get', run_id=row['run_id'])
            if not self.current():
                return
            if run['environment_id'] == self.environment_id():
                details.append(run)
        rows = details
        choices = {row['run_id']: f"{row.get('started_at') or '尚未开始'} · {row['run_id'][:8]}" for row in rows}
        selected = self.state.source_run_id
        if selected not in choices:
            selected = None
            self.state.source_run_id, self.state.source_paths = None, {}
        with ui.row().classes('w-full items-center gap-2'):
            self.results = ui.select({'': '请选择来源运行', **choices}, value=selected or '',
                                     label='前序结果来源').props('dense outlined options-dense').classes('flex-1 min-w-0')
        paths_host = ui.column().classes('w-full')

        async def choose(event):
            if not self.current():
                return
            self.state.source_run_id = event.value or None
            self.state.source_paths = {}
            await render_paths()

        async def render_paths():
            paths_host.clear()
            run_id = self.state.source_run_id
            if not run_id:
                return
            run = await self.controller.call('run.get', run_id=run_id)
            if not self.current() or self.state.source_run_id != run_id or paths_host.is_deleted:
                return
            with paths_host:
                for step_id in sorted(dependencies):
                    attempts = [a for a in run.get('attempts', []) if a['step_id'] == step_id
                                and a['valid'] and a['status'] == 'SUCCEEDED' and a.get('execution_path')]
                    paths = list(dict.fromkeys(a['execution_path'] for a in attempts))
                    if len(paths) == 1:
                        self.state.source_paths[step_id] = paths[0]
                    elif len(paths) > 1:
                        previous = self.state.source_paths.get(step_id)
                        if previous not in paths:
                            self.state.source_paths.pop(step_id, None)
                            previous = None
                        control = ui.select({path: path for path in paths}, value=previous,
                                            label='结果实例 · ' + step_id[:8]).props(
                            'dense outlined').classes('w-full')
                        control.on_value_change(lambda event, sid=step_id: self.state.source_paths.update({sid: event.value}))

        self.results.on_value_change(choose)
        await render_paths()
