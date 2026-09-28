"""Local sharing overview; no online marketplace operations are implied."""

from nicegui import ui
from taskweave.desktop.pages.base import Page


class MarketplacePage(Page):
    def __init__(self, controller=None, button=None, navigate=None):
        self.controller, self.button, self.navigate = controller, button, navigate

    async def render(self):
        ui.label("集市").classes("text-xl")
        plugins = await self.controller.call("plugin.list") if self.controller else []
        tasks = await self.controller.call("task.list") if self.controller else []
        with ui.column().classes("tw-marketplace w-full gap-5"):
            with ui.row().classes("tw-market-hero w-full items-center justify-between gap-5 flex-wrap"):
                with ui.column().classes("gap-3 min-w-0"):
                    ui.label("建设中").classes("tw-market-status")
                    ui.label("把好的工作方式，分享给更多人。").classes("text-2xl font-semibold")
                    ui.label("市集暂未开放，当前版本不提供浏览、下载或安装服务。").classes("text-gray-600")
                ui.icon("storefront").classes("tw-market-hero-icon")
            with ui.row().classes("tw-market-resource-grid w-full"):
                resources = (
                    ("任务模板", "复用验证过的任务配置", "checklist"),
                    ("规划模板", "从目标整理到步骤设计", "assignment"),
                    ("插件资源", "连接工具与外部服务", "extension"),
                )
                for title, description, icon in resources:
                    with ui.card().classes("tw-market-resource-card gap-2"):
                        ui.icon(icon).classes("tw-market-resource-icon")
                        ui.label(title).classes("text-lg font-semibold mt-2")
                        ui.label(description).classes("text-sm text-gray-600")
                        ui.label("尚未开放").classes("tw-market-closed-badge mt-2")
            with ui.row().classes("tw-market-local-links w-full items-center gap-2 flex-wrap"):
                ui.label("本机快捷入口").classes("text-sm text-gray-500")
                if self.button and self.navigate:
                    self.button(f"打开任务 · {len(tasks)}", lambda: self.navigate("tasks"), flat=True)
                    self.button(f"查看插件 · {len(plugins)}", lambda: self.navigate("plugins"), flat=True)
