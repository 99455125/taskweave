"""Durable interval scheduling, task operations and desktop API evidence."""
from contextlib import closing
from pathlib import Path
import sqlite3
from taskweave.application.service import Application
from taskweave.infrastructure.storage import uid
from tests._runtime_fixture import RuntimeFixture

class ExecutorRecoveryTests(RuntimeFixture):
    def test_restart_removes_dead_executor_lease_preserves_run(self):
        step = self.step()
        run = self.app.create_run(self.task)
        self.app.close()
        with closing(sqlite3.connect(Path(self.temp.name) / 'taskweave.db')) as db:
            with db:
                db.execute("INSERT INTO runtime_lease VALUES(1,?,?,?)", (run['run_id'],'dead-owner','2020-01-01'))
        self.app = Application(self.temp.name)
        self.assertFalse(self.app.repo.query('SELECT * FROM runtime_lease'))
        self.assertEqual(self.app.repo.run(run['run_id'])['status'],'READY')
        trial = self.app.trial_step(step['step_id'],{},uid())
        self.assertEqual(self.app.coordinator.wait(trial['run_id'])['status'],'SUCCEEDED')
