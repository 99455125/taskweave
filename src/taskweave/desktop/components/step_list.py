"""Step selection and task-step list actions for the editor page."""

from nicegui import ui
from taskweave.core.validation import TaskError


def reordered_ids(values, index, delta):
    target = index + delta
    if not 0 <= index < len(values) or not 0 <= target < len(values):
        return None
    result = list(values)
    result[index], result[target] = result[target], result[index]
    return result


def move_controls(steps, controls, index, target, container):
    moving, adjacent = controls[index], controls[target]
    moving.move(container, target)
    steps.insert(target, steps.pop(index))
    controls.insert(target, controls.pop(index))
    for position, (step, control) in enumerate(zip(steps, controls), 1):
        control.text = f"{position}. {step['name']}"
        control.update()
    return moving, adjacent


class StepList:
    def __init__(self, controller, button, task_id, selected_step_id, identity,
                 save_editor, navigate_step, select_step, paint, animate, finish_animation):
        self.controller, self.button = controller, button
        self.task_id, self.selected_step_id, self.identity = task_id, selected_step_id, identity
        self.save_editor, self.navigate_step, self.select_step = save_editor, navigate_step, select_step
        self.paint, self.animate, self.finish_animation = paint, animate, finish_animation
        self.selected_control = None
        self.move_menu_items = (None, None)

    def bind_move_menu_items(self, move_up, move_down):
        self.move_menu_items = (move_up, move_down)

    def _sync_move_menu(self, index, count):
        self.actions["can_move_up"] = index > 0
        self.actions["can_move_down"] = 0 <= index < count - 1
        for item, enabled in zip(self.move_menu_items, (self.actions["can_move_up"], self.actions["can_move_down"])):
            if item is not None and not item.is_deleted:
                item.set_enabled(enabled)

    async def render(self, steps, catalog, toolbar, list_area):
        controls = []
        selected_id = self.selected_step_id()
        identity = self.identity()
        with list_area:
            for index, step in enumerate(steps):
                control = self.button(
                    f"{index + 1}. {step['name']}",
                    lambda item=step: self.navigate_step(item["step_id"]), flat=True,
                )
                controls.append(control)
                validated = step["validation_state"] == "VALIDATED"
                control.props("icon-right=check" if validated else "")
                control.classes("tw-step-list-item w-full justify-start text-left")
                control.classes(add="tw-step-list-validated" if validated else "")
                if step["step_id"] == selected_id:
                    self.selected_control = control
                    control.classes("tw-selected")
                    control.props("icon-right=check_circle" if validated else "icon-right=radio_button_checked")

        async def add():
            await self.save_editor()
            if self.identity() != identity:
                return
            current = await self.controller.call("step.list", task_id=self.task_id())
            if self.identity() != identity:
                return
            previous = current[-1]["capabilities"] if current else []
            selected_plugins = {cap.split(".", 1)[0] for cap in previous}
            available = ([item["id"] for item in catalog["actions"] + catalog["tools"]]
                         + catalog["result_handlers"] + catalog["resource_providers"])
            inherited = sorted(set(previous) | {cap for cap in available if cap.split(".", 1)[0] in selected_plugins})
            saved = await self.controller.call(
                "step.save", task_id=self.task_id(),
                document={"name": "新步骤", "step_content": "async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n", "capabilities": inherited},
            )
            if self.identity() == identity:
                self.select_step(saved["step_id"])
                await self.paint()

        with toolbar:
            self.button("", add, flat=True, icon="add").props("aria-label=添加步骤 title=添加步骤").classes("tw-add-step-button")

        async def reorder(delta):
            await self.save_editor()
            if self.identity() != identity:
                return
            current = await self.controller.call("step.list", task_id=self.task_id())
            if self.identity() != identity:
                return
            ids = [step["step_id"] for step in current]
            index = ids.index(selected_id)
            updated_ids = reordered_ids(ids, index, delta)
            if updated_ids is None:
                return
            target = index + delta
            moving, adjacent = controls[index], controls[target]
            await self.controller.call("step.reorder", task_id=self.task_id(), step_ids=updated_ids)
            if self.identity() != identity:
                return
            await self.animate(moving, adjacent)
            if self.identity() != identity:
                return
            moving, adjacent = move_controls(current, controls, index, target, list_area)
            steps[:] = current
            self._sync_move_menu(target, len(current))
            await self.finish_animation(moving, adjacent)
            return True

        async def delete():
            with ui.dialog() as dialog, ui.card():
                ui.label("移除当前步骤？其他步骤若引用它，将阻止删除。")
                with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                    ui.button("取消", on_click=lambda: dialog.submit(False))
                    ui.button("移除", on_click=lambda: dialog.submit(True))
            if not await dialog or self.identity() != identity:
                return
            ids = [step["step_id"] for step in steps]
            index = ids.index(selected_id)
            await self.controller.call("step.delete", step_id=selected_id)
            if self.identity() != identity:
                return
            remaining = [step_id for step_id in ids if step_id != selected_id]
            self.select_step(remaining[index - 1] if index > 0 else (remaining[0] if remaining else None))
            await self.paint()

        async def confirm_all():
            feedback_client = ui.context.client

            async def repaint_if_current(expected_identity):
                if self.identity() != expected_identity:
                    return False
                await self.paint()
                current_identity = self.identity()
                accepted = (
                    len(expected_identity) >= 4
                    and current_identity[:3] == expected_identity[:3]
                    and isinstance(expected_identity[-1], int)
                    and current_identity[-1] == expected_identity[-1] + 1
                )
                return accepted

            try:
                await self.save_editor()
            except TaskError as exc:
                if self.identity() != identity:
                    return
                ui.notify(f"批量确认未执行：当前步骤保存失败，草稿已保留：{exc}", type="negative")
                raise
            if self.identity() != identity:
                return
            current = await self.controller.call("step.list", task_id=self.task_id())
            if self.identity() != identity:
                return
            invalid = []

            def append_failure(index, candidate, reason):
                invalid.append({"index": index, "step": candidate, "reason": reason})

            for index, candidate in enumerate(current, 1):
                try:
                    validation = await self.controller.call("step.validate", step_id=candidate["step_id"])
                except TaskError as exc:
                    if self.identity() != identity:
                        return
                    append_failure(index, candidate, str(exc))
                    continue
                if self.identity() != identity:
                    return
                if not validation["valid"]:
                    diagnostics = [item for item in validation.get("diagnostics", []) if item.get("severity") == "error"]
                    reason = "；".join(item.get("message") or item.get("code", "") for item in diagnostics)
                    append_failure(index, candidate, reason or "校验未通过")
            if invalid:
                first = invalid[0]
                self.select_step(first["step"]["step_id"])
                selected_identity = self.identity()
                if not await repaint_if_current(selected_identity):
                    return
                with feedback_client.layout:
                    with ui.dialog() as dialog, ui.card():
                        ui.label("批量确认未执行")
                        ui.label("以下步骤未通过校验，未执行任何确认：")
                        for failure in invalid:
                            ui.label(
                                f"第 {failure['index']} 步「{failure['step']['name']}」校验失败：{failure['reason']}"
                            )
                        ui.button("关闭", on_click=dialog.close).props("outline")
                    dialog.open()
                with feedback_client:
                    ui.notify(f"批量确认未执行：{len(invalid)} 步校验失败。", type="negative")
                return

            for index, candidate in enumerate(current, 1):
                if candidate["validation_state"] != "VALIDATED":
                    try:
                        await self.controller.call("step.confirm.manual", step_id=candidate["step_id"], expected_hash=candidate["content_hash"], environment_id=None)
                    except TaskError as exc:
                        if self.identity() != identity:
                            return
                        refreshed = await self.controller.call("step.list", task_id=self.task_id())
                        if self.identity() != identity:
                            return
                        confirmed_ids = {item["step_id"] for item in current}
                        confirmed_count = sum(
                            item["validation_state"] == "VALIDATED"
                            for item in refreshed if item["step_id"] in confirmed_ids
                        )
                        self.select_step(candidate["step_id"])
                        selected_identity = self.identity()
                        if not await repaint_if_current(selected_identity):
                            return
                        with feedback_client:
                            ui.notify(
                                f"批量确认已中止：已确认 {confirmed_count}/{len(current)} 步。"
                                f"第 {index} 步「{candidate['name']}」确认失败：{exc}",
                                type="negative",
                            )
                        return
                    if self.identity() != identity:
                        return
            if not await repaint_if_current(identity):
                return
            with feedback_client:
                ui.notify("全部步骤已确认", type="positive")

        selected_index = next((i for i, item in enumerate(steps) if item["step_id"] == selected_id), -1)
        self.actions = {
            "move_up": lambda: reorder(-1),
            "move_down": lambda: reorder(1),
            "delete": delete,
            "confirm_all": confirm_all,
            "can_move_up": selected_index > 0,
            "can_move_down": selected_index >= 0 and selected_index < len(steps) - 1,
        }
        return self.selected_control
