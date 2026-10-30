"""Task sequence editor and durable execution progress page."""

import json
from copy import deepcopy
from uuid import uuid4

from nicegui import ui

from taskweave.core.validation import TaskError
from taskweave.desktop.components.sequence_execution import LABELS
from taskweave.desktop.display import step_names
from taskweave.desktop.pages.base import Page
from taskweave.presentation.sequences import SequenceDraft
from taskweave.core.task_flow import conditional_branches
from taskweave.desktop.components.sequence_flow_editor import SequenceFlowEditor
from taskweave.desktop.components.startup_inputs import StartupInputs
from taskweave.presentation.startup_inputs import StartupInputDraft


class SequencesPage(Page):
    def __init__(self, controller, button, repaint, *, identity, execution=False):
        self.controller, self.button, self.repaint = controller, button, repaint
        self.identity = identity
        self.execution = execution
        self.draft = SequenceDraft()
        self.flow_editor = SequenceFlowEditor(self)
        self.tasks = []
        self.steps = {}
        self.flows = {}
        self.flow_confirmations = {}
        self.environments = []
        self.definitions = []
        self.progress_area = None
        self.progress_snapshot = None
        self.timer = None
        self.invalid_literals = set()
        self.literal_text = {}
        self.selected_node_id = None
        self.active_section = "flow"
        self.node_section = "task"
        self.startup_drafts = {}
        self.startup_views = {}

    def dispose(self):
        if self.timer:
            self.timer.cancel()
            self.timer = None
        self.progress_area = None
        self.progress_snapshot = None

    async def _load(self):
        self.tasks = await self.controller.call("task.list")
        self.environments = await self.controller.call("environment.list")
        self.definitions = await self.controller.call("sequence.list")
        self.steps = {task["task_id"]: await self.controller.call("step.list", task_id=task["task_id"])
                      for task in self.tasks}
        descriptions = {task['task_id']: await self.controller.call('task.flow.describe', task_id=task['task_id'])
                        for task in self.tasks}
        self.flows = {key: item['flow'] for key, item in descriptions.items()}
        self.flow_confirmations = {key: item['confirmed'] for key, item in descriptions.items()}

    def _task_name(self, task_id):
        return next((task["name"] for task in self.tasks if task["task_id"] == task_id), "已删除任务")

    def _task_status(self, task_id):
        steps = self.steps.get(task_id, [])
        confirmed = (bool(steps) and all(step['validation_state'] == 'VALIDATED' for step in steps)
                     and self.flow_confirmations.get(task_id, False))
        return '任务已确认' if confirmed else '任务待确认'

    async def render(self):
        await self._load()
        with ui.row().classes("w-full justify-between items-center"):
            ui.label("任务组合").classes("text-xl font-semibold")
            self.button("新建组合", self.new, primary=True, icon="add")
        with ui.element("div").classes("tw-sequence-layout w-full"):
            with ui.column().classes("tw-panel tw-sequence-sidebar gap-2"):
                ui.label("已保存组合").classes("font-semibold mb-2")
                for definition in self.definitions:
                    with ui.column().classes("tw-sequence-definition w-full gap-1" + (
                            " is-selected" if definition["sequence_id"] == self.draft.sequence_id else "")):
                        self.button(definition["name"], lambda item=definition: self.open_definition(item),
                                    flat=True).classes("w-full text-left")
                        ui.label(f"{len(definition['nodes'])} 个任务").classes("text-xs text-gray-500 px-3 pb-2")
                if not self.definitions:
                    ui.label("暂无组合").classes("text-gray-500")
            with ui.column().classes("tw-sequence-workspace w-full gap-4"):
                await self._render_editor()
                await self.refresh_progress()
        origin = self.identity()
        async def poll():
            if self.identity() == origin and self.progress_area:
                await self.refresh_progress()
        self.timer = ui.timer(1, poll)

    async def new(self):
        self.flow_editor.reset()
        self.draft.reset()
        self.startup_drafts.clear()
        self.startup_views.clear()
        self.invalid_literals.clear()
        self.literal_text.clear()
        self.selected_node_id = None
        self.active_section = "flow"
        self.node_section = "task"
        await self.repaint()

    async def open_definition(self, definition):
        self.flow_editor.reset()
        self.draft.load(definition)
        self.startup_drafts.clear()
        self.startup_views.clear()
        self.invalid_literals.clear()
        self.literal_text.clear()
        self.selected_node_id = None
        self.active_section = "flow"
        self.node_section = "task"
        await self.repaint()

    async def _render_editor(self):
        draft = self.draft
        ids = {node["node_id"] for node in draft.nodes}
        if self.selected_node_id not in ids:
            self.selected_node_id = draft.nodes[0]["node_id"] if draft.nodes else None
        with ui.row().classes("tw-sequence-header w-full items-center justify-between"):
            with ui.column().classes('gap-1 grow min-w-0'):
                ui.label(draft.name or "新建组合").classes("text-xl font-semibold")
                if draft.revision is not None:
                    ui.label(f"v{draft.revision}").classes('tw-badge')
            with ui.row().classes("items-center gap-2 flex-wrap"):
                if draft.sequence_id:
                    self.button("删除定义", self.confirm_delete_definition, flat=True).classes("tw-danger")
                self.button("保存组合", self.save, icon="save")
                self.button("调试组合", self.launch_dialog, primary=True, icon="bug_report")
        with ui.tabs(value=self.active_section).classes('tw-sequence-tabs tw-step-workspace-tabs w-full') as tabs:
            ui.tab('flow', label='任务编排')
            ui.tab('basic', label='基础配置')
            ui.tab('debug', label='调试')
        tabs.on_value_change(lambda event: setattr(self, 'active_section', event.value))
        self.progress_snapshot = None
        with ui.tab_panels(tabs, value=self.active_section).classes('tw-sequence-outer-panels w-full'):
            with ui.tab_panel('flow').classes('tw-sequence-flow w-full gap-4'):
                await self._render_flow()
                await self._render_node_editor()
            with ui.tab_panel('basic').classes('tw-panel tw-editor-body'):
                ui.input("组合名称", value=draft.name,
                    on_change=lambda event: setattr(draft, "name", event.value or "")).classes("w-full")
                ui.textarea("说明", value=draft.description,
                    on_change=lambda event: setattr(draft, "description", event.value or ""))\
                    .props("outlined autogrow").classes("w-full")
                with ui.expansion("组合启动输入 Schema", icon="data_object").classes("w-full"):
                    ui.textarea("Schema（JSON）", value=draft.input_schema_text,
                        on_change=lambda event: setattr(draft, "input_schema_text", event.value or ""))\
                        .props("outlined autogrow").classes("w-full")
            with ui.tab_panel('debug').classes('tw-sequence-history w-full'):
                self.progress_area = ui.column().classes('tw-panel w-full gap-3')

    async def _render_flow(self):
        self.flow_editor.render()

    async def _render_node_editor(self):
        if self.flow_editor.selected:
            with ui.column().classes("tw-panel tw-editor-panel w-full tw-editor-body"):
                self.flow_editor.render_configuration()
            return
        draft = self.draft
        with ui.column().classes("tw-panel tw-editor-panel w-full"):
            selected = next(((i, node) for i, node in enumerate(draft.nodes)
                             if node["node_id"] == self.selected_node_id), None)
            if selected:
                index, node = selected
                with ui.row().classes('tw-step-config-heading w-full items-center gap-3'):
                    ui.label(f"{index + 1:02d}").classes('tw-step-number')
                    ui.label(self._task_name(node['task_id'])).classes('text-lg font-semibold grow min-w-0')
                    ui.label(self._task_status(node['task_id'])).classes('tw-badge')
            with ui.tabs(value=self.node_section).classes("tw-sequence-node-tabs tw-step-workspace-tabs w-full") as tabs:
                ui.tab("task", label="任务配置")
                ui.tab("mapping", label="输入映射")
            tabs.on_value_change(lambda event: setattr(self, "node_section", event.value))
            with ui.tab_panels(tabs, value=self.node_section).classes("w-full tw-sequence-panels"):
                with ui.tab_panel("task").classes("tw-editor-body"):
                    if selected:
                        index, node = selected
                        with ui.row().classes("w-full items-center justify-between"):
                            ui.label(f"引用任务 · {len(self.steps.get(node['task_id'], []))} 个步骤").classes('text-sm text-gray-500')
                            ui.button("输入映射", on_click=lambda: tabs.set_value("mapping"), icon="input").props("flat no-caps")
                        task = next((item for item in self.tasks if item['task_id'] == node['task_id']), None)
                        if task and task.get('description'):
                            ui.label(task['description']).classes('text-sm whitespace-pre-wrap')
                        environment_options = {"": "默认环境"} | {
                            item["environment_id"]: item["name"] for item in self.environments}
                        ui.select(environment_options, value=node["environment_id"] or "", label="执行环境",
                            on_change=lambda event, current=node: current.__setitem__("environment_id", event.value or None))\
                            .classes("w-full")
                        with ui.row().classes("items-center gap-2"):
                            if draft.can_move(index, -1):
                                self.button("向前移动", lambda i=index: self.move_node(i, -1), flat=True, icon="arrow_back")
                            if draft.can_move(index, 1):
                                self.button("向后移动", lambda i=index: self.move_node(i, 1), flat=True, icon="arrow_forward")
                            self.button("移除任务", lambda i=index: self.remove_node(i), flat=True, icon="remove_circle_outline")
                    else:
                        ui.label("请选择或添加任务").classes("text-gray-500")
                with ui.tab_panel("mapping").classes("tw-editor-body"):
                    if selected:
                        index, node = selected
                        await self._node_mappings(index, node)
                    else:
                        ui.label("请选择或添加任务").classes("text-gray-500")

    async def launch_dialog(self):
        with ui.dialog() as dialog, ui.card().classes('tw-panel w-full max-w-3xl gap-4'):
            ui.label('执行组合' if self.execution else '调试组合').classes('text-lg font-semibold')
            ui.label(self.draft.name or '新建组合').classes('text-sm text-gray-500')
            ui.textarea('启动输入（JSON 对象）', value=self.draft.launch_inputs_text,
                on_change=lambda event: setattr(self.draft, 'launch_inputs_text', event.value or ''))\
                .props('outlined autogrow').classes('w-full')
            self.startup_views = {}
            for index, node in enumerate(self.draft.nodes):
                task = next((item for item in self.tasks if item['task_id'] == node['task_id']), None)
                if task is None:
                    continue
                schema = json.loads(task['input_schema_json'])
                manual_schema = deepcopy(schema)
                for name, source in node['inputs'].items():
                    if source['kind'] == 'literal':
                        manual_schema['properties'][name]['default'] = source['value']
                    else:
                        manual_schema.get('properties', {}).pop(name, None)
                manual_schema['required'] = [name for name in schema.get('required', [])
                                             if name in manual_schema.get('properties', {})]
                steps = deepcopy(self.steps.get(node['task_id'], []))
                for step in steps:
                    bindings = step.setdefault('bindings', {})
                    for name, source in node['step_inputs'].get(step['step_id'], {}).items():
                        if source['kind'] == 'literal':
                            step['input_schema']['properties'][name]['default'] = source['value']
                        else:
                            bindings[name] = {'literal': None}
                    for name in schema.get('properties', {}):
                        if (name not in manual_schema.get('properties', {})
                                and 'default' not in step['input_schema'].get('properties', {}).get(name, {})):
                            bindings.setdefault(name, {'literal': None})
                with ui.expansion(f'{index + 1}. {task["name"]}', value=False).classes('w-full border rounded'):
                    environment = ui.select({node['environment_id'] or '': '执行环境'},
                                            value=node['environment_id'] or '').classes('hidden')
                    draft = self.startup_drafts.setdefault(node['node_id'], StartupInputDraft())
                    view = StartupInputs(self.controller)
                    await view.render(steps, environment, task_schema=manual_schema, draft=draft,
                                      environments=self.environments)
                    self.startup_views[node['node_id']] = view
            async def launch():
                dialog.close()
                await self.start()
            with ui.row().classes('w-full justify-end gap-2'):
                ui.button('取消', on_click=dialog.close).props('flat no-caps')
                self.button('执行整个组合' if self.execution else '开始调试', launch, primary=True, icon='play_arrow')
        dialog.open()

    async def _node_mappings(self, index, node):
        task = next((item for item in self.tasks if item["task_id"] == node["task_id"]), None)
        fields = False
        if task:
            schema = json.loads(task["input_schema_json"])
            if schema.get("properties"):
                fields = True
                await self._target_fields(index, node, node["inputs"], schema, "任务输入", None)
        for step in self.steps.get(node["task_id"], []):
            available = {key: spec for key, spec in step["input_schema"].get("properties", {}).items()
                         if key not in step["bindings"]}
            if available:
                fields = True
                sources = node["step_inputs"].setdefault(step["step_id"], {})
                schema = {**step["input_schema"], "properties": available}
                await self._target_fields(index, node, sources, schema, f"步骤输入 · {step['name']}", step["step_id"])
        if not fields:
            ui.label("该任务没有需要配置的输入").classes("text-gray-500")

    async def select_node(self, node_id):
        self.flow_editor.flush()
        self.flow_editor.reset()
        self.selected_node_id = node_id
        self.active_section = "flow"
        await self.repaint()

    async def add_dialog(self, parent_id="root", index=None):
        try:
            self.flow_editor.flush()
        except TaskError as exc:
            self.flow_editor.feedback("插入失败：" + str(exc))
            return
        with ui.dialog() as dialog, ui.card().classes("tw-panel w-full max-w-lg gap-4"):
            ui.label("添加任务").classes("text-lg font-semibold")
            chooser = ui.select({task["task_id"]: task["name"] for task in self.tasks},
                                label="选择任务", with_input=True).classes("w-full")
            summary = ui.column().classes('tw-sequence-task-summary w-full gap-2')
            def show_summary(event):
                summary.clear()
                task = next((item for item in self.tasks if item['task_id'] == event.value), None)
                if task is None: return
                with summary:
                    ui.label(task['name']).classes('font-semibold')
                    if task.get('description'):
                        ui.label(task['description']).classes('text-sm whitespace-pre-wrap')
                    ui.label(f"{len(self.steps.get(task['task_id'], []))} 个步骤 · {self._task_status(task['task_id'])}").classes('text-sm text-gray-500')
            chooser.on_value_change(show_summary)
            async def add():
                try:
                    self.flow_editor.flush()
                    identity = self.draft.add(chooser.value, parent_id, index)
                except TaskError as exc:
                    error.set_text("插入失败：" + str(exc))
                    return
                self.flow_editor.reset()
                self.selected_node_id = identity
                self.active_section = "flow"
                self.node_section = "task"
                dialog.close()
                await self.repaint()
            error = ui.label("").classes("text-negative whitespace-pre-wrap")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("取消", on_click=dialog.close).props("flat no-caps")
                self.button("添加到末尾" if index is None else "添加到此处", add, primary=True, icon="add")
        dialog.open()

    async def confirm_delete_definition(self):
        with ui.dialog() as dialog, ui.card().classes("tw-panel w-full max-w-md gap-4"):
            ui.label("删除组合定义？").classes("text-lg font-semibold")
            ui.label(self.draft.name)
            async def delete():
                dialog.close()
                await self.delete_definition()
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("取消", on_click=dialog.close).props("flat no-caps")
                self.button("删除", delete).props("outline color=negative").classes("tw-confirm-danger")
        dialog.open()

    async def _target_fields(self, index, node, sources, schema, title, step_id):
        ui.label(title).classes("font-medium text-sm")
        required = set(schema.get("required", []))
        for key, spec in schema.get("properties", {}).items():
            with ui.column().classes("tw-sequence-mapping w-full gap-3"):
                caption = f"{key}{' *' if key in required else ''}"
                if isinstance(spec, dict) and spec.get("description"):
                    caption += f" · {spec['description']}"
                ui.label(caption).classes("text-sm")
                token = (node["node_id"], step_id, key)
                source = sources.get(key)
                kind = source["kind"] if source else ""
                options = {"": "执行时填写", "literal": "固定值", "sequence": "组合启动输入", "output": "前序任务输出", "loop": "当前循环变量", "branch": "分支公共输出"}
                choice = ui.select(options, value=kind, label="取值方式").classes("w-full")
                async def change_kind(event, mapping=sources, field=key, marker=token):
                    self.invalid_literals.discard(marker)
                    self.literal_text.pop(marker, None)
                    selected = event.value
                    if selected == "literal":
                        mapping[field] = {"kind": "literal", "value": None}
                    elif selected == "sequence":
                        mapping[field] = {"kind": "sequence", "pointer": ""}
                    elif selected == "loop":
                        mapping[field] = {"kind": "loop", "node_id": "", "field": "item", "pointer": ""}
                    elif selected == "branch":
                        mapping[field] = {"kind": "branch", "node_id": "", "output": "", "pointer": ""}
                    elif selected == "output":
                        mapping[field] = {"kind": "output", "node_id": "", "step_id": "",
                                          "output": "data", "pointer": ""}
                    else:
                        mapping.pop(field, None)
                    await self.repaint()
                choice.on_value_change(change_kind)
                if kind == "literal":
                    def literal_changed(event, mapping=sources, field=key, marker=token):
                        self.literal_text[marker] = event.value
                        try:
                            mapping[field]["value"] = json.loads(event.value)
                            self.invalid_literals.discard(marker)
                        except (ValueError, TypeError):
                            self.invalid_literals.add(marker)
                    ui.input("JSON 值", value=self.literal_text.get(token, json.dumps(source["value"], ensure_ascii=False)),
                             on_change=literal_changed).classes("w-full")
                elif kind == "sequence":
                    ui.input("启动输入路径，例如 /customer/id", value=source["pointer"],
                             on_change=lambda event, item=source: item.__setitem__("pointer", event.value or ""))\
                        .classes("w-full")
                elif kind in {"loop", "branch"}:
                    scope = self.draft.scope(node["node_id"])
                    allowed = scope["loops" if kind == "loop" else "branches"]
                    labels = {key: value for key, value in self.flow_editor.controls().items() if key in allowed}
                    ui.select(labels, value=source["node_id"] if source["node_id"] in labels else None,
                              label="所属控制块", on_change=lambda event, item=source: item.__setitem__("node_id", event.value or "")).classes("w-full")
                    if kind == "loop":
                        ui.select({"item": "当前项", "index": "当前索引（从 0 开始）", "state": "循环状态"}, value=source["field"],
                                  label="循环变量", on_change=lambda event, item=source: item.__setitem__("field", event.value)).classes("w-full")
                    else:
                        ui.input("公共输出名称", value=source["output"],
                                 on_change=lambda event, item=source: item.__setitem__("output", event.value or "")).classes("w-full")
                    ui.input("JSON 路径（留空表示整体）", value=source["pointer"],
                             on_change=lambda event, item=source: item.__setitem__("pointer", event.value or "")).classes("w-full")
                elif kind == "output":
                    predecessors = {}
                    for position, preceding in enumerate([item for item in self.draft.nodes if item["node_id"] in self.draft.scope(node["node_id"])["nodes"]], 1):
                        for prior_step in self.steps.get(preceding["task_id"], []):
                            predecessors[preceding["node_id"] + "|" + prior_step["step_id"]] = (
                                f"{position:02d} · {self._task_name(preceding['task_id'])} · {prior_step['name']}")
                    selected = source["node_id"] + "|" + source["step_id"]
                    async def choose_output(event, item=source):
                        if event.value:
                            item["node_id"], item["step_id"] = event.value.split("|", 1)
                    ui.select(predecessors, value=selected if selected in predecessors else None,
                              label="来源任务和步骤", on_change=choose_output).classes("w-full")
                    with ui.row().classes("w-full gap-2"):
                        ui.input("输出名", value=source["output"],
                                 on_change=lambda event, item=source: item.__setitem__("output", event.value or ""))\
                            .classes("w-36")
                        ui.input("JSON 路径（留空表示整体）", value=source["pointer"],
                                 on_change=lambda event, item=source: item.__setitem__("pointer", event.value or ""))\
                            .classes("grow")
                    loop_options = {'combination:' + key: '组合 · ' + self.flow_editor.controls()[key] for key in self.draft.scope(node["node_id"])["aggregates"]}
                    def collect_loops(flow_node, task_name):
                        if flow_node["kind"] in {"foreach", "loop"}:
                            loop_options['task:' + flow_node["id"]] = f"{task_name} · {flow_node['id']}"
                        children = (flow_node["children"] if flow_node["kind"] == "sequence" else
                                    [body for _, body in conditional_branches(flow_node)] if flow_node["kind"] == "if" else
                                    [flow_node["body"]] if flow_node["kind"] in {"foreach", "loop"} else [])
                        for child in children:
                            collect_loops(child, task_name)
                    for preceding in self.draft.nodes:
                        if preceding["node_id"] not in self.draft.scope(node["node_id"])["nodes"]:
                            continue
                        flow = self.flows.get(preceding["task_id"])
                        if flow:
                            collect_loops(flow["root"], self._task_name(preceding["task_id"]))
                    if loop_options:
                        async def choose_projection_loop(event, item=source):
                            if event.value:
                                projection_scope, loop_id = event.value.split(':', 1)
                                item.update(loop_node_id=loop_id, projection_scope=projection_scope, item_pointer=item.get("item_pointer", ""), pointer="")
                            else:
                                item.pop("loop_node_id", None)
                                item.pop("item_pointer", None)
                                item.pop('projection_scope', None)
                            await self.repaint()
                        inferred_scope = source.get('projection_scope') or ('combination' if source.get('loop_node_id') in self.draft.scope(node['node_id'])['aggregates'] else 'task')
                        projection = inferred_scope + ':' + source['loop_node_id'] if source.get('loop_node_id') else ''
                        ui.select({"": "使用完整结果"} | loop_options,
                                  value=projection if projection in loop_options or not projection else None, label="逐轮投影所属循环",
                                  on_change=choose_projection_loop)\
                            .classes("w-full")
                        if projection and projection not in loop_options:
                            ui.label('原投影循环不可用，请重新选择。').classes('text-sm text-red-700')
                        if source.get("loop_node_id"):
                            ui.input("每轮结果字段（例如 /id）", value=source.get("item_pointer", ""),
                                     on_change=lambda event, item=source: item.__setitem__("item_pointer", event.value or ""))\
                                .classes("w-full")

    async def add_node(self, task_id):
        self.flow_editor.flush()
        self.flow_editor.reset()
        self.draft.add(task_id)
        self.selected_node_id = self.draft.nodes[-1]["node_id"]
        self.active_section = "flow"
        self.node_section = "task"
        await self.repaint()

    async def move_node(self, index, direction):
        try:
            self.flow_editor.flush()
            self.draft.move(index, direction)
        except TaskError as exc:
            self.flow_editor.feedback("无法移动：" + str(exc))
            return
        await self.repaint()

    async def remove_node(self, index):
        removed = self.draft.nodes[index]["node_id"]
        try:
            self.flow_editor.flush()
            self.draft.remove(index)
        except TaskError as exc:
            self.flow_editor.feedback("无法移除：" + str(exc))
            return
        self.invalid_literals = {token for token in self.invalid_literals if token[0] != removed}
        self.literal_text = {token: text for token, text in self.literal_text.items() if token[0] != removed}
        if self.selected_node_id == removed:
            self.selected_node_id = (self.draft.nodes[min(index, len(self.draft.nodes) - 1)]["node_id"]
                                     if self.draft.nodes else None)
        await self.repaint()

    async def save(self):
        self.flow_editor.flush()
        if self.invalid_literals:
            raise TaskError("INPUT_INVALID", "请填写有效的 JSON 固定值")
        saved = await self.controller.call("sequence.save", **self.draft.payload())
        view = self.flow_editor.views.get(self.draft.sequence_id or 'new')
        if view is not None:
            self.flow_editor.views[saved['sequence_id']] = view
        self.draft.load(saved)
        ui.notify("组合已保存", type="positive")
        await self.repaint()

    async def delete_definition(self):
        await self.controller.call("sequence.delete", sequence_id=self.draft.sequence_id,
                                   expected_revision=self.draft.revision)
        self.flow_editor.reset()
        self.draft.reset()
        self.invalid_literals.clear()
        self.literal_text.clear()
        self.selected_node_id = None
        self.active_section = "flow"
        self.node_section = "task"
        await self.repaint()

    async def start(self):
        if self.invalid_literals:
            raise TaskError("INPUT_INVALID", "请填写有效的 JSON 固定值")
        if self.draft.needs_save():
            await self.save()
        run = await self.controller.call("sequence.start" if self.execution else "sequence.trial", sequence_id=self.draft.sequence_id,
                                         request_id=str(uuid4()), inputs=self.draft.launch_inputs(),
                                         node_inputs={nid: view.task_values() for nid, view in self.startup_views.items()
                                                      if view.task_values()},
                                         node_step_inputs={nid: view.step_values() for nid, view in self.startup_views.items()
                                                           if view.step_values()})
        self.draft.selected_run_id = run["sequence_run_id"]
        self.active_section = "debug"
        await self.repaint()

    async def refresh_progress(self):
        area = self.progress_area
        if area is None or area.is_deleted:
            return
        origin = self.identity()
        runs = await self.controller.call("sequence.run.list", sequence_id=self.draft.sequence_id)
        if self.identity() != origin or area is not self.progress_area or area.is_deleted:
            return
        runs = [run for run in runs if run['snapshot'].get('mode') == 'TRIAL'
                and run.get('sequence_id') == self.draft.sequence_id]
        snapshot = (json.dumps(runs, sort_keys=True, default=str), self.draft.selected_run_id)
        if snapshot == self.progress_snapshot:
            return
        area.clear()
        with area:
            ui.label('组合调试').classes('text-lg font-semibold')
            if not runs:
                ui.label('当前组合暂无调试记录').classes('text-sm text-gray-500')
            else:
                options = {run['sequence_run_id']: LABELS.get(run['status'], run['status']) + ' · ' + run['created_at'][:19]
                           for run in runs}
                selected = self.draft.selected_run_id if self.draft.selected_run_id in options else runs[0]['sequence_run_id']
                self.draft.selected_run_id = selected
                async def select(event):
                    self.draft.selected_run_id = event.value
                    await self.refresh_progress()
                ui.select(options, value=selected, label='调试记录', on_change=select).classes('w-full')
                async def deleted(run_id):
                    if self.draft.selected_run_id == run_id:
                        self.draft.selected_run_id = None
                from taskweave.desktop.components.sequence_execution import SequenceExecution
                view = SequenceExecution(self.controller, self.button, self.refresh_progress, identity=lambda: (self.identity(), self.draft.selected_run_id),
                                         tasks=self.tasks, environments=self.environments, trial=True, on_deleted=deleted)
                await view.render(next(run for run in runs if run['sequence_run_id'] == selected))
        self.progress_snapshot = (snapshot[0], self.draft.selected_run_id)
