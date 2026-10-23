"""Home rendering depends on explicit queries and navigation/run actions."""
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from nicegui import ui
from taskweave.desktop.pages.base import Page


class HomeQueries(Protocol):
    async def call(self, api_operation: str, **params: object) -> list[dict] | dict: ...
    async def run_request(self, run_id: str) -> dict: ...


class HomeButton(Protocol):
    def __call__(self, title: str, callback: Callable[[], Awaitable[object]], *,
                 primary: bool = False, flat: bool = False, icon: str | None = None) -> ui.button: ...


@dataclass(frozen=True)
class HomeActions:
    navigate: Callable[[str], Awaitable[bool | None]]
    open_task: Callable[[dict], Awaitable[object]]
    create_task: Callable[[], Awaitable[object]]
    import_task: Callable[[], Awaitable[object]]
    new_plan: Callable[[], Awaitable[object]]
    new_execution: Callable[[], Awaitable[object]]
    task_execution: Callable[[str], Awaitable[object]]
    open_execution: Callable[[str], Awaitable[object]]
    resume_run: Callable[[dict, dict | None], Awaitable[object]]
    end_run: Callable[[dict], Awaitable[object]]
    reconcile_run: Callable[[dict, dict], Awaitable[object]]


class HomePage(Page):
    def __init__(self, queries: HomeQueries, *, actions: HomeActions, button: HomeButton,
                 page_identity: Callable[[], tuple[int, str]], status_labels: Mapping[str, str]):
        self.queries = queries
        self.actions = actions
        self.button = button
        self.page_identity = page_identity
        self.status_labels = status_labels

    async def render(self):
        home_identity = self.page_identity()

        def current_home():
            return home_identity == self.page_identity() and self.page_identity()[1] == "home"

        tasks = await self.queries.call("task.list")
        if not current_home():
            return
        runs = [run for run in await self.queries.call("run.list") if run.get("mode") == "EXECUTION"]
        if not current_home():
            return
        instances = await self.queries.call("run.instances")
        if not current_home():
            return
        categories = await self.queries.call("organization.category.list")
        if not current_home():
            return
        environments = await self.queries.call("environment.list")
        if not current_home():
            return

        def local_time(value):
            if not value:
                return None
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return parsed.astimezone()
            except (TypeError, ValueError):
                return None

        def short_time(value):
            parsed = local_time(value)
            return parsed.strftime("%m-%d %H:%M") if parsed else "尚未开始"

        now = datetime.now().astimezone()
        today_runs = [run for run in runs if (started := local_time(run.get("started_at"))) and started.date() == now.date()]
        recent_tasks = sorted(
            tasks,
            key=lambda task: task.get("updated_at") or task.get("created_at") or "",
            reverse=True,
        )[:4]
        recent_runs = list(reversed(runs))
        task_steps = {}
        for task in recent_tasks:
            task_steps[task["task_id"]] = await self.queries.call("step.list", task_id=task["task_id"])
            if not current_home():
                return
        task_names = {task["task_id"]: task["name"] for task in tasks}
        category_names = {item["category_id"]: item["name"] for item in categories}
        environment_names = {item["environment_id"]: item["name"] for item in environments}

        active_by_id = {}
        for run in instances:
            if run.get("mode") != "EXECUTION" or run.get("instance_type") not in {None, "execution"}:
                continue
            if run.get("status") in {"RUNNING", "PAUSED"} or run.get("can_end"):
                active_by_id[run["run_id"]] = run
        active_runs = list(active_by_id.values())

        details_by_id = {}
        for run in active_runs:
            details_by_id[run["run_id"]] = await self.queries.call("run.get", run_id=run["run_id"])
            if not current_home():
                return
        for run in runs:
            if run.get("status") in {"FAILED", "INTERRUPTED"} and run["run_id"] not in details_by_id:
                details_by_id[run["run_id"]] = await self.queries.call("run.get", run_id=run["run_id"])
                if not current_home():
                    return

        pending = []
        pending_seen = set()
        for run in details_by_id.values():
            if run.get("status") not in {"FAILED", "INTERRUPTED"}:
                continue
            for attempt in run.get("attempts", []):
                if attempt.get("valid") and (
                    attempt.get("status") == "UNKNOWN"
                    or attempt.get("status") == "FAILED" and attempt.get("effect_state") in {"UNKNOWN", "SUCCEEDED"}
                ):
                    key = (run["run_id"], attempt["attempt_id"])
                    if key not in pending_seen:
                        pending.append((run, attempt))
                        pending_seen.add(key)
        pending_run_ids = {run["run_id"] for run, _attempt in pending}
        recent_results = [
            run for run in recent_runs
            if run.get("status") in {"SUCCEEDED", "FAILED", "INTERRUPTED", "CANCELLED"}
            and run["run_id"] not in active_by_id and run["run_id"] not in pending_run_ids
        ][:5]

        with ui.row().classes("tw-home-heading w-full justify-between items-center flex-wrap gap-3"):
            with ui.column().classes("gap-1"):
                ui.label("工作台").classes("tw-page-title")
            self.button("新建执行", self.actions.new_execution, primary=True, icon="add")

        summary = (
            ("任务总数", len(tasks), "inventory_2", "本地任务", "blue"),
            ("活跃执行", len(active_runs), "play_circle_outline", "当前可操作实例", "green"),
            ("今日执行", len(today_runs), "calendar_today", "按本地日期统计", "purple"),
            ("待处理", len(pending), "inbox", "需要人工核对", "amber"),
        )
        with ui.row().classes("tw-home-stats w-full"):
            for label, value, icon, note, color in summary:
                with ui.row().classes("tw-home-stat tw-panel items-center"):
                    with ui.element("div").classes(f"tw-home-stat-icon tw-home-icon-{color}"):
                        ui.icon(icon, size="20px")
                    with ui.column().classes("gap-0 min-w-0"):
                        ui.label(label).classes("tw-home-stat-label")
                        ui.label(str(value)).classes("tw-home-stat-value")
                        ui.label(note).classes("tw-home-stat-note")

        with ui.row().classes("tw-home-grid w-full items-start"):
            recent_tasks_panel = ui.column().classes("tw-panel tw-home-panel min-w-0 gap-0")
            recent_results_panel = ui.column().classes("tw-panel tw-home-panel min-w-0 gap-0")
        with ui.row().classes("tw-home-bottom w-full items-start"):
            quick_start_panel = ui.column().classes("tw-panel tw-home-panel tw-home-quick gap-0")
            active_runs_panel = ui.column().classes("tw-panel tw-home-panel tw-home-runs min-w-0 gap-0")

        with recent_tasks_panel:
            with ui.row().classes("tw-section-heading w-full justify-between items-center"):
                ui.label("最近更新任务").classes("tw-section-title")
                self.button("查看全部", lambda: self.actions.navigate("tasks"), flat=True, icon="arrow_forward")
            for task in recent_tasks:
                steps = task_steps[task["task_id"]]
                can_execute = bool(steps) and all(step.get("validation_state") == "VALIDATED" for step in steps)
                with ui.row().classes("tw-home-task w-full items-center gap-3"):
                    with ui.element("div").classes("tw-home-task-icon"):
                        ui.icon("checklist", size="20px")
                    with ui.column().classes("tw-home-task-copy min-w-0 gap-1"):
                        ui.label(task["name"]).classes("tw-home-task-name")
                        description = task.get("description") or "暂无说明"
                        ui.label(description).classes("tw-home-task-description").tooltip(description)
                        with ui.row().classes("tw-home-task-meta items-center gap-2"):
                            ui.label(category_names.get(task.get("category_id"), "未分类")).classes("tw-home-tag")
                            ui.label(short_time(task.get("updated_at") or task.get("created_at")))
                    with ui.row().classes("tw-home-task-actions items-center gap-2"):
                        self.button("打开", lambda t=task: self.actions.open_task(t))
                        execute = self.button(
                            "新建执行", lambda tid=task["task_id"]: self.actions.task_execution(tid),
                            primary=True,
                        )
                        if not can_execute:
                            execute.disable()
                            execute.tooltip("所有步骤确认后才能创建执行")

        with active_runs_panel:
            with ui.row().classes("tw-section-heading w-full justify-between items-center"):
                ui.label("活跃执行").classes("tw-section-title")
                self.button("查看全部", lambda: self.actions.navigate("executions"), flat=True, icon="arrow_forward")
            if not active_runs and not pending:
                ui.label("暂无需要操作的活跃执行").classes("tw-home-empty")
            for run in active_runs[:4]:
                detail = details_by_id.get(run["run_id"], run)
                steps = task_steps.get(run["task_id"])
                if steps is None:
                    steps = await self.queries.call("step.list", task_id=run["task_id"])
                    task_steps[run["task_id"]] = steps
                    if not current_home():
                        return
                attempts = [item for item in detail.get("attempts", []) if item.get("valid")]
                completed = sum(item.get("status") == "SUCCEEDED" for item in attempts)
                total = len(steps)
                current_attempt = next((item for item in reversed(attempts) if item.get("status") != "SUCCEEDED"), None)
                current_step = next((item for item in steps if current_attempt and item["step_id"] == current_attempt.get("step_id")), None)
                if current_step is None and steps:
                    current_step = steps[min(completed, len(steps) - 1)]
                progress = min(1.0, completed / total) if total else 0.0
                request = None
                if run.get("status") == "PAUSED":
                    request = await self.queries.run_request(run["run_id"])
                    if not current_home():
                        return
                status_class = {
                    "RUNNING": "tw-status-running", "PAUSED": "tw-status-paused",
                    "FAILED": "tw-status-failed", "INTERRUPTED": "tw-status-interrupted",
                }.get(run.get("status"), "")
                with ui.column().classes("tw-home-run w-full gap-2"):
                    with ui.row().classes("tw-home-run-title w-full items-center justify-between gap-2"):
                        ui.label(task_names.get(run["task_id"], "已删除任务")).classes("tw-home-task-name min-w-0")
                        ui.label(self.status_labels.get(run["status"], run["status"])).classes(f"tw-status {status_class}")
                    with ui.element("div").classes("tw-home-progress"):
                        ui.element("div").style(f"width:{progress * 100:.1f}%")
                    with ui.row().classes("tw-home-run-footer w-full items-center justify-between gap-2"):
                        with ui.column().classes("tw-home-run-meta min-w-0 gap-1"):
                            current_name = current_step.get("name") if current_step else "步骤尚未建立"
                            ui.label(f"步骤 {min(completed + 1, total) if total else 0}/{total} · {current_name}")
                            env_name = environment_names.get(detail.get("environment_id"), "未指定环境")
                            ui.label(f"{env_name} · {short_time(run.get('started_at'))}")
                        with ui.row().classes("tw-home-task-actions items-center gap-2"):
                            if run.get("status") == "PAUSED" and request and request.get("waiting_input"):
                                self.button("填写输入", lambda rid=run["run_id"]: self.actions.open_execution(rid), primary=True)
                            elif run.get("status") == "PAUSED":
                                self.button("继续执行", lambda r=run, q=request: self.actions.resume_run(r, q), primary=True)
                            else:
                                self.button("查看", lambda rid=run["run_id"]: self.actions.open_execution(rid), primary=True)
                            if run.get("can_end", False):
                                self.button("结束", lambda r=run: self.actions.end_run(r), flat=True)
            if pending:
                with ui.row().classes("tw-home-pending-heading w-full items-center justify-between"):
                    ui.label("待核对结果").classes("tw-section-subtitle")
                    self.button("查看执行", lambda: self.actions.navigate("executions"), flat=True)
                for run, attempt in pending[:3]:
                    with ui.row().classes("tw-home-pending w-full items-center justify-between gap-3"):
                        with ui.column().classes("min-w-0 gap-1"):
                            label = task_names.get(run["task_id"], "已删除任务") + " · " + attempt.get("step_name", "步骤结果待核对")
                            ui.label(label).classes("tw-home-task-name")
                            ui.label(attempt.get("error_summary") or "外部业务结果尚未确认").classes("tw-home-task-description")
                        with ui.row().classes("tw-home-task-actions items-center gap-2"):
                            self.button("核对结果", lambda r=run, a=attempt: self.actions.reconcile_run(r, a), primary=True)
                            if run.get("can_end", False):
                                self.button("结束", lambda r=run: self.actions.end_run(r), flat=True)

        with recent_results_panel:
            with ui.row().classes("tw-section-heading w-full justify-between items-center"):
                ui.label("最近执行结果").classes("tw-section-title")
                self.button("全部记录", lambda: self.actions.navigate("executions"), flat=True, icon="arrow_forward")
            result_rows = []
            for run in recent_results:
                if run.get("run_id") not in details_by_id:
                    details_by_id[run["run_id"]] = await self.queries.call("run.get", run_id=run["run_id"])
                    if not current_home():
                        return
                result = details_by_id[run["run_id"]]
                summaries = result.get("results") or []
                result_summary = f"{len(summaries)} 项结果" if summaries else self.status_labels.get(run["status"], run["status"])
                result_rows.append({
                    "run_id": run["run_id"],
                    "task": task_names.get(run["task_id"], "已删除任务"),
                    "time": short_time(run.get("finished_at") or run.get("started_at")),
                    "status": self.status_labels.get(run["status"], run["status"]),
                    "summary": result_summary,
                })
            if result_rows:
                columns = [
                    {"name": "task", "label": "任务名称", "field": "task", "align": "left"},
                    {"name": "time", "label": "执行时间", "field": "time", "align": "left"},
                    {"name": "status", "label": "状态", "field": "status", "align": "left"},
                    {"name": "summary", "label": "结果摘要", "field": "summary", "align": "left"},
                ]
                ui.table(columns=columns, rows=result_rows, row_key="run_id").props("flat").classes("tw-home-results w-full")
            else:
                ui.label("暂无已完成结果").classes("tw-home-empty")

        with quick_start_panel:
            with ui.row().classes("tw-section-heading w-full justify-between items-center"):
                ui.label("快速开始").classes("tw-section-title")
                ui.icon("bolt", size="19px").classes("text-blue-400")
            with ui.grid(columns=2).classes("tw-home-quick-grid w-full"):
                self.button("新建规划", self.actions.new_plan, icon="assignment")
                self.button("新建任务", self.actions.create_task, icon="add_box")
                self.button("导入任务", self.actions.import_task, icon="file_upload")
                self.button("新建执行", self.actions.new_execution, icon="play_arrow")
