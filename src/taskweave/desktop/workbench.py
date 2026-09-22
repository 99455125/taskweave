"""Cross-platform NiceGUI workbench backed by the existing application service."""

from datetime import datetime, timezone
from pathlib import Path
import asyncio
import json
import logging

from nicegui import ui
from taskweave.core.validation import TaskError, normalize_step
from taskweave.desktop.controller import command_id
from taskweave.desktop.forms import SchemaEditor, ValueForm
from taskweave.desktop.display import execution_title, readable_metadata, step_names, image_reference

EMPTY = "async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n"
STATUS = {
    "DRAFT": "草稿",
    "VALIDATED": "已验证",
    "READY": "就绪",
    "RUNNING": "执行中",
    "PAUSED": "已暂停",
    "FAILED": "失败",
    "INTERRUPTED": "中断 / 待核对",
    "SUCCEEDED": "成功",
    "CANCELLED": "已结束",
    "UNKNOWN": "结果待核对",
}
ERRORS = {
    "TASK_LOCKED": "任务有活跃运行，请先结束运行再修改。",
    "RUN_LEASE_BUSY": "另一个运行占用了执行器，请先结束该运行。",
    "STEP_NOT_VALIDATED": "请先确认所有步骤。",
    "MODEL_NOT_CONFIGURED": "尚未配置 AI；可以手写步骤，或到设置中配置模型。",
    "EDIT_CONFLICT": "内容已被修改，请重新打开步骤。",
    "RECONCILIATION_REQUIRED": "先查询业务系统并核对执行结果，再继续。",
    "EXPLICIT_RETRY_REQUIRED": "请选中失败步骤并点击“重试选中步骤”。",
    "PLUGIN_CONFIG_LOCKED": "活跃运行期间不能修改插件配置。",
    "EXECUTOR_CAPACITY": "执行器已达并发上限，请等待已有运行结束或手动结束实例。",
}


def document_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


class Workbench:
    def __init__(self, controller):
        self.controller = controller
        self.page, self.task_id, self.step_id, self.run_id = "tasks", None, None, None
        self.environment_id = None
        self.trials, self.contexts, self.context_entries = {}, [], []
        self.debug_supplements = {}
        self.busy, self.edit_controls, self.old_step = False, None, None
        self.save_lock = asyncio.Lock()
        ui.colors(primary="#2563eb", positive="#15803d", negative="#dc2626")
        ui.add_css("""
            body { background: #f5f6f8; color: #202936; }
            .tw-panel { background: white; border: 1px solid #dce2e9; border-radius: 10px; padding: 18px; }
            .q-btn { box-shadow: none; border-radius: 6px; }
            .q-btn.bg-primary { background: white !important; color: #345adb !important; border: 1px solid #cbd5e1; }
            .q-btn.text-primary { color: #345adb !important; }
            .tw-code { white-space: pre-wrap; overflow-wrap: anywhere; font-family: ui-monospace, monospace; }
            .tw-content { min-width: 0; flex: 1; }
            .tw-sidebar { width: 145px; flex-shrink: 0; }
            .tw-selected { background:#ecfeff !important; border-left:4px solid #0f766e !important; color:#134e4a !important; }
            .tw-danger { color:#dc2626 !important; border-color:#fecaca !important; }
            .tw-save-state { min-width: 9rem; text-align:right; }
            @media(max-width: 780px) { .tw-sidebar { width: 100%; flex-direction: row; flex-wrap: wrap; } }
        """)
        with ui.header().classes(
            "bg-white text-gray-800 border-b items-center justify-between"
        ):
            ui.label("TaskWeave · 任务织流").classes("text-lg font-medium")
            ui.label("本地工作空间").classes("text-gray-500")
            with ui.row().classes("items-center gap-2"):
                self.button("执行实例", self.instance_dialog)
                if hasattr(controller, "open_logs"):
                    self.button("服务日志", controller.open_logs)
        with ui.row().classes("w-full items-start flex-wrap md:flex-nowrap gap-5"):
            with ui.column().classes("tw-sidebar tw-panel"):
                for page, title in [
                    ("tasks", "任务"),
                    ("executions", "执行"),
                    ("plugins", "插件"),
                    ("environment", "环境"),
                    ("settings", "设置"),
                ]:
                    self.button(title, lambda p=page: self.navigate(p), flat=True)
            self.content = ui.column().classes("tw-content w-full gap-5")

    def button(self, title, callback, primary=False, flat=False):
        async def action():
            if self.busy:
                return
            self.busy = True
            self._buttons = [button for button in getattr(self, '_buttons', []) if not button.is_deleted]
            for button in self._buttons:
                button._tw_before_busy = button.enabled
                button.disable()
            try:
                await callback()
            except TaskError as exc:
                if control in getattr(self, 'trial_actions', {}).values():
                    self.style_trial_action(control, 'FAILED')
                    if getattr(self, 'trial_start_status', None) and not self.trial_start_status.is_deleted:
                        self.trial_start_status.text = ''
                if exc.code in {'RUN_LEASE_BUSY', 'RUN_STATE_INVALID'}:
                    with ui.dialog() as dialog, ui.card().classes('w-full max-w-xl'):
                        ui.label('该执行已有活跃实例，不能重复启动。').classes('text-lg font-medium')
                        ui.label('不同执行可以并行；同一条执行必须先结束现有实例。').classes('text-gray-500')
                        with ui.row().classes('gap-2'):
                            ui.button('查看实例', on_click=lambda: dialog.submit('instances')).props('outline')
                            ui.button('关闭', on_click=lambda: dialog.submit(None)).props('outline')
                    if await dialog == 'instances':
                        await self.instance_dialog()
                else:
                    ui.notify(ERRORS.get(exc.code, str(exc)), type="negative", timeout=8000)
            except (ValueError, TypeError, KeyError) as exc:
                ui.notify("配置无效：" + str(exc), type="negative", timeout=8000)
            finally:
                self.busy = False
                for button in getattr(self, '_buttons', []):
                    if button.is_deleted:
                        continue
                    if button is getattr(self, 'trial_actions', {}).get('end'):
                        rid = self.trials.get(self.step_id)
                        current = await self.controller.call('run.get', run_id=rid) if rid else None
                        button.set_enabled(bool(current and current.get('can_end')))
                    elif hasattr(button, '_tw_before_busy'):
                        button.set_enabled(button._tw_before_busy)
                    if hasattr(button, '_tw_before_busy'):
                        del button._tw_before_busy

        control = ui.button(title, on_click=action)
        if not hasattr(self, '_buttons'):
            self._buttons = []
        self._buttons.append(control)
        if self.busy:
            control._tw_before_busy = control.enabled
            control.disable()
        control.props('flat text-color=primary')
        control.style('background: white; color: #345adb; border: 1px solid #cbd5e1')
        if primary:
            control.style('background: #f0fdfa; border: 1px solid #0f766e; color: #0f766e')
            control.props('text-color=teal-8')
        return control

    def style_trial_action(self, control, state=None):
        if state == 'SUCCEEDED':
            control.props('text-color=teal-8').style('background: #f0fdfa; color: #0f766e; border: 1px solid #0f766e')
        elif state in {'FAILED', 'UNKNOWN', 'INTERRUPTED'}:
            control.props('text-color=red-7').style('background: #fef2f2; color: #b91c1c; border: 1px solid #dc2626')
        else:
            control.props('text-color=primary').style('background: white; color: #345adb; border: 1px solid #cbd5e1')

    async def instance_dialog(self):
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-4xl"):
            ui.label("执行实例").classes("text-lg font-medium")
            ui.label("调试实例按任务复用；正式执行每条运行使用独立实例。").classes("text-gray-500")
            area = ui.column().classes("w-full gap-2")

            async def refresh():
                instances = await self.controller.call("run.instances")
                tasks = {row['task_id']: row['name'] for row in await self.controller.call('task.list')}
                area.clear()
                with area:
                    if not instances:
                        ui.label("当前没有未结束的执行实例。").classes("text-gray-500")
                        return
                    for instance in instances:
                        with ui.row().classes("w-full items-center justify-between border rounded p-3 gap-3"):
                            kind = "调试" if instance["instance_type"] == "trial" else "正式执行"
                            with ui.column().classes("gap-0 min-w-0"):
                                ui.label(f"{kind} · {instance['status']}").classes("font-medium")
                                ui.label(f"{tasks.get(instance['task_id'], '已删除任务')} · {execution_title(instance)}").classes("text-sm text-gray-500")

                            async def end(current=instance):
                                operation = "cancel" if current["status"] == "RUNNING" else "abandon"
                                await self.controller.call("run.control", run_id=current["run_id"], command_id=command_id(), operation=operation)
                                if operation == "cancel":
                                    await self.controller.call("run.wait", run_id=current["run_id"], timeout=5)
                                    latest = await self.controller.call("run.get", run_id=current["run_id"])
                                    if latest.get("can_end"):
                                        await self.controller.call("run.control", run_id=current["run_id"], command_id=command_id(), operation="abandon")
                                await refresh()

                            self.button("结束实例", end)
            await refresh()
            with ui.row().classes("w-full justify-end"):
                ui.button("关闭", on_click=dialog.close).props("outline")
        dialog.open()

    async def navigate(self, page, task_id=None, step_id=None):
        dirty = False
        if self.edit_controls and self.old_step:
            try:
                dirty = normalize_step(self.document()) != normalize_step(self.old_step)
            except (TaskError, ValueError, TypeError):
                dirty = True
        if dirty:
            with ui.dialog() as dialog, ui.card():
                ui.label("步骤有未保存的修改，是否离开？")
                with ui.row():
                    ui.button("继续编辑", on_click=lambda: dialog.submit(False)).props(
                        "outline"
                    )
                    ui.button("舍弃修改并离开", on_click=lambda: dialog.submit(True))
            if not await dialog:
                return
        self.page = page
        if task_id is not None:
            if self.task_id != task_id:
                self.step_id = self.run_id = None
                self.contexts = []
                self.context_entries = []
            self.task_id = task_id
        if step_id is not None:
            if self.step_id != step_id:
                self.contexts = []
                self.context_entries = []
            self.step_id = step_id
        self.edit_controls = None
        await self.paint()

    async def navigate_step_debug(self, task_id, step_id, run_id=None, preserve_repair=False):
        await self.navigate('editor', task_id=task_id, step_id=step_id)
        if run_id:
            self.trials[step_id] = run_id
        if not preserve_repair:
            self.controller.reset_debug_conversation(step_id)
            self.debug_supplements.pop(step_id, None)
        self.debug_feedback = None
        self.debug_feedback_run_id = None
        self.debug_removed_feedback = set()
        if getattr(self, 'editor_tabs', None):
            self.editor_tabs.value = '调试'

    async def paint(self):
        self.run_signature = self.trial_signature = None
        self.content.clear()
        with self.content:
            if self.page in {"editor", "run", "history"}:
                if not self.task_id:
                    self.page = "tasks"
                else:
                    await self.task_header()
            await {
                "tasks": self.task_list,
                "executions": self.execution_hub,
                "editor": self.editor,
                "run": self.run,
                "history": self.history,
                "plugins": self.plugins,
                "environment": self.environment,
                "settings": self.settings,
            }[self.page]()

    async def task_header(self):
        task = await self.controller.call("task.get", task_id=self.task_id)
        with ui.row().classes("w-full items-center justify-between"):
            with ui.row().classes("items-center"):
                self.button("返回任务列表", lambda: self.navigate("tasks"))
                self.task_name_label = ui.label(task["name"]).classes("text-xl font-medium")
            self.button("任务配置", lambda: self.task_dialog(task))
        with ui.row().classes("w-full border-b pb-3"):
            for page, title in [
                ("editor", "步骤编写"),
                ("history", "调试历史"),
            ]:
                self.button(
                    title, lambda p=page: self.navigate(p), primary=page == self.page
                )

    async def task_list(self):
        with ui.row().classes("w-full justify-between items-center"):
            ui.label("任务").classes("text-xl font-medium")
            with ui.row():
                self.button("导入任务", self.import_task_dialog)
                self.button("新建任务", lambda: self.task_dialog(), primary=True)
        tasks = await self.controller.call("task.list")
        if not tasks:
            ui.label("还没有任务。新建任务后，可以手写或 AI 编写步骤。").classes(
                "tw-panel w-full"
            )
        for i, task in enumerate(tasks):
            with ui.row().classes("tw-panel w-full items-center justify-between"):
                with ui.column().classes("gap-1"):
                    ui.label(task["name"]).classes("font-medium")
                    ui.label(task["description"] or "暂无说明").classes("text-gray-500")
                with ui.row():
                    self.button(
                        "打开",
                        lambda t=task: self.open_task(t),
                        primary=True,
                    )

                    async def copy(t=task):
                        await self.controller.call("task.copy", task_id=t["task_id"])
                        await self.paint()

                    self.button("复制", copy)
                    self.button("导出", lambda t=task: self.export_task_dialog(t))
                    for direction, label in [(-1, "上移"), (1, "下移")]:

                        async def reorder(index=i, d=direction):
                            ids = [t["task_id"] for t in tasks]
                            target = index + d
                            if 0 <= target < len(ids):
                                ids[target], ids[index] = ids[index], ids[target]
                                await self.controller.call("task.reorder", task_ids=ids)
                                await self.paint()

                        self.button(label, reorder)
                    self.button("清理运行", lambda t=task: self.clear_task_runs(t))
                    self.button("", lambda t=task: self.delete_task(t), flat=True).props(
                        "icon=delete round dense text-color=red-7 aria-label=删除"
                    ).classes('tw-danger').tooltip('删除任务')

    async def open_task(self, task):
        steps = await self.controller.call("step.list", task_id=task["task_id"])
        # Task pages are for authoring and debugging. Formal executions live in
        # the independent Execution menu.
        await self.navigate("editor", task_id=task["task_id"], step_id=steps[0]["step_id"] if steps else None)

    async def execution_hub(self):
        tasks = await self.controller.call("task.list")
        with ui.row().classes("w-full items-center justify-between gap-3"):
            ui.label("执行").classes("text-xl font-medium")
            task_filter = ui.select(
                {task["task_id"]: task["name"] for task in tasks},
                value=self.task_id if self.task_id in {task["task_id"] for task in tasks} else (tasks[0]["task_id"] if tasks else None),
                label="任务筛选",
            ).classes("w-80")
        if not tasks:
            ui.label("暂无任务。请先在任务菜单中创建并确认步骤。").classes("tw-panel w-full text-gray-500")
            return
        self.task_id = task_filter.value
        task_filter.on_value_change(lambda event: self.navigate("executions", task_id=event.value))
        await self.run()

    async def export_task_dialog(self, task):
        package = await self.controller.call('task.export', task_id=task['task_id'])
        text = document_text(package)
        with ui.dialog() as dialog, ui.card().classes('w-full max-w-4xl'):
            ui.label(task['name'] + ' · 导出任务').classes('text-lg')
            ui.label('包含任务参数默认值、步骤内容和绑定，不包含环境和执行历史。')
            ui.textarea('任务 JSON', value=text).props('readonly').classes('w-full').style('max-height: 65vh; overflow: auto')
            async def copy():
                await self.controller.copy_text(text)
                ui.notify('任务 JSON 已复制')
            async def download():
                if self.controller.native:
                    path = await self.controller.save_task_export(text)
                    ui.notify('任务 JSON 已保存：' + str(path), timeout=8000)
                else:
                    ui.download.content(text, filename='taskweave-task.json', media_type='application/json')
            with ui.row():
                self.button('复制 JSON', copy)
                self.button('下载 JSON', download)
                ui.button('关闭', on_click=dialog.close).props('outline')
        dialog.open()

    async def import_task_dialog(self):
        with ui.dialog() as dialog, ui.card().classes('w-full max-w-4xl'):
            ui.label('导入任务').classes('text-lg')
            ui.label('粘贴任务 JSON，创建独立副本；全部步骤默认已验证，不执行代码。请先启用所需插件。')
            source = ui.textarea('任务 JSON').classes('w-full').props('placeholder="粘贴导出的任务 JSON"')
            async def import_package():
                if len(source.value or '') > 2 * 1024 * 1024:
                    raise TaskError('TASK_PACKAGE_INVALID', '任务 JSON 超过 2MB')
                try:
                    package = json.loads(source.value or '')
                except ValueError as exc:
                    raise TaskError('TASK_PACKAGE_INVALID', '请粘贴有效 JSON') from exc
                await self.controller.call('task.import', package=package)
                dialog.close()
                await self.paint()
                ui.notify('任务已导入，全部步骤已验证')
            with ui.row():
                self.button('导入为新任务', import_package, primary=True)
                ui.button('取消', on_click=dialog.close).props('outline')
        dialog.open()

    async def clear_task_runs(self, task):
        with ui.dialog() as dialog, ui.card().classes('w-full max-w-xl'):
            ui.label('清理任务“' + task['name'] + '”的全部运行数据？').classes('text-lg')
            ui.label('保留任务配置、步骤及验证状态；删除执行和调试记录、结果、截图、文件及调试对话。保留的插件资源也会关闭，删除后无法恢复。')
            with ui.row().classes('w-full items-center gap-2 flex-wrap'):
                ui.button('取消', on_click=lambda: dialog.submit(False)).props('outline')
                ui.button('确认清理', on_click=lambda: dialog.submit(True)).props('outline color=negative')
        if await dialog:
            result = await self.controller.call('task.clear_runs', task_id=task['task_id'])
            for step in await self.controller.call('step.list', task_id=task['task_id']):
                self.trials.pop(step['step_id'], None)
            if self.task_id == task['task_id']:
                self.run_id = None
                self.contexts = []
                self.context_entries = []
                self.trial_signature = None
            ui.notify('已清理 ' + str(result['deleted_runs']) + ' 条运行记录', type='positive')
            await self.paint()

    async def delete_task(self, task):
        with ui.dialog() as dialog, ui.card():
            ui.label('删除任务“' + task['name'] + '”及其全部执行记录、结果？')
            with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                ui.button('取消', on_click=lambda: dialog.submit(False)).props('outline')
                ui.button('确认删除', on_click=lambda: dialog.submit(True)).props('color=negative')
        if await dialog:
            await self.controller.call('task.delete', task_id=task['task_id'])
            if self.task_id == task['task_id']:
                self.task_id, self.edit_controls, self.run_id = None, None, None
            await self.paint()

    async def task_dialog(self, task=None):
        if task is not None:
            task = await self.controller.call("task.get", task_id=task["task_id"])
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-3xl"):
            ui.label("任务配置" if task else "新建任务").classes("text-lg")
            name = ui.input("任务名称", value=task["name"] if task else "").classes(
                "w-full"
            )
            description = ui.textarea(
                "说明", value=task["description"] if task else ""
            ).classes("w-full")
            schema = SchemaEditor(
                json.loads(task["input_schema_json"]) if task else None
            )

            async def save():
                if not name.value.strip():
                    raise TaskError("FORM_INVALID", "请填写任务名称")
                if task:
                    selected_tab = self.editor_tabs.value if self.edit_controls and hasattr(self, 'editor_tabs') else None
                    if self.edit_controls and getattr(self, 'old_step', None):
                        await self.save_editor()
                    await self.controller.call(
                        "task.update",
                        task_id=task["task_id"],
                        name=name.value.strip(),
                        input_schema=schema.schema(),
                        description=description.value,
                    )
                else:
                    saved = await self.controller.call(
                        "task.create",
                        name=name.value.strip(),
                        input_schema=schema.schema(),
                        description=description.value,
                    )
                    self.task_id, self.page = saved["task_id"], "editor"
                dialog.close()
                if task and self.edit_controls:
                    self.edit_controls = None
                    await self.paint()
                    if selected_tab is not None:
                        self.editor_tabs.value = selected_tab
                    ui.notify("任务配置已保存，任务参数已刷新。")
                else:
                    self.edit_controls = None
                    await self.paint()

            with ui.row():
                self.button("保存", save, primary=True)
                ui.button("取消", on_click=dialog.close).props("outline")
        dialog.open()

    async def environment_select(self):
        environments = await self.controller.call("environment.list")
        options = {
            "": "默认环境（无配置）",
            **{e["environment_id"]: e["name"] for e in environments},
        }
        if self.environment_id not in options:
            self.environment_id = ""
        if not self.environment_id:
            default = await self.controller.default_environment()
            if default in options:
                self.environment_id = default

        def change(e):
            if self.environment_id != e.value:
                self.contexts = []
                self.context_entries = []
            self.environment_id = e.value

        return ui.select(
            options,
            label="运行 / 调试环境",
            value=self.environment_id,
            on_change=change,
        ).classes("w-72")

    async def variable_form(self, schema, environment, values=None):
        configured = await self.controller.configured_inputs(self.task_id, environment.value or None)
        form = ValueForm(schema, {**configured, **(values or {})})
        async def change(e):
            form.apply_defaults(await self.controller.configured_inputs(self.task_id, e.value or None))
        environment.on_value_change(change)
        return form

    async def trial_variables(self, step, environment, values=None, *, run=None, focus=None, readonly_other=False):
        task = await self.controller.call('task.get', task_id=self.task_id)
        task_schema = json.loads(task['input_schema_json'])
        area = ui.column().classes('w-full gap-2')
        form = step_form = None

        async def render(selected, overrides=None, step_overrides=None):
            nonlocal form, step_form
            environments = await self.controller.call('environment.list')
            env = next((json.loads(e['public_config_json']) for e in environments if e['environment_id'] == selected), {})
            defaults = {k: v['default'] for k, v in task_schema.get('properties', {}).items() if 'default' in v}
            task_values = {**env, **defaults, **(overrides or {})}
            area.clear()
            with area:
                with ui.expansion('环境变量 · 只读', icon='public').classes('w-full border rounded'):
                    if not env:
                        ui.label('当前环境未配置变量').classes('text-gray-500')
                    for key, value in env.items():
                        suffix = '（被任务变量覆盖）' if key in defaults or key in (overrides or {}) else ''
                        ui.label(f'{key} = {document_text(value)} · 环境{suffix}').classes('tw-code w-full')
                with ui.expansion('任务变量 · 本次运行输入', icon='edit', value=bool(task_schema.get('required')) and focus in {None, 'task'}).classes('w-full border rounded'):
                    form = ValueForm(task_schema, task_values)
                    if readonly_other and focus != 'task':
                        for _, control in form.controls.values():
                            control.disable()
                with ui.expansion('步骤变量与依赖 · 本次步骤输入', icon='account_tree', value=bool([key for key in step['input_schema'].get('required', []) if key not in step['bindings']]) and focus in {None, 'step'}).classes('w-full border rounded'):
                    properties = step['input_schema'].get('properties', {})
                    if not properties and not step['bindings']:
                        ui.label('此步骤无专用输入或依赖').classes('text-gray-500')
                    editable = {key: spec for key, spec in properties.items() if key not in step['bindings']}
                    step_schema = {**step['input_schema'], 'properties': editable, 'required': [key for key in step['input_schema'].get('required', []) if key in editable]}
                    step_defaults = {key: spec['default'] for key, spec in editable.items() if 'default' in spec}
                    step_form = ValueForm(step_schema, {**task_values, **step_defaults, **(step_overrides or {})})
                    if readonly_other and focus != 'step':
                        for _, control in step_form.controls.values():
                            control.disable()
                    def update_step_defaults(_):
                        try:
                            step_form.apply_defaults({**env, **defaults, **form.values()})
                        except TaskError:
                            return  # A JSON input may be incomplete while typing.
                    for _, control in form.controls.values():
                        if hasattr(control, 'on_value_change'):
                            control.on_value_change(update_step_defaults)
                    for key, spec in properties.items():
                        if key not in step['bindings']:
                            continue
                        if key in step['bindings']:
                            binding = step['bindings'][key]
                            if 'literal' in binding:
                                value, source = binding['literal'], '步骤固定值'
                            else:
                                ref = binding['ref']
                                source = {'task': '任务引用', 'environment': '环境引用', 'step': '前序步骤结果'}.get(ref['source'], '步骤引用')
                                if ref['source'] in {'task', 'environment'}:
                                    from taskweave.core.validation import pointer
                                    try:
                                        value = pointer(task_values if ref['source'] == 'task' else env, ref['pointer'])
                                    except TaskError:
                                        value = '未配置'
                                else:
                                    previous_steps = await self.controller.call('step.list', task_id=self.task_id)
                                    previous = next((f"{i+1}. {s['name']}" for i, s in enumerate(previous_steps) if s['step_id'] == ref['step_id']), '未知步骤')
                                    value = f"{previous} · {ref.get('output', 'data')}{ref['pointer']}（执行时读取）"
                                    try:
                                        from taskweave.core.validation import pointer
                                        result = await self.controller.call('run.output', run_id=run['run_id'], step_id=ref['step_id'], output=ref.get('output', 'data')) if run else await self.controller.previous_result(self.task_id, ref['step_id'], selected, output=ref.get('output', 'data'))
                                        value = pointer(result, ref['pointer'])
                                        source = f"前序结果 · {previous}（最近成功结果示例）"
                                    except TaskError:
                                        source = f"前序结果 · {previous}（暂无可用结果）"
                        ui.label(f'{key} = {document_text(value)} · {source}').classes('tw-code w-full').style('max-height: 10rem; overflow: auto')
            return form

        stored_inputs = await self.controller.execution_inputs(run['run_id']) if run else None
        supplied_task = stored_inputs['task'] if run else values
        supplied_step = stored_inputs['steps'].get(step['step_id'], {}) if run else values
        await render(environment.value or None, supplied_task, supplied_step)
        proxy = type('TrialInputs', (), {
            'replace': lambda _, selected, task_values, step_values: render(selected, task_values, step_values),
            'values': lambda _: {**form.values(), **step_form.values()},
            'task_values': lambda _: form.values(),
            'step_values': lambda _: step_form.values(),
            'task_edits': lambda _: {key: value for key, value in form.values().items() if value != form.defaults.get(key)},
            'step_edits': lambda _: {key: value for key, value in step_form.values().items() if value != step_form.defaults.get(key)},
            'apply_task_values': lambda _, values: form.apply_defaults(values),
            'apply_step_values': lambda _, values: step_form.apply_defaults(values),
            'task_form': property(lambda _: form),
            'step_form': property(lambda _: step_form),
        })()
        async def change(event):
            if getattr(environment, '_tw_skip_change', False):
                environment._tw_skip_change = False
                return
            edits = {key: value for key, value in form.values().items()
                     if key in form.controls and form.controls[key][1].value != form.defaults.get(key)}
            step_edits = {key: value for key, value in step_form.values().items()
                          if key in step_form.controls and step_form.controls[key][1].value != step_form.defaults.get(key)}
            await render(event.value or None, edits, step_edits)
        environment.on_value_change(change)
        return proxy

    def document(self):
        controls = self.edit_controls
        doc = normalize_step(self.old_step)
        doc.update(
            name=controls["name"].value,
            goal=controls["goal"].value,
            ai_authoring_notes=controls["ai_authoring_notes"].value,
            step_content=controls["code"].value,
            capabilities=sorted({action for plugin in (controls["caps"].value or []) for action in controls["plugin_actions"].get(plugin, [])}),
            input_schema=controls["schema"].schema(),
            delay_after_previous_seconds=(
                int(controls["delay"].value or 0)
                if float(controls["delay"].value or 0).is_integer()
                else controls["delay"].value
            ),
            timeout_ms=int(controls["timeout"].value or 60) * 1000,
        )
        doc["bindings"] = {}
        for name, source, value, source_step, output, ref_pointer in controls[
            "bindings"
        ]:
            key = name.value.strip()
            if not key or key in doc["bindings"]:
                raise TaskError("FORM_INVALID", "输入绑定名称不能为空或重复")
            if source.value == "literal":
                try:
                    literal = json.loads(value.value)
                except ValueError:
                    literal = value.value
                doc["bindings"][key] = {"literal": literal}
            else:
                ref = {"source": source.value, "pointer": ref_pointer.value}
                if source.value == "step":
                    if not source_step.value:
                        raise TaskError("FORM_INVALID", "请选择前序步骤")
                    ref.update(step_id=source_step.value, output=output.value or "data")
                doc["bindings"][key] = {"ref": ref}
        properties = (doc['input_schema'].setdefault('properties', {}) if doc['bindings']
                      else doc['input_schema'].get('properties', {}))
        for key, binding in doc['bindings'].items():
            if key not in properties:
                if 'literal' in binding:
                    from taskweave.desktop.dependencies import result_fields
                    kind = result_fields(binding['literal'])['']['type']
                else:
                    control = next(row[5] for row in controls['bindings'] if row[0].value.strip() == key)
                    kind = getattr(control, 'field_types', {}).get(binding['ref']['pointer'], 'string')
                properties[key] = {'type': kind}

        return doc

    async def save_editor(self):
        lock = getattr(self, 'save_lock', None)
        if lock is None:
            self.save_lock = lock = asyncio.Lock()
        async with lock:
            document = self.document()
            saved = await self.controller.save_draft(self.task_id, document, self.old_step)
            self.old_step = saved
            self.step_id = saved["step_id"]
            return saved

    async def mark_step_pending(self):
        """Reflect non-code step evidence changes without rebuilding the active page."""
        if not self.step_id:
            return
        self.old_step = await self.controller.call('step.get', step_id=self.step_id)
        if getattr(self, 'save_state', None) and not self.save_state.is_deleted:
            self.save_state.text = '已保存 · 待确认'
        control = getattr(self, 'selected_step_control', None)
        if control is not None and not control.is_deleted:
            control.props(remove='icon-right')
            control.props('icon-right=radio_button_checked text-color=grey-7')
            control.style('background:#ecfeff;color:#134e4a;box-shadow:inset 4px 0 #0f766e')

    async def refresh_trial_inputs(self, step, preserve_values=True):
        if not getattr(self, 'trial_variables_area', None) or self.trial_variables_area.is_deleted:
            return
        task_edits = step_edits = None
        if preserve_values and getattr(self, 'trial_form', None):
            try:
                task_edits = self.trial_form.task_edits()
                step_edits = self.trial_form.step_edits()
            except TaskError:
                # Keep the newly saved schema authoritative if an old JSON edit is incomplete.
                task_edits = step_edits = None
        self.trial_variables_area.clear()
        with self.trial_variables_area:
            self.trial_form = await self.trial_variables(
                step,
                self.trial_environment,
                values=None,
            )
        if task_edits or step_edits:
            await self.trial_form.replace(
                self.trial_environment.value or None,
                task_edits or {},
                step_edits or {},
            )

    async def editor(self):
        steps = await self.controller.call("step.list", task_id=self.task_id)
        if not steps:

            async def add_first():
                step = await self.controller.call(
                    "step.save",
                    task_id=self.task_id,
                    document={"name": "第一个步骤", "step_content": EMPTY},
                )
                self.step_id = step["step_id"]
                await self.paint()

            ui.label("任务暂无步骤。先添加步骤，再编写、调试和保存。").classes(
                "tw-panel"
            )
            self.button("添加步骤", add_first, primary=True)
            return
        if self.step_id not in {s["step_id"] for s in steps}:
            self.step_id = steps[0]["step_id"]
        step = next(s for s in steps if s["step_id"] == self.step_id)
        self.old_step = step
        self.selected_step_control = None
        self.context_entries = await self.controller.call("context.list", step_id=self.step_id)
        self.contexts = [entry["item"] for entry in self.context_entries]
        catalog = await self.controller.call("capabilities")
        with ui.row().classes("w-full items-start flex-wrap lg:flex-nowrap"):
            with ui.column().classes("tw-panel w-full lg:w-56 shrink-0"):
                toolbar = ui.row().classes("w-full flex-nowrap gap-1 shrink-0")
                with ui.column().classes("w-full overflow-y-auto gap-2").style("max-height: calc(100vh - 330px)"):
                    for i, item in enumerate(steps):
                        control = self.button(
                            f"{i + 1}. {item['name']}",
                            lambda s=item: self.navigate("editor", step_id=s["step_id"]),
                            flat=True,
                        )
                        validated = item['validation_state'] == 'VALIDATED'
                        control.props('icon-right=check' if validated else '')
                        control.props('text-color=white' if validated else 'text-color=grey-7')
                        control.classes("w-full justify-start text-left")
                        control.style("background: " + ('#16a34a; color: white' if validated else '#e5e7eb; color: #6b7280'))
                        if item['step_id'] == self.step_id:
                            self.selected_step_control = control
                            if validated:
                                control.style('box-shadow: inset 4px 0 #134e4a, 0 0 0 2px #99f6e4')
                            else:
                                control.classes('tw-selected')
                            control.props('icon-right=check_circle' if validated else 'icon-right=radio_button_checked')

                async def add():
                    await self.save_editor()
                    current_steps = await self.controller.call("step.list", task_id=self.task_id)
                    previous_capabilities = current_steps[-1]["capabilities"] if current_steps else []
                    selected_plugins = {cap.split(".", 1)[0] for cap in previous_capabilities}
                    available = ([item["id"] for item in catalog["actions"] + catalog["tools"]]
                                 + catalog["result_handlers"] + catalog["resource_providers"])
                    inherited = sorted(set(previous_capabilities) | {
                        cap for cap in available if cap.split(".", 1)[0] in selected_plugins
                    })
                    saved = await self.controller.call(
                        "step.save",
                        task_id=self.task_id,
                        document={"name": "新步骤", "step_content": EMPTY, "capabilities": inherited},
                    )
                    self.step_id, self.edit_controls = saved["step_id"], None
                    await self.paint()

                with toolbar:
                    self.button("+", add, flat=True).tooltip("添加步骤")
                for delta, label in [(-1, "上移"), (1, "下移")]:

                    async def reorder(d=delta):
                        await self.save_editor()
                        ids = [s["step_id"] for s in steps]
                        index = ids.index(self.step_id)
                        target = index + d
                        if 0 <= target < len(ids):
                            ids[index], ids[target] = ids[target], ids[index]
                            await self.controller.call(
                                "step.reorder", task_id=self.task_id, step_ids=ids
                            )
                            self.edit_controls = None
                            await self.paint()

                    with toolbar:
                        self.button("↑" if delta < 0 else "↓", reorder, flat=True).tooltip(label)

                async def delete():
                    with ui.dialog() as dialog, ui.card():
                        ui.label("移除当前步骤？其他步骤若引用它，将阻止删除。")
                        with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                            ui.button("取消", on_click=lambda: dialog.submit(False))
                            ui.button("移除", on_click=lambda: dialog.submit(True))
                    if await dialog:
                        ids = [item["step_id"] for item in steps]
                        index = ids.index(self.step_id)
                        await self.controller.call("step.delete", step_id=self.step_id)
                        remaining = [item for item in ids if item != self.step_id]
                        self.step_id = remaining[index - 1] if index > 0 else (remaining[0] if remaining else None)
                        self.edit_controls = None
                        await self.paint()

                with toolbar:
                    self.button("−", delete, flat=True).tooltip("移除步骤")

                async def confirm_all():
                    await self.save_editor()
                    current = await self.controller.call("step.list", task_id=self.task_id)
                    invalid = []
                    for candidate in current:
                        validation = await self.controller.call("step.validate", step_id=candidate["step_id"])
                        if not validation["valid"]:
                            invalid.append(candidate)
                    if invalid:
                        self.step_id, self.edit_controls = invalid[0]["step_id"], None
                        await self.paint()
                        raise TaskError("PLUGIN_LINT_FAILED", "存在未通过校验的步骤：" + "、".join(item["name"] for item in invalid))
                    for candidate in current:
                        if candidate["validation_state"] != "VALIDATED":
                            await self.controller.call("step.confirm.manual", step_id=candidate["step_id"], expected_hash=candidate["content_hash"], environment_id=None)
                    self.edit_controls = None
                    await self.paint()
                    ui.notify("全部步骤已确认", type="positive")

                with toolbar:
                    self.button("✓", confirm_all, flat=True).tooltip("一键确认全部步骤")
            with ui.column().classes("tw-panel tw-content w-full").style('transition: margin-right .2s ease') as editor_panel:
                async def toggle_debug_drawer():
                    opening = not debug_panel.visible
                    if opening:
                        saved = await self.save_editor()
                        await self.refresh_trial_inputs(saved, preserve_values=False)
                    debug_panel.set_visibility(opening)
                    editor_panel.style('margin-right: 720px' if opening else 'margin-right: 0')

                with ui.tabs().classes("w-full") as tabs:
                    self.editor_tabs = tabs
                    content = ui.tab("步骤详情")
                    action = ui.tab("动作表单")
                    bindings = ui.tab("输入依赖")
                    settings = ui.tab("时间设置")
                    trial = content  # Debug is a drawer; callbacks keep the editor visible.
                with ui.tab_panels(tabs, value=content).classes("w-full"):
                    with ui.tab_panel(content):
                        with ui.row().classes("w-full justify-end items-center gap-2"):
                            self.button('调试', toggle_debug_drawer)
                            self.save_state = ui.label("已保存").classes("tw-save-state text-sm text-gray-500")
                        name = ui.input("步骤名称", value=step["name"]).classes(
                            "w-full"
                        )
                        with ui.row().classes('w-full items-center justify-between gap-2'):
                            ui.label('步骤描述').classes('font-medium')
                            self.button('AI 生成步骤描述', self.generate_goal_dialog)
                        goal = ui.textarea(
                            value=step["goal"],
                            placeholder='描述本步骤的前置状态、操作、成功标准、输出和展示要求',
                        ).props('autogrow').classes("w-full")
                        ai_authoring_notes = ui.textarea(
                            'AI 编写说明',
                            value=step.get('ai_authoring_notes', ''),
                            placeholder='长期提供给 AI 的特殊规则，例如：点击后异步刷新表格，应以结果出现作为成功标准。',
                        ).props('autogrow').classes('w-full')
                        plugin_actions = {plugin: [] for plugin in catalog["versions"]}
                        for item in catalog["actions"]:
                            plugin = item["id"].split(".", 1)[0]
                            plugin_actions.setdefault(plugin, []).append(item["id"])
                        for capability in ([item['id'] for item in catalog['tools']] + catalog['result_handlers'] + catalog['resource_providers']):
                            plugin_actions.setdefault(capability.split('.',1)[0], []).append(capability)
                        selected_plugins = sorted({c.split(".", 1)[0] for c in step["capabilities"]})
                        for capability in step["capabilities"]:
                            plugin = capability.split(".", 1)[0]
                            if plugin not in catalog["versions"]:
                                plugin_actions.setdefault(plugin, []).append(capability)
                        options = {plugin: plugin + ("（当前不可用）" if plugin not in catalog["versions"] else "") for plugin in plugin_actions}
                        caps = (
                            ui.select(
                                options,
                                label="使用的插件",
                                multiple=True,
                                value=selected_plugins,
                            )
                            .props("use-chips")
                            .classes("w-full")
                        )
                        ui.label(
                            "可直接手写，也可生成后手动修改；AI 建议等待采纳。"
                        ).classes("text-gray-500")
                        with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                            self.button("AI 生成内容", self.choose_generation_mode)
                            self.button("采集插件上下文", self.collect_context)
                        self.context_panel = ui.column().classes("w-full")
                        self.render_collected_contexts()
                        code = ui.codemirror(
                            step["step_content"], language="Python", line_wrapping=True
                        ).classes("w-full border rounded")
                        with ui.row():

                            async def lint():
                                saved = await self.save_editor()
                                value = await self.controller.call(
                                    "step.validate", step_id=saved["step_id"]
                                )
                                ui.notify(
                                    "校验通过"
                                    if value["valid"]
                                    else document_text(value["diagnostics"])
                                )

                            self.button("校验内容", lint)
                            self.button("确认验证并保存", self.confirm)
                    with ui.tab_panel(action):
                        actions = {a["id"]: a for a in catalog["actions"]}
                        selection = ui.select(
                            list(actions),
                            label="插件动作",
                            value=next(iter(actions), None),
                        ).classes("w-full")
                        form_area = ui.column().classes("w-full")
                        active_form = [None]

                        def action_form():
                            form_area.clear()
                            with form_area:
                                if selection.value:
                                    spec = actions[selection.value]
                                    ui.label(spec["description"])
                                    active_form[0] = ValueForm(spec["input_schema"])

                        selection.on_value_change(lambda _: action_form())
                        action_form()

                        async def insert():
                            if not selection.value:
                                raise TaskError("CAPABILITY_UNAVAILABLE")
                            values = active_form[0].values()
                            invocation = f"    value = await ctx.call({selection.value!r}, {values!r})\n"
                            lines = code.value.splitlines(True)
                            return_index = next(
                                (
                                    i
                                    for i, line in enumerate(lines)
                                    if line.startswith("    return ")
                                ),
                                len(lines),
                            )
                            lines.insert(return_index, invocation)
                            code.value = "".join(lines)
                            if "return ctx.result(data=inputs)" in code.value:
                                code.value = code.value.replace(
                                    "return ctx.result(data=inputs)",
                                    "return ctx.result(data=value)",
                                )
                            caps.value = sorted(
                                set(caps.value or []) | {selection.value.split(".", 1)[0]}
                            )
                            tabs.value = content

                        self.button("插入到步骤内容", insert, primary=True)
                    with ui.tab_panel(bindings):
                        schema = SchemaEditor(step["input_schema"])
                        ui.label("选择输入来源即可；保存绑定时自动补充输入参数，无需先添加参数。")
                        binding_area = ui.column().classes("w-full")
                        binding_rows = []
                        previous = {
                            s["step_id"]: s["name"]
                            for s in steps
                            if s["position"] < step["position"]
                        }

                        async def add_binding(key="", binding=None):
                            binding = binding or {"literal": ""}
                            ref = binding.get("ref", {})
                            with binding_area:
                                with ui.column().classes(
                                    "border rounded p-3 w-full"
                                ) as row:
                                    with ui.row().classes("w-full"):
                                        key_input = ui.input("步骤输入名称", value=key)
                                        source = ui.select(
                                            {
                                                "literal": "固定值",
                                                "step": "前序结果",
                                                "task": "任务参数",
                                                "environment": "环境配置",
                                            },
                                            label="来源",
                                            value=ref.get("source", "literal"),
                                        )
                                        literal = ui.input(
                                            "固定值（文本或 JSON 值）",
                                            value=document_text(
                                                binding.get("literal", "")
                                            ),
                                        )
                                    with ui.row().classes("w-full"):
                                        source_step = ui.select(
                                            previous,
                                            label="前序步骤",
                                            value=ref.get("step_id"),
                                        ).classes("w-48")
                                        output = ui.input(
                                            "结果容器（通常为 data）", value=ref.get("output", "data")
                                        )
                                        ref_pointer = ui.select(
                                            {ref.get("pointer", ""): ref.get("pointer", "") or "全部结果"},
                                            label="结果字段（可选择或填写 /字段名）",
                                            value=ref.get("pointer", ""), with_input=True, new_value_mode="add-unique",
                                        ).classes("min-w-64")
                                    preview = ui.label().classes("text-xs text-gray-500 tw-code w-full")
                                    record = (
                                        key_input,
                                        source,
                                        literal,
                                        source_step,
                                        output,
                                        ref_pointer,
                                    )
                                    binding_rows.append(record)
                                    async def update_fields():
                                        literal.set_visibility(source.value == 'literal')
                                        source_step.set_visibility(source.value == 'step')
                                        output.set_visibility(source.value == 'step')
                                        ref_pointer.set_visibility(source.value != 'literal')
                                        preview.set_visibility(source.value == 'step')
                                        if source.value != 'step' or not source_step.value:
                                            return
                                        try:
                                            result = await self.controller.previous_result(self.task_id, source_step.value, self.environment_id or None, output=output.value or 'data')
                                        except TaskError as exc:
                                            if exc.code != 'OUTPUT_NOT_AVAILABLE':
                                                raise
                                            preview.text = '尚无成功结果；可以填写 /字段名。运行时从本次任务 DB 读取。'
                                            return
                                        from taskweave.desktop.dependencies import result_fields
                                        fields = result_fields(result)
                                        ref_pointer.field_types = {path: item['type'] for path, item in fields.items()}
                                        options = {path: item['label'] for path, item in fields.items()}
                                        if ref_pointer.value not in options:
                                            options[ref_pointer.value] = ref_pointer.value or '全部结果'
                                        ref_pointer.options = options
                                        ref_pointer.update()
                                        preview.text = '字段与示例值来自最近成功运行；执行仍读取本次运行结果。'

                                    async def choose_field(event):
                                        if source.value == 'step' and not key_input.value and event.value:
                                            key_input.value = event.value.rsplit('/', 1)[-1].replace('~1', '/').replace('~0', '~')
                                    source.on_value_change(lambda _: update_fields())
                                    source_step.on_value_change(lambda _: update_fields())
                                    output.on_value_change(lambda _: update_fields())
                                    ref_pointer.on_value_change(choose_field)
                                    await update_fields()


                                    def remove():
                                        binding_rows.remove(record)
                                        row.delete()

                                    ui.button("移除此绑定", on_click=remove).props(
                                        "flat"
                                    )

                        for key, binding in step["bindings"].items():
                            await add_binding(key, binding)
                        ui.button("添加绑定", on_click=lambda: add_binding()).props(
                            "outline"
                        )
                        ui.label(
                            "前序结果从本次运行的任务数据库读取，不依赖内存。"
                        ).classes("text-gray-500")
                    with ui.tab_panel(settings):
                        delay = ui.number(
                            "上一步成功后等待（秒）",
                            value=step["delay_after_previous_seconds"],
                            min=0,
                            max=86400,
                            step=1,
                        ).classes("w-full")
                        if step["position"] == 0:
                            delay.disable()
                            ui.label("首步骤无上一步，不等待。")
                        else:
                            ui.label(
                                "默认 0 秒；单步和继续也遵守间隔，已等待足够时间则立即执行。"
                            )
                        timeout = ui.number(
                            "步骤执行超时（秒，不包含间隔）",
                            value=step["timeout_ms"] // 1000,
                            min=1,
                            max=3600,
                            step=1,
                        ).classes("w-full")
                        self.button("保存步骤设置", self.save_editor, primary=True)
                with ui.column().classes('fixed right-0 top-0 bottom-0 bg-white border-l shadow-lg p-4 gap-3').style('width: min(720px, 92vw); z-index: 3000; overflow-y: auto') as debug_panel:
                    with ui.row().classes('w-full items-center justify-between gap-2'):
                        with ui.column().classes('gap-0'):
                            ui.label('调试 · ' + step['name']).classes('text-lg font-medium')
                            ui.label('浏览器与插件资源由本任务的调试实例保留').classes('text-xs text-gray-500')
                        async def close_debug_drawer():
                            debug_panel.set_visibility(False)
                            editor_panel.style('margin-right: 0')
                        ui.button(icon='close', on_click=close_debug_drawer).props('flat round aria-label=收起调试').tooltip('收起调试')
                    with ui.row().classes('w-full items-center gap-2 flex-wrap'):
                        ui.label('步骤插件上下文').classes('font-medium')
                        self.button('采集插件上下文', lambda: self.collect_context(source_page='trial_feedback'))
                    self.trial_context_panel = ui.column().classes('w-full')
                    self.render_collected_contexts(self.trial_context_panel)
                    self.trial_ai_supplement = ui.textarea(
                        'AI 补充说明（可选）',
                        value=getattr(self, 'debug_supplements', {}).get(self.step_id, ''),
                        placeholder='仅用于当前调试轮次，例如：点击结果后会打开新标签页。',
                    ).props('debounce=50').classes('w-full')
                    def remember_supplement(event, step_id=self.step_id):
                        self.debug_supplements[step_id] = event.value or ''
                    self.trial_ai_supplement.on_value_change(remember_supplement)
                    environment = await self.environment_select()
                    self.trial_environment = environment
                    self.trial_variables_area = ui.column().classes('w-full')
                    with self.trial_variables_area:
                        self.trial_form = await self.trial_variables(step, environment)
                    self.trial_start_status = ui.label().classes('text-sm text-gray-500')
                    self.trial_actions = {}
                    with ui.row().classes('w-full items-center gap-2 flex-wrap'):
                        self.trial_actions['single'] = self.button('调试当前步骤', lambda: self.start_trial(tabs, trial, continue_session=True), flat=True)
                        self.trial_actions['flow'] = self.button('从选定步骤调试', self.start_flow_trial, flat=True)
                        self.trial_actions['end'] = self.button('结束调试', self.end_trial, flat=True)
                        self.button('AI 修复', lambda control=self.trial_ai_supplement: self.choose_trial_ai(control)).classes('w-44')
                        self.button('清空 AI 修复上下文', self.new_debug_round).classes('w-44')
                    for control in self.trial_actions.values():
                        control.classes('w-44')
                        self.style_trial_action(control)
                        self.trial_area = ui.column().classes("w-full")
                        ui.timer(1, self.refresh_trial)
                debug_panel.set_visibility(step['validation_state'] != 'VALIDATED')
                if debug_panel.visible:
                    editor_panel.style('margin-right: 720px')
                self.edit_controls = {
                    "name": name,
                    "goal": goal,
                    "ai_authoring_notes": ai_authoring_notes,
                    "code": code,
                    "caps": caps,
                    "plugin_actions": plugin_actions,
                    "schema": schema,
                    "delay": delay,
                    "timeout": timeout,
                    "bindings": binding_rows,
                }
                current_tab = [tabs.value]
                changing_tab = [False]

                async def save_on_tab_change(event):
                    if changing_tab[0] or not self.edit_controls:
                        return
                    previous = current_tab[0]
                    try:
                        saved = await self.save_editor()
                        current_tab[0] = event.value
                        if event.value == trial or event.value == getattr(trial, 'name', None) or event.value == '调试':
                            await self.refresh_trial_inputs(saved)
                    except (TaskError, ValueError, TypeError) as exc:
                        changing_tab[0] = True
                        tabs.value = previous
                        changing_tab[0] = False
                        ui.notify("当前页面内容尚未生效：" + str(exc), type="negative", timeout=8000)

                tabs.on_value_change(save_on_tab_change)
                self._autosave_snapshot = normalize_step(self.document())
                self._autosave_running = False

                async def autosave():
                    if self.page != "editor" or not self.edit_controls or self._autosave_running:
                        return
                    try:
                        current = normalize_step(self.document())
                    except (TaskError, ValueError, TypeError):
                        return
                    if current == self._autosave_snapshot:
                        return
                    self._autosave_running = True
                    self.save_state.text = "正在保存…"
                    try:
                        await self.save_editor()
                        self._autosave_snapshot = normalize_step(self.document())
                        self.save_state.text = "已保存 · 待确认"
                    except Exception:
                        self.save_state.text = "保存失败，点击重试"
                        self.save_state.classes("text-red-700")
                    finally:
                        self._autosave_running = False

                ui.timer(1.0, autosave)
        await self.refresh_trial()

    async def end_trial(self):
        rid = self.trials.get(self.step_id)
        if not rid:
            return
        run = await self.controller.call('run.get', run_id=rid)
        if not run.get('can_end') or not await self.confirm_end(run):
            return
        try:
            run = await self.controller.call('run.get', run_id=rid)
            if not run.get('can_end'):
                await self.refresh_trial()
                return
            operation = 'cancel' if run['status'] == 'RUNNING' else 'abandon'
            try:
                await self.controller.call('run.control', run_id=rid, command_id=command_id(), operation=operation)
            except TaskError as exc:
                if operation != 'cancel' or exc.code != 'RUN_STATE_INVALID':
                    raise
                # Execution can finish while the end confirmation is open.
                await self.controller.call('run.control', run_id=rid, command_id=command_id(), operation='abandon')
            self.style_trial_action(self.trial_actions['end'], 'SUCCEEDED')
        except Exception:
            self.style_trial_action(self.trial_actions['end'], 'FAILED')
            raise
        self.trial_signature = None
        await self.refresh_trial()

    async def start_flow_trial(self):
        saved = await self.save_editor()
        steps = await self.controller.call('step.list', task_id=self.task_id)
        eligible = [step for step in steps if step['position'] <= saved['position']]
        with ui.dialog() as dialog, ui.card().classes('w-full max-w-2xl'):
            ui.label('从选定步骤调试到当前步骤').classes('text-lg')
            start = ui.select({step['step_id']: f"{i + 1}. {step['name']}" for i, step in enumerate(eligible)}, value=eligible[0]['step_id'], label='开始步骤').classes('w-full')
            ui.label('默认从第一步开始。使用上方环境和本次输入，按本次调试结果传递依赖。').classes('text-gray-500')
            async def launch():
                if getattr(self, 'trial_start_status', None) and not self.trial_start_status.is_deleted:
                    self.trial_start_status.text = '正在等待执行器和插件响应…'
                run = await self.controller.call('step.trial.flow', step_id=saved['step_id'],
                    inputs=self.trial_form.task_values(), step_inputs={saved['step_id']: self.trial_form.step_values()},
                    environment_id=self.trial_environment.value or None, command_id=command_id(), defer_inputs=True,
                    start_step_id=start.value)
                self.trials[saved['step_id']] = run['run_id']
                dialog.close()
                await self.settle_trial_start(run['run_id'])
            with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                self.button('开始调试', launch, primary=True)
                ui.button('取消', on_click=dialog.close).props('outline')
        dialog.open()

    async def enter_debug(self, tabs, trial_tab):
        saved = await self.save_editor()
        await self.refresh_trial_inputs(saved)
        self.controller.reset_debug_conversation(saved['step_id'])
        self.debug_round_fresh = True
        self.debug_feedback = None
        self.debug_feedback_run_id = None
        self.debug_removed_feedback = set()
        self.debug_supplements.pop(saved['step_id'], None)
        self.trial_signature = None
        tabs.value = trial_tab
        await self.refresh_trial()

    async def start_trial(self, tabs, trial_tab, continue_session=False):
        if getattr(self, 'trial_start_status', None) and not self.trial_start_status.is_deleted:
            self.trial_start_status.text = '正在等待执行器和插件响应…'
        saved = await self.save_editor()
        self.debug_round_fresh = False
        self.debug_feedback = None
        self.debug_feedback_run_id = None
        self.debug_removed_feedback = set()
        if continue_session:
            previous_id = self.trials.get(saved["step_id"])
            if previous_id:
                previous = await self.controller.call("run.get", run_id=previous_id)
                if previous.get('can_end') and previous['environment_id'] != (self.trial_environment.value or None):
                    if not await self.confirm_end(previous):
                        return
                    await self.controller.call('run.control', run_id=previous_id, command_id=command_id(), operation='abandon')
                if previous.get('can_end') and previous['status'] != 'CANCELLED' and previous['environment_id'] == (self.trial_environment.value or None):
                    waiting = json.loads(previous.get('request_json', '{}')).get('waiting_input')
                    if waiting:
                        if waiting['scope'] == 'step' and waiting['step_id'] != saved['step_id']:
                            ui.notify('请先填写下方等待步骤的输入，再继续。')
                            return
                        values = self.trial_form.task_values() if waiting['scope'] == 'task' else self.trial_form.step_values()
                        await self.resume_inputs(previous, values)
                        await self.refresh_trial()
                        return
                    uncertain = any(a['valid'] and (a['status'] == 'UNKNOWN' or (a['status'] == 'FAILED' and a['effect_state'] in {'UNKNOWN', 'SUCCEEDED'})) for a in previous['attempts'])
                    if uncertain:
                        with ui.dialog() as retry_dialog, ui.card().classes('w-full max-w-xl'):
                            ui.label('保留当前页面并再次调试？').classes('text-lg')
                            ui.label('上次操作结果未确认，请先检查当前页面；再次执行可能重复点击或提交。浏览器会保留，上次失败记录不会被改写。')
                            with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                                ui.button('确认再次调试', on_click=lambda: retry_dialog.submit(True))
                                ui.button('取消', on_click=lambda: retry_dialog.submit(False)).props('outline')
                        if not await retry_dialog:
                            return
                    run = await self.controller.repeat_trial(saved, previous_id, overrides=self.trial_form.values())
                    self.trials[saved['step_id']] = run['run_id']
                    self.environment_id = previous['environment_id']
                    tabs.value = trial_tab
                    await self.settle_trial_start(run['run_id'])
                    return
            run = await self.controller.trial(saved, self.trial_form.values(), self.trial_environment.value or None)
            self.trials[saved['step_id']] = run['run_id']
            tabs.value = trial_tab
            await self.settle_trial_start(run['run_id'])
            return
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-2xl"):
            ui.label("调试有效输入").classes("text-lg")
            ui.label("前序结果依赖在此填写实际值；调试不会执行其他步骤。")
            environment = await self.environment_select()
            form = await self.trial_variables(saved, environment)

            async def launch():
                run = await self.controller.trial(
                    saved, form.values(), environment.value or None
                )
                self.trials[saved["step_id"]] = run["run_id"]
                self.environment_id = environment.value
                if self.trial_environment.value != environment.value:
                    self.trial_environment._tw_skip_change = True
                    self.trial_environment.value = environment.value
                await self.trial_form.replace(environment.value or None, form.task_values(), form.step_values())
                dialog.close()
                tabs.value = trial_tab
                self.trial_signature = None
                await self.settle_trial_start(run['run_id'])

            with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                self.button("开始调试", launch, primary=True)
                ui.button("取消", on_click=dialog.close).props("outline")
        dialog.open()

    async def settle_trial_start(self, run_id, timeout=0.8):
        """Let immediate input validation finish so a required-input dialog appears now."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            current = await self.controller.call('run.get', run_id=run_id)
            request = json.loads(current.get('request_json', '{}'))
            if current['status'] != 'RUNNING' or request.get('waiting_input') or current.get('attempts'):
                break
            await asyncio.sleep(0.05)
        self.trial_signature = None
        await self.refresh_trial()
        if getattr(self, 'trial_start_status', None) and not self.trial_start_status.is_deleted:
            self.trial_start_status.text = ''

    async def resume_inputs(self, run, values, step_inputs=None):
        from taskweave.core.validation import validate
        waiting = json.loads(run['request_json'])['waiting_input']
        validate(values, waiting['schema'])
        await self.controller.call('run.inputs', run_id=run['run_id'], command_id=command_id(), inputs=values, **({'step_inputs': step_inputs} if step_inputs is not None else {}))
        if self.page == 'editor' and getattr(self, 'trial_form', None):
            if waiting['scope'] == 'task':
                self.trial_form.apply_task_values(values)
            elif waiting['step_id'] == self.step_id:
                self.trial_form.apply_step_values(values)
        command = json.loads(run['request_json']).get('last_command', {})
        await self.controller.call('run.start', run_id=run['run_id'], command_id=command_id(),
            mode=command.get('mode', 'ALL'), target_step_id=command.get('target'))
        self.run_signature = self.trial_signature = None

    async def pending_inputs(self, run):
        if not run or run['status'] != 'PAUSED':
            return
        waiting = json.loads(run['request_json']).get('waiting_input')
        if not waiting:
            return
        token = (run['run_id'], waiting.get('id'), waiting['scope'], waiting.get('step_id'))
        if getattr(self, 'input_dialog_token', None) == token and getattr(self, 'input_dialog', None) and not self.input_dialog.is_deleted:
            self.button('补充必录参数', self.input_dialog.open, primary=True)
            return
        previous_dialog = getattr(self, 'input_dialog', None)
        if previous_dialog is not None and not previous_dialog.is_deleted:
            previous_dialog.delete()
        self.input_dialog_token = token
        with self.content if hasattr(self, 'content') else ui.column():
            dialog = ui.dialog()
        with dialog, ui.card().classes('w-full max-w-xl'):
            self.input_dialog = dialog
            title = '任务运行输入' if waiting['scope'] == 'task' else '当前步骤输入'
            ui.label(title + ' · 补充必录参数').classes('font-medium')
            definition = json.loads(run['definition_json'])['steps']
            current = next(step for step in definition if step['step_id'] == waiting['step_id'])
            environment = type('FixedEnvironment', (), {'value': run['environment_id'], 'on_value_change': lambda *args: None})()
            form = await self.trial_variables(current, environment, run=run, focus=None if waiting['scope'] == 'task' else 'step', readonly_other=waiting['scope'] != 'task')
            if waiting['scope'] == 'task':
                form.apply_task_values(waiting['values'])
            else:
                form.apply_step_values(waiting['values'])
            async def resume():
                step_inputs = None
                if waiting['scope'] == 'task':
                    editable_schema = {**current['input_schema'], 'properties': {key: spec for key, spec in current['input_schema'].get('properties', {}).items() if key not in current['bindings']}, 'required': [key for key in current['input_schema'].get('required', []) if key not in current['bindings']]}
                    from taskweave.core.validation import validate
                    validate(form.step_values(), {**editable_schema, 'additionalProperties': True})
                    step_inputs = {current['step_id']: form.step_values()}
                await self.resume_inputs(run, form.task_values() if waiting['scope'] == 'task' else form.step_values(), step_inputs=step_inputs)
                dialog.close()
            with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                submit = ui.button('提交输入并继续', on_click=resume).props('outline')
                ui.button('稍后填写', on_click=dialog.close).props('outline')
            validation_hint = ui.label().classes('text-sm text-red-700')
            def update_submit(_=None):
                from taskweave.core.validation import validate
                try:
                    values = form.task_values() if waiting['scope'] == 'task' else form.step_values()
                    validate(values, waiting['schema'])
                    if waiting['scope'] == 'task':
                        editable_schema = {**current['input_schema'], 'properties': {key: spec for key, spec in current['input_schema'].get('properties', {}).items() if key not in current['bindings']}, 'required': [key for key in current['input_schema'].get('required', []) if key not in current['bindings']]}
                        validate(form.step_values(), {**editable_schema, 'additionalProperties': True})
                    submit.enable()
                    validation_hint.text = ''
                except (TaskError, ValueError, TypeError) as exc:
                    submit.disable()
                    required = list(waiting['schema'].get('required', []))
                    values = form.task_values() if waiting['scope'] == 'task' else form.step_values()
                    missing = [key for key in required if key not in values or values[key] in (None, '')]
                    if waiting['scope'] == 'task':
                        step_values = form.step_values()
                        missing.extend(key for key in editable_schema.get('required', []) if key not in step_values or step_values[key] in (None, ''))
                    validation_hint.text = ('请补充必填字段：' + '、'.join(missing)) if missing else ('输入格式不正确：' + str(exc))
            for value_form in (form.task_form, form.step_form):
                for _, control in value_form.controls.values():
                    if hasattr(control, 'on_value_change'):
                        control.on_value_change(update_submit)
            update_submit()
        self.button('补充必录参数', dialog.open, primary=True)
        dialog.open()

    async def refresh_trial(self):
        if (
            self.page != "editor"
            or not self.edit_controls
            or self.trial_area.is_deleted
        ):
            return
        run_id = self.trials.get(self.step_id)
        if not run_id:
            runs = await self.controller.call("run.list", task_id=self.task_id)
            previous = next((r for r in reversed(runs) if r.get("trial_step_id") == self.step_id), None)
            if previous:
                run_id = previous["run_id"]
                self.trials[self.step_id] = run_id
        run = await self.controller.call("run.get", run_id=run_id) if run_id else None
        if getattr(self, 'trial_actions', None):
            self.trial_actions['end'].set_enabled(bool(run and run.get('can_end')))
            if run:
                kind = 'flow' if json.loads(run['request_json']).get('flow_trial') else 'single'
                state = run['status']
                self.style_trial_action(self.trial_actions[kind], state)
        signature = document_text({'run': run, 'fresh_round': bool(getattr(self, 'debug_round_fresh', False))})
        if signature == getattr(self, "trial_signature", None):
            return
        self.trial_signature = signature
        self.trial_area.clear()
        with self.trial_area:
            if getattr(self, 'debug_round_fresh', False):
                ui.label('AI 修复上下文已清空。调试实例、插件资源和运行记录继续保留。')
                return
            await self.pending_inputs(run)
            if not run_id:
                ui.label("暂无调试记录。修改后请重新调试，再确认保存。")
                return
            ui.label("调试状态：" + STATUS.get(run["status"], run["status"]))
            names = step_names(run, await self.controller.call("step.list", task_id=self.task_id))
            for attempt in run["attempts"]:
                ui.label(
                    f"{names.get(attempt['step_id'], '未知步骤')} · 尝试 {attempt['attempt_no']} · {STATUS.get(attempt['status'], attempt['status'])}"
                )
                if attempt["error_code"]:
                    ui.label(
                        f"{attempt['error_code']}：{attempt['error_summary']}"
                    ).classes("text-red-700")
                if attempt["status"] == "SUCCEEDED":
                    value = await self.controller.call(
                        "run.output", run_id=run_id, step_id=attempt["step_id"]
                    )
                    ui.code(document_text(value), language="json").classes("w-full")
                if any(ref['attempt_id'] == attempt['attempt_id'] for ref in run['results']):
                    result_step = {'step_id': attempt['step_id'], 'name': names.get(attempt['step_id'], '步骤')}
                    self.button('查看结果', lambda r=run, st=result_step, aid=attempt['attempt_id']: self.step_result_dialog(r, st, aid))
            failed_other = next((a for a in reversed(run['attempts']) if a['valid'] and a['status'] in {'FAILED', 'UNKNOWN'} and a['step_id'] != self.step_id), None)
            if failed_other:
                failed_name = names.get(failed_other['step_id'], '未知步骤')
                with ui.row().classes('w-full items-center gap-2 border border-red-200 bg-red-50 rounded p-3'):
                    ui.label('失败步骤：' + failed_name).classes('text-red-700 font-medium')
                    async def open_failed(step_id=failed_other['step_id'], rid=run_id):
                        await self.navigate_step_debug(self.task_id, step_id, run_id=rid, preserve_repair=True)
                    self.button('打开失败步骤', open_failed)
            failed = next((a for a in reversed(run['attempts']) if a['valid'] and a['status'] in {'FAILED', 'UNKNOWN'} and a['step_id'] == self.step_id), None)
            if failed:
                feedback = await self.controller.trial_feedback(run_id, self.step_id)
                self.debug_feedback = feedback
                self.debug_feedback_run_id = run_id
                removed = getattr(self, 'debug_removed_feedback', set())
                self.debug_removed_feedback = removed
                with ui.expansion('本次报错上下文', icon='error_outline').classes('w-full border rounded'):
                    ui.label('下列内容默认提供给 AI；删除只影响本轮 AI 请求，不删除运行记录。').classes('text-sm text-gray-500')
                    for key, title in [
                        ('executed_step_content', '本次实际执行的步骤内容'),
                        ('failed_action', '失败动作'),
                        ('failure_snapshots', '失败快照'),
                        ('trial_logs', '本次调试日志'),
                    ]:
                        value = feedback.get(key)
                        if key in removed or not value:
                            continue
                        with ui.expansion(title).classes('w-full'):
                            with ui.row().classes('w-full justify-end'):
                                def remove_error_part(part=key):
                                    self.debug_removed_feedback.add(part)
                                    self.trial_signature = None
                                ui.button(icon='delete', on_click=remove_error_part).props('flat round color=negative').tooltip('不再发送给 AI')
                            ui.code(document_text(value), language='json').classes('w-full tw-code')
            events = await self.controller.call("run.events", run_id=run_id)
            if events:
                with ui.expansion("调试日志").classes("w-full"):
                    ui.code(document_text(readable_metadata(events, names)), language="json").classes("w-full")

    async def choose_trial_ai(self, supplement_control=None):
        step_key = getattr(self, 'step_id', None)
        with ui.dialog() as dialog, ui.card().classes('w-full max-w-xl'):
            ui.label('选择 AI 修复方式').classes('text-lg')
            feedback = getattr(self, 'debug_feedback', None) or {}
            if feedback.get('run_id') and feedback.get('attempt_id'):
                ui.label(
                    '修复依据：Trial ' + feedback['run_id'][:8]
                    + ' · Attempt ' + feedback['attempt_id'][:8]
                ).classes('text-sm text-gray-500')
            rounds = ui.select({-1: '全部历史', 0: '不带历史', **{i: f'最近 {i} 轮' for i in range(1, 11)}}, value=-1, label='本轮携带的历史会话').classes('w-full')
            deduplicate = ui.checkbox('精简重复静态字段', value=True)
            supplement = ui.textarea('本轮补充说明（可编辑）', value=(supplement_control.value or '') if supplement_control is not None else getattr(self, 'debug_supplements', {}).get(step_key, '')).classes('w-full')
            ui.label('API 直接生成修复建议；Chat 生成可复制到网页端的提示内容。').classes('text-gray-500')
            with ui.row().classes('w-full items-center gap-2 flex-wrap'):
                ui.button('API 修复', on_click=lambda: dialog.submit(('api', rounds.value, deduplicate.value, supplement.value or ''))).props('outline')
                ui.button('Chat 网页修复', on_click=lambda: dialog.submit(('chat', rounds.value, deduplicate.value, supplement.value or ''))).props('outline')
                ui.button('取消', on_click=lambda: dialog.submit(None)).props('outline')
        choice = await dialog
        if choice is not None:
            # Older callers and lightweight UI tests may submit only a mode.
            if isinstance(choice, str):
                mode, history_rounds, dedup, supplement_text = choice, -1, True, ''
            elif len(choice) == 3:
                mode, history_rounds, dedup = choice
                supplement_text = ''
            else:
                mode, history_rounds, dedup, supplement_text = choice
            if not hasattr(self, 'debug_supplements'):
                self.debug_supplements = {}
            self.debug_supplements[step_key] = supplement_text
            if supplement_control is not None:
                supplement_control.value = supplement_text
            await self.generate(fix_logs=True, web_chat=mode == 'chat', supplement_override=supplement_text, history_rounds=history_rounds, deduplicate_history=dedup)

    async def confirm(self):
        saved = await self.save_editor()
        run_id = self.trials.get(saved["step_id"])
        confirmed = None
        if run_id:
            try:
                confirmed = await self.controller.confirm(saved, run_id)
            except TaskError as exc:
                if exc.code != 'VALIDATION_EVIDENCE_INVALID':
                    raise
        if confirmed is None:
            with ui.dialog() as dialog, ui.card().classes('w-full max-w-xl'):
                ui.label('当前步骤内容尚未调试通过，是否手动确认验证通过并保存？')
                with ui.row().classes('w-full items-center gap-2 flex-wrap'):
                    ui.button('取消', on_click=lambda: dialog.submit(False)).props('outline')
                    ui.button('确认验证通过并保存', on_click=lambda: dialog.submit(True)).props('outline text-color=teal-8').style('background: #f0fdfa; border: 1px solid #0f766e')
            if not await dialog:
                return
            confirmed = await self.controller.call('step.confirm.manual', step_id=saved['step_id'], expected_hash=saved['content_hash'], environment_id=self.environment_id or None)
        self.old_step = confirmed
        ui.notify("步骤验证并保存成功", type="positive")
        self.edit_controls = None
        await self.paint()

    async def generate(self, fix_logs=False, web_chat=False, supplement_override=None, history_rounds=None, deduplicate_history=True):
        supplement = (supplement_override if supplement_override is not None else getattr(self, 'debug_supplements', {}).get(self.step_id, '')) if fix_logs else ''
        saved = await self.save_editor()
        feedback = None
        if fix_logs and self.trials.get(saved["step_id"]):
            trial = await self.controller.call(
                "run.get", run_id=self.trials[saved["step_id"]]
            )
            if trial["attempts"]:
                failed = next((a for a in reversed(trial['attempts']) if a['valid'] and a['status'] in {'FAILED', 'UNKNOWN'}), None)
                if failed and failed['step_id'] != saved['step_id']:
                    definition = json.loads(trial['definition_json'])['steps']
                    name = next(st['name'] for st in definition if st['step_id'] == failed['step_id'])
                    raise TaskError('FORM_INVALID', '本次流程调试失败在“' + name + '”，请切换到该步骤修复。')
                feedback = await self.controller.trial_feedback(trial['run_id'], saved['step_id'])
                if getattr(self, 'debug_feedback_run_id', None) == trial['run_id'] and getattr(self, 'debug_feedback', None):
                    feedback = dict(self.debug_feedback)
                for key in getattr(self, 'debug_removed_feedback', set()):
                    feedback.pop(key, None)
        if fix_logs and feedback is None:
            raise TaskError("VALIDATION_EVIDENCE_INVALID", "请先执行当前步骤调试")
        generation_contexts = self.contexts
        if fix_logs:
            generation_contexts, availability = await self.controller.repair_contexts(saved, trial['run_id'], feedback)
            feedback['current_context_status'] = availability
            if not availability['available']:
                ui.notify('当前页面上下文无法刷新，将明确告知 AI；未打开新浏览器。', type='warning')
        ui.notify("正在准备网页对话内容。" if web_chat else "正在生成建议，界面保持响应；当前草稿已保存。")
        proposal = await self.controller.call(
            "step.generate",
            step_id=saved["step_id"],
            expected_hash=saved["content_hash"],
            goal=(saved["goal"] + "\n根据本次调试失败信息和日志修复当前步骤，保持原目标，不自动执行。") if fix_logs else saved["goal"],
            feedback=feedback,
            contexts=generation_contexts,
            environment_id=self.environment_id or None,
            supplement=supplement,
            use_history=fix_logs and history_rounds != 0,
            history_rounds=(-1 if fix_logs else 0) if history_rounds is None else history_rounds,
            deduplicate_history=deduplicate_history,
            export_only=web_chat,
        )
        if proposal.get('history_trimmed'):
            ui.notify("本次已按选择携带限定轮数的历史对话。", type="info")
        if web_chat:
            await self.web_chat_dialog(saved, proposal, fix_logs)
            return
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-4xl"):
            ui.label("AI 建议 · 采纳后保存为草稿").classes("text-lg")
            ui.label("变更对比由程序生成；可调试确认，也可手动确认验证成功。")
            ui.label(proposal["explanation"])
            ui.code(
                self.controller.diff(
                    saved["step_content"], proposal["proposed_content"]
                ),
                language="diff",
            ).classes("w-full")
            if proposal["diagnostics"]:
                ui.label(document_text(proposal["diagnostics"]))

            async def accept():
                # Never overwrite edits made while the model was working.
                if (
                    proposal["stale"]
                    or self.edit_controls["code"].value != saved["step_content"]
                ):
                    raise TaskError(
                        "EDIT_CONFLICT", "生成期间内容已修改，请重新生成建议"
                    )
                self.edit_controls["code"].value = proposal["proposed_content"]
                await self.save_editor()
                ui.notify("AI 建议已保存为草稿，下一次调试使用此内容。")
                dialog.close()
                selected_tab = self.editor_tabs.value
                await self.paint()
                self.editor_tabs.value = selected_tab

            with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                self.button("采纳到编辑器", accept, primary=True)
                ui.button("舍弃", on_click=dialog.close).props("outline")
        dialog.open()

    async def web_chat_dialog(self, saved, exported, use_history):
        from taskweave.desktop.chat import parse_chat_reply
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-4xl"):
            ui.label("网页 AI 对话 · 不需要 API Key").classes("text-lg")
            ui.label("复制以下内容到网页 AI，再将它的整段回复粘贴到下方。推荐回复为包含 step_content 和 explanation 的 JSON；也兼容完整 Python 代码。")
            ui.textarea("复制到网页 AI 的内容", value=exported["prompt"]).props("readonly autogrow").classes("w-full")
            async def copy_prompt():
                await self.controller.copy_text(exported["prompt"])
                ui.notify("对话内容已复制")
            self.button("复制对话内容", copy_prompt)
            reply = ui.textarea("粘贴网页 AI 回复").classes("w-full").props("autogrow")
            async def preview_reply():
                source, explanation = parse_chat_reply(reply.value or "")
                current = await self.controller.call("step.get", step_id=saved["step_id"])
                if current["content_hash"] != exported["expected_hash"] or self.edit_controls["code"].value != saved["step_content"]:
                    raise TaskError("EDIT_CONFLICT", "步骤已修改，请重新生成网页对话内容")
                candidate = normalize_step({**saved, "step_content": source})
                diagnostics = await self.controller.validate_step_candidate(candidate)
                errors = [item.get("message", "") for item in diagnostics if item.get("severity") == "error"]
                if errors:
                    raise TaskError("CHAT_REPLY_INVALID", "；".join(errors))
                with ui.dialog() as preview, ui.card().classes("w-full max-w-4xl"):
                    ui.label("网页 AI 回复预览").classes("text-lg")
                    ui.label("解析和差异均由程序生成；只有点击采纳后才会写入草稿。").classes("text-gray-500")
                    ui.label("解释").classes("font-medium")
                    ui.label(explanation or "AI 未提供解释。").classes("whitespace-pre-wrap")
                    ui.label("步骤对比").classes("font-medium")
                    ui.code(
                        self.controller.diff(saved["step_content"], source),
                        language="diff",
                    ).classes("w-full tw-code")
                    warnings = [item.get("message", "") for item in diagnostics if item.get("severity") != "error"]
                    if warnings:
                        ui.label("校验提示：" + "；".join(warnings)).classes("text-amber-700")

                    async def adopt():
                        latest = await self.controller.call("step.get", step_id=saved["step_id"])
                        if latest["content_hash"] != exported["expected_hash"] or self.edit_controls["code"].value != saved["step_content"]:
                            raise TaskError("EDIT_CONFLICT", "预览期间步骤已修改，请重新生成网页对话内容")
                        self.edit_controls["code"].value = source
                        try:
                            await self.save_editor()
                        except Exception:
                            self.edit_controls["code"].value = saved["step_content"]
                            raise
                        if use_history:
                            self.controller.append_debug_conversation(saved["step_id"], [
                                exported["messages"][-1],
                                {"role": "assistant", "content": json.dumps({"step_content": source, "explanation": explanation}, ensure_ascii=False)},
                            ])
                        from taskweave.infrastructure.privacy import redact
                        logging.getLogger(__name__).info("网页 AI 回复已采纳：%s", redact({"step_content": source, "explanation": explanation}))
                        ui.notify("网页 AI 回复已保存为草稿，下一次调试使用此内容。")
                        preview.close()
                        dialog.close()
                        selected_tab = self.editor_tabs.value
                        await self.paint()
                        self.editor_tabs.value = selected_tab

                    with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                        self.button("采纳到编辑器", adopt, primary=True)
                        ui.button("返回修改粘贴内容", on_click=preview.close).props("outline")
                preview.open()
            with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                self.button("解析并预览", preview_reply, primary=True)
                ui.button("关闭", on_click=dialog.close).props("outline")
        dialog.open()

    async def choose_generation_mode(self):
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-md"):
            ui.label("AI 生成内容").classes("text-lg font-medium")
            ui.label("选择本次使用的对话方式。").classes("text-gray-500")
            with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                ui.button("使用 API", on_click=lambda: dialog.submit("api")).props(
                    "outline"
                )
                ui.button(
                    "使用 Chat 网页", on_click=lambda: dialog.submit("chat")
                ).props("outline")
                ui.button("取消", on_click=lambda: dialog.submit(None)).props("outline")
        mode = await dialog
        if mode:
            await self.generate(web_chat=mode == "chat")

    async def generate_goal_dialog(self):
        saved = await self.save_editor()
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-2xl"):
            ui.label("AI 生成步骤描述").classes("text-lg font-medium")
            ui.label('输入简单想法即可。AI 会结合插件上下文、变量和能力，整理成可用于生成步骤内容的明确操作说明。').classes('text-gray-500')
            requirement = ui.textarea(
                "你想让这个步骤完成什么",
                placeholder="例如：登录后进入合约管理，新建比例再保险合同，并保存结果截图",
            ).props('autogrow').classes("w-full")
            with ui.row().classes("w-full gap-2 flex-wrap"):
                ui.button("使用 API", on_click=lambda: dialog.submit(("api", requirement.value or ""))).props("outline")
                ui.button("使用 Chat 网页", on_click=lambda: dialog.submit(("chat", requirement.value or ""))).props("outline")
                ui.button("取消", on_click=lambda: dialog.submit(None)).props("flat")
        choice = await dialog
        if not choice:
            return
        mode, supplement = choice
        proposal = await self.controller.call(
            "step.generate_goal",
            step_id=saved["step_id"],
            expected_hash=saved["content_hash"],
            supplement=supplement,
            contexts=self.contexts,
            export_only=mode == "chat",
        )
        if mode == "chat":
            with ui.dialog() as chat, ui.card().classes("w-full max-w-3xl"):
                ui.label("网页 AI 生成步骤描述").classes("text-lg")
                ui.textarea("复制到网页 AI", value=proposal["prompt"]).props("readonly autogrow").classes("w-full")
                reply = ui.textarea("粘贴网页回复").props("autogrow").classes("w-full")

                async def adopt_chat_goal():
                    from taskweave.desktop.chat import parse_goal_reply
                    goal_text = parse_goal_reply(reply.value or "")
                    await self.preview_goal(saved, goal_text, '', chat)

                with ui.row().classes("gap-2 flex-wrap"):
                    self.button("复制对话内容", lambda: self.controller.copy_text(proposal["prompt"]))
                    self.button("解析并预览", adopt_chat_goal, primary=True)
                    ui.button("关闭", on_click=chat.close).props("outline")
            chat.open()
            return
        await self.preview_goal(saved, proposal["goal"], proposal.get("explanation", ""))

    async def preview_goal(self, saved, goal_text, explanation="", parent=None):
        with ui.dialog() as preview, ui.card().classes("w-full max-w-2xl"):
            ui.label("步骤描述预览").classes("text-lg")
            if explanation:
                ui.label(explanation).classes("text-gray-600")
            ui.label(goal_text).classes("whitespace-pre-wrap border rounded p-3 w-full")

            async def accept():
                latest = await self.controller.call("step.get", step_id=saved["step_id"])
                if latest["content_hash"] != saved["content_hash"]:
                    raise TaskError("EDIT_CONFLICT")
                self.edit_controls["goal"].value = goal_text
                await self.save_editor()
                preview.close()
                if parent:
                    parent.close()
                ui.notify("步骤描述已保存为待确认内容")

            with ui.row().classes("gap-2"):
                self.button("采纳步骤描述", accept, primary=True)
                ui.button("取消", on_click=preview.close).props("outline")
        preview.open()

    async def new_debug_round(self):
        if not self.step_id:
            return
        self.controller.reset_debug_conversation(self.step_id)
        self.debug_supplements.pop(self.step_id, None)
        self.debug_feedback = None
        self.debug_feedback_run_id = None
        self.debug_removed_feedback = set()
        if getattr(self, "trial_ai_supplement", None) and not self.trial_ai_supplement.is_deleted:
            self.trial_ai_supplement.value = ""
        ui.notify("已清空当前步骤的 AI 修复上下文；调试实例和运行记录继续保留", type="positive")

    def render_collected_contexts(self, panel=None):
        panel = panel or getattr(self, "context_panel", None)
        if panel is None or panel.is_deleted:
            return
        panel.clear()
        if not self.context_entries:
            return
        with panel:
            with ui.expansion(
                "已采集的上下文（" + str(len(self.context_entries)) + "）",
                icon="inventory_2",
            ).classes("w-full border rounded"):
                ui.label(
                    "可以分别采集多个插件或同一插件的多个上下文；以下内容会一起交给 AI。"
                ).classes("text-sm text-gray-500 px-2")
                for entry in list(self.context_entries):
                    item = entry["item"]
                    provider = entry.get("provider_id", entry.get("provider", ""))
                    source_label = {'draft': '草稿页面', 'trial_feedback': '调试页面'}.get(entry.get('source_page'), entry.get('source_page', ''))
                    label = entry.get('name') or item.get("source") or provider
                    with ui.expansion(label, icon="description").classes(
                        "w-full border rounded"
                    ):
                        with ui.row().classes("w-full items-center justify-between"):
                            ui.label("插件上下文：" + provider + " · 来源：" + source_label).classes(
                                "text-sm text-gray-500"
                            )

                            async def remove(current=entry):
                                await self.remove_context_entry(current)
                                self.render_all_context_panels()

                            ui.button(icon="delete", on_click=remove).props(
                                "flat round color=negative aria-label=删除上下文"
                            ).tooltip("删除上下文")
                        name = ui.input('上下文名称', value=entry.get('name', label)).classes('w-full')
                        async def rename(current=entry, control=name, provider_id=provider):
                            if control.value and control.value.strip() != current.get('name'):
                                saved = await self.controller.call('context.save', step_id=self.step_id,
                                    provider_id=provider_id, name=control.value.strip(), source_page=current['source_page'],
                                    item=current['item'], context_id=current['context_id'])
                                current.update(saved)
                                await self.mark_step_pending()
                                self.render_all_context_panels()
                        name.on('blur', rename)
                        ui.code(document_text(item), language="json").classes(
                            "w-full tw-code"
                        )

    def render_all_context_panels(self):
        for panel in (getattr(self, 'context_panel', None), getattr(self, 'trial_context_panel', None)):
            if panel is not None and not panel.is_deleted:
                self.render_collected_contexts(panel)

    async def append_contexts(self, provider, collected, source_page='draft'):
        for index, item in enumerate(collected, 1):
            suggested = item.get('source') if isinstance(item, dict) else None
            saved = await self.controller.call('context.save', step_id=self.step_id, provider_id=provider,
                name=suggested or f'{provider} 上下文 {index}', source_page=source_page, item=item)
            self.context_entries.append(saved)
        self.contexts = [entry["item"] for entry in self.context_entries]
        await self.mark_step_pending()

    async def remove_context_entry(self, entry):
        await self.controller.call('context.delete', context_id=entry['context_id'])
        if entry in self.context_entries:
            self.context_entries.remove(entry)
        self.contexts = [saved["item"] for saved in self.context_entries]
        await self.mark_step_pending()

    async def collect_context(self, source_page='draft'):
        saved = await self.save_editor()
        contributions = self.controller.plugin_contributions(
            saved["capabilities"]
        )
        ids = sorted(
            {identifier for c in contributions for identifier in c.context_provider_ids}
        )
        if not ids:
            raise TaskError("CONTEXT_PROVIDER_UNAVAILABLE", "所选插件没有提供上下文")
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-2xl"):
            provider = ui.select(ids, label="插件上下文", value=ids[0]).classes(
                "w-full"
            )
            url = ui.input("页面地址（独立观察时填写）").classes("w-full")
            role = ui.input("角色", value="operator")
            run_options = {"": "独立观察（不使用运行会话）"}
            runs = await self.controller.call("run.context.sessions", task_id=self.task_id)
            run_options.update(
                {
                    r["run_id"]: execution_title(r) + " · " + STATUS[r["status"]]
                    for r in runs
                    if r["status"] in {"PAUSED", "FAILED", "SUCCEEDED"}
                }
            )
            run = ui.select(run_options, label="观察会话", value=runs[0]["run_id"] if runs else "").classes("w-full")
            session_note = ui.label("仅显示当前仍保留的运行会话；成功调试并保存后也可采集当前页面。")
            request_forms = {}
            request_groups = {}
            for identifier, request_schema in self.controller.plugin_context_requests().items():
                if identifier in ids:
                    with ui.column().classes('w-full') as group:
                        request_forms[identifier] = ValueForm(request_schema)
                    request_groups[identifier] = group
            def select_provider(_=None):
                custom = provider.value in request_forms
                for field in (url, role, run, session_note):
                    field.set_visibility(not custom)
                for identifier, group in request_groups.items():
                    group.set_visibility(identifier == provider.value)
            provider.on_value_change(select_provider)
            select_provider()

            async def collect():
                request = request_forms[provider.value].values() if provider.value in request_forms else {"role": role.value}
                if provider.value not in request_forms and url.value:
                    request["url"] = url.value
                collected = await self.controller.call(
                    "context.read",
                    step_id=saved["step_id"],
                    provider_id=provider.value,
                    request=request,
                    environment_id=self.environment_id or None,
                    run_id=None if provider.value in request_forms else run.value or None,
                )
                await self.append_contexts(provider.value, collected, source_page)
                dialog.close()
                self.render_all_context_panels()
                ui.notify(
                    "已采集 " + str(len(collected)) + " 条上下文，共 "
                    + str(len(self.context_entries)) + " 条"
                )

            self.button("采集上下文", collect, primary=True)
        dialog.open()

    async def run(self):
        task = await self.controller.call("task.get", task_id=self.task_id)
        with ui.row().classes("w-full justify-between items-center"):
            ui.label("执行列表").classes("text-xl font-medium")
            async def create():
                with ui.dialog() as dialog, ui.card().classes("w-full max-w-2xl"):
                    ui.label("新建执行").classes("text-lg")
                    environment = await self.environment_select()
                    steps = await self.controller.call('step.list', task_id=self.task_id)
                    start = ui.select({step['step_id']: f"{i + 1}. {step['name']}" for i, step in enumerate(steps)}, value=steps[0]['step_id'] if steps else None, label='开始步骤').classes('w-full')
                    input_area = ui.column().classes('w-full')
                    selected_form = [None]

                    async def render_inputs():
                        input_area.clear()
                        selected = next(step for step in steps if step['step_id'] == start.value)
                        with input_area:
                            selected_form[0] = await self.trial_variables(selected, environment)

                    start.on_value_change(lambda _: render_inputs())
                    await render_inputs()
                    async def save():
                        form = selected_form[0]
                        response = await self.controller.call("run.create", task_id=self.task_id, inputs=form.task_values(), step_inputs={start.value: form.step_values()}, environment_id=environment.value or None, defer_inputs=True)
                        self.run_id = response["run_id"]
                        await self.controller.call('run.start', run_id=self.run_id, command_id=command_id(), mode='ALL', start_step_id=start.value)
                        dialog.close()
                        await self.paint()
                    with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                        self.button("创建并执行", save, primary=True)
                        ui.button("取消", on_click=dialog.close).props("outline")
                dialog.open()
            self.button("新建执行", create, primary=True)
        self.execution_rows = ui.column().classes("w-full gap-3")
        self.execution_signature = None
        self.run_area = None
        ui.timer(1, self.refresh_run)
        await self.refresh_run()

    async def confirm_end(self, run):
        catalog = await self.controller.call("capabilities")
        definition = json.loads(run["definition_json"])["steps"] if run.get("definition_json") else await self.controller.call("step.list", task_id=run["task_id"])
        capabilities = {cap for step in definition for cap in step.get("capabilities", [])}
        resources = set()
        for action in catalog["actions"]:
            if action["id"] in capabilities:
                resources.update(action.get("resource_ids", []))
        resources.update(capabilities.intersection(catalog["resource_providers"]))
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-xl"):
            ui.label("确认结束执行？").classes("text-lg")
            for plugin_id in sorted({resource.split(".")[0] for resource in resources}):
                manifest = catalog["manifests"].get(plugin_id, {})
                descriptions = manifest.get("resource_descriptions", {})
                names = [descriptions.get(resource, resource) for resource in sorted(resources) if resource.startswith(plugin_id + ".")]
                ui.label("使用了 " + plugin_id + " 插件，结束时将关闭或释放其已创建的资源：" + "、".join(names) + "。")
            if not resources:
                ui.label("没有声明插件运行资源，结束时将释放执行器占用。")
            ui.label("已保存的结果和历史保留。结束后如需继续，请从头重新执行或新建执行。")
            with ui.row():
                ui.button("确认结束", on_click=lambda: dialog.submit(True))
                ui.button("取消", on_click=lambda: dialog.submit(False)).props("outline")
        return await dialog

    async def refresh_execution_rows(self):
        runs = [r for r in await self.controller.call("run.list", task_id=self.task_id) if r["mode"] == "EXECUTION"]
        details = [await self.controller.call("run.get", run_id=r["run_id"]) for r in reversed(runs)]
        signature = document_text([details, self.run_id])
        if signature == self.execution_signature:
            return
        self.execution_signature = signature
        self.execution_rows.clear()
        self.run_area = None
        self.run_signature = None
        environments = {e["environment_id"]: e["name"] for e in await self.controller.call("environment.list")}
        task = await self.controller.call("task.get", task_id=self.task_id)
        with self.execution_rows:
            if not details:
                ui.label("暂无执行，点击右上角新建执行并选择环境。").classes("tw-panel w-full")
            for run in details:
                with ui.column().classes("tw-panel w-full gap-2"):
                    async def delete(r=run):
                        with ui.dialog() as dialog, ui.card():
                            ui.label('删除这次执行及其日志、结果？其他执行和任务配置保留。')
                            with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                                ui.button('取消', on_click=lambda: dialog.submit(False)).props('outline')
                                ui.button('确认删除执行', on_click=lambda: dialog.submit(True)).props('color=negative')
                        if await dialog:
                            await self.controller.call('run.delete', run_id=r['run_id'])
                            if self.run_id == r['run_id']:
                                self.run_id = None
                            self.run_signature = self.execution_signature = None
                            await self.refresh_run()
                    with ui.row().classes('w-full justify-between items-center'):
                        with ui.column().classes('gap-0'):
                            ui.label(task['name'] + ' · ' + STATUS.get(run['status'], run['status'])).classes('font-medium')
                            ui.label(environments.get(run['environment_id'], json.loads(run['request_json']).get('deleted_environment_name', '默认环境')) + ' · ' + (run.get('started_at') or '尚未开始')).classes('text-xs text-gray-500')
                        with ui.row().classes('items-center gap-2'):
                            async def inspect_history(rid=run["run_id"]):
                                self.run_id = None if self.run_id == rid else rid
                                self.run_signature = self.execution_signature = None
                                await self.refresh_run()
                            self.button("执行历史", inspect_history)
                            self.button('', delete, flat=True).props('icon=delete round dense text-color=red-7 aria-label=删除执行').classes('tw-danger').style('background: white; margin-left: 24px').tooltip('删除执行')
                    with ui.row().classes('w-full items-center flex-nowrap gap-3'):
                        definition = json.loads(run["definition_json"])["steps"] if run["definition_json"] else await self.controller.call("step.list", task_id=self.task_id)
                        with ui.row().classes('flex-1 min-w-0 overflow-x-auto flex-nowrap gap-2'):
                            for index, step in enumerate(definition):
                                attempts = [a for a in run["attempts"] if a["step_id"] == step["step_id"] and a["valid"]]
                                state = attempts[-1]['status'] if attempts else None
                                with ui.row().classes('shrink-0 flex-nowrap gap-0 items-stretch'):
                                    control = self.button(f"{index+1}. {step['name']}", lambda r=run, st=step: self.choose_run_step(r, st), flat=True)
                                    control.classes('shrink-0 whitespace-nowrap rounded-r-none')
                                    control.props('text-color=white' if state == 'SUCCEEDED' else 'text-color=red-7' if state in {'FAILED', 'UNKNOWN'} else 'text-color=grey-7')
                                    control.style('background: ' + ('#16a34a; color: white' if state == 'SUCCEEDED' else '#fee2e2; color: #dc2626' if state in {'FAILED', 'UNKNOWN'} else '#e5e7eb; color: #6b7280'))
                                    control.tooltip(STATUS.get(state, '未执行'))
                                    if state == 'SUCCEEDED':
                                        icon = self.button('', lambda r=run, st=step: self.step_result_dialog(r, st), flat=True)
                                        icon.props('icon=check dense aria-label=查看步骤结果').classes('rounded-l-none').style('background:#16a34a;color:white;border-left:1px solid #86efac').tooltip('查看运行结果')
                                    elif state in {'FAILED', 'UNKNOWN'}:
                                        icon = self.button('', lambda a=attempts[-1], st=step: self.step_error_dialog(a, st), flat=True)
                                        icon.props('icon=error dense aria-label=查看步骤错误').classes('rounded-l-none').style('background:#fee2e2;color:#dc2626;border-left:1px solid #fecaca').tooltip('查看报错')
                        with ui.row().classes('shrink-0 flex-nowrap gap-2'):
                            async def end(r=run):
                                if not await self.confirm_end(r):
                                    return
                                await self.controller.call("run.control", run_id=r["run_id"], command_id=command_id(), operation="cancel" if r["status"] == "RUNNING" else "abandon")
                                await self.refresh_run()
                            if run.get("can_end", False):
                                self.button("结束执行", end)
                            if run["status"] == "RUNNING":
                                async def pause(rid=run["run_id"]):
                                    await self.controller.call("run.control",run_id=rid,command_id=command_id(),operation="pause")
                                self.button("暂停", pause)
                    if self.run_id == run['run_id']:
                        self.run_area = ui.column().classes('tw-panel w-full')

    async def choose_run_step(self, run, step):
        current = await self.controller.call('run.get', run_id=run['run_id'])
        succeeded = any(a['step_id'] == step['step_id'] and a['valid'] and a['status'] == 'SUCCEEDED' for a in current['attempts'])
        with ui.dialog() as dialog, ui.card().classes('w-full max-w-xl'):
            ui.label('执行到：' + step['name']).classes('text-lg')
            start = None
            if succeeded:
                definition = json.loads(current['definition_json'])['steps']
                index = next(i for i, st in enumerate(definition) if st['step_id'] == step['step_id'])
                start = ui.select({st['step_id']: f"{i+1}. {st['name']}" for i, st in enumerate(definition[:index+1])}, value=step['step_id'], label='开始步骤').classes('w-full')
                ui.label('开始步骤及后续结果将清空，前面的结果保留。')
            with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                if succeeded:
                    ui.button('从所选步骤重新执行到此步', on_click=lambda: dialog.submit('partial'))
                else:
                    ui.button('从前面未执行的步骤继续到此步', on_click=lambda: dialog.submit('continue'))
                ui.button('清理本次结果，从头执行到此步', on_click=lambda: dialog.submit('restart')).props('outline')
                ui.button('取消', on_click=lambda: dialog.submit(None)).props('flat')
        choice = await dialog
        if choice is None:
            return
        self.run_id = run['run_id']
        if choice in {'restart', 'partial'}:
            await self.controller.call('run.restart', run_id=self.run_id, command_id=command_id(), target_step_id=step['step_id'], start_step_id=start.value if choice == 'partial' else None)
        else:
            failed = next((a for a in current['attempts'] if a['valid'] and a['status'] == 'FAILED'), None)
            await self.controller.call('run.start', run_id=self.run_id, command_id=command_id(), mode='UNTIL', target_step_id=step['step_id'], retry_step_id=failed['step_id'] if failed else None)
        self.run_signature = self.execution_signature = None
        await self.refresh_run()

    async def step_error_dialog(self, attempt, step):
        with ui.dialog() as dialog, ui.card().classes('w-full max-w-2xl'):
            ui.label(step['name'] + ' · 执行错误').classes('text-lg font-medium')
            ui.label((attempt.get('error_code') or 'UNKNOWN') + '：' + (attempt.get('error_summary') or '无错误说明')).classes('text-red-700 whitespace-pre-wrap')
            with ui.row().classes('gap-2'):
                async def go_debug():
                    dialog.close()
                    await self.navigate_step_debug(step['task_id'], step['step_id'])
                self.button('前往该步骤调试', go_debug, primary=True)
                ui.button('关闭', on_click=dialog.close).props('outline')
        dialog.open()

    async def refresh_run(self):
        if self.page not in {"run", "executions"}:
            return
        await self.refresh_execution_rows()
        if self.run_area is None:
            self.run_signature = None
            return
        run = (
            await self.controller.call("run.get", run_id=self.run_id)
            if self.run_id
            else None
        )
        signature = document_text(run)
        remaining = 0
        if run and run["wait_until"]:
            remaining = max(
                0,
                int(
                    (
                        datetime.fromisoformat(run["wait_until"])
                        - datetime.now(timezone.utc)
                    ).total_seconds()
                )
                + 1,
            )
        if signature == getattr(self, "run_signature", None):
            if (
                getattr(self, "countdown_label", None)
                and not self.countdown_label.is_deleted
            ):
                self.countdown_label.text = f"等待步骤间隔 · 剩余 {remaining} 秒" + (
                    "（已暂停，不会自动开始）" if run["status"] != "RUNNING" else ""
                )
            return
        self.run_signature = signature
        self.run_area.clear()
        with self.run_area:
            if not self.run_id:
                return
            await self.pending_inputs(run)
            with ui.row().classes('w-full justify-between items-center'):
                ui.label('运行状态：' + STATUS[run['status']]).classes('text-lg font-medium')
                async def collapse():
                    self.run_id = None
                    self.run_signature = self.execution_signature = None
                    await self.refresh_run()
                self.button('收起详情', collapse)
            if run["waiting_step_id"] and run["wait_until"]:
                remaining = max(
                    0,
                    int(
                        (
                            datetime.fromisoformat(run["wait_until"])
                            - datetime.now(timezone.utc)
                        ).total_seconds()
                    )
                    + 1,
                )
                self.countdown_label = ui.label(
                    f"等待步骤间隔 · 剩余 {remaining} 秒"
                    + ("（已暂停，不会自动开始）" if run["status"] != "RUNNING" else "")
                ).classes("text-amber-700")
            definition = (
                json.loads(run["definition_json"])
                if run["definition_json"]
                else {
                    "steps": await self.controller.call(
                        "step.list", task_id=self.task_id
                    )
                }
            )
            for step in definition["steps"]:
                attempts = [
                    a for a in run["attempts"] if a["step_id"] == step["step_id"]
                ]
                latest = next((a for a in reversed(attempts) if a["valid"]), None)
                with ui.expansion(
                    step["name"]
                    + " · "
                    + (STATUS[latest["status"]] if latest else "待执行"),
                    icon="check_circle" if latest and latest["status"] == "SUCCEEDED" else "error" if latest and latest["status"] in {"FAILED", "UNKNOWN"} else "radio_button_unchecked",
                    value=bool(latest and latest["status"] in {"FAILED", "UNKNOWN"}),
                ).classes("w-full"):
                    with ui.row().classes("w-full justify-end gap-2"):
                        if latest and latest["status"] == "SUCCEEDED":
                            self.button("查看结果", lambda r=run, st=step, aid=latest["attempt_id"]: self.step_result_dialog(r, st, aid))
                        elif latest and latest["status"] in {"FAILED", "UNKNOWN"}:
                            self.button("查看错误", lambda a=latest, st=step: self.step_error_dialog(a, st))
                    ui.label(f"间隔：{step.get('delay_after_previous_seconds', 0)} 秒")
                    if not attempts:
                        ui.label("尚未执行")
                    for attempt in attempts:
                        ui.label(
                            f"尝试 {attempt['attempt_no']} · {STATUS[attempt['status']]}"
                            + (" · 已失效" if not attempt["valid"] else "")
                        )
                        with ui.tabs() as tabs:
                            input_tab = ui.tab("有效输入")
                            output_tab = ui.tab("输出")
                            error_tab = ui.tab("错误 / 核对")
                        with ui.tab_panels(
                            tabs,
                            value=error_tab if attempt["error_code"] else input_tab,
                        ).classes("w-full"):
                            with ui.tab_panel(input_tab):
                                ui.code(
                                    attempt["input_summary_json"], language="json"
                                ).classes("w-full")
                            with ui.tab_panel(output_tab):
                                refs = [
                                    r
                                    for r in run["results"]
                                    if r["attempt_id"] == attempt["attempt_id"]
                                ]
                                if not refs:
                                    ui.label("暂无输出")
                            with ui.tab_panel(error_tab):
                                ui.label(attempt["error_code"] or "无错误")
                                ui.label(attempt["error_summary"] or "")
                                if attempt["valid"] and (
                                    attempt["status"] == "UNKNOWN"
                                    or attempt["status"] == "FAILED"
                                    and attempt["effect_state"]
                                    in {"UNKNOWN", "SUCCEEDED"}
                                ):
                                    self.button(
                                        "核对外部业务结果",
                                        lambda a=attempt: self.reconcile_dialog(a),
                                    )
            with ui.expansion("运行日志").classes("w-full"):
                events = await self.controller.call("run.events", run_id=self.run_id)
                ui.code(document_text(readable_metadata(events, step_names(run, definition["steps"]))), language="json").classes("w-full")

    async def reconcile_dialog(self, attempt):
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-2xl"):
            ui.label("先在业务系统查询，再记录核对结果。")
            decision = ui.select(
                {"completed": "确认已完成", "not_completed": "确认未完成"},
                label="业务结果",
                value=None,
            )
            evidence = ui.textarea("说明（可选）").classes("w-full")

            async def submit():
                if decision.value not in {'completed', 'not_completed'}:
                    raise TaskError('RECONCILIATION_INVALID', '请选择业务结果')
                await self.controller.call(
                    "run.reconcile",
                    attempt_id=attempt["attempt_id"],
                    decision=decision.value,
                    evidence={"manual_query": evidence.value.strip()} if (evidence.value or "").strip() else {},
                    command_id=command_id(),
                )
                dialog.close()
                await self.refresh_run()

            self.button("保存核对结果", submit, primary=True)
        dialog.open()

    async def step_result_dialog(self, run, step, attempt_id=None):
        current = await self.controller.call('run.get', run_id=run['run_id'])
        if attempt_id is None:
            attempt = next((a for a in reversed(current['attempts']) if a['step_id'] == step['step_id'] and a['valid'] and a['status'] == 'SUCCEEDED'), None)
            attempt_id = attempt['attempt_id'] if attempt else None
        refs = [r for r in current['results'] if r['attempt_id'] == attempt_id]
        stored = {}
        for ref in refs:
            value = await self.controller.call('result.read', result_id=ref['result_id'])
            ref['name'] = value.get('name', Path(ref['locator']).name)
            value['result_id'] = ref['result_id']
            stored[ref['name']] = value
        data = stored.get('data', {}).get('data')
        views = stored.get('data', {}).get('views', [])
        renderers = self.controller.result_renderers
        with ui.dialog() as dialog, ui.card().classes('w-full max-w-5xl'):
            ui.label(step['name'] + ' · 运行结果').classes('text-lg font-medium')
            if not refs:
                ui.label('本步骤已成功完成，没有保存结果。')
            else:
                with ui.tabs().classes('w-full') as tabs:
                    view_tabs = [ui.tab(v['title']) for v in views]
                    raw_tab = ui.tab('原始数据')
                with ui.tab_panels(tabs, value=(view_tabs + [raw_tab])[0]).classes('w-full'):
                    for view, tab in zip(views, view_tabs):
                        with ui.tab_panel(tab):
                            try:
                                from taskweave.core.validation import pointer
                                payload = pointer(data, view.get('pointer', ''))
                                kind = renderers.get(view['renderer'], {}).get('type', 'json')
                                await self.render_result_view(kind, payload, stored)
                            except (TaskError, ValueError, TypeError, KeyError) as exc:
                                ui.label('该展示暂不可用：' + str(exc)).classes('text-red-700')
                                ui.code(document_text(data), language='json').classes('w-full')
                    with ui.tab_panel(raw_tab):
                        ui.code(document_text(data), language='json').classes('w-full')
            ui.button('关闭', on_click=dialog.close).props('outline')
        dialog.open()

    async def render_result_view(self, kind, payload, stored):
        if kind == 'table':
            if not isinstance(payload, dict) or not isinstance(payload.get('rows'), list):
                raise ValueError('表格需要 columns 和 rows')
            columns = [{'name': c['key'], 'label': c.get('label', c['key']), 'field': c['key'], 'align': 'left', 'sortable': True} for c in payload.get('columns', [])]
            if not columns and payload['rows']:
                columns = [{'name': key, 'label': key, 'field': key, 'align': 'left', 'sortable': True} for key in payload['rows'][0]]
            rows = [dict(row, __row_index=i) for i, row in enumerate(payload['rows'])]
            ui.table(columns=columns, rows=rows, row_key='__row_index', pagination=20).classes('w-full').style('max-width: 100%; overflow-x: auto')
        elif kind == 'report':
            if not isinstance(payload, dict):
                raise ValueError('核对报告需要对象')
            with ui.row().classes('items-center'):
                ui.icon('check_circle' if payload.get('passed') else 'error', color='green' if payload.get('passed') else 'red')
                ui.label(payload.get('message') or ('核对通过' if payload.get('passed') else '核对未通过'))
            tables = payload.get('tables', [])
            if tables:
                with ui.tabs() as tabs:
                    labels = [ui.tab(table['title']) for table in tables]
                with ui.tab_panels(tabs, value=labels[0]).classes('w-full'):
                    for table, label in zip(tables, labels):
                        with ui.tab_panel(label):
                            await self.render_result_view('table', table, stored)
            if payload.get('query_info'):
                with ui.expansion('查询信息').classes('w-full'):
                    ui.code(document_text(payload['query_info']), language='json').classes('w-full')
        elif kind == 'image':
            import base64
            payload = image_reference(payload, stored)
            if payload.get('output'):
                image = stored[payload['output']]
                mime = image['media_type']
                path = Path(image['path'])
                if not mime.startswith('image/') or path.stat().st_size > 10 * 1024 * 1024:
                    raise ValueError('图片格式不支持或超过 10MB')
                encoded = base64.b64encode(path.read_bytes()).decode()
            else:
                encoded = payload['image_base64']
                mime = payload.get('mime_type', 'image/png')
                if mime not in {'image/png', 'image/jpeg', 'image/webp'} or len(encoded) > 14 * 1024 * 1024 or len(base64.b64decode(encoded, validate=True)) > 10 * 1024 * 1024:
                    raise ValueError('图片格式不支持或超过 10MB')
            ui.image('data:' + mime + ';base64,' + encoded).classes('w-full')
        else:
            ui.code(document_text(payload), language='json').classes('w-full')

    async def result_dialog(self, result_id):
        result = await self.controller.call("result.read", result_id=result_id)
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-4xl"):
            ui.label("执行结果").classes("text-lg")
            if result.get("path"):
                ui.label(result["path"])
                if result.get("media_type", "").startswith("image/"):
                    # Send only this authorized image; no broad static task-data mount.
                    import base64

                    image = Path(result["path"])
                    if image.stat().st_size <= 10 * 1024 * 1024:
                        ui.image(
                            "data:"
                            + result["media_type"]
                            + ";base64,"
                            + base64.b64encode(image.read_bytes()).decode()
                        ).classes("w-full")
                with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                    self.button(
                        "打开文件", lambda: self.controller.open_path(result["path"])
                    )
                    self.button(
                        "打开所在位置",
                        lambda: self.controller.open_path(Path(result["path"]).parent),
                    )
            ui.code(
                document_text(result.get("preview", result.get("data", result))),
                language="json",
            ).classes("w-full")
            ui.button("关闭", on_click=dialog.close)
        dialog.open()

    async def history(self):
        ui.label("本任务调试历史").classes("text-xl")
        runs = [run for run in await self.controller.call("run.list", task_id=self.task_id) if run["mode"] == "TRIAL"]
        if not runs:
            ui.label("暂无调试记录。").classes("tw-panel")
        fallback = await self.controller.call("step.list", task_id=self.task_id)
        for run in reversed(runs):
            with ui.row().classes("tw-panel w-full items-center justify-between"):
                ui.label(
                    f"{run['started_at'] or '未开始'} · 调试 · {STATUS[run['status']]}"
                )

                async def details(r=run):
                    value = await self.controller.call("run.get", run_id=r["run_id"])
                    with ui.dialog() as dialog, ui.card().classes("w-full max-w-4xl"):
                        ui.label("历史执行详情 · " + execution_title(r))
                        names = step_names(value, fallback)
                        snapshot = (
                            json.loads(value["definition_json"])
                            if value["definition_json"]
                            else None
                        )
                        if snapshot:
                            ui.label("执行时任务：" + snapshot["task"]["name"])
                        for attempt in value["attempts"]:
                            title = f"{names.get(attempt['step_id'], '未知步骤')} · 尝试 {attempt['attempt_no']} · {STATUS[attempt['status']]}"
                            icon = 'check_circle' if attempt['status'] == 'SUCCEEDED' else 'error' if attempt['status'] in {'FAILED', 'UNKNOWN'} else 'radio_button_unchecked'
                            with ui.expansion(title, icon=icon).classes('w-full'):
                                with ui.row().classes('w-full justify-end gap-2'):
                                    result_step = {'step_id': attempt['step_id'], 'task_id': value['task_id'], 'name': names.get(attempt['step_id'], '步骤')}
                                    if any(ref['attempt_id'] == attempt['attempt_id'] for ref in value['results']):
                                        self.button('查看结果', lambda r=value, st=result_step, aid=attempt['attempt_id']: self.step_result_dialog(r, st, aid))
                                    if attempt['status'] in {'FAILED', 'UNKNOWN'}:
                                        self.button('查看错误', lambda a=attempt, st=result_step: self.step_error_dialog(a, st))
                                ui.code(document_text(readable_metadata(attempt, names)), language="json").classes("w-full")
                        ui.code(
                            document_text(
                                readable_metadata(await self.controller.call(
                                    "run.events", run_id=r["run_id"]
                                ), names)
                            ),
                            language="json",
                        ).classes("w-full")
                        ui.button("关闭", on_click=dialog.close)
                    dialog.open()

                self.button("查看记录", details)

    async def plugins(self):
        ui.label("插件").classes("text-xl")
        catalog = await self.controller.call("capabilities")
        installed = await self.controller.call("plugin.list")
        installed = sorted((plugin for plugin in installed if plugin["id"] not in {"demo", "sample", "text"}), key=lambda item: (not item["enabled"], item["id"]))
        for plugin in installed:
            name = plugin["id"]
            with ui.expansion(("已启用 · " if plugin["enabled"] else "未启用 · ") + name, icon="extension").classes("tw-panel w-full"):
                with ui.row().classes("w-full items-center justify-between"):
                    ui.label(name + " · " + catalog["versions"].get(name, "未加载"))

                    async def toggle(p=plugin):
                        await self.controller.call(
                            "plugin.configure",
                            plugin_id=p["id"],
                            enabled=not p["enabled"],
                        )
                        await self.paint()

                    self.button("停用" if plugin["enabled"] else "启用", toggle)
                error = plugin.get("error") or catalog["load_errors"].get(name)
                if error:
                    ui.label("加载错误：" + str(error)).classes("text-red-700")
                actions = [
                    a["id"]
                    for a in catalog["actions"]
                    if a["id"].startswith(name + ".")
                ]
                ui.label("动作：" + (", ".join(actions) or "未启用 / 无动作"))
                variables = catalog['manifests'].get(name, {}).get('config_variables', [])
                if variables:
                    ui.label("环境或任务配置变量（任务参数优先）").classes("font-medium")
                    for variable in variables:
                        ui.label(variable['key'] + ' · ' + variable['type'] + ' · ' + ('必填' if variable.get('required') else '可选') + ' · ' + variable.get('description',''))
                        if 'default' in variable:
                            ui.label('默认值：' + document_text(variable['default']))
                for spec in catalog["actions"]:
                    if spec["id"] in actions:
                        with ui.expansion(spec["id"]).classes("w-full"):
                            ui.label(spec["description"])
                            ui.label("输入参数：")
                            ui.code(document_text(spec["input_schema"]), language="json")
                ui.label("插件可贡献提示词、上下文、工具、校验和结果解析。").classes(
                    "text-gray-500"
                )

    async def environment(self):
        ui.label("环境").classes("text-xl")
        environments = await self.controller.call("environment.list")
        default = await self.controller.default_environment()
        environments = sorted(environments, key=lambda item: (item['environment_id'] != default, item['name']))
        async def dialog(existing=None):
            config = json.loads(existing["public_config_json"]) if existing else {}
            if existing:
                config.update(json.loads(existing['secret_refs_json']))
            with ui.dialog() as form, ui.card().classes("w-full max-w-3xl"):
                name = ui.input("环境名称", value=existing["name"] if existing else "").classes("w-full")
                ui.label("配置变量：普通值直接填写；对象、数组、数字和布尔值支持 JSON。")
                ui.label('变量保存在 TaskWeave 本地配置，不修改系统环境变量。步骤通过 inputs["变量名"] 引用；统一优先级为：步骤变量 > 任务变量 > 环境变量。')
                area = ui.column().classes("w-full")
                rows = []
                def add(key="", value=""):
                    with area, ui.row().classes("w-full") as row:
                        key_input = ui.input("Key", value=key)
                        value_input = ui.input("Value", value=value)
                        record = (key_input, value_input)
                        rows.append(record)
                        def remove():
                            rows.remove(record)
                            row.delete()
                        ui.button("移除",on_click=remove).props("flat")
                for key,value in config.items():
                    add(key, value if isinstance(value,str) else json.dumps(value,ensure_ascii=False))
                ui.button("添加变量",on_click=lambda: add()).props("outline")
                async def save():
                    if not name.value.strip():
                        raise TaskError("FORM_INVALID", "请填写环境名称")
                    values = {}
                    for key,value in rows:
                        field = key.value.strip()
                        if not field or field in values:
                            raise TaskError("FORM_INVALID", "Key 不能为空或重复")
                        try:
                            values[field] = json.loads(value.value)
                        except ValueError:
                            values[field] = value.value
                    await self.controller.call("environment.save",name=name.value.strip(),public_config=values,secret_refs={},environment_id=existing["environment_id"] if existing else None)
                    form.close()
                    await self.paint()
                with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                    self.button("保存环境",save,primary=True)
                    ui.button("取消",on_click=form.close).props("outline")
            form.open()
        self.button("新建环境",dialog,primary=True)
        if not environments:
            ui.label("可使用默认环境，或新建环境配置变量。")
        for environment in environments:
            with ui.row().classes("tw-panel w-full justify-between items-center"):
                with ui.column().classes('gap-1'):
                    if environment['environment_id'] == default:
                        ui.badge('默认', color='teal')
                    ui.label(environment['name'])
                with ui.row():
                    async def set_default(e=environment):
                        await self.controller.set_default_environment(e['environment_id'])
                        self.environment_id = e['environment_id']
                        await self.paint()
                    if environment['environment_id'] != default:
                        self.button('设为默认', set_default)
                    self.button('编辑',lambda e=environment: dialog(e))
                    async def delete(e=environment):
                        with ui.dialog() as confirmation, ui.card():
                            ui.label('删除环境“' + e['name'] + '”？历史执行结果保留。')
                            with ui.row():
                                ui.button('取消', on_click=lambda: confirmation.submit(False)).props('outline')
                                ui.button('确认删除环境', on_click=lambda: confirmation.submit(True)).props('outline text-color=red-7')
                        if not await confirmation:
                            return
                        await self.controller.call('environment.delete', environment_id=e['environment_id'])
                        if e['environment_id'] == default:
                            await self.controller.set_default_environment(None)
                        if self.environment_id == e['environment_id']:
                            self.environment_id = None
                        await self.paint()
                    self.button('', delete, flat=True).props(
                        'icon=delete round dense text-color=red-7 aria-label=删除环境'
                    ).classes('tw-danger').tooltip('删除环境')


    async def settings(self):
        ui.label("设置").classes("text-xl")
        with ui.column().classes("tw-panel w-full"):
            ui.label("本地工作空间").classes("font-medium")
            ui.label(str(self.controller.workspace_home))
            ui.label("总库保存配置与执行记录；每个任务的数据库保存返回结果。")
            destination = ui.input("新的工作空间目录").classes("w-full")

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
            self.button(
                "打开数据目录",
                lambda: self.controller.open_path(self.controller.workspace_home),
            )
        workbench_settings = await self.controller.workbench_settings()
        with ui.column().classes("tw-panel w-full"):
            ui.label("执行器").classes("font-medium")
            executor_threads = ui.number(
                "最大并发执行线程数",
                value=workbench_settings.get('executor_max_threads', 8),
                min=1,
                max=8,
                step=1,
            ).classes('w-full')
            ui.label("单条运行内的步骤顺序执行；不同运行最多并行 8 条。超出上限时新运行直接报错。").classes('text-gray-500')

            async def save_executor():
                value = executor_threads.value
                if value is None or value != int(value):
                    raise TaskError('FORM_INVALID', '请填写 1 到 8 之间的整数')
                await self.controller.save_executor_max_threads(int(value))
                ui.notify('执行器设置已保存')

            self.button('保存执行器设置', save_executor, primary=True)
        settings = await self.controller.model_settings()
        with ui.column().classes("tw-panel w-full"):
            ui.label("AI 编写连接（可选）").classes("font-medium")
            url = ui.input(
                "完整 Chat Completions 接口地址", value=settings.get("url", "")
            ).classes("w-full")
            model = ui.input("模型名称", value=settings.get("model", "")).classes(
                "w-full"
            )
            api_key = ui.input(
                "API Key（本地保存，留空保留当前密钥）",
                password=True,
                password_toggle_button=True,
            ).classes("w-full")
            key_env = ui.input(
                "API Key 所在环境变量名",
                value=settings.get("key_env", "TASKWEAVE_MODEL_API_KEY"),
            ).classes("w-full")
            ui.label(
                "API Key 与连接配置保存在本地，重启后自动读取；也可使用环境变量。执行固定步骤不调用模型。"
            )

            async def save():
                await self.controller.save_model(
                    url.value.strip(),
                    model.value.strip(),
                    key_env.value.strip(),
                    api_key.value or None,
                )
                ui.notify("AI 连接配置已保存")

            async def test():
                await save()
                value = await self.controller.test_model()
                ui.notify("连接成功" if value["connected"] else "服务未返回有效内容")

            with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                self.button("保存连接", save, primary=True)
                self.button("测试连接（实际调用一次模型）", test)
