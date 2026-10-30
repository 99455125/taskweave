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

    async def render(self, host, step, baseline, *, current: Callable[[], bool], toolbar_host, logs_host):
        host.clear()
        toolbar_host.clear()
        logs_host.clear()
        with toolbar_host:
            with ui.row().classes('tw-debug-runbar w-full items-center gap-3'):
                environment = await self.environment_select()
                environment.classes(remove='w-72', add='tw-debug-environment min-w-0')
                if not current(): return False
                self.views['trial_environment'] = environment
                self.panel.run_status = ui.label('尚未调试').classes('tw-debug-run-status text-sm')
                ui.space()
                self.panel.render_actions(
                    ui.row().classes('tw-debug-actions items-center gap-2'),
                    lambda: self.session.start_trial(continue_session=True), self.session.start_flow_trial,
                    lambda: self.panel.end(self.confirm_end, self.panel.refresh_trial),
                )
            from taskweave.desktop.components.debug_sources import DebugSources
            sources = DebugSources(self.panel.controller, self.state, step, lambda: environment.value, current)
            self.session.refresh_sources = sources.refresh
            await sources.render()
            if not current(): return False
            async def refresh_sources(_event):
                await sources.refresh()
            environment.on_value_change(refresh_sources)
            self.views['trial_start_status'] = ui.label().classes('text-sm text-gray-500')
            self.panel.history_control = ui.select({}, value=None, label='查看调试记录',
                on_change=lambda event: self.panel.select_history_run(event.value)).props('outlined dense').classes('tw-debug-history-select w-full')
            self.panel.history_control.disable()
            with ui.expansion('调试输入', icon='tune').classes('tw-debug-inputs w-full'):
                self.views['trial_variables_area'] = ui.column().classes('w-full')
                with self.views['trial_variables_area']:
                    form = await self.trial_variables(baseline, environment)
                if not current(): return False
                self.views['trial_form'] = form
                form.input_draft.bind(self.state, (step['task_id'], step['step_id']))
                await sources.render_results()
                if not current(): return False
                recovered = self.editor_state.reload_debug
                if recovered and (recovered['task_id'], recovered['step_id']) == (step['task_id'], step['step_id']):
                    form.apply_task_values(recovered['task'])
                    form.apply_step_values(recovered['step'])
                    self.editor_state.reload_debug = None
            with ui.expansion('运行记录与结果', icon='history').classes('tw-debug-records w-full'):
                self.panel.trial_area = ui.column().classes('w-full')
        with host:
            with ui.column().classes('tw-debug-drawer tw-panel bg-white gap-3') as self.container:
                with ui.row().classes('w-full items-center gap-2'):
                    ui.icon('auto_awesome').classes('text-primary')
                    ui.label('AI 修复').classes('text-base font-semibold')
                ui.label(step['name']).classes('text-sm text-gray-500')
                preferences = self.ai_editor.repair_forms.setdefault((step['task_id'], step['step_id']),
                    {'channel': 'api', 'history': -1, 'deduplicate': True})
                channel = ui.select({'api': 'API 调用', 'chat': '网页 Chat'},
                    value=preferences['channel'], label='生成方式').props('outlined dense').classes('w-full')
                channel.on_value_change(lambda event: preferences.__setitem__('channel', event.value))
                self.views['trial_ai_channel'] = channel
                self.panel.repair_evidence_area = ui.column().classes('tw-repair-evidence w-full gap-2')
                supplement = ui.textarea('本轮修复要求', value=self.state.supplements.get(step['step_id'], ''),
                    placeholder='描述本轮需要保留或调整的内容').props('outlined autogrow debounce=50').classes('w-full')
                self.views['trial_ai_supplement'] = supplement
                supplement.on_value_change(lambda event: self.state.supplements.__setitem__(step['step_id'], event.value or ''))
                with ui.expansion('历史会话', icon='history').classes('tw-repair-history w-full'):
                    rounds = ui.select({-1: '全部历史', 0: '不带历史',
                        **{i: f'最近 {i} 轮' for i in range(1, 11)}}, value=preferences['history'],
                        label='本轮携带的历史会话').props('outlined dense').classes('w-full')
                    rounds.on_value_change(lambda event: preferences.__setitem__('history', event.value))
                    deduplicate = ui.checkbox('精简重复静态字段', value=preferences['deduplicate'])
                    deduplicate.on_value_change(lambda event: preferences.__setitem__('deduplicate', event.value))
                    self.views['trial_ai_history'] = rounds
                async def repair():
                    feedback = self.state.feedback or {}
                    await self.ai_editor.repair_from_form(channel.value, rounds.value, deduplicate.value,
                        supplement.value or '', expected_evidence=(self.state.feedback_run_id, feedback.get('attempt_id')),
                        repaint=self.repaint)
                self.panel.repair_button = self.button('生成修复建议', repair, primary=True).classes('w-full')
                self.button('查看上次 AI 结果', lambda: self.ai_editor.recover_generation(repaint=self.repaint),
                            flat=True).classes('w-full')
                async def clear_context():
                    self.ai_editor.new_debug_round(supplement)
                    self.state.trial_signature = None
                    await self.panel.refresh_trial()
                self.button('清空 AI 修复上下文', clear_context, flat=True).classes('w-full')
        with logs_host:
            with ui.column().classes('tw-debug-log-panel w-full min-w-0 gap-2'):
                ui.label('调试日志').classes('font-semibold')
                self.panel.logs_area = ui.column().classes('tw-debug-log-body w-full')
        if not current(): return False
        async def poll():
            if (current() and toolbar_host.visible and self.poll_allowed()
                    and not getattr(self.session, 'flow_dialog_open', False)
                    and not getattr(self.ai_editor, '_ai_flow_active', False)):
                await self.panel.poll()
        self.own_timer(ui.timer(1, poll))
        return True
