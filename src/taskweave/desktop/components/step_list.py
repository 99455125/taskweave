"""Step selection and task-step list actions for the editor page."""

from nicegui import ui
from taskweave.core.validation import TaskError
from taskweave.presentation.step_actions import StepActions, reordered_ids


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
        interaction = StepActions(self.controller.call, self.task_id(), selected_id, self.identity)
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
            result = await interaction.add(catalog)
            if result is not None:
                self.select_step(result.selected_step_id)
                await self.paint()

        with toolbar:
            self.button("", add, flat=True, icon="add").props("aria-label=添加步骤 title=添加步骤").classes("tw-add-step-button")

        async def reorder(delta):
            await self.save_editor()
            result = await interaction.reorder(delta)
            if result is None:
                return
            index, target = result.index, result.target
            moving, adjacent = controls[index], controls[target]
            await self.animate(moving, adjacent)
            if not interaction.is_current():
                return
            moving, adjacent = move_controls(result.steps, controls, index, target, list_area)
            steps[:] = result.steps
            self._sync_move_menu(target, len(steps))
            await self.finish_animation(moving, adjacent)
            return True

        async def delete():
            with ui.dialog() as dialog, ui.card():
                ui.label("移除当前步骤？其他步骤若引用它，将阻止删除。")
                with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                    ui.button("取消", on_click=lambda: dialog.submit(False))
                    ui.button("移除", on_click=lambda: dialog.submit(True))
            result = await interaction.delete(steps, confirmed=bool(await dialog))
            if result is not None:
                self.select_step(result.selected_step_id)
                await self.paint()

        async def confirm_all():
            feedback_client = ui.context.client

            async def repaint_if_current(expected_identity):
                if self.identity() != expected_identity:
                    return False
                await self.paint()
                return interaction.accepts_repaint(expected_identity)

            try:
                await self.save_editor()
            except TaskError as exc:
                if self.identity() != identity:
                    return
                ui.notify(f"批量确认未执行：当前步骤保存失败，草稿已保留：{exc}", type="negative")
                raise
            result = await interaction.confirm_all()
            if result is None:
                return
            if result.status == "invalid":
                invalid = result.failures
                self.select_step(result.selected_step_id)
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

            if result.status == "partial":
                failure = result.failures[0]
                self.select_step(result.selected_step_id)
                selected_identity = self.identity()
                if not await repaint_if_current(selected_identity):
                    return
                with feedback_client:
                    ui.notify(
                        f"批量确认已中止：已确认 {result.confirmed_count}/{result.total} 步。"
                        f"第 {failure['index']} 步「{failure['step']['name']}」确认失败：{failure['reason']}",
                        type="negative",
                    )
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
