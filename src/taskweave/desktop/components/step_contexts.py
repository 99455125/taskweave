"""Step context group, capture editing, and batched persistence UI."""

import copy
import json
from nicegui import ui
from taskweave.core.validation import TaskError
from taskweave.desktop.contexts import (
    render_context_draft_rows, show_context_preview, ContextCards, ContextCaptureDraft, ContextTargetPicker, context_ai_items,
    context_advanced_overrides, context_hidden_parameters, context_target_options,
    context_view_default,
)
from taskweave.desktop.display import execution_title
from taskweave.desktop.forms import ValueForm
from taskweave.presentation.collection_form import CollectionForm
from taskweave.desktop.context_recording import collection_workspace, RecordingControls

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

    @property
    def interaction(self):
        from taskweave.presentation.step_contexts import StepContexts
        return StepContexts(self.controller.call, self.state,
                            lambda: (self._generation, self.task_id() if self.task_id else None, self.step_id()))

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
        group, current = await self.interaction.save_batch(step_id, existing, provider, name, notes, draft.payload())
        if current and self.cards:
            self.cards.sync_group(group)
        return group

    async def move_group(self, entry, direction):
        if await self.interaction.reorder(self.step_id(), entry, direction):
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
        if not await self.interaction.reload(self.step_id()):
            return
        if self.cards:
            self.render(self.panel)
        await self.mark_pending()

    async def remove_group(self, entry):
        if await self.interaction.remove(self.step_id(), entry):
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
        request_schemas = self.controller.plugin_context_requests()
        available_providers = set(ids)
        workspace=collection_workspace(self.controller,('step',target_step_id,(existing or {}).get('context_id')),(existing or {}).get('captures', []))
        form_state = CollectionForm(workspace.fields, request_schemas, available=available_providers)
        # Continuing an existing recording retains its captured authority. A
        # changed step must still allow stop/discard without granting a new
        # recording or snapshot access to a removed provider.
        retained_provider = (workspace.recording.options.get('provider_id')
                             if workspace.recording and workspace.recording.pending else None)
        provider_removed = form_state.provider_removed(retained_provider)
        if provider_removed:
            ids = form_state.provider_choices(retained_provider)
        if not ids: raise TaskError('CONTEXT_PROVIDER_UNAVAILABLE', '所选插件没有提供上下文')
        if not await workspace.prepare_dialog(ui.context.client):
            return
        draft = workspace.draft
        async def invoke_recording(operation, **options):
            return await self.controller.call('context.record',step_id=target_step_id,operation=operation,**options)
        workspace.bind(invoke_recording,source_page=source_page)
        initial_name = (existing or {}).get('name', '新上下文')
        initial_notes = (existing or {}).get('context_notes', '')
        def bind_field(field, control):
            form_state.change(field, control.value)
            control.on_value_change(lambda event: form_state.change(field, event.value))

        def bind_form(identifier, form, schema):
            raw = form_state.configure(identifier, schema)
            for key, (_, control) in form.controls.items():
                control.value = raw[key]
                control.on_value_change(lambda event, name=key: form_state.change_input(identifier, name, event.value))

        with ui.dialog() as dialog, ui.card().classes('tw-context-collection-dialog w-full max-w-5xl'):
            self._dialogs.append(dialog)
            with ui.row().classes('w-full justify-between items-center'):
                ui.label('编辑与采集上下文 · 步骤').classes('text-lg font-medium')
                ui.button(icon='close',on_click=lambda:cancel()).props('flat round dense aria-label=关闭弹窗')
            ui.label('修改先暂存，确认保存时整组一次提交；取消不会写入。').classes('tw-context-dialog-note w-full')
            if provider_removed:
                ui.label('步骤的插件能力已变化，原录制仍保留。可停止或丢弃；保存素材需恢复原插件能力。').classes('text-sm text-amber-700')
            name = ui.input('上下文名称', value=workspace.fields.get('name',initial_name)).classes('w-full')
            bind_field('name', name)
            notes = ui.textarea('操作说明（可选）', value=workspace.fields.get('notes',initial_notes)).props('autogrow').classes('w-full')
            bind_field('notes', notes)
            staged_title = ui.label().classes('font-medium')
            staged_area = ui.column().classes('w-full gap-2')
            deleted_area = ui.column().classes('w-full gap-1')
            initial_provider = existing.get('provider_id') if existing and existing.get('provider_id') in ids else ids[0]
            provider = ui.select(ids, label='插件上下文', value=retained_provider or workspace.fields.get('provider',initial_provider)).classes('w-full')
            bind_field('provider', provider)
            if existing and existing.get('context_id'): provider.disable()
            run_options = {'': '独立观察（不使用运行会话）'}
            runs = await self.controller.call('run.context.sessions', task_id=target_task_id)
            if not current():
                dialog.close()
                return
            eligible_runs, initial_run, missing_retained = form_state.run_choices(
                runs, (workspace.recording.options.get('run_id') or '') if retained_provider else None,
                initial=(existing or {}).get('source_session_id', ''))
            run_options.update({r['run_id']: execution_title(r) + ' · ' + STATUS[r['status']] for r in eligible_runs})
            if missing_retained:
                run_options[initial_run] = '原录制会话 · ' + initial_run[:8]
            run = ui.select(run_options, label='观察会话（可选）', value=initial_run).classes('w-full')
            bind_field('run', run)
            target_area = ui.column().classes('w-full gap-1')
            target_state = {'picker': None}
            request_forms, request_groups = {}, {}
            for identifier in ids:
                schema = request_schemas.get(identifier, {'type':'object','properties':{}})
                if existing and identifier == initial_provider:
                    schema = copy.deepcopy(schema)
                    for key, value in existing.get('request', {}).items():
                        if key in schema.get('properties', {}):
                            schema['properties'][key]['default'] = value
                with ui.column().classes('w-full') as group:
                    request_forms[identifier] = ValueForm(schema)
                request_groups[identifier] = group
                bind_form(identifier, request_forms[identifier], schema)

            def update_request_form(_=None):
                picker=target_state['picker']
                for identifier,group in request_groups.items():
                    group.set_visibility(identifier == workspace.fields['provider'])
                    request_forms[identifier].hide_fields(context_hidden_parameters(request_schemas.get(identifier,{}),identifier == workspace.fields['provider'] and picker is not None and not picker.uses_parameters))

            async def load_targets():
                return await self.controller.call('context.targets', step_id=saved['step_id'], provider_id=workspace.fields['provider'], run_id=workspace.fields['run'] or None)

            async def select_provider(_=None):
                selected=workspace.fields.get('target',(existing or {}).get('request',{}).get('target_id'))
                if not current():
                    dialog.close()
                    return
                target_area.clear(); options=context_target_options(request_schemas.get(workspace.fields['provider'],{})); target_state['picker']=None; form_state.target=None
                if options and not workspace.recording.pending and workspace.fields['provider'] in available_providers:
                    with target_area: picker=ContextTargetPicker(load_targets,options)
                    target_state['picker']=picker; form_state.target=picker.interaction
                    picker.select.on_value_change(lambda event: form_state.change('target', event.value))
                    picker.select.on_value_change(update_request_form); await picker.refresh()
                    if not current():
                        dialog.close()
                        return
                    if selected and selected in picker.targets: picker.select.value=selected
                update_request_form()

            async def refresh_targets(_=None):
                if not current():
                    dialog.close()
                    return
                if target_state['picker'] and not workspace.recording.pending:
                    await target_state['picker'].refresh()
                    if not current():
                        dialog.close()
                        return
                    update_request_form()
            provider.on_value_change(select_provider); run.on_value_change(refresh_targets); await select_provider()
            view_default=context_view_default(request_schemas.get(workspace.fields['provider'],{})); view_state={'supported':view_default is not None}
            include_view=ui.checkbox('同时生成预览',value=workspace.fields.get('include_view',(existing or {}).get('include_view',view_default is True))); include_view.set_visibility(view_state['supported'])
            bind_field('include_view', include_view)
            def update_view_option(_=None):
                value=context_view_default(request_schemas.get(workspace.fields['provider'],{})); view_state['supported']=value is not None; include_view.set_visibility(view_state['supported'])
                if not existing: include_view.value=value is True
            provider.on_value_change(update_view_option)
            advanced_values=context_advanced_overrides(request_schemas.get(initial_provider,{}),(existing or {}).get('request',{}))
            with ui.expansion('高级参数 JSON（可选）',icon='tune').classes('w-full border rounded'):
                advanced=ui.textarea('JSON 对象',value=workspace.fields.get('advanced',json.dumps(advanced_values,ensure_ascii=False,indent=2))).classes('w-full')

            bind_field('advanced', advanced)

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
                if workspace.busy or workspace.recording.committed: return
                if not current():
                    dialog.close()
                    return
                workspace.busy=True
                recording_controls.sync()
                try:
                    options, selected_view = form_state.start_options(environment_id=self.environment_id(), step=True)
                    capture = await self.controller.call('context.read', step_id=target_step_id,
                        **{**options, 'environment_id': self.environment_id() or None}, include_view=selected_view)
                    if not current():
                        dialog.close()
                        return
                    label=(capture.get('items') or [{}])[0].get('source') or f'采集 {len(draft.entries)+1}'
                    draft.append(capture, options['request'], selected_view, options['run_id'], source_page, label)
                    render_staged(); ui.notify(f'已暂存采集项：{label}，可继续采集',type='positive')
                except Exception as exc: ui.notify(f'采集失败，暂存内容仍保留：{exc}',type='negative')
                finally:
                    workspace.busy=False
                    if not dialog.is_deleted: recording_controls.sync()

            async def cancel():
                if workspace.busy: return
                if workspace.recording.committed:
                    ui.notify('上下文已保存，请重试确认保存完成录制确认；关闭弹窗会保留草稿。',type='warning')
                    return
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
                if workspace.recording.pending:
                    if not await confirm_discard(): return
                elif not await self.may_discard_draft(draft, workspace.fields['name'], workspace.fields['notes'], initial_name, initial_notes, confirm_discard):
                    return
                if not current():
                    dialog.close()
                    return
                try: await workspace.recording.discard()
                except Exception as exc:
                    ui.notify(f'丢弃失败，录制仍保留：{exc}',type='negative')
                    return
                workspace.forget()
                dialog.close()
                if dialog in self._dialogs: self._dialogs.remove(dialog)

            async def save_batch():
                if workspace.busy: return
                if not current():
                    dialog.close()
                    return
                if existing and not workspace.recording.pending and not workspace.recording.committed and not draft.dirty and (workspace.fields['name'] or '') == initial_name and (workspace.fields['notes'] or '') == initial_notes:
                    workspace.forget()
                    dialog.close()
                    return
                async def commit():
                    return await self.save_batch(existing,workspace.fields['provider'],(workspace.fields['name'] or '').strip(),workspace.fields['notes'] or '',draft,
                                          step_id=target_step_id,generation=generation,task_id=target_task_id)
                async def save():
                    await workspace.recording.persist(commit)
                    workspace.forget()
                    dialog.close(); ui.notify('上下文已保存',type='positive')
                    if dialog in self._dialogs: self._dialogs.remove(dialog)
                await recording_controls.run(save)

            def start_options():
                if not current(): raise TaskError('CONTEXT_SESSION_CHANGED')
                return form_state.start_options(environment_id=self.environment_id(), step=True)

            capture_control = None
            def lock_inputs(locked):
                for control in (provider,run,include_view,advanced):
                    control.set_enabled(not locked and not (control is provider and existing and existing.get('context_id')))
                for form in request_forms.values():
                    for _,control in form.controls.values(): control.set_enabled(not locked)
                picker=target_state['picker']
                if picker: picker.select.set_enabled(not locked)
                for control in (name,notes): control.set_enabled(not workspace.busy and not workspace.recording.committed)
                if capture_control is not None:
                    capture_control.set_enabled(workspace.fields['provider'] in available_providers and not workspace.busy and not workspace.recording.committed)
                if workspace.recording.committed:
                    for element in staged_area.descendants():
                        if hasattr(element,'disable'): element.disable()

            recording_controls=RecordingControls(workspace,dialog,start_options,lock_inputs,render_staged)
            def recording_supported():
                return workspace.fields['provider'] in available_providers and request_schemas.get(workspace.fields['provider'],{}).get('x-taskweave-context-recording') is True
            recording_controls.sync(recording_supported())
            provider.on_value_change(lambda _:recording_controls.sync(recording_supported()))
            workspace.capture_fields = None
            async def hidden():
                if workspace.dialog is not dialog: return
                try: await workspace.hide()
                except Exception as exc: ui.notify(f'暂停录制失败，原实例仍保留：{exc}',type='negative')
            dialog.on('hide',hidden)
            workspace.dialog=dialog

            capture_control = self.button('采集一项',collect,primary=True)
            recording_controls.sync()
            ui.label('采集结果仅暂存在弹窗；确认保存后才会进入 AI 输入。浏览器等外部操作不会因取消自动回滚。').classes('text-xs text-gray-500')
            with ui.row().classes('w-full justify-end gap-2'):
                ui.button('取消',on_click=cancel).props('outline')
                ui.button('确认保存',on_click=save_batch).props('unelevated color=primary')
        dialog.open()
