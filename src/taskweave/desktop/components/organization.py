"""Reusable local category management dialog."""

from nicegui import ui


class CategoryManager:
    def __init__(self, controller, button, repaint, after_change=None):
        self.controller, self.button, self.repaint = controller, button, repaint
        self.after_change = after_change

    async def _refresh_after_change(self, dialog):
        if self.after_change:
            await self.after_change()
        else:
            await self.repaint()
        dialog.close()

    def render_button(self):
        self.button("管理分类", self.open)

    async def open(self):
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-xl"):
            ui.label("管理分类").classes("text-lg font-medium")
            area = ui.column().classes("w-full gap-2")
            name = ui.input("新分类名称").classes("w-full")

            async def refresh():
                categories = await self.controller.call("organization.category.list")
                area.clear()
                with area:
                    if not categories:
                        ui.label("暂无分类")
                    for category in categories:
                        with ui.row().classes("w-full items-center"):
                            edit = ui.input(value=category["name"]).classes("grow")

                            async def rename(item=category, field=edit):
                                await self.controller.call("organization.category.rename", category_id=item["category_id"], name=field.value)
                                await self._refresh_after_change(dialog)

                            async def delete(item=category):
                                await self.controller.call("organization.category.delete", category_id=item["category_id"])
                                await self._refresh_after_change(dialog)

                            self.button("重命名", rename)
                            self.button("删除并移到未分类", delete)

            async def create():
                await self.controller.call("organization.category.create", name=name.value or "")
                await self._refresh_after_change(dialog)

            await refresh()
            with ui.row().classes("w-full gap-2"):
                self.button("新建分类", create, primary=True)
                ui.button("关闭", on_click=dialog.close).props("outline")
        dialog.open()
