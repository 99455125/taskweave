"""Result reference reads and deletion recovery state."""

import json
from taskweave.core.validation import TaskError
from taskweave.infrastructure.storage import connect
from taskweave.infrastructure.repositories.collaboration import TaskLockGuard


class ResultRepository:
    def __init__(self, store, tasks: TaskLockGuard):
        self.store = store
        self.tasks = tasks

    def query(self, sql, args=(), one=False):
        return self.store.query(sql, args, one)

    def transaction(self):
        return self.store.transaction()

    def execute(self, sql, args=()):
        return self.store.execute(sql, args)

    def task_path(self, task_id):
        return self.store.task_path(task_id)

    def run(self, run_id):
        return self.query("SELECT * FROM task_runs WHERE run_id=?", (run_id,), True)

    def receipt(self, attempt):
        path = self.task_path(attempt["task_id"])
        if not path.exists():
            return None
        with connect(path) as db:
            row = db.execute(
                "SELECT refs_json FROM result_receipts WHERE attempt_id=? AND run_id=? AND step_id=? AND state='COMMITTED'",
                (attempt["attempt_id"], attempt["run_id"], attempt["step_id"]),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def refs_for_attempt(self, attempt_id):
        return self.query("SELECT * FROM result_refs WHERE attempt_id=? ORDER BY result_id", (attempt_id,))

    def read_output(self, run_id, step_id, output="data", registry=None):
        run = self.run(run_id)
        attempts = self.query(
            "SELECT * FROM step_attempts WHERE run_id=? AND step_id=? AND valid=1 ORDER BY attempt_no DESC LIMIT 1",
            (run_id, step_id),
        )
        if not attempts or attempts[0]["status"] != "SUCCEEDED":
            raise TaskError("OUTPUT_NOT_AVAILABLE")
        if output != "data":
            refs = self.receipt(attempts[0]) or []
            ref = next((item for item in refs if item.get("name") == output), None)
            if ref is None:
                raise TaskError("OUTPUT_NOT_AVAILABLE")
            if registry is None:
                raise TaskError("HANDLER_UNAVAILABLE")
            if ref["handler_id"] != "core.json" and ref["handler_id"] not in registry.handlers:
                raise TaskError("HANDLER_UNAVAILABLE")
            return self.read_result(ref["result_id"], registry)["data"]
        path = self.task_path(run["task_id"])
        if not path.exists():
            raise TaskError("OUTPUT_NOT_AVAILABLE")
        with connect(path) as db:
            row = db.execute(
                "SELECT payload_json FROM step_outputs WHERE run_id=? AND step_id=? AND attempt_id=? AND name='data'",
                (run_id, step_id, attempts[0]["attempt_id"]),
            ).fetchone()
        if row is None:
            raise TaskError("OUTPUT_NOT_AVAILABLE")
        return json.loads(row[0])

    def read_result(self, result_id, registry):
        from taskweave.infrastructure.storage import connect
        ref = self.query('SELECT * FROM result_refs WHERE result_id=?', (result_id,), True)
        if ref['state'] != 'AVAILABLE':
            raise TaskError('RESULT_UNAVAILABLE')
        path = self.task_path(ref['task_id'])
        with connect(path) as db:
            receipt = db.execute('SELECT refs_json FROM result_receipts WHERE attempt_id=?', (ref['attempt_id'],)).fetchone()
        output_name = next((item.get('name', 'data' if item['locator'] == 'data' else item['locator']) for item in json.loads(receipt[0]) if item['result_id'] == result_id), ref['locator']) if receipt else ref['locator']
        if ref['kind'] == 'file':
            p = (path.parent / ref['locator']).resolve()
            if not p.is_relative_to(path.parent.resolve()) or not p.is_file():
                raise TaskError('RESULT_UNAVAILABLE')
            file_info = {'name': output_name, 'path': str(p), 'media_type': ref['media_type'], 'size_bytes': p.stat().st_size}
            handler = registry.handlers.get(ref['handler_id'])
            if handler is not None:
                parsed = handler.parse(file_info)
                return {**file_info, 'data': parsed, 'preview': handler.preview(parsed)}
            return file_info
        with connect(path) as db:
            if ref['kind'] == 'json':
                row = db.execute('SELECT payload_json FROM step_outputs WHERE attempt_id=? AND name=?', (ref['attempt_id'], ref['locator'])).fetchone()
                if row is None:
                    raise TaskError('RESULT_UNAVAILABLE')
                value = json.loads(row[0])
            else:
                import re
                if not re.fullmatch('p_[a-z0-9_]+', ref['locator']):
                    raise TaskError('TABLE_SCHEMA_INVALID')
                value = [dict(r) for r in db.execute('SELECT * FROM "' + ref['locator'] + '" WHERE run_id=? AND step_id=? AND attempt_id=?', (ref['run_id'], ref['step_id'], ref['attempt_id']))]
        if ref['handler_id'] == 'core.json':
            with connect(path) as db:
                metadata = db.execute('SELECT payload_json FROM step_outputs WHERE attempt_id=? AND name=?', (ref['attempt_id'], '__views')).fetchone()
            return {'name': output_name, 'data': value, 'preview': value, 'views': json.loads(metadata[0])['items'] if metadata and ref['locator'] == 'data' else []}
        handler = registry.handlers.get(ref['handler_id'])
        if handler is None:
            raise TaskError('HANDLER_UNAVAILABLE')
        parsed = handler.parse(value)
        return {'name': output_name, 'data': parsed, 'preview': handler.preview(parsed)}

    def delete_result(self, result_id):
        from taskweave.infrastructure.storage import connect
        ref = self.query('SELECT * FROM result_refs WHERE result_id=?', (result_id,), True)
        with self.transaction() as db:
            self.tasks.assert_unlocked(db, ref['task_id'])
            db.execute("UPDATE result_refs SET state='DELETING' WHERE result_id=?", (result_id,))
        path = self.task_path(ref['task_id'])
        with connect(path) as db:
            receipt = db.execute('SELECT refs_json FROM result_receipts WHERE attempt_id=?', (ref['attempt_id'],)).fetchone()
        output_name = next((item.get('name', 'data' if item['locator'] == 'data' else item['locator']) for item in json.loads(receipt[0]) if item['result_id'] == result_id), ref['locator']) if receipt else ref['locator']
        if ref['kind'] == 'file':
            p = (path.parent / ref['locator']).resolve()
            if not p.is_relative_to(path.parent.resolve()):
                raise TaskError('ARTIFACT_INVALID')
            p.unlink(missing_ok=True)
        elif path.exists():
            with connect(path) as db:
                if ref['kind'] == 'json':
                    db.execute('DELETE FROM step_outputs WHERE attempt_id=? AND name=?', (ref['attempt_id'], ref['locator']))
                else:
                    import re
                    if not re.fullmatch('p_[a-z0-9_]+', ref['locator']):
                        raise TaskError('TABLE_SCHEMA_INVALID')
                    db.execute('DELETE FROM "' + ref['locator'] + '" WHERE attempt_id=?', (ref['attempt_id'],))
        self.execute("UPDATE result_refs SET state='UNAVAILABLE' WHERE result_id=?", (result_id,))
        return {'deleted': result_id}
