"""Real local processes and host-owned file persistence; no external tools."""
import asyncio
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from taskweave.core.ports import ResultRequest, Scope, StepResult
from taskweave.core.validation import TaskError, validate
from taskweave.infrastructure.storage import Results, uid
from taskweave.infrastructure.worker import PluginContext, Resources
from taskweave.plugins.registry import Registry
from taskweave_process import ProcessPlugin
from taskweave_process.runner import ProcessError, run_command
from taskweave_process.artifacts import stage_artifact


class OwnedProcessSessionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from types import SimpleNamespace
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.cancel=threading.Event()
        self.ctx=SimpleNamespace(cancelled=self.cancel.is_set,log=lambda *args,**kw:None,
                                 redaction_values=('synthetic-secret',))

    async def start(self,source,**options):
        import taskweave_process
        self.assertTrue(hasattr(taskweave_process,'OwnedProcessSession'),'Persistent owned process library missing')
        session=await taskweave_process.OwnedProcessSession.start(self.ctx,sys.executable,
            ['-u','-c',source],cwd=self.temp.name,env={},**options)
        self.addAsyncCleanup(session.close)
        return session

    async def test_bidirectional_lines_and_idempotent_close(self):
        session=await self.start('import sys\nfor line in sys.stdin: print(line.strip(),flush=True)')
        await session.write_line(b'{"request":1}',timeout_seconds=1)
        self.assertEqual(await session.read_line(timeout_seconds=1),b'{"request":1}')
        await session.close();await session.close()
        self.assertIsNotNone(session.process.returncode)

    async def test_oversize_frame_fails_and_reaps_owned_process(self):
        session=await self.start('import sys,time;print("x"*2048,flush=True);time.sleep(30)',max_line_bytes=1024)
        with self.assertRaises(ProcessError) as error:await session.read_line(timeout_seconds=1)
        self.assertEqual(error.exception.code,'PROCESS_FRAME_TOO_LARGE')
        self.assertIsNotNone(session.process.returncode)

    async def test_stderr_is_drained_redacted_before_clip(self):
        session=await self.start('import sys,time;sys.stderr.write("x"*1018+"synthetic-secret"+"z"*200000);sys.stderr.flush();print("ready",flush=True);time.sleep(30)',max_stderr_bytes=1024)
        self.assertEqual(await session.read_line(timeout_seconds=2),b'ready')
        await asyncio.sleep(.1)
        self.assertNotIn('synthetic',session.stderr_result()['stderr'])
        self.assertTrue(session.stderr_result()['stderr_truncated'])

    async def test_deadline_reaps_descendants_holding_streams(self):
        source='import subprocess,sys;subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"]);print("ready",flush=True)'
        session=await self.start(source);self.assertEqual(await session.read_line(timeout_seconds=1),b'ready')
        started=time.monotonic()
        with self.assertRaises(ProcessError):await session.read_line(timeout_seconds=1)
        self.assertLess(time.monotonic()-started,3)
        self.assertIsNotNone(session.process.returncode)

    async def test_cancelled_session_releases_owned_tree(self):
        session=await self.start('import time;time.sleep(30)');self.cancel.set()
        with self.assertRaises(ProcessError) as error:await session.read_line(timeout_seconds=1)
        self.assertEqual(error.exception.code,'CANCELLED');self.assertIsNotNone(session.process.returncode)

    async def test_idle_stdout_protocol_failure_reaps_without_caller_read(self):
        for source in ('import time;print("x"*2048,flush=True);time.sleep(30)',
                       'import os,time;os.write(1,b"unfinished");os.close(1);time.sleep(30)',
                       'import time;print("line\\n"*20,flush=True);time.sleep(30)'):
            session=await self.start(source,max_line_bytes=1024)
            await asyncio.sleep(.4)
            with self.subTest(source=source):self.assertIsNotNone(session.process.returncode)


class ProcessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.registry = Registry([ProcessPlugin()])
        self.results = Results(self.root / 'host', Scope(uid(), uid(), uid(), uid()), self.registry)
        self.cancel = threading.Event()
        self.events = []
        self.ctx = PluginContext(self.results.scope, self.results, Resources(self.registry),
                                 {'process_root': str(self.root)}, {'password': 'env:TASKWEAVE_TEST_SECRET'},
                                 self.cancel, lambda kind, payload: self.events.append((kind, payload)))

    async def command(self, script, *args, **options):
        return await run_command(self.ctx, sys.executable, ['-c', script, *args],
                                 cwd=str(self.root), env={}, stdin=options.pop('stdin', None), **options)

    async def test_argv_and_stdin_are_literal(self):
        result = await self.command('import sys,json; print(json.dumps(sys.argv[1:])); print(sys.stdin.read())',
                                    'a;echo bad', stdin=b'literal input')
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(result['stdout'], '["a;echo bad"]\nliteral input\n')

    async def test_nonzero_exit_is_reported(self):
        result = await self.command('import sys; print("failure",file=sys.stderr); sys.exit(7)')
        self.assertEqual(result['exit_code'], 7)
        self.assertEqual(result['stderr'], 'failure\n')

    async def test_output_budget_drains_both_streams(self):
        result = await self.command('import os; [(os.write(1,b"x"*8192),os.write(2,b"y"*8192)) for _ in range(32)]')
        self.assertEqual(result['exit_code'], 0)
        for stream in ('stdout', 'stderr'):
            self.assertLessEqual(len(result[stream].encode()), 65536)
            self.assertTrue(result[stream + '_truncated'])

    async def test_unicode_output_stays_within_byte_budget(self):
        result = await self.command('print("界"*1000)', max_output_bytes=1024)
        self.assertLessEqual(len(result['stdout'].encode()), 1024)
        self.assertTrue(result['stdout_truncated'])

    async def test_cancel_before_start_has_no_effect(self):
        self.cancel.set()
        with self.assertRaises(ProcessError) as raised:
            await self.command('from pathlib import Path; Path("probe").write_text("started")')
        self.assertEqual(raised.exception.code, 'CANCELLED')
        self.assertFalse((self.root / 'probe').exists())
        self.assertIsNone(raised.exception.result)

    def tree_script(self, parent_exits=False):
        child = 'import os,time; from pathlib import Path; Path("child.pid").write_text(str(os.getpid())); time.sleep(3); Path("probe").write_text("escaped"); time.sleep(60)'
        return ('import subprocess,sys,time,os; from pathlib import Path; '
                'Path("parent.pid").write_text(str(os.getpid())); '
                f'subprocess.Popen([sys.executable,"-c",{child!r}]); '
                + ('time.sleep(.2)' if parent_exits else 'time.sleep(60)'))

    async def wait_started(self):
        for _ in range(200):
            if (self.root / 'child.pid').exists():
                return
            await asyncio.sleep(.01)
        self.fail('test child did not start')

    async def assert_tree_stopped(self):
        for name in ('parent.pid', 'child.pid'):
            pid = int((self.root / name).read_text())
            for _ in range(100):
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                # Orphaned zombies are dead; only the OS parent can reap them.
                process = await asyncio.create_subprocess_exec('ps', '-o', 'stat=', '-p', str(pid), stdout=asyncio.subprocess.PIPE)
                state, _ = await process.communicate()
                if not state.strip() or state.strip().startswith(b'Z'):
                    break
                await asyncio.sleep(.02)
            else:
                self.fail(f'process {pid} still running')
        self.assertFalse((self.root / 'probe').exists())

    @unittest.skipUnless(os.name == 'posix', 'POSIX PID/tree inspection')
    async def test_timeout_reaps_descendants_holding_pipes(self):
        with self.assertRaises(ProcessError) as raised:
            await asyncio.wait_for(self.command(self.tree_script(parent_exits=True), timeout_seconds=1), 5)
        self.assertEqual(raised.exception.code, 'PROCESS_TIMEOUT')
        self.assertIsNotNone(raised.exception.result)
        self.assertEqual(raised.exception.effect_state, 'UNKNOWN')
        await self.assert_tree_stopped()

    @unittest.skipUnless(os.name == 'posix', 'POSIX PID/tree inspection')
    async def test_cancel_reaps_process_tree(self):
        task = asyncio.create_task(self.command(self.tree_script()))
        await self.wait_started()
        self.cancel.set()
        with self.assertRaises(ProcessError) as raised:
            await asyncio.wait_for(task, 5)
        self.assertEqual(raised.exception.code, 'CANCELLED')
        await self.assert_tree_stopped()

    @unittest.skipUnless(os.name == 'posix', 'POSIX PID/tree inspection')
    async def test_outer_task_cancel_reaps_process_tree(self):
        task = asyncio.create_task(self.command(self.tree_script()))
        await self.wait_started()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError) as raised:
            await task
        self.assertIsNotNone(raised.exception.result)
        self.assertEqual(raised.exception.effect_state, 'UNKNOWN')
        await self.assert_tree_stopped()

    async def test_command_failure_evidence_does_not_cross_attempts(self):
        plugin = self.registry.plugins[0]
        command = 'import time; from pathlib import Path; print("partial",flush=True); Path("started").touch(); time.sleep(60)'
        task = asyncio.create_task(self.registry.actions['process.run'].execute(self.ctx,
            {'executable': sys.executable, 'args': ['-c', command]}))
        for _ in range(200):
            if (self.root / 'started').exists():
                break
            await asyncio.sleep(.01)
        self.assertTrue((self.root / 'started').exists())
        self.cancel.set()
        with self.assertRaises(ProcessError):
            await task
        requests = await plugin.failure_results(self.ctx, None)
        self.assertEqual(len(requests), 1)
        self.assertIn('partial', requests[0].payload['result']['stdout'])
        self.ctx.scope = replace(self.ctx.scope, attempt_id=uid())
        self.assertEqual(await plugin.failure_results(self.ctx, None), [])

    @unittest.skipUnless(os.name == 'posix', 'POSIX PID/tree inspection')
    async def test_cancel_during_spawn_preserves_ownership_and_reaps_tree(self):
        original = asyncio.create_subprocess_exec
        release = asyncio.Event()
        spawned = []

        async def delayed_spawn(*args, **kwargs):
            process = await original(*args, **kwargs)
            spawned.append(process)
            await release.wait()
            return process

        task = None
        try:
            with patch('taskweave_process.runner.asyncio.create_subprocess_exec', side_effect=delayed_spawn):
                task = asyncio.create_task(self.command(self.tree_script()))
                await self.wait_started()
                task.cancel()
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            await self.assert_tree_stopped()
        finally:
            if task is not None and not task.done():
                task.cancel()
            for process in spawned:
                try:
                    os.killpg(process.pid, 9)
                except ProcessLookupError:
                    pass
                await process.communicate()

    async def test_secret_echo_is_redacted_in_output_and_logs(self):
        secret = 'special-S3cr3t-value'
        action = self.registry.actions['process.run']
        with patch.dict(os.environ, {'TASKWEAVE_TEST_SECRET': secret}):
            result = await action.execute(self.ctx, {'executable': sys.executable,
                'args': ['-c', 'import os,sys; print(os.environ["CHILD_PASSWORD"]); print(sys.stdin.read(),file=sys.stderr)'],
                'env_secret_refs': {'CHILD_PASSWORD': 'password'}, 'stdin_secret_ref': 'password'})
        self.assertNotIn(secret, json.dumps(result))
        self.assertNotIn(secret, json.dumps(self.events))
        self.assertIn('[REDACTED]', result['stdout'])
        self.assertIn('[REDACTED]', result['stderr'])
        self.assertEqual(result['exit_code'], 0)
        validate(result, action.spec.output_schema)

    async def test_missing_secret_reference_never_starts_command(self):
        with self.assertRaises(TaskError) as raised:
            await self.registry.actions['process.run'].execute(self.ctx, {'executable': sys.executable,
                'args': ['-c', 'from pathlib import Path; Path("probe").touch()'], 'stdin_secret_ref': 'unmapped'})
        self.assertEqual(raised.exception.code, 'SECRET_UNAVAILABLE')
        self.assertFalse((self.root / 'probe').exists())

    async def test_path_escape_and_invalid_limits_prevent_execution(self):
        with tempfile.TemporaryDirectory() as outside:
            (self.root / 'outside').symlink_to(outside)
            for cwd in (outside, str(self.root / 'outside')):
                with self.assertRaises(TaskError):
                    await self.registry.actions['process.run'].execute(self.ctx, {'executable': sys.executable, 'cwd': cwd, 'args': ['-c', 'print(1)']})
        for options in ({'timeout_seconds': 0}, {'max_output_bytes': 100}, {'max_output_bytes': 1048577}):
            with self.subTest(options=options), self.assertRaises(TaskError):
                await self.command('print(1)', **options)

    async def test_missing_program_and_directory_are_structured_errors(self):
        with self.assertRaises(ProcessError) as raised:
            await run_command(self.ctx, 'taskweave-absent-program-42', [], cwd=str(self.root), env={}, stdin=None)
        self.assertEqual(raised.exception.code, 'PROCESS_EXECUTABLE_NOT_FOUND')
        with self.assertRaises(ProcessError) as raised:
            await run_command(self.ctx, sys.executable, [], cwd=str(self.root / 'absent'), env={}, stdin=None)
        self.assertEqual(raised.exception.code, 'PROCESS_DIRECTORY_INVALID')

    async def test_artifact_escape_and_oversize_do_not_stage_partial_files(self):
        with tempfile.TemporaryDirectory() as outside:
            Path(outside, 'private').write_bytes(b'private')
            (self.root / 'link').symlink_to(Path(outside, 'private'))
            (self.root / 'large').write_bytes(b'x' * 100)
            for path, limit in [('link', 1000), ('../private', 1000), ('large', 10)]:
                with self.subTest(path=path), self.assertRaises(TaskError):
                    await stage_artifact(self.ctx, str(self.root), path, max_bytes=limit)
        self.assertFalse(self.results.tokens)

    async def test_artifact_is_committed_only_when_included_in_host_result(self):
        (self.root / 'report.txt').write_bytes(b'evidence')
        action = self.registry.actions['process.collect_artifacts']
        output = await action.execute(self.ctx, {'paths': ['report.txt']})
        validate(output, action.spec.output_schema)
        artifact = output['artifacts'][0]
        self.assertEqual(artifact['checksum'], hashlib.sha256(b'evidence').hexdigest())
        self.assertEqual(artifact['size_bytes'], 8)
        self.assertNotIn('local_path', artifact)
        self.assertFalse((self.results.root / 'artifacts').exists())
        refs = self.results.persist(StepResult(outputs=[ResultRequest('process.file', 'report', artifact)]))
        self.assertEqual(refs[0]['kind'], 'file')
        self.assertEqual((self.results.root / refs[0]['locator']).read_bytes(), b'evidence')
        self.assertEqual(refs[0]['media_type'], 'text/plain')

    async def test_environment_and_context_are_read_only_and_bounded(self):
        output = await self.registry.actions['process.check_environment'].execute(self.ctx,
            {'programs': [{'executable': sys.executable, 'version_args': ['--version']}, {'executable': 'taskweave-absent-42'}], 'directories': ['.']})
        self.assertTrue(output['programs'][0]['available'])
        self.assertFalse(output['programs'][1]['available'])
        self.assertTrue(output['directories'][0]['available'])
        context = await ProcessPlugin().collect_context('process.environment', self.ctx,
            {'programs': [{'executable': sys.executable, 'version_args': ['--version']}]}, include_view=False)
        self.assertTrue(context.items)
        self.assertFalse(context.views)
        request = {'programs': [{'executable': sys.executable,
            'version_args': ['-c', 'from pathlib import Path; Path("probe").touch()']}]}
        await ProcessPlugin().collect_context('process.environment', self.ctx, request)
        await ProcessPlugin().tools()['process.inspect_environment'].execute(self.ctx, request)
        self.assertFalse((self.root / 'probe').exists())

    async def test_context_byte_budget_limits_model_items_and_views(self):
        context = await ProcessPlugin().collect_context('process.environment', self.ctx,
            {'programs': [{'executable': 'missing-' + 'x' * 100}] * 32, 'max_output_bytes': 1024})
        self.assertLessEqual(len(context.items[0].content.encode()), 1024)
        self.assertTrue(context.items[0].truncated)
        self.assertLessEqual(len(json.dumps(context.views[0].data, ensure_ascii=False).encode()), 1024)

    async def test_artifact_count_and_aggregate_budget_are_checked_before_staging(self):
        (self.root / 'one').write_bytes(b'x' * 8)
        (self.root / 'two').write_bytes(b'y' * 8)
        for inputs in ({'paths': ['one', 'two'], 'max_total_bytes': 10}, {'paths': ['one'] * 101}):
            with self.subTest(inputs=inputs), self.assertRaises(TaskError):
                await self.registry.actions['process.collect_artifacts'].execute(self.ctx, inputs)
        self.assertFalse(self.results.tokens)

    async def test_empty_artifact_after_exact_aggregate_budget_is_valid(self):
        (self.root / 'one').write_bytes(b'12345678')
        (self.root / 'empty').write_bytes(b'')
        output = await self.registry.actions['process.collect_artifacts'].execute(self.ctx,
            {'paths': ['one', 'empty'], 'max_total_bytes': 8})
        self.assertEqual(output['total_bytes'], 8)
        self.assertEqual([item['size_bytes'] for item in output['artifacts']], [8, 0])

    async def test_cancel_while_staging_waits_for_writer_before_removing_file(self):
        (self.root / 'report.txt').write_bytes(b'evidence')
        original = Path.write_bytes
        started, release = threading.Event(), threading.Event()

        def delayed_write(path, data):
            started.set()
            release.wait(3)
            return original(path, data)

        with patch.object(Path, 'write_bytes', delayed_write):
            task = asyncio.create_task(stage_artifact(self.ctx, str(self.root), 'report.txt', max_bytes=100))
            for _ in range(100):
                if started.is_set():
                    break
                await asyncio.sleep(.01)
            self.assertTrue(started.is_set())
            task.cancel()
            await asyncio.sleep(.05)
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
            await asyncio.sleep(.05)
        self.assertFalse(any(path.exists() for path in self.results.tokens.values()))


class ProcessWorkerTests(unittest.TestCase):
    def run_failed_command(self, *, cancel):
        from taskweave.application.service import Application
        secret = 'worker-secret-never-persist-this'
        with patch.dict(os.environ, {'TASKWEAVE_WORKER_TEST_SECRET': secret}), tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as root, Application(home) as app:
            app.configure_plugin('process', True)
            env = app.repo.save_environment('process failure evidence', {'process_root': root},
                {'command_token': 'env:TASKWEAVE_WORKER_TEST_SECRET'})['environment_id']
            task = app.repo.create_task('process failure evidence')['task_id']
            command = ('import os,sys,time; from pathlib import Path; '
                'print("partial success",flush=True); print(os.environ["CHILD_TOKEN"],flush=True); '
                'print("x"*2000,flush=True); '
                'print("partial stderr "+os.environ["CHILD_TOKEN"],file=sys.stderr,flush=True); '
                'print("y"*2000,file=sys.stderr,flush=True); Path("started").touch(); time.sleep(60)')
            inputs = {'executable': sys.executable, 'args': ['-c', command],
                'env_secret_refs': {'CHILD_TOKEN': 'command_token'},
                'timeout_seconds': 60 if cancel else 1, 'max_output_bytes': 1024}
            step = app.repo.save_step(task, {'name': 'partial progress then stop', 'capabilities': ['process.run'],
                'step_content': 'async def run(ctx, inputs):\n'
                    f'    execution = await ctx.call("process.run", {inputs!r})\n'
                    '    return ctx.result(data=execution)'})
            app.confirm_step_manual(step['step_id'], step['content_hash'], environment_id=env)
            run = app.create_run(task, environment_id=env)
            app.coordinator.start(run['run_id'], uid())
            if cancel:
                deadline = time.monotonic() + 5
                while not Path(root, 'started').exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(Path(root, 'started').exists(), 'command must start before cancellation')
                app.coordinator.control(run['run_id'], uid(), 'cancel')
            finished = app.coordinator.wait(run['run_id'], 8)
            self.assertEqual(finished['status'], 'FAILED', finished)
            attempt = finished['attempts'][0]
            self.assertEqual(attempt['status'], 'FAILED')
            self.assertEqual(attempt['effect_state'], 'UNKNOWN')
            self.assertEqual(attempt['error_code'], 'CANCELLED' if cancel else 'PROCESS_TIMEOUT')
            refs = app.repo.repositories.results.refs_for_attempt(attempt['attempt_id'])
            self.assertEqual(len(refs), 1, 'partial output must survive the host failure boundary')
            self.assertEqual(refs[0]['handler_id'], 'process.command_failure')
            saved = app.repo.read_result(refs[0]['result_id'], Registry([ProcessPlugin()]))['data']
            self.assertEqual(saved['error_code'], attempt['error_code'])
            self.assertEqual(saved['effect_state'], 'UNKNOWN')
            self.assertIn('partial success', saved['result']['stdout'])
            self.assertIn('partial stderr', saved['result']['stderr'])
            self.assertIn('[REDACTED]', saved['result']['stdout'])
            self.assertIn('[REDACTED]', saved['result']['stderr'])
            self.assertNotIn(secret, json.dumps(saved))
            for stream in ('stdout', 'stderr'):
                self.assertLessEqual(len(saved['result'][stream].encode()), 1024)
                self.assertTrue(saved['result'][stream + '_truncated'])
            with self.assertRaisesRegex(TaskError, 'OUTPUT_NOT_AVAILABLE'):
                app.repo.read_output(run['run_id'], step['step_id'])

    def test_real_worker_timeout_preserves_redacted_partial_diagnostic(self):
        self.run_failed_command(cancel=False)

    def test_real_worker_cancel_preserves_redacted_partial_diagnostic(self):
        self.run_failed_command(cancel=True)

    def test_real_worker_executes_and_commits_artifact(self):
        from taskweave.application.service import Application
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as root, Application(home) as app:
            app.configure_plugin('process', True)
            task = app.repo.create_task('process evidence')['task_id']
            app.repo.update_task(task, name='process evidence', input_schema={'type': 'object', 'properties': {
                'process_root': {'type': 'string', 'default': root}}})
            code = 'from pathlib import Path; Path("report.txt").write_text("worker evidence"); print("completed")'
            inputs = {'executable': sys.executable, 'args': ['-c', code]}
            step = app.repo.save_step(task, {'name': 'execute and collect',
                'capabilities': ['process.run', 'process.collect_artifacts', 'process.file'],
                'step_content': 'async def run(ctx, inputs):\n'
                    f'    execution = await ctx.call("process.run", {inputs!r})\n'
                    '    collection = await ctx.call("process.collect_artifacts", {"paths": ["report.txt"]})\n'
                    '    return ctx.result(data=execution, outputs=[ctx.output("process.file", "report", collection["artifacts"][0])])'})
            app.confirm_step_manual(step['step_id'], step['content_hash'])
            run = app.create_run(task)
            app.coordinator.start(run['run_id'], uid())
            finished = app.coordinator.wait(run['run_id'])
            self.assertEqual(finished['status'], 'SUCCEEDED', finished['attempts'])
            self.assertEqual(app.repo.read_output(run['run_id'], step['step_id'])['stdout'], 'completed\n')
            artifacts = list((Path(home) / 'tasks' / task / 'artifacts').rglob('report'))
            self.assertEqual(len(artifacts), 1)
            self.assertEqual(artifacts[0].read_text(), 'worker evidence')
