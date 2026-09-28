"""Step context group, capture editing, and batched persistence UI."""

import copy
import json
from nicegui import ui
from taskweave.core.validation import TaskError
from taskweave.desktop.contexts import (
    render_context_draft_rows, show_context_preview, ContextCards, ContextCaptureDraft, ContextTargetPicker, context_ai_items,
    context_advanced_overrides, context_hidden_parameters, context_target_options,
    context_view_default, merge_context_request,
)
from taskweave.desktop.display import execution_title
from taskweave.desktop.forms import ValueForm

STATUS = {"PAUSED":"已暂停", "FAILED":"失败", "SUCCEEDED":"成功"}


class StepContextPanel:
    def __init__(self, controller, state, step_id, remove_entry, move_entry, recollect, mark_pending,
                 *, save_editor=None, plugin_contributions=None, task_id=None,
                 environment_id=None, button=None, render_result_view=None):
        self.controller, self.state, self.step_id = controller, state, step_id
        self.remove_entry, self.move_entry = remove_entry, move_entry
        self.recollect, self.mark_pending = recollect, mark_pending
        self.save_editor, self.plugin_contributions = save_editor, plugin_contributions
        self.task_id, self.environment_id = task_id, environment_id
        self.button, self.render_result_view = button, render_result_view
        self.cards = None
        self.panel = None
        self._generation = 0
        self._dialogs = []

    def dispose(self):
        """Release UI handles; late collection results must not repaint a left editor."""
        self._generation += 1
        self.cards = None
        self.panel = None
        for dialog in self._dialogs:
            if not getattr(dialog, "is_deleted", False):
                dialog.close()
        self._dialogs.clear()

    def _active(self, generation):
        return generation == self._generation

    async def may_discard_draft(self, draft, name, notes, initial_name, initial_notes, confirm):
        dirty = draft.dirty or (name or "") != initial_name or (notes or "") != initial_notes
        return await confirm() if dirty else True

    def _collection_active(self, generation, task_id, step_id):
        current_task = self.task_id() if self.task_id is not None else None
        return (self._active(generation) and current_task == task_id
                and self.step_id() == step_id)

    async def save_batch(self, existing, provider, name, notes, draft, *, step_id=None,
                         generation=None, task_id=None):
        generation = self._generation if generation is None else generation
        task_id = (self.task_id() if self.task_id is not None else None) if task_id is None else task_id
        step_id = self.step_id() if step_id is None else step_id
        if not self._collection_active(generation, task_id, step_id):
            return None
        result = await self.controller.call(
            "context.save_batch", step_id=step_id,
            context_id=(existing or {}).get("context_id"),
            expected_revision=(existing or {}).get("revision"), provider_id=provider,
            name=name, context_notes=notes, captures=draft.payload(),
        )
        group = result["group"]
        if not self._collection_active(generation, task_id, step_id):
            return group
        current = next((item for item in self.state.entries if item["context_id"] == group["context_id"]), None)
        if current: current.update(group)
        else: self.state.entries.append(group)
        self.state.ai_contexts = context_ai_items(self.state.entries)
        if self.cards:
            self.cards.sync_group(group)
        return group

    async def move_group(self, entry, direction):
        generation, task_id, step_id = self._generation, self.task_id() if self.task_id is not None else None, self.step_id()
        updated = await self.controller.call("context.reorder", context_id=entry["context_id"], direction=direction, expected_revision=entry.get("revision"), step_id=self.step_id())
        if not self._collection_active(generation, task_id, step_id): return
        latest = {row["context_id"]:row for row in updated}
        for current in self.state.entries: current.update(latest.get(current["context_id"], {}))
        await self.mark_pending()

    async def delete_capture(self, group, capture):
        generation, task_id, step_id = self._generation, self.task_id() if self.task_id is not None else None, self.step_id()
        await self.controller.call("context.capture.delete", context_id=group["context_id"], capture_id=capture["capture_id"], expected_revision=group.get("revision"), step_id=self.step_id())
        if not self._collection_active(generation, task_id, step_id): return
        await self.reload()

    async def move_capture(self, group, capture, direction):
        generation, task_id, step_id = self._generation, self.task_id() if self.task_id is not None else None, self.step_id()
        await self.controller.call("context.capture.reorder", context_id=group["context_id"], capture_id=capture["capture_id"], direction=direction, expected_revision=group.get("revision"), step_id=self.step_id())
        if not self._collection_active(generation, task_id, step_id): return
        await self.reload()

    async def update_capture_label(self, group, capture, label, **metadata):
        generation, task_id, step_id = self._generation, self.task_id() if self.task_id is not None else None, self.step_id()
        await self.controller.call("context.capture.label", context_id=group["context_id"], capture_id=capture["capture_id"], label=label, expected_revision=group.get("revision"), step_id=self.step_id(), **metadata)
        if not self._collection_active(generation, task_id, step_id): return
        await self.reload()

    async def reload(self):
        generation, task_id, step_id = self._generation, self.task_id() if self.task_id is not None else None, self.step_id()
        entries = await self.controller.call("context.list", step_id=step_id)
        if not self._collection_active(generation, task_id, step_id):
            return
        self.state.entries = entries
        self.state.ai_contexts = context_ai_items(self.state.entries)
        if self.cards:
            self.render(self.panel)
        await self.mark_pending()

    async def remove_group(self, entry):
        generation, task_id, step_id = self._generation, self.task_id() if self.task_id is not None else None, self.step_id()
        await self.controller.call("context.delete", context_id=entry["context_id"], expected_revision=entry.get("revision"), step_id=self.step_id())
        if not self._collection_active(generation, task_id, step_id): return
        if entry in self.state.entries: self.state.entries.remove(entry)
        self.state.ai_contexts = context_ai_items(self.state.entries)
        await self.mark_pending()

    async def preview_capture(self, entry):
        generation, task_id, step_id = self._generation, self.task_id(), self.step_id()
        capture = await self.controller.call("context.capture.get", context_id=entry["context_id"], capture_id=entry["capture_id"], step_id=step_id)
        if not self._collection_active(generation, task_id, step_id): return
        await show_context_preview(entry.get("name", "上下文") + " · " + (entry.get("label") or "采集项"),
            capture, self.controller.result_renderers, self.render_result_view,
            redact_on_display=self.controller.privacy_settings()["redact_on_display"],
            is_active=lambda: self._collection_active(generation, task_id, step_id),
            register_dialog=self._dialogs.append)

    def render(self, panel):
        if panel is None or panel.is_deleted:
            return
        self.panel = panel
        generation = self._generation
        task_id = self.task_id() if self.task_id is not None else None
        panel.clear()
        step_id = self.step_id()

        async def save(entry, name, notes):
            updated = await self.controller.call(
                "context.group.update", step_id=step_id, context_id=entry["context_id"],
                name=name, context_notes=notes, expected_revision=entry.get("revision"),
            )
            if not self._collection_active(generation, task_id, step_id): return
            entry.update(updated)
            self.state.ai_contexts = context_ai_items(self.state.entries)
            await self.mark_pending()

        expanded = self.cards.expanded if self.cards else set()
        with panel:
            self.cards = ContextCards(
                self.state.entries, save, self.remove_group,
                move=self.move_group, recollect=self._recollect,
                append=lambda: self.collect(),
                preview_capture=lambda group, capture: self.preview_capture({**group, **capture}),
                delete_capture=self.delete_capture,
                move_capture=self.move_capture,
                update_capture=self.update_capture_label,
                redact_on_display=self.controller.privacy_settings()["redact_on_display"],
                is_active=lambda:self._active(generation), expanded=expanded,
            )

    def render_all(self):
        if self.panel is not None and not self.panel.is_deleted:
            self.render(self.panel)

    async def _recollect(self, entry):
        source = "draft" if entry.get("source_page") == "planning_import" else entry.get("source_page", "draft")
        await self.collect(source, entry)

    async def collect(self, source_page='draft', existing=None):
        generation = self._generation
        target_task_id, target_step_id = self.task_id(), self.step_id()
        def current():
            return self._collection_active(generation, target_task_id, target_step_id)
        if existing and existing.get('captures'):
            latest = existing['captures'][-1]
            capture = await self.controller.call('context.capture.get', context_id=existing['context_id'], capture_id=latest['capture_id'], step_id=target_step_id)
            if not current(): return
            existing = {**existing, **capture}
        saved = await self.save_editor()
        if not current() or saved.get('step_id') != target_step_id: return
        ids = sorted({identifier for contribution in self.plugin_contributions(saved['capabilities']) for identifier in contribution.context_provider_ids})
        if not ids: raise TaskError('CONTEXT_PROVIDER_UNAVAILABLE', '所选插件没有提供上下文')
        draft = ContextCaptureDraft((existing or {}).get('captures', []))
        initial_name = (existing or {}).get('name', '新上下文')
        initial_notes = (existing or {}).get('context_notes', '')
        with ui.dialog() as dialog, ui.card().classes('tw-context-collection-dialog w-full max-w-5xl'):
            self._dialogs.append(dialog)
            with ui.row().classes('w-full justify-between items-center'):
                ui.label('编辑与采集上下文 · 步骤').classes('text-lg font-medium')
                ui.button(icon='close',on_click=lambda:cancel()).props('flat round dense aria-label=关闭弹窗')
            ui.label('修改先暂存，确认保存时整组一次提交；取消不会写入。').classes('tw-context-dialog-note w-full')
            name = ui.input('上下文名称', value=initial_name).classes('w-full')
            notes = ui.textarea('操作说明（可选）', value=initial_notes).props('autogrow').classes('w-full')
            staged_title = ui.label().classes('font-medium')
            staged_area = ui.column().classes('w-full gap-2')
            deleted_area = ui.column().classes('w-full gap-1')
            initial_provider = existing.get('provider_id') if existing and existing.get('provider_id') in ids else ids[0]
            provider = ui.select(ids, label='插件上下文', value=initial_provider).classes('w-full')
            if existing and existing.get('context_id'): provider.disable()
            run_options = {'': '独立观察（不使用运行会话）'}
            runs = await self.controller.call('run.context.sessions', task_id=target_task_id)
            if not current():
                dialog.close()
                return
            run_options.update({r['run_id']: execution_title(r) + ' · ' + STATUS[r['status']] for r in runs if r['status'] in {'PAUSED','FAILED','SUCCEEDED'}})
            initial_run = (existing or {}).get('source_session_id', '')
            run = ui.select(run_options, label='观察会话（可选）', value=initial_run if initial_run in run_options else '').classes('w-full')
            target_area = ui.column().classes('w-full gap-1')
            target_state = {'picker': None}
            request_schemas = self.controller.plugin_context_requests()
            request_forms, request_groups = {}, {}
            for identifier in ids:
                schema = request_schemas.get(identifier, {'type':'object','properties':{}})
                if existing and identifier == initial_provider:
                    import copy
                    schema = copy.deepcopy(schema)
                    for key,value in existing.get('request',{}).items():
                        if key in schema.get('properties',{}): schema['properties'][key]['default'] = value
                with ui.column().classes('w-full') as group: request_forms[identifier] = ValueForm(schema)
                request_groups[identifier] = group

            def update_request_form(_=None):
                picker=target_state['picker']
                for identifier,group in request_groups.items():
                    group.set_visibility(identifier == provider.value)
                    request_forms[identifier].hide_fields(context_hidden_parameters(request_schemas.get(identifier,{}),identifier == provider.value and picker is not None and not picker.uses_parameters))

            async def load_targets():
                return await self.controller.call('context.targets', step_id=saved['step_id'], provider_id=provider.value, run_id=run.value or None)

            async def select_provider(_=None):
                if not current():
                    dialog.close()
                    return
                target_area.clear(); options=context_target_options(request_schemas.get(provider.value,{})); target_state['picker']=None
                if options:
                    with target_area: picker=ContextTargetPicker(load_targets,options)
                    target_state['picker']=picker; picker.select.on_value_change(update_request_form); await picker.refresh()
                    if not current():
                        dialog.close()
                        return
                    selected=(existing or {}).get('request',{}).get('target_id')
                    if selected and selected in picker.targets: picker.select.value=selected
                update_request_form()

            async def refresh_targets(_=None):
                if not current():
                    dialog.close()
                    return
                if target_state['picker']:
                    await target_state['picker'].refresh()
                    if not current():
                        dialog.close()
                        return
                    update_request_form()
            provider.on_value_change(select_provider); run.on_value_change(refresh_targets); await select_provider()
            view_default=context_view_default(request_schemas.get(provider.value,{})); view_state={'supported':view_default is not None}
            include_view=ui.checkbox('同时生成预览',value=(existing or {}).get('include_view',view_default is True)); include_view.set_visibility(view_state['supported'])
            def update_view_option(_=None):
                value=context_view_default(request_schemas.get(provider.value,{})); view_state['supported']=value is not None; include_view.set_visibility(view_state['supported'])
                if not existing: include_view.value=value is True
            provider.on_value_change(update_view_option)
            advanced_values=context_advanced_overrides(request_schemas.get(initial_provider,{}),(existing or {}).get('request',{}))
            with ui.expansion('高级参数 JSON（可选）',icon='tune').classes('w-full border rounded'):
                advanced=ui.textarea('JSON 对象',value=json.dumps(advanced_values,ensure_ascii=False,indent=2)).classes('w-full')

            async def preview_item(entry):
                if not current():
                    dialog.close()
                    return
                capture=entry['capture'] if entry.get('is_new') else await self.controller.call('context.capture.get',context_id=existing['context_id'],capture_id=entry['capture_id'],step_id=target_step_id)
                if not current():
                    dialog.close()
                    return
                await show_context_preview(entry.get('label') or '采集项', capture,
                    self.controller.result_renderers, self.render_result_view,
                    redact_on_display=self.controller.privacy_settings()['redact_on_display'],
                    is_active=current, register_dialog=self._dialogs.append)

            def render_staged():
                if not current(): return
                staged_area.clear(); deleted_area.clear()
                with staged_area:
                    render_context_draft_rows(draft, preview_item, render_staged)
                if draft.deleted:
                    with deleted_area:
                        ui.label('待删除（可撤销）').classes('text-xs text-gray-500')
                        for entry in draft.deleted:
                            with ui.row().classes('items-center gap-2'):
                                ui.label(entry.get('label') or '采集项')
                                ui.button('撤销删除',on_click=lambda item=entry:(draft.undo_delete(item),render_staged())).props('flat dense')
            render_staged()

            async def collect():
                if not current():
                    dialog.close()
                    return
                try:
                    picker=target_state['picker']; hidden=context_hidden_parameters(request_schemas.get(provider.value,{}),picker is not None and not picker.uses_parameters)
                    form_values=request_forms[provider.value].values(exclude=hidden)
                    overrides=json.loads(advanced.value or '{}')
                    target_request,session_id=picker.selection() if picker else ({},None)
                    request=merge_context_request(form_values,overrides,target_request)
                    capture=await self.controller.call('context.read',step_id=target_step_id,provider_id=provider.value,request=request,environment_id=self.environment_id() or None,run_id=run.value or None,expected_session_id=session_id,include_view=bool(include_view.value) if view_state['supported'] else False)
                    if not current():
                        dialog.close()
                        return
                    label=(capture.get('items') or [{}])[0].get('source') or f'采集 {len(draft.entries)+1}'
                    draft.append(capture,request,bool(include_view.value) if view_state['supported'] else False,run.value or None,source_page,label)
                    render_staged(); ui.notify(f'已暂存采集项：{label}，可继续采集',type='positive')
                except Exception as exc: ui.notify(f'采集失败，暂存内容仍保留：{exc}',type='negative')

            async def cancel():
                if not current():
                    dialog.close()
                    return
                async def confirm_discard():
                    with ui.dialog() as confirm, ui.card():
                        self._dialogs.append(confirm)
                        ui.label('关闭将丢弃本次未保存的编辑和采集项。')
                        with ui.row():
                            ui.button('继续编辑',on_click=lambda:confirm.submit(False)).props('outline')
                            ui.button('丢弃并关闭',on_click=lambda:confirm.submit(True)).props('text-color=red-7')
                    answer = await confirm
                    if confirm in self._dialogs: self._dialogs.remove(confirm)
                    return answer
                if not await self.may_discard_draft(draft, name.value, notes.value, initial_name, initial_notes, confirm_discard):
                    return
                if not current():
                    dialog.close()
                    return
                dialog.close()
                if dialog in self._dialogs: self._dialogs.remove(dialog)

            save_in_progress = False

            async def save_batch():
                nonlocal save_in_progress
                if save_in_progress:
                    return
                if not current():
                    dialog.close()
                    return
                if existing and not draft.dirty and (name.value or '') == initial_name and (notes.value or '') == initial_notes:
                    dialog.close()
                    return
                save_in_progress = True
                try:
                    await self.save_batch(existing,provider.value,(name.value or '').strip(),notes.value or '',draft,
                                          step_id=target_step_id,generation=generation,task_id=target_task_id)
                except Exception as exc:
                    ui.notify(f'保存失败，暂存内容仍保留：{exc}',type='negative'); return
                else:
                    dialog.close(); ui.notify('上下文已保存',type='positive')
                    if dialog in self._dialogs: self._dialogs.remove(dialog)
                finally:
                    save_in_progress = False

            self.button('采集一项',collect,primary=True)
            ui.label('采集结果仅暂存在弹窗；确认保存后才会进入 AI 输入。浏览器等外部操作不会因取消自动回滚。').classes('text-xs text-gray-500')
            with ui.row().classes('w-full justify-end gap-2'):
                ui.button('取消',on_click=cancel).props('outline')
                ui.button('确认保存',on_click=save_batch).props('unelevated color=primary')
        dialog.props('persistent'); dialog.open()
