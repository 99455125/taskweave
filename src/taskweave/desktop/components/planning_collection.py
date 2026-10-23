"""Plan page: collect plugin evidence and turn a validated candidate into a task."""

import copy
import json
from nicegui import ui
from taskweave.core.validation import TaskError
from taskweave.desktop.forms import ValueForm, compact_field, arrange_context_fields
from taskweave.presentation.collection_form import CollectionForm
from taskweave.desktop.context_recording import collection_workspace, RecordingControls
from taskweave.desktop.contexts import (
    render_context_draft_rows, show_context_preview,
    ContextTargetPicker,
    context_hidden_parameters,
    context_advanced_overrides,
    context_target_options,
    context_view_default,
    context_surface_defaults,
)

from taskweave.presentation.planning import PlanningCollection


class PlanningCollectionView:
    """NiceGUI collection controls over the shared recording and capture drafts."""

    async def collect_dialog(self, plan, existing=None, on_saved=None):
        if existing and existing.get('capture_id'):
            existing = {**existing, **await self.controller.call('plan.context.capture.get', context_id=existing['context_id'], capture_id=existing['capture_id'], plan_id=plan['plan_id'])}
        elif existing and existing.get('captures'):
            latest=existing['captures'][-1]
            existing={**existing,**await self.controller.call('plan.context.capture.get',context_id=existing['context_id'],capture_id=latest['capture_id'],plan_id=plan['plan_id'])}
        requests = self.controller.plugin_context_requests()
        available = {key: value for key, value in requests.items() if key.split(".", 1)[0] in set(plan.get("plugin_ids", []))}
        if not available: raise TaskError("CONTEXT_PROVIDER_UNAVAILABLE", "所选插件没有上下文采集器")
        workspace = collection_workspace(self.controller, ('plan',plan['plan_id'],(existing or {}).get('context_id')), (existing or {}).get('captures', []))
        if not await workspace.prepare_dialog(ui.context.client):
            return
        form_state = CollectionForm(workspace.fields, available)
        draft = workspace.draft
        collection = PlanningCollection(self.controller, plan, draft, (existing or {}).get("context_id"))
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

        workspace.bind(collection.record, source_page='planning')
        with ui.dialog() as dialog, ui.card().classes("tw-context-collection-dialog w-full max-w-5xl"):
            with ui.row().classes('tw-context-dialog-header w-full justify-between items-center'):
                ui.label("编辑与采集上下文 · 规划").classes("text-lg font-medium")
                ui.button(icon='close', on_click=lambda:cancel()).props('flat round dense aria-label=关闭弹窗')
            with ui.column().classes('tw-context-collection-body w-full'):
                initial_provider = existing.get("provider_id") if existing else next(iter(sorted(available)))
                if initial_provider not in available:
                    initial_provider = next(iter(sorted(available)))
                with ui.row().classes('tw-context-basics w-full items-start'):
                    name = ui.input("上下文名称", value=workspace.fields.get('name',initial_name)).classes("w-full")
                    bind_field('name', name)
                    notes = ui.textarea("操作说明（可选）", value=workspace.fields.get('notes',initial_notes), placeholder="说明本组页面或数据的用途，以及操作顺序").props("autogrow").classes("w-full")
                    bind_field('notes', notes)

                staged_title = ui.label().classes("font-medium")
                staged_area = ui.column().classes("w-full gap-2")
                deleted_area = ui.column().classes("w-full gap-1")
                capture_actions = ui.row().classes('tw-context-collection-actions w-full items-end gap-3 flex-wrap')
                rendered_count = len(draft.entries)

                with ui.column().classes('tw-context-parameters w-full'):
                    ui.label('采集参数').classes('tw-context-parameter-heading')

                    selectors = ui.row().classes("tw-context-param-selectors w-full")
                    with selectors, ui.column().classes("tw-context-param-field w-full gap-0") as provider_field:
                        provider = ui.select(sorted(available), value=workspace.fields.get('provider',initial_provider), label="插件采集器").classes("w-full")
                        compact_field(provider)
                    bind_field('provider', provider)
                    if existing and existing.get('context_id'):
                        provider.disable()

                    async def load_targets():
                        return await self.controller.call("plan.context.targets", plan_id=plan["plan_id"], provider_id=workspace.fields['provider'])

                    with selectors:
                        target_area = ui.column().classes("tw-context-param-target tw-context-param-wide w-full gap-0")
                    target_state = {"picker": None, "options": None}

                    host_fields = {'$provider': provider_field, '$target': target_area}
                    selectors.set_visibility(False)
                    request_forms = {}
                    request_groups = {}
                    for identifier, request_schema in available.items():
                        schema = copy.deepcopy(request_schema)
                        for key, value in context_surface_defaults(request_schema, "planning").items():
                            schema["properties"][key]["default"] = value
                        if existing and identifier == initial_provider:
                            for key, value in existing.get("request", {}).items():
                                if key in schema.get("properties", {}):
                                    schema["properties"][key]["default"] = value
                        with ui.column().classes("tw-context-request-grid w-full") as group:
                            request_forms[identifier] = ValueForm(schema, compact=True)
                        request_groups[identifier] = group
                        bind_form(identifier, request_forms[identifier], schema)

                    def update_request_form(_=None):
                        picker = target_state["picker"]
                        for identifier, group in request_groups.items():
                            group.set_visibility(identifier == workspace.fields['provider'])
                            request_forms[identifier].hide_fields(context_hidden_parameters(
                                available[identifier], identifier == workspace.fields['provider'] and picker is not None and not picker.uses_parameters
                            ))

                        selected = workspace.fields['provider']
                        selected_schema = available.get(selected, {})
                        hidden = context_hidden_parameters(selected_schema, picker is not None and not picker.uses_parameters)
                        active_host = dict(host_fields)
                        if not context_target_options(selected_schema):
                            active_host.pop('$target', None)
                        if context_view_default(selected_schema) is None:
                            active_host.pop('$preview', None)
                        arrange_context_fields(selected_schema, request_groups[selected], request_forms[selected], active_host, hidden)

                    async def select_provider(_=None):
                        selected = workspace.fields.get('target', (existing or {}).get("request", {}).get("target_id"))
                        target_area.clear()
                        options = context_target_options(available[workspace.fields['provider']])
                        target_state.update(picker=None, options=options)
                        target_area.set_visibility(bool(options))
                        form_state.target = None
                        if options:
                            with target_area:
                                picker = ContextTargetPicker(load_targets, options, compact=True)
                            target_state["picker"] = picker
                            form_state.target = picker.interaction
                            picker.select.on_value_change(lambda event: form_state.change("target", event.value))
                            picker.select.on_value_change(update_request_form)
                            await picker.refresh()
                            if selected and selected in picker.targets:
                                picker.select.value = selected
                        update_request_form()

                    provider.on_value_change(select_provider)
                    await select_provider()
                    view_default = context_view_default(available[workspace.fields['provider']])
                    view_state = {"supported": view_default is not None}
                    include_view = ui.checkbox("同时生成预览", value=workspace.fields.get('include_view',(existing or {}).get("include_view", view_default is True)))
                    bind_field('include_view', include_view)
                    include_view.props("dense").classes("tw-context-param-preview")
                    host_fields['$preview'] = include_view
                    update_request_form()
                    include_view.set_visibility(view_state["supported"])

                    def update_view_option(_=None):
                        default = context_view_default(available[workspace.fields['provider']])
                        view_state["supported"] = default is not None
                        update_request_form()
                        include_view.set_visibility(view_state["supported"])
                        if not existing:
                            include_view.value = default is True
                    provider.on_value_change(update_view_option)
                    advanced_values = context_advanced_overrides(
                        available[initial_provider], (existing or {}).get("request", {})
                    )
                    with ui.expansion("高级参数 JSON", icon="tune").props("dense").classes("tw-context-advanced w-full"):
                        advanced = ui.textarea(
                            "JSON 对象", value=workspace.fields.get('advanced',json.dumps(advanced_values, ensure_ascii=False, indent=2))
                        ).classes("w-full")

                    bind_field('advanced', advanced)

                async def preview_item(entry):
                    preview_identity = self._planning_identity()
                    if entry.get('is_new'):
                        capture = entry['capture']
                    else:
                        capture = await self.controller.call('plan.context.capture.get', plan_id=plan['plan_id'], context_id=existing['context_id'], capture_id=entry['capture_id'])
                    if not self._identity_is_current(preview_identity):
                        return
                    await self.show_context_preview(entry.get('label') or '采集项', capture)

                def render_staged():
                    nonlocal rendered_count
                    staged_title.text = f"已采集 · {len(draft.entries)}"
                    staged_area.clear(); deleted_area.clear()
                    deleted_area.set_visibility(bool(draft.deleted))
                    with staged_area:
                        render_context_draft_rows(draft, preview_item, render_staged, scroll_target=capture_actions if len(draft.entries) > rendered_count else None,
                                                  redact_on_display=self.controller.privacy_settings()["redact_on_display"])
                    rendered_count = len(draft.entries)
                    if draft.deleted:
                        with deleted_area:
                            ui.label('待删除（可撤销）').classes('text-xs text-gray-500')
                            for entry in draft.deleted:
                                with ui.row().classes('items-center gap-2'):
                                    ui.label(entry.get('label') or '采集项')
                                    ui.button('撤销删除', on_click=lambda item=entry: (draft.undo_delete(item), render_staged())).props('flat dense')
                render_staged()

                async def collect():
                    if not workspace.interaction.begin_operation(capture=True):
                        return
                    recording_controls.sync()
                    try:
                        options, selected_view = form_state.start_options()
                        entry = await collection.collect(options['provider_id'], options['request'],
                            options['expected_session_id'], selected_view)
                        label = entry['label']
                        render_staged()
                        ui.notify(f'已暂存采集项：{label}，可继续采集', type='positive')
                    except ValueError as exc:
                        ui.notify(f'采集失败，暂存内容仍保留：高级参数需要有效 JSON 对象（{exc}）', type='negative')
                    except Exception as exc:
                        ui.notify(f'采集失败，暂存内容仍保留：{exc}', type='negative')
                    finally:
                        workspace.interaction.finish_operation()
                        if not dialog.is_deleted:
                            recording_controls.sync()

                async def cancel():
                    decision = workspace.interaction.cancel_decision(initial_name, initial_notes)
                    if decision == 'busy':
                        return
                    if decision == 'committed':
                        ui.notify('上下文已保存，请重试确认保存以完成录制确认；关闭弹窗会保留草稿。', type='warning')
                        return
                    approved = False
                    if decision == 'confirm':
                        with ui.dialog() as confirm, ui.card().classes('tw-confirm-dialog'):
                            ui.label('丢弃未保存的内容？').classes('tw-confirm-title')
                            ui.label('本次编辑和采集项将不会保存。').classes('tw-confirm-description')
                            with ui.row().classes('tw-confirm-actions'):
                                ui.button('继续编辑', on_click=lambda: confirm.submit(False)).props('outline').classes('tw-confirm-cancel')
                                ui.button('丢弃并关闭', on_click=lambda: confirm.submit(True)).props('outline color=negative').classes('tw-confirm-danger')
                        approved = bool(await confirm)
                    try:
                        closed = await workspace.interaction.cancel(initial_name, initial_notes, approved=approved)
                    except Exception as exc:
                        ui.notify(f'丢弃失败，录制仍保留：{exc}', type='negative')
                        return
                    if closed:
                        workspace.forget()
                        dialog.close()

                async def save_batch():
                    decision = workspace.interaction.save_decision(bool(existing), initial_name, initial_notes)
                    if decision == 'busy':
                        return
                    if decision == 'unchanged':
                        workspace.forget()
                        dialog.close()
                        return
                    async def save():
                        result = await collection.save(workspace.recording, workspace.fields['provider'], workspace.fields.get('name') or '', workspace.fields.get('notes') or '')
                        if on_saved: await on_saved(result['group'])
                        workspace.forget()
                        dialog.close()
                    await recording_controls.run(save)

                def start_options():
                    return form_state.start_options()

                def lock_inputs(locked):
                    for control in (provider,include_view,advanced):
                        control.set_enabled(not locked and not (control is provider and existing and existing.get('context_id')))
                    for form in request_forms.values():
                        for _,control in form.controls.values(): control.set_enabled(not locked)
                    picker=target_state['picker']
                    if picker: picker.select.set_enabled(not locked)
                    for control in (name,notes): control.set_enabled(not workspace.busy and not workspace.recording.committed)
                    if workspace.recording.committed:
                        for element in staged_area.descendants():
                            if hasattr(element,'disable'): element.disable()

                with capture_actions:
                    recording_controls=RecordingControls(workspace,dialog,start_options,lock_inputs,render_staged)
                recording_controls.sync(available[workspace.fields['provider']].get('x-taskweave-context-recording') is True)
                provider.on_value_change(lambda _:recording_controls.sync(available[workspace.fields['provider']].get('x-taskweave-context-recording') is True))
                workspace.capture_fields = None
                async def hidden():
                    if workspace.dialog is not dialog: return
                    try: await workspace.hide()
                    except Exception as exc: ui.notify(f'暂停录制失败，原实例仍保留：{exc}',type='negative')
                dialog.on('hide',hidden)
                workspace.dialog=dialog

                with capture_actions:
                    self.button('采集一项', collect, primary=True)
            with ui.row().classes('tw-context-dialog-actions w-full justify-end gap-2'):
                ui.button('取消', on_click=cancel).props('outline')
                ui.button('确认保存', on_click=save_batch).props('unelevated color=primary')
        dialog.open()

    async def show_context_preview(self, title, capture):
        identity = self._planning_identity()
        await show_context_preview(title, capture, self.controller.result_renderers,
            self.render_result, redact_on_display=self.controller.privacy_settings()['redact_on_display'],
            is_active=lambda: self._identity_is_current(identity))

    async def context_preview(self, context):
        identity = self._planning_identity()
        capture = await self.controller.call('plan.context.capture.get', context_id=context['context_id'], capture_id=context['capture_id'], plan_id=self.state.plan_id)
        if not self._identity_is_current(identity):
            return
        await self.show_context_preview(context["name"] + " · " + (context.get('label') or '采集项'), capture)
