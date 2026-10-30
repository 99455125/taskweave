"""Step document composition and serialized draft persistence."""

import json
import io
import tokenize
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Protocol
from taskweave.desktop.state import StepEditorState
from taskweave.presentation.state import ContextPageState

from nicegui import ui

from taskweave.core.validation import TaskError, normalize_step
from taskweave.desktop.contexts import context_ai_items
from taskweave.desktop.forms import StepSchemaEditor, ValueForm

EMPTY = "async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n"

def insert_action_source(source, invocation, position):
    """Insert a complete call before the logical statement containing the cursor."""
    if type(position) is not int or not 0 <= position <= len(source):
        raise TaskError('FORM_INVALID', '光标位置不可用，请在步骤代码中重新定位。')
    cursor_line = source.count('\n', 0, position) + 1
    statement_line = cursor_line
    logical_start = None
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type in {tokenize.INDENT, tokenize.DEDENT, tokenize.NL, tokenize.COMMENT, tokenize.ENDMARKER}:
                continue
            if logical_start is None:
                logical_start = token.start[0]
            if token.type == tokenize.NEWLINE:
                if logical_start <= cursor_line <= token.end[0]:
                    statement_line = logical_start
                    break
                logical_start = None
    except (tokenize.TokenError, IndentationError) as error:
        raise TaskError('FORM_INVALID', '步骤代码存在未完成的语句，请补全后再插入动作。') from error
    start = sum(len(line) for line in source.splitlines(keepends=True)[:statement_line - 1])
    end = source.find('\n', start)
    line = source[start:end if end >= 0 else len(source)]
    indent = line[:len(line) - len(line.lstrip(' \t'))]
    if not indent and line.strip():
        raise TaskError('FORM_INVALID', '请将光标放在 run 函数内需要插入动作的行。')
    if not source[:start].strip():
        raise TaskError('FORM_INVALID', '请将光标放在 run 函数内需要插入动作的行。')
    indent = indent or '    '
    return source[:start] + indent + invocation + '\n' + source[start:]

def document_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)

from taskweave.core.validation import TaskError, normalize_step
from taskweave.presentation.result_fields import result_fields


class EditorApplicationPort(Protocol):
    async def call(self, operation: str, **params) -> dict | list[dict]: ...
    async def validate_step_candidate(self, document: dict) -> list[dict]: ...
    async def previous_result(self, task_id: str, step_id: str, environment_id: str | None, *, output: str = 'data') -> object: ...


class EditorButtonFactory(Protocol):
    def __call__(self, title: str, action: Callable[[], object], *, primary: bool = False, flat: bool = False) -> ui.button: ...


class StepListRenderer(Protocol):
    actions: dict
    async def render(self, steps: list[dict], catalog: dict, toolbar: ui.element, container: ui.element, *, show_list: bool = True) -> ui.element | None: ...
    def bind_move_menu_items(self, up: ui.element, down: ui.element) -> None: ...


class AuthoringEditorActions(Protocol):
    async def generate_goal_dialog(self) -> None: ...
    def retained_request(self) -> object | None: ...
    async def recover_generation(self, *, repaint: Callable[[], Awaitable[None]]) -> None: ...
    async def choose_generation_mode(self, *, repaint: Callable[[], Awaitable[None]]) -> None: ...
    async def generate_from_form(self, channel: str, supplement: str, *, repaint: Callable[[], Awaitable[None]]) -> None: ...
    async def confirm_step(self, repaint: Callable[[], Awaitable[None]]) -> None: ...


class DebugDrawerRenderer(Protocol):
    @property
    def environment_id(self) -> str | None: ...
    def set_visible(self, visible: bool) -> None: ...
    async def refresh(self) -> None: ...
    async def render(self, host: ui.element, step: dict, baseline: dict, *, current: Callable[[], bool],
                     toolbar_host: ui.element, logs_host: ui.element) -> bool: ...


class ContextMaterialsRenderer(Protocol):
    def render(self, container: ui.element) -> None: ...


@dataclass
class StepEditorRenderContext:
    """Explicit editor-only services and view handles used during composition."""
    state: StepEditorState
    context_state: ContextPageState
    debug_drawer: DebugDrawerRenderer
    controller: EditorApplicationPort
    button: EditorButtonFactory
    page_getter: Callable[[], str]
    page_generation_getter: Callable[[], int]
    step_list: StepListRenderer
    save_editor: Callable[[], Awaitable[dict]]
    document: Callable[[], dict]
    paint: Callable[[], Awaitable[None]]
    ai_editor: AuthoringEditorActions
    context_component: ContextMaterialsRenderer
    selected_step_control: ui.element | None = None
    save_state: ui.label | None = None
    context_panel: ui.element | None = None
    open_debug_on_navigation: bool = False

    @property
    def task_id(self): return self.state.task_id
    @task_id.setter
    def task_id(self, value): self.state.task_id = value
    @property
    def step_id(self): return self.state.step_id
    @step_id.setter
    def step_id(self, value): self.state.step_id = value
    @property
    def old_step(self): return self.state.old_step
    @old_step.setter
    def old_step(self, value): self.state.old_step = value
    @property
    def edit_controls(self): return self.state.edit_controls
    @edit_controls.setter
    def edit_controls(self, value): self.state.edit_controls = value
    @property
    def step_state(self): return self.state
    @property
    def page(self): return self.page_getter()
    @property
    def page_generation(self): return self.page_generation_getter()
    @property
    def context_entries(self): return self.context_state.entries
    @context_entries.setter
    def context_entries(self, value): self.context_state.entries = value
    @property
    def contexts(self): return self.context_state.ai_contexts
    @contexts.setter
    def contexts(self, value): self.context_state.ai_contexts = value
    @property
    def environment_id(self): return self.debug_drawer.environment_id


class StepEditor:
    def __init__(self, controller, state, page_generation, trial_variables=None):
        self.controller, self.state, self.page_generation = controller, state, page_generation
        self.trial_variables = trial_variables
        self.timers = []
        self.view = {}
        self.active_section = None
        self.ai_drafts = {}
        self.assistant_modes = {}
        self.flow_views = {}
        self.codegen_flows = {}

    def identity(self):
        return (self.state.task_id, self.state.step_id, self.state.generation, self.page_generation())

    def snapshot_draft(self):
        controls = self.state.edit_controls
        if not controls or not self.state.old_step:
            return None
        return deepcopy({
            'task_id': self.state.task_id, 'step_id': self.state.step_id,
            'baseline': self.state.old_step,
            'fields': {key: controls[key].value for key in (
                'name', 'step_description', 'step_notes', 'code', 'caps', 'delay', 'timeout')},
            'schema': controls['schema'].raw_rows(),
            'schema_original': controls['schema'].original,
            'schema_mode': controls['schema'].edit_mode.value,
            'schema_json': controls['schema'].json_editor.value,
            'output_schema': controls['output_schema'].raw_rows(),
            'output_schema_original': controls['output_schema'].original,
            'output_schema_mode': controls['output_schema'].edit_mode.value,
            'output_schema_json': controls['output_schema'].json_editor.value,
            'bindings': [[control.value for control in row] for row in controls['bindings']],
        })

    def snapshot_debug_inputs(self):
        form = self.view.get('trial_form')
        if form is None:
            return None
        return form.input_draft.snapshot(self.state.task_id, self.state.step_id)

    def _is_current(self, identity):
        return self.identity() == identity

    def update_step_validation(self, saved):
        tree = self.view.get('flow_tree')
        if tree is not None and not tree.canvas.is_deleted and saved['step_id'] in tree.steps:
            tree.set_validation(saved['step_id'], saved['validation_state'])

    async def mark_step_pending(self):
        """Reload the selected step and update editor-owned save/list controls."""
        identity = self.identity()
        if not identity[1]:
            return None
        step = await self.controller.call("step.get", step_id=identity[1])
        if not self._is_current(identity):
            return None
        self.state.old_step = step
        self.update_step_validation(step)
        save_state = self.view.get("save_state")
        if save_state and not save_state.is_deleted:
            save_state.text = "已保存 · 待确认"
        control = self.view.get("selected_step_control")
        if control is not None and not control.is_deleted:
            control.props(remove="icon-right")
            control.props("icon-right=radio_button_checked text-color=grey-7")
            control.style("background:#ecfeff;color:#134e4a;box-shadow:inset 4px 0 #0f766e")
        return step

    async def refresh_trial_inputs(self, step, preserve_values=True):
        """Refresh the editor-owned trial controls while preserving editable drafts."""
        identity = self.identity()
        variables_area = self.view.get("trial_variables_area")
        trial_form = self.view.get("trial_form")
        environment = self.view.get("trial_environment")
        if not variables_area or variables_area.is_deleted:
            return
        task_edits = step_edits = None
        if preserve_values and trial_form:
            try:
                task_edits = trial_form.task_edits()
                step_edits = trial_form.step_edits()
            except TaskError:
                task_edits = step_edits = None
        selected = environment.value or None
        if trial_form and hasattr(trial_form, "refresh"):
            await trial_form.refresh(step, selected, task_edits or {}, step_edits or {})
            return
        if self.trial_variables is None:
            raise RuntimeError("StepEditor trial_variables factory was not configured")
        if not self._is_current(identity):
            return
        variables_area.clear()
        with variables_area:
            refreshed = await self.trial_variables(step, environment, values=None)
        if self._is_current(identity):
            self.view["trial_form"] = refreshed

    def apply_trial_values(self, waiting, values, identity):
        """Apply resumed input values only to the editor instance that opened the request."""
        if not self._is_current(identity):
            return False
        trial_form = self.view.get("trial_form")
        if trial_form is None:
            return False
        if waiting.get("scope") == "task":
            trial_form.apply_task_values(values)
        elif waiting.get("step_id") == self.state.step_id:
            trial_form.apply_step_values(values)
        else:
            return False
        return True

    def capture_view(self, ctx):
        self.view.update({name: getattr(ctx, name) for name in (
            "selected_step_control", "save_state", "context_panel",
        )})

    def own_timer(self, timer):
        self.timers.append(timer)
        return timer

    def update_dirty_indicator(self, ctx, is_current):
        """Reflect unsaved form edits against the persisted editor baseline."""
        if not is_current() or not ctx.edit_controls:
            return
        try:
            changed = normalize_step(ctx.document()) != normalize_step(ctx.old_step)
        except (TaskError, ValueError, TypeError):
            changed = True
        if is_current():
            ctx.save_state.text = "未保存修改" if changed else "已保存"

    def dispose(self):
        tabs = self.view.get('workspace_tabs')
        if tabs is not None:
            self.active_section = (self.state.task_id, self.state.step_id, tabs.value)
        for timer in self.timers:
            if not getattr(timer, "is_deleted", True):
                timer.delete()
        self.timers.clear()
        self.view.clear()

    async def add_first_step(self, ctx):
        """Create the initial step through the same guarded editor flow everywhere."""
        task_id, page_generation, editor_generation = ctx.task_id, ctx.page_generation, ctx.step_state.generation

        def is_current():
            return (ctx.task_id == task_id and ctx.page_generation == page_generation
                    and ctx.step_state.generation == editor_generation and ctx.page == "editor")

        step = await ctx.controller.call(
            "step.save", task_id=task_id,
            document={"name": "第一个步骤", "step_content": EMPTY},
        )
        if not is_current():
            return False
        self.flow_views.get(ctx.task_id, {}).pop('selected', None)
        ctx.step_id = step["step_id"]
        await ctx.paint()
        return True

    async def reuse_step(self, ctx, parent_id, index, expected_flow):
        task_id, page_generation, editor_generation = ctx.task_id, ctx.page_generation, ctx.step_state.generation
        def is_current():
            return (ctx.task_id == task_id and ctx.page_generation == page_generation
                    and ctx.step_state.generation == editor_generation and ctx.page == 'editor')
        if ctx.step_id and ctx.edit_controls:
            await ctx.save_editor()
        if not is_current(): return
        from taskweave.desktop.components.step_reuse import show_step_reuse
        async def created(step):
            if is_current():
                self.flow_views.get(ctx.task_id, {}).pop('selected', None)
                ctx.step_id = step['step_id']
                await ctx.paint()
        try:
            await show_step_reuse(ctx.controller, task_id=task_id, parent_id=parent_id, index=index, expected_flow=expected_flow,
                                  is_current=is_current, on_created=created)
        except TaskError as exc:
            if is_current(): ui.notify(str(exc), type='negative')

    async def render(self, ctx):
        feedback_client = ui.context.client
        task_id, page_generation, editor_generation = ctx.task_id, ctx.page_generation, ctx.step_state.generation
        def route_is_current():
            return (ctx.task_id == task_id and ctx.page_generation == page_generation
                    and ctx.step_state.generation == editor_generation and ctx.page == "editor")
        steps = await ctx.controller.call("step.list", task_id=ctx.task_id)
        if not route_is_current():
            return
        if ctx.step_id not in {s["step_id"] for s in steps}:
            ctx.step_id = steps[0]["step_id"] if steps else None
        step = next((s for s in steps if s["step_id"] == ctx.step_id), None)
        draft = ctx.step_state.reload_draft
        if draft and (draft['task_id'], draft['step_id']) != (ctx.task_id, ctx.step_id):
            draft = None
        # Recovery retains the original saved version, including its hash.
        # A concurrent edit must still fail the usual optimistic-lock check.
        ctx.old_step = deepcopy(draft['baseline']) if draft else step
        fields = draft['fields'] if draft else {}
        editor_generation = ctx.step_state.generation
        editor_step_id = ctx.step_id
        def editor_is_current():
            return (route_is_current() and ctx.step_id == editor_step_id
                    and ctx.step_state.generation == editor_generation)
        context_entries = await ctx.controller.call("context.list", step_id=editor_step_id) if step else []
        if not editor_is_current():
            return
        ctx.context_entries = context_entries
        ctx.contexts = context_ai_items(context_entries)
        catalog = await ctx.controller.call("capabilities")
        if not editor_is_current():
            return
        flow_description = await ctx.controller.call("task.flow.describe", task_id=ctx.task_id)
        flow = flow_description["flow"]
        from taskweave.core.task_flow import is_linear_flow, validate_flow
        linear_flow = is_linear_flow(flow)
        if not editor_is_current():
            return
        control_nodes = {}
        def collect_controls(node):
            if node["kind"] in {"loop", "foreach", "if"}:
                control_nodes[node["id"]] = node["kind"]
            if node["kind"] == "sequence":
                for child in node["children"]:
                    collect_controls(child)
            elif node["kind"] == "if":
                from taskweave.core.task_flow import conditional_branches
                for _, body in conditional_branches(node):
                    collect_controls(body)
            elif node["kind"] in {"loop", "foreach"}:
                collect_controls(node["body"])
        collect_controls(flow["root"])
        from taskweave.presentation.flow_editor import (find_node, insert_control, move_node,
                                                        remove_control, update_control)
        from taskweave.desktop.components.branch_form import BranchForm, branch_sequence_targets
        from taskweave.desktop.components.flow_controls import ControlForm
        from taskweave.desktop.components.flow_tree import FlowTree

        async def save_flow_tree(updated, selected_action=None):
            if step:
                await ctx.save_editor()
            current = await ctx.controller.call('task.flow.describe', task_id=ctx.task_id)
            if not editor_is_current():
                return
            if current['flow'] != flow:
                raise TaskError('EDIT_CONFLICT', '流程已更新，请重新打开后编辑。')
            await ctx.controller.call("task.flow.save", task_id=ctx.task_id, flow=updated,
                                      expected_hash=current["definition_hash"])
            if editor_is_current():
                if selected_action:
                    flow_view.pop('selected', None)
                    ctx.step_list.select_step(selected_action)
                await ctx.paint()

        async def add_control(kind):
            if not await prepare_control_leave():
                return
            try:
                updated, identity = insert_control(flow, kind)
                flow_view['selected'] = identity
                await save_flow_tree(updated)
            except TaskError as exc:
                with feedback_client.layout:
                    ui.notify('插入失败：' + str(exc), type='negative')

        control_form = None
        control_baseline = None
        selected_control_id = None

        def control_is_dirty():
            if control_form is None:
                return False
            try:
                return control_form.value() != control_baseline
            except (TaskError, ValueError, TypeError):
                return True

        def refresh_control_status():
            if editor_is_current() and not control_status.is_deleted:
                control_status.set_text('未保存修改' if control_is_dirty() else '已保存')

        async def save_control():
            nonlocal flow, flow_description, control_baseline
            if control_form is None or not control_is_dirty():
                return
            changes = control_form.value()
            if isinstance(control_form, BranchForm):
                updated = deepcopy(flow)
                node, _ = find_node(updated, selected_control_id)
                node.clear()
                node.update(changes)
            else:
                updated = update_control(flow, selected_control_id, changes)
            validate_flow(updated, steps)
            await ctx.controller.call('task.flow.save', task_id=ctx.task_id, flow=updated,
                                      expected_hash=flow_description['definition_hash'])
            if not editor_is_current():
                return
            flow = updated
            flow_description = await ctx.controller.call('task.flow.describe', task_id=ctx.task_id)
            if not editor_is_current():
                return
            control_baseline = deepcopy(changes)
            control_nodes.clear()
            collect_controls(flow['root'])
            redraw_tree()
            tree.root.style(f'zoom:{zoom.value}')
            refresh_control_status()
            flow_status.set_text('流程已确认' if flow_description['confirmed'] else '流程待确认')

        async def prepare_control_leave():
            nonlocal control_form, control_baseline
            if not control_is_dirty():
                return True
            with ui.dialog() as dialog, ui.card().classes('tw-confirm-dialog'):
                ui.label('流程配置有未保存的更改').classes('tw-confirm-title')
                with ui.row().classes('tw-confirm-actions'):
                    ui.button('继续编辑', on_click=lambda: dialog.submit('stay')).props('outline')
                    ui.button('丢弃并切换', on_click=lambda: dialog.submit('discard')).props('outline color=negative').classes('tw-confirm-danger')
                    ui.button('保存并切换', on_click=lambda: dialog.submit('save')).props('unelevated')
            choice = await dialog
            if not editor_is_current() or choice not in {'save', 'discard'}:
                return False
            if choice == 'save':
                try:
                    await save_control()
                except (TaskError, ValueError, TypeError) as exc:
                    ui.notify(str(exc), type='negative')
                    return False
            else:
                control_body.clear()
                node, _ = find_node(flow, selected_control_id)
                with control_body:
                    control_form = (BranchForm if node['kind'] == 'if' else ControlForm)(node,
                        {item['step_id']: item['name'] for item in steps},
                        {key: ('循环 ' if kind in {'loop', 'foreach'} else '分支 ') + key
                         for key, kind in control_nodes.items()}, on_change=refresh_control_status)
                control_baseline = deepcopy(control_form.value())
                refresh_control_status()
            return True

        self.view['prepare_control_leave'] = prepare_control_leave

        async def select_action(step_id):
            nonlocal control_form
            if not await prepare_control_leave():
                return
            flow_view.pop('selected', None)
            if step_id == ctx.step_id:
                control_form = None
                control_panel.set_visibility(False)
                editor_panel.set_visibility(True)
                tree.select(step_id)
                flow_location.set_text(tree.node_paths.get(step_id, '主流程'))
                show_section(workspace_tabs.value)
                return
            await ctx.step_list.navigate_step(step_id)

        async def configure_control(node_id):
            nonlocal control_form, control_baseline, selected_control_id, flow_description
            if not await prepare_control_leave():
                return
            latest = await ctx.controller.call('task.flow.describe', task_id=ctx.task_id)
            if not editor_is_current():
                return
            if latest['flow'] != flow:
                raise TaskError('EDIT_CONFLICT', '流程已更新，请重新打开后编辑。')
            flow_description = latest
            selected_control_id = node_id
            flow_view['selected'] = node_id
            tree.select(node_id)
            flow_location.set_text(tree.node_paths.get(node_id, '主流程'))
            node, _ = find_node(flow, node_id)
            control_body.clear()
            with control_body:
                control_form = (BranchForm if node['kind'] == 'if' else ControlForm)(node,
                    {item['step_id']: item['name'] for item in steps},
                    {key: ('循环 ' if kind in {'loop', 'foreach'} else '分支 ') + key
                     for key, kind in control_nodes.items()}, on_change=refresh_control_status)
            control_baseline = deepcopy(control_form.value())
            control_title.set_text({'if': '条件分支', 'foreach': '列表遍历', 'loop': '条件循环'}[node['kind']])
            control_status.set_text('已保存')
            editor_panel.set_visibility(False)
            control_panel.set_visibility(True)
            if step:
                debug_column.set_visibility(False)
                debug_toolbar.set_visibility(False)
            ctx.debug_drawer.set_visible(False)
            editor_layout.classes(remove='tw-debug-open')

        async def move_flow_node(node_id):
            if not await prepare_control_leave():
                return
            targets = dict(branch_sequence_targets(flow, moving_node_id=node_id))
            moving = False
            with ui.dialog() as dialog, ui.card().classes('tw-confirm-dialog'):
                ui.label("移动到流程分组").classes("tw-confirm-title")
                ui.label('移动到目标分组末尾，保存前校验步骤依赖。').classes('text-sm text-gray-600')
                target = ui.select(targets, value="root", label="目标分组").classes("w-full")
                error = ui.label('').classes('text-negative whitespace-pre-wrap')
                error.set_visibility(False)
                progress = ui.label('正在保存，关闭窗口不会取消已提交的操作。').classes('text-sm text-gray-600')
                progress.set_visibility(False)
                async def apply_move():
                    nonlocal moving
                    if moving or not editor_is_current() or not dialog.value: return
                    moving = True
                    dialog.props('no-backdrop-dismiss')
                    progress.set_visibility(True)
                    for control in (target, cancel, confirm): control.disable()
                    try:
                        node, _ = find_node(flow, node_id)
                        if node['kind'] != 'action':
                            flow_view['selected'] = node_id
                        await save_flow_tree(move_node(flow, node_id, target.value), node.get('step_id'))
                        dialog.close()
                    except TaskError as exc:
                        error.set_text('无法移动：' + str(exc))
                        error.set_visibility(True)
                    finally:
                        moving = False
                        if not dialog.is_deleted: dialog.props(remove='no-backdrop-dismiss')
                        if not progress.is_deleted: progress.set_visibility(False)
                        for control in (target, cancel, confirm):
                            if not control.is_deleted: control.enable()
                with ui.row().classes('tw-confirm-actions'):
                    cancel = ui.button("取消", on_click=lambda: dialog.close() if not moving else None).props("outline")
                    confirm = ui.button("移动", on_click=apply_move)
            dialog.open()

        async def drop_flow_node(node_id, parent_id, index):
            if not editor_is_current() or not await prepare_control_leave():
                return
            try:
                node, parent = find_node(flow, node_id)
                if node is None or parent is None:
                    raise TaskError('FLOW_EDITOR_TARGET_INVALID')
                if parent['id'] == parent_id:
                    old_index = parent['children'].index(node)
                    if old_index < index:
                        index -= 1
                updated = move_node(flow, node_id, parent_id, index)
                if updated == flow:
                    return
                if node['kind'] != 'action':
                    flow_view['selected'] = node_id
                await save_flow_tree(updated, node.get('step_id'))
            except TaskError as exc:
                ui.notify('无法移动：步骤依赖、分支或循环作用域必须有效。' + str(exc), type='negative')

        async def insert_flow_node(parent_id, index):
            with feedback_client.layout:
                if not editor_is_current() or not await prepare_control_leave():
                    return
                with ui.dialog() as dialog, ui.card().classes('tw-confirm-dialog'):
                    ui.label('在此插入节点').classes('tw-confirm-title')
                    for kind, label in [('action', '步骤'), ('reuse', '从已有步骤复制'), ('if', '条件分支'), ('foreach', '列表遍历'), ('loop', '条件循环')]:
                        ui.button(label, on_click=lambda _, k=kind: dialog.submit(k)).props('flat')
                    ui.button('取消', on_click=lambda: dialog.submit(None)).props('outline')
                kind = await dialog
                if not kind or not editor_is_current():
                    return
                try:
                    if kind == 'reuse':
                        await self.reuse_step(ctx, parent_id, index, flow)
                        return
                    if kind != 'action':
                        updated, identity = insert_control(flow, kind, parent_id, index)
                        flow_view['selected'] = identity
                        await save_flow_tree(updated)
                        return
                    if step:
                        await ctx.save_editor()
                    current = await ctx.controller.call('task.flow.describe', task_id=ctx.task_id)
                    if not editor_is_current(): return
                    if current['flow'] != flow:
                        raise TaskError('EDIT_CONFLICT')
                    saved = await ctx.controller.call('step.insert', task_id=ctx.task_id,
                        document={'name': '新步骤', 'capabilities': step['capabilities'] if step else []},
                        parent_id=parent_id, index=index, expected_hash=current['definition_hash'])
                    if editor_is_current():
                        flow_view.pop('selected', None)
                        ctx.step_list.select_step(saved['step_id'])
                        await ctx.paint()
                except TaskError as exc:
                    ui.notify('插入失败：' + str(exc), type='negative')

        async def delete_flow_step(step_id):
            if not editor_is_current() or not await prepare_control_leave(): return
            with ui.dialog() as dialog, ui.card().classes('tw-confirm-dialog'):
                ui.label('删除步骤？已有运行记录或被引用的步骤会阻止删除。')
                with ui.row():
                    ui.button('取消', on_click=lambda: dialog.submit(False)).props('outline')
                    ui.button('删除', on_click=lambda: dialog.submit(True)).props('color=negative')
            if not await dialog or not editor_is_current(): return
            try:
                await ctx.save_editor()
                if not editor_is_current(): return
                await ctx.controller.call('step.delete', step_id=step_id)
                if editor_is_current():
                    if ctx.step_id == step_id:
                        remaining = [item['step_id'] for item in steps if item['step_id'] != step_id]
                        ctx.step_list.select_step(remaining[0] if remaining else None)
                    await ctx.paint()
            except TaskError as exc:
                ui.notify('删除失败：' + str(exc), type='negative')

        async def derive_flow_step(step_id, mode):
            if not editor_is_current() or not await prepare_control_leave(): return
            try:
                await ctx.save_editor()
                saved = await ctx.controller.call('step.get', step_id=step_id)
                if not editor_is_current(): return
                from taskweave.desktop.components.step_derivation import show_step_derivation
                async def created(new_step):
                    if editor_is_current():
                        flow_view.pop('selected', None)
                        ctx.step_list.select_step(new_step['step_id'])
                        await ctx.paint()
                await show_step_derivation(ctx.controller, saved, mode=mode,
                                           is_current=editor_is_current, on_created=created)
            except TaskError as exc:
                ui.notify('操作失败：' + str(exc), type='negative')

        async def delete_control(node_id):
            if not await prepare_control_leave():
                return
            try:
                await save_flow_tree(remove_control(flow, node_id))
            except TaskError as exc:
                with feedback_client.layout:
                    ui.notify('删除失败：' + str(exc), type='negative')

        async def confirm_flow():
            if not await prepare_control_leave():
                return
            await ctx.save_editor()
            current = await ctx.controller.call("task.flow.describe", task_id=ctx.task_id)
            await ctx.controller.call("task.flow.confirm", task_id=ctx.task_id,
                                      expected_hash=current["definition_hash"])
            if editor_is_current():
                await ctx.paint()
        ctx.selected_step_control = None
        with ui.row().classes("tw-editor-layout w-full items-start flex-wrap lg:flex-nowrap") as editor_layout:
            with ui.column().classes("tw-panel tw-flow-panel w-full"):
                with ui.row().classes("tw-step-list-heading w-full items-center gap-2"):
                    ui.icon('account_tree').classes('text-blue-500')
                    ui.label("任务流程").classes("font-semibold")
                    flow_count = ui.label().classes("tw-step-count")
                    ui.space()
                    toolbar = ui.row().classes("tw-flow-toolbar items-center gap-2 flex-wrap")
                ui.label('在节点“更多”中选择前后插入；拖动时显示落点，放下后校验依赖并自动排版。').classes('text-xs text-gray-600 w-full')
                tree_host = ui.column().classes('w-full gap-0')
                tree = None
                flow_view = self.flow_views.setdefault(ctx.task_id, {'expanded': True, 'zoom': 1.0})
                def redraw_tree():
                    nonlocal tree
                    visible = tree.canvas.visible if tree else flow_view['expanded']
                    tree_host.clear()
                    with tree_host:
                        tree = FlowTree(steps, ctx.step_id, select_action,
                                        configure_control, move_flow_node, delete_control,
                                        on_insert=insert_flow_node, on_drop=drop_flow_node, on_delete_step=delete_flow_step,
                                        on_derive=derive_flow_step)
                        tree.render(flow)
                        if selected_control_id:
                            tree.select(selected_control_id)
                        tree.canvas.set_visibility(visible)
                        tree.root.style(f"zoom:{flow_view['zoom']}")
                    ctx.selected_step_control = tree.selected_control
                    self.view['selected_step_control'] = tree.selected_control
                    self.view['flow_tree'] = tree
                    flow_count.text = f"{len(steps)} 个步骤 · {len(control_nodes)} 个控制节点"
                redraw_tree()
                flow_location = ui.label(tree.node_paths.get(ctx.step_id, '主流程')).classes('tw-flow-location text-xs text-gray-500')
                tools_area = ui.column().classes('hidden')
                await ctx.step_list.render(steps, catalog, toolbar, tools_area, show_list=False)
                with toolbar:
                    with ui.button('添加节点', icon='add').props('flat no-caps'):
                        with ui.menu():
                            async def add_at_end():
                                if not await prepare_control_leave(): return
                                flow_view.pop('selected', None)
                                if step:
                                    await ctx.step_list.actions['add']()
                                else:
                                    await self.add_first_step(ctx)
                            ui.menu_item('步骤', add_at_end)
                            async def reuse_at_end():
                                if await prepare_control_leave():
                                    await self.reuse_step(ctx, 'root', len(flow['root']['children']), flow)
                            ui.menu_item('从已有步骤复制', reuse_at_end)
                            ui.separator()
                            ui.menu_item("条件分支", lambda: add_control("if"))
                            ui.menu_item("列表遍历", lambda: add_control("foreach"))
                            ui.menu_item("条件循环", lambda: add_control("loop"))
                    def set_zoom(event):
                        flow_view['zoom'] = event.value
                        tree.root.style(f'zoom:{event.value}')
                    def toggle_canvas():
                        flow_view['expanded'] = not tree.canvas.visible
                        tree.canvas.set_visibility(flow_view['expanded'])
                    zoom = ui.select({0.75: '75%', 1.0: '100%', 1.25: '125%'}, value=flow_view['zoom'],
                              on_change=set_zoom).props(
                                  'borderless dense aria-label=流程缩放').classes('tw-flow-zoom')
                    ui.button(icon='unfold_less', on_click=toggle_canvas).props('flat round dense aria-label=展开或收起流程')
                with ui.row().classes('tw-flow-footer w-full items-center justify-between'):
                    flow_status = ui.label("流程已确认" if flow_description["confirmed"] else "流程待确认").classes("text-xs text-gray-500")
                    ctx.button("确认流程", confirm_flow, flat=True)
                if not editor_is_current():
                    return
                ctx.selected_step_control = tree.selected_control
            with ui.column().classes('tw-panel tw-control-panel w-full') as control_panel:
                with ui.row().classes('w-full items-center gap-3'):
                    control_title = ui.label('流程配置').classes('text-lg font-semibold grow')
                    control_status = ui.label('已保存').classes('text-xs text-gray-500')
                    ctx.button('保存配置', save_control, primary=True)
                    if step:
                        ctx.button('返回步骤', lambda: select_action(ctx.step_id), flat=True)
                control_body = ui.column().classes('tw-control-body w-full gap-3')
            control_panel.set_visibility(False)
            selected = flow_view.get('selected')
            if not step:
                ctx.old_step = None
                ctx.edit_controls = {}
                editor_panel = ui.column().classes('tw-panel w-full')
                with editor_panel:
                    ui.label('暂无步骤，请通过添加节点开始编排。').classes('text-gray-500')
                if selected in control_nodes:
                    await configure_control(selected)
                return
            with ui.column().classes("tw-panel tw-editor-panel tw-content w-full relative overflow-hidden")as editor_panel:
                candidate_open = None
                def show_section(section):
                    self.active_section = (ctx.task_id, ctx.step_id, section)
                    for key, panel in sections.items():
                        panel.set_visibility(key == section or (key == 'code' and section == 'debug'))
                    code_options.set_visibility(section == 'code')
                    refresh_assistant()
                    code_section.classes(add='tw-code-debug' if section == 'debug' else '',
                                         remove='' if section == 'debug' else 'tw-code-debug')
                    debug_column.set_visibility(section == 'debug' and not candidate_open)
                    code_editor_area.set_visibility(candidate_open != 'review')
                    candidate_main.set_visibility(candidate_open == 'review')
                    candidate_side.set_visibility(candidate_open == 'review')
                    chat_side.set_visibility(candidate_open == 'chat')
                    code_section.classes(add='tw-candidate-open' if candidate_open else '',
                                         remove='' if candidate_open else 'tw-candidate-open')
                    debug_toolbar.set_visibility(section == 'debug')
                    debug_logs.set_visibility(section == 'debug')
                    ctx.debug_drawer.set_visible(section == 'debug')
                    editor_layout.classes(add='tw-debug-open' if section == 'debug' else '',
                                          remove='' if section == 'debug' else 'tw-debug-open')
                    if workspace_tabs.value != section:
                        workspace_tabs.set_value(section)

                def set_debug_layout(opening):
                    show_section('debug' if opening else 'basic')

                async def change_section(event):
                    if not editor_is_current():
                        return
                    section = event.value
                    if section == 'debug':
                        await build_debug()
                        if not editor_is_current():
                            return
                    show_section(section)
                    if section == 'debug':
                        await ctx.debug_drawer.refresh()

                debug_built = False
                debug_building = False

                async def toggle_debug_drawer():
                    nonlocal debug_building
                    if debug_building:
                        return
                    opening = not debug_column.visible
                    if opening:
                        debug_building = True
                        debug_toggle.disable()
                        try:
                            await build_debug()
                            if not editor_is_current(): return
                        finally:
                            debug_building = False
                            if not debug_toggle.is_deleted: debug_toggle.enable()
                    if not editor_is_current(): return
                    set_debug_layout(opening)
                    if opening:
                        await ctx.debug_drawer.refresh()

                def mark_dirty(_=None):
                    if editor_is_current() and ctx.edit_controls and ctx.save_state and not ctx.save_state.is_deleted:
                        self.sync_draft()
                        ctx.save_state.text = '未保存修改'

                assistant_key = (ctx.task_id, ctx.step_id)
                local_codegen = None

                def refresh_assistant():
                    mode = self.assistant_modes.get(assistant_key, 'ai')
                    visible = self.active_section[2] == 'code' and mode is not None and not candidate_open
                    code_tools.set_visibility(visible)
                    action_panel.set_visibility(mode == 'actions')
                    code_assistant.set_visibility(mode == 'ai')
                    local_panel.set_visibility(mode == 'codegen')
                    if local_codegen is not None and mode != 'codegen':
                        local_codegen.hide_preview()
                    code_section.classes(add='' if visible else 'tw-assistant-closed',
                                         remove='tw-assistant-closed' if visible else '')

                def choose_assistant(mode):
                    self.assistant_modes[assistant_key] = mode
                    refresh_assistant()

                with ui.row().classes("tw-step-config-heading w-full items-center gap-2"):
                    with ui.row().classes('tw-step-identity items-center gap-3 grow min-w-0'):
                        ui.label(f"{step.get('position', 0) + 1:02d}").classes('tw-step-number')
                        with ui.column().classes('gap-0 min-w-0'):
                            step_title = ui.label(step['name']).classes("tw-step-config-title text-lg font-semibold")
                            ui.label(tree.step_paths.get(ctx.step_id, '主流程')).classes('tw-step-path text-xs text-gray-500')
                    ui.button('AI 编写', icon='auto_awesome', on_click=lambda: (
                        show_section('code'), choose_assistant('ai'))).props('flat dense')
                    ctx.button("保存步骤", ctx.save_editor, primary=True)
                    ctx.button("确认验证", lambda: ctx.ai_editor.confirm_step(ctx.paint), flat=True)
                    with ui.button("更多", icon="more_horiz").props("flat"):
                        with ui.menu():
                            actions_menu = ctx.step_list.actions
                            move_up_item = ui.menu_item("上移", actions_menu["move_up"]).set_enabled(linear_flow and actions_menu["can_move_up"])
                            move_down_item = ui.menu_item("下移", actions_menu["move_down"]).set_enabled(linear_flow and actions_menu["can_move_down"])
                            ctx.step_list.bind_move_menu_items(move_up_item, move_down_item)
                            ui.menu_item("复制步骤", lambda: derive_flow_step(ctx.step_id, "copy"))
                            ui.menu_item("拆分步骤", lambda: derive_flow_step(ctx.step_id, "split"))
                            ui.menu_item("删除步骤", actions_menu["delete"])
                            ui.menu_item("确认全部步骤", actions_menu["confirm_all"])
                    debug_toggle = ui.button("调试", icon="bug_report", on_click=toggle_debug_drawer).props(
                        "flat dense aria-label=展开调试 title=展开调试"
                    ).classes("tw-debug-toggle")
                initial_section = (self.active_section[2] if self.active_section
                    and self.active_section[:2] == (ctx.task_id, ctx.step_id) else 'basic')
                with ui.tabs(value=initial_section, on_change=change_section).classes('tw-step-workspace-tabs w-full') as workspace_tabs:
                    for key, title in [('basic', '基础配置'), ('code', '步骤代码'), ('inputs', '输入输出'),
                                       ('contexts', '上下文'), ('debug', '调试')]:
                        ui.tab(key, label=title)
                self.view['workspace_tabs'] = workspace_tabs
                debug_toolbar = ui.column().classes('tw-debug-session-toolbar w-full min-w-0 gap-3')
                debug_toolbar.set_visibility(False)
                editor_body = ui.column().classes("tw-editor-body h-full overflow-y-auto")
                with editor_body, ui.column().classes("w-full gap-3"):
                    with ui.row().classes("w-full justify-end items-center gap-2"):
                        ctx.save_state = ui.label("未保存修改 · 已恢复草稿" if draft else "已保存").classes("tw-save-state text-sm text-gray-500")
                    if draft and draft['baseline']['content_hash'] != step['content_hash']:
                        ui.label('已保存的步骤版本发生变化；恢复草稿未覆盖新版本，保存时仍会检查冲突。').classes('text-sm text-amber-700')
                    sections = {}
                    basic_section = ui.column().classes('tw-step-basic w-full gap-4')
                    sections['basic'] = basic_section
                    code_section = ui.column().classes('tw-step-code w-full gap-3')
                    sections['code'] = code_section
                    inputs_section = ui.column().classes('tw-step-inputs w-full gap-3')
                    sections['inputs'] = inputs_section
                    contexts_section = ui.column().classes('tw-step-contexts w-full gap-3')
                    sections['contexts'] = contexts_section
                    with code_section:
                        code_options = ui.row().classes('tw-code-options tw-code-toolbar w-full items-center gap-3')
                        code_tools = ui.column().classes('tw-code-tools w-full gap-3')
                    with code_tools:
                        with ui.row().classes('w-full items-center justify-between'):
                            ui.label('编写辅助').classes('text-sm font-semibold')
                            ui.button(icon='close', on_click=lambda: choose_assistant(None)).props(
                                'flat round dense aria-label=收起辅助区').tooltip('收起辅助区')
                        action_panel = ui.column().classes('tw-action-panel w-full gap-3')
                        local_panel = ui.column().classes('tw-local-codegen w-full gap-3')
                    with basic_section:
                        name = ui.input("步骤名称", value=fields.get('name', step["name"])).props("outlined dense").classes("w-full")
                        step_title.bind_text_from(name, 'value')
                        with ui.row().classes('w-full items-center justify-between gap-2'):
                            ui.label('步骤描述').classes('font-medium')
                            ctx.button('AI 生成步骤描述', ctx.ai_editor.generate_goal_dialog)
                        step_description = ui.textarea(
                            value=fields.get('step_description', step["step_description"]),
                            placeholder='描述本步骤的前置状态、操作、成功标准、输出和展示要求',
                        ).props('outlined autogrow').classes("w-full")
                        step_notes = ui.textarea(
                            '步骤说明',
                            value=fields.get('step_notes', step.get('step_notes', '')),
                            placeholder='长期提供给 AI 的特殊规则，例如：点击后异步刷新表格，应以结果出现作为成功标准。',
                        ).props('outlined autogrow').classes('w-full')
                    with code_options:
                        plugin_actions = {plugin: [] for plugin in catalog["versions"]}
                        for item in catalog["actions"]:
                            plugin = item["id"].split(".", 1)[0]
                            plugin_actions.setdefault(plugin, []).append(item["id"])
                        for capability in ([item['id'] for item in catalog['tools']] + catalog['result_handlers'] + catalog['resource_providers']):
                            plugin_actions.setdefault(capability.split('.',1)[0], []).append(capability)
                        selected_plugins = sorted({c.split(".", 1)[0] for c in step["capabilities"]})
                        if draft:
                            selected_plugins = fields['caps'] or []
                            for plugin in selected_plugins:
                                plugin_actions.setdefault(plugin, [])
                        for capability in step["capabilities"]:
                            plugin = capability.split(".", 1)[0]
                            if plugin not in catalog["versions"]:
                                plugin_actions.setdefault(plugin, []).append(capability)
                        options = {plugin: plugin + ("（当前不可用）" if plugin not in catalog["versions"] else "") for plugin in plugin_actions}
                        caps = (
                            ui.select(
                                options,
                                label="使用的插件",
                                multiple=True,
                                value=selected_plugins,
                            )
                            .props("borderless dense use-chips")
                            .classes("tw-code-plugins min-w-0 grow")
                        )
                        ui.button('插入动作', icon='add', on_click=lambda: choose_assistant('actions')).props('outline dense no-caps')
                        async def open_codegen():
                            choose_assistant('codegen')
                            await local_codegen.open()
                        codegen_button = ui.button('本地代码生成', icon='code', on_click=open_codegen).props('outline dense no-caps')
                        def codegen_visibility(_=None):
                            available = any(spec['id'].split('.', 1)[0] in (caps.value or [])
                                            for spec in catalog.get('code_generators', []))
                            codegen_button.set_visibility(available)
                            if not available and self.assistant_modes.get(assistant_key) == 'codegen':
                                choose_assistant('ai')
                        caps.on_value_change(codegen_visibility)
                        codegen_visibility()
                        ui.button('AI 编写', icon='auto_awesome', on_click=lambda: choose_assistant('ai')).props('flat dense no-caps')
                    with action_panel:
                        with ui.column().classes("tw-action-assistant w-full gap-3"):
                            ui.label('插入动作').classes('font-semibold')
                            actions = {a["id"]: a for a in catalog["actions"]}
                            def available_actions():
                                return [action_id for action_id in actions
                                        if action_id.split('.', 1)[0] in (caps.value or [])]
                            available = available_actions()
                            selection = ui.select(
                                available,
                                label="插件动作",
                                value=next(iter(available), None),
                            ).props("outlined dense").classes("w-full")
                            form_area = ui.column().classes("w-full gap-3")
                            active_form = [None]
                            ui.label('插入代码').classes('text-xs text-gray-500')
                            preview = ui.code('', language='python').classes('tw-action-preview w-full')
                            preview_error = ui.label().classes('text-xs text-red-700')

                            def refresh_action_preview(_=None):
                                if not selection.value or active_form[0] is None:
                                    preview.content = ''
                                    preview_error.text = ''
                                    return
                                try:
                                    values = active_form[0].values()
                                    preview.content = f"value = await ctx.call({selection.value!r}, {values!r})"
                                    preview_error.text = ''
                                except TaskError as exc:
                                    preview.content = ''
                                    preview_error.text = str(exc)

                            def action_form():
                                form_area.clear()
                                active_form[0] = None
                                with form_area:
                                    if selection.value:
                                        spec = actions[selection.value]
                                        ui.label(spec["description"]).classes("text-sm text-gray-500")
                                        with ui.element('div').classes('tw-action-parameters w-full'):
                                            active_form[0] = ValueForm(spec["input_schema"], compact=True)
                                            for name, field in active_form[0].fields.items():
                                                if spec["input_schema"].get("properties", {}).get(name, {}).get("type") in {"object", "array"}:
                                                    field.classes('tw-action-parameter-wide')
                                        for _, control in active_form[0].controls.values():
                                            control.on_value_change(refresh_action_preview)
                                refresh_action_preview()

                            selection.on_value_change(lambda _: action_form())
                            action_form()
                        with ui.row().classes("w-full justify-end"):
                            async def insert():
                                if not selection.value:
                                    raise TaskError("CAPABILITY_UNAVAILABLE")
                                action_id = selection.value
                                values = active_form[0].values()
                                invocation = f"value = await ctx.call({action_id!r}, {values!r})"
                                cursor = await ui.run_javascript(f'''return (() => {{
                                    const view = getElement({code.id})?.editor;
                                    if (!view) return null;
                                    const source = view.state.doc.toString();
                                    return {{source, position: Array.from(source.slice(0, view.state.selection.main.head)).length}};
                                }})()''')
                                if not editor_is_current(): return
                                if not cursor or cursor.get('source') != code.value:
                                    raise TaskError('EDIT_CONFLICT', '步骤代码正在变化，请重新定位后插入。')
                                if action_id not in available_actions():
                                    raise TaskError('EDIT_CONFLICT', '插件选择已变化，请重新选择动作后插入。')
                                code.value = insert_action_source(code.value, invocation, cursor['position'])
                                caps.value = sorted(
                                    set(caps.value or []) | {action_id.split(".", 1)[0]}
                                )

                            insert_button = ctx.button("插入到光标位置", insert, primary=True)
                            insert_button.bind_enabled_from(selection, 'value', bool)
                            def refresh_actions(_=None):
                                available = available_actions()
                                selection.set_options(available, value=selection.value if selection.value in available else next(iter(available), None))
                            caps.on_value_change(refresh_actions)
                    with inputs_section, ui.column().classes('tw-step-input-schema tw-panel w-full gap-3'):
                        ui.label('默认只要求对象，没有预设字段。字段默认值属于步骤输入层，可由显式输入或绑定覆盖。').classes('text-xs text-gray-500')
                        schema = StepSchemaEditor('输入 Schema',
                            draft.get('schema_original', ctx.old_step['input_schema']) if draft else ctx.old_step['input_schema'],
                            on_change=mark_dirty, on_mode_change=lambda: self.sync_draft() if editor_is_current() else None)
                        if draft:
                            schema.restore_editor(rows=draft['schema'], mode=draft.get('schema_mode'), json_text=draft.get('schema_json'))
                    with inputs_section, ui.expansion('输入来源绑定', value=True).classes('w-full'):
                        binding_area = ui.column().classes("w-full")
                        binding_rows = []
                        binding_refreshers = []
                        previous = {
                            s["step_id"]: s["name"]
                            for s in steps
                            if s["position"] < step["position"]
                        }

                        async def add_binding(key="", binding=None, raw=None):
                            binding = binding or {"literal": ""}
                            ref = binding.get("ref", {})
                            with binding_area:
                                with ui.column().classes(
                                    "tw-input-binding w-full"
                                ) as row:
                                    with ui.row().classes("tw-input-binding-row w-full"):
                                        key_input = ui.input("步骤输入名称", value=key)
                                        source = ui.select(
                                            {
                                                "literal": "固定值",
                                                "step": "前序结果",
                                                "task": "任务参数",
                                                "environment": "环境配置",
                                                "loop": "循环变量",
                                                "branch": "分支公共输出",
                                            },
                                            label="来源",
                                            value=ref.get("source", "literal"),
                                        )
                                        literal = ui.input(
                                            "固定值（文本或 JSON 值）",
                                            value=document_text(
                                                binding.get("literal", "")
                                            ),
                                        )
                                    with ui.row().classes("tw-input-binding-row w-full") as reference_fields:
                                        source_step = ui.select(
                                            {**previous, **{nid: ("循环 " if kind in {"loop", "foreach"} else "分支 ") + nid
                                                            for nid, kind in control_nodes.items()}},
                                            label="来源步骤或控制块",
                                            value=ref.get("step_id", ref.get("node_id")),
                                        ).classes("w-48")
                                        output = ui.input(
                                            "结果容器、循环变量或公共输出", value=ref.get("field", ref.get("output", "data"))
                                        )
                                        ref_pointer = ui.select(
                                            {ref.get("pointer", ""): ref.get("pointer", "") or "全部结果"},
                                            label="结果字段（可选择或填写 /字段名）",
                                            value=ref.get("pointer", ""), with_input=True, new_value_mode="add-unique",
                                        ).classes("min-w-64")
                                    with ui.row().classes("tw-input-binding-projection w-full") as projection_fields:
                                        item_pointer = ui.input("逐轮投影字段（可选）", value=ref.get("item_pointer", ""))
                                        loop_node_id = ui.select(
                                            {nid: nid for nid, kind in control_nodes.items() if kind in {"loop", "foreach"}},
                                            label="投影所属循环", value=ref.get("loop_node_id"),
                                        )
                                    preview = ui.label().classes("text-xs text-gray-500 tw-code w-full")
                                    record = (
                                        key_input,
                                        source,
                                        literal,
                                        source_step,
                                        output,
                                        ref_pointer,
                                        item_pointer,
                                        loop_node_id,
                                    )
                                    binding_rows.append(record)
                                    if raw is not None:
                                        # with_input selects must retain partially typed
                                        # pointers as well as known result fields.
                                        ref_pointer.options = {raw[5]: raw[5] or '全部结果'}
                                        for control, value in zip(record, raw):
                                            control.value = value
                                    for binding_control in record:
                                        binding_control.on_value_change(mark_dirty)
                                    mark_dirty()
                                    async def update_fields():
                                        choices = (previous if source.value == 'step' else
                                                   {nid: nid for nid, kind in control_nodes.items()
                                                    if kind in ({'loop', 'foreach'} if source.value == 'loop' else {'if'})})
                                        if source.value in {'step', 'loop', 'branch'}:
                                            source_step.options = choices
                                            if source_step.value not in choices:
                                                source_step.value = None
                                            source_step.update()
                                        reference_fields.set_visibility(source.value != 'literal')
                                        projection_fields.set_visibility(source.value == 'step')
                                        literal.set_visibility(source.value == 'literal')
                                        source_step.set_visibility(source.value in {'step', 'loop', 'branch'})
                                        output.set_visibility(source.value in {'step', 'loop', 'branch'})
                                        ref_pointer.set_visibility(source.value != 'literal')
                                        item_pointer.set_visibility(source.value == 'step')
                                        loop_node_id.set_visibility(source.value == 'step')
                                        preview.set_visibility(source.value == 'step')
                                        selection = (source.value, source_step.value, output.value, ctx.environment_id)
                                        fields = {}
                                        message = ''
                                        if source.value == 'environment':
                                            environments = await ctx.controller.call('environment.list')
                                            environment = next((row for row in environments
                                                if row['environment_id'] == selection[3]), None)
                                            fields = result_fields(json.loads(environment['public_config_json']) if environment else {})
                                        elif source.value == 'task':
                                            from taskweave.presentation.result_fields import schema_fields
                                            task = await ctx.controller.call('task.get', task_id=ctx.task_id)
                                            fields = schema_fields(json.loads(task['input_schema_json']))
                                        elif source.value == 'step' and source_step.value:
                                            from taskweave.presentation.result_fields import schema_fields
                                            declared = {}
                                            if (output.value or 'data') == 'data':
                                                producer = await ctx.controller.call('step.get', step_id=source_step.value)
                                                declared = schema_fields(producer['output_schema'])
                                            fields = declared.copy()
                                            try:
                                                result = await ctx.controller.previous_result(ctx.task_id, source_step.value, ctx.environment_id or None, output=output.value or 'data')
                                            except TaskError as exc:
                                                if exc.code != 'OUTPUT_NOT_AVAILABLE':
                                                    raise
                                                message = '字段来自前序步骤的输出 Schema，尚无成功运行示例；执行时读取本次运行结果。' if len(declared) > 1 else '尚无声明字段或成功结果；可以填写 /字段名。执行时读取本次运行结果。'
                                            else:
                                                fields = result_fields(result)
                                                for path, spec in declared.items():
                                                    if path not in fields:
                                                        fields[path] = spec
                                                    elif isinstance(spec['type'], str):
                                                        fields[path]['type'] = spec['type']
                                                message = '字段来自输出 Schema 与最近成功结果，示例值来自历史运行；执行时读取本次运行结果。'
                                        if not editor_is_current() or selection != (source.value, source_step.value, output.value, ctx.environment_id):
                                            return
                                        ref_pointer.field_types = {path: item['type'] for path, item in fields.items() if isinstance(item['type'], str)}
                                        options = {path: item['label'] for path, item in fields.items()}
                                        if ref_pointer.value not in options:
                                            options[ref_pointer.value] = ref_pointer.value or '全部结果'
                                        ref_pointer.options = options
                                        ref_pointer.update()
                                        self.sync_draft()
                                        preview.text = message

                                    async def choose_field(event):
                                        if source.value in {'step', 'environment', 'task'} and not key_input.value and event.value:
                                            key_input.value = event.value.rsplit('/', 1)[-1].replace('~1', '/').replace('~0', '~')
                                    source.on_value_change(lambda _: update_fields())
                                    source_step.on_value_change(lambda _: update_fields())
                                    output.on_value_change(lambda _: update_fields())
                                    ref_pointer.on_value_change(choose_field)
                                    binding_refreshers.append(update_fields)
                                    await update_fields()


                                    def remove():
                                        binding_rows.remove(record)
                                        binding_refreshers.remove(update_fields)
                                        row.delete()
                                        mark_dirty()

                                    ui.button("移除此绑定", on_click=remove).props(
                                        "flat"
                                    )

                        if draft:
                            for raw in draft['bindings']:
                                await add_binding(raw=raw)
                        else:
                            for key, binding in step["bindings"].items():
                                await add_binding(key, binding)
                        ui.button("添加绑定", on_click=lambda: add_binding()).props(
                            "outline"
                        )
                    with inputs_section, ui.column().classes('tw-step-output-schema tw-panel w-full gap-3'):
                        ui.label('默认 {} 不限制 data 结构；约束 ctx.result(data=...) 的业务数据，字段 default 不会自动补返回值。').classes('text-xs text-gray-500')
                        output_schema = StepSchemaEditor('输出 Schema',
                            draft.get('output_schema_original', ctx.old_step['output_schema']) if draft else ctx.old_step['output_schema'],
                            on_change=mark_dirty, on_mode_change=lambda: self.sync_draft() if editor_is_current() else None)
                        if draft and 'output_schema' in draft:
                            output_schema.restore_editor(rows=draft['output_schema'], mode=draft.get('output_schema_mode'),
                                                         json_text=draft.get('output_schema_json'))
                    with contexts_section:
                        ctx.context_panel = ui.column().classes("tw-step-context-materials w-full min-w-0")
                    ctx.context_component.render(ctx.context_panel)
                    with basic_section, ui.expansion("时间设置", value=False).classes("w-full"):
                        delay = ui.number(
                            "上一步成功后等待（秒）", value=fields.get('delay', step["delay_after_previous_seconds"]),
                            min=0, max=86400, step=1,
                        ).classes("w-full")
                        if step["position"] == 0:
                            delay.disable()
                        timeout = ui.number(
                            "步骤执行超时（秒，不包含间隔）", value=fields.get('timeout', step["timeout_ms"] / 1000),
                            min=0.001, max=3600, step=0.001,
                        ).classes("w-full")
                    with code_section, ui.column().classes('tw-code-main w-full gap-3'):
                        code_editor_area = ui.column().classes('w-full gap-3')
                        candidate_main = ui.column().classes('tw-candidate-main w-full gap-3')
                        debug_logs = ui.column().classes('tw-step-debug-logs w-full gap-3')
                    with code_editor_area:
                        ui.label("步骤代码").classes("text-base font-semibold")
                        code = ui.codemirror(fields.get('code', step["step_content"]), language="Python", line_wrapping=True).classes("w-full border rounded")
                        codegen_preview = ui.column().classes('tw-codegen-preview w-full gap-3')
                        codegen_preview.set_visibility(False)
                        with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                            async def lint():
                                diagnostics = await ctx.controller.validate_step_candidate(ctx.document())
                                if not editor_is_current():
                                    return
                                ui.notify("校验通过" if not diagnostics else document_text(diagnostics))
                            ctx.button("校验内容", lint)
                            ctx.button("确认验证", lambda: ctx.ai_editor.confirm_step(ctx.paint))
                    with code_tools, ui.column().classes('tw-code-assistant w-full gap-3') as code_assistant:
                        with ui.row().classes('items-center gap-2'):
                            ui.icon('auto_awesome').classes('text-primary')
                            ui.label('AI 编写').classes('text-base font-semibold')
                        ai_draft = self.ai_drafts.setdefault((ctx.task_id, ctx.step_id), {'channel': 'api', 'supplement': ''})
                        channel = ui.select({'api': 'API 调用', 'chat': '网页 Chat'},
                                            value=ai_draft['channel'], label='生成方式').props('outlined dense').classes('w-full')
                        supplement = ui.textarea('本轮编写要求', value=ai_draft['supplement'],
                                                 placeholder='描述本轮希望生成或调整的内容').props('outlined autogrow').classes('w-full')
                        channel.on_value_change(lambda event: ai_draft.update(channel=event.value))
                        supplement.on_value_change(lambda event: ai_draft.update(supplement=event.value or ''))
                        with ui.column().classes('tw-ai-basis w-full gap-2'):
                            ui.label('生成依据').classes('text-sm font-medium')
                            ui.label('当前步骤代码 · 步骤描述 · 步骤说明').classes('text-xs text-gray-500')
                            ui.label('所选插件与上下文材料').classes('text-xs text-gray-500')
                            ui.button('查看上下文', icon='folder_open', on_click=lambda: show_section('contexts')).props('flat dense')
                        ctx.button('AI 生成步骤代码', lambda: ctx.ai_editor.generate_from_form(
                            channel.value, supplement.value, repaint=ctx.paint), primary=True).classes('w-full')
                        ctx.button('查看上次 AI 结果', lambda: ctx.ai_editor.recover_generation(repaint=ctx.paint), flat=True).classes('w-full')
            with code_section:
                debug_column = ui.column().classes("tw-debug-column w-full min-w-0 gap-3")
                debug_column.set_visibility(False)
                candidate_side = ui.column().classes('tw-candidate-side w-full min-w-0 gap-3')
                chat_side = ui.column().classes('tw-candidate-side tw-chat-side w-full min-w-0 gap-3')

            def show_candidate():
                nonlocal candidate_open
                if not editor_is_current(): return
                candidate_open = 'review'
                section = self.active_section[2]
                show_section(section if section in ('code', 'debug') else 'code')

            def close_candidate():
                nonlocal candidate_open
                if not editor_is_current(): return
                candidate_open = None
                candidate_main.clear()
                candidate_side.clear()
                show_section(self.active_section[2])

            def show_chat():
                nonlocal candidate_open
                if not editor_is_current(): return
                candidate_open = 'chat'
                section = self.active_section[2]
                show_section(section if section in ('code', 'debug') else 'code')

            self.view['candidate_host'] = {'main': candidate_main, 'side': candidate_side,
                'chat': chat_side, 'show_chat': show_chat,
                'current': editor_is_current, 'show': show_candidate, 'close': close_candidate}
            from taskweave.presentation.codegen import LocalGenerationFlow
            from taskweave.desktop.components.step_codegen import StepCodeGenerator
            local_flow = self.codegen_flows.setdefault(assistant_key, LocalGenerationFlow(ctx.controller.call, self.identity))
            def codegen_document():
                self.sync_draft()
                return ctx.document()
            local_codegen = StepCodeGenerator(local_flow, ctx.controller, local_panel, codegen_preview, code,
                step_id=ctx.step_id, document=codegen_document, current=editor_is_current,
                changed=mark_dirty, show_contexts=lambda: show_section('contexts'))
            self.view['local_codegen'] = local_codegen

            async def build_debug():
                nonlocal debug_built
                if debug_built:
                    return
                debug_built = await ctx.debug_drawer.render(
                    debug_column, step, ctx.old_step, current=editor_is_current,
                    toolbar_host=debug_toolbar, logs_host=debug_logs,
                )
                if debug_built:
                    async def refresh_binding_fields(_=None):
                        for refresh in list(binding_refreshers):
                            await refresh()
                    self.view['trial_environment'].on_value_change(refresh_binding_fields)
                    await refresh_binding_fields()
                    self.capture_view(ctx)

            async def open_debug():
                await build_debug()
                if editor_is_current():
                    show_section('debug')
                    await ctx.debug_drawer.refresh()

            self.view['open_debug'] = open_debug

            show_section(initial_section if initial_section != 'debug' else 'code')
            ctx.edit_controls = {
                "name": name,
                "step_description": step_description,
                "step_notes": step_notes,
                "code": code,
                "caps": caps,
                "plugin_actions": plugin_actions,
                "schema": schema,
                "output_schema": output_schema,
                "delay": delay,
                "timeout": timeout,
                "bindings": binding_rows,
            }
            self.sync_draft()
            if selected in control_nodes:
                await configure_control(selected)
            local_codegen.render()
            for control in (name, step_description, step_notes, code, caps, delay, timeout):
                control.on_value_change(mark_dirty)
        if editor_is_current():
            ctx.step_state.reload_draft = None
            self.capture_view(ctx)
            if ctx.open_debug_on_navigation or initial_section == 'debug':
                await build_debug()
                if editor_is_current():
                    set_debug_layout(True)
                    await ctx.debug_drawer.refresh()


    def sync_draft(self):
        """Translate widget input into plain values at the framework boundary."""
        controls = self.state.edit_controls
        if not controls:
            return
        self.state.capture_draft({
            'fields': {key: controls[key].value for key in (
                'name', 'step_description', 'step_notes', 'code', 'caps', 'delay', 'timeout')},
            'schema': controls['schema'].raw_rows(),
            'schema_original': controls['schema'].original,
            'schema_mode': controls['schema'].edit_mode.value,
            'schema_json': controls['schema'].json_editor.value,
            'output_schema': controls['output_schema'].raw_rows(),
            'output_schema_original': controls['output_schema'].original,
            'output_schema_mode': controls['output_schema'].edit_mode.value,
            'output_schema_json': controls['output_schema'].json_editor.value,
            'bindings': [[control.value for control in row] for row in controls['bindings']],
            'field_types': {row[0].value.strip(): getattr(row[5], 'field_types', {})
                            for row in controls['bindings']},
            'plugin_actions': controls['plugin_actions'],
        })

    def document(self):
        from taskweave.presentation.editor import document_from_draft
        if self.state.draft is None:
            self.sync_draft()
        return document_from_draft(self.state.old_step, self.state.draft)

    async def save(self, document=None):
        from taskweave.presentation.editor import EditorSession
        document = self.document() if document is None else document
        return await EditorSession(getattr(self.state, "interaction", self.state), self.controller.save_draft, self.page_generation).save(document)
