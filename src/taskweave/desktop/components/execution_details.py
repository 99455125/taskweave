"""Execution run list and detail refresh component."""

from datetime import datetime, timezone
import json
from nicegui import ui
from taskweave.desktop.controller import command_id
from taskweave.desktop.display import readable_metadata, step_names

STATUS = {"READY": "就绪", "RUNNING": "执行中", "PAUSED": "已暂停", "FAILED": "失败", "INTERRUPTED": "中断 / 待核对", "SUCCEEDED": "成功", "CANCELLED": "已结束", "UNKNOWN": "结果待核对"}

def document_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)

def short_run_id(value):
    return str(value or "")[:8]

def local_run_time(value):
    if not value: return "尚未开始"
    try: return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone().strftime("%m-%d %H:%M")
    except (TypeError, ValueError, OSError): return str(value)[:16]

class ExecutionDetails:
    def __init__(self, controller, state, button, page, page_generation, pending_inputs, choose_run_step, confirm_end, step_error_dialog, step_result_dialog, reconcile_dialog):
        self.controller, self.state, self.button = controller, state, button
        self.page, self.page_generation = page, page_generation
        self.pending_inputs, self.choose_run_step, self.confirm_end = pending_inputs, choose_run_step, confirm_end
        self.step_error_dialog, self.step_result_dialog, self.reconcile_dialog = step_error_dialog, step_result_dialog, reconcile_dialog
        self.timers = []
        self.render_sequence = 0
        self.refresh_sequence = 0

    def invalidate_render(self):
        self.render_sequence += 1

    def own_timer(self, timer):
        self.timers.append(timer)
        return timer

    def dispose(self):
        self.invalidate_render()
        self.refresh_sequence += 1
        for timer in self.timers:
            if not getattr(timer, "is_deleted", True):
                timer.delete()
        self.timers.clear()

    @property
    def run_id(self): return self.state.run_id
    @run_id.setter
    def run_id(self, value): self.state.run_id = value
    @property
    def run_signature(self): return self.state.run_signature
    @run_signature.setter
    def run_signature(self, value): self.state.run_signature = value
    @property
    def execution_signature(self): return self.state.signature
    @execution_signature.setter
    def execution_signature(self, value): self.state.signature = value
    @property
    def execution_task_ids(self): return self.state.task_ids
    @property
    def execution_statuses(self): return self.state.statuses
    @property
    def execution_rows(self): return self.state.execution_rows
    @execution_rows.setter
    def execution_rows(self, value): self.state.execution_rows = value
    @property
    def execution_list_area(self): return self.state.execution_list_area
    @property
    def run_area(self): return self.state.run_area
    @run_area.setter
    def run_area(self, value): self.state.run_area = value
    @property
    def countdown_label(self): return self.state.countdown_label
    @countdown_label.setter
    def countdown_label(self, value): self.state.countdown_label = value

    def default_step_id(self, run, steps):
        step_ids = {step["step_id"] for step in steps}
        latest_valid = next(
            (attempt["step_id"] for attempt in reversed(run.get("attempts", []))
             if attempt.get("valid") and attempt.get("step_id") in step_ids),
            None,
        )
        return latest_valid or (steps[0]["step_id"] if steps else None)

    def selected_step(self, run, steps):
        run_id = run["run_id"]
        step_ids = {step["step_id"] for step in steps}
        if self.state.selected_step_run_id == run_id and self.state.selected_step_id in step_ids:
            return self.state.selected_step_id
        self.state.selected_step_run_id = run_id
        self.state.selected_step_id = self.default_step_id(run, steps)
        return self.state.selected_step_id

    async def select_step(self, run_id, step_id):
        self.invalidate_render()
        self.run_id = run_id
        self.state.selected_step_run_id = run_id
        self.state.selected_step_id = step_id
        self.run_signature = self.execution_signature = None
        await self.refresh()

    async def select_run(self, run_id):
        self.invalidate_render()
        if self.run_id != run_id:
            self.state.selected_step_run_id = None
            self.state.selected_step_id = None
        self.run_id = run_id
        self.run_signature = self.execution_signature = None
        await self.refresh()

    async def render_rows(self):
        self.invalidate_render()
        request_sequence = self.render_sequence
        identity = [
            request_sequence, self.page_generation(), self.page(),
            tuple(self.execution_task_ids), tuple(self.execution_statuses), self.run_id,
            self.state.selected_step_run_id, self.state.selected_step_id, self.state.search_query,
        ]
        def current():
            return identity == [
                self.render_sequence, self.page_generation(), self.page(),
                tuple(self.execution_task_ids), tuple(self.execution_statuses), self.run_id,
                self.state.selected_step_run_id, self.state.selected_step_id, self.state.search_query,
            ]
        all_runs = await self.controller.call("run.list")
        if not current():
            return
        runs = [r for r in all_runs if r["mode"] == "EXECUTION"]
        if self.execution_task_ids:
            runs = [run for run in runs if run["task_id"] in set(self.execution_task_ids)]
        if self.execution_statuses:
            runs = [run for run in runs if run["status"] in set(self.execution_statuses)]
        details = []
        for row in reversed(runs):
            details.append(await self.controller.call("run.get", run_id=row["run_id"]))
            if not current():
                return
        if self.run_id is None and self.execution_signature is None and details:
            self.run_id = details[0]["run_id"]
            identity[5] = self.run_id
        signature = document_text([details, self.run_id, self.state.selected_step_run_id, self.state.selected_step_id])
        if signature == self.execution_signature:
            return
        environments = {e["environment_id"]: e["name"] for e in await self.controller.call("environment.list")}
        if not current():
            return
        tasks = {task["task_id"]: task for task in await self.controller.call("task.list")}
        if not current():
            return
        query = (self.state.search_query or "").strip().casefold()
        if query:
            details = [run for run in details if query in tasks.get(run["task_id"], {}).get("name", "").casefold()
                       or query in run["run_id"].casefold()]
        active_run = next((run for run in details if run["run_id"] == self.run_id), None)
        definition_steps = None
        if active_run is not None:
            definition_steps = (
                json.loads(active_run["definition_json"])["steps"]
                if active_run["definition_json"]
                else await self.controller.call("step.list", task_id=active_run["task_id"])
            )
            if not current():
                return
        self.execution_signature = signature
        self.execution_rows.clear()
        if self.execution_list_area is not None:
            self.execution_list_area.clear()
        self.run_area = None
        self.run_signature = None
        if self.execution_list_area is not None:
            with self.execution_list_area:
                if not details:
                    ui.label("暂无执行").classes("text-sm text-gray-500")
                for run in details:
                    task = tasks.get(run["task_id"], {"name": "已删除任务"})
                    environment_name = environments.get(run["environment_id"], json.loads(run["request_json"]).get("deleted_environment_name", "默认环境"))
                    selected_run = self.run_id == run["run_id"]
                    with ui.column().classes("tw-run-card gap-2" + (" tw-selected" if selected_run else "")):
                        async def inspect_history(rid=run["run_id"]):
                            await self.select_run(rid)
                        with ui.row().classes("w-full items-start justify-between gap-2 flex-nowrap"):
                            self.button(task["name"], inspect_history, flat=True).classes("tw-run-name grow min-w-0 justify-start text-left")
                            ui.label(STATUS.get(run["status"], run["status"])).classes("tw-run-status tw-status " + "tw-status-" + run["status"].lower())
                        ui.label(f"#{short_run_id(run['run_id'])} · {environment_name} · {local_run_time(run.get('started_at'))}").classes("text-xs text-gray-500")
                        try:
                            total_steps = len(json.loads(run.get("definition_json") or "{}").get("steps", []))
                        except (TypeError, ValueError):
                            total_steps = 0
                        completed_steps = sum(attempt.get("valid") and attempt.get("status") == "SUCCEEDED" for attempt in run.get("attempts", []))
                        if total_steps:
                            ui.linear_progress(min(1, completed_steps / total_steps), show_value=False).props("rounded size=5px color=primary")
                            ui.label(f"{completed_steps}/{total_steps} 步").classes("text-xs text-gray-500")

        with self.execution_rows:
            if active_run is None:
                ui.label("当前筛选下没有选中的执行。请调整筛选条件或选择其他执行。").classes("tw-panel w-full text-gray-500")
            else:
                run = active_run
                task = tasks.get(run["task_id"], {"name": "已删除任务"})
                with ui.card().classes("tw-run-summary-card w-full"):
                    with ui.row().classes("w-full justify-between items-center flex-wrap gap-2"):
                        with ui.column().classes("gap-0"):
                            ui.label(task["name"]).classes("text-lg font-medium")
                            ui.label(STATUS.get(run["status"], run["status"])).classes("text-sm text-gray-500")
                        with ui.row().classes("items-center gap-2"):
                            async def delete_selected(r=run):
                                with ui.dialog() as dialog, ui.card():
                                    ui.label("删除这次执行及其日志、结果？其他执行和任务配置保留。")
                                    with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                                        ui.button("取消", on_click=lambda: dialog.submit(False)).props("outline")
                                        ui.button("确认删除执行", on_click=lambda: dialog.submit(True)).props("color=negative")
                                if await dialog:
                                    await self.controller.call("run.delete", run_id=r["run_id"])
                                    if self.run_id == r["run_id"]:
                                        self.run_id = None
                                        self.state.selected_step_run_id = None
                                        self.state.selected_step_id = None
                                    self.run_signature = self.execution_signature = None
                                    await self.refresh()
                            async def end(r=run):
                                if not await self.confirm_end(r):
                                    return
                                await self.controller.call("run.control", run_id=r["run_id"], command_id=command_id(), operation="cancel" if r["status"] == "RUNNING" else "abandon")
                                await self.refresh()
                            if run.get("can_end", False):
                                self.button("结束执行", end)
                            if run["status"] == "RUNNING":
                                async def pause(rid=run["run_id"]):
                                    await self.controller.call("run.control", run_id=rid, command_id=command_id(), operation="pause")
                                    await self.refresh()
                                self.button("暂停", pause)
                            self.button("删除执行", delete_selected, flat=True).props("icon=delete dense aria-label=删除执行").classes("tw-danger")
                    ui.label(f"运行编号 #{short_run_id(run['run_id'])} · 环境 {environments.get(run['environment_id'], '默认环境')} · {local_run_time(run.get('started_at'))}").classes("text-xs text-gray-500 mt-2")

                definition = definition_steps or []
                total = len(definition)
                latest_by_step = {}
                for attempt in run["attempts"]:
                    if attempt.get("valid"):
                        latest_by_step[attempt["step_id"]] = attempt
                succeeded_count = sum(item.get("status") == "SUCCEEDED" for item in latest_by_step.values())
                with ui.card().classes("tw-run-progress-card w-full"):
                    with ui.row().classes("w-full justify-between items-center flex-wrap gap-2"):
                        ui.label("步骤进度").classes("text-lg font-semibold")
                        ui.label(f"{succeeded_count} / {total} 已完成 · 点击节点查看步骤").classes("text-sm text-gray-500")
                    with ui.row().classes("w-full items-center gap-3 mt-2"):
                        ui.linear_progress(min(1, succeeded_count / total) if total else 0, show_value=False).props("rounded size=7px color=primary").classes("grow")
                    with ui.row().classes("tw-step-track"):
                        for index, step in enumerate(definition):
                            attempts = [a for a in run["attempts"] if a["step_id"] == step["step_id"] and a["valid"]]
                            step_status = attempts[-1]["status"] if attempts else None
                            is_selected = (
                                self.state.selected_step_run_id == run["run_id"]
                                and self.state.selected_step_id == step["step_id"]
                                or self.state.selected_step_run_id != run["run_id"]
                                and self.default_step_id(run, definition) == step["step_id"]
                            )
                            classes = "tw-step-node" + (" is-selected" if is_selected else "")
                            classes += " is-succeeded" if step_status == "SUCCEEDED" else " is-failed" if step_status == "FAILED" else " is-unknown" if step_status == "UNKNOWN" else " is-running" if step_status == "RUNNING" else " is-pending"
                            with ui.column().classes(classes):
                                self.button("✓" if step_status == "SUCCEEDED" else str(index + 1), lambda rid=run["run_id"], sid=step["step_id"]: self.select_step(rid, sid), flat=True).props(f'round dense aria-label="查看步骤 {index + 1}"').classes("tw-step-dot")
                                self.button(step["name"], lambda rid=run["run_id"], sid=step["step_id"]: self.select_step(rid, sid), flat=True).classes("tw-step-name")
                                ui.label(STATUS.get(step_status, "未执行")).classes("text-xs text-gray-500")
                                if step_status == "SUCCEEDED":
                                    self.button("查看结果", lambda r=run, st=step: self.step_result_dialog(r, st), flat=True)
                                elif step_status in {"FAILED", "UNKNOWN"}:
                                    self.button("查看错误", lambda a=attempts[-1], st=step: self.step_error_dialog(a, st), flat=True)

                with ui.tabs().classes("tw-run-tabs") as run_tabs:
                    detail_tab = ui.tab("执行详情")
                    history_tab = ui.tab("历史记录")
                with ui.tab_panels(run_tabs, value=detail_tab).classes("tw-run-tab-panels w-full"):
                    with ui.tab_panel(detail_tab):
                        self.run_area = ui.column().classes("tw-run-step-detail tw-panel w-full gap-3")
                    with ui.tab_panel(history_tab):
                        with ui.card().classes("tw-run-history w-full"):
                            ui.label("历史尝试").classes("text-lg font-semibold")
                            attempts = run.get("attempts", [])
                            if not attempts:
                                ui.label("暂无步骤尝试记录。").classes("text-sm text-gray-500")
                            for attempt in reversed(attempts):
                                step_name = next((item["name"] for item in definition if item["step_id"] == attempt["step_id"]), attempt["step_id"])
                                valid_label = "当前有效" if attempt.get("valid") else "已失效"
                                with ui.expansion(f"尝试 {attempt['attempt_no']} · {step_name} · {STATUS.get(attempt['status'], attempt['status'])} · {valid_label}", icon="history").classes("tw-history-attempt w-full"):
                                    ui.label(f"开始：{local_run_time(attempt.get('started_at'))} · 结束：{local_run_time(attempt.get('finished_at'))}").classes("text-xs text-gray-500")
                                    ui.label("有效状态：" + valid_label).classes("text-sm text-gray-600")
                                    ui.label("本次输入").classes("font-medium mt-2")
                                    ui.code(attempt.get("input_summary_json") or "{}", language="json").classes("w-full")
                                    attempt_refs = [ref for ref in run.get("results", []) if ref.get("attempt_id") == attempt["attempt_id"]]
                                    ui.label("输出与结果引用").classes("font-medium mt-2")
                                    if not attempt_refs:
                                        ui.label("此尝试没有保存输出引用。")
                                    for ref in attempt_refs:
                                        with ui.row().classes("w-full items-center justify-between gap-2 flex-wrap"):
                                            ui.label(f"{ref.get('kind', '结果')} · {ref.get('state', 'UNKNOWN')} · {ref.get('media_type', '未知类型')}")
                                            attempt_step = next((item for item in definition if item["step_id"] == attempt["step_id"]), None)
                                            if attempt_step and ref.get("state") == "AVAILABLE":
                                                self.button("查看结果", lambda r=run, st=attempt_step, aid=attempt["attempt_id"]: self.step_result_dialog(r, st, aid))
                                    ui.label("错误").classes("font-medium mt-2")
                                    ui.label(attempt.get("error_code") or "无错误代码")
                                    ui.label(attempt.get("error_summary") or "无错误摘要").classes("whitespace-pre-wrap")
                                    ui.label("本次尝试日志").classes("font-medium mt-2")
                                    logs = ui.column().classes("w-full")
                                    history_identity = (self.page_generation(), self.page(), run["run_id"], self.state.selected_step_id)
                                    async def load_attempt_logs(target=attempt, area=logs, expected=history_identity, source_run=run):
                                        if area.is_deleted:
                                            return
                                        area.clear()
                                        with area:
                                            ui.label("正在读取本次尝试日志…").classes("text-sm text-gray-500")
                                        events = await self.controller.call("run.events", run_id=source_run["run_id"])
                                        if (area.is_deleted or expected != (self.page_generation(), self.page(), self.run_id, self.state.selected_step_id)):
                                            return
                                        selected_events = [event for event in events if event.get("attempt_id") == target["attempt_id"]]
                                        area.clear()
                                        with area:
                                            ui.code(document_text(readable_metadata(selected_events, step_names(source_run, definition))), language="json").classes("w-full")
                                    ui.button("加载尝试日志", on_click=load_attempt_logs).props("flat dense")

    async def refresh(self):
        if self.page() not in {"run", "executions"}:
            return
        self.refresh_sequence += 1
        request_sequence = self.refresh_sequence
        page_identity = (self.page_generation(), self.page())
        def current_page():
            return page_identity == (self.page_generation(), self.page()) and self.page() in {'run', 'executions'}

        await self.render_rows()
        if not current_page() or request_sequence != self.refresh_sequence:
            return

        identity = (
            self.page_generation(), self.page(), self.run_id,
            self.state.selected_step_run_id, self.state.selected_step_id,
        )
        def current_run_page():
            return request_sequence == self.refresh_sequence and identity == (
                self.page_generation(), self.page(), self.run_id,
                self.state.selected_step_run_id, self.state.selected_step_id,
            ) and self.page() in {'run', 'executions'}
        if not current_run_page():
            return
        if self.run_area is None:
            self.run_signature = None
            return
        run = (
            await self.controller.call("run.get", run_id=self.run_id)
            if self.run_id
            else None
        )
        if not current_run_page():
            return
        signature = document_text([run, self.state.selected_step_run_id, self.state.selected_step_id])
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
            if not current_run_page():
                return
            with ui.row().classes('w-full justify-between items-center'):
                ui.label('运行状态：' + STATUS[run['status']]).classes('text-lg font-medium')
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
                        "step.list", task_id=run["task_id"]
                    )
                }
            )
            if not current_run_page():
                return
            selected_id = self.selected_step(run, definition["steps"])
            selected = next((step for step in definition["steps"] if step["step_id"] == selected_id), None)
            if selected is None:
                ui.label("该执行没有可查看的步骤")
            else:
                step = selected
                attempts = [a for a in run["attempts"] if a["step_id"] == step["step_id"]]
                latest = next((a for a in reversed(attempts) if a["valid"]), None)
                step_status = STATUS.get(latest["status"], latest["status"]) if latest else "未执行"
                with ui.card().classes("tw-selected-step-card w-full"):
                    with ui.row().classes("w-full items-center justify-between gap-3 flex-wrap"):
                        with ui.row().classes("items-center gap-3"):
                            ui.icon("article").classes("text-blue-600")
                            with ui.column().classes("gap-0"):
                                ui.label(f"{definition['steps'].index(step) + 1:02d} · {step['name']}").classes("text-lg font-semibold")
                                ui.label("所选步骤 · 选择进度节点只查看详情，不会启动执行").classes("text-sm text-gray-500")
                        ui.label(step_status).classes("tw-status " + ("tw-status-" + latest["status"].lower() if latest else "tw-status-ready"))
                    with ui.row().classes("w-full items-center justify-between gap-3 flex-wrap mt-3"):
                        ui.label(f"前置间隔：{step.get('delay_after_previous_seconds', 0)} 秒").classes("text-sm text-gray-500")
                        with ui.row().classes("items-center gap-2 flex-wrap"):
                            unsafe = any(
                                attempt["valid"] and (
                                    attempt["status"] == "UNKNOWN"
                                    or attempt["status"] == "FAILED" and attempt.get("effect_state") in {"UNKNOWN", "SUCCEEDED"}
                                )
                                for attempt in run["attempts"]
                            )
                            if run["status"] in {"READY", "PAUSED", "FAILED", "INTERRUPTED", "SUCCEEDED"} and not unsafe:
                                self.button("执行到此步骤…", lambda r=run, st=step: self.choose_run_step(r, st), primary=True)
                            if latest and latest["status"] == "SUCCEEDED":
                                self.button("查看结果", lambda r=run, st=step, aid=latest["attempt_id"]: self.step_result_dialog(r, st, aid))
                            elif latest and latest["status"] in {"FAILED", "UNKNOWN"}:
                                self.button("查看错误", lambda a=latest, st=step: self.step_error_dialog(a, st))
                    if latest is None:
                        ui.label("此步骤尚未执行，因此还没有输入、输出或步骤日志。").classes("tw-empty-step-state mt-3")
                    else:
                        ui.label(f"尝试 {latest['attempt_no']} · {step_status}" + (" · 当前有效" if latest["valid"] else " · 已失效")).classes("text-sm text-gray-500 mt-3")
                        with ui.row().classes("tw-step-execution-overview w-full items-start gap-3"):
                            with ui.column().classes("tw-step-effective-input min-w-0 gap-2"):
                                ui.label("有效输入").classes("font-medium")
                                ui.code(latest.get("input_summary_json") or "{}", language="json").classes("w-full")
                            with ui.column().classes("tw-step-execution-info min-w-0 gap-2"):
                                ui.label("执行信息").classes("font-medium")
                                ui.label(f"尝试编号：{latest['attempt_no']} · {step_status}")
                                ui.label(f"开始：{local_run_time(latest.get('started_at'))} · 结束：{local_run_time(latest.get('finished_at'))}").classes("text-sm text-gray-600")
                                ui.label(f"结果引用：{sum(ref.get('attempt_id') == latest['attempt_id'] for ref in run.get('results', []))}").classes("text-sm text-gray-600")
                                ui.label(latest.get("error_summary") or "无错误摘要").classes("text-sm text-gray-600 whitespace-pre-wrap")
                        with ui.column().classes("tw-step-result-info w-full gap-2 mt-3"):
                            ui.label("输出与结果引用").classes("font-medium")
                            refs = [ref for ref in run["results"] if ref["attempt_id"] == latest["attempt_id"]]
                            if not refs:
                                ui.label("暂无此步骤输出。")
                            for ref in refs:
                                with ui.row().classes("w-full items-center justify-between flex-wrap"):
                                    ui.label(f"{ref['kind']} · {ref['state']} · {ref['media_type']}")
                                    if ref["state"] == "AVAILABLE":
                                        self.button("查看结果", lambda r=run, st=step, aid=latest["attempt_id"]: self.step_result_dialog(r, st, aid))
                            ui.label("错误 / 核对").classes("font-medium")
                            ui.label(latest["error_code"] or "无错误").classes("text-sm")
                            ui.label(latest["error_summary"] or "").classes("whitespace-pre-wrap text-sm")
                            if latest["valid"] and (
                                latest["status"] == "UNKNOWN"
                                or latest["status"] == "FAILED" and latest["effect_state"] in {"UNKNOWN", "SUCCEEDED"}
                            ):
                                self.button("核对外部业务结果", lambda a=latest: self.reconcile_dialog(a))
                    if len(attempts) > 1:
                        with ui.expansion(f"历史尝试 · {len(attempts)}", icon="history"):
                            for attempt in reversed(attempts[:-1]):
                                ui.label(f"尝试 {attempt['attempt_no']} · {STATUS[attempt['status']]}" + (" · 已失效" if not attempt["valid"] else " · 当前有效"))
            events = await self.controller.call("run.events", run_id=run["run_id"])
            if not current_run_page():
                return
            with ui.card().classes("tw-run-logs w-full mt-3"):
                log_text = document_text(readable_metadata(events, step_names(run, definition["steps"])))
                with ui.row().classes("w-full items-center justify-between gap-2 flex-wrap"):
                    ui.label("运行日志").classes("font-semibold")

                    async def copy_full_logs():
                        await self.controller.copy_text(log_text)
                        ui.notify("完整运行日志已复制")

                    async def show_full_logs():
                        with ui.dialog() as dialog, ui.card().classes("w-full max-w-5xl"):
                            ui.label("完整运行日志").classes("text-lg font-semibold")
                            ui.textarea("运行日志", value=log_text).props("readonly rows=20").classes("w-full tw-run-log-fulltext")

                            async def close_full_logs():
                                dialog.close()

                            with ui.row().classes("w-full justify-end gap-2"):
                                self.button("复制完整日志", copy_full_logs)
                                self.button("关闭", close_full_logs, flat=True)
                        dialog.open()

                    self.button("查看完整日志", show_full_logs, flat=True)
                    self.button("复制完整日志", copy_full_logs, flat=True)
                ui.code(log_text, language="json").classes("w-full")
