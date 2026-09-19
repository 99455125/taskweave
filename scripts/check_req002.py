"""Executable design checks, not a runtime or a complete JSON Schema validator.

Only executes the two repository-owned contract examples with in-memory mocks.
Never imports legacy code, starts a browser, calls AI, or opens production DBs.
"""
import ast
import asyncio
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'docs/requirements/REQ-002-task-plugin-design'
spec = importlib.util.spec_from_file_location('req002_ports', BASE / 'contracts/ports.py')
ports = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ports
spec.loader.exec_module(ports)


def check_fixture_schema(value, schema):
    """Only the type/properties/required/additionalProperties subset in our fixtures."""
    types = {'object': dict, 'string': str, 'boolean': bool, 'null': type(None)}
    if type(value) is not types[schema['type']]:
        raise ValueError('Wrong value type')
    if schema['type'] == 'object':
        if not set(schema.get('required', ())).issubset(value):
            raise ValueError('Required property missing')
        props = schema.get('properties', {})
        if schema.get('additionalProperties') is False and set(value) - set(props):
            raise ValueError('Unexpected property')
        for key, item in value.items():
            if key in props:
                check_fixture_schema(item, props[key])


class MockContext:
    def __init__(self, actions, title='TaskWeave demo', allowed=None):
        self.actions = {x['id']: x for x in actions}
        self.allowed = set(self.actions) if allowed is None else set(allowed)
        self.calls = []
        self.title = title

    async def call(self, name, inputs):
        if name not in self.allowed:
            raise ValueError('CAPABILITY_DENIED')
        check_fixture_schema(inputs, self.actions[name]['input_schema'])
        self.calls.append(name)
        output = {'playwright.page_open': None,
                  'playwright.page_title': {'title': self.title},
                  'playwright.page_screenshot': {'staged_file': 'mock-owned-token'}}[name]
        check_fixture_schema(output, self.actions[name]['output_schema'])
        return output

    def result(self, data=None, outputs=()):
        return ports.StepResult(data=data, outputs=outputs)

    def output(self, handler_id, name, payload):
        return ports.ResultRequest(handler_id, name, payload)


def load_example(name):
    source = (BASE / 'examples' / name).read_text(encoding='utf-8')
    tree = ast.parse(source)
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.AsyncFunctionDef):
        raise ValueError('Expected single async function')
    fn = tree.body[0]
    if fn.name != 'run' or [x.arg for x in fn.args.args] != ['ctx', 'inputs']:
        raise ValueError('Wrong entry signature')
    if fn.decorator_list or fn.args.defaults:
        raise ValueError('Unexpected top-level expressions')
    ns = {}
    exec(compile(tree, str(BASE / 'examples' / name), 'exec'), ns)
    return ns['run']


class ContractChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.task = json.loads((BASE / 'examples/task.json').read_text())
        cls.manifest = json.loads((BASE / 'examples/playwright.json').read_text())

    def test_task_manifest_references(self):
        task = self.task
        step = task['steps'][0]
        self.assertEqual(step['step_content'], (BASE / 'examples/inspect_page.py').read_text())
        self.assertEqual(task['nodes'][0]['config']['step_id'], step['step_id'])
        self.assertEqual(task['entry_node_id'], task['nodes'][0]['id'])
        declared = {x['id'] for x in self.manifest['actions']} | set(self.manifest['result_handlers'])
        self.assertTrue(set(step['capabilities']).issubset(declared))
        self.assertEqual(self.manifest['api_version'], 1)
        for binding in step['bindings'].values():
            self.assertIn(binding['ref']['pointer'][1:], task['input_schema']['properties'])
        self.assertNotIn('step_version', step)

    def test_data_without_file(self):
        ctx = MockContext(self.manifest['actions'])
        result = asyncio.run(load_example('inspect_page.py')(ctx, {'url':'https://example.test','role':'operator','capture':False}))
        self.assertEqual(ctx.calls, ['playwright.page_open','playwright.page_title'])
        self.assertEqual(result.data, {'title':'TaskWeave demo'})
        self.assertFalse(result.outputs)
        check_fixture_schema(result.data, self.task['steps'][0]['output_schema'])

    def test_optional_file_request(self):
        ctx = MockContext(self.manifest['actions'])
        result = asyncio.run(load_example('inspect_page.py')(ctx, {'url':'https://example.test','role':'operator','capture':True}))
        self.assertEqual(result.outputs[0].handler_id, 'playwright.image')
        self.assertEqual(result.outputs[0].payload, {'staged_file':'mock-owned-token'})

    def test_status_only_result(self):
        ctx = MockContext(self.manifest['actions'])
        result = asyncio.run(load_example('open_page.py')(ctx, {'url':'https://example.test','role':'operator'}))
        self.assertIsNone(result.data)
        self.assertFalse(result.outputs)

    def test_business_assertion_rejects_empty_title(self):
        with self.assertRaisesRegex(ValueError, 'title is empty'):
            asyncio.run(load_example('inspect_page.py')(MockContext(self.manifest['actions'], title=''),
                       {'url':'https://example.test','role':'operator','capture':False}))

    def test_input_and_allowlist_errors(self):
        ctx = MockContext(self.manifest['actions'])
        with self.assertRaises(ValueError):
            asyncio.run(ctx.call('playwright.page_open', {'role':'operator','url':42}))
        self.assertFalse(ctx.calls)
        ctx = MockContext(self.manifest['actions'], allowed=[])
        with self.assertRaisesRegex(ValueError, 'CAPABILITY_DENIED'):
            asyncio.run(ctx.call('playwright.page_title', {'role':'operator'}))

    def test_control_ddl_constraints(self):
        with sqlite3.connect(':memory:') as db:
            db.executescript((BASE / 'contracts/control.sql').read_text())
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 1)
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertFalse({'step_versions','step_revisions'} & tables)
            self.assertEqual(len(tables), 8)
            for task, step, run in [('t1','s1','r1'),('t2','s2','r2')]:
                db.execute("INSERT INTO tasks(task_id,name,graph_json,created_at,updated_at) VALUES(?,?,?, 'now','now')", (task,task,'{}'))
                db.execute("INSERT INTO steps(step_id,task_id,name,position,step_content,input_schema_json,output_schema_json,content_hash,updated_at) VALUES(?,?,?,0,'async def run(ctx,inputs): pass','{}','{}','h','now')", (step,task,step))
                db.execute("INSERT INTO task_runs(run_id,task_id,mode,status,definition_hash) VALUES(?,?,'EXECUTION','READY','h')", (run,task))
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE steps SET validation_state='VALIDATED' WHERE step_id='s1'")
            db.execute("UPDATE steps SET validation_state='VALIDATED',verified_hash='h' WHERE step_id='s1'")
            db.execute("INSERT INTO runtime_lease VALUES(1,'r1','worker','now')")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO runtime_lease VALUES(1,'r2','worker','now')")
            attempt = "INSERT INTO step_attempts(attempt_id,task_id,run_id,step_id,execution_path,attempt_no,content_hash,status,effect_state,started_at) VALUES(?,?,?,?,?,1,'h','RUNNING','NOT_STARTED','now')"
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(attempt, ('bad','t1','r1','s2','/main/n'))
            db.execute(attempt, ('a1','t1','r1','s1','/main/n'))
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(attempt, ('duplicate','t1','r1','s1','/main/n'))
            self.assertFalse(db.execute('PRAGMA foreign_key_check').fetchall())

    def test_separate_task_databases(self):
        with tempfile.TemporaryDirectory(prefix='req002-') as tmp:
            ddl = (BASE / 'contracts/task-data.sql').read_text()
            for task in ('t1','t2'):
                with sqlite3.connect(Path(tmp) / f'{task}.db') as db:
                    db.executescript(ddl)
                    db.execute('CREATE TABLE p_demo_items(value TEXT)')
                    db.execute('INSERT INTO p_demo_items VALUES(?)', (task,))
                    db.execute("INSERT INTO step_outputs VALUES('r1','s1','a1','data',?,'now')",
                               (json.dumps({'order_id': task + '-order'}),))
                    db.execute("INSERT INTO result_receipts VALUES('a1','r1','s1','COMMITTED','[]','now')")
                    with self.assertRaises(sqlite3.IntegrityError):
                        db.execute("INSERT INTO result_receipts VALUES('a1','r1','s1','COMMITTED','[]','now')")
            for task in ('t1','t2'):
                with sqlite3.connect(Path(tmp) / f'{task}.db') as db:
                    self.assertEqual(db.execute('SELECT value FROM p_demo_items').fetchone()[0], task)
                    # Reopen the DB: a later step can obtain output without producer memory.
                    saved = db.execute("SELECT payload_json FROM step_outputs WHERE run_id='r1' AND step_id='s1' AND attempt_id='a1' AND name='data'").fetchone()
                    self.assertEqual(json.loads(saved[0])['order_id'], task + '-order')
                    self.assertIsNone(db.execute("SELECT payload_json FROM step_outputs WHERE run_id='other-run'").fetchone())


if __name__ == '__main__':
    unittest.main(verbosity=2)
