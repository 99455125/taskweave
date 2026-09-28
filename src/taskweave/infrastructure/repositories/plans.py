"""Persistence for plan metadata and copy coordination."""

import json
from pathlib import Path
import shutil
from taskweave.core.validation import TaskError
from taskweave.infrastructure.storage import now, uid
from taskweave.infrastructure.repositories.collaboration import PlanContextCopier
from taskweave.infrastructure.repositories.plan_helpers import decode_plan, expect_plan_revision


class PlanMetadataRepository:

    def __init__(self, store, plan_contexts: PlanContextCopier):
        self.store = store
        self.plan_contexts = plan_contexts
        self.root = Path(store.home) / 'plans'
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _decode(plan):
        return decode_plan(plan)

    def create(self, name='新计划'):
        plan_id, stamp = (uid(), now())
        self.store.execute('INSERT INTO plans(plan_id,name,created_at,updated_at) VALUES(?,?,?,?)', (plan_id, name or '新计划', stamp, stamp))
        (self.root / plan_id).mkdir(parents=True, exist_ok=True)
        return self.get(plan_id)

    def list(self):
        return [self._decode(x) for x in self.store.query('SELECT * FROM plans ORDER BY updated_at DESC')]

    @staticmethod
    def _expect(db, plan_id, revision):
        return expect_plan_revision(db, plan_id, revision)

    def delete(self, plan_id, expected_revision):
        with self.store.transaction() as db:
            self._expect(db, plan_id, expected_revision)
            db.execute('DELETE FROM plans WHERE plan_id=?', (plan_id,))
        shutil.rmtree(self.root / plan_id, ignore_errors=True)
        return {'deleted': True, 'plan_id': plan_id}

    def get(self, plan_id):
        try:
            return self._decode(self.store.query('SELECT * FROM plans WHERE plan_id=?', (plan_id,), True))
        except TaskError as exc:
            raise TaskError('PLAN_NOT_FOUND', plan_id) from exc

    def update(self, plan_id, expected_revision, name, plan_description='', plan_notes='', environment_id=None, plugin_ids=None):
        with self.store.transaction() as db:
            self._expect(db, plan_id, expected_revision)
            db.execute('UPDATE plans SET name=?,plan_description=?,plan_notes=?,environment_id=?,plugin_ids_json=?,revision=revision+1,updated_at=? WHERE plan_id=?', (name, plan_description, plan_notes, environment_id, json.dumps(plugin_ids or []), now(), plan_id))
        return self.get(plan_id)

    def copy(self, plan_id, expected_revision):
        target_id, stamp = (uid(), now())
        target_root = self.root / target_id
        target_root.mkdir(parents=True, exist_ok=False)
        try:
            with self.store.transaction() as db:
                self._expect(db, plan_id, expected_revision)
                source = db.execute('SELECT * FROM plans WHERE plan_id=?', (plan_id,)).fetchone()
                db.execute('INSERT INTO plans(plan_id,name,plan_description,plan_notes,environment_id,plugin_ids_json,category_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)', (target_id, source['name'] + ' 副本', source['plan_description'], source['plan_notes'], source['environment_id'], source['plugin_ids_json'], source['category_id'], stamp, stamp))
                self.plan_contexts.copy_contexts(db, plan_id, target_id, stamp)
        except Exception:
            shutil.rmtree(target_root, ignore_errors=True)
            raise
        return self.get(target_id)
