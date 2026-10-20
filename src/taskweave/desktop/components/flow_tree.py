"""Compact nested task-flow navigation; action buttons retain the step editor."""

from nicegui import ui


class FlowTree:
    def __init__(self, steps, selected_step_id, on_action, on_control, on_move, on_delete_control):
        self.names = {step["step_id"]: step["name"] for step in steps}
        self.selected_step_id = selected_step_id
        self.on_action, self.on_control, self.on_move = on_action, on_control, on_move
        self.on_delete_control = on_delete_control

    def render(self, flow):
        self._node(flow["root"], 0)

    def _node(self, node, depth):
        kind = node["kind"]
        if kind == "sequence":
            for child in node["children"]:
                self._node(child, depth)
            return
        indent = min(depth, 5) * 12
        if kind == "action":
            with ui.row().classes("w-full items-center gap-1").style(f"padding-left:{indent}px"):
                control = ui.button(self.names.get(node["step_id"], "步骤"),
                                    on_click=lambda sid=node["step_id"]: self.on_action(sid)).props("flat dense no-caps").classes(
                                        "grow justify-start text-left tw-step-list-item")
                if node["step_id"] == self.selected_step_id:
                    control.classes("tw-selected")
                ui.button(icon="drive_file_move", on_click=lambda nid=node["id"]: self.on_move(nid)).props(
                    "flat dense round size=sm title=移动到其他分组")
            return
        label = {"if": "条件分支", "foreach": "遍历列表", "loop": "条件循环"}[kind]
        with ui.expansion(label, icon={"if": "alt_route", "foreach": "repeat", "loop": "autorenew"}[kind],
                          value=True).classes("w-full tw-flow-control").style(f"margin-left:{indent}px"):
            with ui.row().classes("w-full justify-end"):
                ui.button("设置", on_click=lambda nid=node["id"]: self.on_control(nid)).props("flat dense")
                ui.button(icon="drive_file_move", on_click=lambda nid=node["id"]: self.on_move(nid)).props(
                    "flat dense round size=sm title=移动控制块")
                ui.button(icon="delete_outline", on_click=lambda nid=node["id"]: self.on_delete_control(nid)).props(
                    "flat dense round size=sm title=删除空控制块")
            if kind == "if":
                ui.label("满足条件").classes("text-xs text-gray-500")
                self._node(node["then"], depth + 1)
                ui.label("其他情况").classes("text-xs text-gray-500")
                self._node(node["else"], depth + 1)
            else:
                self._node(node["body"], depth + 1)
