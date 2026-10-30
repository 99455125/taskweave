"""Local application settings page."""

from nicegui import ui
from taskweave.desktop.pages.base import Page
from taskweave.presentation.settings import SettingsSession
from taskweave.application.ai_requests import DEFAULT_AI_REQUEST_LIMIT_KIB, MAX_AI_REQUEST_LIMIT_KIB


class SettingsPage(Page):
    SECTIONS = (
        ("AI 连接与请求", "ai"),
        ('外部 AI / MCP', 'external_ai'),
        ("脱敏设置", "privacy"),
        ("执行设置", "execution"),
        ("工作空间", "workspace"),
    )

    def __init__(self, controller, button):
        self.controller = controller
        self.button = button
        self.session = SettingsSession(controller)

    @property
    def selected_section(self): return self.session.section
    @selected_section.setter
    def selected_section(self, value): self.session.section = value

    async def render(self):
        ui.label("设置").classes("text-xl")
        ai_limits = await self.controller.call("ai.settings.get")
        workbench_settings = await self.controller.workbench_settings()
        model_settings = await self.controller.model_settings()
        # Each mounted form retains its own draft while an old confirmation is
        # awaiting input; remounting must not retarget that accepted action.
        previous_section = self.selected_section
        session = SettingsSession(self.controller)
        session.section = previous_section
        session.load(model_settings, workbench_settings, ai_limits)
        self.session = session

        def bind(control, key):
            control.on_value_change(lambda event: session.draft.__setitem__(key, event.value))

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

                with ui.column().classes('tw-panel w-full gap-4') as external_panel:
                    from taskweave.integration.skill import connection_config, install_skill
                    import json
                    from pathlib import Path
                    ui.label('让外部 AI 编写和调用 TaskWeave').classes('font-medium')
                    ui.label('在运行桥接命令的 Python 环境安装 taskweave[mcp]；源码开发可用 uv run --extra mcp。')
                    config = json.dumps(connection_config(self.controller.workspace_home), ensure_ascii=False, indent=2)
                    ui.code(config, language='json').classes('w-full')
                    async def copy_config():
                        ui.clipboard.write(config)
                        ui.notify('MCP 配置已复制')
                    self.button('复制 MCP 配置', copy_config)
                    ui.label('将配置添加到所用 AI 客户端的 MCP 设置；配置中不含工作空间访问令牌。')
                    import sys
                    if getattr(sys, 'frozen', False):
                        ui.label('桌面打包版需另安装 taskweave[mcp] 命令行桥接；配置使用 PATH 中的 taskweave。')
                    skill_destination = ui.input('Skill 安装目录', value=str(Path.home() / '.agents' / 'skills' / 'taskweave')).props('outlined dense').classes('w-full')
                    async def export_skill():
                        result = install_skill(skill_destination.value)
                        ui.notify('Skill 已安装' if result['status'] == 'installed' else 'Skill 已是当前版本')
                    self.button('安装 / 导出 TaskWeave Skill', export_skill)
                panels['external_ai'] = external_panel

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

                    for control, key in ((url, 'url'), (model, 'model'), (key_env, 'key_env'), (api_key, 'api_key')):
                        bind(control, key)

                    async def save_model():
                        await session.save_model()
                        ui.notify("AI 连接配置已保存")

                    async def test_model():
                        async for result in session.test_model():
                            if result is None:
                                ui.notify("AI 连接配置已保存")
                            else:
                                ui.notify("连接成功" if result["connected"] else "服务未返回有效内容")

                    with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                        self.button("保存连接", save_model, primary=True)
                        self.button("测试连接（实际调用一次模型）", test_model)

                    ui.separator()
                    ui.label("AI 请求大小").classes("font-medium")
                    request_limit = ui.number(
                        "AI 请求大小上限（KiB）", value=ai_limits["ai_request_limit_kib"],
                        min=1, max=MAX_AI_REQUEST_LIMIT_KIB, step=1,
                    ).props("outlined dense").classes("w-full")

                    bind(request_limit, 'request_limit')

                    async def save_ai_limit():
                        await session.save_limit()
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

                    bind(display_redaction, 'redact_on_display')
                    bind(ai_redaction, 'redact_for_ai')

                    async def save_redaction():
                        await session.save_privacy()
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

                    bind(executor_threads, 'executor_threads')

                    async def save_executor():
                        await session.save_executor()
                        ui.notify("执行器设置已保存")

                    self.button("保存执行器设置", save_executor, primary=True)
                panels["execution"] = execution_panel

                with ui.column().classes("tw-panel w-full gap-4") as workspace_panel:
                    ui.label("本地工作空间").classes("font-medium")
                    ui.label(str(self.controller.workspace_home))
                    destination = ui.input("新的工作空间目录").props("outlined dense").classes("w-full")

                    bind(destination, 'destination')

                    async def migrate_workspace():
                        with ui.dialog() as confirmation, ui.card().classes("tw-confirm-dialog"):
                            ui.label("迁移工作空间？").classes("tw-confirm-title")
                            ui.label("迁移前必须结束全部执行实例。复制并校验完成后，下次启动使用新目录并删除旧目录。").classes("tw-confirm-description")
                            with ui.row().classes("tw-confirm-actions"):
                                ui.button("取消", on_click=lambda: confirmation.submit(False)).props("outline").classes("tw-confirm-cancel")
                                ui.button("确认迁移", on_click=lambda: confirmation.submit(True)).props("outline color=negative").classes("tw-confirm-danger")
                        result = await session.migrate(bool(await confirmation))
                        if result is None:
                            return
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
