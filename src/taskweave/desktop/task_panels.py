"""Narrow view adapters used by the task page; never passed into interaction code."""
from dataclasses import dataclass
from typing import Awaitable, Callable

Render = Callable[[], Awaitable[object]]
TaskAction = Callable[[str], Awaitable[object]]


@dataclass(frozen=True)
class TaskEditorPanel:
    render: Render
    save: Render
    prepare_leave: Callable[[], Awaitable[str]] | None
    discard_for_tab: Callable[[str], Awaitable[object]] | None
    create_first: TaskAction | None


@dataclass(frozen=True)
class TaskHistoryPanels:
    execution: TaskAction
    debug: TaskAction
    open_execution: TaskAction


@dataclass(frozen=True)
class TaskLifecycle:
    runs_cleared: TaskAction
    deleted: TaskAction
    before_update: Render
    after_update: Callable[[dict], Awaitable[object]]
