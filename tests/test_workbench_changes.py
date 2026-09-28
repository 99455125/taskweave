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
    def test_reorder_helper_swaps_adjacent_items_and_rejects_boundaries(self):
        from taskweave.desktop.components.step_list import reordered_ids

        self.assertEqual(reordered_ids(['a', 'b', 'c'], 1, -1), ['b', 'a', 'c'])
        self.assertEqual(reordered_ids(['a', 'b', 'c'], 1, 1), ['a', 'c', 'b'])
        self.assertIsNone(reordered_ids(['a', 'b'], 0, -1))
        self.assertIsNone(reordered_ids(['a', 'b'], 1, 1))

    def test_task_search_matches_name_and_description(self):
        from taskweave.desktop.workbench import filter_tasks

        tasks = [
            {'name': '合约录入', 'description': '再保平台'},
            {'name': '账单核对', 'description': 'TiDB 数据校验'},
        ]
        self.assertEqual([task['name'] for task in filter_tasks(tasks, '合约')], ['合约录入'])
        self.assertEqual([task['name'] for task in filter_tasks(tasks, 'tidb')], ['账单核对'])
        self.assertEqual(filter_tasks(tasks, '不存在'), [])

    def test_step_reorder_moves_existing_controls_and_updates_visible_positions(self):
        from taskweave.desktop.components.step_list import move_controls, reordered_ids

        steps = [{'name': 'A'}, {'name': 'B'}, {'name': 'C'}]
        controls = [SimpleNamespace(text=f'{i}. {row["name"]}', update=lambda: None, move=lambda *_: None) for i, row in enumerate(steps, 1)]
        moving, adjacent = move_controls(steps, controls, 1, 2, object())
        self.assertEqual([step['name'] for step in steps], ['A', 'C', 'B'])
        self.assertIs(controls[2], moving)
        self.assertIs(controls[1], adjacent)
        self.assertEqual([control.text for control in controls], ['1. A', '2. C', '3. B'])
        self.assertIsNone(reordered_ids(['a', 'b'], 1, 1))

    def test_planning_actions_save_draft_before_dependent_workflow(self):
        from taskweave.desktop.planning import PlanningPage
        from taskweave.desktop.state import PlanningPageState

        events = []
        state = PlanningPageState(save_callback=AsyncMock(side_effect=lambda: events.append('save')))
        page = PlanningPage(AsyncMock(), state, None, None, None, None)
        action = AsyncMock(side_effect=lambda plan, channel: events.append((plan, channel)))
        asyncio.run(page.save_then(action, {'plan_id': 'p1'}, 'api'))
        self.assertEqual(events, ['save', ({'plan_id': 'p1'}, 'api')])

    def test_context_request_merges_form_advanced_and_target_values_in_order(self):
        from taskweave.desktop.contexts import merge_context_request

        self.assertEqual(
            merge_context_request({'url': 'form', 'scope': 'form'}, {'scope': 'advanced', 'token': 'raw'}, {'url': 'target'}),
            {'url': 'target', 'scope': 'advanced', 'token': 'raw'},
        )
        with self.assertRaises(TaskError):
            merge_context_request({}, [], {})

    def test_step_contexts_persist_and_can_be_renamed_or_deleted(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task('contexts')['task_id']
            step = app.repo.save_step(task, {'name': 'collect', 'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data={})'})
            app.confirm_step_manual(step['step_id'], step['content_hash'])
            saved = app.dispatch('context.save', {
                'step_id': step['step_id'], 'provider_id': 'playwright.page',
                'name': '登录页', 'source_page': 'draft',
                'item': {'kind': 'text', 'content': 'page'},
            })
            self.assertEqual(app.repo.step(step['step_id'])['validation_state'], 'DRAFT')

            self.assertEqual(app.dispatch('context.list', {'step_id': step['step_id']})[0]['name'], '登录页')
            app.dispatch('context.save', {
                'context_id': saved['context_id'], 'step_id': saved['step_id'],
                'provider_id': saved['provider_id'], 'source_page': saved['source_page'],
                'name': '登录页面', 'item': saved['item'],
            })
            app.confirm_step_manual(step['step_id'], step['content_hash'])
            self.assertEqual(app.dispatch('context.list', {'step_id': step['step_id']})[0]['name'], '登录页面')
            app.dispatch('context.delete', {'context_id': saved['context_id']})
            self.assertEqual(app.dispatch('context.list', {'step_id': step['step_id']}), [])
            self.assertEqual(app.repo.step(step['step_id'])['validation_state'], 'DRAFT')

    def test_recollection_advanced_json_keeps_only_non_form_parameters(self):
        from taskweave.desktop.contexts import context_advanced_overrides

        schema = {"type": "object", "properties": {"url": {}, "scope": {}}}
        request = {
            "url": "https://example.test", "scope": "full_page",
            "target_id": "page-1", "plugin_private": {"mode": "deep"},
        }
        self.assertEqual(
            context_advanced_overrides(schema, request),
            {"plugin_private": {"mode": "deep"}},
        )

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

    def test_workspace_migration_copies_then_removes_only_after_new_workspace_starts(self):
        from taskweave.desktop.controller import DesktopController
        from taskweave.desktop.launcher import finish_workspace_migration
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            old, new, unrelated = root / 'old', root / 'new', root / 'unrelated'
            marker = root / 'location.json'
            with Application(old) as app:
                app.repo.create_task('migrated')
                controller = DesktopController(app)
                with patch('taskweave.infrastructure.storage.workspace_location_file', return_value=marker):
                    result = asyncio.run(controller.migrate_workspace(new))
            self.assertEqual(result['workspace_home'], str(new.resolve()))
            self.assertTrue((new / 'taskweave.db').exists())
            self.assertTrue(old.exists())
            unrelated.mkdir()
            with patch('taskweave.infrastructure.storage.workspace_location_file', return_value=marker):
                self.assertFalse(finish_workspace_migration(unrelated))
                self.assertTrue(old.exists())
                self.assertTrue(finish_workspace_migration(new))
            self.assertFalse(old.exists())
            self.assertNotIn('remove_after_restart', json.loads(marker.read_text()))

    def test_context_draft_is_committed_once_as_a_batch(self):
        from taskweave.desktop.workbench import Workbench
        from taskweave.desktop.contexts import ContextCaptureDraft

        workbench = Workbench.__new__(Workbench)
        calls = []
        group = {'context_id': 'new-group', 'provider_id': 'fake.page', 'name': '登录页', 'context_notes': '说明', 'revision': 0, 'captures': [{'capture_id': 'saved-one', 'label': '登录页'}]}
        async def call(operation, **params):
            calls.append((operation, params))
            if operation == 'context.save_batch': return {'group': group}
            raise AssertionError(operation)
        workbench.controller = SimpleNamespace(call=call)
        workbench.step_id = uid()
        workbench.contexts = []
        workbench.context_entries = []
        workbench.context_cards = SimpleNamespace(sync_group=lambda saved: None)
        draft = ContextCaptureDraft()
        draft.append({'items': [{'kind': 'text', 'source': 'fake.page', 'content': 'page'}], 'views': [{'title': '页面预览'}]}, {'scope': 'viewport'}, True, 'session', label='登录页')
        self.assertEqual(calls, [])
        asyncio.run(workbench.save_context_batch(None, 'fake.page', '登录页', '说明', draft))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], 'context.save_batch')
        self.assertEqual(calls[0][1]['captures'][0]['capture']['views'][0]['title'], '页面预览')
        self.assertEqual(workbench.context_entries, [group])

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
                edited=app.repo.save_step(task,{**good,'step_description':'changed'},good['step_id'],good['content_hash'])
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
