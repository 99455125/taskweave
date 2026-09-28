"""Persistence for planning generation status and frozen candidate records."""

import json
from taskweave.infrastructure.storage import now, uid


class PlanGenerationRepository:

    def __init__(self, store):
        self.store = store

    def generation(self, generation_id):
        row = self.store.query('SELECT * FROM plan_generations WHERE generation_id=?', (generation_id,), True)
        row['candidate'] = json.loads(row.pop('candidate_json')) if row.get('candidate_json') else None
        row['diagnostics'] = json.loads(row.pop('diagnostics_json'))
        return row

    def generations(self, plan_id):
        rows = self.store.query('SELECT generation_id FROM plan_generations WHERE plan_id=? ORDER BY created_at DESC,generation_id DESC', (plan_id,))
        return [self.generation(row['generation_id']) for row in rows]

    def imports(self, generation_id):
        return self.store.query('SELECT import_id,generation_id,task_id,imported_at FROM plan_generation_imports WHERE generation_id=? ORDER BY imported_at,import_id', (generation_id,))

    def finish_generation(self, generation_id, status, response_path=None, candidate=None, diagnostics=None):
        self.store.execute('UPDATE plan_generations SET status=?,response_path=?,candidate_json=?,diagnostics_json=?,updated_at=? WHERE generation_id=?', (status, response_path, json.dumps(candidate, ensure_ascii=False) if candidate else None, json.dumps(diagnostics or [], ensure_ascii=False), now(), generation_id))
        return self.generation(generation_id)

    def mark_imported(self, generation_id, task_id):
        with self.store.transaction():
            stamp = now()
            self.store.execute('INSERT INTO plan_generation_imports(import_id,generation_id,task_id,imported_at) VALUES(?,?,?,?)', (uid(), generation_id, task_id, stamp))
            self.store.execute("UPDATE plan_generations SET status='IMPORTED',imported_task_id=COALESCE(imported_task_id,?),updated_at=? WHERE generation_id=?", (task_id, stamp, generation_id))
        return self.generation(generation_id)

    def create_generation(self, plan_id, revision, channel, request_path):
        generation_id, stamp = (uid(), now())
        self.store.execute("INSERT INTO plan_generations(generation_id,plan_id,plan_revision,channel,request_snapshot_path,status,created_at,updated_at) VALUES(?,?,?,?,?,'GENERATING',?,?)", (generation_id, plan_id, revision, channel, request_path, stamp, stamp))
        return self.generation(generation_id)
