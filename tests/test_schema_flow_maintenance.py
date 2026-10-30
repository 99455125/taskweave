"""Offline conversion preserves source and history while rejecting live state."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from scripts.maintain_current_schema import rebuild
from taskweave.infrastructure.sqlite_storage import initialize


class FlowMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / 'source.db'
        self.target = Path(self.temp.name) / 'current.db'
        initialize(self.source, 'control')
        self.graph = {'version': 2, 'root': {'id': 'root', 'kind': 'sequence', 'children': [{
            'id': 'choice', 'kind': 'if', 'condition': {'op': 'exists', 'value': {'literal': 1}},
            'then': {'id': 'yes', 'kind': 'sequence', 'children': []},
            'else': {'id': 'no', 'kind': 'sequence', 'children': []}}]}}
        with closing(sqlite3.connect(self.source)) as db, db:
            db.execute("INSERT INTO tasks(task_id,name,graph_json,created_at,updated_at) VALUES('task','kept',?,'now','now')", (json.dumps(self.graph),))
            definition = {'task': {'graph_json': json.dumps(self.graph)}, 'steps': [], 'flow': self.graph}
            db.execute("INSERT INTO task_runs(run_id,task_id,mode,status,definition_hash,definition_json,flow_cursor_json) VALUES('run','task','EXECUTION','SUCCEEDED','historical-hash',?,?)", (json.dumps(definition), json.dumps({'frames': [], 'pending': None})))
            db.execute("INSERT INTO flow_instances(run_id,execution_path,node_id,kind,status,payload_json,created_at,updated_at) VALUES('run','/root/choice','choice','if','SUCCEEDED',?,'now','now')", (json.dumps({'selected': 'then'}),))
            db.execute("INSERT INTO run_events VALUES('event','run',NULL,'debug',?,'now')", (json.dumps({'message': 'preserve me'}),))

    def test_offline_conversion_preserves_history_and_source(self):
        before = self.source.read_bytes()
        rebuild(self.source, self.target, 'control')
        self.assertEqual(self.source.read_bytes(), before)
        with closing(sqlite3.connect(self.target)) as db:
            graph, state, verified = db.execute('SELECT graph_json,flow_validation_state,flow_verified_hash FROM tasks').fetchone()
            self.assertEqual(json.loads(graph)['root']['children'][0]['cases'][0]['id'], 'then')
            self.assertEqual((state, verified), ('DRAFT', None))
            definition, digest = db.execute('SELECT definition_json,definition_hash FROM task_runs').fetchone()
            self.assertEqual(json.loads(definition)['flow'], json.loads(graph))
            self.assertEqual(json.loads(json.loads(definition)['task']['graph_json']), json.loads(graph))
            self.assertEqual(digest, 'historical-hash')
            self.assertEqual(json.loads(db.execute('SELECT payload_json FROM flow_instances').fetchone()[0]), {'selected': ['then']})
            self.assertEqual(json.loads(db.execute('SELECT payload_json FROM run_events').fetchone()[0]), {'message': 'preserve me'})

    def test_linear_chain_is_converted_without_steps(self):
        with closing(sqlite3.connect(self.source)) as db, db:
            db.execute('UPDATE tasks SET graph_json=?', (json.dumps({'entry_node_id': None, 'nodes': []}),))
        rebuild(self.source, self.target, 'control')
        with closing(sqlite3.connect(self.target)) as db:
            self.assertEqual(json.loads(db.execute('SELECT graph_json FROM tasks').fetchone()[0]), {'version': 2, 'root': {'id': 'root', 'kind': 'sequence', 'children': []}})

    def test_failed_run_and_cancelled_old_branch_cursor_are_preserved(self):
        from scripts.maintain_current_schema import convert_flow, convert_cursor
        from taskweave.core.flow_machine import next_action, advance_after_action
        old = json.loads(json.dumps(self.graph))
        old['root']['children'][0]['then']['children'] = [{'id': 'step', 'kind': 'action', 'step_id': 'step'}]
        pending = {'node_id': 'step', 'step_id': 'step', 'execution_path': '/root/choice/then/yes/step'}
        cursor = {'frames': [{'node_id': 'root', 'kind': 'sequence', 'path': '/root', 'index': 0},
                  {'node_id': 'choice', 'kind': 'if', 'path': '/root/choice', 'selected': 'then'},
                  {'node_id': 'yes', 'kind': 'sequence', 'path': '/root/choice/then/yes', 'index': 0}],
                  'pending': pending, 'actions': 2, 'control_visits': 1}
        flow = convert_flow(old)
        converted = convert_cursor(cursor, flow)
        self.assertEqual(cursor['frames'][1]['selected'], 'then')
        self.assertEqual(converted['frames'][1]['selected'], ['then'])
        transition = next_action(flow, converted, lambda *_: None)
        self.assertEqual(transition['action'], pending)
        advanced = advance_after_action(flow, transition['cursor'], 'attempt', execution_path=pending['execution_path'])
        self.assertTrue(next_action(flow, advanced['cursor'], lambda *_: None)['done'])
        with closing(sqlite3.connect(self.source)) as db, db:
            db.execute("UPDATE task_runs SET status='FAILED',flow_cursor_json=NULL")
        rebuild(self.source, self.target, 'control')
        with closing(sqlite3.connect(self.target)) as db:
            self.assertEqual(db.execute('SELECT status,flow_cursor_json FROM task_runs').fetchone(), ('FAILED', None))

    def test_live_status_or_recovery_cursor_prevents_publication(self):
        for status, cursor in [('RUNNING', {'frames': [], 'pending': None}), ('SUCCEEDED', {'frames': [{'kind': 'if'}], 'pending': None})]:
            with self.subTest(status=status, cursor=cursor):
                with closing(sqlite3.connect(self.source)) as db, db:
                    db.execute('UPDATE task_runs SET status=?,flow_cursor_json=?', (status, json.dumps(cursor)))
                before = self.source.read_bytes()
                with self.assertRaisesRegex(ValueError, 'active|recover'):
                    rebuild(self.source, self.target, 'control')
                self.assertFalse(self.target.exists())
                self.assertEqual(self.source.read_bytes(), before)

class DefinitionHashMaintenanceTests(unittest.TestCase):
    """Only semantic identity backed by the old database can renew a guard hash."""
    def setUp(self):
        FlowMaintenanceTests.setUp(self)
        from taskweave.core.validation import fingerprint
        with closing(sqlite3.connect(self.source)) as db, db:
            schema, graph = db.execute('SELECT input_schema_json,graph_json FROM tasks').fetchone()
            self.old_hash = fingerprint({'input_schema': schema, 'graph': graph, 'steps': []})
            definition = {'task': {'task_id': 'task', 'input_schema_json': schema, 'graph_json': graph}, 'steps': [], 'flow': json.loads(graph)}
            db.execute("UPDATE task_runs SET status='FAILED',definition_hash=?,definition_json=?", (self.old_hash, json.dumps(definition)))

    def current_hash(self, db):
        from taskweave.core.validation import fingerprint
        schema, graph = db.execute('SELECT input_schema_json,graph_json FROM tasks').fetchone()
        return fingerprint({'input_schema': schema, 'graph': graph, 'steps': []})

    def test_same_failed_definition_keeps_configuration_guard_valid(self):
        rebuild(self.source, self.target, 'control')
        with closing(sqlite3.connect(self.target)) as db:
            self.assertEqual(db.execute('SELECT definition_hash FROM task_runs').fetchone()[0], self.current_hash(db))
            self.assertNotEqual(self.current_hash(db), self.old_hash)
            self.assertEqual(db.execute('SELECT status FROM task_runs').fetchone()[0], 'FAILED')

    def test_preexisting_stale_failed_run_is_not_reapproved(self):
        with closing(sqlite3.connect(self.source)) as db, db:
            db.execute("UPDATE task_runs SET definition_hash='already-stale'")
        rebuild(self.source, self.target, 'control')
        with closing(sqlite3.connect(self.target)) as db:
            self.assertEqual(db.execute('SELECT definition_hash FROM task_runs').fetchone()[0], 'already-stale')

    def test_conflicting_frozen_snapshot_is_not_reapproved(self):
        with closing(sqlite3.connect(self.source)) as db, db:
            raw = json.loads(db.execute('SELECT definition_json FROM task_runs').fetchone()[0])
            raw['task']['input_schema_json'] = '{"type":"string"}'
            db.execute('UPDATE task_runs SET definition_json=?', (json.dumps(raw),))
        with self.assertRaisesRegex(ValueError, 'snapshot'):
            rebuild(self.source, self.target, 'control')
        self.assertFalse(self.target.exists())

    def test_evidence_repairs_only_hash_after_previous_conversion(self):
        rebuild(self.source, self.target, 'control')
        with closing(sqlite3.connect(self.target)) as db, db:
            db.execute('UPDATE task_runs SET definition_hash=?', (self.old_hash,))
            db.execute("UPDATE tasks SET name='new user title'")
        repaired = self.target.with_name('repaired.db')
        audit = []
        rebuild(self.target, repaired, 'control', definition_evidence=self.source, audit=audit)
        with closing(sqlite3.connect(repaired)) as db:
            self.assertEqual(db.execute('SELECT definition_hash FROM task_runs').fetchone()[0], self.current_hash(db))
            self.assertEqual(db.execute('SELECT name FROM tasks').fetchone()[0], 'new user title')
        self.assertTrue(any(item['kind'] == 'run_definition_hash' for item in audit))

    def test_evidence_does_not_override_later_business_changes(self):
        rebuild(self.source, self.target, 'control')
        with closing(sqlite3.connect(self.target)) as db, db:
            db.execute('UPDATE task_runs SET definition_hash=?', (self.old_hash,))
            db.execute('UPDATE tasks SET input_schema_json=?', ('{"type":"string"}',))
        repaired = self.target.with_name('repaired.db')
        rebuild(self.target, repaired, 'control', definition_evidence=self.source)
        with closing(sqlite3.connect(repaired)) as db:
            self.assertEqual(db.execute('SELECT definition_hash FROM task_runs').fetchone()[0], self.old_hash)
            self.assertEqual(db.execute('SELECT input_schema_json FROM tasks').fetchone()[0], '{"type":"string"}')

    def test_sequence_task_hash_uses_the_same_equivalence_proof(self):
        snapshot = {'nodes': [{'node_id': 'call', 'task_id': 'task', 'inputs': {}, 'step_inputs': {}}],
                    'task_hashes': {'call': self.old_hash}}
        with closing(sqlite3.connect(self.source)) as db, db:
            db.execute("INSERT INTO sequence_runs(sequence_run_id,request_id,request_hash,status,snapshot_json,inputs_json,created_at,updated_at) VALUES('sequence-run','request','request-hash','SUCCEEDED',?,'{}','now','now')", (json.dumps(snapshot),))
        audit = []
        rebuild(self.source, self.target, 'control', audit=audit)
        with closing(sqlite3.connect(self.target)) as db:
            current = json.loads(db.execute('SELECT snapshot_json FROM sequence_runs').fetchone()[0])
            self.assertEqual(current['task_hashes']['call'], self.current_hash(db))
            self.assertEqual(current['nodes'], snapshot['nodes'])
        self.assertTrue(any(item['kind'] == 'sequence_task_hash' for item in audit))
