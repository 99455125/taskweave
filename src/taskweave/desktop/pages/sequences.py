"""Task sequence editor and durable execution progress page."""

import json
from uuid import uuid4

from nicegui import ui

from taskweave.core.validation import TaskError
from taskweave.desktop.pages.base import Page
from taskweave.presentation.sequences import SequenceDraft


LABELS = {"READY": "就绪", "RUNNING": "执行中", "WAITING_INPUT": "等待输入",
          "PAUSED": "已暂停", "BLOCKED": "需要处理", "SUCCEEDED": "成功",
          "CANCELLED": "已取消", "DELETING": "清理中", "PENDING": "待执行"}


class SequencesPage(Page):
    def __init__(self, controller, button, repaint, *, identity):
        self.controller, self.button, self.repaint = controller, button, repaint
        self.identity = identity
        self.draft = SequenceDraft()
        self.tasks = []
        self.steps = {}
        self.flows = {}
        self.environments = []
        self.definitions = []
        self.progress_area = None
        self.timer = None
        self.invalid_literals = set()

    def dispose(self):
        if self.timer:
            self.timer.cancel()
            self.timer = None
        self.progress_area = None

    async def _load(self):
        self.tasks = await self.controller.call("task.list")
        self.environments = await self.controller.call("environment.list")
        self.definitions = await self.controller.call("sequence.list")
        self.steps = {task["task_id"]: await self.controller.call("step.list", task_id=task["task_id"])
                      for task in self.tasks}
        self.flows = {task["task_id"]: await self.controller.call("task.flow.get", task_id=task["task_id"])
                      for task in self.tasks}

    def _task_name(self, task_id):
        return next((task["name"] for task in self.tasks if task["task_id"] == task_id), "已删除任务")

    async def render(self):
        await self._load()
        with ui.row().classes("w-full justify-between items-center"):
            ui.label("任务组合").classes("text-xl font-medium")
            self.button("新建组合", self.new, primary=True, icon="add")
        with ui.row().classes("w-full gap-4 items-start flex-wrap"):
            with ui.column().classes("tw-panel w-64 gap-2"):
                ui.label("已保存组合").classes("font-medium")
                for definition in self.definitions:
                    self.button(definition["name"], lambda item=definition: self.open_definition(item), flat=True)
                if not self.definitions:
                    ui.label("暂无组合").classes("text-gray-500")
            with ui.column().classes("tw-panel grow min-w-80 gap-4"):
                await self._render_editor()
        self.progress_area = ui.column().classes("tw-panel w-full gap-3")
        await self.refresh_progress()
        origin = self.identity()
        async def poll():
            if self.identity() == origin and self.progress_area:
                await self.refresh_progress()
        self.timer = ui.timer(1, poll)

    async def new(self):
        self.draft.reset()
        self.invalid_literals.clear()
        await self.repaint()

    async def open_definition(self, definition):
        self.draft.load(definition)
        self.invalid_literals.clear()
        await self.repaint()

    async def _render_editor(self):
        draft = self.draft
        ui.label("编排任务").classes("text-lg font-semibold")
        ui.input("组合名称", value=draft.name, on_change=lambda event: setattr(draft, "name", event.value or "")).classes("w-full")
        ui.input("说明", value=draft.description, on_change=lambda event: setattr(draft, "description", event.value or "")).classes("w-full")
        ui.textarea("组合启动输入 Schema（JSON）", value=draft.input_schema_text,
                    on_change=lambda event: setattr(draft, "input_schema_text", event.value or ""))\
            .props("outlined autogrow").classes("w-full")
        task_options = {task["task_id"]: task["name"] for task in self.tasks}
        with ui.row().classes("w-full items-end gap-2"):
            chooser = ui.select(task_options, label="添加任务", with_input=True).classes("min-w-60 grow")
            self.button("添加到末尾", lambda: self.add_node(chooser.value), icon="add")
        if not draft.nodes:
            ui.label("选择任务后按顺序添加。每个节点可以配置启动输入和前序输出映射。")\
                .classes("text-gray-500")
        for index, node in enumerate(draft.nodes):
            with ui.card().classes("w-full gap-3"):
                with ui.row().classes("w-full justify-between items-center"):
                    ui.label(f"{index + 1}. {self._task_name(node['task_id'])}").classes("font-medium")
                    with ui.row().classes("gap-1"):
                        if index:
                            self.button("上移", lambda i=index: self.move_node(i, -1), flat=True)
                        if index < len(draft.nodes) - 1:
                            self.button("下移", lambda i=index: self.move_node(i, 1), flat=True)
                        self.button("移除", lambda i=index: self.remove_node(i), flat=True)
                environment_options = {"": "默认环境"} | {
                    item["environment_id"]: item["name"] for item in self.environments}
                ui.select(environment_options, value=node["environment_id"] or "", label="执行环境",
                          on_change=lambda event, current=node: current.__setitem__("environment_id", event.value or None))\
                    .classes("w-full")
                task = next((item for item in self.tasks if item["task_id"] == node["task_id"]), None)
                if task:
                    schema = json.loads(task["input_schema_json"])
                    await self._target_fields(index, node, node["inputs"], schema, "任务输入", None)
                for step in self.steps.get(node["task_id"], []):
                    available = {key: spec for key, spec in step["input_schema"].get("properties", {}).items()
                                 if key not in step["bindings"]}
                    if available:
                        sources = node["step_inputs"].setdefault(step["step_id"], {})
                        schema = {**step["input_schema"], "properties": available}
                        await self._target_fields(index, node, sources, schema,
                                                  f"步骤输入 · {step['name']}", step["step_id"])
        with ui.row().classes("gap-2"):
            self.button("保存组合", self.save, primary=True)
            if draft.sequence_id:
                self.button("删除定义", self.delete_definition, flat=True)
        ui.separator()
        ui.label("启动组合").classes("text-lg font-semibold")
        ui.textarea("启动输入（JSON 对象）", value=draft.launch_inputs_text,
                    on_change=lambda event: setattr(draft, "launch_inputs_text", event.value or ""))\
            .props("outlined autogrow").classes("w-full")
        self.button("执行整个组合", self.start, primary=True, icon="play_arrow")

    async def _target_fields(self, index, node, sources, schema, title, step_id):
        ui.label(title).classes("font-medium text-sm")
        required = set(schema.get("required", []))
        for key, spec in schema.get("properties", {}).items():
            with ui.column().classes("w-full gap-1 border-l-2 pl-3"):
                caption = f"{key}{' *' if key in required else ''}"
                if isinstance(spec, dict) and spec.get("description"):
                    caption += f" · {spec['description']}"
                ui.label(caption).classes("text-sm")
                source = sources.get(key)
                kind = source["kind"] if source else ""
                options = {"": "执行时填写", "literal": "固定值", "sequence": "组合启动输入", "output": "前序任务输出"}
                choice = ui.select(options, value=kind, label="取值方式").classes("w-full")
                async def change_kind(event, mapping=sources, field=key):
                    selected = event.value
                    if selected == "literal":
                        mapping[field] = {"kind": "literal", "value": None}
                    elif selected == "sequence":
                        mapping[field] = {"kind": "sequence", "pointer": ""}
                    elif selected == "output":
                        mapping[field] = {"kind": "output", "node_id": "", "step_id": "",
                                          "output": "data", "pointer": ""}
                    else:
                        mapping.pop(field, None)
                    await self.repaint()
                choice.on_value_change(change_kind)
                if kind == "literal":
                    token = (node["node_id"], step_id, key)
                    def literal_changed(event, mapping=sources, field=key, marker=token):
                        try:
                            mapping[field]["value"] = json.loads(event.value)
                            self.invalid_literals.discard(marker)
                        except (ValueError, TypeError):
                            self.invalid_literals.add(marker)
                    ui.input("JSON 值", value=json.dumps(source["value"], ensure_ascii=False),
                             on_change=literal_changed).classes("w-full")
                elif kind == "sequence":
                    ui.input("启动输入路径，例如 /customer/id", value=source["pointer"],
                             on_change=lambda event, item=source: item.__setitem__("pointer", event.value or ""))\
                        .classes("w-full")
                elif kind == "output":
                    predecessors = {}
                    for preceding in self.draft.nodes[:index]:
                        for prior_step in self.steps.get(preceding["task_id"], []):
                            predecessors[preceding["node_id"] + "|" + prior_step["step_id"]] = (
                                f"{self._task_name(preceding['task_id'])} · {prior_step['name']}")
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
                    loop_options = {}
                    def collect_loops(flow_node, task_name):
                        if flow_node["kind"] in {"foreach", "loop"}:
                            loop_options[flow_node["id"]] = f"{task_name} · {flow_node['id']}"
                        children = (flow_node["children"] if flow_node["kind"] == "sequence" else
                                    [flow_node["then"], flow_node["else"]] if flow_node["kind"] == "if" else
                                    [flow_node["body"]] if flow_node["kind"] in {"foreach", "loop"} else [])
                        for child in children:
                            collect_loops(child, task_name)
                    for preceding in self.draft.nodes[:index]:
                        flow = self.flows.get(preceding["task_id"])
                        if flow:
                            collect_loops(flow["root"], self._task_name(preceding["task_id"]))
                    if loop_options:
                        async def choose_projection_loop(event, item=source):
                            if event.value:
                                item.update(loop_node_id=event.value, item_pointer=item.get("item_pointer", ""), pointer="")
                            else:
                                item.pop("loop_node_id", None)
                                item.pop("item_pointer", None)
                            await self.repaint()
                        ui.select({"": "使用完整结果"} | loop_options,
                                  value=source.get("loop_node_id", ""), label="逐轮投影所属循环",
                                  on_change=choose_projection_loop)\
                            .classes("w-full")
                        if source.get("loop_node_id"):
                            ui.input("每轮结果字段（例如 /id）", value=source.get("item_pointer", ""),
                                     on_change=lambda event, item=source: item.__setitem__("item_pointer", event.value or ""))\
                                .classes("w-full")

    async def add_node(self, task_id):
        self.draft.add(task_id)
        await self.repaint()

    async def move_node(self, index, direction):
        self.draft.move(index, direction)
        await self.repaint()

    async def remove_node(self, index):
        self.draft.remove(index)
        await self.repaint()

    async def save(self):
        if self.invalid_literals:
            raise TaskError("INPUT_INVALID", "请填写有效的 JSON 固定值")
        saved = await self.controller.call("sequence.save", **self.draft.payload())
        self.draft.load(saved)
        ui.notify("组合已保存", type="positive")
        await self.repaint()

    async def delete_definition(self):
        await self.controller.call("sequence.delete", sequence_id=self.draft.sequence_id,
                                   expected_revision=self.draft.revision)
        self.draft.reset()
        await self.repaint()

    async def start(self):
        if self.invalid_literals:
            raise TaskError("INPUT_INVALID", "请填写有效的 JSON 固定值")
        if self.draft.needs_save():
            await self.save()
        run = await self.controller.call("sequence.start", sequence_id=self.draft.sequence_id,
                                         request_id=str(uuid4()), inputs=self.draft.launch_inputs())
        self.draft.selected_run_id = run["sequence_run_id"]
        await self.refresh_progress()

    async def refresh_progress(self):
        area = self.progress_area
        if area is None or area.is_deleted:
            return
        area.clear()
        with area:
            ui.label("组合运行").classes("text-lg font-semibold")
            runs = await self.controller.call("sequence.run.list")
            if runs:
                options = {run["sequence_run_id"]: f"{run['snapshot']['name']} · {LABELS.get(run['status'], run['status'])} · {run['created_at'][:19]}" for run in runs}
                selected = self.draft.selected_run_id if self.draft.selected_run_id in options else runs[0]["sequence_run_id"]
                self.draft.selected_run_id = selected
                async def select_run(event):
                    self.draft.selected_run_id = event.value
                    await self.refresh_progress()
                ui.select(options, value=selected, label="运行记录", on_change=select_run).classes("w-full")
                run = next(item for item in runs if item["sequence_run_id"] == selected)
                ui.label(f"状态：{LABELS.get(run['status'], run['status'])}")
                if run["error_code"]:
                    ui.label(f"原因：{run['error_code']}").classes("text-red-700")
                for member in run["nodes"]:
                    with ui.row().classes("w-full items-center justify-between border-b py-1"):
                        ui.label(f"{member['position'] + 1}. {self._task_name(member['task_id'])} · {LABELS.get(member['status'], member['status'])}")
                        if member["run_id"]:
                            self.button("查看执行", lambda item=member: self.show_child(item["run_id"]), flat=True)
                await self._run_controls(run)
            else:
                ui.label("保存并执行组合后，进度会显示在这里。").classes("text-gray-500")

    async def show_child(self, run_id):
        child = await self.controller.call("run.get", run_id=run_id)
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-3xl"):
            ui.label(f"任务执行 · {child['status']}").classes("text-lg")
            ui.code(json.dumps(child, ensure_ascii=False, indent=2, default=str)).classes("max-h-96 overflow-auto")
            ui.button("关闭", on_click=dialog.close)
        dialog.open()

    async def _run_controls(self, run):
        sequence_run_id = run["sequence_run_id"]
        status = run["status"]
        with ui.row().classes("gap-2 flex-wrap"):
            if status in {"READY", "RUNNING"}:
                self.button("暂停", lambda: self._control("sequence.pause", sequence_run_id))
                self.button("取消", lambda: self._control("sequence.cancel", sequence_run_id))
            if status == "PAUSED" or (status == "BLOCKED" and run["error_code"] in {
                "SEQUENCE_CHILD_INTERRUPTED", "RUN_CONFIG_CHANGED", "ENVIRONMENT_CHANGED", "PLUGIN_VERSION_MISMATCH"}):
                self.button("继续", lambda: self._control("sequence.continue", sequence_run_id), primary=True)
            if status == "WAITING_INPUT":
                self.button("补充输入", lambda: self._inputs_dialog(run), primary=True)
            if status == "BLOCKED" and run["current_node_id"]:
                member = next(item for item in run["nodes"] if item["node_id"] == run["current_node_id"])
                if member["run_id"]:
                    self.button("重试步骤", lambda: self._retry_dialog(run, member))
                    self.button("核对不确定结果", lambda: self._reconcile_dialog(run, member))
            if status not in {"READY", "RUNNING", "DELETING"}:
                self.button("删除运行记录", lambda: self._delete_run(sequence_run_id), flat=True)

    async def _control(self, operation, sequence_run_id):
        await self.controller.call(operation, sequence_run_id=sequence_run_id, command_id=str(uuid4()))
        await self.refresh_progress()

    async def _inputs_dialog(self, run):
        member = next(item for item in run["nodes"] if item["node_id"] == run["current_node_id"])
        request = await self.controller.run_request(member["run_id"])
        waiting = request.get("waiting_input")
        if not waiting:
            raise TaskError("INPUT_REQUEST_STALE", "补参请求已变化，请刷新")
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-2xl"):
            ui.label("补充当前任务输入").classes("text-lg")
            ui.label("必填：" + "、".join(waiting["missing"]))
            values = ui.textarea("JSON 输入", value=json.dumps(waiting["values"], ensure_ascii=False, indent=2))\
                .props("outlined autogrow").classes("w-full")
            async def submit():
                supplied = json.loads(values.value)
                await self.controller.call("sequence.run.inputs", sequence_run_id=run["sequence_run_id"],
                    command_id=str(uuid4()), inputs=supplied, expected_input_id=waiting["id"])
                dialog.close()
                await self.refresh_progress()
            self.button("提交并继续", submit, primary=True)
            ui.button("取消", on_click=dialog.close).props("outline")
        dialog.open()

    async def _retry_dialog(self, run, member):
        steps = await self.controller.call("step.list", task_id=member["task_id"])
        child = await self.controller.call("run.get", run_id=member["run_id"])
        from taskweave.core.task_flow import is_linear_flow
        controlled = not is_linear_flow(json.loads(child["definition_json"])["flow"])
        with ui.dialog() as dialog, ui.card():
            ui.label("重试失败动作" if controlled else "从指定步骤重试").classes("text-lg")
            if controlled:
                names = {step["step_id"]: step["name"] for step in steps}
                failures = {attempt["execution_path"]: (
                    names.get(attempt["step_id"], attempt["step_id"]) + " · " +
                    " / ".join(f"第 {int(part)+1} 轮" for part in attempt["execution_path"].split('/') if part.isdigit()))
                    for attempt in child["attempts"] if attempt["valid"] and attempt["status"] == "FAILED"}
                if not failures:
                    ui.label("控制条件或循环上限失败，请修改流程后新建执行。")
            else:
                failures = {step["step_id"]: step["name"] for step in steps}
            choice = ui.select(failures, value=next(reversed(failures), None),
                               label="失败实例" if controlled else "重试步骤")
            async def submit():
                await self.controller.call("sequence.run.retry", sequence_run_id=run["sequence_run_id"],
                    command_id=str(uuid4()),
                    **({"retry_execution_path": choice.value} if controlled else {"retry_step_id": choice.value}))
                dialog.close()
                await self.refresh_progress()
            if failures:
                self.button("重试", submit, primary=True)
        dialog.open()

    async def _reconcile_dialog(self, run, member):
        child = await self.controller.call("run.get", run_id=member["run_id"])
        attempts = [item for item in child.get("attempts", []) if item["status"] == "UNKNOWN"
                    or (item["status"] == "FAILED" and item.get("effect_state") in {"SUCCEEDED", "UNKNOWN"})]
        if not attempts:
            raise TaskError("RECONCILIATION_INVALID", "当前没有待核对的步骤")
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-2xl"):
            ui.label("核对外部执行结果").classes("text-lg")
            choice = ui.select({item["attempt_id"]: item["step_id"] for item in attempts},
                               value=attempts[0]["attempt_id"], label="步骤尝试")
            decision = ui.select({"completed": "已完成", "not_completed": "未完成"},
                                 value="completed", label="核对结论")
            evidence = ui.textarea("核对依据（文字）").classes("w-full")
            async def submit():
                await self.controller.call("sequence.run.reconcile", sequence_run_id=run["sequence_run_id"],
                    attempt_id=choice.value, decision=decision.value,
                    evidence={"note": evidence.value or ""}, command_id=str(uuid4()))
                dialog.close()
                await self.refresh_progress()
            self.button("保存核对", submit, primary=True)
        dialog.open()

    async def _delete_run(self, sequence_run_id):
        await self.controller.call("sequence.run.delete", sequence_run_id=sequence_run_id)
        if self.draft.selected_run_id == sequence_run_id:
            self.draft.selected_run_id = None
        await self.refresh_progress()
