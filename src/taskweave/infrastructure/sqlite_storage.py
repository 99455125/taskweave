"""SQLite connections, current schema validation and shared transaction storage.

This layer does not import or construct domain repositories. Composition belongs
to callers of build_sqlite_repositories; legacy Store lives in storage.py.
"""

from contextlib import contextmanager, closing
from datetime import datetime, timezone
from importlib.resources import files
from functools import lru_cache
import json
import os
from pathlib import Path
import sqlite3
import sys
from uuid import uuid4

from taskweave.core.validation import TaskError, valid_id
from taskweave.infrastructure.unit_of_work import SQLiteUnitOfWork


def uid():
    return str(uuid4())


def now():
    return datetime.now(timezone.utc).isoformat()


def default_home():
    if os.getenv("TASKWEAVE_HOME"):
        return Path(os.environ["TASKWEAVE_HOME"]).expanduser()
    if sys.platform == "win32":
        standard = Path(os.environ["LOCALAPPDATA"]) / "TaskWeave"
    elif sys.platform == "darwin":
        standard = Path.home() / "Library/Application Support/TaskWeave"
    else:
        standard = (
        Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local/share")))
        / "taskweave"
        )
    location = standard.parent / "taskweave-location.json"
    if location.exists():
        try:
            configured = Path(json.loads(location.read_text(encoding="utf-8"))["workspace_home"]).expanduser().resolve()
            return configured
        except (ValueError, KeyError, TypeError):
            pass
    return standard


def workspace_location_file():
    if sys.platform == "win32":
        standard = Path(os.environ["LOCALAPPDATA"]) / "TaskWeave"
    elif sys.platform == "darwin":
        standard = Path.home() / "Library/Application Support/TaskWeave"
    else:
        standard = Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "taskweave"
    return standard.parent / "taskweave-location.json"


@contextmanager
def connect(path):
    db = sqlite3.connect(path, timeout=5)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=5000")
    try:
        with db:
            yield db
    finally:
        db.close()


def schema_sql(name):
    """Return the single authoritative schema for a database role."""
    if name not in {"control", "task-data"}:
        raise ValueError(f"Unknown database role: {name}")
    return files("taskweave.infrastructure").joinpath(f"sql/{name}.sql").read_text()


def schema_objects(db):
    return {(row[0], row[1]): (row[2], row[3]) for row in db.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' AND sql IS NOT NULL"
    )}


@lru_cache(maxsize=2)
def current_schema(name):
    with closing(sqlite3.connect(":memory:")) as db:
        db.executescript(schema_sql(name))
        return schema_objects(db)


def validate_schema(db, name):
    """Reject drift without changing existing data or guessing conversions."""
    expected = current_schema(name)
    actual = schema_objects(db)
    for key, definition in expected.items():
        if actual.get(key) != definition:
            raise TaskError("SCHEMA_MAINTENANCE_REQUIRED",
                            f"{name} schema differs at {key[1]}; use explicit data maintenance")
    extras = {key: value for key, value in actual.items() if key not in expected}
    if extras and (name != "task-data" or any(
        kind not in {"table", "index"} or not table.startswith("p_")
        for (kind, _), (table, _) in extras.items()
    )):
        raise TaskError("SCHEMA_MAINTENANCE_REQUIRED",
                        f"{name} has unexpected schema objects; use explicit data maintenance")


def initialize(path, name):
    script = schema_sql(name)
    path = Path(path)
    fresh = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        if fresh and not schema_objects(db):
            # Execute within our transaction: executescript would commit it first.
            statement = ""
            for line in script.splitlines(keepends=True):
                statement += line
                if sqlite3.complete_statement(statement):
                    db.execute(statement)
                    statement = ""
            if statement.strip():
                raise ValueError("Incomplete schema statement")
        validate_schema(db, name)


class SQLiteStorage:
    def __init__(self, home):
        self.home = Path(home).resolve()
        self.home.mkdir(parents=True, exist_ok=True)
        self.path = self.home / "taskweave.db"
        initialize(self.path, "control")
        self.unit_of_work = SQLiteUnitOfWork(self.path)

    @contextmanager
    def transaction(self):
        with self.unit_of_work.transaction() as db:
            yield db

    def query(self, sql, args=(), one=False):
        active = self.unit_of_work.current_connection()
        if active is not None:
            rows = [dict(x) for x in active.execute(sql, args)]
        else:
            with connect(self.path) as db:
                rows = [dict(x) for x in db.execute(sql, args)]
        if one:
            if not rows:
                raise TaskError("NOT_FOUND")
            return rows[0]
        return rows

    def execute(self, sql, args=()):
        with self.transaction() as db:
            return db.execute(sql, args).rowcount

    def task_path(self, task_id):
        return self.home / "tasks" / valid_id(task_id) / "data.db"
