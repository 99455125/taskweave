"""Shared context cards and plugin-owned collection target selection."""

import asyncio
from datetime import datetime
import json

from nicegui import ui
from taskweave.core.context_collection import capture_ai_payload

from taskweave.core.validation import TaskError
from taskweave.infrastructure.privacy import redact, redact_collected_context


async def show_context_preview(title, capture, renderers, render_result, *,
                               redact_on_display=True, is_active=lambda: True,
                               register_dialog=None):
    """One read-only preview for saved and staged planning/step captures."""
    visible = redact_collected_context(capture, renderers) if redact_on_display else capture
    views, items = visible.get("views", []), visible.get("items", [])
    with ui.dialog() as dialog, ui.card().classes("tw-context-preview-dialog"):
        if register_dialog:
            register_dialog(dialog)
        with ui.row().classes("tw-context-preview-header w-full items-center justify-between"):
            with ui.column().classes("gap-1 min-w-0 flex-1"):
                ui.label(title or "采集项").classes("text-lg font-semibold break-words")
                ui.label("采集内容预览").classes("text-xs text-gray-500")
            ui.button(icon="close", on_click=dialog.close).props("flat round dense aria-label=关闭预览")
        with ui.column().classes("tw-context-preview-body w-full"):
            for view in views:
                with ui.column().classes("tw-context-preview-media w-full gap-2"):
                    ui.label(view.get("title") or "预览").classes("text-sm font-medium")
                    kind = renderers.get(view["renderer"], {}).get("type", "json")
                    try:
                        await render_result(kind, view["data"], {})
                    except ValueError as exc:
                        ui.label(str(exc)).classes("text-red-700")
                    if not is_active():
                        dialog.close()
                        return dialog
            if items:
                with ui.expansion("原始采集数据", icon="data_object", value=not bool(views)).classes("tw-context-raw w-full"):
                    ui.code(json.dumps(items, ensure_ascii=False, indent=2), language="json").classes("w-full tw-code")
            if not views and not items:
                ui.label("暂无可预览的内容").classes("text-gray-500")
        with ui.row().classes("tw-context-preview-footer w-full justify-end"):
            ui.button("关闭", on_click=dialog.close).props("outline")
    if is_active():
        dialog.open()
    return dialog


def edit_draft_notes(entry, refresh):
    with ui.context.client.layout:
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-2xl"):
            ui.label("编辑采集项").classes("text-lg font-semibold")
            title = ui.input("标题", value=entry.get("label", "")).classes("w-full")
            notes = ui.textarea("操作说明", value=entry.get("operation_notes", "")).classes("w-full").props("rows=8 outlined")
            def save():
                entry.update(label=title.value or "", operation_notes=notes.value or "")
                refresh()
                dialog.close()
            with ui.row().classes("w-full justify-end"):
                ui.button("取消", on_click=dialog.close).props("flat")
                ui.button("保存", on_click=save)
    dialog.open()


def render_preview_attachments(exported):
    import base64
    for item in exported.get("attachments", []):
        ui.button("下载图片 · " + item["title"], icon="download",
                  on_click=lambda _e=None, value=item: ui.download.content(
                      base64.b64decode(value["data"]), filename=value["name"],
                      media_type=value["mime_type"])).props("flat dense")
    if exported.get("attachments"):
        ui.label("请将这些图片与提示词一起上传到网页 Chat。").classes("text-sm text-gray-500")


def render_context_draft_rows(draft, preview, refresh):
    """Shared presentation for modal-only captures; mutations stay in the draft."""
    if not draft.entries:
        ui.label("当前没有保留项；已有组可以保存为空组。").classes("tw-context-empty w-full text-sm text-gray-500")
    for index, entry in enumerate(draft.entries):
        with ui.row().classes("tw-context-staged-row w-full items-center gap-2 flex-wrap"):
            ui.label(str(index + 1)).classes("tw-context-index")
            label = ui.input("采集项标题", value=entry.get("label") or f"采集 {index + 1}").props("dense outlined").classes("tw-context-staged-label")
            label.on_value_change(lambda event, item=entry: item.update(label=event.value or ""))
            captured_at = entry.get("captured_at")
            saved_time = context_capture_time(captured_at)
            status = "本次新采集" if entry.get("is_new") else (f"已保存 · {saved_time}" if saved_time else "已保存")
            ui.label(status).classes("tw-context-capture-meta").tooltip(str(captured_at) if captured_at else status)
            ui.button("预览", icon="visibility", on_click=lambda _event=None, item=entry: preview(item)).props("flat dense")
            ui.button((entry.get("operation_notes") or "＋ 添加操作说明")[:60],
                      on_click=lambda _e=None, item=entry: edit_draft_notes(item, refresh)).props("flat dense").classes("w-full justify-start")
            ui.checkbox("发送上下文预览给 AI", value=bool(entry.get("send_preview")),
                        on_change=lambda event, item=entry: item.update(send_preview=event.value)).set_enabled(
                            bool(entry.get("has_preview") or entry.get("capture", {}).get("views")))
            with ui.button(icon="more_horiz").props("flat dense aria-label=暂存采集项更多"):
                with ui.menu():
                    ui.menu_item("上移", on_click=lambda _event=None, item=entry: (draft.move(item, "up"), refresh())).set_enabled(index > 0)
                    ui.menu_item("下移", on_click=lambda _event=None, item=entry: (draft.move(item, "down"), refresh())).set_enabled(index < len(draft.entries) - 1)
                    ui.menu_item("删除采集项", on_click=lambda _event=None, item=entry: (draft.remove(item), refresh())).props("class=text-red-7")


def context_capture_time(value):
    if not value:
        return ""
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone().strftime("%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return ""


class ContextCaptureDraft:
    """Mutable modal-only ordering and tombstones for one context group."""

    def __init__(self, captures=()):
        self.entries = [{"capture_id": item["capture_id"], "label": item.get("label", ""), "original_label": item.get("label", ""),
                         "captured_at": item.get("captured_at"), "source_page": item.get("source_page"),
                         "operation_notes": item.get("operation_notes", ""), "send_preview": bool(item.get("send_preview")),
                         "original_notes": item.get("operation_notes", ""), "original_send": bool(item.get("send_preview")),
                         "has_preview": bool(item.get("has_preview") or item.get("views")),
                         "is_new": False} for item in captures]
        self.original_order = tuple(item['capture_id'] for item in self.entries)
        self.deleted = []

    @property
    def dirty(self):
        order = tuple(item['capture_id'] for item in self.entries if not item.get('is_new'))
        return bool(self.deleted or order != self.original_order or any(item.get("operation_notes", "") != item.get("original_notes", "") or bool(item.get("send_preview")) != bool(item.get("original_send")) or item.get("is_new") or item.get("label") != item.get("original_label", item.get("label")) for item in self.entries))

    def append(self, capture, request, include_view, source_session_id=None, source_page="planning", label=""):
        if not capture.get("items") and not capture.get("views"):
            raise TaskError("CONTEXT_EMPTY", "插件没有返回上下文内容或预览")
        item = {"capture": capture, "request": request or {}, "include_view": include_view,
                "source_session_id": source_session_id, "source_page": source_page,
                "captured_at": datetime.now().astimezone().isoformat(timespec='seconds'),
                "label": label, "operation_notes": "", "send_preview": False, "is_new": True}
        self.entries.append(item)
        return item

    def remove(self, item):
        index = self.entries.index(item)
        if not item.get('is_new'):
            item['_before_item'] = self.entries[index - 1] if index else None
            item['_after_item'] = self.entries[index + 1] if index + 1 < len(self.entries) else None
            item['_delete_index'] = index
        self.entries.remove(item)
        if not item.get("is_new"):
            self.deleted.append(item)

    def undo_delete(self, item):
        self.deleted.remove(item)
        after_item, before_item = item.pop('_after_item', None), item.pop('_before_item', None)
        delete_index = item.pop('_delete_index', len(self.entries))
        after_index = next((index for index, entry in enumerate(self.entries) if entry is after_item), None)
        before_index = next((index for index, entry in enumerate(self.entries) if entry is before_item), None)
        if after_index is not None:
            index = after_index
        elif before_index is not None:
            index = before_index + 1
        else:
            index = min(delete_index, len(self.entries))
        self.entries.insert(index, item)

    def move(self, item, direction):
        index = self.entries.index(item)
        other = index + (-1 if direction == "up" else 1)
        if 0 <= other < len(self.entries):
            self.entries[index], self.entries[other] = self.entries[other], self.entries[index]

    def payload(self):
        return [{key: item[key] for key in ("capture_id", "label", "operation_notes", "send_preview")} if not item.get("is_new") else
                {key: item[key] for key in ("capture", "request", "include_view", "source_session_id", "source_page", "captured_at", "label", "operation_notes", "send_preview")}
                for item in self.entries]


def context_target_options(request_schema):
    """Return plugin-owned target picker behavior, or None for plain forms."""
    options = request_schema.get("x-taskweave-context-targets")
    if not isinstance(options, dict):
        return None
    return {
        "selector_label": options.get("selector_label", "上下文实例"),
        "parameter_mode_label": options.get("parameter_mode_label", "使用插件参数"),
        "auto_select_single": bool(options.get("auto_select_single", False)),
        "hide_parameters_when_selected": bool(
            options.get("hide_parameters_when_selected", False)
        ),
        "keep_parameters_when_selected": tuple(options.get("keep_parameters_when_selected", ())),
    }


def context_hidden_parameters(request_schema, target_selected):
    """Return form fields supplied by a selected target rather than by the user."""
    if not target_selected:
        return set()
    options = context_target_options(request_schema)
    if not options or not options["hide_parameters_when_selected"]:
        return set()
    properties = request_schema.get("properties", {})
    return set(properties) - set(options["keep_parameters_when_selected"])


def context_view_default(request_schema):
    options = request_schema.get("x-taskweave-context-view")
    return bool(options.get("default", True)) if isinstance(options, dict) else None


def context_surface_defaults(request_schema, surface):
    """Plugin-provided form defaults for a specific authoring surface."""
    surfaces = request_schema.get("x-taskweave-context-surface-defaults", {})
    values = surfaces.get(surface, {}) if isinstance(surfaces, dict) else {}
    properties = request_schema.get("properties", {})
    return {key: value for key, value in values.items() if key in properties} if isinstance(values, dict) else {}


def context_advanced_overrides(request_schema, request):
    """Return persisted plugin parameters that have no generated form control."""
    properties = request_schema.get("properties", {})
    known = set(properties) if isinstance(properties, dict) else set()
    return {
        key: value for key, value in (request or {}).items()
        if key not in known and key != "target_id"
    }


def merge_context_request(form_values, advanced_overrides, target_request=None):
    """Merge plugin form, advanced and selected-target values in UI precedence order."""
    from taskweave.core.validation import TaskError

    if not isinstance(advanced_overrides, dict):
        raise TaskError("FORM_INVALID", "高级参数需要 JSON 对象")
    request = dict(form_values)
    request.update(advanced_overrides)
    request.update(target_request or {})
    return request


def context_ai_items(entries, renderers=None):
    """Preserve group and capture order while keeping plugin items intact."""
    groups=[{
        "context_id": group["context_id"], "provider_id": group["provider_id"],
        "name": group["name"], "context_notes": group.get("context_notes", ""),
        "order_index": group.get("order_index", order),
        "captures": [capture_ai_payload(capture, index, renderers or {})
                     for index, capture in enumerate(group.get("captures", []))
                     if capture.get("items") or (capture.get("send_preview") and capture.get("views"))],
    } for order, group in enumerate(entries) if any(c.get("items") or (c.get("send_preview") and c.get("views")) for c in group.get("captures", []))]

    if groups or not entries:
        return groups
    # In-memory callers may pass a newly collected response before refreshing summaries.
    return [{**item,"context_name":group['name'],"context_notes":group.get('context_notes',''),"order_index":group.get('order_index',index)} for index,group in enumerate(entries) for item in (group.get('item') if isinstance(group.get('item'),list) else [group.get('item')]) if item]


class ContextCards:
    """Compact, shared context-group and capture rows for planning and steps."""

    def __init__(self, entries, save, delete, move=None, recollect=None, preview=None,
                 append=None, delete_capture=None, move_capture=None, update_capture=None,
                 preview_capture=None, redact_on_display=True, is_active=None, expanded=None):
        self.entries, self.save, self.delete = entries, save, delete
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
            with ui.row().classes("w-full items-center justify-between"):
                ui.button("编辑组说明", on_click=lambda: self.edit_group(entry)).props("flat dense")
                if self.recollect:
                    ui.button("继续采集", on_click=lambda: self.recollect(entry)).props("flat dense")
                with ui.button(icon="more_horiz").props("flat dense aria-label=上下文组更多"):
                    with ui.menu():
                        if self.move:
                            ui.menu_item("上移上下文", on_click=lambda: self.move_entry(entry, "up")).set_enabled(index > 1)
                            ui.menu_item("下移上下文", on_click=lambda: self.move_entry(entry, "down")).set_enabled(index < len(self.entries))
                        ui.menu_item("删除上下文", on_click=lambda: self.remove(entry)).props("class=text-red-7")
            ui.label(entry.get("context_notes") or "暂无组说明").classes("tw-context-notes w-full text-sm text-gray-600")
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
        with ui.row().classes("tw-context-capture-row w-full items-center gap-2 flex-wrap"):
            title = capture.get("label") or f"采集 {index}"
            ui.label(f"{index}.").classes("tw-context-capture-index shrink-0")
            ui.label(title).classes("tw-context-capture-name min-w-0 grow").tooltip(title)
            captured_at = capture.get("captured_at")
            readable_time = context_capture_time(captured_at)
            source_name = {"draft":"步骤采集", "planning":"规划采集", "planning_import":"规划导入"}.get(capture.get("source_page"), "")
            metadata = " · ".join(value for value in (readable_time, source_name) if value) or "已采集"
            ui.label(metadata).classes("tw-context-capture-meta shrink-0").tooltip(str(captured_at) if captured_at else metadata)
            with ui.row().classes("tw-context-capture-actions gap-1 flex-wrap"):
                if self.preview_capture:
                    ui.button("内容 / 预览", on_click=lambda _event=None, g=group, c=capture: self.preview_capture(g, c)).props("flat dense icon=visibility")
                with ui.button(icon="more_horiz").props("flat dense aria-label=采集项更多"):
                    with ui.menu():
                        if self.update_capture:
                            ui.menu_item("改名", on_click=lambda _event=None, g=group, c=capture: self.edit_capture_label(g, c))
                        if self.move_capture:
                            ui.menu_item("上移", on_click=lambda _event=None, g=group, c=capture: self.move_capture(g, c, "up")).set_enabled(index > 1)
                            ui.menu_item("下移", on_click=lambda _event=None, g=group, c=capture: self.move_capture(g, c, "down")).set_enabled(index < count)
                        if self.delete_capture:
                            ui.menu_item("删除采集项", on_click=lambda _event=None, g=group, c=capture: self.remove_capture(g, c)).props("class=text-red-7")
            if self.update_capture:
                ui.button((capture.get("operation_notes") or "＋ 添加操作说明")[:80],
                          on_click=lambda: self.edit_capture_label(group, capture)).props("flat dense").classes("tw-capture-notes-button w-full")
                async def toggle_preview(event):
                    if event.value == bool(capture.get("send_preview")):
                        return
                    event.sender.disable()
                    try:
                        await self.update_capture(group, capture, title, send_preview=event.value)
                        capture["send_preview"] = event.value
                    except Exception as exc:
                        if self.is_active():
                            event.sender.set_value(bool(capture.get("send_preview")))
                            ui.notify(str(exc), type="negative")
                    finally:
                        if not event.sender.is_deleted:
                            event.sender.enable()
                ui.checkbox("发送上下文预览给 AI", value=bool(capture.get("send_preview")),
                            on_change=toggle_preview).set_enabled(bool(capture.get("has_preview") or capture.get("views")))
            preview = self.capture_preview(capture)
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
                ui.button("确认删除", on_click=lambda: dialog.submit(True)).props("text-color=red-7")
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
    """The host only renders labels and forwards opaque plugin request fields."""

    def __init__(self, load, options=None):
        self.load, self.targets, self.session_id = load, {}, None
        self.options = options or {
            "selector_label": "上下文实例",
            "parameter_mode_label": "使用插件参数",
            "auto_select_single": False,
            "hide_parameters_when_selected": False,
        }
        self.auto_selected_id = None
        self.updating_selection = False
        self.revision = 0
        self.loading, self.error = False, False
        with ui.row().classes("w-full items-center flex-nowrap gap-2"):
            self.select = ui.select(
                {"": self.options["parameter_mode_label"]},
                value="",
                label=self.options["selector_label"],
                with_input=True,
            ).classes("grow min-w-0")
            self.refresh_button = ui.button(icon="refresh", on_click=self.refresh).props(
                "outline dense aria-label=刷新上下文实例"
            ).classes("shrink-0").tooltip("刷新上下文实例")
        self.select.on_value_change(self.selection_changed)
        self.note = ui.label().classes("text-xs text-gray-500")
        self.note.set_visibility(False)

    def show_note(self, message):
        self.note.text = message
        self.note.set_visibility(bool(message))

    def selection_changed(self):
        if not self.updating_selection:
            self.auto_selected_id = None

    @property
    def uses_parameters(self):
        return self.select.value not in self.targets

    async def refresh(self):
        self.revision += 1
        revision = self.revision
        previous = self.select.value
        if previous == self.auto_selected_id:
            previous = ""
        self.auto_selected_id = None
        self.loading, self.error = True, False
        self.select.disable()
        self.targets, self.session_id = {}, None
        manual_label = self.options["parameter_mode_label"]
        self.updating_selection = True
        self.select.set_options({"": manual_label}, value="")
        self.updating_selection = False
        self.show_note("正在读取实例…")
        try:
            result = await self.load()
            if revision != self.revision or self.select.is_deleted:
                return
            self.targets = {target["target_id"]: target for target in result["targets"]}
            self.session_id = result["session_id"]
            options = {"": manual_label, **{key: item["label"] for key, item in self.targets.items()}}
            selected = previous if previous in self.targets else ""
            if not selected and self.options["auto_select_single"] and len(self.targets) == 1:
                selected = next(iter(self.targets))
                self.auto_selected_id = selected
            self.updating_selection = True
            self.select.set_options(options, value=selected)
            self.updating_selection = False
            if previous and previous not in self.targets:
                self.show_note("原实例已不可用，请重新选择。")
            else:
                self.show_note("")
        except Exception as exc:
            if revision == self.revision:
                self.error = True
                self.show_note(f"实例读取失败，请刷新重试：{exc}")
        finally:
            if revision == self.revision and not self.select.is_deleted:
                self.loading = False
                self.select.enable()

    def selection(self):
        if self.loading or self.error:
            raise TaskError("FORM_INVALID", "请等待实例列表加载完成，或刷新重试")
        target = self.targets.get(self.select.value)
        return (dict(target["request"]), self.session_id) if target else ({}, None)
