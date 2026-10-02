"""Step document composition and serialized draft persistence."""

import json
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable

from nicegui import ui

from taskweave.core.validation import TaskError, normalize_step
from taskweave.desktop.contexts import context_ai_items
from taskweave.desktop.forms import SchemaEditor, ValueForm

EMPTY = "async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n"

def document_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)

from taskweave.core.validation import TaskError, normalize_step
from taskweave.desktop.dependencies import result_fields


@dataclass
class StepEditorRenderContext:
    """Explicit editor-only services and view handles used during composition."""
    state: Any
    context_state: Any
    debug_panel: Any
    controller: Any
    button: Callable
    page_getter: Callable
    page_generation_getter: Callable
    page_timer: Callable
    step_list: Any
    save_editor: Callable
    document: Callable
    paint: Callable
    animate_reorder: Callable
    finish_reorder_animation: Callable
    environment_select: Callable
    trial_variables: Callable
    refresh_trial_inputs: Callable
    debug_session: Any
    ai_editor: Any
    context_component: Any
    confirm_end: Callable
    selected_step_control: Any = None
    save_state: Any = None
    context_panel: Any = None
    trial_ai_supplement: Any = None
    trial_variables_area: Any = None
    trial_form: Any = None
    trial_environment: Any = None
    trial_start_status: Any = None
    edit_controls_cache: Any = None
    open_debug_on_navigation: bool = False
    on_debug_visibility: Callable = lambda visible: None
    debug_poll_allowed: Callable = lambda: True

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
    def debug_supplements(self): return self.debug_panel.state.supplements
    @property
    def environment_id(self): return self.debug_panel.state.environment_id
    @environment_id.setter
    def environment_id(self, value): self.debug_panel.state.environment_id = value


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
        environment = self.view.get('trial_environment')
        if form is None or environment is None or environment.is_deleted:
            return None
        return deepcopy({
            'task_id': self.state.task_id, 'step_id': self.state.step_id,
            'environment_id': environment.value,
            'task': form.task_edits(), 'step': form.step_edits(),
        })

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
        self.view = {name: getattr(ctx, name) for name in (
            "selected_step_control", "save_state", "context_panel",
            "trial_ai_supplement", "trial_variables_area", "trial_form", "trial_environment",
            "trial_start_status",
        )}

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
        ctx.selected_step_control = None
        with ui.row().classes("tw-editor-layout w-full items-start flex-wrap lg:flex-nowrap") as editor_layout:
            with ui.column().classes("tw-panel tw-step-sidebar w-full lg:w-56 shrink-0"):
                with ui.row().classes("tw-step-list-heading w-full items-center justify-between gap-2"):
                    ui.label("步骤目录").classes("font-semibold")
                    ui.label(str(len(steps))).classes("tw-step-count")
                    toolbar = ui.row().classes("tw-step-list-toolbar items-center justify-end shrink-0")
                with ui.column().classes("w-full overflow-y-auto gap-2").style("max-height: calc(100vh - 330px)") as step_list_area:
                    pass
                selected_step_control = await ctx.step_list.render(steps, catalog, toolbar, step_list_area)
                if not editor_is_current():
                    return
                ctx.selected_step_control = selected_step_control
            with ui.column().classes("tw-panel tw-editor-panel tw-content w-full relative overflow-hidden").style('position: relative; min-height: calc(100vh - 260px)') as editor_panel:
                def set_debug_layout(opening):
                    debug_column.set_visibility(opening)
                    ctx.on_debug_visibility(opening)
                    if opening:
                        editor_layout.classes(add="tw-debug-open")
                        if debug_drawer:
                            debug_drawer.style('width: 100%; min-width: 0; max-height: calc(100vh - 300px); overflow-y: auto')
                    else:
                        editor_layout.classes(remove="tw-debug-open")
                    debug_toggle.text = '收起调试' if opening else '调试'
                    debug_toggle.props('icon=expand_less aria-label=收起调试' if opening else 'icon=bug_report aria-label=展开调试')

                debug_built = False
                debug_building = False
                debug_drawer = None

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
                        await ctx.debug_panel.refresh_trial()

                def mark_dirty(_=None):
                    if editor_is_current() and ctx.edit_controls and ctx.save_state and not ctx.save_state.is_deleted:
                        ctx.save_state.text = '未保存修改'

                with ui.row().classes("tw-step-config-heading w-full items-center gap-2"):
                    ui.label("步骤配置").classes("tw-step-config-title text-lg font-semibold grow")
                    ctx.button("保存步骤", ctx.save_editor, primary=True)
                    with ui.button("更多", icon="more_horiz").props("flat"):
                        with ui.menu():
                            actions_menu = ctx.step_list.actions
                            move_up_item = ui.menu_item("上移", actions_menu["move_up"]).set_enabled(actions_menu["can_move_up"])
                            move_down_item = ui.menu_item("下移", actions_menu["move_down"]).set_enabled(actions_menu["can_move_down"])
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
                                            previous,
                                            label="前序步骤",
                                            value=ref.get("step_id"),
                                        ).classes("w-48")
                                        output = ui.input(
                                            "结果容器（通常为 data）", value=ref.get("output", "data")
                                        )
                                        ref_pointer = ui.select(
                                            {ref.get("pointer", ""): ref.get("pointer", "") or "全部结果"},
                                            label="结果字段（可选择或填写 /字段名）",
                                            value=ref.get("pointer", ""), with_input=True, new_value_mode="add-unique",
                                        ).classes("min-w-64")
                                    preview = ui.label().classes("text-xs text-gray-500 tw-code w-full")
                                    record = (
                                        key_input,
                                        source,
                                        literal,
                                        source_step,
                                        output,
                                        ref_pointer,
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
                                        literal.set_visibility(source.value == 'literal')
                                        source_step.set_visibility(source.value == 'step')
                                        output.set_visibility(source.value == 'step')
                                        ref_pointer.set_visibility(source.value != 'literal')
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
                                        from taskweave.desktop.dependencies import result_fields
                                        if not editor_is_current():
                                            return
                                        fields = result_fields(result)
                                        ref_pointer.field_types = {path: item['type'] for path, item in fields.items()}
                                        options = {path: item['label'] for path, item in fields.items()}
                                        if ref_pointer.value not in options:
                                            options[ref_pointer.value] = ref_pointer.value or '全部结果'
                                        ref_pointer.options = options
                                        ref_pointer.update()
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
                            "步骤执行超时（秒，不包含间隔）", value=fields.get('timeout', step["timeout_ms"] // 1000),
                            min=1, max=3600, step=1,
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
                nonlocal debug_built, debug_drawer
                if debug_built:
                    return
                debug_column.clear()
                with debug_column:
                    with ui.column().classes('tw-debug-drawer tw-panel bg-white gap-3') as debug_drawer:
                        with ui.row().classes('w-full items-center justify-between gap-2'):
                            with ui.column().classes('gap-0'):
                                ui.label('调试 · ' + step['name']).classes('text-lg font-medium')
                        ui.label('输入来自已保存的配置；运行调试前会先保存当前草稿。').classes('text-xs text-gray-500')
                        environment = await ctx.environment_select()
                        environment.classes(remove="w-72", add="w-full min-w-0")
                        if not editor_is_current():
                            return
                        ctx.trial_environment = environment
                        ctx.trial_variables_area = ui.column().classes('w-full')
                        with ctx.trial_variables_area:
                            trial_form = await ctx.trial_variables(ctx.old_step, environment)
                        if not editor_is_current():
                            return
                        ctx.trial_form = trial_form
                        recovered_inputs = ctx.step_state.reload_debug
                        if recovered_inputs and (recovered_inputs['task_id'], recovered_inputs['step_id']) == (ctx.task_id, ctx.step_id):
                            trial_form.apply_task_values(recovered_inputs['task'])
                            trial_form.apply_step_values(recovered_inputs['step'])
                            ctx.step_state.reload_debug = None
                        ctx.trial_start_status = ui.label().classes('text-sm text-gray-500')
                        debug_panel = ctx.debug_panel
                        debug_panel.render_actions(
                            ui.column().classes('tw-debug-actions w-full gap-2'),
                            lambda: ctx.debug_session.start_trial(continue_session=True),
                            ctx.debug_session.start_flow_trial,
                            lambda: debug_panel.end(ctx.confirm_end, debug_panel.refresh_trial),
                        )
                        debug_panel.trial_area = ui.column().classes("w-full")
                        ui.separator()
                        ctx.trial_ai_supplement = ui.textarea(
                            'AI 补充说明（可选）',
                            value=ctx.debug_supplements.get(ctx.step_id, ''),
                            placeholder='仅用于当前调试轮次，例如：点击结果后会打开新标签页。',
                        ).props('outlined autogrow debounce=50').classes('w-full')
                        def remember_supplement(event, step_id=ctx.step_id):
                            ctx.debug_supplements[step_id] = event.value or ''
                        ctx.trial_ai_supplement.on_value_change(remember_supplement)
                        with ui.row().classes('w-full items-center gap-2 flex-nowrap'):
                            ctx.button('AI 修复', lambda control=ctx.trial_ai_supplement: ctx.ai_editor.choose_repair_mode(
                                control, repaint=ctx.paint)).classes('flex-1 min-w-0')
                            async def clear_ai_repair_context(control=ctx.trial_ai_supplement):
                                ctx.ai_editor.new_debug_round(control)
                            ctx.button('清空 AI 修复上下文', clear_ai_repair_context).classes('flex-1 min-w-0')
                        async def refresh_current_trial():
                            if (ctx.page == 'editor' and ctx.step_state.generation == editor_generation
                                    and ctx.step_id == editor_step_id and debug_column.visible
                                    and ctx.debug_poll_allowed()
                                    and not getattr(ctx.debug_session, "flow_dialog_open", False)
                                    and not getattr(ctx.ai_editor, "_ai_flow_active", False)):
                                await debug_panel.poll()
                    with ui.column().classes("tw-debug-log-panel tw-panel w-full min-w-0"):
                        ui.label("调试日志").classes("font-semibold")
                        debug_panel.logs_area = ui.column().classes("tw-debug-log-body w-full")
                if not editor_is_current():
                    return
                debug_built = True
                self.capture_view(ctx)
                self.own_timer(ctx.page_timer(1, refresh_current_trial))

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
            for control in (name, step_description, step_notes, code, caps, delay, timeout):
                control.on_value_change(mark_dirty)
        if editor_is_current():
            ctx.step_state.reload_draft = None
            self.capture_view(ctx)
            if ctx.open_debug_on_navigation:
                await build_debug()
                if editor_is_current():
                    set_debug_layout(True)
                    await ctx.debug_panel.refresh_trial()


    def document(self):
        controls = self.state.edit_controls
        doc = normalize_step(self.state.old_step)
        doc.update(
            name=controls["name"].value,
            step_description=controls["step_description"].value,
            step_notes=controls["step_notes"].value,
            step_content=controls["code"].value,
            capabilities=sorted({action for plugin in (controls["caps"].value or []) for action in controls["plugin_actions"].get(plugin, [])}),
            input_schema=controls["schema"].schema(),
            delay_after_previous_seconds=(
                int(controls["delay"].value or 0)
                if float(controls["delay"].value or 0).is_integer()
                else controls["delay"].value
            ),
            timeout_ms=int(controls["timeout"].value or 60) * 1000,
        )
        doc["bindings"] = {}
        for name, source, value, source_step, output, ref_pointer in controls["bindings"]:
            key = name.value.strip()
            if not key or key in doc["bindings"]:
                raise TaskError("FORM_INVALID", "输入绑定名称不能为空或重复")
            if source.value == "literal":
                try:
                    literal = json.loads(value.value)
                except ValueError:
                    literal = value.value
                doc["bindings"][key] = {"literal": literal}
            else:
                ref = {"source": source.value, "pointer": ref_pointer.value}
                if source.value == "step":
                    if not source_step.value:
                        raise TaskError("FORM_INVALID", "请选择前序步骤")
                    ref.update(step_id=source_step.value, output=output.value or "data")
                doc["bindings"][key] = {"ref": ref}
        properties = (doc["input_schema"].setdefault("properties", {}) if doc["bindings"]
                      else doc["input_schema"].get("properties", {}))
        for key, binding in doc["bindings"].items():
            if key not in properties:
                if "literal" in binding:
                    kind = result_fields(binding["literal"])[""]["type"]
                else:
                    control = next(row[5] for row in controls["bindings"] if row[0].value.strip() == key)
                    kind = getattr(control, "field_types", {}).get(binding["ref"]["pointer"], "string")
                properties[key] = {"type": kind}
        return doc

    async def save(self, document=None):
        state = self.state
        task_id, step_id, generation = state.task_id, state.step_id, state.generation
        page_generation = self.page_generation()
        document = self.document() if document is None else document
        async with state.save_lock:
            if ((state.task_id, state.step_id, state.generation) != (task_id, step_id, generation)
                    or self.page_generation() != page_generation):
                raise TaskError("EDITOR_CHANGED", "步骤已切换，请重新保存当前草稿。")
            # A queued save must use the latest optimistic-lock baseline after
            # the preceding save has committed, while keeping this request's
            # document snapshot from the moment it was triggered.
            old_step = state.old_step
            saved = await self.controller.save_draft(task_id, document, old_step)
            if ((state.task_id, state.step_id, state.generation) == (task_id, step_id, generation)
                    and self.page_generation() == page_generation):
                state.old_step = saved
                state.step_id = saved["step_id"]
            return saved
