"""Forms for branch predicates, list sources and loop state mappings."""

import json

from nicegui import ui

from taskweave.core.validation import TaskError


class OperandForm:
    def __init__(self, value, steps, controls, label="值", *, on_change=None, required=False, sequence_nodes=None):
        self.required = required
        self.sequence_nodes = sequence_nodes
        ref = value.get("ref", {}) if isinstance(value, dict) else {}
        source = ref.get("source", None if required and not value else "literal")
        with ui.column().classes("tw-flow-operand w-full gap-2") as root:
            self.root = root
            self.label = ui.label(label).classes("text-xs font-medium")
            source_options = ({"literal": "固定值", "task": "组合启动输入", "node": "任务输出", "loop": "循环变量", "branch": "分支公共输出"}
                              if sequence_nodes is not None else {"literal": "固定值", "task": "任务参数", "environment": "环境配置",
                                     "step": "步骤结果", "loop": "循环变量", "branch": "分支公共输出"})
            self.source = ui.select(source_options,
                                    value=source, label="来源").classes("w-full")
            self.literal = ui.input("固定值（文本或 JSON）", value=json.dumps(value.get("literal"), ensure_ascii=False)
                                    if "literal" in value else "null").classes("w-full")
            self.step = ui.select(steps, value=ref.get("step_id"), label="步骤").classes("w-full")
            self.task_node = ui.select({key: item['name'] for key, item in (sequence_nodes or {}).items()},
                                       value=ref.get('node_id') if source == 'node' else None, label='来源任务').classes('w-full')
            children = (sequence_nodes or {}).get(self.task_node.value, {}).get('steps', {})
            self.child_step = ui.select(children, value=ref.get('step_id') if source == 'node' else None, label='任务内步骤').classes('w-full')
            def change_task(event):
                self.child_step.set_options((sequence_nodes or {}).get(event.value, {}).get('steps', {}), value=None)
            self.task_node.on_value_change(change_task)
            self.node = ui.select(controls, value=ref.get("node_id"), label="控制块").classes("w-full")
            self.output = ui.input("输出名称", value=ref.get("output", "data")).classes("w-full")
            self.field = ui.select({"item": "当前项", "index": "当前索引", "state": "循环状态"},
                                   value=ref.get("field", "item"), label="循环变量").classes("w-full")
            self.pointer = ui.input("字段路径", value=ref.get("pointer", "")).classes("w-full")
            self.item_pointer = ui.input("逐轮投影路径（可选）", value=ref.get("item_pointer", "")).classes("w-full")
            self.loop_node = ui.select({nid: title for nid, title in controls.items() if title.startswith("循环")},
                                       value=ref.get("loop_node_id"), label="投影所属循环").classes("w-full")
            self.source.on_value_change(lambda _: self._visibility())
            self._visibility()
            if on_change:
                for control in (self.source, self.literal, self.step, self.node, self.output,
                                self.field, self.pointer, self.item_pointer, self.loop_node, self.task_node, self.child_step):
                    control.on_value_change(lambda _: on_change())

    def _visibility(self):
        source = self.source.value
        self.literal.set_visibility(source == "literal")
        self.step.set_visibility(source == "step")
        self.node.set_visibility(source in {"loop", "branch"})
        self.output.set_visibility(source in {"step", "branch", "node"})
        self.task_node.set_visibility(source == "node")
        self.child_step.set_visibility(source == "node")
        self.field.set_visibility(source == "loop")
        self.pointer.set_visibility(bool(source) and source != "literal")
        self.item_pointer.set_visibility(source == "step")
        self.loop_node.set_visibility(source == "step")

    def value(self):
        source = self.source.value
        if self.required and not source:
            raise TaskError("FORM_INVALID", "请选择公共输出的取值来源")
        if source == "literal":
            try:
                value = json.loads(self.literal.value)
            except (TypeError, ValueError):
                value = self.literal.value
            return {"literal": value}
        ref = {"source": source, "pointer": self.pointer.value or ""}
        if source == "step":
            ref.update(step_id=self.step.value, output=self.output.value or "data")
            if self.item_pointer.value:
                ref.update(item_pointer=self.item_pointer.value, loop_node_id=self.loop_node.value)
        elif source == "node":
            ref.update(node_id=self.task_node.value, step_id=self.child_step.value, output=self.output.value or "data")
        elif source == "loop":
            ref.update(node_id=self.node.value, field=self.field.value)
        elif source == "branch":
            ref.update(node_id=self.node.value, output=self.output.value)
        return {"ref": ref}


class ConditionForm:
    OPS = {"eq": "等于", "ne": "不等于", "gt": "大于", "gte": "大于等于", "lt": "小于",
           "lte": "小于等于", "contains": "包含", "exists": "存在", "empty": "为空",
           "all": "全部满足", "any": "任一满足", "not": "取反"}

    def __init__(self, value, steps, controls, *, on_change=None, sequence_nodes=None):
        self.steps, self.controls = steps, controls
        self.sequence_nodes = sequence_nodes
        self.on_change = None
        value = value or {"op": "eq", "left": {"literal": True}, "right": {"literal": True}}
        with ui.column().classes("tw-flow-predicate w-full gap-3"):
            self.op = ui.select(self.OPS, value=value.get("op", "eq"), label="条件").classes("w-full")
            with ui.column().classes("tw-flow-operands w-full") as self.operands_area:
                self.left = OperandForm(value.get("left", value.get("value", {"literal": None})), steps, controls, "左侧值", on_change=self._changed, sequence_nodes=sequence_nodes)
                self.right = OperandForm(value.get("right", {"literal": None}), steps, controls, "右侧值", on_change=self._changed, sequence_nodes=sequence_nodes)
            self.children_area = ui.column().classes("w-full gap-2")
            self.children = []
            existing = (value.get("conditions", []) if value.get("op") in {"all", "any"}
                        else [value.get("condition")] if value.get("op") == "not" else [])
            for child in existing:
                if child:
                    self._add(child)
            self.add_button = ui.button("添加子条件", on_click=lambda: self._add(None)).props("flat")
            self.op.on_value_change(lambda _: self._visibility())
            self.op.on_value_change(lambda _: self._changed())
            self._visibility()
        self.on_change = on_change

    def _changed(self):
        if self.on_change:
            self.on_change()

    def _add(self, value):
        with self.children_area:
            with ui.column().classes("w-full") as host:
                child = ConditionForm(value, self.steps, self.controls, on_change=self._changed, sequence_nodes=self.sequence_nodes)
                self.children.append(child)
                def remove():
                    self.children.remove(child)
                    host.delete()
                    self._changed()
                ui.button("移除此条件", on_click=remove).props("flat dense")
        self._changed()

    def _visibility(self):
        op = self.op.value
        self.operands_area.set_visibility(op not in {"all", "any", "not"})
        self.right.root.set_visibility(op not in {"exists", "empty"})
        self.children_area.set_visibility(op in {"all", "any", "not"})
        self.add_button.set_visibility(op in {"all", "any"})
        if op == "not" and not self.children:
            self._add(None)

    def value(self):
        op = self.op.value
        if op in {"all", "any"}:
            if not self.children:
                raise TaskError("FLOW_CONDITION_INVALID", "请添加子条件")
            return {"op": op, "conditions": [item.value() for item in self.children]}
        if op == "not":
            return {"op": op, "condition": self.children[0].value()}
        if op in {"exists", "empty"}:
            return {"op": op, "value": self.left.value()}
        return {"op": op, "left": self.left.value(), "right": self.right.value()}


class ControlForm:
    """One control form for inline editing and the compatibility dialog."""
    def __init__(self, node, steps, controls, *, on_change=None, sequence_nodes=None):
        self.branch = None
        if node['kind'] == 'if':
            from taskweave.desktop.components.branch_form import BranchForm
            self.branch = BranchForm(node, steps, controls, on_change=on_change, sequence_nodes=sequence_nodes)
            return
        self.node = node
        self.on_change = None
        self.condition = self.items = self.mode = self.limit = None
        self.mappings = []
        if node["kind"] == "loop":
            self.condition = ConditionForm(node.get("condition"), steps, controls, on_change=self._changed, sequence_nodes=sequence_nodes)
        if node["kind"] == "foreach":
            self.items = OperandForm(node["items"], steps, controls, "遍历的列表", on_change=self._changed, sequence_nodes=sequence_nodes)
            self.limit = ui.number("最多项数", value=node.get("max_items", 1000), min=1, max=10000).classes("w-full")
        if node["kind"] == "loop":
            self.mode = ui.select({"while": "满足条件时继续", "until": "满足条件时退出（至少一轮）"},
                             value=node["mode"], label="循环方式").classes("w-full")
            self.limit = ui.number("最多轮数", value=node.get("max_iterations", 100), min=1, max=10000).classes("w-full")
        if node["kind"] == "loop":
            for field, title in [("state_initial", "状态初始值"), ("state_update", "每轮状态更新")]:
                with ui.expansion(title, value=bool(node.get(field))).classes("w-full"):
                    area = ui.column().classes("w-full")
                    rows = []
                    def add_row(key="", value=None, *, field=field, area=area, rows=rows):
                        with area:
                            with ui.column().classes("w-full border rounded p-2") as row_host:
                                name = ui.input("状态变量", value=key)
                                name.on_value_change(lambda _: self._changed())
                                operand = OperandForm(value or {"literal": None}, steps, controls, on_change=self._changed, sequence_nodes=sequence_nodes)
                                record = (name, operand)
                                rows.append(record)
                                def remove():
                                    rows.remove(record)
                                    row_host.delete()
                                    self._changed()
                                ui.button("移除此映射", on_click=remove).props("flat dense")
                        self._changed()
                    for key, value in node.get(field, {}).items():
                        add_row(key, value)
                    ui.button("添加映射", on_click=lambda adder=add_row: adder()).props("flat")
                    self.mappings.append((field, rows))
        for control in (self.mode, self.limit):
            if control is not None:
                control.on_value_change(lambda _: self._changed())
        self.on_change = on_change

    def _changed(self):
        if self.on_change:
            self.on_change()

    def value(self):
        if self.branch is not None:
            return {key: value for key, value in self.branch.value().items() if key not in {'id', 'kind'}}
        if self.node["kind"] == "foreach":
            changes = {"items": self.items.value(), "max_items": int(self.limit.value)}
        else:
            changes = {"mode": self.mode.value, "condition": self.condition.value(),
                       "max_iterations": int(self.limit.value)}
        for field, rows in self.mappings:
            mapped = {}
            for row in rows:
                name = (row[0].value or "").strip()
                if not name or name in mapped:
                    raise TaskError("FORM_INVALID", "映射名称不能为空或重复")
                mapped[name] = row[1].value()
            changes[field] = mapped
        return changes


async def edit_control(node, steps, controls):
    """Return edited fields, or None if the dialog was cancelled."""
    with ui.dialog() as dialog, ui.card().classes("w-[min(92vw,760px)] max-h-[90vh] overflow-y-auto"):
        ui.label({"if": "设置条件分支", "foreach": "设置列表遍历", "loop": "设置条件循环"}[node["kind"]]).classes("text-lg font-semibold")
        form = ControlForm(node, steps, controls)
        def submit():
            try:
                dialog.submit(form.value())
            except (TaskError, TypeError, ValueError) as exc:
                ui.notify(str(exc), type="negative")
        with ui.row().classes("w-full justify-end"):
            ui.button("取消", on_click=lambda: dialog.submit(None)).props("flat")
            ui.button("保存设置", on_click=submit)
    dialog.open()
    return await dialog
