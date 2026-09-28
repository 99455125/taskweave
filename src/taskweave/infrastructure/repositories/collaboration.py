"""Narrow SQLite-only collaboration ports between repository adapters."""

from sqlite3 import Connection
from typing import Protocol


class PlanContextCopier(Protocol):
    def copy_contexts(self, db: Connection, plan_id: str, target_id: str, stamp: str) -> None: ...


class TaskLockGuard(Protocol):
    def assert_unlocked(self, db: Connection, task_id: str, allow_idle_trial: bool = False) -> None: ...
