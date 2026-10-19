"""Plan page: collect plugin evidence and turn a validated candidate into a task."""

import json
import logging
from datetime import datetime
from nicegui import ui

logger = logging.getLogger("taskweave.desktop.planning")

GENERATION_CHANNEL_LABELS = {"api": "大模型 API", "web_chat": "网页 Chat"}
GENERATION_STATUS_LABELS = {
    "GENERATING": "生成中", "READY": "待导入", "IMPORTED": "已导入",
    "FAILED": "生成失败", "PARSE_FAILED": "解析失败", "BLOCKED": "信息不足",
}


def generation_summary(generation):
    """Return the latest candidate's display data without promoting an older result."""
    if not generation:
        return None
    candidate = generation.get("candidate")
    can_import = generation.get("status") in {"READY", "IMPORTED"} and bool(candidate)
    steps = candidate.get("steps", []) if can_import else []
    documents = [item.get("document", item) for item in steps]
    return {
        "generation_id": generation["generation_id"],
        "created_at": short_updated_at(generation.get("created_at")),
        "channel": GENERATION_CHANNEL_LABELS.get(generation.get("channel"), "未知渠道"),
        "status": GENERATION_STATUS_LABELS.get(generation.get("status"), "未就绪"),
        "status_code": generation.get("status"),
        "can_import": can_import,
        "name": (candidate.get("task", {}).get("name") if can_import else None),
        "step_count": len(documents),
        "steps": [{"index": index, "name": step.get("name", "未命名步骤")} for index, step in enumerate(documents[:3], 1)],
        "diagnostics": [
            " · ".join(str(item[key]) for key in ("code", "message") if item.get(key)) if isinstance(item, dict) else str(item)
            for item in generation.get("diagnostics", [])
        ],
    }


def short_updated_at(value):
    if not value:
        return "尚未更新"
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone().strftime("%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return str(value)[:16]



def candidate_step_rows(candidate, context_labels):
    refs = candidate.get("plan_context_refs", {})
    return [{
        "index": index,
        "document": entry["document"],
        "status": "待调试" if entry["document"]["step_content"].strip() else "待编写",
        "context_names": [context_labels.get(context_id, context_id) for context_id in refs.get(entry["key"], [])],
    } for index, entry in enumerate(candidate["steps"], 1)]


class PlanningGenerationView:
    """Candidate dialogs and generation history presentation."""

    async def generate(self, plan, channel):
        identity = self._planning_identity()
        if plan["plan_id"] != identity[0] or not self._identity_is_current(identity):
            return None
        try:
            action = await self.interaction.generate_action(plan, channel)
            result = action.value
        except Exception:
            await self._refresh_failed_generation(identity)
            raise
        await self._refresh_candidate_action(action)
        if not self.interaction.effects(action):
            return result
        if 'web_chat' in self.interaction.effects(action):
            with ui.dialog() as dialog, ui.card().classes("tw-plan-web-dialog w-full max-w-5xl"):
                ui.label("大模型网页chat调用").classes("text-lg font-medium")
                ui.label(f'请求大小：{result["request_size_bytes"] / 1024:.1f} KB / {result["request_limit_bytes"] / 1024:.0f} KB').classes("text-gray-500")
                from taskweave.desktop.contexts import render_preview_attachments
                render_preview_attachments(result)
                prompt = ui.textarea("完整提示词", value=result["prompt"]).props("readonly").classes("tw-plan-prompt w-full")
                response = ui.textarea("粘贴网页回复 JSON").classes("tw-plan-response w-full")
                async def parse():
                    await self.parse_generation(result["generation_id"], response.value or "", identity, dialog.close)
                async def copy_prompt():
                    await self.controller.copy_text(result["prompt"])
                    ui.notify("完整提示词已复制")
                async def download_prompt():
                    if self.controller.native:
                        path = await self.controller.save_plan_prompt(result["prompt"])
                        ui.notify("提示词已保存：" + str(path), timeout=8000)
                    else:
                        ui.download.content(result["prompt"], filename=f'taskweave-plan-{result["generation_id"]}.txt', media_type="application/octet-stream")
                with ui.row().classes("gap-2 flex-wrap"):
                    self.button("复制提示词", copy_prompt)
                    self.button("下载提示词", download_prompt)
                    self.button("解析并预览", parse, primary=True)
                    ui.button("关闭", on_click=dialog.close).props("outline")
            dialog.open()
        else:
            await self.preview(result, identity)

    async def _refresh_candidate_action(self, action, refresh_receipts=None):
        callbacks = {'receipts': refresh_receipts,
                     'history': self._refresh_generation_history,
                     'summary': self._refresh_candidate_summary}
        for effect in ('receipts', 'history', 'summary'):
            self._planning_identity()
            if effect not in self.interaction.effects(action):
                continue
            callback = callbacks[effect]
            if callback:
                await callback() if effect == 'receipts' else await callback(action.identity)
        self._planning_identity()

    async def parse_generation(self, generation_id, response_text, identity, close_dialog=None):
        try:
            action = await self.interaction.parse_action(generation_id, response_text, identity)
        except Exception:
            await self._refresh_failed_generation(identity)
            raise
        await self._refresh_candidate_action(action)
        if close_dialog:
            close_dialog()
        if 'preview' not in self.interaction.effects(action):
            return None
        await self.preview(action.value, identity)
        return action.value

    async def _refresh_failed_generation(self, identity):
        """Refresh diagnostics after failure without hiding the original error."""
        try:
            await self._refresh_candidate_action(self.interaction.failed_action(identity))
        except Exception:
            logger.warning("Could not refresh plan generation history after a failed operation", exc_info=True)

    async def preview(self, generation, identity=None):
        identity = identity or self._planning_identity()
        if not self._identity_is_current(identity):
            return
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-5xl"):
            ui.label("任务候选预览").classes("text-lg font-medium")
            if generation["status"] not in {"READY", "IMPORTED"} or not generation.get("candidate"):
                ui.label("尚不能导入：" + json.dumps(generation.get("diagnostics", []), ensure_ascii=False)).classes("text-red-700")
            else:
                receipt_rows = ui.column().classes("w-full gap-1")

                async def refresh_receipts():
                    receipt_rows.clear()
                    rows = await self.interaction.imports(generation["generation_id"])
                    with receipt_rows:
                        ui.label("已导入任务").classes("font-medium")
                        for receipt in rows:
                            ui.label(f'{receipt["imported_at"]} · {receipt["task_id"]}').classes("text-sm text-gray-600")

                await refresh_receipts()
                package = generation["candidate"]
                ui.label(package["task"]["name"])
                if generation.get("context_labels") and not package.get("plan_context_refs"):
                    ui.label("尚未关联规划上下文；导入后可在步骤中重新采集").classes("text-amber-800")
                rows = candidate_step_rows(package, generation.get("context_labels", {}))
                unwritten = sum(row["status"] == "待编写" for row in rows)
                if unwritten:
                    ui.label(f"{unwritten} 个步骤待编写，可导入后补充上下文并调试").classes("text-amber-800")
                for row in rows:
                    step = row["document"]
                    with ui.expansion(f'{row["index"]}. {step["name"]} · {row["status"]}').classes("w-full"):
                        ui.label(step["step_description"])
                        if step["step_notes"]:
                            ui.label(step["step_notes"]).classes("whitespace-pre-wrap text-gray-700")
                        if row["context_names"]:
                            ui.label("关联上下文：" + "、".join(row["context_names"])).classes("text-sm text-gray-600")
                        if step["step_content"].strip():
                            ui.code(step["step_content"], language="python").classes("w-full")
                async def import_task():
                    await self.import_generation(generation["generation_id"], identity, refresh_receipts)
                self.button("导入为任务", import_task, primary=True)
            ui.button("关闭", on_click=dialog.close).props("outline")
        dialog.open()

    async def import_generation(self, generation_id, identity, refresh_receipts=None):
        action = await self.interaction.import_action(generation_id, identity)
        await self._refresh_candidate_action(action, refresh_receipts)
        if 'notify' in self.interaction.effects(action):
            ui.notify("已创建新任务：" + action.value["task_id"], type="positive")
        return action.value

    async def open_generation(self, generation_id, identity=None):
        identity = identity or self._planning_identity()
        self._planning_identity()
        action = await self.interaction.select_action(generation_id, identity)
        self._planning_identity()
        if 'preview' in self.interaction.effects(action):
            await self.preview(action.value, identity)
