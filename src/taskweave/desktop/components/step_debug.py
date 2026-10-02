"""Debug controls and run lifecycle belong to the step debug components."""

import inspect
import json
import asyncio
from nicegui import ui
from taskweave.core.validation import TaskError
from taskweave.desktop.controller import command_id
from taskweave.desktop.display import readable_metadata, step_names
from taskweave.desktop.components.run_logs import LiveRunLogs

STATUS = {"DRAFT":"草稿", "VALIDATED":"已验证", "READY":"就绪", "RUNNING":"执行中", "PAUSED":"已暂停", "FAILED":"失败", "INTERRUPTED":"中断 / 待核对", "SUCCEEDED":"成功", "CANCELLED":"已结束", "UNKNOWN":"结果待核对"}

def document_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)

class StepDebugSession:
    """Own starting, continuing, and flow trial runs for one editor identity."""

    def __init__(self, *, controller, identity, task_id, save_editor, trial_form,
                 trial_environment, environment_select, trial_variables, trials, button,
                 confirm_end, resume_inputs, refresh_trial, refresh_trial_inputs,
                 update_environment, reset_feedback, trial_start_status, debug_state):
        self.controller, self.identity, self.task_id = controller, identity, task_id
        self.save_editor, self.trial_form = save_editor, trial_form
        self.trial_environment, self.environment_select = trial_environment, environment_select
        self.trial_variables, self.trials, self.button = trial_variables, trials, button
        self.confirm_end, self.resume_inputs = confirm_end, resume_inputs
        self.refresh_trial, self.refresh_trial_inputs = refresh_trial, refresh_trial_inputs
        self.update_environment, self.reset_feedback = update_environment, reset_feedback
        self.trial_start_status = trial_start_status
        self.debug_state = debug_state

    async def enter_debug(self):
        identity = self.identity()
        saved = await self.save_editor()
        if self.identity() != identity or saved.get("step_id") != identity[1]:
            return
        await self.refresh_trial_inputs(saved)
        if self.identity() != identity:
            return
        self.controller.reset_debug_conversation(saved["step_id"])
        self.debug_state.fresh_round = True
        self.debug_state.feedback = None
        self.debug_state.feedback_run_id = None
        self.debug_state.removed_feedback = set()
        self.debug_state.supplements.pop(saved["step_id"], None)
        self.debug_state.trial_signature = None
        await self.refresh_trial()

    async def settle_trial_start(self, run_id, timeout=0.8, *, expected_identity=None):
        """Wait for immediate validation, then refresh only the same debug session."""
        identity = expected_identity or self.identity()
        if self.identity() != identity or self.trials.get(identity[1]) != run_id:
            return
        status = self.trial_start_status()
        if status is not None and not status.is_deleted:
            status.text = "正在等待执行器和插件响应…"
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            current = await self.controller.call("run.get", run_id=run_id)
            if self.identity() != identity or self.trials.get(identity[1]) != run_id:
                return
            request = await self.controller.run_request(run_id)
            if self.identity() != identity or self.trials.get(identity[1]) != run_id:
                return
            if current["status"] != "RUNNING" or request.get("waiting_input") or current.get("attempts"):
                break
            await asyncio.sleep(0.05)
        self.debug_state.trial_signature = None
        await self.refresh_trial()
        if self.identity() != identity or self.trials.get(identity[1]) != run_id:
            return
        status = self.trial_start_status()
        if status is not None and not status.is_deleted:
            status.text = ""

    async def _reset_feedback(self):
        result = self.reset_feedback()
        if inspect.isawaitable(result):
            await result

    async def start_flow_trial(self):
        identity = self.identity()
        saved = await self.save_editor()
        if self.identity() != identity or saved["step_id"] != identity[1]:
            return
        steps = await self.controller.call("step.list", task_id=self.task_id())
        if self.identity() != identity:
            return
        eligible = [step for step in steps if step["position"] <= saved["position"]]
        if not eligible:
            return
        with ui.context.client.layout, ui.dialog() as dialog, ui.card().classes("w-full max-w-2xl"):
            self.flow_dialog_open = True
            dialog.on("hide", lambda: setattr(self, "flow_dialog_open", False))
            ui.label("从选定步骤调试到当前步骤").classes("text-lg")
            start = ui.select({step["step_id"]: f"{i + 1}. {step['name']}" for i, step in enumerate(eligible)}, value=eligible[0]["step_id"], label="开始步骤").classes("w-full")
            ui.label("默认从第一步开始。使用上方环境和本次输入，按本次调试结果传递依赖。").classes("text-gray-500")

            async def launch():
                if self.identity() != identity:
                    dialog.close()
                    return
                form = self.trial_form()
                environment = self.trial_environment()
                run = await self.controller.call(
                    "step.trial.flow", step_id=saved["step_id"], inputs=form.task_values(),
                    step_inputs={saved["step_id"]: form.step_values()},
                    environment_id=environment.value or None, command_id=command_id(),
                    defer_inputs=True, start_step_id=start.value,
                )
                if self.identity() != identity:
                    return
                self.trials[saved["step_id"]] = run["run_id"]
                dialog.close()
                await self.settle_trial_start(run["run_id"])

            with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                self.button("开始调试", launch, primary=True)
                ui.button("取消", on_click=dialog.close).props("outline")
        dialog.open()

    async def start_trial(self, continue_session=False):
        identity = self.identity()
        status = self.trial_start_status()
        if status is not None and not status.is_deleted:
            status.text = "正在等待执行器和插件响应…"
        saved = await self.save_editor()
        if self.identity() != identity or saved["step_id"] != identity[1]:
            return
        await self._reset_feedback()
        form = self.trial_form()
        environment = self.trial_environment()
        if continue_session:
            previous_id = self.trials.get(saved["step_id"])
            if previous_id:
                previous = await self.controller.call("run.get", run_id=previous_id)
                if self.identity() != identity:
                    return
                previous_request = await self.controller.run_request(previous_id)
                if self.identity() != identity:
                    return
                if previous.get("can_end") and previous["environment_id"] != (environment.value or None):
                    if not await self.confirm_end(previous) or self.identity() != identity:
                        return
                    await self.controller.call("run.control", run_id=previous_id, command_id=command_id(), operation="abandon")
                    if self.identity() != identity:
                        return
                if previous.get("can_end") and previous["status"] != "CANCELLED" and previous["environment_id"] == (environment.value or None):
                    waiting = previous_request.get("waiting_input")
                    if waiting:
                        if waiting["scope"] == "step" and waiting["step_id"] != saved["step_id"]:
                            ui.notify("请先填写下方等待步骤的输入，再继续。")
                            return
                        values = form.task_values() if waiting["scope"] == "task" else form.step_values()
                        await self.resume_inputs(previous, values, expected_identity=identity)
                        if self.identity() == identity:
                            await self.refresh_trial()
                        return
                    uncertain = any(a["valid"] and (a["status"] == "UNKNOWN" or (a["status"] == "FAILED" and a["effect_state"] in {"UNKNOWN", "SUCCEEDED"})) for a in previous["attempts"])
                    if uncertain:
                        with ui.dialog() as retry_dialog, ui.card().classes("w-full max-w-xl"):
                            ui.label("保留当前页面并再次调试？").classes("text-lg")
                            ui.label("上次操作结果未确认，请先检查当前页面；再次执行可能重复点击或提交。浏览器会保留，上次失败记录不会被改写。")
                            with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                                ui.button("确认再次调试", on_click=lambda: retry_dialog.submit(True))
                                ui.button("取消", on_click=lambda: retry_dialog.submit(False)).props("outline")
                        if not await retry_dialog or self.identity() != identity:
                            return
                    run = await self.controller.repeat_trial(saved, previous_id, overrides=form.values())
                    if self.identity() != identity:
                        return
                    self.trials[saved["step_id"]] = run["run_id"]
                    self.update_environment(previous["environment_id"])
                    await self.settle_trial_start(run["run_id"])
                    return
            run = await self.controller.trial(saved, form.values(), environment.value or None)
            if self.identity() != identity:
                return
            self.trials[saved["step_id"]] = run["run_id"]
            await self.settle_trial_start(run["run_id"])
            return
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-2xl"):
            ui.label("调试有效输入").classes("text-lg")
            ui.label("前序结果依赖在此填写实际值；调试不会执行其他步骤。")
            environment = await self.environment_select()
            if self.identity() != identity:
                return
            form = await self.trial_variables(saved, environment)
            if self.identity() != identity:
                return

            async def launch():
                run = await self.controller.trial(saved, form.values(), environment.value or None)
                if self.identity() != identity:
                    return
                self.trials[saved["step_id"]] = run["run_id"]
                self.update_environment(environment.value)
                current_environment = self.trial_environment()
                if current_environment.value != environment.value:
                    current_environment._tw_skip_change = True
                    current_environment.value = environment.value
                await self.trial_form().replace(environment.value or None, form.task_values(), form.step_values())
                dialog.close()
                await self.settle_trial_start(run["run_id"])

            with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                self.button("开始调试", launch, primary=True)
                ui.button("取消", on_click=dialog.close).props("outline")
        dialog.open()


class StepDebugPanel:
    def __init__(self, button, controller, identity, run_id, status, *, page=lambda: "",
                 task_id=lambda: None, step_id=lambda: None, edit_controls=lambda: None,
                 trials=None, state=None, pending_inputs=None,
                 step_result_dialog=None, navigate_step_debug=None,
                 debug_round_fresh=lambda: False, logs_allowed=lambda: True):
        self.button, self.controller = button, controller
        self.identity, self.run_id, self.status = identity, run_id, status
        self.page, self.task_id, self.step_id = page, task_id, step_id
        self.edit_controls, self.trials, self.state = edit_controls, trials if trials is not None else {}, state
        self.pending_inputs, self.step_result_dialog = pending_inputs, step_result_dialog
        self.navigate_step_debug, self.debug_round_fresh = navigate_step_debug, debug_round_fresh
        self.trial_area = None
        self.logs_area = None
        self.actions = {}
        self._refresh_lock = asyncio.Lock()
        self._settled_identity = None
        self._logs_identity = None
        self._live_logs = None
        self.logs_allowed = logs_allowed

    def _current(self, identity, run_id=None):
        return (self.page() == "editor" and self.identity() == identity
                and (run_id is None or self.run_id(identity[1]) == run_id))

    def dispose(self):
        if self._live_logs is not None:
            self._live_logs.dispose()
            self._live_logs = None
        self.trial_area = None
        self.logs_area = None
        self.actions.clear()

    async def poll(self):
        key = (self.identity(), self.run_id(self.identity()[1]))
        if self._refresh_lock.locked() or self._settled_identity == key:
            return
        await self.refresh_trial()

    async def refresh_trial(self):
        async with self._refresh_lock:
            await self._refresh_trial()

    async def _refresh_trial(self):
        identity = self.identity()
        if self.page() != "editor" or not self.edit_controls() or self.trial_area is None or self.trial_area.is_deleted:
            return
        task_id, step_id = identity[:2]
        run_id = self.run_id(step_id)
        if not run_id:
            runs = await self.controller.call("run.list", task_id=task_id)
            if not self._current(identity): return
            previous = next((row for row in reversed(runs) if row.get("trial_step_id") == step_id), None)
            if previous:
                run_id = previous["run_id"]
                self.trials[step_id] = run_id
        run = await self.controller.call("run.get", run_id=run_id) if run_id else None
        if not self._current(identity, run_id): return
        key = (identity, run_id)
        self._settled_identity = key if not run or run["status"] in {"SUCCEEDED", "FAILED", "CANCELLED", "UNKNOWN", "INTERRUPTED"} else None
        signature = document_text({"run":run, "fresh_round":bool(self.debug_round_fresh())})
        if signature == self.state.trial_signature: return
        self.refresh(run)
        self.state.trial_signature = signature
        self.trial_area.clear()
        if self.logs_area is not None and not self.logs_area.is_deleted and self._logs_identity != key:
            self._logs_identity = key
            area = self.logs_area
            if self._live_logs is not None:
                self._live_logs.dispose()
            area.clear()
            with area:
                ui.label("暂无调试日志" if not run_id else "运行编号：" + run_id).classes("text-xs break-all")
                if run_id:
                    self._live_logs = LiveRunLogs(self.controller, run_id,
                        lambda: self._current(identity, run_id) and self.logs_area is area and not area.is_deleted,
                        allowed=self.logs_allowed)
                    output = ui.textarea("调试日志（按需加载）").props("readonly rows=12").classes("w-full font-mono")
                    log_text, page_index = "", 0
                    page_size = 24000
                    page_status = ui.label("尚未加载日志").classes("text-xs text-gray-500")
                    def show_page(offset=0):
                        nonlocal page_index
                        pages = max(1, (len(log_text) + page_size - 1) // page_size)
                        page_index = max(0, min(pages - 1, page_index + offset))
                        output.value = log_text[page_index * page_size:(page_index + 1) * page_size]
                        page_status.text = f"第 {page_index + 1} / {pages} 页 · 共 {len(log_text)} 字符"
                        previous.set_enabled(page_index > 0)
                        following.set_enabled(page_index + 1 < pages)
                    async def load_logs():
                        nonlocal log_text, page_index
                        load.disable()
                        try:
                            events = await self.controller.call("run.events", run_id=run_id)
                            text = await asyncio.to_thread(lambda: document_text(readable_metadata(events, {})))
                            if self._current(identity, run_id) and not output.is_deleted:
                                log_text, page_index = text, 0
                                show_page()
                        finally:
                            if not load.is_deleted: load.enable()
                    with ui.row().classes("w-full items-center gap-2"):
                        load = ui.button("查看 / 刷新日志", on_click=load_logs).props("flat")
                        previous = ui.button("上一页", on_click=lambda: show_page(-1)).props("flat")
                        following = ui.button("下一页", on_click=lambda: show_page(1)).props("flat")
                        previous.disable()
                        following.disable()
        with self.trial_area:
            if self.debug_round_fresh():
                ui.label("AI 修复上下文已清空。调试实例、插件资源和运行记录继续保留。")
                return
            await self.pending_inputs(run)
            if not self._current(identity, run_id): return
            if not run_id:
                ui.label("暂无调试记录。修改后请重新调试，再确认保存。")
                return
            ui.label("调试状态：" + STATUS.get(run["status"], run["status"]))
            steps = await self.controller.call("step.list", task_id=task_id)
            if not self._current(identity, run_id): return
            names = step_names(run, steps)
            failure = next((a for a in reversed(run["attempts"])
                            if a["valid"] and a["status"] in {"FAILED", "UNKNOWN"}), None)
            if failure:
                ui.label(f"失败步骤：{names.get(failure['step_id'], '未知步骤')} · 尝试 {failure['attempt_no']} · "
                         f"{failure['error_code'] or '结果待核对'}：{failure['error_summary'] or '请查看调试日志'}").classes("text-red-700 break-words")
            for attempt in run["attempts"]:
                ui.label(f"{names.get(attempt['step_id'], '未知步骤')} · 尝试 {attempt['attempt_no']} · {STATUS.get(attempt['status'], attempt['status'])}")
                if attempt["error_code"]:
                    ui.label(f"{attempt['error_code']}：{attempt['error_summary']}").classes("text-red-700")
                if attempt["status"] == "SUCCEEDED" and attempt["valid"]:
                    try:
                        value = await self.controller.call("run.output", run_id=run_id, step_id=attempt["step_id"])
                    except TaskError as error:
                        if error.code != "OUTPUT_NOT_AVAILABLE":
                            raise
                        if not self._current(identity, run_id): return
                        ui.label("本步骤无业务数据输出；成功状态与文件结果不受影响。").classes("text-sm text-gray-500")
                    else:
                        if not self._current(identity, run_id): return
                        ui.textarea("业务数据输出", value=document_text(value)).props("readonly rows=6").classes("w-full font-mono")
                if any(ref["attempt_id"] == attempt["attempt_id"] for ref in run["results"]):
                    result_step = {"step_id":attempt["step_id"], "name":names.get(attempt["step_id"], "步骤")}
                    self.button("查看结果", lambda r=run, st=result_step, aid=attempt["attempt_id"]: self.step_result_dialog(r, st, aid))
            failed_other = next((a for a in reversed(run["attempts"]) if a["valid"] and a["status"] in {"FAILED","UNKNOWN"} and a["step_id"] != step_id), None)
            if failed_other:
                self.button("打开失败步骤", lambda st=failed_other["step_id"], rid=run_id: self.navigate_step_debug(task_id, st, run_id=rid, preserve_repair=True))
            failed = next((a for a in reversed(run["attempts"]) if a["valid"] and a["status"] in {"FAILED","UNKNOWN"} and a["step_id"] == step_id), None)
            if failed:
                feedback = await self.controller.trial_feedback(run_id, step_id)
                if not self._current(identity, run_id): return
                self.state.feedback = feedback
                self.state.feedback_run_id = run_id
                with ui.expansion("本次报错上下文", icon="error_outline").classes("w-full border rounded"):
                    ui.label("下列内容默认提供给 AI；删除只影响本轮 AI 请求，不删除运行记录。").classes("text-sm text-gray-500")
                    for key, title in [("executed_step_content","本次实际执行的步骤内容"),("failed_action","失败动作"),("failure_snapshots","失败快照")]:
                        value = feedback.get(key)
                        if key in self.state.removed_feedback or not value: continue
                        with ui.expansion(title).classes("w-full"):
                            with ui.row().classes("w-full justify-end"):
                                def remove_error_part(part=key):
                                    if self._current(identity, run_id):
                                        self.state.removed_feedback.add(part)
                                        self.state.trial_signature = None
                                ui.button(icon="delete", on_click=remove_error_part).props("flat round color=negative").tooltip("不再发送给 AI")
                            ui.textarea(value=document_text(value)).props("readonly rows=8").classes("w-full font-mono")

    def render_actions(self, container, single, flow, end):
        identity = self.identity()
        def failure(action):
            async def apply(_error=None):
                if self.identity() != identity:
                    return
                control = self.actions.get(action)
                if control is not None and not control.is_deleted:
                    self.style_action(action, "FAILED")
                status = self.status()
                if status is not None and not status.is_deleted:
                    status.text = ""
            return apply

        async def sync_end():
            if self.identity() != identity:
                return
            step_id = identity[1]
            run_id = self.run_id(step_id)
            run = await self.controller.call("run.get", run_id=run_id) if run_id else None
            control = self.actions.get("end")
            if (control is not None and not control.is_deleted and self.identity() == identity
                    and self.run_id(step_id) == run_id):
                control.set_enabled(bool(run and run.get("can_end")))

        with container:
            self.actions = {
                "single": self.button("调试当前步骤", single, primary=True, on_failure=failure("single")),
                "flow": self.button("从选定步骤调试", flow, on_failure=failure("flow")),
                "end": self.button("结束调试", end, flat=True, on_failure=failure("end"), on_settled=sync_end),
            }
            for control in self.actions.values():
                control.classes("tw-debug-action w-full")
                control.props("no-wrap")
                control.classes(add=f"tw-debug-action-{next(name for name, item in self.actions.items() if item is control)}")
                self.style_action(control, None)
        return self.actions

    def style_action(self, action, state):
        control = action if not isinstance(action, str) else self.actions.get(action)
        if control is None or control.is_deleted:
            return
        if state == "SUCCEEDED":
            control.props("text-color=teal-8").style("background: #f0fdfa; color: #0f766e; border: 1px solid #0f766e")
        elif state in {"FAILED", "UNKNOWN", "INTERRUPTED"}:
            control.props("text-color=red-7").style("background: #fef2f2; color: #b91c1c; border: 1px solid #dc2626")
        else:
            action_name = next((name for name, item in self.actions.items() if item is control), None)
            if action_name == "single":
                control.props("color=primary text-color=white").style("background:#2563eb;color:white;border:1px solid #2563eb")
            elif action_name == "flow":
                control.props("text-color=primary").style("background:white;color:#2563eb;border:1px solid #b8cef9")
            else:
                control.props("text-color=grey-8").style("background:#f5f7fb;color:#526079;border:1px solid #e2e9f3")

    async def end(self, confirm_end, refresh):
        identity = self.identity()
        step_id = identity[1]
        run_id = self.run_id(step_id)
        if not run_id:
            return

        def current():
            return self.identity() == identity and self.run_id(step_id) == run_id

        run = await self.controller.call("run.get", run_id=run_id)
        if not current():
            return
        if not run.get("can_end"):
            self.refresh(run)
            return
        if not await confirm_end(run) or not current():
            return
        run = await self.controller.call("run.get", run_id=run_id)
        if not current():
            return
        if not run.get("can_end"):
            self.refresh(run)
            return
        from taskweave.core.validation import TaskError
        from taskweave.desktop.controller import command_id

        operation = "cancel" if run["status"] == "RUNNING" else "abandon"
        try:
            try:
                await self.controller.call("run.control", run_id=run_id, command_id=command_id(), operation=operation)
            except TaskError as exc:
                if operation != "cancel" or exc.code != "RUN_STATE_INVALID":
                    raise
                await self.controller.call("run.control", run_id=run_id, command_id=command_id(), operation="abandon")
            if current():
                self.style_action("end", "SUCCEEDED")
        except Exception:
            if current():
                self.style_action("end", "FAILED")
            raise
        if current():
            await refresh()

    def refresh(self, run):
        end = self.actions.get("end")
        if end is None or end.is_deleted:
            return
        end.set_enabled(bool(run and run.get("can_end")))
        if run:
            import json
            kind = "flow" if json.loads(run["request_json"]).get("flow_trial") else "single"
            self.style_action(kind, run["status"])
