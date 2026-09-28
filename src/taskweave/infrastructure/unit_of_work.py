"""Thread and asyncio-task local SQLite transactions for repository operations."""

from contextlib import contextmanager
import asyncio
import itertools
import sqlite3
import threading


class SQLiteUnitOfWork:
    """Bind nested repository work to one connection and one outer transaction."""

    def __init__(self, path, timeout=5):
        self.path = str(path)
        self.timeout = timeout
        self._local = threading.local()
        self._savepoints = itertools.count(1)

    @staticmethod
    def _owner_key():
        try:
            task = asyncio.current_task()
        except RuntimeError:
            task = None
        return task

    def _connections(self):
        if not hasattr(self._local, "connections"):
            self._local.connections = {}
        return self._local.connections

    def current_connection(self):
        return self._connections().get(self._owner_key())

    def _open(self):
        db = sqlite3.connect(self.path, timeout=self.timeout)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute(f"PRAGMA busy_timeout={int(self.timeout * 1000)}")
        return db

    @contextmanager
    def transaction(self):
        connections = self._connections()
        key = self._owner_key()
        db = connections.get(key)
        outermost = db is None
        savepoint = None
        if outermost:
            db = self._open()
            connections[key] = db
            try:
                db.execute("BEGIN IMMEDIATE")
            except BaseException:
                connections.pop(key, None)
                db.close()
                raise
        else:
            savepoint = f"uow_sp_{next(self._savepoints)}"
            db.execute(f'SAVEPOINT "{savepoint}"')

        try:
            yield db
        except BaseException:
            if outermost:
                db.rollback()
            else:
                db.execute(f'ROLLBACK TO SAVEPOINT "{savepoint}"')
                db.execute(f'RELEASE SAVEPOINT "{savepoint}"')
            raise
        else:
            if outermost:
                try:
                    db.commit()
                except BaseException:
                    db.rollback()
                    raise
            else:
                db.execute(f'RELEASE SAVEPOINT "{savepoint}"')
        finally:
            if outermost:
                connections.pop(key, None)
                db.close()
