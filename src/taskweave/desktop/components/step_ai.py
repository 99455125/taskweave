"""AI-generated step description flow and guarded candidate preview."""

import asyncio
import json

from nicegui import ui
from taskweave.core.validation import TaskError
from taskweave.desktop.components.chat_export import render_chat_export
from taskweave.presentation.authoring import AIInteraction, AIChoiceDraft, AuthoringFlow, Notice


def exclusive_ai_flow(method):
    """One modal/request flow per editor, acquired before the first await."""
    from functools import wraps
    @wraps(method)
    async def run(self, *args, **kwargs):
        lookup = getattr(self, 'retained_request', None)
        retained = lookup() if lookup else None
        reason = self.interaction.begin(
            retained_pending=bool(retained and not retained['task'].done()),
            recovering=method.__name__ == 'recover_generation')
        if reason:
            ui.notify('AI 操作正在处理中，请勿重复发起。' if reason == 'flow_active'
                      else '当前步骤的 AI 请求仍在处理中，请查看上次 AI 结果。', type='info')
            return
        try:
            # Trial refreshes can clear their slot while an awaited dialog is open.
            with ui.context.client.layout:
                return await method(self, *args, **kwargs)
        finally:
            self.interaction.finish()
    return run


def submit_ai_choice(dialog, values):
    """Lock both channels immediately after the first accepted selection."""
    selection = AIChoiceDraft((None, None, 0, 0))
    buttons = []
    def submit(factory):
        if selection.submit('select', selection.identity) is None:
            return
        for button in buttons:
            button.disable()
        dialog.submit(factory())
    for title, factory in values:
        buttons.append(ui.button(title, on_click=lambda _e=None, f=factory: submit(f)).props("outline"))
    return buttons


def render_code_comparison(current, candidate, diff):
    with ui.tabs(value='compare').classes('w-full tw-ai-review-tabs') as tabs:
        ui.tab('compare', label='代码对比')
        ui.tab('diff', label='变更差异')
    with ui.tab_panels(tabs, value='compare').classes('w-full tw-ai-review-panels'):
        with ui.tab_panel('compare'), ui.element('div').classes('tw-ai-code-comparison w-full'):
            with ui.column().classes('w-full min-w-0 gap-2'):
                ui.label('当前步骤代码').classes('font-medium')
                ui.code(current, language='python').classes('w-full')
            with ui.column().classes('w-full min-w-0 gap-2'):
                ui.label('AI 候选代码').classes('font-medium text-primary')
                ui.code(candidate, language='python').classes('w-full')
        with ui.tab_panel('diff'):
            ui.code(diff, language='diff').classes('w-full')


class InlineChatSurface:
    """Keep export/reply controls alive while the same workspace reviews a candidate."""
    def __init__(self, host):
        self.host = host
        host['chat'].clear()

    def __enter__(self):
        self.host['chat'].__enter__()
        return self

    def __exit__(self, *args):
        return self.host['chat'].__exit__(*args)

    def open(self):
        self.host['show_chat']()

    def close(self):
        self.host['close']()


class StepAIEditor:
    def __init__(self, controller, button, save_editor, environment_id, controls, identity,
                 *, debug_state=None, trials=None, reset_conversation=None, confirmation_step=None,
                 author_step=None, authoring_request=None, draft_values=None,
                 review_host=None, start_debug=None):
        self.controller, self.button, self.save_editor = controller, button, save_editor
        self.environment_id, self.controls = environment_id, controls
        self.identity = identity
        self.debug_state, self.trials = debug_state, trials if trials is not None else {}
        self.reset_conversation = reset_conversation
        self.confirmation_step = confirmation_step or save_editor
        self.interaction = AIInteraction()
        self.author_step, self.authoring_request = author_step, authoring_request
        self.draft_values = draft_values
        self.review_host, self.start_debug = review_host, start_debug
        self._adopting = False
        self.repair_forms = {}

    async def _adopt_content(self, validate, identity, close, repaint, *, debug=False, on_saved=None):
        """Save one validated candidate before starting the existing debug action."""
        if self._adopting:
            return
        self._adopting = True
        try:
            source = await validate()
            controls = self.controls()
            if self.identity() != identity or not controls:
                raise TaskError('EDIT_CONFLICT', '当前步骤已变化，请重新查看 AI 结果。')
            control = controls['code']
            previous = control.value
            control.value = source
            try:
                saved = await self.save_editor()
            except Exception:
                if (self.identity() == identity and not getattr(control, 'is_deleted', False)
                        and control.value == source):
                    control.value = previous
                raise
            if self.identity() != identity:
                return
            if on_saved:
                on_saved()
            close()
            if self._current_code() != source:
                ui.notify('候选代码已保存；当前草稿又有修改，已保留草稿，未开始调试。', type='warning')
                return
            if debug:
                if self.start_debug is None or not isinstance(saved, dict) or saved.get('step_id') != identity[1]:
                    raise TaskError('ADOPTED_DEBUG_START_FAILED', '代码已采纳并保存，调试启动失败：当前调试入口不可用。')
                try:
                    await self.start_debug(saved, identity)
                except Exception as exc:
                    raise TaskError('ADOPTED_DEBUG_START_FAILED', f'代码已采纳并保存，调试启动失败：{exc}') from exc
            else:
                await repaint()
            return saved
        finally:
            self._adopting = False

    @property
    def pending_identity(self): return self.interaction.pending_identity
    @pending_identity.setter
    def pending_identity(self, value): self.interaction.pending_identity = value

    def _flow(self):
        return AuthoringFlow(
            call=getattr(self.controller, 'call', None), request=self._request,
            identity=self.identity, trials=self.trials,
            trial_feedback=getattr(self.controller, 'trial_feedback', None),
            repair_contexts=getattr(self.controller, 'repair_contexts', None),
            confirm=getattr(self.controller, 'confirm', None),
            validate_step=getattr(self.controller, 'validate_step_candidate', None),
        )

    def _current_code(self):
        if self.draft_values is not None:
            draft = self.draft_values()
            return draft.get('fields', {}).get('code') if draft else None
        controls = self.controls()
        return controls['code'].value if controls else None

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
            ui.notify('当前步骤暂无 AI 结果', type='info')
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
            await self._present_generation_result((saved, proposal, identity), bool(params.get('feedback') or params.get('use_history') or params.get('repair_notes')), repaint,
                                                  web_chat=params.get('export_only', False))

    async def _validate_retained_request(self, request, identity):
        from taskweave.presentation.requests import validate_candidate
        return await validate_candidate(
            self.controller.call, request,
            lambda: self.identity() == identity and self.retained_request() is request,
            self._current_code, self.trials)

    @exclusive_ai_flow
    async def generate_from_form(self, channel, supplement, *, repaint):
        """Use the inline assistant while retaining request and adoption guards."""
        if channel not in {'api', 'chat'}:
            raise ValueError('Unknown AI channel')
        web_chat = channel == 'chat'
        result = await self.generate_content(web_chat=web_chat, supplement=supplement or '')
        await self._present_generation_result(result, False, repaint, web_chat=web_chat)

    @exclusive_ai_flow
    async def choose_generation_mode(self, *, repaint):
        identity = self.identity()
        draft = self.interaction.choice(identity)
        def choose(channel):
            choice = draft.submit(channel, self.identity())
            return choice[0] if choice else None
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-md"):
            ui.label("AI 生成步骤代码").classes("text-lg font-medium")
            with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                submit_ai_choice(dialog, [("使用 API", lambda: choose("api")), ("使用 Chat 网页", lambda: choose("chat"))])
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
        active_run_id = self.trials.get(step_id)
        feedback = await self._flow().repair_evidence(identity, step_id, active_run_id)
        if feedback is None:
            return
        has_feedback = bool(feedback)
        feedback_run_id = active_run_id
        if has_feedback:
            self.debug_state.feedback = feedback
            self.debug_state.feedback_run_id = feedback_run_id
        draft = self.interaction.choice(identity, supplement=self.debug_state.supplements.get(step_id, ''))
        with ui.dialog() as dialog, ui.card().classes("tw-repair-mode-dialog w-full max-w-4xl"):
            with ui.row().classes("tw-repair-dialog-header w-full items-center justify-between"):
                ui.label("AI · 修复步骤").classes("text-lg font-semibold")
                ui.button("关闭", on_click=lambda: dialog.submit(None), icon="close").props("flat dense")
            if has_feedback:
                with ui.column().classes("tw-repair-evidence w-full gap-2"):
                    ui.label("本次修复依据").classes("font-medium")
                    ui.input("运行编号", value=feedback_run_id).props("readonly").classes("w-full").tooltip(feedback_run_id)
                    ui.input("尝试编号", value=feedback["attempt_id"]).props("readonly").classes("w-full").tooltip(feedback["attempt_id"])
            rounds = ui.select(
                {-1:"全部历史",0:"不带历史",**{i:f"最近 {i} 轮" for i in range(1,11)}},
                value=-1,label="本轮携带的历史会话",
            ).classes("w-full")
            deduplicate = ui.checkbox("精简重复静态字段",value=True)
            supplement = ui.textarea(
                "本轮补充说明", value=draft.supplement,
                placeholder="补充本轮修复需要关注的细节（可选）",
            ).props("outlined autogrow").classes("tw-repair-supplement w-full")
            rounds.on_value_change(lambda event: setattr(draft, 'history_rounds', event.value))
            deduplicate.on_value_change(lambda event: setattr(draft, 'deduplicate', event.value))
            supplement.on_value_change(lambda event: setattr(draft, 'supplement', event.value or ''))
            with ui.row().classes("tw-repair-dialog-actions w-full items-center gap-2 flex-wrap"):
                submit_ai_choice(dialog, [
                    ("大模型api调用", lambda: draft.submit('api', self.identity())),
                    ("大模型网页chat调用", lambda: draft.submit('chat', self.identity())),
                ])
                ui.button("取消", on_click=lambda:dialog.submit(None)).props("outline")
        choice = await dialog
        if not choice or self.identity() != identity: return
        await self._submit_repair(choice, identity, feedback_run_id, feedback, repaint, supplement_control)

    @exclusive_ai_flow
    async def repair_from_form(self, channel, history_rounds, deduplicate, supplement,
                               *, expected_evidence, repaint):
        if channel not in {'api', 'chat'} or history_rounds not in range(-1, 11):
            raise TaskError('FORM_INVALID', '请选择有效的生成方式和历史范围。')
        if self.debug_state is None:
            return
        identity = self.identity()
        step_id = identity[1]
        run_id = self.trials.get(step_id)
        feedback = await self._flow().repair_evidence(identity, step_id, run_id)
        if feedback is None:
            return
        if expected_evidence != (run_id, feedback.get('attempt_id')):
            ui.notify('调试记录已变化，请核对当前失败依据后再生成修复建议。', type='warning')
            return
        self.debug_state.feedback = feedback
        self.debug_state.feedback_run_id = run_id
        await self._submit_repair((channel, history_rounds, deduplicate, supplement),
                                  identity, run_id, feedback, repaint)

    async def _submit_repair(self, choice, identity, feedback_run_id, feedback, repaint, supplement_control=None):
        step_id = identity[1]
        if feedback:
            evidence_status = await self._flow().recheck_repair(identity, step_id, feedback_run_id, feedback)
            if evidence_status == 'stale':
                return
            if evidence_status == 'changed':
                ui.notify("调试记录已变化，请重新打开 AI 修复并核对最新尝试。", type="warning")
                return
        mode, history_rounds, dedup, text = choice
        self.debug_state.supplements[step_id] = text
        if supplement_control is not None: supplement_control.value = text
        result = await self.generate_content(
            fix_logs=True, web_chat=mode == "chat", supplement=text,
            run_id=self.trials.get(step_id), history_rounds=history_rounds,
            deduplicate_history=dedup, feedback_override=feedback,
            feedback_run_id=feedback_run_id,
            removed_feedback=set(self.debug_state.removed_feedback),
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
        decision = await self._flow().confirm_saved(saved, identity)
        if decision.status == 'stale':
            return
        if decision.status == 'manual':
            with ui.dialog() as dialog, ui.card().classes("w-full max-w-xl"):
                ui.label("当前已保存的步骤尚未调试通过，是否手动确认验证通过？")
                with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                    ui.button("取消",on_click=lambda:dialog.submit(False)).props("outline")
                    ui.button("确认验证通过",on_click=lambda:dialog.submit(True)).props("outline text-color=teal-8").style("background: #f0fdfa; border: 1px solid #0f766e")
            decision = await self._flow().confirm_manual(
                decision, approved=bool(await dialog), environment_id=self.environment_id())
        if decision.status != 'confirmed':
            return
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
        self.interaction.clear_repair(self.debug_state, step_id)
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
        messages = {
            'repair_changed': '当前调试尝试已变化，请重新打开 AI 修复并核对最新证据。',
            'context_unavailable': '当前页面上下文无法刷新，将明确告知 AI；未打开新浏览器。',
            'preparing_chat': '正在准备网页对话内容。',
            'generating': '正在生成建议，界面保持响应；当前草稿已保存。',
        }
        async for event in self._flow().generate_events(
            saved, identity, environment_id=self.environment_id(), fix_logs=fix_logs,
            web_chat=web_chat, supplement=supplement, run_id=run_id,
            history_rounds=history_rounds, deduplicate_history=deduplicate_history,
            feedback_override=feedback_override, feedback_run_id=feedback_run_id,
            removed_feedback=removed_feedback,
        ):
            if isinstance(event, Notice):
                ui.notify(messages[event.code], type=event.kind)
            else:
                return event.candidate
        return None

    def _candidate_host(self):
        host = self.review_host() if self.review_host else None
        return host if host and host['current']() else None

    def _render_inline_candidate(self, host, saved, source, explanation, diagnostics, accept, *, back=None):
        host['main'].clear()
        host['side'].clear()
        with host['main']:
            ui.label('AI 候选审阅').classes('text-base font-semibold')
            render_code_comparison(saved['step_content'], source,
                                   self.controller.diff(saved['step_content'], source))
        with host['side']:
            ui.label('候选代码').classes('text-base font-semibold')
            ui.label(explanation or 'AI 未提供解释。').classes('whitespace-pre-wrap text-sm')
            ui.label('基于版本 ' + saved['content_hash'][:8]).classes('text-xs text-gray-500')
            if diagnostics:
                with ui.expansion('诊断').classes('w-full'):
                    ui.label(json.dumps(diagnostics, ensure_ascii=False, indent=2, default=str)).classes('text-xs whitespace-pre-wrap')
            self.button('仅采纳', lambda: accept(False))
            if self.start_debug:
                self.button('采纳并调试', lambda: accept(True), primary=True)
            ui.button('舍弃', on_click=host['close']).props('flat')
            if back:
                ui.button('返回修改粘贴内容', on_click=back).props('flat')
        host['show']()

    async def present_content_candidate(self, saved, proposal, identity, repaint):
        if self.identity() != identity:
            return
        controls = self.controls()
        if not controls:
            return
        retained = self.retained_request()
        async def validate():
            await self._validate_retained_request(retained, identity)
            return self._flow().content_candidate(saved, proposal, identity, self._current_code())

        if self.review_host:
            host = self._candidate_host()
            if host:
                async def accept_inline(debug=False):
                    await self._adopt_content(validate, identity, host['close'], repaint, debug=debug)
                self._render_inline_candidate(host, saved, proposal['proposed_content'],
                                              proposal['explanation'], proposal['diagnostics'], accept_inline)
            return
        with ui.dialog() as dialog, ui.card().classes("tw-ai-candidate w-full"):
            ui.label("AI 候选审阅").classes("text-lg font-semibold")
            ui.label(proposal["explanation"])
            render_code_comparison(saved['step_content'], proposal['proposed_content'],
                                   self.controller.diff(saved['step_content'], proposal['proposed_content']))
            if proposal["diagnostics"]:
                ui.label(json.dumps(proposal["diagnostics"], ensure_ascii=False, indent=2, default=str))

            async def accept():
                await self._adopt_content(validate, identity, dialog.close, repaint)

            with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                self.button("采纳到编辑器", accept, primary=True)
                ui.button("舍弃", on_click=dialog.close).props("outline")
        dialog.open()

    async def web_chat_dialog(self, saved, exported, use_history, identity=None, *, repaint):
        import json
        import logging
        identity = self.identity() if identity is None else identity
        if not self.identity() == identity:
            return
        retained = self.retained_request()
        host = self._candidate_host() if self.review_host else None
        if self.review_host and not host:
            return
        surface = InlineChatSurface(host) if host and 'chat' in host else ui.dialog()
        with surface as dialog, ui.card().classes('tw-web-chat w-full max-w-4xl').props('flat' if host else ''):
            ui.label("网页 AI 对话").classes("text-lg")
            ui.textarea("复制到网页 AI 的内容", value=exported["prompt"]).props("readonly rows=6" if host else "readonly rows=12").classes("w-full")
            async def copy_prompt():
                await self.controller.copy_text(exported["prompt"])
                ui.notify("对话内容已复制")
            self.button("复制对话内容", copy_prompt)
            render_chat_export(exported, self.controller, filename="taskweave-step-chat.zip")
            draft = self.interaction.choice(identity)
            reply = ui.textarea("粘贴网页 AI 回复", value=draft.reply).classes("w-full").props("autogrow")
            reply.on_value_change(lambda event: setattr(draft, 'reply', event.value or ''))
            async def preview_reply():
                await self._validate_retained_request(retained, identity)
                source, explanation = draft.parse_content()
                current = await self.controller.call("step.get", step_id=saved["step_id"])
                if not self.controls():
                    raise TaskError('EDIT_CONFLICT', '当前编辑器已关闭')
                self._flow().validate_version(saved, current, identity,
                                              current_code=self._current_code(), expected_hash=exported['expected_hash'])
                diagnostics = await self._flow().validate_web_candidate(saved, source, identity)
                if diagnostics is None:
                    return
                async def validate_adoption():
                    await self._validate_retained_request(retained, identity)
                    latest = await self.controller.call("step.get", step_id=saved["step_id"])
                    if not self.controls():
                        raise TaskError('EDIT_CONFLICT', '当前编辑器已关闭')
                    self._flow().validate_version(saved, latest, identity,
                                                  current_code=self._current_code(), expected_hash=exported['expected_hash'])
                    return source

                def record_adoption():
                    if use_history:
                        self.controller.append_debug_conversation(saved["step_id"], [
                            exported["messages"][-1],
                            {"role": "assistant", "content": json.dumps({"step_content": source, "explanation": explanation}, ensure_ascii=False)},
                        ])
                    from taskweave.infrastructure.privacy import redact
                    logging.getLogger(__name__).info("网页 AI 回复已采纳：%s", redact({"step_content": source, "explanation": explanation}))

                if self.review_host:
                    host = self._candidate_host()
                    if not host:
                        return
                    dialog.close()
                    def close_inline():
                        host['close']()
                        dialog.close()
                    def back_to_reply():
                        host['close']()
                        dialog.open()
                    async def adopt_inline(debug=False):
                        await self._adopt_content(validate_adoption, identity, close_inline, repaint,
                                                  debug=debug, on_saved=record_adoption)
                    self._render_inline_candidate(host, saved, source, explanation, diagnostics,
                                                  adopt_inline, back=back_to_reply)
                    return
                with ui.dialog() as preview, ui.card().classes("tw-ai-candidate w-full"):
                    ui.label("网页 AI 回复预览").classes("text-lg font-semibold")
                    ui.label("解释").classes("font-medium")
                    ui.label(explanation or "AI 未提供解释。").classes("whitespace-pre-wrap")
                    render_code_comparison(saved['step_content'], source,
                                           self.controller.diff(saved['step_content'], source))
                    warnings = [item.get("message", "") for item in diagnostics if item.get("severity") != "error"]
                    if warnings:
                        ui.label("校验提示：" + "；".join(warnings)).classes("text-amber-700")

                    async def adopt():
                        def close_preview():
                            preview.close()
                            dialog.close()
                        await self._adopt_content(validate_adoption, identity, close_preview, repaint,
                                                  on_saved=record_adoption)

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
        draft = self.interaction.choice(identity)
        def choose(channel):
            choice = draft.submit(channel, self.identity())
            return (choice[0], choice[3]) if choice else None
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-2xl"):
            ui.label("AI 生成步骤描述").classes("text-lg font-medium")
            requirement = ui.textarea(
                "你想让这个步骤完成什么",
                placeholder="例如：登录后打开记录列表，新建一条记录，并保存结果截图",
            ).props("autogrow").classes("w-full")
            requirement.on_value_change(lambda event: setattr(draft, 'supplement', event.value or ''))
            with ui.row().classes("w-full gap-2 flex-wrap"):
                submit_ai_choice(dialog, [
                    ("使用 API", lambda: choose('api')),
                    ("使用 Chat 网页", lambda: choose('chat')),
                ])
                ui.button("取消", on_click=lambda: dialog.submit(None)).props("flat")
        choice = await dialog
        if not choice or self.identity() != identity:
            return
        mode, supplement = choice
        proposal = await self._flow().generate_goal(
            saved, identity, supplement=supplement,
            environment_id=self.environment_id(), web_chat=mode == 'chat')
        if proposal is None:
            return
        await self._present_goal_result(saved, proposal, identity, web_chat=mode == 'chat')

    async def _present_goal_result(self, saved, proposal, identity, *, web_chat=False):
        if self.identity() != identity:
            return
        if web_chat:
            with ui.dialog() as chat, ui.card().classes("w-full max-w-3xl"):
                ui.label("网页 AI 生成步骤描述").classes("text-lg")
                ui.textarea("复制到网页 AI", value=proposal["prompt"]).props("readonly rows=8").classes("w-full")
                render_chat_export(proposal, self.controller, filename="taskweave-description-chat.zip")
                draft = self.interaction.choice(identity)
                reply = ui.textarea("粘贴网页回复", value=draft.reply).props("autogrow").classes("w-full")
                reply.on_value_change(lambda event: setattr(draft, 'reply', event.value or ''))

                async def adopt_chat_goal():
                    description, notes = draft.parse_goal()
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
            ui.label("步骤说明").classes("font-medium")
            ui.label(notes_text or "无").classes("whitespace-pre-wrap border rounded p-3 w-full text-gray-600")

            async def accept():
                await self._validate_retained_request(retained, identity)
                latest = await self.controller.call("step.get", step_id=saved["step_id"])
                controls = self.controls()
                values = self._flow().goal_candidate(
                    latest, saved, identity, has_draft=bool(controls),
                    description=description_text, notes=notes_text)
                for name, value in values.items():
                    controls[name].value = value
                await self.save_editor()
                preview.close()
                if parent:
                    parent.close()
                ui.notify("步骤描述已保存为待确认内容")

            with ui.row().classes("gap-2"):
                self.button("采纳步骤描述", accept, primary=True)
                ui.button("取消", on_click=preview.close).props("outline")
        preview.open()
