"""Trial history page and its run detail dialog."""

import json
from nicegui import ui
from taskweave.desktop.pages.base import Page
from taskweave.desktop.display import execution_title, readable_metadata, step_names


STATUS = {
    "DRAFT": "草稿", "VALIDATED": "已验证", "READY": "就绪", "RUNNING": "执行中",
    "PAUSED": "已暂停", "FAILED": "失败", "INTERRUPTED": "中断 / 待核对",
    "SUCCEEDED": "成功", "CANCELLED": "已结束", "UNKNOWN": "结果待核对",
}


def _document_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


class HistoryPage(Page):
    def __init__(self, controller, task_id, button, result_dialog, error_dialog, *, identity=None):
        self.controller = controller
        self.task_id = task_id
        self.button = button
        self.result_dialog = result_dialog
        self.error_dialog = error_dialog
        self.identity = identity or (lambda: None)

    async def render(self, mode="TRIAL"):
        task_id = self.task_id
        identity = self.identity()
        def current():
            return task_id == self.task_id and (identity is None or identity == self.identity())

        ui.label("本任务调试历史" if mode == "TRIAL" else "本任务执行历史").classes("text-xl")
        all_runs = await self.controller.call("run.list", task_id=task_id)
        if not current():
            return
        runs = [run for run in all_runs if run["mode"] == mode]
        if not runs:
            ui.label("暂无调试记录。" if mode == "TRIAL" else "暂无正式执行记录。").classes("tw-panel")
        fallback = await self.controller.call("step.list", task_id=task_id)
        if not current():
            return
        for run in reversed(runs):
            with ui.row().classes("tw-panel w-full items-center justify-between"):
                ui.label(f"{run['started_at'] or '未开始'} · {'调试' if mode == 'TRIAL' else '正式执行'} · {STATUS[run['status']]}")

                async def details(r=run):
                    value = await self.controller.call("run.get", run_id=r["run_id"])
                    if not current():
                        return
                    with ui.dialog() as dialog, ui.card().classes("w-full max-w-4xl"):
                        ui.label("历史执行详情 · " + execution_title(r))
                        names = step_names(value, fallback)
                        snapshot = json.loads(value["definition_json"]) if value["definition_json"] else None
                        if snapshot:
                            ui.label("执行时任务：" + snapshot["task"]["name"])
                        for attempt in value["attempts"]:
                            title = f"{names.get(attempt['step_id'], '未知步骤')} · 尝试 {attempt['attempt_no']} · {STATUS[attempt['status']]}"
                            icon = "check_circle" if attempt["status"] == "SUCCEEDED" else "error" if attempt["status"] in {"FAILED", "UNKNOWN"} else "radio_button_unchecked"
                            with ui.expansion(title, icon=icon).classes("w-full"):
                                with ui.row().classes("w-full justify-end gap-2"):
                                    result_step = {"step_id": attempt["step_id"], "task_id": value["task_id"], "name": names.get(attempt["step_id"], "步骤")}
                                    if any(ref["attempt_id"] == attempt["attempt_id"] for ref in value["results"]):
                                        self.button("查看结果", lambda r=value, st=result_step, aid=attempt["attempt_id"]: self.result_dialog(r, st, aid))
                                    if attempt["status"] in {"FAILED", "UNKNOWN"}:
                                        self.button("查看错误", lambda a=attempt, st=result_step: self.error_dialog(a, st))
                                ui.code(_document_text(readable_metadata(attempt, names)), language="json").classes("w-full")
                        events = await self.controller.call("run.events", run_id=r["run_id"])
                        if not current():
                            dialog.delete()
                            return
                        ui.code(_document_text(readable_metadata(events, names)), language="json").classes("w-full")
                        ui.button("关闭", on_click=dialog.close)
                    dialog.open()

                self.button("查看记录", details)
