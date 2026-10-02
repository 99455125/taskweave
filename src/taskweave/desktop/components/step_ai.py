"""AI-generated step description flow and guarded candidate preview."""

import asyncio
import json

from nicegui import ui
from taskweave.core.validation import TaskError, normalize_step
from taskweave.desktop.contexts import context_ai_items, render_preview_attachments


def exclusive_ai_flow(method):
    """One modal/request flow per editor, acquired before the first await."""
    from functools import wraps
    @wraps(method)
    async def run(self, *args, **kwargs):
        if getattr(self, "_ai_flow_active", False):
            ui.notify("AI 操作正在处理中，请勿重复发起。", type="info")
            return
        lookup = getattr(self, 'retained_request', None)
        retained = lookup() if lookup else None
        if method.__name__ != 'recover_generation' and retained and not retained['task'].done():
            ui.notify("当前步骤的 AI 请求仍在处理中，请查看上次 AI 结果。", type="info")
            return
        self._ai_flow_active = True
        try:
            # Trial refreshes can clear their slot while an awaited dialog is open.
            with ui.context.client.layout:
                return await method(self, *args, **kwargs)
        finally:
            self._ai_flow_active = False
    return run


def submit_ai_choice(dialog, values):
    """Lock both channels immediately after the first accepted selection."""
    submitted = False
    buttons = []
    def submit(factory):
        nonlocal submitted
        if submitted:
            return
        submitted = True
        for button in buttons:
            button.disable()
        dialog.submit(factory())
    for title, factory in values:
        buttons.append(ui.button(title, on_click=lambda _e=None, f=factory: submit(f)).props("outline"))
    return buttons


class StepAIEditor:
    def __init__(self, controller, button, save_editor, environment_id, controls, identity,
                 *, debug_state=None, trials=None, reset_conversation=None, confirmation_step=None,
                 author_step=None, authoring_request=None):
        self.controller, self.button, self.save_editor = controller, button, save_editor
        self.environment_id, self.controls = environment_id, controls
        self.identity = identity
        self.debug_state, self.trials = debug_state, trials if trials is not None else {}
        self.reset_conversation = reset_conversation
        self.confirmation_step = confirmation_step or save_editor
        self.pending_identity = None
        self.author_step, self.authoring_request = author_step, authoring_request

    def retained_request(self):
        lookup = getattr(self, 'authoring_request', None)
        return lookup(self.identity()[1]) if lookup else None

    async def _request(self, operation, saved, **params):
        if self.author_step:
            return await self.author_step(operation, saved, **params)
        return await self.controller.call(operation, **params)

    @exclusive_ai_flow
    async def recover_generation(self, *, repaint):
        request = self.retained_request()
        if request is None:
            return
        identity = self.identity()
        proposal = await asyncio.shield(request['task'])
        if self.identity() != identity or self.retained_request() is not request:
            return
        await self._validate_retained_request(request, identity)
        if self.identity() != identity:
            return
        saved, params = request['saved'], request['params']
        if request['operation'] == 'step.generate_goal':
            await self._present_goal_result(saved, proposal, identity, web_chat=params.get('export_only', False))
        else:
            await self._present_generation_result((saved, proposal, identity), bool(params.get('feedback')), repaint,
                                                  web_chat=params.get('export_only', False))

    async def _validate_retained_request(self, request, identity):
        if request is None:
            return
        if self.identity() != identity or self.retained_request() is not request:
            raise TaskError('EDIT_CONFLICT', 'AI 请求或当前步骤已变化，请重新查看结果。')
        saved, params = request['saved'], request['params']
        latest = await self.controller.call('step.get', step_id=saved['step_id'])
        if self.identity() != identity or self.retained_request() is not request:
            raise TaskError('EDIT_CONFLICT')
        controls = self.controls()
        if (latest['content_hash'] != saved['content_hash'] or not controls
                or controls['code'].value != saved['step_content']):
            raise TaskError('EDIT_CONFLICT', '步骤已修改，上次 AI 结果不能采纳，请重新生成。')
        feedback = params.get('feedback') or {}
        if feedback.get('run_id'):
            run_id = feedback['run_id']
            run = await self.controller.call('run.get', run_id=run_id)
            if self.identity() != identity or self.retained_request() is not request:
                raise TaskError('EDIT_CONFLICT')
            failure = next((attempt for attempt in reversed(run.get('attempts', []))
                            if attempt.get('valid') and attempt.get('status') in {'FAILED', 'UNKNOWN'}), None)
            if (self.trials.get(saved['step_id']) != run_id or failure is None
                    or failure.get('step_id') != saved['step_id']
                    or failure.get('attempt_id') != feedback.get('attempt_id')):
                raise TaskError('VALIDATION_EVIDENCE_INVALID', '调试尝试已变化，请重新生成修复建议。')

    @exclusive_ai_flow
    async def choose_generation_mode(self, *, repaint):
        identity = self.identity()
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-md"):
            ui.label("AI 生成内容").classes("text-lg font-medium")
            with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                submit_ai_choice(dialog, [("使用 API", lambda: "api"), ("使用 Chat 网页", lambda: "chat")])
                ui.button("取消", on_click=lambda:dialog.submit(None)).props("outline")
        mode = await dialog
        if not mode or self.identity() != identity: return
        web_chat = mode == "chat"
        result = await self.generate_content(web_chat=web_chat)
        await self._present_generation_result(result, False, repaint, web_chat=web_chat)

    @exclusive_ai_flow
    async def choose_repair_mode(self, supplement_control=None, *, repaint):
        if self.debug_state is None: return
        step_id = self.identity()[1]
        identity = self.identity()
        feedback = self.debug_state.feedback or {}
        feedback_run_id = self.debug_state.feedback_run_id
        active_run_id = self.trials.get(step_id)
        has_feedback = False
        if active_run_id:
            run = await self.controller.call("run.get", run_id=active_run_id)
            if self.identity() != identity or self.trials.get(step_id) != active_run_id:
                return
            failed = next((attempt for attempt in reversed(run.get("attempts", []))
                           if attempt.get("valid") and attempt.get("status") in {"FAILED", "UNKNOWN"}), None)
            if failed and failed.get("step_id") == step_id:
                feedback = await self.controller.trial_feedback(active_run_id, step_id)
                if self.identity() != identity or self.trials.get(step_id) != active_run_id:
                    return
                has_feedback = bool(feedback and feedback.get("run_id") == active_run_id
                                    and feedback.get("attempt_id") == failed.get("attempt_id"))
                if has_feedback:
                    feedback_run_id = active_run_id
                    self.debug_state.feedback = feedback
                    self.debug_state.feedback_run_id = feedback_run_id
            else:
                feedback = {}
        if not has_feedback:
            feedback = {}
        with ui.dialog() as dialog, ui.card().classes("tw-repair-mode-dialog w-full max-w-4xl"):
            with ui.row().classes("tw-repair-dialog-header w-full items-center justify-between"):
                ui.label("AI · 修复步骤").classes("text-lg font-semibold")
                ui.button("关闭", on_click=lambda: dialog.submit(None), icon="close").props("flat dense")
            if has_feedback:
                with ui.column().classes("tw-repair-evidence w-full gap-2"):
                    ui.label("本次修复依据").classes("font-medium")
                    ui.input("运行编号", value=feedback_run_id).props("readonly").classes("w-full").tooltip(feedback_run_id)
                    ui.input("尝试编号", value=feedback["attempt_id"]).props("readonly").classes("w-full").tooltip(feedback["attempt_id"])
            else:
                ui.label("尚无当前步骤的失败运行与尝试记录；先完成一次调试，AI 修复才能引用真实依据。").classes("tw-repair-no-evidence w-full")
            rounds = ui.select(
                {-1:"全部历史",0:"不带历史",**{i:f"最近 {i} 轮" for i in range(1,11)}},
                value=-1,label="本轮携带的历史会话",
            ).classes("w-full")
            deduplicate = ui.checkbox("精简重复静态字段",value=True)
            supplement = ui.textarea(
                "本轮补充说明", value=(supplement_control.value or "") if supplement_control is not None else self.debug_state.supplements.get(step_id, ""),
                placeholder="补充本轮修复需要关注的细节（可选）",
            ).props("outlined autogrow").classes("tw-repair-supplement w-full")
            ui.label("依据当前步骤实际执行内容、失败动作、快照和日志生成；遵守移除项与脱敏设置。").classes("text-sm text-gray-500")
            with ui.row().classes("tw-repair-dialog-actions w-full items-center gap-2 flex-wrap"):
                api, chat = submit_ai_choice(dialog, [
                    ("大模型api调用", lambda: ("api", rounds.value, deduplicate.value, supplement.value or "")),
                    ("大模型网页chat调用", lambda: ("chat", rounds.value, deduplicate.value, supplement.value or "")),
                ])
                if not has_feedback:
                    api.disable(); chat.disable()
                ui.button("取消", on_click=lambda:dialog.submit(None)).props("outline")
        choice = await dialog
        if not choice or self.identity() != identity or not has_feedback: return
        current_run = await self.controller.call("run.get", run_id=feedback_run_id)
        if self.identity() != identity or self.trials.get(step_id) != feedback_run_id:
            return
        latest_failure = next((attempt for attempt in reversed(current_run.get("attempts", []))
                               if attempt.get("valid") and attempt.get("status") in {"FAILED", "UNKNOWN"}), None)
        if (latest_failure is None or latest_failure.get("step_id") != step_id
                or latest_failure.get("attempt_id") != feedback.get("attempt_id")):
            ui.notify("调试记录已变化，请重新打开 AI 修复并核对最新尝试。", type="warning")
            return
        mode, history_rounds, dedup, text = choice
        self.debug_state.supplements[step_id] = text
        if supplement_control is not None: supplement_control.value = text
        result = await self.generate_content(
            fix_logs=True, web_chat=mode == "chat", supplement=text,
            run_id=self.trials.get(step_id), history_rounds=history_rounds,
            deduplicate_history=dedup, feedback_override=feedback if has_feedback else None,
            feedback_run_id=feedback_run_id if has_feedback else None,
            removed_feedback=self.debug_state.removed_feedback if has_feedback else set(),
        )
        await self._present_generation_result(result, True, repaint, web_chat=mode == "chat")

    async def _present_generation_result(self, result, fix_logs, repaint, *, web_chat=False):
        if result is None: return
        saved, proposal, identity = result
        if proposal.get("history_trimmed"):
            ui.notify("本次已按选择携带限定轮数的历史对话。", type="info")
        if web_chat:
            await self.web_chat_dialog(saved, proposal, fix_logs, identity=identity, repaint=repaint)
        else:
            await self.present_content_candidate(saved, proposal, identity, repaint)

    async def confirm_step(self, repaint):
        from taskweave.core.validation import TaskError
        identity = self.identity()
        saved = await self.confirmation_step()
        if self.identity() != identity:
            return
        step_id = saved["step_id"]
        run_id = self.trials.get(step_id)
        confirmed = None
        if run_id:
            try:
                confirmed = await self.controller.confirm(saved, run_id)
            except TaskError as exc:
                if exc.code != "VALIDATION_EVIDENCE_INVALID": raise
        if confirmed is None:
            with ui.dialog() as dialog, ui.card().classes("w-full max-w-xl"):
                ui.label("当前已保存的步骤尚未调试通过，是否手动确认验证通过？")
                with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                    ui.button("取消",on_click=lambda:dialog.submit(False)).props("outline")
                    ui.button("确认验证通过",on_click=lambda:dialog.submit(True)).props("outline text-color=teal-8").style("background: #f0fdfa; border: 1px solid #0f766e")
            if not await dialog: return
            if self.identity() != identity: return
            confirmed = await self.controller.call("step.confirm.manual",step_id=step_id,expected_hash=saved["content_hash"],environment_id=self.environment_id() or None)
        if self.identity() != identity: return
        ui.notify("步骤验证成功",type="positive")
        controls = self.controls()
        if controls is not None:
            self.pending_identity = None
        await repaint()

    def new_debug_round(self, supplement_control=None):
        if self.debug_state is None: return
        step_id = self.identity()[1]
        if not step_id: return
        if self.reset_conversation:
            self.reset_conversation(step_id)
        self.debug_state.supplements.pop(step_id, None)
        self.debug_state.feedback = None
        self.debug_state.feedback_run_id = None
        self.debug_state.removed_feedback.clear()
        if supplement_control is not None and not supplement_control.is_deleted:
            supplement_control.value = ""
        ui.notify("已清空当前步骤的 AI 修复上下文；调试实例和运行记录继续保留", type="positive")

    async def generate_content(self, *, fix_logs=False, web_chat=False, supplement="", run_id=None,
                               history_rounds=None, deduplicate_history=True,
                               feedback_override=None, feedback_run_id=None, removed_feedback=()):
        """Build a guarded step proposal; return None when its editor became stale."""
        requested_identity = self.identity()
        saved = await self.save_editor()
        identity = self.identity()
        if identity != requested_identity or saved["step_id"] != identity[1]:
            return None
        trial = None
        feedback = None
        if fix_logs and run_id:
            trial = await self.controller.call("run.get", run_id=run_id)
            if self.identity() != identity:
                if feedback_override is not None:
                    ui.notify("当前调试尝试已变化，请重新打开 AI 修复并核对最新证据。", type="warning")
                return None
            if trial["attempts"]:
                failed = next((a for a in reversed(trial["attempts"])
                               if a["valid"] and a["status"] in {"FAILED", "UNKNOWN"}), None)
                if failed and failed["step_id"] != saved["step_id"]:
                    definition = json.loads(trial["definition_json"])["steps"]
                    name = next(st["name"] for st in definition if st["step_id"] == failed["step_id"])
                    raise TaskError("FORM_INVALID", "本次流程调试失败在“" + name + "”，请切换到该步骤修复。")
                feedback = await self.controller.trial_feedback(trial["run_id"], saved["step_id"])
                if feedback_override is not None and (
                    self.identity() != identity or self.trials.get(saved["step_id"]) != trial["run_id"]
                ):
                    ui.notify("当前调试尝试已变化，请重新打开 AI 修复并核对最新证据。", type="warning")
                    return None
                if self.identity() != identity:
                    return None
                if feedback_override is not None:
                    bound_attempt_id = feedback_override.get("attempt_id")
                    current_attempt_id = failed.get("attempt_id") if failed and failed.get("step_id") == saved["step_id"] else None
                    refreshed_run_id = feedback.get("run_id") if isinstance(feedback, dict) else None
                    refreshed_attempt_id = feedback.get("attempt_id") if isinstance(feedback, dict) else None
                    if (
                        feedback_run_id != trial["run_id"]
                        or feedback_override.get("run_id") != trial["run_id"]
                        or trial.get("run_id") != run_id
                        or self.trials.get(saved["step_id"]) != trial["run_id"]
                        or not bound_attempt_id
                        or bound_attempt_id != current_attempt_id
                        or refreshed_run_id != trial["run_id"]
                        or refreshed_attempt_id != current_attempt_id
                        or refreshed_attempt_id != bound_attempt_id
                    ):
                        ui.notify("当前调试尝试已变化，请重新打开 AI 修复并核对最新证据。", type="warning")
                        return None
                    feedback = dict(feedback_override)
                for key in removed_feedback:
                    feedback.pop(key, None)
        if fix_logs and feedback is None:
            raise TaskError("VALIDATION_EVIDENCE_INVALID", "请先执行当前步骤调试")
        generation_contexts = context_ai_items(
            await self.controller.call("context.ai", step_id=saved["step_id"])
        )
        if self.identity() != identity:
            return None
        if fix_logs:
            refreshed, availability = await self.controller.repair_contexts(saved, trial["run_id"], feedback)
            if self.identity() != identity:
                return None
            if refreshed:
                generation_contexts.append({"provider_id": "debug.refresh", "name": "本次调试刷新",
                    "context_notes": "", "order_index": len(generation_contexts),
                    "captures": [{"label": "当前页面", "capture_index": 0, "items": refreshed}]})
            feedback["current_context_status"] = availability
            if not availability["available"]:
                ui.notify("当前页面上下文无法刷新，将明确告知 AI；未打开新浏览器。", type="warning")
        ui.notify("正在准备网页对话内容。" if web_chat else "正在生成建议，界面保持响应；当前草稿已保存。")
        proposal = await self._request(
            "step.generate", saved, step_id=saved["step_id"], expected_hash=saved["content_hash"],
            step_description=saved["step_description"], feedback=feedback, contexts=generation_contexts,
            environment_id=self.environment_id() or None, repair_notes=supplement,
            use_history=fix_logs and history_rounds != 0,
            history_rounds=(-1 if fix_logs else 0) if history_rounds is None else history_rounds,
            deduplicate_history=deduplicate_history, export_only=web_chat,
        )
        if self.identity() != identity:
            return None
        return saved, proposal, identity

    async def present_content_candidate(self, saved, proposal, identity, repaint):
        if self.identity() != identity:
            return
        controls = self.controls()
        if not controls:
            return
        retained = self.retained_request()
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-4xl"):
            ui.label("AI 建议 · 采纳后保存为草稿").classes("text-lg")
            ui.label(proposal["explanation"])
            ui.code(self.controller.diff(saved["step_content"], proposal["proposed_content"]), language="diff").classes("w-full")
            if proposal["diagnostics"]:
                ui.label(json.dumps(proposal["diagnostics"], ensure_ascii=False, indent=2, default=str))

            async def accept():
                await self._validate_retained_request(retained, identity)
                controls = self.controls()
                if self.identity() != identity or not controls:
                    raise TaskError("EDIT_CONFLICT", "生成期间当前步骤已切换，请重新生成建议")
                if proposal["stale"] or controls["code"].value != saved["step_content"]:
                    raise TaskError("EDIT_CONFLICT", "生成期间内容已修改，请重新生成建议")
                controls["code"].value = proposal["proposed_content"]
                await self.save_editor()
                if self.identity() != identity:
                    return
                ui.notify("AI 建议已保存为草稿，下一次调试使用此内容。")
                dialog.close()
                await repaint()

            with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                self.button("采纳到编辑器", accept, primary=True)
                ui.button("舍弃", on_click=dialog.close).props("outline")
        dialog.open()

    async def web_chat_dialog(self, saved, exported, use_history, identity=None, *, repaint):
        import json
        import logging
        from taskweave.desktop.chat import parse_chat_reply
        identity = self.identity() if identity is None else identity
        if not self.identity() == identity:
            return
        retained = self.retained_request()
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-4xl"):
            ui.label("网页 AI 对话 · 不需要 API Key").classes("text-lg")
            ui.label("复制以下内容到网页 AI，再将它的整段回复粘贴到下方。推荐回复为包含 step_content 和 explanation 的 JSON；也兼容完整 Python 代码。")
            ui.textarea("复制到网页 AI 的内容", value=exported["prompt"]).props("readonly rows=12").classes("w-full")
            async def copy_prompt():
                await self.controller.copy_text(exported["prompt"])
                ui.notify("对话内容已复制")
            self.button("复制对话内容", copy_prompt)
            render_preview_attachments(exported)
            reply = ui.textarea("粘贴网页 AI 回复").classes("w-full").props("autogrow")
            async def preview_reply():
                await self._validate_retained_request(retained, identity)
                source, explanation = parse_chat_reply(reply.value or "")
                current = await self.controller.call("step.get", step_id=saved["step_id"])
                if (not self.identity() == identity or not self.controls()
                        or current["content_hash"] != exported["expected_hash"]
                        or self.controls()["code"].value != saved["step_content"]):
                    raise TaskError("EDIT_CONFLICT", "步骤已修改，请重新生成网页对话内容")
                candidate = normalize_step({**saved, "step_content": source})
                diagnostics = await self.controller.validate_step_candidate(candidate)
                if not self.identity() == identity:
                    return
                errors = [item.get("message", "") for item in diagnostics if item.get("severity") == "error"]
                if errors:
                    raise TaskError("CHAT_REPLY_INVALID", "；".join(errors))
                with ui.dialog() as preview, ui.card().classes("w-full max-w-4xl"):
                    ui.label("网页 AI 回复预览").classes("text-lg")
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
                        await self._validate_retained_request(retained, identity)
                        latest = await self.controller.call("step.get", step_id=saved["step_id"])
                        if (not self.identity() == identity or not self.controls()
                                or latest["content_hash"] != exported["expected_hash"]
                                or self.controls()["code"].value != saved["step_content"]):
                            raise TaskError("EDIT_CONFLICT", "预览期间步骤已修改，请重新生成网页对话内容")
                        code_control = self.controls()["code"]
                        code_control.value = source
                        try:
                            await self.save_editor()
                        except Exception:
                            if not getattr(code_control, "is_deleted", False):
                                code_control.value = saved["step_content"]
                            raise
                        if not self.identity() == identity:
                            return
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
                        await repaint()

                    with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                        self.button("采纳到编辑器", adopt, primary=True)
                        ui.button("返回修改粘贴内容", on_click=preview.close).props("outline")
                preview.open()
            with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                self.button("解析并预览", preview_reply, primary=True)
                ui.button("关闭", on_click=dialog.close).props("outline")
        dialog.open()


    @exclusive_ai_flow
    async def generate_goal_dialog(self):
        before_save = self.identity()
        saved = await self.save_editor()
        if self.identity() != before_save:
            return
        identity = self.identity()
        self.pending_identity = identity
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-2xl"):
            ui.label("AI 生成步骤描述").classes("text-lg font-medium")
            requirement = ui.textarea(
                "你想让这个步骤完成什么",
                placeholder="例如：登录后进入合约管理，新建比例再保险合同，并保存结果截图",
            ).props("autogrow").classes("w-full")
            with ui.row().classes("w-full gap-2 flex-wrap"):
                submit_ai_choice(dialog, [
                    ("使用 API", lambda: ("api", requirement.value or "")),
                    ("使用 Chat 网页", lambda: ("chat", requirement.value or "")),
                ])
                ui.button("取消", on_click=lambda: dialog.submit(None)).props("flat")
        choice = await dialog
        if not choice or self.identity() != identity:
            return
        mode, supplement = choice
        contexts = context_ai_items(await self.controller.call("context.ai", step_id=saved["step_id"]))
        if self.identity() != identity:
            return
        proposal = await self._request(
            "step.generate_goal", saved, step_id=saved["step_id"], expected_hash=saved["content_hash"],
            supplement=supplement,
            contexts=contexts,
            environment_id=self.environment_id() or None, export_only=mode == "chat",
        )
        if self.identity() != identity:
            return
        await self._present_goal_result(saved, proposal, identity, web_chat=mode == 'chat')

    async def _present_goal_result(self, saved, proposal, identity, *, web_chat=False):
        if self.identity() != identity:
            return
        if web_chat:
            with ui.dialog() as chat, ui.card().classes("w-full max-w-3xl"):
                ui.label("网页 AI 生成步骤描述").classes("text-lg")
                ui.textarea("复制到网页 AI", value=proposal["prompt"]).props("readonly autogrow").classes("w-full")
                render_preview_attachments(proposal)
                reply = ui.textarea("粘贴网页回复").props("autogrow").classes("w-full")

                async def adopt_chat_goal():
                    from taskweave.desktop.chat import parse_goal_reply
                    description, notes = parse_goal_reply(reply.value or "")
                    await self.preview_goal(saved, description, notes, chat, identity)

                with ui.row().classes("gap-2 flex-wrap"):
                    self.button("复制对话内容", lambda: self.controller.copy_text(proposal["prompt"]))
                    self.button("解析并预览", adopt_chat_goal, primary=True)
                    ui.button("关闭", on_click=chat.close).props("outline")
            chat.open()
            return
        await self.preview_goal(saved, proposal["step_description"], proposal["step_notes"], identity=identity)

    async def preview_goal(self, saved, description_text, notes_text="", parent=None, identity=None):
        identity = self.identity() if identity is None else identity
        if self.identity() != identity:
            return
        retained = self.retained_request()
        with ui.dialog() as preview, ui.card().classes("w-full max-w-2xl"):
            ui.label("步骤描述预览").classes("text-lg")
            ui.label("步骤描述").classes("font-medium")
            ui.label(description_text).classes("whitespace-pre-wrap border rounded p-3 w-full")
            ui.label("步骤补充说明").classes("font-medium")
            ui.label(notes_text or "无").classes("whitespace-pre-wrap border rounded p-3 w-full text-gray-600")

            async def accept():
                await self._validate_retained_request(retained, identity)
                latest = await self.controller.call("step.get", step_id=saved["step_id"])
                if self.identity() != identity or latest["content_hash"] != saved["content_hash"]:
                    raise TaskError("EDIT_CONFLICT")
                controls = self.controls()
                if not controls:
                    raise TaskError("EDIT_CONFLICT")
                controls["step_description"].value = description_text
                controls["step_notes"].value = notes_text
                await self.save_editor()
                preview.close()
                if parent:
                    parent.close()
                ui.notify("步骤描述已保存为待确认内容")

            with ui.row().classes("gap-2"):
                self.button("采纳步骤描述", accept, primary=True)
                ui.button("取消", on_click=preview.close).props("outline")
        preview.open()
