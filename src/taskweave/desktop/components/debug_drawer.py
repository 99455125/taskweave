"""Debug drawer rendering and its view resources, separate from document editing."""
from typing import Awaitable, Callable
from nicegui import ui


class StepDebugDrawer:
    def __init__(self, *, panel, session, ai_editor, state, editor_state, views,
                 button, environment_select, trial_variables, confirm_end, repaint,
                 on_visibility: Callable[[bool], None], poll_allowed: Callable[[], bool],
                 own_timer):
        self.panel, self.session, self.ai_editor = panel, session, ai_editor
        self.state, self.editor_state, self.views = state, editor_state, views
        self.button, self.environment_select, self.trial_variables = button, environment_select, trial_variables
        self.confirm_end, self.repaint = confirm_end, repaint
        self.on_visibility, self.poll_allowed, self.own_timer = on_visibility, poll_allowed, own_timer
        self.container = None

    @property
    def environment_id(self):
        return self.state.environment_id

    def set_visible(self, visible):
        self.on_visibility(visible)
        if visible and self.container is not None:
            self.container.style('width: 100%; min-width: 0; max-height: calc(100vh - 300px); overflow-y: auto')

    async def refresh(self):
        await self.panel.refresh_trial()

    async def render(self, host, step, baseline, *, current: Callable[[], bool]):
        host.clear()
        with host:
            with ui.column().classes('tw-debug-drawer tw-panel bg-white gap-3') as self.container:
                with ui.row().classes('w-full items-center justify-between gap-2'):
                    with ui.column().classes('gap-0'):
                        ui.label('调试 · ' + step['name']).classes('text-lg font-medium')
                environment = await self.environment_select()
                environment.classes(remove='w-72', add='w-full min-w-0')
                if not current(): return False
                self.views['trial_environment'] = environment
                self.views['trial_variables_area'] = ui.column().classes('w-full')
                with self.views['trial_variables_area']:
                    form = await self.trial_variables(baseline, environment)
                if not current(): return False
                self.views['trial_form'] = form
                form.input_draft.bind(self.state, (step['task_id'], step['step_id']))
                recovered = self.editor_state.reload_debug
                if recovered and (recovered['task_id'], recovered['step_id']) == (step['task_id'], step['step_id']):
                    form.apply_task_values(recovered['task'])
                    form.apply_step_values(recovered['step'])
                    self.editor_state.reload_debug = None
                self.views['trial_start_status'] = ui.label().classes('text-sm text-gray-500')
                self.panel.render_actions(
                    ui.column().classes('tw-debug-actions w-full gap-2'),
                    lambda: self.session.start_trial(continue_session=True), self.session.start_flow_trial,
                    lambda: self.panel.end(self.confirm_end, self.panel.refresh_trial),
                )
                self.panel.trial_area = ui.column().classes('w-full')
                ui.separator()
                supplement = ui.textarea('AI 补充说明（可选）', value=self.state.supplements.get(step['step_id'], ''),
                    placeholder='仅用于当前调试轮次，例如：点击结果后会打开新标签页。').props('outlined autogrow debounce=50').classes('w-full')
                self.views['trial_ai_supplement'] = supplement
                supplement.on_value_change(lambda event: self.state.supplements.__setitem__(step['step_id'], event.value or ''))
                with ui.row().classes('w-full items-center gap-2 flex-nowrap'):
                    self.button('AI 修复', lambda: self.ai_editor.choose_repair_mode(supplement, repaint=self.repaint)).classes('flex-1 min-w-0')
                    async def clear_context(): self.ai_editor.new_debug_round(supplement)
                    self.button('清空 AI 修复上下文', clear_context).classes('flex-1 min-w-0')
            with ui.column().classes('tw-debug-log-panel tw-panel w-full min-w-0'):
                ui.label('调试日志').classes('font-semibold')
                self.panel.logs_area = ui.column().classes('tw-debug-log-body w-full')
        if not current(): return False
        async def poll():
            if (current() and host.visible and self.poll_allowed()
                    and not getattr(self.session, 'flow_dialog_open', False)
                    and not getattr(self.ai_editor, '_ai_flow_active', False)):
                await self.panel.poll()
        self.own_timer(ui.timer(1, poll))
        return True
