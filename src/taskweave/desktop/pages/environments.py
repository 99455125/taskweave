"""Environment configuration and local defaults page."""

from nicegui import ui
from taskweave.desktop.pages.base import Page
from taskweave.presentation.environment import EnvironmentSession


class EnvironmentPage(Page):
    def __init__(self, controller, button, repaint, on_default_selected, on_deleted=None, page_identity=None):
        self.controller = controller
        self.button = button
        self.repaint = repaint
        self.on_default_selected = on_default_selected
        self.on_deleted = on_deleted or _noop
        self.page_identity = page_identity or (lambda: None)
        self.interaction = EnvironmentSession(lambda operation, **params: controller.call(operation, **params), self.page_identity)
        self.prepare_leave = None

    @property
    def selected_environment_id(self): return self.interaction.selected_environment_id
    @selected_environment_id.setter
    def selected_environment_id(self, value): self.interaction.selected_environment_id = value
    @property
    def search_query(self): return self.interaction.search_query
    @search_query.setter
    def search_query(self, value): self.interaction.search_query = value
    @property
    def _creating(self): return self.interaction.creating
    @_creating.setter
    def _creating(self, value): self.interaction.creating = value
    @property
    def _render_generation(self): return self.interaction.generation
    @_render_generation.setter
    def _render_generation(self, value): self.interaction.generation = value

    def view_identity(self): return self.interaction.view_identity()
    def form_identity(self): return self.interaction.form_identity()
    def _form_is_current(self, identity): return self.interaction.form_current(identity)
    def _view_is_current(self, identity): return self.interaction.view_current(identity)

    async def set_default_for_view(self, environment_id, identity, update_view):
        if not await self.interaction.set_default(environment_id, identity, self.controller.set_default_environment):
            return False
        await self.on_default_selected(environment_id)
        if not self._view_is_current(identity) or environment_id != self.selected_environment_id:
            return False
        update_view()
        return True

    async def save_environment(
        self, name, rows, *, environment_id=None, secret_refs=None, refresh=True,
        form_state=None, form_identity=None,
    ):
        result = await self.interaction.save_values(name, rows, environment_id=environment_id,
            secret_refs=secret_refs, form_identity=form_identity)
        if result.current:
            if form_state is not None:
                form_state['environment_id'] = result.saved['environment_id']
            if refresh:
                await self.repaint()
        return result.saved

    async def create_environment(self, *, expected_view=None, prepare_leave=None):
        if expected_view is not None and not self._view_is_current(expected_view):
            return False
        if prepare_leave is not None and not await prepare_leave():
            return False
        if not self.interaction.create(expected_view):
            return False
        await self.repaint()
        return True

    async def render(self):
        self.interaction.begin_render()
        render_generation = self._render_generation
        page_at_start = self.page_identity()
        ui.label("环境").classes("text-xl")
        environments = await self.controller.call("environment.list")
        default = await self.controller.default_environment()
        if page_at_start != self.page_identity() or render_generation != self._render_generation:
            return
        environments = sorted(environments, key=lambda item: (item["environment_id"] != default, item["name"]))
        selected = self.interaction.choose_initial(environments, default)
        self.interaction.mount(selected)
        draft = self.interaction.draft
        view_identity = self.view_identity()
        form_identity = self.form_identity()
        default_environment_id = [default]
        with ui.row().classes("tw-master-layout tw-secondary-layout"):
            with ui.column().classes("tw-panel tw-list-sidebar gap-3"):
                with ui.row().classes("tw-environment-sidebar-heading w-full items-center justify-between"):
                    ui.label("环境列表").classes("font-medium")
                    self.button("新建", lambda: begin_create(), primary=True)
                search = ui.input("搜索环境", value=self.search_query, placeholder="搜索环境名称").props(
                    "clearable debounce=200 prepend-icon=search"
                ).classes("w-full")
                environment_list = ui.column().classes("w-full gap-2")

                def render_environment_list():
                    self.search_query = search.value if isinstance(search.value, str) else self.search_query
                    query = self.search_query.strip().casefold()
                    visible = [item for item in environments if query in item["name"].casefold()]
                    environment_list.clear()
                    with environment_list:
                        if not visible:
                            ui.label("没有匹配的环境" if environments else "暂无环境").classes("text-sm text-gray-500")
                        for item in visible:
                            with ui.column().classes("tw-environment-list-item w-full rounded-lg border border-gray-200 p-2 gap-1" + (" tw-selected" if item["environment_id"] == self.selected_environment_id else "")):
                                self.button(item["name"], lambda current=item: open_existing(current["environment_id"]), flat=True).classes("tw-environment-name w-full justify-start text-left")
                                ui.badge("默认" if item["environment_id"] == default_environment_id[0] else "可用").props("color=green" if item["environment_id"] == default_environment_id[0] else "color=grey")

                async def prepare_leave():
                    decision_kind = self.interaction.leave_decision(form_identity)
                    if decision_kind == 'stay':
                        return False
                    if decision_kind == 'allow':
                        return True
                    with ui.dialog() as decision, ui.card().classes("tw-confirm-dialog"):
                        ui.label("环境有未保存的更改").classes("tw-confirm-title")
                        ui.label("切换前，可保存或丢弃本次更改。").classes("tw-confirm-description")
                        with ui.row().classes("tw-confirm-actions"):
                            ui.button("继续编辑", on_click=lambda: decision.submit("stay")).props("outline").classes("tw-confirm-cancel")
                            ui.button("丢弃更改", on_click=lambda: decision.submit("discard")).props("outline color=negative").classes("tw-confirm-danger")
                            ui.button("保存更改", on_click=lambda: decision.submit("save")).props("unelevated color=primary")
                    return await self.interaction.leave(form_identity, await decision)

                self.prepare_leave = prepare_leave

                async def begin_create():
                    await self.create_environment(expected_view=view_identity, prepare_leave=prepare_leave)

                async def open_existing(environment_id):
                    await self.open_environment(
                        environment_id, expected_view=view_identity, prepare_leave=prepare_leave,
                    )

                search.on_value_change(lambda _: render_environment_list())
                render_environment_list()

            with ui.column().classes("tw-content tw-environment-detail min-w-0 gap-3"):
                async def delete_selected():
                    if selected is None:
                        return
                    with ui.dialog() as confirmation, ui.card():
                        ui.label("删除环境“" + selected["name"] + "”？历史执行结果保留。")
                        with ui.row():
                            ui.button("取消", on_click=lambda: confirmation.submit(False)).props("outline")
                            ui.button("确认删除环境", on_click=lambda: confirmation.submit(True)).props("outline text-color=red-7")
                    if not await confirmation:
                        return
                    environment_id = selected["environment_id"]
                    await self.controller.call("environment.delete", environment_id=environment_id)
                    if environment_id == default:
                        await self.controller.set_default_environment(None)
                    await self.on_deleted(environment_id)
                    self.selected_environment_id = None
                    await self.repaint()

                with ui.row().classes("tw-environment-detail-heading w-full items-center justify-between gap-3 flex-wrap"):
                    ui.label("环境详情").classes("text-xl font-semibold")
                    if selected:
                        self.button("删除环境", delete_selected, flat=True).props("icon=delete_outline outline dense").classes("tw-danger")
                with ui.column().classes("tw-panel w-full gap-4"):
                    if selected is None and not self._creating:
                        return

                    name = ui.input("环境名称", value=draft.name).props("outlined dense").classes("w-full")
                    name.on_value_change(lambda event: setattr(draft, 'name', event.value))
                    ui.label("环境变量").classes("font-medium")
                    area = ui.column().classes("w-full gap-2")
                    def render_row(record):
                        secret = record.secret_reference is not None
                        with area, ui.row().classes("tw-env-variable-row w-full items-end gap-2") as row:
                            key_input = ui.input("Key", value=record.key).props("outlined dense").classes("tw-env-key")
                            value_input = ui.input("Value", value=record.value, password=secret, password_toggle_button=secret).props("outlined dense").classes("tw-env-value")
                            description_input = ui.input("说明（可选）", value=record.description, placeholder="说明用途或录入要求").props("outlined dense").classes("tw-env-description")
                            key_input.on_value_change(lambda event: setattr(record, 'key', event.value))
                            value_input.on_value_change(lambda event: setattr(record, 'value', event.value))
                            description_input.on_value_change(lambda event: setattr(record, 'description', event.value))

                            def remove():
                                draft.remove(record)
                                row.delete()

                            ui.button("移除", on_click=remove).props("outline dense").classes("tw-danger")

                    for record in draft.rows:
                        render_row(record)
                    ui.button("添加变量", on_click=lambda: render_row(draft.add())).props("outline")

                    async def save():
                        result = await self.interaction.save_draft()
                        if result.current:
                            await self.repaint()

                    with ui.row().classes("tw-environment-actions w-full items-center gap-2 flex-wrap"):
                        self.button("保存环境", save, primary=True)
                        if selected and selected["environment_id"] != default:
                            async def set_default():
                                def update_view():
                                    default_environment_id[0] = selected["environment_id"]
                                    render_environment_list()
                                    default_button.set_visibility(False)
                                await self.set_default_for_view(selected["environment_id"], view_identity, update_view)
                            default_button = self.button("设为默认", set_default)

    async def open_environment(self, environment_id, *, expected_view=None, prepare_leave=None):
        if expected_view is not None and not self._view_is_current(expected_view):
            return False
        if prepare_leave is not None and not await prepare_leave():
            return False
        if not self.interaction.select(environment_id, expected_view):
            return False
        await self.repaint()
        return True


async def _noop(*args, **kwargs):
    return None
