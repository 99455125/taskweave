"""Shared context cards and plugin-owned collection target selection."""

import asyncio
from datetime import datetime
import json
from urllib.parse import urlsplit, urlunsplit

from nicegui import ui
from taskweave.core.context_collection import capture_ai_payload

from taskweave.core.validation import TaskError
from taskweave.infrastructure.privacy import redact, redact_collected_context
from taskweave.desktop.forms import compact_field


_CONTEXT_FIELDS = {
    'title':'页面标题', 'url':'页面地址', 'role':'角色', 'captured_at':'采集时间',
    'elements':'页面元素', 'frames':'页面框架', 'events':'录制动作', 'tag':'元素标签',
    'name':'名称', 'label':'标签', 'type':'类型', 'text':'文本', 'value':'值',
    'visible':'可见', 'enabled':'可用', 'editable':'可编辑', 'selector':'定位器',
    'preferred_selector':'首选定位器', 'candidate_selectors':'候选定位器',
    'attributes':'属性', 'placeholder':'占位提示', 'match_count':'匹配数量',
    'target':'目标元素', 'kind':'动作 / 类型', 'sequence':'顺序', 'truncated':'内容已截断',
}


def _context_scalar(value):
    if value is True:return '是'
    if value is False:return '否'
    if value is None:return '未提供'
    return str(value)


def _context_field_nodes(value, path='data'):
    """Preserve all fields while presenting nested data as expandable nodes."""
    pairs=value.items() if isinstance(value,dict) else enumerate(value) if isinstance(value,list) else [('内容',value)]
    nodes=[]
    for key,item in pairs:
        label=f'{_CONTEXT_FIELDS[key]} ({key})' if key in _CONTEXT_FIELDS else str(key)
        node={'id':f'{path}/{key}','label':label}
        if isinstance(item,(dict,list)):
            node['label']+=f' · {len(item)} 项'
            node['children']=_context_field_nodes(item,node['id'])
        else:
            node['label']+='：'+_context_scalar(item)
        nodes.append(node)
    return nodes


def _render_context_fields(value):
    search=ui.input('查找字段或内容',placeholder='例如 selector、字段名、控件名称').props('outlined dense clearable').classes('w-full')
    tree=ui.tree(_context_field_nodes(value)).props('dense').classes('tw-context-field-tree w-full break-words')
    search.bind_value_to(tree,'filter',forward=lambda value:value or '')


def _context_locator_summary(selector):
    if isinstance(selector,str):return selector
    if not isinstance(selector,dict):return '未提供'
    return ' · '.join(f'{key}={selector[key]}' for key in ('kind','value','name','nth') if key in selector)


def _render_context_records(records, title, *, actions=False, is_active, register_dialog=None):
    rows=[]
    for index,record in enumerate(records):
        if not isinstance(record,dict):
            record={'value':record}
        target=record.get('target') if actions else record
        target=target if isinstance(target,dict) else {}
        rows.append({'_row':index,'order':record.get('sequence',index+1),
            'name':target.get('name') or target.get('label') or target.get('text') or target.get('placeholder') or target.get('id') or '未命名',
            'type':target.get('tag') or target.get('type') or target.get('role') or '未提供',
            'action':record.get('kind') or record.get('type') or record.get('action') or '未提供',
            'visible':_context_scalar(target.get('visible')),'enabled':_context_scalar(target.get('enabled')),
            'locator':_context_locator_summary(target.get('preferred_selector') or target.get('selector'))})
    ui.label(f'{title} · {len(records)} 项').classes('font-medium')
    ui.label('点击一行查看完整属性、定位器和参数。').classes('text-xs text-gray-500')
    search=ui.input('筛选'+title).props('outlined dense clearable').classes('w-full')
    names=[('order','顺序'),('action','动作'),('name','目标名称'),('locator','定位器')] if actions else [
        ('order','序号'),('name','名称 / 文本'),('type','类型'),('visible','可见'),('enabled','可用'),('locator','定位器')]
    table=ui.table(columns=[{'name':key,'label':label,'field':key,'align':'left','sortable':True} for key,label in names],
                   rows=rows,row_key='_row',pagination=10).classes('tw-context-data-table w-full').props('wrap-cells')
    search.bind_value_to(table,'filter',forward=lambda value:value or '')
    def details(event):
        if not is_active():return
        record=records[event.args[1]['_row']]
        with ui.dialog() as dialog,ui.card().classes('w-full max-w-4xl'):
            if register_dialog:register_dialog(dialog)
            ui.label(title+' · 完整字段').classes('text-lg font-semibold')
            _render_context_fields(record)
            target=record.get('target',{}) if actions and isinstance(record,dict) else record
            selector=(target.get('preferred_selector') or target.get('selector')) if isinstance(target,dict) else None
            if selector is not None:
                with ui.expansion('复制定位器',icon='content_copy').classes('w-full'):
                    ui.code(json.dumps(selector,ensure_ascii=False,indent=2),language='json').classes('w-full')
            ui.button('关闭',on_click=dialog.close).props('outline')
        dialog.open()
    table.on('rowClick',details)


def _render_context_data(data, *, is_active, register_dialog=None):
    if not isinstance(data,dict):
        _render_context_fields(data)
        return
    metadata={key:value for key,value in data.items() if key not in {'elements','frames','events'}}
    if metadata:_render_context_fields(metadata)
    for key,title in [('elements','页面元素'),('events','录制动作')]:
        if isinstance(data.get(key),list):
            _render_context_records(data[key],title,actions=key=='events',is_active=is_active,register_dialog=register_dialog)
    frames=data.get('frames')
    if isinstance(frames,list):
        for index,frame in enumerate(frames):
            with ui.expansion(f'页面框架 {index+1}',icon='web').classes('w-full'):
                _render_context_data(frame,is_active=is_active,register_dialog=register_dialog)


async def show_context_preview(title, capture, renderers, render_result, *,
                               redact_on_display=True, is_active=lambda: True,
                               register_dialog=None):
    """One read-only reader for screenshots, structured data and original items."""
    visible = redact_collected_context(capture, renderers) if redact_on_display else capture
    views, items = visible.get('views', []), visible.get('items', [])
    detail_dialogs=[]
    def register_detail(child):
        detail_dialogs.append(child)
        if register_dialog:register_dialog(child)
    with ui.dialog() as dialog, ui.card().classes('tw-context-preview-dialog'):
        if register_dialog:register_dialog(dialog)
        dialog.on('hide',lambda:[child.close() for child in detail_dialogs if not child.is_deleted])
        with ui.row().classes('tw-context-preview-header w-full items-center justify-between'):
            with ui.column().classes('gap-1 min-w-0 flex-1'):
                ui.label(title or '采集项').classes('text-lg font-semibold break-words')
                ui.label('上下文查看 · 可据此手动编写步骤代码').classes('text-xs text-gray-500')
            ui.button(icon='close',on_click=dialog.close).props('flat round dense aria-label=关闭预览')
        with ui.column().classes('tw-context-preview-body w-full'):
            with ui.tabs().classes('w-full') as tabs:
                ui.tab('采集数据',icon='account_tree')
                ui.tab('截图与预览',icon='image')
                ui.tab('原文',icon='data_object')
            with ui.tab_panels(tabs,value='采集数据' if items else '截图与预览').classes('w-full'):
                with ui.tab_panel('采集数据').classes('w-full p-0'):
                    for index,item in enumerate(items):
                        with ui.expansion(f"{index+1}. {item.get('source') or '采集内容'}",value=index==0).classes('w-full'):
                            if item.get('truncated'):ui.label('此项采集内容已截断，未包含完整数据。').classes('text-amber-700')
                            data=item.get('content','')
                            if isinstance(data,str):
                                try:data=json.loads(data)
                                except (ValueError,TypeError):pass
                            _render_context_data(data,is_active=is_active,register_dialog=register_detail)
                    if not items:ui.label('暂无采集数据').classes('text-gray-500')
                with ui.tab_panel('原文').classes('w-full p-0'):
                    ui.label('原始采集数据 · 沿用当前显示脱敏设置').classes('text-xs text-gray-500')
                    ui.code(json.dumps(items,ensure_ascii=False,indent=2),language='json').classes('tw-context-raw w-full tw-code')
                with ui.tab_panel('截图与预览').classes('w-full p-0'):
                    for view in views:
                        with ui.column().classes('tw-context-preview-media w-full gap-2'):
                            ui.label(view.get('title') or '预览').classes('text-sm font-medium')
                            kind=renderers.get(view['renderer'],{}).get('type','json')
                            try:await render_result(kind,view['data'],{})
                            except ValueError as exc:ui.label(str(exc)).classes('text-red-700')
                            if not is_active():
                                dialog.close()
                                return dialog
                    if not views:ui.label('本次未采集截图或其他预览，仍可查看采集数据。').classes('text-gray-500')
        with ui.row().classes('tw-context-preview-footer w-full items-center justify-end gap-3'):
            ui.button('关闭',on_click=dialog.close).props('outline')
    if is_active():dialog.open()
    return dialog


def context_capture_summary(entry, *, redact_on_display=True):
    """Use collected page metadata; keep URL credentials and queries out of summaries."""
    title, url, source = "", "", ""
    for item in entry.get("capture", {}).get("items", []):
        source = source or item.get("source", "")
        if item.get("source") != "playwright.page":
            continue
        try:
            data = json.loads(item.get("content", ""))
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict):
            title = data.get("title") if isinstance(data.get("title"), str) else ""
            url = data.get("url") if isinstance(data.get("url"), str) else ""
            break
    if url:
        try:
            parsed = urlsplit(url)
            url = urlunsplit((parsed.scheme, parsed.netloc.rsplit("@", 1)[-1], parsed.path, "", ""))
        except ValueError:
            url = ""
    summary = url or source
    return (redact(title), redact(summary)) if redact_on_display else (title, summary)


def _render_context_draft_row(draft, entry, index, preview, refresh, *, redact_on_display):
    page_title, source = context_capture_summary(entry, redact_on_display=False)
    if redact_on_display:
        source = redact(source)
    if entry.get("is_new") and page_title and entry.get("label") in {"", "playwright.page"}:
        entry["label"] = page_title
    with ui.column().classes("tw-context-staged-row w-full gap-0"):
        with ui.row().classes("tw-context-staged-header w-full items-start gap-2"):
            ui.label(str(index + 1)).classes("tw-context-index")
            title_area = ui.column().classes("tw-context-staged-identity gap-0")

            def render_title():
                title_area.clear()
                with title_area:
                    title = entry.get("label") or f"采集 {index + 1}"
                    ui.button(redact(title) if redact_on_display else title, on_click=edit_title).props(
                        "flat dense icon-right=edit").classes("tw-context-staged-title")

            def edit_title():
                original_title = entry.get("label") or ""
                title_area.clear()
                with title_area:
                    control = ui.input("采集项标题", value=entry.get("label") or "").props(
                        "dense outlined autofocus").classes("w-full").bind_value(entry, "label")
                finished = False

                def finish(save=True):
                    nonlocal finished
                    if finished:
                        return
                    finished = True
                    if save:
                        entry["label"] = (control.value or "").strip() or original_title
                    else:
                        entry["label"] = original_title
                    render_title()
                control.on("keydown.enter", lambda: finish())
                control.on("keydown.escape", lambda: finish(False))
                control.on("blur", lambda: finish())
            render_title()
            with ui.row().classes("tw-context-staged-tools items-center gap-1"):
                saved_time = context_capture_time(entry.get("captured_at"))
                status = "本次采集" if entry.get("is_new") else (f"已保存 · {saved_time}" if saved_time else "已保存")
                ui.label(status).classes("tw-context-staged-status")
                with ui.row().classes("tw-context-preview-choice items-center gap-1"):
                    ui.button("查看上下文", icon="visibility", on_click=lambda: preview(entry)).props("flat dense")
                    ui.checkbox("携带预览").props("dense").bind_value(entry, "send_preview").set_enabled(
                        bool(entry.get("has_preview") or entry.get("capture", {}).get("views")))
                with ui.button(icon="more_horiz").props("flat round dense aria-label=暂存采集项更多"):
                    with ui.menu():
                        ui.menu_item("上移", on_click=lambda: (draft.move(entry, "up"), refresh())).set_enabled(index > 0)
                        ui.menu_item("下移", on_click=lambda: (draft.move(entry, "down"), refresh())).set_enabled(index < len(draft.entries) - 1)
                        ui.menu_item("删除采集项", on_click=lambda: (draft.remove(entry), refresh())).props("class=text-red-7")
        notes_area = ui.column().classes("tw-context-staged-notes w-full gap-0")

        def render_notes():
            notes_area.clear()
            with notes_area:
                notes = entry.get("operation_notes") or ""
                with ui.row().classes("tw-context-staged-meta w-full items-center gap-2 flex-nowrap"):
                    if source:
                        ui.label(source).classes("tw-context-staged-source grow min-w-0").tooltip(source)
                    else:
                        ui.space()
                    with ui.row().classes("tw-context-note-actions items-center gap-1"):
                        if len(notes) > 70 or "\n" in notes:
                            def toggle_notes(event):
                                expanded = "tw-context-note-expanded" not in text.classes
                                text.classes(toggle="tw-context-note-expanded")
                                event.sender.text = "收起" if expanded else "展开"
                            ui.button("展开", on_click=toggle_notes).props("flat dense")
                        ui.button("编辑说明", on_click=edit_notes).props("flat dense")
                if notes:
                    text = ui.label(notes).classes("tw-context-staged-note-text w-full")

        def edit_notes():
            original_notes = entry.get("operation_notes") or ""
            notes_area.clear()
            with notes_area:
                control = ui.textarea("操作说明", value=entry.get("operation_notes") or "").props(
                    "outlined autogrow autofocus").classes("w-full").bind_value(entry, "operation_notes")
                def cancel():
                    entry["operation_notes"] = original_notes
                    render_notes()
                def save():
                    entry["operation_notes"] = (control.value or "").strip()
                    render_notes()
                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button("取消", on_click=cancel).props("flat dense")
                    ui.button("完成", on_click=save).props("unelevated dense")
        render_notes()


def render_context_draft_rows(draft, preview, refresh, *, scroll_target=None, redact_on_display=True):
    """Shared compact cards; edits and preview choices stay in the collection draft."""
    for index, entry in enumerate(draft.entries):
        _render_context_draft_row(draft, entry, index, preview, refresh, redact_on_display=redact_on_display)
    if scroll_target is not None and scroll_target.client.has_socket_connection:
        ui.run_javascript(
            f'requestAnimationFrame(() => document.getElementById("c{scroll_target.id}")?.scrollIntoView({{block: "nearest"}}))'
        )


def context_capture_time(value):
    if not value:
        return ""
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone().strftime("%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return ""


from taskweave.presentation.context_collection import (
    ContextCaptureDraft, context_target_options, context_hidden_parameters,
    context_view_default, context_surface_defaults, context_advanced_overrides,
    merge_context_request, context_ai_items,
)


class ContextCards:
    """Compact, shared context-group and capture rows for planning and steps."""

    def __init__(self, entries, save, delete, move=None, recollect=None, preview=None,
                 append=None, delete_capture=None, move_capture=None, update_capture=None,
                 preview_capture=None, redact_on_display=True, is_active=None, expanded=None, transfer=None):
        self.entries, self.save, self.delete = entries, save, delete
        self.transfer = transfer
        self.move, self.recollect, self.append = move, recollect, append
        self.preview_capture, self.delete_capture = preview_capture, delete_capture
        self.move_capture, self.update_capture = move_capture, update_capture
        self.redact_on_display = redact_on_display
        self.is_active = is_active or (lambda: True)
        self.expanded = expanded if expanded is not None else set()
        self.cards = {}
        self.panel = ui.column().classes("tw-context-cards w-full min-w-0 gap-2")
        self.rebuild()

    def title(self):
        return f"上下文材料 · {len(self.entries)} 组"

    def rebuild(self):
        if self.panel.is_deleted:
            return
        self.panel.clear()
        self.cards.clear()
        with self.panel:
            with ui.row().classes("tw-context-heading w-full items-center justify-between gap-2 flex-wrap"):
                ui.label(self.title()).classes("font-semibold")
                if self.append:
                    ui.button("采集上下文", on_click=self.append, icon="add").props("outline dense")
            if not self.entries:
                ui.label("暂无插件上下文").classes("tw-context-empty text-sm text-gray-500")
            for entry in self.entries:
                self.add(entry)

    def add(self, entry):
        index = self.entries.index(entry) + 1
        key = entry["context_id"]
        captures = entry.get("captures", [])
        def remember(event):
            if event.value:
                self.expanded.add(key)
            else:
                self.expanded.discard(key)
        with ui.expansion(
            (entry.get("name") or "未命名上下文") + f" · {len(captures)} 项",
            caption=entry.get("provider_id", ""), value=key in self.expanded,
            on_value_change=remember,
        ).classes("tw-context-group w-full min-w-0 border rounded") as card:
            with ui.row().classes("tw-context-group-actions w-full items-center justify-end gap-1"):
                ui.button("编辑组说明", on_click=lambda: self.edit_group(entry)).props("flat dense")
                if self.recollect:
                    ui.button("继续采集", on_click=lambda: self.recollect(entry)).props("flat dense")
                with ui.button(icon="more_horiz").props("flat dense aria-label=上下文组更多"):
                    with ui.menu():
                        if self.move:
                            ui.menu_item("上移上下文", on_click=lambda: self.move_entry(entry, "up")).set_enabled(index > 1)
                            ui.menu_item("下移上下文", on_click=lambda: self.move_entry(entry, "down")).set_enabled(index < len(self.entries))
                        if self.transfer:
                            ui.menu_item("移动整组材料…", on_click=lambda: self.transfer(entry, None, "move"))
                            ui.menu_item("复制整组材料…", on_click=lambda: self.transfer(entry, None, "copy"))
                        ui.menu_item("删除上下文", on_click=lambda: self.remove(entry)).props("class=text-red-7")
            if entry.get("context_notes"):
                ui.label(entry["context_notes"]).classes("tw-context-notes w-full text-sm text-gray-600")
            if not captures:
                ui.label("暂无采集项").classes("text-xs text-gray-500")
            for capture_index, capture in enumerate(captures, 1):
                self.add_capture(entry, capture, capture_index, len(captures))
        self.cards[key] = card

    async def edit_group(self, entry):
        with ui.dialog() as dialog, ui.card().classes("tw-context-edit-dialog w-full max-w-2xl"):
            ui.label("编辑上下文组").classes("text-lg font-medium")
            name = ui.input("上下文名称", value=entry.get("name", "")).classes("w-full")
            notes = ui.textarea("操作说明", value=entry.get("context_notes", "")).props("autogrow").classes("w-full")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("取消", on_click=dialog.close).props("outline")
                async def save_group():
                    try:
                        await self.save(entry, name.value or "", notes.value or "")
                        if self.is_active():
                            entry.update(name=name.value or "", context_notes=notes.value or "")
                            self.rebuild()
                            dialog.close()
                    except Exception as exc:
                        if self.is_active(): ui.notify(str(exc), type="negative")
                ui.button("保存", on_click=save_group).props("unelevated color=primary")
        dialog.open()

    def add_capture(self, group, capture, index, count):
        title = capture.get("label") or f"采集 {index}"
        captured_at = capture.get("captured_at")
        readable_time = context_capture_time(captured_at)
        source_name = {"draft":"步骤采集", "planning":"规划采集", "planning_import":"规划导入"}.get(capture.get("source_page"), "")
        metadata = " · ".join(value for value in (readable_time, source_name) if value)
        notes = capture.get("operation_notes") or ""
        preview = self.capture_preview(capture) if not self.preview_capture else ""
        with ui.column().classes("tw-context-capture-row w-full gap-0"):
            with ui.row().classes("tw-context-capture-header w-full items-center gap-2 flex-nowrap"):
                ui.label(f"{index}.").classes("tw-context-capture-index shrink-0")
                ui.label(title).classes("tw-context-capture-name min-w-0 grow").tooltip(title)
                with ui.row().classes("tw-context-capture-actions items-center gap-1 flex-nowrap"):
                    if self.preview_capture or self.update_capture:
                        with ui.row().classes("tw-context-preview-choice items-center gap-1"):
                            if self.preview_capture:
                                ui.button("查看上下文", on_click=lambda _event=None, g=group, c=capture: self.preview_capture(g, c)).props("flat dense icon=visibility")
                            if self.update_capture:
                                async def toggle_preview(event):
                                    if not self.is_active() or event.sender.is_deleted or event.value == bool(capture.get("send_preview")):
                                        return
                                    event.sender.disable()
                                    try:
                                        await self.update_capture(group, capture, title, send_preview=event.value)
                                        if self.is_active():
                                            capture["send_preview"] = event.value
                                    except Exception as exc:
                                        if self.is_active():
                                            if not event.sender.is_deleted:
                                                event.sender.set_value(bool(capture.get("send_preview")))
                                            ui.notify(str(exc), type="negative")
                                    finally:
                                        if self.is_active() and not event.sender.is_deleted:
                                            event.sender.enable()
                                ui.checkbox("携带预览", value=bool(capture.get("send_preview")),
                                            on_change=toggle_preview).props("dense").set_enabled(
                                                bool(capture.get("has_preview") or capture.get("views")))
                    with ui.button(icon="more_horiz").props("flat dense aria-label=采集项更多"):
                        with ui.menu():
                            if self.update_capture:
                                ui.menu_item("改名", on_click=lambda _event=None, g=group, c=capture: self.edit_capture_label(g, c))
                            if self.move_capture:
                                ui.menu_item("上移", on_click=lambda _event=None, g=group, c=capture: self.move_capture(g, c, "up")).set_enabled(index > 1)
                                ui.menu_item("下移", on_click=lambda _event=None, g=group, c=capture: self.move_capture(g, c, "down")).set_enabled(index < count)
                            if self.transfer:
                                ui.menu_item("移动采集项…", on_click=lambda _event=None, g=group, c=capture: self.transfer(g, c, "move"))
                                ui.menu_item("复制采集项…", on_click=lambda _event=None, g=group, c=capture: self.transfer(g, c, "copy"))
                            if self.delete_capture:
                                ui.menu_item("删除采集项", on_click=lambda _event=None, g=group, c=capture: self.remove_capture(g, c)).props("class=text-red-7")
            if metadata or self.update_capture or notes or preview:
                with ui.column().classes("tw-context-capture-details w-full gap-0"):
                    if metadata or self.update_capture:
                        with ui.row().classes("tw-context-capture-meta-row w-full items-center gap-2 flex-nowrap"):
                            if metadata:
                                ui.label(metadata).classes("tw-context-capture-meta grow min-w-0").tooltip(str(captured_at) if captured_at else metadata)
                            else:
                                ui.space()
                            if self.update_capture:
                                with ui.row().classes("tw-context-note-actions items-center gap-1"):
                                    ui.button("编辑说明", on_click=lambda: self.edit_capture_label(group, capture)).props("flat dense")
                    if notes:
                        ui.label(notes).classes("tw-context-staged-note-text w-full")
                    if preview:
                        ui.label(preview).classes("tw-context-capture-preview w-full text-xs text-gray-500")

    def capture_preview(self, capture):
        values = []
        for item in capture.get("items", [])[:3]:
            text = item.get("content") or item.get("text") or item.get("source") or item.get("url")
            if text:
                preview = str(text).strip().replace("\n", " ")
                values.append(str(redact({"preview": preview})["preview"]) if self.redact_on_display else preview)
        return " · ".join(values)[:260]

    async def edit_capture_label(self, group, capture):
        with ui.context.client.layout, ui.dialog() as dialog, ui.card().classes("w-full max-w-lg"):
            ui.label("编辑采集项").classes("text-lg font-medium")
            label = ui.input("采集项名称", value=capture.get("label", "")).classes("w-full")
            notes = ui.textarea("操作说明", value=capture.get("operation_notes", "")).props("rows=8 outlined").classes("w-full")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("取消", on_click=dialog.close).props("outline")
                async def save_label():
                    await self.update_capture(group, capture, label.value or "", operation_notes=notes.value or "")
                    if self.is_active() and not dialog.is_deleted: dialog.close()
                ui.button("保存", on_click=save_label).props("unelevated color=primary")
        dialog.open()

    async def remove_capture(self, group, capture):
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-lg"):
            ui.label(f'删除采集项“{capture.get("label") or "采集项"}”？')
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("取消", on_click=lambda: dialog.submit(False)).props("outline")
                ui.button("确认删除", on_click=lambda: dialog.submit(True)).props("outline color=negative")
        if await dialog and self.is_active():
            await self.delete_capture(group, capture)

    async def move_entry(self, entry, direction):
        if not self.move: return
        await self.move(entry, direction)
        if not self.is_active(): return
        index = self.entries.index(entry); other = index + (-1 if direction == "up" else 1)
        if 0 <= other < len(self.entries):
            self.entries[index], self.entries[other] = self.entries[other], self.entries[index]
            self.rebuild()

    async def remove(self, entry):
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-lg"):
            ui.label(f'删除上下文“{entry["name"]}”？').classes("text-lg font-medium")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("取消", on_click=lambda: dialog.submit(False)).props("outline")
                ui.button("确认删除", on_click=lambda: dialog.submit(True)).props("outline text-color=red-7")
        if not await dialog or not self.is_active(): return
        try:
            await self.delete(entry)
            if not self.is_active(): return
            if entry in self.entries: self.entries.remove(entry)
            self.rebuild()
        except Exception as exc:
            if self.is_active(): ui.notify(str(exc), type="negative")

    def sync_group(self, group):
        current = next((item for item in self.entries if item.get("context_id") == group.get("context_id")), None)
        if current: current.update(group)
        else: self.entries.append(group)
        self.rebuild()


class ContextTargetPicker:
    """NiceGUI controls bound to plain target/session selection."""

    def __init__(self, load, options=None, *, compact=False):
        from taskweave.presentation.collection_form import TargetSelection
        self.load = load
        self.interaction = TargetSelection(options)
        self.options = self.interaction.options
        self.updating_selection = False
        label_container = ui.context.slot.parent
        with ui.row().classes("tw-context-target-controls w-full items-center flex-nowrap gap-2"):
            self.select = ui.select({"": self.options["parameter_mode_label"]}, value="",
                label=self.options["selector_label"], with_input=True).classes("grow min-w-0")
            self.refresh_button = ui.button(icon="refresh", on_click=self.refresh).props(
                "outline dense aria-label=刷新上下文实例").classes("shrink-0").tooltip("刷新上下文实例")
        if compact:
            compact_field(self.select, label_container=label_container)
        self.select.on_value_change(self.selection_changed)
        self.note = ui.label().classes("text-xs text-gray-500")
        self.note.set_visibility(False)

    @property
    def targets(self): return self.interaction.targets
    @property
    def uses_parameters(self): return self.interaction.uses_parameters

    def selection_changed(self, event):
        if not self.updating_selection:
            self.interaction.select(event.value)

    def render_selection(self):
        self.updating_selection = True
        try:
            self.select.set_options({"": self.options['parameter_mode_label'],
                **{key: item['label'] for key, item in self.targets.items()}}, value=self.interaction.selected)
        finally:
            self.updating_selection = False
        self.note.text = self.interaction.note
        self.note.set_visibility(bool(self.interaction.note))
        self.select.set_enabled(not self.interaction.loading)

    async def refresh(self):
        revision, previous = self.interaction.begin()
        self.render_selection()
        try:
            result = await self.load()
            if self.select.is_deleted:
                self.interaction.invalidate()
                return
            if self.interaction.apply(revision, previous, result):
                self.render_selection()
        except Exception as exc:
            if not self.select.is_deleted and self.interaction.fail(revision, exc):
                self.render_selection()

    def selection(self):
        return self.interaction.selection()
