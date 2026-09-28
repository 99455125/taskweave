"""Installed plugin list and selected capability detail."""

import json
from nicegui import ui
from taskweave.desktop.pages.base import Page


def _document_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _schema_rows(schema):
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    required = schema.get("required", []) if isinstance(schema, dict) else []
    return [
        [key, spec.get("type", "见约束"), "是" if key in required else "否",
         _document_text(spec["default"]) if "default" in spec else "未声明",
         spec.get("description") or _document_text({k: v for k, v in spec.items() if k not in {"type", "default", "description"}}) or "未提供文字说明"]
        for key, spec in properties.items()
    ]


def filter_plugins(plugins, query="", status="all"):
    query = (query or "").strip().casefold()
    visible = [plugin for plugin in plugins if query in plugin["id"].casefold()]
    if status == "enabled":
        visible = [plugin for plugin in visible if plugin["enabled"]]
    elif status == "disabled":
        visible = [plugin for plugin in visible if not plugin["enabled"]]
    return visible


class PluginsPage(Page):
    def __init__(self, controller, button, repaint):
        self.controller, self.button, self.repaint = controller, button, repaint
        self.selected_plugin_id = None
        self.search_query = ""
        self.status_filter = "all"

    async def render(self):
        catalog = await self.controller.call("capabilities")
        installed = await self.controller.call("plugin.list")
        installed = sorted(
            (plugin for plugin in installed if plugin["id"] not in {"demo", "sample", "text"}),
            key=lambda item: (not item["enabled"], item["id"]),
        )
        plugin_ids = {plugin["id"] for plugin in installed}
        if self.selected_plugin_id not in plugin_ids:
            self.selected_plugin_id = installed[0]["id"] if installed else None

        with ui.row().classes("tw-master-layout tw-secondary-layout"):
            with ui.column().classes("tw-panel tw-list-sidebar gap-3"):
                ui.label("插件").classes("font-medium")
                search = ui.input("搜索插件", value=self.search_query, placeholder="搜索插件名称").props(
                    "clearable debounce=200 prepend-icon=search"
                ).classes("w-full")
                status = ui.select(
                    {"all": "全部插件", "enabled": "已启用", "disabled": "未启用"},
                    value=self.status_filter, label="启用状态",
                ).classes("w-full")
                plugin_list = ui.column().classes("w-full gap-2")

            detail = ui.column().classes("tw-content tw-plugin-detail min-w-0 gap-3")

        def render_plugin_list():
            self.search_query = search.value if isinstance(search.value, str) else self.search_query
            self.status_filter = status.value if status.value in {"all", "enabled", "disabled"} else self.status_filter
            visible = filter_plugins(installed, self.search_query, self.status_filter)
            plugin_list.clear()
            with plugin_list:
                if not visible:
                    ui.label("没有匹配的插件" if installed else "没有发现已安装的插件").classes("text-sm text-gray-500")
                for plugin in visible:
                    selected = plugin["id"] == self.selected_plugin_id
                    with ui.column().classes("w-full rounded-lg border border-gray-200 p-2 gap-1" + (" tw-selected" if selected else "")):
                        self.button(plugin["id"], lambda item=plugin: self.select_plugin(item["id"]), flat=True).classes("w-full justify-start text-left")
                        ui.label(("已启用 · " if plugin["enabled"] else "未启用 · ") + plugin["id"]).classes("text-xs text-gray-500")

        def render_selected_plugin():
            detail.clear()
            selected = next((plugin for plugin in installed if plugin["id"] == self.selected_plugin_id), None)
            with detail:
                if selected is None:
                    ui.label("选择一个插件查看能力和配置说明。").classes("text-gray-500")
                    return
                name = selected["id"]
                with ui.row().classes("tw-plugin-detail-heading w-full items-center justify-between gap-3 flex-wrap"):
                    with ui.row().classes("items-center gap-3 min-w-0"):
                        ui.icon("extension").classes("tw-plugin-heading-icon")
                        with ui.column().classes("gap-1 min-w-0"):
                            ui.label(name).classes("text-2xl font-semibold")
                            version = catalog["versions"].get(name)
                            version_label = f"版本 {version}" if version else "版本未加载"
                            status_label = "已启用" if selected["enabled"] else "未启用"
                            ui.label(f"{version_label} · {status_label}").classes("text-sm text-gray-500")

                    async def toggle(plugin=selected):
                        await self.controller.call("plugin.configure", plugin_id=plugin["id"], enabled=not plugin["enabled"])
                        await self.repaint()

                    self.button("停用" if selected["enabled"] else "启用", toggle, primary=not selected["enabled"])
                error = selected.get("error") or catalog["load_errors"].get(name)
                if error:
                    ui.label("加载错误：" + str(error)).classes("text-red-700")
                manifest = catalog["manifests"].get(name)

                actions = [item for item in catalog["actions"] if item["id"].startswith(name + ".")]
                tools = [item for item in catalog["tools"] if item["id"].startswith(name + ".")]
                capabilities = actions + tools
                with ui.card().classes("tw-plugin-section w-full"):
                    ui.label("能力与动作").classes("text-lg font-semibold")
                    if capabilities:
                        for index, spec in enumerate(capabilities):
                            with ui.expansion(spec["id"], icon="code", value=index == 0).classes("tw-plugin-capability-card w-full"):
                                with ui.row().classes("gap-2 items-center flex-wrap"):
                                    ui.badge("写入能力" if spec["effect"] == "WRITE" else "读取能力")
                                    ui.label(f'超时 {spec["timeout_ms"]} ms')
                                    ui.label("可安全重试" if spec["retry_safe"] else "不保证可重试")
                                    if spec.get("resource_ids"):
                                        ui.label("资源：" + "、".join(spec["resource_ids"]))
                                ui.label("用途说明").classes("font-medium mt-2")
                                ui.label(spec.get("description") or "插件未提供文字用途说明；以下 schema 是完整动作契约。").classes("whitespace-pre-wrap")
                                ui.label("输入参数").classes("font-medium mt-3")
                                rows = _schema_rows(spec.get("input_schema", {}))
                                if rows:
                                    ui.table(columns=[{"name": key, "label": label, "field": key, "align": "left"} for key, label in [("name", "参数"), ("type", "类型"), ("required", "必填"), ("default", "默认值"), ("description", "说明")]], rows=[dict(zip(("name", "type", "required", "default", "description"), row)) for row in rows]).classes("w-full tw-plugin-config-table")
                                else:
                                    ui.label("无输入参数")
                                ui.code(_document_text(spec.get("input_schema", {})), language="json").classes("w-full")
                                ui.label("返回结果").classes("font-medium mt-3")
                                output = spec.get("output_schema", {})
                                ui.label("返回空值，无结构化结果。" if output.get("type") == "null" else "返回值符合以下 schema 约束。")
                                ui.code(_document_text(output), language="json").classes("w-full")
                                ui.label("调用示例").classes("font-medium mt-3")
                                example = {key: f"<填写 {key}>" for key in spec.get("input_schema", {}).get("required", [])}
                                ui.code("result = await ctx.call(" + repr(spec["id"]) + ", " + repr(example) + ")", language="python").classes("w-full")
                                ui.label("示例占位值按参数类型与约束替换；页面不会执行动作。效果类别不代表不会改变页面或外部状态。" ).classes("text-sm text-gray-500")
                    else:
                        ui.label("插件未加载，暂无动作和工具契约。启用后可查看完整说明。").classes("text-sm text-gray-500")
                    requests = (manifest or {}).get("context_requests", {})
                    if requests:
                        ui.label("采集能力").classes("font-medium mt-4")
                        for provider, schema in requests.items():
                            with ui.expansion(provider, icon="collections_bookmark").classes("tw-plugin-capability-card w-full"):
                                ui.label("从插件提供方采集上下文证据；参数和目标选择规则如下。")
                                ui.code(_document_text(schema), language="json").classes("w-full")

                variables = (manifest or {}).get("config_variables", [])
                with ui.card().classes("tw-plugin-section w-full"):
                    ui.label("配置变量").classes("text-lg font-semibold")
                    ui.label("在环境或任务参数中维护，任务参数优先；此处仅展示插件声明。").classes("text-sm text-gray-500")
                    if variables:
                        rows = [[v["key"], v.get("type", "未知"), "是" if v.get("required") else "否", _document_text(v["default"]) if "default" in v else "未声明", v.get("description", "")] for v in variables]
                        ui.table(columns=[{"name": key, "label": label, "field": key, "align": "left"} for key, label in [("key", "变量"), ("type", "类型"), ("required", "必填"), ("default", "默认值"), ("description", "说明")]], rows=[dict(zip(("key", "type", "required", "default", "description"), row)) for row in rows]).classes("w-full tw-plugin-config-table")
                    elif manifest:
                        ui.label("插件未声明配置变量。")
                    else:
                        ui.label("插件未加载，配置变量不可用。")
                handlers = [identifier for identifier in catalog.get("result_handlers", []) if identifier.startswith(name + ".")]
                providers = [identifier for identifier in catalog.get("resource_providers", []) if identifier.startswith(name + ".")]
                views = {identifier: descriptor for identifier, descriptor in catalog.get("result_views", {}).items() if identifier.startswith(name + ".")}
                ui.label("结果处理器：" + ("、".join(handlers) or "无"))
                ui.label("资源提供器：" + ("、".join(providers) or "无"))
                if views:
                    with ui.expansion("结果视图"):
                        ui.code(_document_text(views), language="json")
                with ui.card().classes("tw-plugin-section tw-plugin-contributions w-full"):
                    ui.label("编写上下文与示例").classes("text-lg font-semibold")
                    try:
                        contribution = self.controller.plugin_contributions([spec["id"] for spec in capabilities])
                    except Exception as exc:
                        contribution = []
                        ui.label("能力上下文暂不可读取：" + str(exc)).classes("text-amber-800")
                    for item in contribution:
                        if item.instructions:
                            ui.label("使用约束").classes("font-medium")
                            ui.label(item.instructions).classes("whitespace-pre-wrap")
                        if item.constraints:
                            ui.label("生成约束").classes("font-medium")
                            ui.code(_document_text(item.constraints), language="json")
                        if item.channel_overrides:
                            ui.label("渠道专用约束").classes("font-medium")
                            ui.code(_document_text(item.channel_overrides), language="json")
                        if item.examples:
                            ui.label("示例").classes("font-medium")
                            for example in item.examples:
                                ui.code(example, language="python")
                    if not contribution or not any(item.examples for item in contribution):
                        ui.label("插件未提供代码示例。").classes("text-sm text-gray-500")
                with ui.card().classes("tw-plugin-load-state w-full"):
                    ui.label("加载状态").classes("text-lg font-semibold")
                    ui.badge("正常加载" if manifest and not error else "未加载" if not manifest else "加载错误").props("color=green" if manifest and not error else "color=red" if error else "color=grey")
                    if error:
                        ui.label("加载错误：" + str(error)).classes("text-red-700 whitespace-pre-wrap")
                    elif not manifest:
                        ui.label("该插件当前未启用或未加载；启用会通过 plugin.configure 校验本地已安装插件。").classes("text-sm text-gray-600")
                    else:
                        ui.label("插件契约已由当前本地运行时加载。").classes("text-sm text-gray-600")

        def render():
            query = search.value if isinstance(search.value, str) else self.search_query
            status_value = status.value if status.value in {"all", "enabled", "disabled"} else self.status_filter
            visible = filter_plugins(installed, query, status_value)
            if self.selected_plugin_id not in {item["id"] for item in visible}:
                self.selected_plugin_id = visible[0]["id"] if visible else None
            render_plugin_list()
            render_selected_plugin()

        self._render = render
        search.on_value_change(lambda _: render())
        status.on_value_change(lambda _: render())
        render()

    async def select_plugin(self, plugin_id):
        self.selected_plugin_id = plugin_id
        if getattr(self, "_render", None):
            self._render()
