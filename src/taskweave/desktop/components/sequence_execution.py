"""Shared combination detail and lifecycle controls for execution and debugging."""
import json
from uuid import uuid4
from nicegui import ui
from taskweave.core.validation import TaskError
from taskweave.infrastructure.privacy import redact
from taskweave.desktop.components.execution_details import STATUS, local_run_time, round_label, short_run_id
from taskweave.desktop.components.result_viewer import ResultViewer, document_text
from taskweave.desktop.display import step_names

LABELS = {"READY": "就绪", "RUNNING": "执行中", "WAITING_INPUT": "等待输入",
          "PAUSED": "已暂停", "BLOCKED": "需要处理", "SUCCEEDED": "成功",
          "CANCELLED": "已取消", "DELETING": "清理中", "PENDING": "待执行"}


class SequenceExecution:
    def __init__(self, controller, button, refresh, *, identity, tasks=None, environments=None,
                 trial=False, on_deleted=None):
        self.controller, self.button, self.refresh_progress = controller, button, refresh
        self.identity = identity
        self.origin = identity()
        self.tasks, self.environments = tasks or [], environments or []
        self.trial, self.on_deleted = trial, on_deleted

    def _task_name(self, task_id):
        return next((task['name'] for task in self.tasks if task['task_id'] == task_id), '已删除任务')

    async def render(self, run):
        with ui.column().classes('tw-panel tw-sequence-execution-detail w-full gap-4'):
            ui.label(run['snapshot']['name']).classes('text-xl font-semibold')
            ui.label(('组合调试' if self.trial else '组合执行') + ' · #' + short_run_id(run['sequence_run_id']))                .classes('text-sm text-gray-500')
            ui.label('状态：' + LABELS.get(run['status'], run['status']))
            if run.get('error_code'):
                ui.label('原因：' + run['error_code']).classes('text-red-700')
            await self._run_controls(run)
            ui.label('子任务执行').classes('text-lg font-semibold')
            if not run['nodes']:
                ui.label('尚未进入任务节点').classes('text-sm text-gray-500')
            for member in run['nodes']:
                with ui.column().classes('tw-sequence-run-row w-full gap-2'):
                    ui.label(f"{member['position'] + 1}. {self._task_name(member['task_id'])} · {LABELS.get(member['status'], member['status'])}")
                    ui.label(round_label(member.get('execution_path'))).classes('text-xs text-gray-500')
                    with ui.row().classes('gap-2 flex-wrap'):
                        if member.get('run_id'):
                            self.button('查看执行', lambda item=member: self.show_child(item['run_id']), flat=True)
                        if (member.get('run_id') and run['status'] not in {'SUCCEEDED', 'CANCELLED', 'DELETING'}
                                and not run.get('stop_intent')):
                            if member['status'] == 'WAITING_INPUT':
                                self.button('补充输入', lambda item=member: self._inputs_dialog(run, item))
                            elif member['status'] == 'BLOCKED':
                                self.button('重试步骤', lambda item=member: self._retry_dialog(run, item))
                                self.button('核对不确定结果', lambda item=member: self._reconcile_dialog(run, item))
            with ui.expansion('组合输入', icon='input').classes('w-full'):
                ui.code(document_text(redact(run.get('inputs', {}))), language='json').classes('w-full')
            with ui.expansion('执行时编排快照', icon='code').classes('w-full'):
                ui.code(document_text(redact(run['snapshot'])), language='json').classes('w-full')

    async def show_child(self, run_id):
        origin = self.origin
        if self.identity() != origin:
            return
        child = await self.controller.call("run.get", run_id=run_id)
        if self.identity() != origin:
            return
        definition = json.loads(child.get("definition_json") or "{}")
        title = definition.get("task", {}).get("name") or self._task_name(child["task_id"])
        names = step_names(child)
        attempts = child.get("attempts", [])
        results = child.get("results", [])
        viewer = ResultViewer(self.controller, self.button)
        with ui.dialog() as dialog, ui.card().classes("tw-panel w-full max-w-4xl gap-4"):
            with ui.row().classes("w-full items-start justify-between gap-3"):
                with ui.column().classes("grow min-w-0 gap-1"):
                    ui.label("任务执行").classes("text-sm text-gray-500")
                    ui.label(title).classes("text-xl font-semibold break-words")
                ui.label(STATUS.get(child["status"], child["status"])).classes(
                    "tw-status tw-status-" + child["status"].lower())
            environment = next((item["name"] for item in self.environments
                                if item["environment_id"] == child.get("environment_id")), None)
            if environment is None:
                environment = json.loads(child.get("request_json") or "{}").get(
                    "deleted_environment_name", "已删除环境" if child.get("environment_id") else "默认环境")
            ui.label(f"#{short_run_id(child['run_id'])} · {environment}").classes("text-sm text-gray-500")
            with ui.row().classes("w-full gap-x-6 gap-y-1 text-sm text-gray-500"):
                ui.label("开始：" + local_run_time(child.get("started_at")))
                ui.label("结束：" + (local_run_time(child["finished_at"]) if child.get("finished_at") else "—"))
            with ui.expansion("任务输入", icon="input").classes("w-full"):
                ui.code(child.get("input_summary_json") or "{}", language="json").classes("w-full")
            with ui.row().classes("w-full items-center justify-between"):
                ui.label("步骤尝试").classes("font-semibold")
                ui.label(f"{len(attempts)} 次").classes("tw-badge")
            if not attempts:
                ui.label("尚无步骤尝试").classes("text-sm text-gray-500")
            for attempt in attempts:
                valid_label = "当前有效" if attempt.get("valid") else "已失效"
                attempt_title = (f"{names.get(attempt['step_id'], attempt['step_id'])} · "
                    f"{round_label(attempt.get('execution_path'))} · 尝试 {attempt['attempt_no']} · "
                    f"{STATUS.get(attempt['status'], attempt['status'])} · {valid_label}")
                with ui.expansion(attempt_title, icon="history",
                        value=bool(attempt.get("valid") and attempt["status"] in {"FAILED", "UNKNOWN"}))\
                        .classes("tw-history-attempt w-full"):
                    ui.label(f"开始：{local_run_time(attempt.get('started_at'))} · 结束：" + (
                        local_run_time(attempt["finished_at"]) if attempt.get("finished_at") else "—"))\
                        .classes("text-xs text-gray-500")
                    if attempt.get("error_code") or attempt.get("error_summary"):
                        ui.label(attempt.get("error_code") or "执行失败").classes("text-sm text-red-700")
                        if attempt.get("error_summary"):
                            ui.label(attempt["error_summary"]).classes("text-sm whitespace-pre-wrap break-words")
                        effect = {"NOT_STARTED": "未开始", "SUCCEEDED": "已完成", "FAILED": "失败", "UNKNOWN": "待核对"}
                        ui.label("外部动作状态：" + effect.get(attempt.get("effect_state"), attempt.get("effect_state") or "—"))\
                            .classes("text-xs text-gray-500")
                    ui.label("本次输入").classes("font-medium text-sm mt-2")
                    ui.code(attempt.get("input_summary_json") or "{}", language="json").classes("w-full")
                    ui.label("保存结果").classes("font-medium text-sm mt-2")
                    attempt_results = [ref for ref in results if ref.get("attempt_id") == attempt["attempt_id"]]
                    if not attempt_results:
                        ui.label("无保存结果").classes("text-sm text-gray-500")
                    for ref in attempt_results:
                        with ui.row().classes("w-full items-center justify-between gap-2"):
                            kind = {"json": "JSON 数据", "table": "表格", "file": "文件"}.get(ref["kind"], ref["kind"])
                            ui.label(f"{kind} · {ref['media_type']}").classes("text-sm")
                            if ref.get("state") == "AVAILABLE":
                                frozen_step = next((step for step in definition.get("steps", [])
                                                    if step["step_id"] == attempt["step_id"]),
                                                   {"step_id": attempt["step_id"], "name": names.get(attempt["step_id"], "步骤")})
                                self.button("查看结果", lambda st=frozen_step, aid=attempt["attempt_id"]:
                                            viewer.step_result_dialog(child, st, aid), flat=True)
                            else:
                                ui.label({"UNAVAILABLE": "结果不可用", "DELETING": "清理中"}.get(
                                    ref.get("state"), ref.get("state") or "结果不可用")).classes("text-sm text-gray-500")
            with ui.expansion("执行日志", icon="article").classes("w-full"):
                logs = ui.column().classes("w-full")
                async def load_logs():
                    events = await self.controller.call("run.events", run_id=run_id)
                    if self.identity() != origin or logs.is_deleted:
                        return
                    logs.clear()
                    with logs:
                        from taskweave.desktop.components.run_logs import render_log_text
                        from taskweave.desktop.display import readable_metadata
                        render_log_text(self.controller, self.button, document_text(readable_metadata(events, names)))
                self.button("加载日志", load_logs, flat=True)
            with ui.expansion("原始数据", icon="data_object").classes("w-full"):
                ui.code(document_text(child), language="json").classes("w-full max-h-96 overflow-auto")
            with ui.row().classes("w-full justify-end"):
                ui.button("关闭", on_click=dialog.close).props("outline no-caps")
        dialog.open()

    async def _run_controls(self, run):
        sequence_run_id = run["sequence_run_id"]
        status = run["status"]
        with ui.row().classes("gap-2 flex-wrap"):
            if not self.trial:
                self.button('查看验收', lambda: self.controller.open_review('sequence', sequence_run_id))
            if status in {"READY", "RUNNING"}:
                self.button("暂停", lambda: self._control("sequence.pause", sequence_run_id))
            if status not in {"SUCCEEDED", "CANCELLED", "DELETING"}:
                self.button("取消", lambda: self._control("sequence.cancel", sequence_run_id))
            if status == "PAUSED" or (status == "BLOCKED" and run["error_code"] in {
                "SEQUENCE_CHILD_INTERRUPTED", "RUN_CONFIG_CHANGED", "ENVIRONMENT_CHANGED", "PLUGIN_VERSION_MISMATCH"}):
                self.button("继续", lambda: self._control("sequence.continue", sequence_run_id), primary=True)
            if status == "WAITING_INPUT":
                self.button("补充输入", lambda: self._inputs_dialog(run), primary=True)
            if status == "BLOCKED" and run["current_node_id"]:
                member = next((item for item in run["nodes"] if
                              (item.get('execution_path') == run.get('current_execution_path') if run.get('current_execution_path')
                               else item["node_id"] == run["current_node_id"])), None)
                if member is not None and member["run_id"]:
                    self.button("重试步骤", lambda: self._retry_dialog(run, member))
                    self.button("核对不确定结果", lambda: self._reconcile_dialog(run, member))
                elif member is None:
                    ui.label('控制配置或取值失败，请修改组合后新建执行。').classes('text-sm text-gray-500')
            if status not in {"READY", "RUNNING"}:
                label = "重试删除" if status == "DELETING" else ("删除调试记录" if self.trial else "删除执行")
                self.button(label, lambda: self._delete_run(
                    sequence_run_id, run.get("snapshot", {}).get("name", "")), flat=True).classes("tw-danger")

    async def _control(self, operation, sequence_run_id):
        if self.identity() != self.origin:
            return
        await self.controller.call(operation, sequence_run_id=sequence_run_id, command_id=str(uuid4()))
        await self.refresh_progress()

    async def _inputs_dialog(self, run, member=None):
        origin = self.origin
        if self.identity() != origin:
            return
        if member is None:
            member = next(item for item in run["nodes"] if
                          (item.get('execution_path') == run.get('current_execution_path') if run.get('current_execution_path')
                           else item["node_id"] == run["current_node_id"]))
        request = await self.controller.run_request(member["run_id"])
        if self.identity() != origin:
            return
        waiting = request.get("waiting_input")
        if not waiting:
            raise TaskError("INPUT_REQUEST_STALE", "补参请求已变化，请刷新")
        with ui.dialog() as dialog, ui.card().classes("tw-confirm-dialog").style("width:640px"):
            ui.label("补充当前任务输入").classes("tw-confirm-title")
            ui.label("必填：" + "、".join(waiting["missing"])).classes("tw-confirm-description")
            values = ui.textarea("JSON 输入", value=json.dumps(waiting["values"], ensure_ascii=False, indent=2))\
                .props("outlined autogrow").classes("w-full")
            async def submit():
                if self.identity() != origin:
                    dialog.close()
                    return
                supplied = json.loads(values.value)
                await self.controller.call("sequence.run.inputs", sequence_run_id=run["sequence_run_id"],
                    command_id=str(uuid4()), inputs=supplied, expected_input_id=waiting["id"],
                    **({'execution_path': member['execution_path']} if member.get('execution_path') else {}))
                dialog.close()
                await self.refresh_progress()
            with ui.row().classes("tw-confirm-actions"):
                ui.button("取消", on_click=dialog.close).props("outline").classes("tw-confirm-cancel")
                self.button("提交并继续", submit, primary=True)
        dialog.open()

    async def _retry_dialog(self, run, member):
        origin = self.origin
        if self.identity() != origin:
            return
        child = await self.controller.call("run.get", run_id=member["run_id"])
        if self.identity() != origin:
            return
        steps = json.loads(child["definition_json"])["steps"]
        from taskweave.core.task_flow import is_linear_flow
        controlled = not is_linear_flow(json.loads(child["definition_json"])["flow"])
        with ui.dialog() as dialog, ui.card().classes("tw-confirm-dialog"):
            ui.label("重试失败动作" if controlled else "从指定步骤重试").classes("tw-confirm-title")
            if controlled:
                names = {step["step_id"]: step["name"] for step in steps}
                failures = {attempt["execution_path"]: (
                    names.get(attempt["step_id"], attempt["step_id"]) + " · " +
                    " / ".join(f"第 {int(part)+1} 轮" for part in attempt["execution_path"].split('/') if part.isdigit()))
                    for attempt in child["attempts"] if attempt["valid"] and attempt["status"] == "FAILED"}
                if not failures:
                    ui.label("控制条件或循环上限失败，请修改流程后新建执行。")
            else:
                failures = {step["step_id"]: step["name"] for step in steps}
            selected = next(reversed(failures), None)
            if not controlled:
                selected = next((item['step_id'] for item in reversed(child['attempts'])
                    if item.get('valid') and item['status'] == 'FAILED' and item['step_id'] in failures), selected)
            choice = ui.select(failures, value=selected,
                               label="失败实例" if controlled else "重试步骤").classes("w-full")
            async def submit():
                if self.identity() != origin:
                    dialog.close()
                    return
                await self.controller.call("sequence.run.retry", sequence_run_id=run["sequence_run_id"],
                    command_id=str(uuid4()),
                    **({'execution_path': member['execution_path']} if member.get('execution_path') else {}),
                    **({"retry_execution_path": choice.value} if controlled else {"retry_step_id": choice.value}))
                dialog.close()
                await self.refresh_progress()
            with ui.row().classes("tw-confirm-actions"):
                ui.button("取消", on_click=dialog.close).props("outline").classes("tw-confirm-cancel")
                if failures:
                    self.button("重试", submit, primary=True)
        dialog.open()

    async def _reconcile_dialog(self, run, member):
        origin = self.origin
        if self.identity() != origin:
            return
        child = await self.controller.call("run.get", run_id=member["run_id"])
        if self.identity() != origin:
            return
        attempts = [item for item in child.get("attempts", []) if item.get("valid") and (
                    item["status"] == "UNKNOWN"
                    or (item["status"] == "FAILED" and item.get("effect_state") in {"SUCCEEDED", "UNKNOWN"}))]
        if not attempts:
            raise TaskError("RECONCILIATION_INVALID", "当前没有待核对的步骤")
        names = step_names(child)
        with ui.dialog() as dialog, ui.card().classes("tw-confirm-dialog").style("width:560px"):
            ui.label("核对外部执行结果").classes("tw-confirm-title")
            choice = ui.select({item["attempt_id"]: f"{names.get(item['step_id'], item['step_id'])} · 尝试 {item.get('attempt_no', 1)}" for item in attempts},
                               value=attempts[0]["attempt_id"], label="步骤尝试").classes("w-full")
            decision = ui.select({"completed": "已完成", "not_completed": "未完成"},
                                 value="completed", label="核对结论").classes("w-full")
            evidence = ui.textarea("核对依据（文字）").props("rows=3").classes("w-full")
            async def submit():
                if self.identity() != origin:
                    dialog.close()
                    return
                await self.controller.call("sequence.run.reconcile", sequence_run_id=run["sequence_run_id"],
                    attempt_id=choice.value, decision=decision.value,
                    evidence={"note": evidence.value or ""}, command_id=str(uuid4()),
                    **({'execution_path': member['execution_path']} if member.get('execution_path') else {}))
                dialog.close()
                await self.refresh_progress()
            with ui.row().classes("tw-confirm-actions"):
                ui.button("取消", on_click=dialog.close).props("outline").classes("tw-confirm-cancel")
                self.button("保存核对", submit, primary=True)
        dialog.open()

    async def _delete_run(self, sequence_run_id, name=""):
        with ui.dialog() as dialog, ui.card().classes("tw-confirm-dialog"):
            ui.label("删除这次组合调试？" if self.trial else "删除这次组合执行？").classes("tw-confirm-title")
            ui.label(f"{name} · #{short_run_id(sequence_run_id)}" if name else
                     f"#{short_run_id(sequence_run_id)}").classes("tw-confirm-description break-words")
            ui.label("删除本次运行及其子执行记录与结果。").classes("tw-confirm-description")
            with ui.row().classes("tw-confirm-actions"):
                ui.button("取消", on_click=lambda: dialog.submit(False)).props("outline").classes("tw-confirm-cancel")
                ui.button("确认删除调试记录" if self.trial else "确认删除执行", on_click=lambda: dialog.submit(True))\
                    .props("outline color=negative").classes("tw-confirm-danger")
        if not await dialog:
            return
        await self.controller.call("sequence.run.delete", sequence_run_id=sequence_run_id)
        if self.on_deleted is not None:
            await self.on_deleted(sequence_run_id)
        await self.refresh_progress()
