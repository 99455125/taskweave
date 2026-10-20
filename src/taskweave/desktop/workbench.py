"""Cross-platform NiceGUI workbench backed by the existing application service."""

from datetime import datetime, timezone
from pathlib import Path
import asyncio
import json
import logging
from copy import deepcopy

from nicegui import ui
from taskweave.desktop.theme import STYLE
from taskweave.core.validation import TaskError, normalize_step
from taskweave.desktop.controller import command_id
from taskweave.desktop.forms import SchemaEditor, ValueForm
from taskweave.desktop.display import execution_title, readable_metadata, step_names, image_reference
from taskweave.desktop.pages.planning import PlanningPage
from taskweave.desktop.pages.tasks import TasksPage, filter_tasks
from taskweave.desktop.pages.environments import EnvironmentPage
from taskweave.desktop.pages.history import HistoryPage
from taskweave.desktop.pages.marketplace import MarketplacePage
from taskweave.desktop.pages.plugins import PluginsPage
from taskweave.desktop.pages.settings import SettingsPage
from taskweave.desktop.components.result_viewer import ResultViewer
from taskweave.desktop.components.run_inputs import RunInputDialog
from taskweave.desktop.components.step_contexts import StepContextPanel
from taskweave.desktop.components.step_list import StepList
from taskweave.desktop.components.step_editor import StepEditor, StepEditorRenderContext
from taskweave.desktop.components.step_debug import StepDebugPanel, StepDebugSession
from taskweave.desktop.components.step_ai import StepAIEditor
from taskweave.desktop.components.execution_details import ExecutionDetails
from taskweave.desktop.pages.executions import ExecutionsPage, RunPage
from taskweave.desktop.state import ContextPageState, DebugState, ExecutionPageState, PlanningPageState, StepEditorState, RunInputState
from taskweave.desktop.contexts import (
    ContextCards,
    ContextCaptureDraft,
    ContextTargetPicker,
    context_advanced_overrides,
    merge_context_request,
    context_ai_items,
    context_hidden_parameters,
    context_target_options,
    context_view_default,
)
from taskweave.infrastructure.privacy import redact_collected_context

EMPTY = "async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n"
STATUS = {
    "DRAFT": "草稿",
    "VALIDATED": "已验证",
    "READY": "就绪",
    "RUNNING": "执行中",
    "PAUSED": "已暂停",
    "FAILED": "失败",
    "INTERRUPTED": "中断 / 待核对",
    "SUCCEEDED": "成功",
    "CANCELLED": "已结束",
    "UNKNOWN": "结果待核对",
}
ERRORS = {
    "TASK_LOCKED": "任务有活跃运行，请先结束运行再修改。",
    "RUN_LEASE_BUSY": "另一个运行占用了执行器，请先结束该运行。",
    "STEP_NOT_VALIDATED": "请先确认所有步骤。",
    "MODEL_NOT_CONFIGURED": "尚未配置 AI；可以手写步骤，或到设置中配置模型。",
    "EDIT_CONFLICT": "内容已被修改，请重新打开步骤。",
    "RECONCILIATION_REQUIRED": "先查询业务系统并核对执行结果，再继续。",
    "EXPLICIT_RETRY_REQUIRED": "请选中失败步骤并点击“重试选中步骤”。",
    "PLUGIN_CONFIG_LOCKED": "活跃运行期间不能修改插件配置。",
    "EXECUTOR_CAPACITY": "执行器已达并发上限，请等待已有运行结束或手动结束实例。",
}
MAIN_NAV_ITEMS = (
    ("home", "工作台"), ("planning", "规划"), ("tasks", "任务"), ("executions", "执行"),
    ("plugins", "插件"), ("marketplace", "集市"), ("environment", "环境"),
    ("settings", "设置"),
)
MAIN_NAV_ICONS = {
    "home": "space_dashboard", "planning": "assignment", "tasks": "checklist",
    "executions": "play_circle_outline", "plugins": "extension",
    "marketplace": "storefront", "environment": "dns", "settings": "tune",
}


def document_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


class Workbench:
    def _route_state(self):
        from taskweave.presentation.workspace import RouteState
        if not hasattr(self, '_route'):
            self._route = RouteState()
        return self._route

    @property
    def page(self): return self._route_state().page
    @page.setter
    def page(self, value): self._route_state().page = value
    @property
    def page_generation(self): return self._route_state().generation
    @page_generation.setter
    def page_generation(self, value): self._route_state().generation = value
    @property
    def _open_debug_on_navigation(self): return self._route_state().debug_open
    @_open_debug_on_navigation.setter
    def _open_debug_on_navigation(self, value): self._route_state().debug_open = value

    def _workspace_navigation(self):
        from taskweave.presentation.workspace import WorkspaceNavigation, TaskWorkspace
        editor = self._editor_state()
        if not hasattr(self, 'execution_state'):
            self.execution_state = ExecutionPageState()
        tasks_page = getattr(self, 'tasks_page', None)
        # Legacy lightweight adapters expose only workspace_tab; the real page
        # supplies the same TaskWorkspace used by its tab actions.
        tabs = getattr(tasks_page, 'workspace', None)
        if tabs is None:
            tabs = TaskWorkspace()
            if tasks_page is not None:
                tabs.tab = tasks_page.workspace_tab
        return WorkspaceNavigation(
            self._route_state(), getattr(editor, 'interaction', editor),
            self.execution_state.interaction, self._context_state(), tabs,
        )

    @property
    def debug_supplements(self):
        return self._debug_state().supplements

    @debug_supplements.setter
    def debug_supplements(self, value):
        self._debug_state().supplements = value

    @property
    def debug_feedback(self):
        return self._debug_state().feedback

    @debug_feedback.setter
    def debug_feedback(self, value):
        self._debug_state().feedback = value

    @property
    def debug_feedback_run_id(self):
        return self._debug_state().feedback_run_id

    @debug_feedback_run_id.setter
    def debug_feedback_run_id(self, value):
        self._debug_state().feedback_run_id = value

    @property
    def debug_removed_feedback(self):
        return self._debug_state().removed_feedback

    @debug_removed_feedback.setter
    def debug_removed_feedback(self, value):
        self._debug_state().removed_feedback = value

    @property
    def trial_signature(self):
        return self._debug_state().trial_signature

    @trial_signature.setter
    def trial_signature(self, value):
        self._debug_state().trial_signature = value

    @property
    def debug_round_fresh(self):
        return self._debug_state().fresh_round

    @debug_round_fresh.setter
    def debug_round_fresh(self, value):
        self._debug_state().fresh_round = value

    def _debug_state(self):
        if not hasattr(self, "debug_state"):
            self.debug_state = DebugState()
        return self.debug_state

    @property
    def context_entries(self):
        return self._context_state().entries

    @context_entries.setter
    def context_entries(self, value):
        self._context_state().entries = value

    @property
    def contexts(self):
        return self._context_state().ai_contexts

    @contexts.setter
    def contexts(self, value):
        self._context_state().ai_contexts = value

    @property
    def context_cards(self):
        panel = getattr(self, "step_context_panel", None)
        return panel.cards if panel else getattr(self, "_context_cards_compat", None)

    @context_cards.setter
    def context_cards(self, value):
        panel = getattr(self, "step_context_panel", None)
        if panel:
            panel.cards = value
        else:
            self._context_cards_compat = value

    def _context_state(self):
        if not hasattr(self, "context_state"):
            self.context_state = ContextPageState()
        return self.context_state

    @property
    def execution_task_ids(self):
        return self._execution_page_state().task_ids

    @execution_task_ids.setter
    def execution_task_ids(self, value):
        self._execution_page_state().task_ids = value

    @property
    def execution_statuses(self):
        return self._execution_page_state().statuses

    @execution_statuses.setter
    def execution_statuses(self, value):
        self._execution_page_state().statuses = value

    @property
    def execution_signature(self):
        return self._execution_page_state().signature

    @execution_signature.setter
    def execution_signature(self, value):
        self._execution_page_state().signature = value

    @property
    def run_id(self):
        return self._execution_page_state().run_id

    @run_id.setter
    def run_id(self, value):
        self._execution_page_state().run_id = value

    @property
    def run_signature(self):
        return self._execution_page_state().run_signature

    @run_signature.setter
    def run_signature(self, value):
        self._execution_page_state().run_signature = value

    @property
    def execution_rows(self):
        return self._execution_page_state().execution_rows

    @execution_rows.setter
    def execution_rows(self, value):
        self._execution_page_state().execution_rows = value

    @property
    def run_area(self):
        return self._execution_page_state().run_area

    @run_area.setter
    def run_area(self, value):
        self._execution_page_state().run_area = value

    @property
    def countdown_label(self):
        return self._execution_page_state().countdown_label

    @countdown_label.setter
    def countdown_label(self, value):
        self._execution_page_state().countdown_label = value

    def _execution_page_state(self):
        if not hasattr(self, "execution_state"):
            self.execution_state = ExecutionPageState()
        return self.execution_state

    @property
    def task_id(self):
        return self._editor_state().task_id

    @task_id.setter
    def task_id(self, value):
        self._editor_state().task_id = value

    @property
    def step_id(self):
        return self._editor_state().step_id

    @step_id.setter
    def step_id(self, value):
        self._editor_state().step_id = value

    @property
    def edit_controls(self):
        return self._editor_state().edit_controls

    @edit_controls.setter
    def edit_controls(self, value):
        self._editor_state().edit_controls = value

    @property
    def old_step(self):
        return self._editor_state().old_step

    @old_step.setter
    def old_step(self, value):
        self._editor_state().old_step = value

    def _editor_state(self):
        if not hasattr(self, "step_state"):
            self.step_state = StepEditorState()
        return self.step_state

    def __init__(self, controller, route_writer=None, *, reload_state=None):
        self.reload_state = None
        self.route_writer = route_writer
        self.controller = controller
        self.page = "home"
        self.execution_state = ExecutionPageState()
        self.run_id = None
        self.step_state = StepEditorState()
        self.step_editor = StepEditor(
            controller, self.step_state, lambda: self.page_generation,
            trial_variables=self.trial_variables,
        )
        self.context_state = ContextPageState()
        self.debug_state = DebugState()
        self.page_generation = 0
        self.task_id = self.step_id = None
        self.execution_task_ids, self.execution_statuses = [], []
        self.environment_id = None
        self.trials, self.contexts, self.context_entries = {}, [], []
        self.step_ai_editor = StepAIEditor(
            controller, self.button, self.save_editor, lambda: self.environment_id,
            lambda: self.edit_controls,
            lambda: (self.task_id, self.step_id, self.step_state.generation, self.page_generation),
            debug_state=self.debug_state, trials=self.trials,
            draft_values=lambda: self.step_state.draft,
            reset_conversation=controller.reset_debug_conversation,
            confirmation_step=self.step_for_confirmation,
            author_step=controller.author_step if hasattr(type(controller), 'author_step') else None,
            authoring_request=controller.authoring_request if hasattr(type(controller), 'authoring_request') else None,
        )
        self.busy = False
        self.save_lock = self.step_state.save_lock
        ui.colors(primary="#2563eb", positive="#15803d", negative="#dc2626")
        ui.add_css(STYLE)
        self.nav_buttons = {}
        with ui.header().classes("tw-header bg-white text-gray-800 items-center"):
            with ui.row().classes("items-center gap-2"):
                ui.icon("layers", size="24px").classes("tw-brand-mark")
                ui.label("TaskWeave").classes("tw-brand")
            with ui.row().classes("tw-main-nav items-center"):
                for page, title in MAIN_NAV_ITEMS:
                    control = self.button(title, lambda p=page: self.navigate(p), flat=True, icon=MAIN_NAV_ICONS[page])
                    control.classes("tw-nav")
                    self.nav_buttons[page] = control
            with ui.row().classes("items-center gap-2"):
                with ui.row().classes("tw-local-indicator items-center gap-2"):
                    ui.icon("circle", size="7px").classes("text-green-500")
                    ui.label("本地工作空间")
                self.button("执行实例", self.instance_dialog, flat=True, icon="devices")
                if hasattr(controller, "open_logs"):
                    self.button("实时日志", controller.open_logs, flat=True, icon="description")
        self.content = ui.column().classes("tw-content tw-app-content w-full")
        from taskweave.desktop.task_panels import TaskEditorPanel, TaskHistoryPanels, TaskLifecycle
        self.tasks_page = TasksPage(
            controller, self.button, self.navigate, self.paint,
            lifecycle=TaskLifecycle(self._on_task_runs_cleared, self._on_task_deleted,
                                    self._before_task_update, self._after_task_update),
            task_id=lambda: self.task_id, step_id=lambda: self.step_id,
            page_generation=lambda: self.page_generation,
            editor_panel=TaskEditorPanel(self.editor, self.save_editor,
                self.prepare_step_editor_leave, self.discard_step_editor_for_workspace_tab,
                self.create_first_step_from_workspace),
            history_panels=TaskHistoryPanels(
                lambda task_id: self.render_task_history(task_id, 'EXECUTION'),
                lambda task_id: self.render_task_history(task_id, 'TRIAL'), self.open_task_execution),
            page_identity=lambda: (self.page, self.page_generation),
        )
        self.environment_page = EnvironmentPage(
            controller, self.button, self.paint,
            self._on_environment_default_selected, self._on_environment_deleted,
            page_identity=lambda: (self.page, self.page_generation),
        )
        self.plugins_page = PluginsPage(controller, self.button, self.paint)
        self.marketplace_page = MarketplacePage(controller, self.button, self.navigate)
        self.settings_page = SettingsPage(controller, self.button)
        self.result_viewer = ResultViewer(controller, self.button)
        self.run_input_dialog = RunInputDialog(
            controller, RunInputState(), self.button, self.trial_variables,
            lambda: getattr(self, "content", None), identity=self._run_input_identity,
            apply_inputs=self._apply_run_input_values,
            invalidate_signatures=self._invalidate_run_input_signatures,
        )
        self.execution_details = ExecutionDetails(
            controller, self.execution_state, self.button, lambda: self.page, lambda: self.page_generation,
            self.pending_inputs, self.choose_run_step, self.confirm_end, self.step_error_dialog,
            self.step_result_dialog, self.reconcile_dialog,
        )
        self._document_visible = True
        ui.context.client.on_delete(self._client_deleted)
        if reload_state is not None:
            self.attach_reload_state(reload_state)
        ui.on('tw_document_visibility', lambda event: self.document_visibility_changed(event.args))
        ui.context.client.on_connect(lambda: ui.run_javascript('''
            if (!window.twVisibilityListener) {
                window.twVisibilityListener = () => emitEvent('tw_document_visibility', !document.hidden);
                document.addEventListener('visibilitychange', window.twVisibilityListener);
            }
            window.twVisibilityListener();
        '''))
        self.step_list = StepList(
            controller, self.button, lambda: self.task_id, lambda: self.step_id,
            lambda: (self.task_id, self.step_id, self.step_state.generation, self.page_generation),
            self.save_editor, lambda step_id: self.navigate("editor", step_id=step_id),
            self._select_step_from_list, self.paint, self.animate_reorder, self.finish_reorder_animation,
        )
        self.step_context_panel = StepContextPanel(
            controller, self.context_state, lambda: self.step_id, None, None, None,
            self.mark_step_pending, save_editor=self.save_editor,
            plugin_contributions=controller.plugin_contributions,
            task_id=lambda: self.task_id, environment_id=lambda: self.environment_id,
            button=self.button, render_result_view=self.render_result_view,
        )
        self.run_page = RunPage(
            controller, self.execution_state, self.button, self.paint, self.environment_select,
            self.trial_variables, self.execution_details, lambda: self.page,
            lambda: self.page_generation,
        )
        self.executions_page = ExecutionsPage(controller, self.execution_state, self.button, self.run_page.render)
        self.planning_page = PlanningPage(
            controller, PlanningPageState(), self.button, self.paint,
            self.navigate, self.render_result_view,
            page_identity=lambda: (self.page, self.page_generation),
        )
        self.step_debug_session = StepDebugSession(
            controller=controller,
            identity=lambda: (self.task_id, self.step_id, self.step_state.generation, self.page_generation),
            task_id=lambda: self.task_id,
            save_editor=self.save_editor,
            trial_form=lambda: self._editor_view("trial_form"),
            trial_environment=lambda: self._editor_view("trial_environment"),
            environment_select=self.environment_select,
            trial_variables=self.trial_variables,
            trials=self.trials,
            button=self.button,
            confirm_end=self.confirm_end,
            resume_inputs=self.run_input_dialog.resume_inputs,
            refresh_trial=self.refresh_trial,
            refresh_trial_inputs=self.refresh_trial_inputs,
            update_environment=lambda value: setattr(self, "environment_id", value),
            reset_feedback=self._reset_trial_feedback,
            trial_start_status=lambda: self._editor_view("trial_start_status"),
            debug_state=self.debug_state,
        )
        self.step_debug_panel = StepDebugPanel(
            self.button, controller,
            lambda: (self.task_id, self.step_id, self.step_state.generation, self.page_generation),
            lambda step_id: self.trials.get(step_id),
            lambda: self._editor_view("trial_start_status"),
            page=lambda: self.page, task_id=lambda: self.task_id, step_id=lambda: self.step_id,
            edit_controls=lambda: self.edit_controls, trials=self.trials, state=self.debug_state,
            pending_inputs=self.pending_inputs, step_result_dialog=self.step_result_dialog,
            navigate_step_debug=self.navigate_step_debug,
            debug_round_fresh=lambda: self.debug_round_fresh,
            logs_allowed=lambda: (getattr(self, '_document_visible', True) and not self.busy
                and self.tasks_page.workspace_tab == 'steps'
                and self.step_debug_panel.logs_area is not None
                and not self.step_debug_panel.logs_area.is_deleted
                and getattr(self, '_debug_visible', False)),
        )

    def _client_deleted(self):
        # A short reconnect retains the client. Only expiration invalidates late UI replies.
        self.page_generation += 1

    def _select_step_from_list(self, step_id):
        self.step_id = step_id
        self.edit_controls = None

    def button(self, title, callback, primary=False, flat=False, *, icon=None, on_failure=None, on_settled=None):
        async def action():
            if self.busy:
                return
            self.busy = True
            self._buttons = [button for button in getattr(self, '_buttons', []) if not button.is_deleted]
            for button in self._buttons:
                button._tw_before_busy = button.enabled
                button.disable()
            try:
                await callback()
            except TaskError as exc:
                if on_failure:
                    result = on_failure(exc)
                    if asyncio.iscoroutine(result):
                        await result
                if exc.code in {'RUN_LEASE_BUSY', 'RUN_STATE_INVALID'}:
                    with ui.dialog() as dialog, ui.card().classes('w-full max-w-xl'):
                        ui.label('该执行已有活跃实例，不能重复启动。').classes('text-lg font-medium')
                        ui.label('不同执行可以并行；同一条执行必须先结束现有实例。').classes('text-gray-500')
                        with ui.row().classes('gap-2'):
                            ui.button('查看实例', on_click=lambda: dialog.submit('instances')).props('outline')
                            ui.button('关闭', on_click=lambda: dialog.submit(None)).props('outline')
                    if await dialog == 'instances':
                        await self.instance_dialog()
                else:
                    ui.notify(ERRORS.get(exc.code, str(exc)), type="negative", timeout=8000)
            except (ValueError, TypeError, KeyError) as exc:
                ui.notify("配置无效：" + str(exc), type="negative", timeout=8000)
            finally:
                self.busy = False
                for button in getattr(self, '_buttons', []):
                    if button.is_deleted:
                        continue
                    if hasattr(button, '_tw_before_busy'):
                        button.set_enabled(button._tw_before_busy)
                    if hasattr(button, '_tw_before_busy'):
                        del button._tw_before_busy
                if on_settled:
                    result = on_settled()
                    if asyncio.iscoroutine(result):
                        await result

        control = ui.button(title, on_click=action, icon=icon)
        if not hasattr(self, '_buttons'):
            self._buttons = []
        self._buttons.append(control)
        if self.busy:
            control._tw_before_busy = control.enabled
            control.disable()
        control.props('flat no-caps').classes('tw-button')
        if flat:
            control.classes('tw-ghost')
        if primary:
            control.classes('tw-primary')
        return control

    async def animate_reorder(self, moving, adjacent):
        """Animate two adjacent elements exchanging places without repainting the page."""
        script = f"""
            const moving = document.getElementById('c{moving.id}');
            const adjacent = document.getElementById('c{adjacent.id}');
            if (!moving || !adjacent) return;
            const from = moving.getBoundingClientRect();
            const to = adjacent.getBoundingClientRect();
            const options = {{duration: 200, easing: 'cubic-bezier(.2,.8,.2,1)', fill: 'forwards'}};
            return Promise.all([
                moving.animate([
                    {{transform: 'translateY(0)', boxShadow: '0 0 0 rgba(15,118,110,0)'}},
                    {{transform: `translateY(${{to.top - from.top}}px)`, boxShadow: '0 8px 20px rgba(15,118,110,.18)'}}
                ], options).finished,
                adjacent.animate([
                    {{transform: 'translateY(0)'}},
                    {{transform: `translateY(${{from.top - to.top}}px)`}}
                ], options).finished,
            ]).then(() => true);
        """
        try:
            await ui.run_javascript(script, timeout=1.5)
        except Exception:  # animation support must never block a saved reorder
            logging.debug("reorder animation unavailable", exc_info=True)

    async def finish_reorder_animation(self, *elements):
        ids = ",".join(f"'c{element.id}'" for element in elements)
        try:
            await ui.run_javascript(f"""
                [{ids}].forEach(id => {{
                    const element = document.getElementById(id);
                    if (!element) return;
                    element.getAnimations().forEach(animation => animation.cancel());
                    element.animate([
                        {{backgroundColor: '#ccfbf1'}},
                        {{backgroundColor: 'transparent'}}
                    ], {{duration: 450, easing: 'ease-out'}});
                }});
            """, timeout=1.0)
        except Exception:
            logging.debug("reorder animation cleanup unavailable", exc_info=True)

    async def instance_dialog(self):
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-4xl"):
            ui.label("执行实例").classes("text-lg font-medium")
            area = ui.column().classes("w-full gap-2")

            async def refresh():
                instances = await self.controller.call("run.instances")
                tasks = {row['task_id']: row['name'] for row in await self.controller.call('task.list')}
                area.clear()
                with area:
                    if not instances:
                        ui.label("当前没有未结束的执行实例。").classes("text-gray-500")
                        return
                    for instance in instances:
                        with ui.row().classes("w-full items-center justify-between border rounded p-3 gap-3"):
                            if instance["instance_type"] in {'plan','step'}:
                                owner_label = '步骤' if instance['instance_type']=='step' else '规划'
                                with ui.column().classes("gap-0 min-w-0"):
                                    ui.label(owner_label + "采集 · " + ("采集中" if instance.get("busy") else "资源保留")).classes("font-medium")
                                    ui.label(owner_label + "实例 " + instance["owner_id"]).classes("text-sm text-gray-500")
                                async def end_plan(current=instance):
                                    await self.controller.call("instance.end", instance_type=current['instance_type'], owner_id=current["owner_id"])
                                    await refresh()
                                self.button("结束实例", end_plan)
                                continue
                            kind = "调试" if instance["instance_type"] == "trial" else "正式执行"
                            with ui.column().classes("gap-0 min-w-0"):
                                ui.label(f"{kind} · {instance['status']}").classes("font-medium")
                                ui.label(f"{tasks.get(instance['task_id'], '已删除任务')} · {execution_title(instance)}").classes("text-sm text-gray-500")

                            async def end(current=instance):
                                operation = "cancel" if current["status"] == "RUNNING" else "abandon"
                                await self.controller.call("run.control", run_id=current["run_id"], command_id=command_id(), operation=operation)
                                if operation == "cancel":
                                    await self.controller.call("run.wait", run_id=current["run_id"], timeout=5)
                                    latest = await self.controller.call("run.get", run_id=current["run_id"])
                                    if latest.get("can_end"):
                                        await self.controller.call("run.control", run_id=current["run_id"], command_id=command_id(), operation="abandon")
                                await refresh()

                            self.button("结束实例", end)
            await refresh()
            with ui.row().classes("w-full justify-end"):
                ui.button("关闭", on_click=dialog.close).props("outline")
        dialog.open()

    def _step_editor_identity(self):
        return (self.page_generation, self.task_id, self.step_id, self.step_state.generation)

    def _step_editor_is_dirty(self):
        dirty = False
        if self.edit_controls and self.old_step:
            try:
                dirty = normalize_step(self.document()) != normalize_step(self.old_step)
            except (TaskError, ValueError, TypeError):
                dirty = True
        return dirty

    async def prepare_step_editor_leave(self):
        """Present the framework-independent leave workflow's requested actions."""
        from taskweave.presentation.workspace import WorkspaceFailure
        flow = self._workspace_navigation().leave_editor()
        response = None
        try:
            while True:
                action = await flow.asend(response)
                response = None
                if action.kind == 'done':
                    return action.value
                if action.kind == 'inspect_editor':
                    if self.edit_controls and self.old_step:
                        try:
                            response = (self.document(), self.old_step)
                        except (TaskError, ValueError, TypeError) as exc:
                            response = WorkspaceFailure(str(exc), getattr(exc, "code", type(exc).__name__))
                elif action.kind == 'ask_leave':
                    with ui.dialog() as dialog, ui.card():
                        ui.label("步骤有尚未保存的修改，是否离开？")
                        with ui.row():
                            ui.button("继续编辑", on_click=lambda: dialog.submit("stay")).props("outline")
                            ui.button("舍弃未保存修改并离开", on_click=lambda: dialog.submit("discard"))
                            ui.button("保存并离开", on_click=lambda: dialog.submit("save")).props("outline")
                    response = await dialog
                elif action.kind == 'save_editor':
                    try:
                        await self.save_editor()
                    except Exception as exc:
                        response = WorkspaceFailure(str(exc), getattr(exc, "code", type(exc).__name__))
                elif action.kind == 'save_failed':
                    ui.notify(f"步骤保存失败，无法切换页面：{action.value}", type="negative", timeout=8000)
        finally:
            await flow.aclose()

    async def discard_step_editor_for_workspace_tab(self, value):
        """Rebuild the task workspace from persisted data after an explicit discard."""
        self.tasks_page.workspace_tab = value
        await self.paint()

    async def restore_route(self, view="home", task_id=None, step_id=None, debug=False):
        navigation = self._workspace_navigation()
        flow = navigation.restore(view, task_id, step_id, debug)
        response = None
        try:
            while True:
                action = await flow.asend(response)
                if action.kind == 'done':
                    return
                operation = 'task.get' if action.kind == 'read_task' else 'step.get'
                parameter = 'task_id' if action.kind == 'read_task' else 'step_id'
                response = await self.controller.call(operation, **{parameter: action.value})
        finally:
            await flow.aclose()

    def capture_reload_state(self):
        if self.reload_state is None:
            return
        draft = (self.step_editor.snapshot_draft()
                 if self.page == 'editor' and self._step_editor_is_dirty() else None)
        self._workspace_navigation().capture(
            self.reload_state, draft, self.run_input_dialog.state.drafts,
            self.trials, self.debug_state,
            self.step_editor.snapshot_debug_inputs() if self.page == 'editor' else None,
        )

    def attach_reload_state(self, state):
        self.reload_state = state
        self._workspace_navigation().restore_snapshot(
            state, self.debug_state, self.trials, self.run_input_dialog.state.drafts,
        )
        ui.context.client.on_disconnect(self.capture_reload_state)

    def remember_route(self):
        payload = {"view": self.page, "task_id": self.task_id, "step_id": self.step_id,
                   "debug": "true" if getattr(self, "_debug_visible", False) else None}
        writer = getattr(self, "route_writer", None)
        if writer:
            writer(payload)

    def debug_visibility_changed(self, visible):
        self._debug_visible = visible
        self.remember_route()

    def document_visibility_changed(self, visible):
        self._document_visible = bool(visible)
        self.execution_details.set_visible(self._document_visible)

    async def navigate(self, page, task_id=None, step_id=None):
        navigation = self._workspace_navigation()
        planning_save = self.page == 'planning' and bool(self.planning_page.state.save_callback)
        environment_guard = (self.page == 'environment' and self.environment_page.prepare_leave is not None)
        flow = navigation.navigate(page, task_id, step_id, planning_save=planning_save,
                                   environment_guard=environment_guard)
        response = None
        try:
            while True:
                action = await flow.asend(response)
                response = None
                if action.kind == 'done':
                    if action.value:
                        self.remember_route()
                    return action.value
                if action.kind == 'save_planning':
                    await self.planning_page.state.save_callback()
                    self.planning_page.state.save_callback = None
                elif action.kind == 'leave_environment':
                    response = await self.environment_page.prepare_leave()
                elif action.kind == 'leave_editor':
                    response = await self.prepare_step_editor_leave()
                elif action.kind == 'dispose':
                    self._dispose_page(action.value)
                elif action.kind == 'render':
                    self.edit_controls = None
                    if hasattr(self, 'tasks_page') and not hasattr(self.tasks_page, 'workspace'):
                        self.tasks_page.workspace_tab = navigation.tabs.tab
                    await self.paint()
        finally:
            await flow.aclose()

    async def navigate_step_debug(self, task_id, step_id, run_id=None, preserve_repair=False):
        self._open_debug_on_navigation = True
        try:
            navigated = await self.navigate('editor', task_id=task_id, step_id=step_id)
        finally:
            self._open_debug_on_navigation = False
        if not navigated:
            return
        if run_id:
            self.trials[step_id] = run_id
        if not preserve_repair:
            self.controller.reset_debug_conversation(step_id)
            self.debug_supplements.pop(step_id, None)
        self.debug_feedback = None
        self.debug_feedback_run_id = None
        self.debug_removed_feedback = set()
        await self.refresh_trial()

    async def paint(self):
        self.page_generation += 1
        self._dispose_page(self.page)
        self.run_signature = self.trial_signature = None
        self.content.clear()
        active_nav = "tasks" if self.page in {"editor", "history"} else "executions" if self.page == "run" else self.page
        for route, control in getattr(self, "nav_buttons", {}).items():
            control.classes(add="tw-nav-active" if route == active_nav else "", remove="" if route == active_nav else "tw-nav-active")
        with self.content:
            if self.page in {"editor", "run", "history"}:
                if not self.task_id:
                    self.page = "tasks"
            if self.page != "planning":
                self.planning_page.state.save_callback = None
            await {
                "planning": self.planning_page.render,
                "home": self.workbench_home,
                "tasks": self.tasks_page.render,
                "editor": self.tasks_page.render_task_workspace,
                "history": self.tasks_page.render_task_workspace,
                "executions": self.execution_hub,
                "run": self.run_page.render,
                "plugins": self.plugins,
                "marketplace": self.marketplace,
                "environment": self.environment,
                "settings": self.settings,
                    }[self.page]()

    def _dispose_page(self, route):
        if hasattr(self, 'run_input_dialog'):
            self.run_input_dialog.dismiss()
        if route in {"editor", "history"}:
            self.tasks_page.dispose()
        if route == "editor":
            self._step_editor().dispose()
            self.step_debug_panel.dispose()
            self.step_context_panel.dispose()
            return
        if route == "history":
            return
        if route in {"run", "executions"}:
            self.run_page.dispose()
            return
        page_name = {
            "tasks":"tasks_page", "history":"history_page", "plugins":"plugins_page",
            "marketplace":"marketplace_page", "environment":"environment_page",
            "settings":"settings_page", "planning":"planning_page",
        }.get(route)
        page = getattr(self, page_name, None) if page_name else None
        if page is not None:
            page.dispose()

    async def task_header(self):
        return await self.tasks_page.render_task_workspace()

    async def workbench_home(self):
        from taskweave.desktop.pages.home import HomePage, HomeActions
        return await HomePage(
            self.controller,
            actions=HomeActions(
                navigate=lambda route: self.navigate(route),
                open_task=lambda task: self.tasks_page.open_task(task),
                create_task=lambda: self.tasks_page.task_dialog(),
                import_task=lambda: self.tasks_page.import_task_dialog(),
                new_plan=self._open_new_plan, new_execution=self._open_new_execution,
                task_execution=self.open_task_execution, open_execution=self.open_execution,
                resume_run=self.resume_home_run, end_run=self.end_home_run,
                reconcile_run=self.reconcile_home_run),
            button=self.button, page_identity=lambda: (self.page_generation, self.page),
            status_labels=STATUS).render()

    async def _open_new_plan(self):
        # Navigation deletes the home button's slot; keep later UI work on the client.
        with ui.context.client:
            if await self.navigate("planning") is not False:
                await self.planning_page.create()

    async def _open_new_execution(self):
        # Keep the dialog on the client when its originating page is replaced.
        with ui.context.client:
            await self.run_page.open_create(on_created=lambda: self.navigate("executions"))

    async def open_task_execution(self, task_id):
        if self.page == "home":
            with ui.context.client:
                await self.run_page.open_create(task_id, on_created=lambda: self.navigate("executions"))
            return
        self.run_page.pending_task_id = task_id
        await self.navigate("executions")

    async def open_execution(self, run_id):
        if self.run_id != run_id:
            self.execution_state.selected_step_run_id = None
            self.execution_state.selected_step_id = None
        self.run_id = run_id
        await self.navigate("executions")

    async def resume_home_run(self, run, request):
        command = request.get("last_command", {})
        await self.controller.call(
            "run.start", run_id=run["run_id"], command_id=command_id(),
            mode=command.get("mode", "ALL"), target_step_id=command.get("target"),
            retry_step_id=command.get("retry"), start_step_id=command.get("from"),
        )
        await self.paint()

    async def end_home_run(self, run):
        if not run.get("can_end") or not await self.confirm_end(run):
            return
        await self.controller.call(
            "run.control", run_id=run["run_id"], command_id=command_id(),
            operation="cancel" if run["status"] == "RUNNING" else "abandon",
        )
        await self.paint()

    async def reconcile_home_run(self, run, attempt):
        self.run_id = run["run_id"]
        if await self.navigate("executions"):
            await self.reconcile_dialog(attempt)

    async def task_list(self):
        """Compatibility entry point; task UI is owned by TasksPage."""
        return await self.tasks_page.render()

    async def open_task(self, task):
        return await self.tasks_page.open_task(task)

    async def execution_hub(self):
        return await self.executions_page.render()

    async def marketplace(self):
        return await self.marketplace_page.render()

    async def export_task_dialog(self, task):
        return await self.tasks_page.export_task_dialog(task)

    async def import_task_dialog(self):
        return await self.tasks_page.import_task_dialog()

    async def clear_task_runs(self, task):
        return await self.tasks_page.clear_task_runs(task)

    async def delete_task(self, task):
        return await self.tasks_page.delete_task(task)

    async def task_dialog(self, task=None):
        return await self.tasks_page.task_dialog(task)

    async def _on_task_runs_cleared(self, task_id):
        for step in await self.controller.call("step.list", task_id=task_id):
            self.trials.pop(step["step_id"], None)
        if self.task_id == task_id:
            self.run_id = None
            self.contexts = []
            self.context_entries = []
            self.trial_signature = None

    async def _on_task_deleted(self, task_id):
        if self.task_id == task_id:
            self.task_id, self.edit_controls, self.run_id = None, None, None

    async def _before_task_update(self):
        self._task_config_tab = None
        if self.edit_controls and self.old_step:
            await self.save_editor()

    async def _after_task_update(self, task):
        if self.edit_controls:
            self.edit_controls = None
            await self.paint()
            ui.notify("任务配置已保存，任务参数已刷新。")
        else:
            await self.paint()
        self._task_config_tab = None

    async def environment_select(self):
        environments = await self.controller.call("environment.list")
        options = {
            "": "默认环境（无配置）",
            **{e["environment_id"]: e["name"] for e in environments},
        }
        if self.environment_id not in options:
            self.environment_id = ""
        if not self.environment_id:
            default = await self.controller.default_environment()
            if default in options:
                self.environment_id = default

        def change(e):
            if self.environment_id != e.value:
                self.contexts = []
                self.context_entries = []
            self.environment_id = e.value

        return ui.select(
            options,
            label="运行 / 调试环境",
            value=self.environment_id,
            on_change=change,
        ).classes("w-72")

    async def variable_form(self, schema, environment, values=None):
        configured = await self.controller.configured_inputs(self.task_id, environment.value or None)
        form = ValueForm(schema, {**configured, **(values or {})})
        async def change(e):
            form.apply_defaults(await self.controller.configured_inputs(self.task_id, e.value or None))
        environment.on_value_change(change)
        return form

    def _trial_input_panel(self):
        if not hasattr(self, "trial_input_panel"):
            from taskweave.desktop.components.trial_inputs import TrialInputPanel
            self.trial_input_panel = TrialInputPanel(self.controller, lambda: self.task_id, document_text)
        return self.trial_input_panel

    async def trial_variables(self, step, environment, values=None, *, run=None, focus=None, readonly_other=False, task_id=None):
        return await self._trial_input_panel().render(
            step, environment, values, run=run, focus=focus, readonly_other=readonly_other, task_id=task_id,
        )

    def _step_editor(self):
        if not hasattr(self, "step_editor"):
            self.step_editor = StepEditor(
                self.controller, self._editor_state(), lambda: getattr(self, "page_generation", 0),
                trial_variables=self.trial_variables,
            )
        return self.step_editor

    def _editor_identity(self):
        state = self._editor_state()
        return (state.task_id, state.step_id, state.generation, getattr(self, "page_generation", 0))

    def _editor_identity_current(self, identity):
        return self.page == "editor" and self._editor_identity() == identity

    def _run_input_identity(self, requested_run_id=None):
        selected_run_id = self.trials.get(self.step_id) if self.page == "editor" and self.step_id else self.run_id
        return (
            self.page, self.page_generation, self.task_id, self.step_id,
            self.step_state.generation, selected_run_id, requested_run_id,
        )

    async def _apply_run_input_values(self, waiting, values, identity):
        if self._run_input_identity(identity[-1]) != identity or self.page != "editor":
            return False
        editor_identity = (identity[2], identity[3], identity[4], identity[1])
        return self._step_editor().apply_trial_values(waiting, values, editor_identity)

    def _invalidate_run_input_signatures(self, identity):
        if self._run_input_identity(identity[-1]) != identity:
            return False
        self.run_signature = self.trial_signature = None
        return True

    def document(self):
        return self._step_editor().document()

    async def save_editor(self):
        editor = self._step_editor()
        identity = editor.identity()
        label = editor.view.get('save_state')
        try:
            saved = await editor.save(self.document())
        except Exception:
            if editor.identity() == identity and label and not label.is_deleted:
                label.text = '保存失败，点击重试'
            raise
        if editor.identity() == identity:
            if label and not label.is_deleted:
                label.text = '未保存修改' if self._step_editor_is_dirty() else '已保存'
            await editor.refresh_trial_inputs(saved, preserve_values=True)
        return saved

    async def step_for_confirmation(self):
        if self._step_editor_is_dirty():
            raise TaskError('STEP_UNSAVED', '请先保存步骤，再确认验证。')
        return self.old_step

    async def mark_step_pending(self):
        """Compatibility delegate to the component that owns step editor state."""
        return await self._step_editor().mark_step_pending()

    async def refresh_trial_inputs(self, step, preserve_values=True):
        """Compatibility delegate to StepEditor, which owns these controls."""
        return await self._step_editor().refresh_trial_inputs(step, preserve_values)

    def step_editor_context(self):
        from taskweave.desktop.components.debug_drawer import StepDebugDrawer
        editor = self._step_editor()
        drawer = StepDebugDrawer(
            panel=self.step_debug_panel, session=self.step_debug_session,
            ai_editor=self.step_ai_editor, state=self.debug_state, editor_state=self.step_state,
            views=editor.view, button=self.button, environment_select=self.environment_select,
            trial_variables=self.trial_variables, confirm_end=self.confirm_end, repaint=self.paint,
            on_visibility=self.debug_visibility_changed,
            poll_allowed=lambda: (getattr(self, '_document_visible', True) and not self.busy
                                  and self.tasks_page.workspace_tab == "steps"),
            own_timer=editor.own_timer,
        )
        return StepEditorRenderContext(
            state=self.step_state, context_state=self.context_state, debug_drawer=drawer,
            controller=self.controller, button=self.button, page_getter=lambda: self.page,
            page_generation_getter=lambda: self.page_generation,
            step_list=self.step_list, save_editor=self.save_editor, document=self.document,
            paint=self.paint, ai_editor=self.step_ai_editor,
            context_component=self.step_context_panel,
            open_debug_on_navigation=getattr(self, "_open_debug_on_navigation", False),
        )

    async def editor(self):
        ctx = self.step_editor_context()
        await self._step_editor().render(ctx)

    async def create_first_step_from_workspace(self, task_id):
        identity = (self.page, self.task_id, self.page_generation)
        if identity[0] != "editor" or identity[1] != task_id:
            return False
        return await self._step_editor().add_first_step(self.step_editor_context())

    def _editor_view(self, name):
        return self._step_editor().view.get(name)

    def _set_editor_view(self, name, value):
        self._step_editor().view[name] = value

    async def end_trial(self):
        self.trial_signature = None
        await self.step_debug_panel.end(self.confirm_end, self.step_debug_panel.refresh_trial)

    async def start_flow_trial(self):
        return await self.step_debug_session.start_flow_trial()

    def _reset_trial_feedback(self):
        self.debug_round_fresh = False
        self.debug_feedback = None
        self.debug_feedback_run_id = None
        self.debug_removed_feedback = set()

    async def settle_trial_start(self, run_id, timeout=0.8):
        """Compatibility delegate to the component that owns debug run lifecycle."""
        return await self.step_debug_session.settle_trial_start(run_id, timeout)

    async def resume_inputs(self, run, values, step_inputs=None):
        """Compatibility delegate to RunInputDialog's pause/resume flow."""
        return await self.run_input_dialog.resume_inputs(run, values, step_inputs)

    async def pending_inputs(self, run):
        return await self.run_input_dialog.show(run)

    async def refresh_trial(self):
        await self.step_debug_panel.refresh_trial()

    async def choose_trial_ai(self, supplement_control=None):
        return await self.step_ai_editor.choose_repair_mode(
            supplement_control, repaint=self.paint,
        )

    async def confirm(self):
        return await self.step_ai_editor.confirm_step(self.paint)

    async def generate(self, fix_logs=False, web_chat=False, supplement_override=None, history_rounds=None, deduplicate_history=True):
        step_id = self.step_id
        result = await self.step_ai_editor.generate_content(
            fix_logs=fix_logs, web_chat=web_chat,
            supplement=(supplement_override if supplement_override is not None else self.debug_supplements.get(step_id, "")) if fix_logs else "",
            run_id=self.trials.get(step_id) if fix_logs else None,
            history_rounds=history_rounds, deduplicate_history=deduplicate_history,
            feedback_override=self.debug_feedback, feedback_run_id=self.debug_feedback_run_id,
            removed_feedback=self.debug_removed_feedback,
        )
        return await self.step_ai_editor._present_generation_result(
            result, fix_logs, self.paint, web_chat=web_chat,
        )

    async def choose_generation_mode(self):
        return await self.step_ai_editor.choose_generation_mode(
            repaint=self.paint,
        )

    async def generate_goal_dialog(self):
        return await self.step_ai_editor.generate_goal_dialog()

    async def preview_goal(self, saved, description_text, notes_text="", parent=None):
        return await self.step_ai_editor.preview_goal(saved, description_text, notes_text, parent)

    async def new_debug_round(self):
        return self.step_ai_editor.new_debug_round(self._editor_view("trial_ai_supplement"))

    def render_collected_contexts(self, panel=None):
        panel = panel or self._editor_view("context_panel")
        return self.step_context_panel.render(panel)

    def render_all_context_panels(self):
        return self.step_context_panel.render_all()

    async def save_context_batch(self, existing, provider, name, notes, draft):
        return await self.step_context_panel.save_batch(existing, provider, name, notes, draft)

    async def move_context_entry(self, entry, direction):
        return await self.step_context_panel.move_group(entry, direction)

    async def delete_context_capture(self, group, capture):
        return await self.step_context_panel.delete_capture(group, capture)

    async def move_context_capture(self, group, capture, direction):
        return await self.step_context_panel.move_capture(group, capture, direction)

    async def update_context_capture_label(self, group, capture, label):
        return await self.step_context_panel.update_capture_label(group, capture, label)

    async def preview_context_entry(self, entry):
        return await self.step_context_panel.preview_capture(entry)

    async def remove_context_entry(self, entry):
        return await self.step_context_panel.remove_group(entry)

    async def collect_context(self, source_page="draft", existing=None):
        return await self.step_context_panel.collect(source_page, existing)

    async def run(self):
        return await self.run_page.render()

    async def confirm_end(self, run):
        catalog = await self.controller.call("capabilities")
        definition = json.loads(run["definition_json"])["steps"] if run.get("definition_json") else await self.controller.call("step.list", task_id=run["task_id"])
        capabilities = {cap for step in definition for cap in step.get("capabilities", [])}
        resources = set()
        for action in catalog["actions"]:
            if action["id"] in capabilities:
                resources.update(action.get("resource_ids", []))
        resources.update(capabilities.intersection(catalog["resource_providers"]))
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-xl"):
            ui.label("确认结束执行？").classes("text-lg")
            for plugin_id in sorted({resource.split(".")[0] for resource in resources}):
                manifest = catalog["manifests"].get(plugin_id, {})
                descriptions = manifest.get("resource_descriptions", {})
                names = [descriptions.get(resource, resource) for resource in sorted(resources) if resource.startswith(plugin_id + ".")]
                ui.label("使用了 " + plugin_id + " 插件，结束时将关闭或释放其已创建的资源：" + "、".join(names) + "。")
            if not resources:
                ui.label("没有声明插件运行资源，结束时将释放执行器占用。")
            ui.label("已保存的结果和历史保留。结束后如需继续，请从头重新执行或新建执行。")
            with ui.row():
                ui.button("确认结束", on_click=lambda: dialog.submit(True))
                ui.button("取消", on_click=lambda: dialog.submit(False)).props("outline")
        return await dialog

    async def refresh_execution_rows(self):
        return await self.execution_details.render_rows()

    async def choose_run_step(self, run, step):
        current = await self.controller.call('run.get', run_id=run['run_id'])
        succeeded = any(a['step_id'] == step['step_id'] and a['valid'] and a['status'] == 'SUCCEEDED' for a in current['attempts'])
        with ui.dialog() as dialog, ui.card().classes('w-full max-w-xl'):
            ui.label('执行到：' + step['name']).classes('text-lg')
            start = None
            if succeeded:
                definition = json.loads(current['definition_json'])['steps']
                index = next(i for i, st in enumerate(definition) if st['step_id'] == step['step_id'])
                start = ui.select({st['step_id']: f"{i+1}. {st['name']}" for i, st in enumerate(definition[:index+1])}, value=step['step_id'], label='开始步骤').classes('w-full')
                ui.label('开始步骤及后续结果将清空，前面的结果保留。')
            with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                if succeeded:
                    ui.button('从所选步骤重新执行到此步', on_click=lambda: dialog.submit('partial'))
                else:
                    ui.button('从前面未执行的步骤继续到此步', on_click=lambda: dialog.submit('continue'))
                ui.button('清理本次结果，从头执行到此步', on_click=lambda: dialog.submit('restart')).props('outline')
                ui.button('取消', on_click=lambda: dialog.submit(None)).props('flat')
        choice = await dialog
        if choice is None:
            return
        self.run_id = run['run_id']
        if choice in {'restart', 'partial'}:
            await self.controller.call('run.restart', run_id=self.run_id, command_id=command_id(), target_step_id=step['step_id'], start_step_id=start.value if choice == 'partial' else None)
        else:
            failed = next((a for a in current['attempts'] if a['valid'] and a['status'] == 'FAILED'), None)
            await self.controller.call('run.start', run_id=self.run_id, command_id=command_id(), mode='UNTIL', target_step_id=step['step_id'], retry_step_id=failed['step_id'] if failed else None)
        self.run_signature = self.execution_signature = None
        await self.refresh_run()

    async def step_error_dialog(self, attempt, step):
        with ui.dialog() as dialog, ui.card().classes('w-full max-w-2xl'):
            ui.label(step['name'] + ' · 执行错误').classes('text-lg font-medium')
            ui.label((attempt.get('error_code') or 'UNKNOWN') + '：' + (attempt.get('error_summary') or '无错误说明')).classes('text-red-700 whitespace-pre-wrap')
            with ui.row().classes('gap-2'):
                async def go_debug():
                    dialog.close()
                    await self.navigate_step_debug(step['task_id'], step['step_id'])
                self.button('前往该步骤调试', go_debug, primary=True)
                ui.button('关闭', on_click=dialog.close).props('outline')
        dialog.open()

    async def refresh_run(self):
        return await self.execution_details.refresh()

    async def reconcile_dialog(self, attempt):
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-2xl"):
            ui.label("先在业务系统查询，再记录核对结果。")
            decision = ui.select(
                {"completed": "确认已完成", "not_completed": "确认未完成"},
                label="业务结果",
                value=None,
            )
            evidence = ui.textarea("说明（可选）").classes("w-full")

            async def submit():
                if decision.value not in {'completed', 'not_completed'}:
                    raise TaskError('RECONCILIATION_INVALID', '请选择业务结果')
                await self.controller.call(
                    "run.reconcile",
                    attempt_id=attempt["attempt_id"],
                    decision=decision.value,
                    evidence={"manual_query": evidence.value.strip()} if (evidence.value or "").strip() else {},
                    command_id=command_id(),
                )
                dialog.close()
                await self.refresh_run()

            self.button("保存核对结果", submit, primary=True)
        dialog.open()

    async def step_result_dialog(self, run, step, attempt_id=None):
        return await self.result_viewer.step_result_dialog(run, step, attempt_id)

    async def render_result_view(self, kind, payload, stored):
        return await self.result_viewer.render_result_view(kind, payload, stored)

    async def plugins(self):
        return await self.plugins_page.render()

    async def history(self):
        return await self.render_task_history(self.task_id, "TRIAL")

    async def render_task_history(self, task_id, mode):
        page = HistoryPage(
            self.controller, task_id, self.button, self.step_result_dialog, self.step_error_dialog,
            identity=lambda: (self.task_id, self.page_generation, self.step_state.generation),
        )
        return await page.render(mode=mode)

    async def environment(self):
        """Compatibility entry point; environment UI is owned by EnvironmentPage."""
        return await self.environment_page.render()

    async def _on_environment_default_selected(self, environment_id):
        self.environment_id = environment_id

    async def _on_environment_deleted(self, environment_id):
        if self.environment_id == environment_id:
            self.environment_id = None

    async def settings(self):
        return await self.settings_page.render()
    async def result_dialog(self, result_id):
        return await self.result_viewer.result_dialog(result_id)
