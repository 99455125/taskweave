"""File reads are bounded and reusable as ordinary step data."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from taskweave.core.validation import TaskError, validate


class FilePluginTests(unittest.TestCase):
    def test_read_sql_preserves_complete_text_and_encoding(self):
        from taskweave_file import FilePlugin
        with tempfile.TemporaryDirectory() as root:
            text = "-- 中文说明\nINSERT INTO sample(value) VALUES ('a;b');\n"
            Path(root, 'script.sql').write_text(text, encoding='utf-8-sig')
            action = FilePlugin().actions()['file.read']
            ctx = SimpleNamespace(environment={'file_root': root}, task_parameters={}, cancelled=lambda: False)
            result = asyncio.run(action.execute(ctx, {'path': 'script.sql'}))
            self.assertEqual(result['content'], text)
            self.assertEqual(result['path'], 'script.sql')
            validate(result, action.spec.output_schema)
            self.assertEqual(action.spec.effect, 'READ')

    def test_rejects_escape_symlink_and_oversized_file_without_partial_data(self):
        from taskweave_file import FilePlugin
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            Path(root, 'big.sql').write_bytes(b'x' * 100)
            Path(outside, 'private.txt').write_text('outside')
            Path(root, 'link').symlink_to(Path(outside, 'private.txt'))
            action = FilePlugin().actions()['file.read']
            ctx = SimpleNamespace(environment={'file_root': root}, task_parameters={}, cancelled=lambda: False)
            for inputs in ({'path': '../private.txt'}, {'path': 'link'}, {'path': 'big.sql', 'max_bytes': 10}):
                with self.assertRaises(TaskError):
                    asyncio.run(action.execute(ctx, inputs))

    def test_json_csv_and_binary_share_read_contract(self):
        from taskweave_file import FilePlugin
        with tempfile.TemporaryDirectory() as root:
            Path(root, 'data.json').write_text('{"count":2}')
            Path(root, 'data.csv').write_text('name,count\n样本,2\n')
            Path(root, 'data.bin').write_bytes(b'\x00\xff')
            action = FilePlugin().actions()['file.read']
            ctx = SimpleNamespace(environment={'file_root': root}, task_parameters={}, cancelled=lambda: False)
            def read(path, format):
                return asyncio.run(action.execute(ctx, {'path': path, 'format': format}))['content']
            self.assertEqual(read('data.json', 'json'), {'count': 2})
            self.assertEqual(read('data.csv', 'csv'), [{'name': '样本', 'count': '2'}])
            self.assertEqual(read('data.bin', 'base64'), 'AP8=')

    def test_real_worker_returns_file_content_for_next_step_binding(self):
        from taskweave.application.service import Application
        from taskweave.infrastructure.storage import uid
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as root, Application(home) as app:
            Path(root, 'sample.sql').write_text('SELECT 7 AS sample;')
            app.configure_plugin('file', True)
            task = app.repo.create_task('SQL 文件链路')['task_id']
            app.repo.update_task(task, name="SQL 文件链路", input_schema={'type': 'object', 'properties': {'file_root': {'type': 'string', 'default': root}}})
            first = app.repo.save_step(task, {'name': '读取 SQL', 'capabilities': ['file.read'],
                'step_content': 'async def run(ctx, inputs):\n    result = await ctx.call("file.read", {"path":"sample.sql"})\n    return ctx.result(data=result)'})
            second = app.repo.save_step(task, {'name': '接收 SQL',
                'input_schema': {'type': 'object', 'properties': {'sql': {'type': 'string'}}, 'required': ['sql']},
                'bindings': {'sql': {'ref': {'source': 'step', 'step_id': first['step_id'], 'output': 'data', 'pointer': '/content'}}},
                'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data={"received_sql": inputs["sql"]})'})
            for step in (first, second):
                app.confirm_step_manual(step['step_id'], step['content_hash'])
            run = app.create_run(task)
            app.coordinator.start(run['run_id'], uid())
            finished = app.coordinator.wait(run['run_id'])
            self.assertEqual(finished['status'], 'SUCCEEDED', finished['attempts'])
            self.assertEqual(app.repo.read_output(run['run_id'], second['step_id'])['received_sql'], 'SELECT 7 AS sample;')

    def test_invalid_json_and_empty_csv_headers_fail_as_format_errors(self):
        from taskweave_file import FilePlugin
        with tempfile.TemporaryDirectory() as root:
            action = FilePlugin().actions()['file.read']
            ctx = SimpleNamespace(environment={'file_root': root}, task_parameters={}, cancelled=lambda: False)
            for name, text, format in [('bad.json', '{"n":NaN}', 'json'), ('bad.csv', ',count\nsample,2\n', 'csv')]:
                Path(root, name).write_text(text)
                with self.subTest(name=name):
                    with self.assertRaises(TaskError) as raised:
                        asyncio.run(action.execute(ctx, {'path': name, 'format': format}))
                    self.assertEqual(raised.exception.code, 'FILE_FORMAT_INVALID')
