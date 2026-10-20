"""Step document composition and serialized draft persistence."""

import json
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Protocol
from taskweave.desktop.state import StepEditorState
from taskweave.presentation.state import ContextPageState

from nicegui import ui

from taskweave.core.validation import TaskError, normalize_step
from taskweave.desktop.contexts import context_ai_items
from taskweave.desktop.forms import SchemaEditor, ValueForm

EMPTY = "async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n"

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
    async def render(self, steps: list[dict], catalog: dict, toolbar: ui.element, container: ui.element) -> ui.element | None: ...
    def bind_move_menu_items(self, up: ui.element, down: ui.element) -> None: ...


class AuthoringEditorActions(Protocol):
    async def generate_goal_dialog(self) -> None: ...
    def retained_request(self) -> object | None: ...
    async def recover_generation(self, *, repaint: Callable[[], Awaitable[None]]) -> None: ...
    async def choose_generation_mode(self, *, repaint: Callable[[], Awaitable[None]]) -> None: ...
    async def confirm_step(self, repaint: Callable[[], Awaitable[None]]) -> None: ...


class DebugDrawerRenderer(Protocol):
    @property
    def environment_id(self) -> str | None: ...
    def set_visible(self, visible: bool) -> None: ...
    async def refresh(self) -> None: ...
    async def render(self, host: ui.element, step: dict, baseline: dict, *, current: Callable[[], bool]) -> bool: ...


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
            'bindings': [[control.value for control in row] for row in controls['bindings']],
        })

    def snapshot_debug_inputs(self):
        form = self.view.get('trial_form')
        if form is None:
            return None
        return form.input_draft.snapshot(self.state.task_id, self.state.step_id)

    def _is_current(self, identity):
        return self.identity() == identity

    async def mark_step_pending(self):
        """Reload the selected step and update editor-owned save/list controls."""
        identity = self.identity()
        if not identity[1]:
            return None
        step = await self.controller.call("step.get", step_id=identity[1])
        if not self._is_current(identity):
            return None
        self.state.old_step = step
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
        ctx.step_id = step["step_id"]
        await ctx.paint()
        return True

    async def render(self, ctx):
        task_id, page_generation, editor_generation = ctx.task_id, ctx.page_generation, ctx.step_state.generation
        def route_is_current():
            return (ctx.task_id == task_id and ctx.page_generation == page_generation
                    and ctx.step_state.generation == editor_generation and ctx.page == "editor")
        steps = await ctx.controller.call("step.list", task_id=ctx.task_id)
        if not route_is_current():
            return
        if not steps:
            ui.label("暂无步骤").classes(
                "tw-panel"
            )
            ctx.button("添加步骤", lambda: self.add_first_step(ctx), primary=True)
            return
        if ctx.step_id not in {s["step_id"] for s in steps}:
            ctx.step_id = steps[0]["step_id"]
        step = next(s for s in steps if s["step_id"] == ctx.step_id)
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
        context_entries = await ctx.controller.call("context.list", step_id=editor_step_id)
        if not editor_is_current():
            return
        ctx.context_entries = context_entries
        ctx.contexts = context_ai_items(context_entries)
        catalog = await ctx.controller.call("capabilities")
        if not editor_is_current():
            return
        flow_description = await ctx.controller.call("task.flow.describe", task_id=ctx.task_id)
        flow = flow_description["flow"]
        from taskweave.core.task_flow import is_linear_flow
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
                collect_controls(node["then"])
                collect_controls(node["else"])
            elif node["kind"] in {"loop", "foreach"}:
                collect_controls(node["body"])
        collect_controls(flow["root"])
        from taskweave.presentation.flow_editor import (find_node, insert_control, move_node,
                                                        remove_control, sequence_targets, update_control)
        from taskweave.desktop.components.flow_controls import edit_control
        from taskweave.desktop.components.flow_tree import FlowTree

        async def save_flow_tree(updated):
            await ctx.save_editor()
            await ctx.controller.call("task.flow.save", task_id=ctx.task_id, flow=updated,
                                      expected_hash=flow_description["definition_hash"])
            if editor_is_current():
                await ctx.paint()

        async def add_control(kind):
            updated, _ = insert_control(flow, kind)
            await save_flow_tree(updated)

        async def configure_control(node_id):
            node, _ = find_node(flow, node_id)
            changes = await edit_control(node,
                                         {item["step_id"]: item["name"] for item in steps},
                                         {key: ("循环 " if kind in {"loop", "foreach"} else "分支 ") + key
                                          for key, kind in control_nodes.items()})
            if changes is not None and editor_is_current():
                await save_flow_tree(update_control(flow, node_id, changes))

        async def move_flow_node(node_id):
            targets = dict(sequence_targets(flow))
            with ui.dialog() as dialog, ui.card():
                ui.label("移动到流程分组").classes("text-lg font-semibold")
                target = ui.select(targets, value="root", label="目标分组").classes("w-64")
                with ui.row():
                    ui.button("取消", on_click=lambda: dialog.submit(None)).props("flat")
                    ui.button("移动", on_click=lambda: dialog.submit(target.value))
            dialog.open()
            selected = await dialog
            if selected and editor_is_current():
                await save_flow_tree(move_node(flow, node_id, selected))

        async def delete_control(node_id):
            await save_flow_tree(remove_control(flow, node_id))

        async def confirm_flow():
            await ctx.save_editor()
            current = await ctx.controller.call("task.flow.describe", task_id=ctx.task_id)
            await ctx.controller.call("task.flow.confirm", task_id=ctx.task_id,
                                      expected_hash=current["definition_hash"])
            if editor_is_current():
                await ctx.paint()
        ctx.selected_step_control = None
        with ui.row().classes("tw-editor-layout w-full items-start flex-wrap lg:flex-nowrap") as editor_layout:
            with ui.column().classes("tw-panel tw-step-sidebar w-full lg:w-56 shrink-0"):
                with ui.row().classes("tw-step-list-heading w-full items-center justify-between gap-2"):
                    ui.label("任务流程").classes("font-semibold")
                    ui.label(str(len(steps))).classes("tw-step-count")
                    toolbar = ui.row().classes("tw-step-list-toolbar items-center justify-end shrink-0")
                with ui.column().classes("w-full overflow-y-auto gap-2").style("max-height: calc(100vh - 330px)") as step_list_area:
                    FlowTree(steps, ctx.step_id, ctx.step_list.navigate_step,
                             configure_control, move_flow_node, delete_control).render(flow)
                with toolbar:
                    with ui.button(icon="add_circle_outline").props("flat round dense title=添加流程控制"):
                        with ui.menu():
                            ui.menu_item("条件分支", lambda: add_control("if"))
                            ui.menu_item("列表遍历", lambda: add_control("foreach"))
                            ui.menu_item("条件循环", lambda: add_control("loop"))
                ui.label("流程已确认" if flow_description["confirmed"] else "流程待确认").classes("text-xs text-gray-500")
                ctx.button("确认流程", confirm_flow, flat=True)
                with ui.expansion("步骤工具", value=False).classes("w-full"):
                    tools_toolbar = ui.row().classes("w-full justify-end")
                    tools_area = ui.column().classes("w-full gap-2")
                    selected_step_control = await ctx.step_list.render(steps, catalog, tools_toolbar, tools_area)
                if not editor_is_current():
                    return
                ctx.selected_step_control = selected_step_control
            with ui.column().classes("tw-panel tw-editor-panel tw-content w-full relative overflow-hidden").style('position: relative; min-height: calc(100vh - 260px)') as editor_panel:
                def set_debug_layout(opening):
                    debug_column.set_visibility(opening)
                    ctx.debug_drawer.set_visible(opening)
                    if opening:
                        editor_layout.classes(add="tw-debug-open")
                    else:
                        editor_layout.classes(remove="tw-debug-open")
                    debug_toggle.text = '收起调试' if opening else '调试'
                    debug_toggle.props('icon=expand_less aria-label=收起调试' if opening else 'icon=bug_report aria-label=展开调试')

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

                with ui.row().classes("tw-step-config-heading w-full items-center gap-2"):
                    ui.label("步骤配置").classes("tw-step-config-title text-lg font-semibold grow")
                    ctx.button("保存步骤", ctx.save_editor, primary=True)
                    ctx.button("确认验证", lambda: ctx.ai_editor.confirm_step(ctx.paint), flat=True)
                    with ui.button("更多", icon="more_horiz").props("flat"):
                        with ui.menu():
                            actions_menu = ctx.step_list.actions
                            move_up_item = ui.menu_item("上移", actions_menu["move_up"]).set_enabled(linear_flow and actions_menu["can_move_up"])
                            move_down_item = ui.menu_item("下移", actions_menu["move_down"]).set_enabled(linear_flow and actions_menu["can_move_down"])
                            ctx.step_list.bind_move_menu_items(move_up_item, move_down_item)
                            ui.menu_item("删除步骤", actions_menu["delete"])
                            ui.menu_item("确认全部步骤", actions_menu["confirm_all"])
                    debug_toggle = ui.button("调试", icon="bug_report", on_click=toggle_debug_drawer).props(
                        "flat dense aria-label=展开调试 title=展开调试"
                    ).classes("tw-debug-toggle")
                editor_body = ui.column().classes("tw-editor-body h-full overflow-y-auto")
                with editor_body, ui.column().classes("w-full gap-3"):
                    with ui.row().classes("w-full justify-end items-center gap-2"):
                        ctx.save_state = ui.label("未保存修改 · 已恢复草稿" if draft else "已保存").classes("tw-save-state text-sm text-gray-500")
                    if draft and draft['baseline']['content_hash'] != step['content_hash']:
                        ui.label('已保存的步骤版本发生变化；恢复草稿未覆盖新版本，保存时仍会检查冲突。').classes('text-sm text-amber-700')
                    name = ui.input("步骤名称", value=fields.get('name', step["name"])).props("outlined dense").classes("w-full")
                    with ui.row().classes('w-full items-center justify-between gap-2'):
                        ui.label('步骤描述').classes('font-medium')
                        ctx.button('AI 生成步骤描述', ctx.ai_editor.generate_goal_dialog)
                    step_description = ui.textarea(
                        value=fields.get('step_description', step["step_description"]),
                        placeholder='描述本步骤的前置状态、操作、成功标准、输出和展示要求',
                    ).props('outlined autogrow').classes("w-full")
                    step_notes = ui.textarea(
                        '步骤补充说明',
                        value=fields.get('step_notes', step.get('step_notes', '')),
                        placeholder='长期提供给 AI 的特殊规则，例如：点击后异步刷新表格，应以结果出现作为成功标准。',
                    ).props('outlined autogrow').classes('w-full')
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
                        .props("outlined dense use-chips")
                        .classes("w-full")
                    )
                    with ui.row().classes("w-full items-center justify-end gap-2 flex-wrap"):
                        if ctx.ai_editor.retained_request() is not None:
                            ctx.button("查看上次 AI 结果", lambda: ctx.ai_editor.recover_generation(repaint=ctx.paint))
                        ctx.button("AI 生成内容", lambda: ctx.ai_editor.choose_generation_mode(repaint=ctx.paint))
                    with ui.expansion("动作表单", value=False).classes("w-full") as action_form_expansion:
                        actions = {a["id"]: a for a in catalog["actions"]}
                        selection = ui.select(
                            list(actions),
                            label="插件动作",
                            value=next(iter(actions), None),
                        ).classes("w-full")
                        form_area = ui.column().classes("w-full")
                        active_form = [None]

                        def action_form():
                            form_area.clear()
                            with form_area:
                                if selection.value:
                                    spec = actions[selection.value]
                                    ui.label(spec["description"])
                                    active_form[0] = ValueForm(spec["input_schema"])

                        selection.on_value_change(lambda _: action_form())
                        action_form()
                    async def open_action_form():
                        action_form_expansion.set_value(True)
                        action_form_expansion.update()
                    with ui.row().classes("w-full justify-end"):
                        ctx.button("插入动作", open_action_form, icon="add").props("outline")

                        async def insert():
                            if not selection.value:
                                raise TaskError("CAPABILITY_UNAVAILABLE")
                            values = active_form[0].values()
                            invocation = f"    value = await ctx.call({selection.value!r}, {values!r})\n"
                            lines = code.value.splitlines(True)
                            return_index = next(
                                (
                                    i
                                    for i, line in enumerate(lines)
                                    if line.startswith("    return ")
                                ),
                                len(lines),
                            )
                            lines.insert(return_index, invocation)
                            code.value = "".join(lines)
                            if "return ctx.result(data=inputs)" in code.value:
                                code.value = code.value.replace(
                                    "return ctx.result(data=inputs)",
                                    "return ctx.result(data=value)",
                                )
                            caps.value = sorted(
                                set(caps.value or []) | {selection.value.split(".", 1)[0]}
                            )

                        ctx.button("插入到步骤内容", insert, primary=True)
                    with ui.expansion("变量与输入依赖", value=False).classes("w-full"):
                        schema = SchemaEditor(ctx.old_step["input_schema"], on_change=mark_dirty)
                        if draft:
                            schema.restore_rows(draft['schema'])
                        ui.label("选择输入来源即可；保存绑定时自动补充输入参数，无需先添加参数。")
                        binding_area = ui.column().classes("w-full")
                        binding_rows = []
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
                                    "border rounded p-3 w-full"
                                ) as row:
                                    with ui.row().classes("w-full"):
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
                                    with ui.row().classes("w-full"):
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
                                    with ui.row().classes("w-full"):
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
                                        literal.set_visibility(source.value == 'literal')
                                        source_step.set_visibility(source.value in {'step', 'loop', 'branch'})
                                        output.set_visibility(source.value in {'step', 'loop', 'branch'})
                                        ref_pointer.set_visibility(source.value != 'literal')
                                        item_pointer.set_visibility(source.value == 'step')
                                        loop_node_id.set_visibility(source.value == 'step')
                                        preview.set_visibility(source.value == 'step')
                                        if source.value != 'step' or not source_step.value:
                                            return
                                        try:
                                            result = await ctx.controller.previous_result(ctx.task_id, source_step.value, ctx.environment_id or None, output=output.value or 'data')
                                        except TaskError as exc:
                                            if not editor_is_current():
                                                return
                                            if exc.code != 'OUTPUT_NOT_AVAILABLE':
                                                raise
                                            preview.text = '尚无成功结果；可以填写 /字段名。运行时从本次任务 DB 读取。'
                                            return
                                        from taskweave.presentation.result_fields import result_fields
                                        if not editor_is_current():
                                            return
                                        fields = result_fields(result)
                                        ref_pointer.field_types = {path: item['type'] for path, item in fields.items()}
                                        options = {path: item['label'] for path, item in fields.items()}
                                        if ref_pointer.value not in options:
                                            options[ref_pointer.value] = ref_pointer.value or '全部结果'
                                        ref_pointer.options = options
                                        ref_pointer.update()
                                        self.sync_draft()
                                        preview.text = '字段与示例值来自最近成功运行；执行仍读取本次运行结果。'

                                    async def choose_field(event):
                                        if source.value == 'step' and not key_input.value and event.value:
                                            key_input.value = event.value.rsplit('/', 1)[-1].replace('~1', '/').replace('~0', '~')
                                    source.on_value_change(lambda _: update_fields())
                                    source_step.on_value_change(lambda _: update_fields())
                                    output.on_value_change(lambda _: update_fields())
                                    ref_pointer.on_value_change(choose_field)
                                    await update_fields()


                                    def remove():
                                        binding_rows.remove(record)
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
                        ui.label(
                            "前序结果从本次运行的任务数据库读取，不依赖内存。"
                        ).classes("text-gray-500")
                    ctx.context_panel = ui.column().classes("tw-step-context-materials w-full min-w-0")
                    ctx.context_component.render(ctx.context_panel)
                    with ui.expansion("时间设置", value=False).classes("w-full"):
                        delay = ui.number(
                            "上一步成功后等待（秒）", value=fields.get('delay', step["delay_after_previous_seconds"]),
                            min=0, max=86400, step=1,
                        ).classes("w-full")
                        if step["position"] == 0:
                            delay.disable()
                            ui.label("首步骤无上一步，不等待。")
                        else:
                            ui.label("默认 0 秒；单步和继续也遵守间隔，已等待足够时间则立即执行。")
                        timeout = ui.number(
                            "步骤执行超时（秒，不包含间隔）", value=fields.get('timeout', step["timeout_ms"] / 1000),
                            min=0.001, max=3600, step=0.001,
                        ).classes("w-full")
                    ui.label("执行代码").classes("text-base font-semibold")
                    code = ui.codemirror(fields.get('code', step["step_content"]), language="Python", line_wrapping=True).classes("w-full border rounded")
                    with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                        async def lint():
                            diagnostics = await ctx.controller.validate_step_candidate(ctx.document())
                            if not editor_is_current():
                                return
                            ui.notify("校验通过" if not diagnostics else document_text(diagnostics))
                        ctx.button("校验内容", lint)
                        ctx.button("确认验证", lambda: ctx.ai_editor.confirm_step(ctx.paint))
            debug_column = ui.column().classes("tw-debug-column w-full min-w-0 gap-3")
            debug_column.set_visibility(False)

            async def build_debug():
                nonlocal debug_built
                if debug_built:
                    return
                debug_built = await ctx.debug_drawer.render(
                    debug_column, step, ctx.old_step, current=editor_is_current,
                )
                if debug_built:
                    self.capture_view(ctx)

            set_debug_layout(False)
            ctx.edit_controls = {
                "name": name,
                "step_description": step_description,
                "step_notes": step_notes,
                "code": code,
                "caps": caps,
                "plugin_actions": plugin_actions,
                "schema": schema,
                "delay": delay,
                "timeout": timeout,
                "bindings": binding_rows,
            }
            self.sync_draft()
            for control in (name, step_description, step_notes, code, caps, delay, timeout):
                control.on_value_change(mark_dirty)
        if editor_is_current():
            ctx.step_state.reload_draft = None
            self.capture_view(ctx)
            if ctx.open_debug_on_navigation:
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
