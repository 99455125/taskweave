import asyncio
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from taskweave.application.service import Application
from taskweave.core.validation import TaskError
from taskweave.infrastructure.storage import uid


class WorkbenchChanges(unittest.TestCase):
    def test_step_contexts_persist_and_can_be_renamed_or_deleted(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task('contexts')['task_id']
            step = app.repo.save_step(task, {'name': 'collect'})
            saved = app.dispatch('context.save', {
                'step_id': step['step_id'], 'provider_id': 'playwright.page',
                'name': '登录页', 'source_page': 'draft',
                'item': {'kind': 'text', 'content': 'page'},
            })
            self.assertEqual(app.dispatch('context.list', {'step_id': step['step_id']})[0]['name'], '登录页')
            app.dispatch('context.save', {
                'context_id': saved['context_id'], 'step_id': saved['step_id'],
                'provider_id': saved['provider_id'], 'source_page': saved['source_page'],
                'name': '登录页面', 'item': saved['item'],
            })
            self.assertEqual(app.dispatch('context.list', {'step_id': step['step_id']})[0]['name'], '登录页面')
            app.dispatch('context.delete', {'context_id': saved['context_id']})
            self.assertEqual(app.dispatch('context.list', {'step_id': step['step_id']}), [])

    def test_executor_thread_setting_persists(self):
        from taskweave.desktop.controller import DesktopController
        with tempfile.TemporaryDirectory() as home:
            with Application(home) as app:
                controller = DesktopController(app)
                self.assertEqual(asyncio.run(controller.workbench_settings())['executor_max_threads'], 8)
                asyncio.run(controller.save_executor_max_threads(3))
                self.assertEqual(app.coordinator.max_concurrency, 3)
            with Application(home) as reopened:
                self.assertEqual(reopened.coordinator.max_concurrency, 3)

    def test_collected_contexts_accumulate_across_plugins_and_delete_one(self):
        from taskweave.desktop.workbench import Workbench

        workbench = Workbench.__new__(Workbench)
        saved = []
        async def call(operation, **params):
            if operation == 'context.save':
                entry = {**params, 'context_id': uid()}
                saved.append(entry)
                return entry
            if operation == 'context.delete':
                saved[:] = [entry for entry in saved if entry['context_id'] != params['context_id']]
                return {'deleted': True}
            raise AssertionError(operation)
        workbench.controller = SimpleNamespace(call=call)
        workbench.step_id = uid()
        workbench.contexts = []
        workbench.context_entries = []
        page = {"kind": "text", "source": "playwright.page", "content": "page"}
        schema = {"kind": "text", "source": "tidb.schema", "content": "orders"}
        second_schema = {"kind": "text", "source": "tidb.schema", "content": "items"}
        asyncio.run(workbench.append_contexts("playwright.page", [page], "draft"))
        asyncio.run(workbench.append_contexts("tidb.schema", [schema, second_schema], "trial_feedback"))
        self.assertEqual(workbench.contexts, [page, schema, second_schema])
        self.assertEqual(
            [entry["provider_id"] for entry in workbench.context_entries],
            ["playwright.page", "tidb.schema", "tidb.schema"],
        )
        asyncio.run(workbench.remove_context_entry(workbench.context_entries[1]))
        self.assertEqual(workbench.contexts, [page, second_schema])

    def test_manual_confirmation_execution_and_scoped_restart(self):
        with tempfile.TemporaryDirectory() as home:
            with Application(home) as app:
                task=app.repo.create_task('restart')['task_id']
                steps=[]
                for index in range(3):
                    step=app.repo.save_step(task,{'name':str(index),'step_content':'async def run(ctx, inputs):\n    return ctx.result(data={"n": '+str(index)+'})'})
                    step=app.confirm_step_manual(step['step_id'],step['content_hash'])
                    self.assertEqual(step['validation_source'],'MANUAL')
                    self.assertFalse(app.repo.query('SELECT 1 FROM step_attempts'))
                    steps.append(step)
                runs=[]
                for _ in range(2):
                    run=app.create_run(task)
                    app.coordinator.start(run['run_id'],uid())
                    self.assertEqual(app.coordinator.wait(run['run_id'])['status'],'SUCCEEDED')
                    runs.append(run['run_id'])
                command=uid()
                app.coordinator.restart(runs[0],command,steps[0]['step_id'])
                result=app.coordinator.wait(runs[0])
                self.assertEqual(result['status'],'PAUSED')
                self.assertEqual(len(result['attempts']),1)
                self.assertEqual(len(app.repo.run_details(runs[1])['attempts']),3)
                with closing(sqlite3.connect(Path(home)/'tasks'/task/'data.db')) as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM step_outputs WHERE run_id=?',(runs[0],)).fetchone()[0],1)
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM step_outputs WHERE run_id=?',(runs[1],)).fetchone()[0],3)
                self.assertEqual(len(app.repo.query('SELECT * FROM command_receipts WHERE run_id=?',(runs[0],))),1)
                app.coordinator.restart(runs[0],command,steps[0]['step_id'])
                self.assertEqual(len(app.repo.run_details(runs[0])['attempts']),1)
                app.coordinator.start(runs[0],uid(),mode='UNTIL',target_step_id=steps[2]['step_id'])
                self.assertEqual(len(app.coordinator.wait(runs[0])['attempts']),3)

    def test_manual_confirmation_rejects_invalid_action_and_edits_invalidate(self):
        with tempfile.TemporaryDirectory() as home:
            with Application(home) as app:
                task=app.repo.create_task('manual')['task_id']
                bad=app.repo.save_step(task,{'name':'bad','step_content':'async def run(ctx, inputs):\n    return ctx.result(data=await ctx.call(action_id="nonexistent", inputs={}))'})
                with self.assertRaises(TaskError):
                    app.confirm_step_manual(bad['step_id'],bad['content_hash'])
                good=app.repo.save_step(task,{'name':'good','step_content':'async def run(ctx, inputs):\n    return ctx.result(data={})'})
                app.confirm_step_manual(good['step_id'],good['content_hash'])
                edited=app.repo.save_step(task,{**good,'goal':'changed'},good['step_id'],good['content_hash'])
                self.assertEqual(edited['validation_state'],'DRAFT')
                self.assertIsNone(edited['validation_source'])

    def test_flow_trial_drafts_and_persisted_dependencies(self):
        with tempfile.TemporaryDirectory() as home:
            with Application(home) as app:
                task = app.repo.create_task('flow')['task_id']
                one = app.repo.save_step(task, {'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data={"n": 7})'})
                two = app.repo.save_step(task, {'input_schema': {'type': 'object', 'properties': {'n': {'type': 'number'}}, 'required': ['n']}, 'bindings': {'n': {'ref': {'source': 'step', 'step_id': one['step_id'], 'pointer': '/n'}}}, 'step_content': 'async def run(ctx, inputs):\n    assert inputs["n"] == 7\n    return ctx.result(data=inputs)'})
                third = app.repo.save_step(task, {'step_content': 'async def run(ctx, inputs):\n    assert False'})
                run = app.trial_flow(two['step_id'], {}, uid())
                done = app.coordinator.wait(run['run_id'])
                self.assertEqual(done['status'], 'SUCCEEDED', done)
                self.assertEqual([a['step_id'] for a in done['attempts']], [one['step_id'], two['step_id']])
                self.assertEqual(app.repo.read_output(run['run_id'], two['step_id'], 'data', app.registry), {'n': 7})
                first_pid = app.coordinator.process.pid
                again = app.trial_flow(two['step_id'], {}, uid())
                self.assertEqual(app.coordinator.wait(again['run_id'])['status'], 'SUCCEEDED')
                self.assertEqual(app.coordinator.process.pid, first_pid)

    def test_failed_trial_edit_and_retry_reuses_task_debug_instance(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task('debug reuse')['task_id']
            step = app.repo.save_step(task, {'step_content': 'async def run(ctx, inputs):\n    assert False, "first"'})
            first = app.trial_step(step['step_id'], {}, uid(), continue_session=True)
            self.assertEqual(app.coordinator.wait(first['run_id'])['status'], 'FAILED')
            first_pid = app.coordinator.process.pid
            self.assertTrue(app.coordinator.describe_run(first['run_id'])['can_end'])
            edited = app.repo.save_step(task, {**step, 'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data={"ok": True})'}, step['step_id'], step['content_hash'])
            second = app.trial_step(edited['step_id'], {}, uid(), continue_session=True)
            self.assertEqual(app.coordinator.wait(second['run_id'])['status'], 'SUCCEEDED')
            self.assertEqual(app.coordinator.process.pid, first_pid)

    def test_restart_clears_live_sessions_keeps_history(self):
        with tempfile.TemporaryDirectory() as home:
            with Application(home) as app:
                task = app.repo.create_task('sessions')['task_id']
                step = app.repo.save_step(task, {'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data={})'})
                run = app.trial_step(step['step_id'], {}, uid())
                app.coordinator.wait(run['run_id'])
                self.assertEqual(len(app.coordinator.context_sessions(task)), 1)
                self.assertTrue(app.coordinator.describe_run(run['run_id'])['can_end'])
            with Application(home) as reopened:
                self.assertEqual(reopened.coordinator.context_sessions(task), [])
                self.assertFalse(reopened.coordinator.describe_run(run['run_id'])['can_end'])
                self.assertEqual(reopened.repo.run_details(run['run_id'])['status'], 'SUCCEEDED')

    def test_end_button_tracks_live_session_not_success_status(self):
        with tempfile.TemporaryDirectory() as home:
            with Application(home) as app:
                task = app.repo.create_task('end')['task_id']
                step = app.repo.save_step(task, {'step_content': 'async def run(ctx, inputs):\n    return ctx.result()'})
                app.confirm_step_manual(step['step_id'], step['content_hash'])
                run = app.create_run(task)
                self.assertFalse(app.dispatch('run.get', {'run_id': run['run_id']})['can_end'])
                app.coordinator.start(run['run_id'], uid())
                app.coordinator.wait(run['run_id'])
                self.assertTrue(app.dispatch('run.get', {'run_id': run['run_id']})['can_end'])
                app.coordinator.control(run['run_id'], uid(), 'abandon')
                details = app.dispatch('run.get', {'run_id': run['run_id']})
                self.assertEqual(details['status'], 'SUCCEEDED')
                self.assertFalse(details['can_end'])

    def test_environment_credentials_use_generic_variable_rows(self):
        with tempfile.TemporaryDirectory() as home:
            with Application(home) as app:
                env=app.repo.save_environment('test',{'base_url':'https://example.com','password':'env:TEST_PASSWORD','roles':['a','b']})
                public,refs=app.repo.environment(env['environment_id'])
                self.assertNotIn('password',public)
                self.assertEqual(refs['password'],'env:TEST_PASSWORD')
                self.assertEqual(public['roles'],['a','b'])

    def test_playwright_task_parameters_override_environment(self):
        from taskweave_playwright import BrowserSession
        page=SimpleNamespace(set_default_timeout=lambda value: None)
        context=SimpleNamespace(new_page=AsyncMock(return_value=page))
        browser=SimpleNamespace(new_context=AsyncMock(return_value=context))
        launch=AsyncMock(return_value=browser)
        runtime=SimpleNamespace(chromium=SimpleNamespace(launch=launch),stop=AsyncMock())
        factory=SimpleNamespace(start=AsyncMock(return_value=runtime))
        ctx=SimpleNamespace(environment={'browser':{'headless':False},'playwright_headless':False},task_parameters={'playwright_headless':True})
        with patch('taskweave_playwright.async_playwright',return_value=factory):
            asyncio.run(BrowserSession().open(ctx,'operator'))
        self.assertTrue(launch.call_args.kwargs['headless'])
        self.assertEqual(browser.new_context.call_args.kwargs['locale'], 'zh-CN')
