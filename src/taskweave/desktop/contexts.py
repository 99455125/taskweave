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


async def show_context_preview(title, capture, renderers, render_result, *,
                               redact_on_display=True, is_active=lambda: True,
                               register_dialog=None):
    """Read-only evidence preview for saved and staged captures."""
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
        with ui.row().classes("tw-context-preview-footer w-full items-center justify-end gap-3"):
            ui.button("关闭", on_click=dialog.close).props("outline")
    if is_active():
        dialog.open()
    return dialog


def render_preview_attachments(exported):
    import base64
    for item in exported.get("attachments", []):
        ui.button("下载图片 · " + item["title"], icon="download",
                  on_click=lambda _e=None, value=item: ui.download.content(
                      base64.b64decode(value["data"]), filename=value["name"],
                      media_type=value["mime_type"])).props("flat dense")


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
                    ui.button("预览", icon="visibility", on_click=lambda: preview(entry)).props("flat dense")
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
                with ui.row().classes("w-full items-start gap-2 flex-nowrap"):
                    ui.label(capture.get("operation_notes") or "").classes("tw-context-staged-note-text")
                    ui.button("编辑说明", on_click=lambda: self.edit_capture_label(group, capture)).props("flat dense")
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
                ui.checkbox("携带预览", value=bool(capture.get("send_preview")),
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
