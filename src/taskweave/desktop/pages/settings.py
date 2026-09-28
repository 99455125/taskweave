"""Local application settings page."""

from nicegui import ui
from taskweave.desktop.pages.base import Page
from taskweave.core.validation import TaskError


class SettingsPage(Page):
    SECTIONS = (
        ("AI 连接与请求", "ai"),
        ("脱敏设置", "privacy"),
        ("执行设置", "execution"),
        ("工作空间", "workspace"),
    )

    def __init__(self, controller, button):
        self.controller = controller
        self.button = button
        self.selected_section = "ai"

    async def render(self):
        ui.label("设置").classes("text-xl")
        ai_limits = await self.controller.call("ai.settings.get")
        workbench_settings = await self.controller.workbench_settings()
        model_settings = await self.controller.model_settings()

        with ui.row().classes("tw-master-layout tw-secondary-layout"):
            with ui.column().classes("tw-panel tw-list-sidebar tw-settings-sidebar gap-2"):
                ui.label("设置分组").classes("font-medium")
                navigation = {}
                with ui.row().classes("tw-settings-nav-options w-full gap-1"):
                    for label, section in self.SECTIONS:
                        navigation[section] = self.button(
                            label, lambda value=section: self.select_section(value), flat=True
                        ).props("flat align=left").classes("tw-settings-nav w-full justify-start text-left")

            with ui.column().classes("tw-content min-w-0 gap-3"):
                heading = ui.label().classes("text-2xl font-semibold")
                panels = {}

                with ui.column().classes("tw-panel w-full gap-4") as ai_panel:
                    ui.label("AI 编写连接（可选）").classes("font-medium")
                    url = ui.input(
                        "完整 Chat Completions 接口地址", value=model_settings.get("url", "")
                    ).props("outlined dense").classes("w-full")
                    model = ui.input("模型名称", value=model_settings.get("model", "")).props("outlined dense").classes("w-full")
                    api_key = ui.input(
                        "API Key（本地保存，留空保留当前密钥）", password=True,
                        password_toggle_button=True,
                    ).props("outlined dense").classes("w-full")
                    key_env = ui.input(
                        "API Key 所在环境变量名",
                        value=model_settings.get("key_env", "TASKWEAVE_MODEL_API_KEY"),
                    ).props("outlined dense").classes("w-full")
                    ui.label(
                        "API Key 与连接配置保存在本地，重启后自动读取；也可使用环境变量。执行固定步骤不调用模型。"
                    ).classes("text-gray-500")

                    async def save_model():
                        await self.controller.save_model(
                            url.value.strip(), model.value.strip(), key_env.value.strip(), api_key.value or None,
                        )
                        ui.notify("AI 连接配置已保存")

                    async def test_model():
                        await save_model()
                        result = await self.controller.test_model()
                        ui.notify("连接成功" if result["connected"] else "服务未返回有效内容")

                    with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                        self.button("保存连接", save_model, primary=True)
                        self.button("测试连接（实际调用一次模型）", test_model)

                    ui.separator()
                    ui.label("AI 请求大小").classes("font-medium")
                    request_limit = ui.number(
                        "AI 请求大小上限（KB）", value=ai_limits["ai_request_limit_kib"],
                        min=1, max=4096, step=1,
                    ).props("outlined dense").classes("w-full")
                    ui.label("默认 2048 KiB，最高 4096 KiB；此值不是模型 token 上限。").classes("text-gray-500")

                    async def save_ai_limit():
                        value = request_limit.value
                        if value is None or value != int(value):
                            raise TaskError("FORM_INVALID", "请输入 1–4096 的整数")
                        await self.controller.call("ai.settings.update", ai_request_limit_kib=int(value))
                        ui.notify("AI 请求上限已保存")

                    self.button("保存 AI 请求设置", save_ai_limit, primary=True)
                panels["ai"] = ai_panel

                with ui.column().classes("tw-panel w-full gap-4") as privacy_panel:
                    ui.label("脱敏").classes("font-medium")
                    display_redaction = ui.checkbox(
                        "展示插件上下文时脱敏", value=workbench_settings["redact_on_display"]
                    )
                    ai_redaction = ui.checkbox(
                        "发送给 AI 时脱敏", value=workbench_settings["redact_for_ai"]
                    )

                    async def save_redaction():
                        await self.controller.save_privacy_settings(
                            redact_on_display=display_redaction.value,
                            redact_for_ai=ai_redaction.value,
                        )
                        ui.notify("脱敏设置已保存")

                    self.button("保存脱敏设置", save_redaction, primary=True)
                panels["privacy"] = privacy_panel

                with ui.column().classes("tw-panel w-full gap-4") as execution_panel:
                    ui.label("执行器").classes("font-medium")
                    executor_threads = ui.number(
                        "最大并发执行线程数",
                        value=workbench_settings.get("executor_max_threads", 8),
                        min=1, max=8, step=1,
                    ).props("outlined dense").classes("w-full")
                    ui.label("单条运行内的步骤顺序执行；不同运行最多并行 8 条。超出上限时新运行直接报错。").classes("text-gray-500")

                    async def save_executor():
                        value = executor_threads.value
                        if value is None or value != int(value):
                            raise TaskError("FORM_INVALID", "请填写 1 到 8 之间的整数")
                        await self.controller.save_executor_max_threads(int(value))
                        ui.notify("执行器设置已保存")

                    self.button("保存执行器设置", save_executor, primary=True)
                panels["execution"] = execution_panel

                with ui.column().classes("tw-panel w-full gap-4") as workspace_panel:
                    ui.label("本地工作空间").classes("font-medium")
                    ui.label(str(self.controller.workspace_home))
                    ui.label("总库保存配置与执行记录；每个任务的数据库保存返回结果。")
                    destination = ui.input("新的工作空间目录").props("outlined dense").classes("w-full")

                    async def migrate_workspace():
                        with ui.dialog() as confirmation, ui.card().classes("w-full max-w-xl"):
                            ui.label("迁移工作空间？").classes("text-lg")
                            ui.label("迁移前必须结束全部执行实例。复制并校验完成后，下次启动使用新目录并删除旧目录。")
                            with ui.row().classes("gap-2"):
                                ui.button("取消", on_click=lambda: confirmation.submit(False)).props("outline")
                                ui.button("确认迁移", on_click=lambda: confirmation.submit(True)).props("outline text-color=red-7")
                        if not await confirmation:
                            return
                        result = await self.controller.migrate_workspace(destination.value or "")
                        ui.notify("迁移完成，请重启 TaskWeave。新目录：" + result["workspace_home"], type="positive", timeout=12000)

                    self.button("迁移工作空间", migrate_workspace)
                    self.button("打开数据目录", lambda: self.controller.open_path(self.controller.workspace_home))
                panels["workspace"] = workspace_panel

        def update_section(section):
            self.selected_section = section
            titles = dict((key, label) for label, key in self.SECTIONS)
            heading.text = titles[section]
            for key, panel in panels.items():
                panel.set_visibility(key == section)
            for key, button in navigation.items():
                button.classes(
                    add="tw-settings-nav-active" if key == section else "",
                    remove="" if key == section else "tw-settings-nav-active",
                )

        async def select_section(section):
            update_section(section)

        self.select_section = select_section
        update_section(self.selected_section)
