"""Environment configuration and local defaults page."""

import json
from nicegui import ui
from taskweave.desktop.pages.base import Page
from taskweave.core.validation import TaskError


class EnvironmentPage(Page):
    def __init__(self, controller, button, repaint, on_default_selected, on_deleted=None, page_identity=None):
        self.controller = controller
        self.button = button
        self.repaint = repaint
        self.on_default_selected = on_default_selected
        self.on_deleted = on_deleted or _noop
        self.page_identity = page_identity or (lambda: None)
        self.selected_environment_id = None
        self.search_query = ""
        self._creating = False
        self._render_generation = 0
        self._form_token = None
        self.prepare_leave = None

    def view_identity(self):
        return (self.page_identity(), self._render_generation, self.selected_environment_id)

    def form_identity(self):
        if self._form_token is None:
            return None
        return (self.page_identity(), self._render_generation, self._form_token)

    def _form_is_current(self, identity):
        return identity is not None and identity == self.form_identity() and identity[0] == self.page_identity()

    def _view_is_current(self, identity):
        return identity == self.view_identity() and identity[0] == self.page_identity()

    async def set_default_for_view(self, environment_id, identity, update_view):
        await self.controller.set_default_environment(environment_id)
        if not self._view_is_current(identity) or environment_id != self.selected_environment_id:
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
        save_form_identity = form_identity or self.form_identity()
        save_view_identity = self.view_identity()
        selected_at_start = self.selected_environment_id
        creating_at_start = self._creating
        if not (name or "").strip():
            raise TaskError("FORM_INVALID", "请填写环境名称")
        values, descriptions = {}, {}
        for key, value, description in rows:
            field = (key or "").strip()
            if not field or field in values:
                raise TaskError("FORM_INVALID", "Key 不能为空或重复")
            try:
                values[field] = json.loads(value)
            except (ValueError, TypeError):
                values[field] = value
            if description and description.strip():
                descriptions[field] = description.strip()
        saved = await self.controller.call(
            "environment.save", name=name.strip(), public_config=values,
            secret_refs=secret_refs or {}, descriptions=descriptions, environment_id=environment_id,
        )
        if save_form_identity is not None:
            still_current = (
                self._form_is_current(save_form_identity)
                and self.selected_environment_id == selected_at_start
                and self._creating == creating_at_start
            )
        else:
            still_current = self.view_identity() == save_view_identity
        if not still_current:
            return saved
        self.selected_environment_id = saved["environment_id"]
        self._creating = False
        if form_state is not None:
            form_state["environment_id"] = saved["environment_id"]
        if refresh:
            await self.repaint()
        return saved

    async def create_environment(self, *, expected_view=None, prepare_leave=None):
        if expected_view is not None and not self._view_is_current(expected_view):
            return False
        if prepare_leave is not None and not await prepare_leave():
            return False
        self.selected_environment_id = None
        self._creating = True
        await self.repaint()
        return True

    async def render(self):
        self._render_generation += 1
        render_generation = self._render_generation
        form_token = object()
        self._form_token = form_token
        page_at_start = self.page_identity()
        ui.label("环境").classes("text-xl")
        environments = await self.controller.call("environment.list")
        default = await self.controller.default_environment()
        if page_at_start != self.page_identity() or render_generation != self._render_generation:
            return
        environments = sorted(environments, key=lambda item: (item["environment_id"] != default, item["name"]))
        ids = {item["environment_id"] for item in environments}
        if self.selected_environment_id not in ids and not self._creating:
            self.selected_environment_id = default if default in ids else (environments[0]["environment_id"] if environments else None)
        selected = next((item for item in environments if item["environment_id"] == self.selected_environment_id), None)

        view_identity = self.view_identity()
        form_identity = (page_at_start, render_generation, form_token)
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

                form = {
                    "name": None, "rows": [], "secret_rows": [], "baseline": None,
                    "environment_id": selected["environment_id"] if selected else None,
                }

                def form_values():
                    return (
                        form["name"].value if form["name"] else "",
                        tuple((key.value, value.value, description.value) for key, value, description in form["rows"]),
                    )

                def form_secret_refs():
                    secret_refs = {}
                    for secret_row in form["secret_rows"]:
                        if not any(record is secret_row["record"] for record in form["rows"]):
                            continue
                        key_input, value_input, _description_input = secret_row["record"]
                        key = (key_input.value or "").strip()
                        value = value_input.value
                        if not key:
                            raise TaskError("FORM_INVALID", "Key 不能为空或重复")
                        if value != secret_row["reference"] and not (
                            isinstance(value, str) and value.startswith("env:")
                        ):
                            raise TaskError("FORM_INVALID", "密钥变量必须保留环境变量引用")
                        secret_refs[key] = value
                    return secret_refs

                async def prepare_leave():
                    if not self._view_is_current(view_identity):
                        return False
                    if form_values() == form["baseline"]:
                        return True
                    with ui.dialog() as decision, ui.card():
                        ui.label("环境配置有未保存修改")
                        ui.label("保存后继续、舍弃修改，或继续编辑当前环境。")
                        with ui.row().classes("gap-2 flex-wrap"):
                            ui.button("保存更改", on_click=lambda: decision.submit("save")).props("outline")
                            ui.button("舍弃更改", on_click=lambda: decision.submit("discard")).props("outline")
                            ui.button("继续编辑", on_click=lambda: decision.submit("stay")).props("outline")
                    choice = await decision
                    if not self._view_is_current(view_identity) or choice == "stay" or choice is None:
                        return False
                    if choice == "discard":
                        return True
                    if choice == "save":
                        saved_name = form["name"].value
                        saved_rows = [
                            (key.value, value.value, description.value)
                            for key, value, description in form["rows"]
                        ]
                        await self.save_environment(
                            saved_name,
                            saved_rows,
                            environment_id=form["environment_id"],
                            secret_refs=form_secret_refs(),
                            refresh=False,
                            form_state=form,
                            form_identity=form_identity,
                        )
                        if not self._form_is_current(form_identity):
                            return False
                        form["baseline"] = (saved_name, tuple(saved_rows))
                        return self.page_identity() == view_identity[0] and self._render_generation == view_identity[1]
                    return False

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
                        ui.label("选择一个环境，或新建环境配置变量。").classes("text-gray-500")
                        return

                    config = json.loads(selected["public_config_json"]) if selected else {}
                    descriptions = json.loads(selected.get("descriptions_json") or "{}") if selected else {}
                    stored_secret_refs = json.loads(selected.get("secret_refs_json") or "{}") if selected else {}
                    if selected:
                        config.update(stored_secret_refs)
                    name = ui.input("环境名称", value=selected["name"] if selected else "").props("outlined dense").classes("w-full")
                    form["name"] = name
                    ui.label("变量保存在 TaskWeave 本地配置，不修改系统环境变量。步骤通过 inputs[\"变量名\"] 引用；统一优先级为：步骤变量 > 任务变量 > 环境变量。").classes("text-sm text-gray-500")
                    ui.label("环境变量").classes("font-medium")
                    ui.label("普通值直接填写；对象、数组、数字和布尔值支持 JSON。密钥仅保存 env: 引用，不保存明文。").classes("tw-info-note text-sm")
                    area = ui.column().classes("w-full gap-2")
                    rows = []
                    form["rows"] = rows

                    def add(key="", value="", description="", secret_reference=None):
                        with area, ui.row().classes("tw-env-variable-row w-full items-end gap-2") as row:
                            key_input = ui.input("Key", value=key).props("outlined dense").classes("tw-env-key")
                            value_input = ui.input("Value", value=value, password=secret_reference is not None, password_toggle_button=secret_reference is not None).props("outlined dense").classes("tw-env-value")
                            description_input = ui.input("说明（可选）", value=description, placeholder="说明用途或录入要求").props("outlined dense").classes("tw-env-description")
                            record = (key_input, value_input, description_input)
                            rows.append(record)
                            if secret_reference is not None:
                                form["secret_rows"].append({"record": record, "reference": secret_reference})

                            def remove():
                                rows.remove(record)
                                form["secret_rows"][:] = [item for item in form["secret_rows"] if item["record"] is not record]
                                row.delete()

                            ui.button("移除", on_click=remove).props("outline dense").classes("tw-danger")

                    for key, value in config.items():
                        add(
                            key,
                            value if isinstance(value, str) else json.dumps(value, ensure_ascii=False),
                            descriptions.get(key, ""),
                            secret_reference=stored_secret_refs.get(key),
                        )
                    form["baseline"] = form_values()
                    ui.button("添加变量", on_click=lambda: add()).props("outline")

                    async def save():
                        await self.save_environment(
                            name.value,
                            [(key.value, value.value, description.value) for key, value, description in rows],
                            environment_id=form["environment_id"],
                            secret_refs=form_secret_refs(),
                            form_state=form,
                            form_identity=form_identity,
                        )

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
        if expected_view is not None and not (
            self.page_identity() == expected_view[0] and self._render_generation == expected_view[1]
        ):
            return False
        self._creating = False
        self.selected_environment_id = environment_id
        await self.repaint()
        return True


async def _noop(*args, **kwargs):
    return None
