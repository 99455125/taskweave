"""Datasets are immutable, scoped, durable step results with bounded SQL."""
import tempfile
import unittest

from taskweave.core.ports import Scope, StepResult
from taskweave.core.validation import TaskError
from taskweave.infrastructure.storage import Results, uid
from taskweave.plugins.registry import Registry


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.scope = Scope(uid(), uid(), uid(), uid())
        self.results = Results(self.temp.name, self.scope, Registry())

    def store(self):
        self.assertTrue(hasattr(self.results, 'datasets'), 'host dataset port must be available')
        return self.results.datasets

    def sample(self):
        return self.store().create('通用示例', [{'name': '客户', 'type': 'text'}, {'name': '金额', 'type': 'integer'}],
                                   [['甲', 120], ['乙', 80], ['甲', 30]])

    def test_query_join_parameters_and_update_preserve_source(self):
        ds = self.store()
        source = self.sample()
        clients = ds.create('客户', [{'name': '客户'}, {'name': '地区'}], [['甲', '北'], ['乙', '南']])
        result = ds.query({'orders': source, 'clients': clients},
                          'SELECT c."地区", SUM(o."金额") AS total FROM orders o JOIN clients c USING("客户") WHERE o."金额" >= ? GROUP BY c."地区" ORDER BY total DESC', [50], '汇总')
        self.assertEqual(ds.read(result)['rows'], [{'地区': '北', 'total': 120}, {'地区': '南', 'total': 80}])
        changed = ds.execute(source, 'UPDATE data SET "金额"="金额"+? WHERE "客户"=?', [5, '甲'], '调整')
        self.assertEqual(ds.read(changed)['rows'][0]['金额'], 125)
        self.assertEqual(ds.read(source)['rows'][0]['金额'], 120)

    def test_sql_cannot_access_storage_attach_or_execute_extra_statements(self):
        ds = self.store()
        source = self.sample()
        for sql in ['SELECT * FROM step_outputs', 'SELECT * FROM sqlite_master',
                    "ATTACH DATABASE '/tmp/taskweave-secret.db' AS other", 'PRAGMA database_list',
                    'SELECT 1; SELECT 2', "SELECT load_extension('x')", 'DELETE FROM data',
                    'SELECT randomblob(100000000)']:
            with self.subTest(sql=sql), self.assertRaises(TaskError):
                ds.query({'data': source}, sql, [], '拒绝')
        for sql in ['DROP TABLE data', 'CREATE TABLE evil(x)', 'BEGIN', 'DELETE FROM data; SELECT 1']:
            with self.subTest(sql=sql), self.assertRaises(TaskError):
                ds.execute(source, sql, [], '拒绝')
        self.assertEqual(ds.read(source)['row_count'], 3)

    def test_empty_schema_pagination_types_and_invalid_data(self):
        ds = self.store()
        empty = ds.create('空表', [{'name': '编号', 'type': 'text'}], [])
        self.assertEqual(ds.describe(empty)['columns'], [{'name': '编号', 'type': 'text'}])
        self.assertEqual(ds.read(empty)['rows'], [])
        page = ds.read(self.sample(), offset=1, limit=1)
        self.assertEqual((page['total'], page['row_count'], page['truncated']), (3, 1, True))
        typed = ds.create('类型', [{'name': 'flag', 'type': 'boolean'}, {'name': 'code', 'type': 'text'}], [[False, '001'], [None, '=A1']])
        self.assertEqual(ds.read(typed)['rows'], [{'flag': False, 'code': '001'}, {'flag': None, 'code': '=A1'}])
        for columns, rows in [([{'name': 'A'}, {'name': 'a'}], []),
                              ([{'name': ''}], []), ([{'name': 'x', 'type': 'integer'}], [[1.5]]),
                              ([{'name': 'x'}], [[float('nan')]]), ([{'name': 'x'}], [[{}]]),
                              ([{'name': 'x'}], [[1, 2]])]:
            with self.subTest(columns=columns, rows=rows), self.assertRaises(TaskError):
                ds.create('bad', columns, rows)

    def test_staging_is_atomic_with_results_and_diagnostic_does_not_publish(self):
        ds = self.store()
        ref = self.sample()
        self.assertFalse(self.results.path.exists())
        self.results.persist_diagnostics(())
        self.assertFalse(self.results.path.exists())
        refs = self.results.persist(StepResult(data={'dataset': ref}))
        self.assertEqual(len([r for r in refs if r['handler_id'] == 'dataset.table']), 1)
        from taskweave.infrastructure.sqlite_storage import connect
        with connect(self.results.path) as db:
            names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            table = next(n for n in names if n.startswith('p_dataset_'))
            self.assertEqual(db.execute('SELECT count(*) FROM "' + table + '"').fetchone()[0], 3)
        self.assertEqual(self.results.persist(StepResult(data={'dataset': ref})), refs)

    def test_boolean_any_column_survives_storage_without_becoming_integer(self):
        ds = self.store()
        ref = ds.create('mixed', [{'name': 'v'}], [[True], [False], [1], [None]])
        refs = self.results.persist(StepResult(data=ref))
        from taskweave.infrastructure.datasets import stored_snapshot
        from taskweave.infrastructure.sqlite_storage import connect
        with connect(self.results.path) as db:
            saved = stored_snapshot(db, refs[-1]['locator'], self.scope.run_id, self.scope.step_id, self.scope.attempt_id)
        self.assertIs(saved['rows'][0][0], True)
        self.assertIs(saved['rows'][1][0], False)
        self.assertIs(type(saved['rows'][2][0]), int)

    def test_persist_failure_rolls_back_datasets_and_ordinary_output_together(self):
        self.sample()
        self.sample()
        from unittest.mock import patch
        original = self.results._json
        counter = []
        def fail_second_metadata(db, name, value):
            if name.startswith('__dataset_'):
                counter.append(name)
                if len(counter) == 2:
                    raise OSError('storage failure')
            original(db, name, value)
        with patch.object(self.results, '_json', side_effect=fail_second_metadata), self.assertRaises(OSError):
            self.results.persist(StepResult(data={'ok': True}))
        from taskweave.infrastructure.sqlite_storage import connect
        with connect(self.results.path) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM step_outputs').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM result_receipts').fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM sqlite_master WHERE name LIKE 'p_dataset_%'").fetchone()[0], 0)

    def test_nonfinite_sql_parameters_are_rejected(self):
        ds = self.store()
        ref = self.sample()
        for value in (float('nan'), float('inf')):
            with self.subTest(value=value), self.assertRaises(TaskError):
                ds.query({'data': ref}, 'SELECT ? AS value', [value], 'invalid')

    def test_sql_accepts_legal_wide_row(self):
        ds = self.store()
        ref = ds.create('wide', [{'name': 'a'}, {'name': 'b'}], [['a' * 600000, 'b' * 600000]])
        result = ds.query({'data': ref}, 'SELECT length(a) AS n FROM data', [], 'length')
        self.assertEqual(ds.read(result)['rows'], [{'n': 600000}])

    def test_execute_preserves_row_order_with_rowid_column_and_any_booleans(self):
        ds = self.store()
        ref = ds.create('types', [{'name': 'rowid'}, {'name': 'flag'}], [[2, True], [1, False], [3, 1]])
        changed = ds.execute(ref, 'UPDATE data SET flag=flag', [], 'copy')
        rows = ds.read(changed)['rows']
        self.assertEqual([r['rowid'] for r in rows], [2, 1, 3])
        self.assertIs(rows[0]['flag'], True)
        self.assertIs(rows[1]['flag'], False)
        self.assertIs(type(rows[2]['flag']), int)

    def test_execute_preserves_boolean_identity_when_deleting_middle_rows(self):
        ds = self.store()
        ref = ds.create('types', [{'name': 'id'}, {'name': 'flag'}], [[1, True], [2, 1], [3, False], [4, 0]])
        changed = ds.execute(ref, 'DELETE FROM data WHERE id=2', [], 'copy')
        rows = ds.read(changed)['rows']
        self.assertIs(rows[0]['flag'], True)
        self.assertIs(rows[1]['flag'], False)
        self.assertIs(type(rows[2]['flag']), int)

    def test_cancelled_and_oversized_queries_do_not_stage_results(self):
        ds = self.store()
        source = self.sample()
        with self.assertRaises(TaskError):
            ds.query({'data': source}, 'WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<100001) SELECT x FROM n', [], 'too big')
        ds.cancelled = lambda: True
        with self.assertRaisesRegex(TaskError, 'CANCELLED'):
            ds.query({'data': source}, 'SELECT * FROM data', [], 'cancelled')


class DatasetWorkerTests(unittest.TestCase):
    def test_real_worker_binding_restart_view_delete_and_run_isolation(self):
        from taskweave.application.service import Application
        from taskweave.infrastructure.storage import uid
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            app.configure_plugin('dataset', True)
            task = app.repo.create_task('数据集链路')['task_id']
            first = app.repo.save_step(task, {'name': '创建', 'capabilities': ['dataset.create'],
                'step_content': 'async def run(ctx, inputs):\n    ref = await ctx.call("dataset.create", {"name":"通用示例","columns":[{"name":"n","type":"integer"}],"rows":[[2],[3]]})\n    return ctx.result(data={"ref":ref})'})
            second = app.repo.save_step(task, {'name': '聚合', 'capabilities': ['dataset.query', 'dataset.read'],
                'bindings': {'source': {'ref': {'source': 'step', 'step_id': first['step_id'], 'pointer': '/ref'}}},
                'step_content': 'async def run(ctx, inputs):\n    ref = await ctx.call("dataset.query", {"sources":{"items":inputs["source"]},"sql":"SELECT SUM(n) AS total FROM items","name":"汇总"})\n    table = await ctx.call("dataset.read", {"dataset":ref})\n    return ctx.result(data={"ref":ref,"table":table},views=[{"title":"汇总","renderer":"core.table","pointer":"/table"}])'})
            for step in (first, second):
                app.confirm_step_manual(step['step_id'], step['content_hash'])
            run = app.create_run(task)
            app.coordinator.start(run['run_id'], uid())
            done = app.coordinator.wait(run['run_id'])
            self.assertEqual(done['status'], 'SUCCEEDED', done['attempts'])
            output = app.repo.read_output(run['run_id'], second['step_id'])
            self.assertEqual(output['table']['rows'], [{'total': 5}])
            ref = app.repo.read_output(run['run_id'], first['step_id'])['ref']
            reader = Results(home, Scope(task, run['run_id'], uid(), uid()), app.registry).datasets
            with self.assertRaises(TaskError):
                reader.read(ref)
            reader.authorize_inputs({'nested': [ref]})
            self.assertEqual(reader.read(ref)['rows'], [{'n': 2}, {'n': 3}])
            app.repo.execute('UPDATE step_attempts SET valid=0 WHERE attempt_id=?', (ref['attempt_id'],))
            with self.assertRaises(TaskError):
                reader.read(ref)
            app.repo.execute('UPDATE step_attempts SET valid=1 WHERE attempt_id=?', (ref['attempt_id'],))
            other = Results(home, Scope(task, uid(), uid(), uid()), app.registry).datasets
            other.authorize_inputs({'source': ref})
            with self.assertRaises(TaskError):
                other.read(ref)
            stored = app.repo.query("SELECT * FROM result_refs WHERE handler_id='dataset.table' AND attempt_id=?", (ref['attempt_id'],))[0]
            viewed = app.repo.read_result(stored['result_id'], app.registry)
            self.assertEqual(viewed['data']['rows'], [{'n': 2}, {'n': 3}])
            app.repo.delete_result(stored['result_id'])
            with self.assertRaises(TaskError):
                reader.read(ref)

    def test_failed_step_does_not_publish_staged_dataset(self):
        from taskweave.application.service import Application
        from taskweave.infrastructure.sqlite_storage import connect
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            app.configure_plugin('dataset', True)
            task = app.repo.create_task('失败不发布')['task_id']
            step = app.repo.save_step(task, {'name': '失败', 'capabilities': ['dataset.create'],
                'step_content': 'async def run(ctx, inputs):\n    ref=await ctx.call("dataset.create", {"name":"暂存","columns":[{"name":"n"}],"rows":[[1]]})\n    value=1/0\n    return ctx.result(data=ref)'})
            app.confirm_step_manual(step['step_id'], step['content_hash'])
            run = app.create_run(task)
            app.coordinator.start(run['run_id'], uid())
            done = app.coordinator.wait(run['run_id'])
            self.assertEqual(done['attempts'][0]['error_code'], 'ZeroDivisionError')
            self.assertEqual(done['results'], [])
            with connect(app.repo.task_path(task)) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM sqlite_master WHERE name LIKE 'p_dataset_%'").fetchone()[0], 0)

