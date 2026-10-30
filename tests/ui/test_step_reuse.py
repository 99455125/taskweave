"""Step reuse uses real application writes and explicit dependency resolution."""
import asyncio
import inspect
import json
from unittest.mock import AsyncMock
from nicegui.client import Client
from nicegui.page import page
from tests._core_fixture import CoreFixture
from taskweave.desktop.controller import DesktopController
from taskweave.desktop.components.step_reuse import show_step_reuse


class StepReuseUITests(CoreFixture):
    def setUp(self):
        super().setUp()
        self.task_id = self.task()
        self.source = self.step(self.task_id, bindings={'value': {'literal': 'kept'}})
        self.client = Client(page('/reuse-test'))
        self.controller = DesktopController(self.app)
        self.created = AsyncMock()

    def tearDown(self):
        self.client.delete()
        super().tearDown()

    def scenario(self, fn):
        async def run():
            with self.client: await fn()
        asyncio.run(run())

    async def open(self, target=None):
        target = target or self.task_id
        flow = self.app.tasks.flow(target)
        return await show_step_reuse(self.controller, task_id=target,
            parent_id=flow['root']['id'], index=len(flow['root']['children']), expected_flow=flow,
            is_current=lambda: True, on_created=self.created)

    @staticmethod
    def field(dialog, label):
        return next(e for e in dialog.descendants() if e._props.get('label') == label)

    @staticmethod
    async def click(dialog, label):
        button = next(e for e in dialog.descendants() if getattr(e, 'text', '') == label)
        handler = next(e.handler for e in button._event_listeners.values() if e.type == 'click')
        result = inspect.getclosurevars(handler).nonlocals['callback']()
        if inspect.iscoroutine(result): await result

    async def change(self, control, value):
        handlers = control._change_handlers
        control._change_handlers = []
        control.value = value
        control._change_handlers = handlers
        for handler in handlers:
            result = handler()
            if inspect.iscoroutine(result): await result

    async def select_source(self, dialog):
        await self.change(self.field(dialog, '来源任务'), self.task_id)
        await self.change(self.field(dialog, '来源步骤'), self.source['step_id'])

    def test_current_task_reuse_preserves_bindings_and_cancel_does_not_write(self):
        async def run():
            dialog = await self.open()
            await self.click(dialog, '取消')
            self.assertEqual(len(self.app.steps.list(self.task_id)), 1)
            dialog = await self.open()
            await self.click(dialog, '确认复用')
            self.created.assert_awaited_once()
            self.assertEqual(self.created.await_args.args[0]['bindings'], self.source['bindings'])
            self.assertEqual(len(self.app.steps.list(self.task_id)), 2)
        self.scenario(run)

    def cross_source(self):
        upstream = self.source
        self.source = self.step(self.task_id, bindings={'value': {'ref': {'source': 'step', 'step_id': upstream['step_id'], 'pointer': '/value'}}})
        target = self.app.repo.create_task('Destination')['task_id']
        target_step = self.step(target)
        return target, target_step

    def test_cross_task_requires_mapping_and_accepts_target_step(self):
        target, target_step = self.cross_source()
        async def run():
            dialog = await self.open(target)
            await self.select_source(dialog)
            await self.click(dialog, '确认复用')
            self.assertEqual(len(self.app.steps.list(target)), 1)
            self.assertTrue(dialog.value)
            self.field(dialog, '输入 value 的依赖处理').value = target_step['step_id']
            await self.click(dialog, '确认复用')
            self.created.assert_awaited_once()
            self.assertEqual(self.created.await_args.args[0]['bindings']['value']['ref']['step_id'], target_step['step_id'])
        self.scenario(run)

    def test_cross_task_can_delete_binding_without_removing_input_schema(self):
        target, _ = self.cross_source()
        self.source = self.app.steps.save(self.task_id, {**self.source, 'input_schema': {'type': 'object', 'properties': {'value': {'type': 'string'}}}}, self.source['step_id'], self.source['content_hash'])
        async def run():
            dialog = await self.open(target)
            await self.select_source(dialog)
            selector = self.field(dialog, '输入 value 的依赖处理')
            selector.value = next(key for key, value in selector.options.items() if value == '删除依赖绑定')
            await self.click(dialog, '确认复用')
            new = self.created.await_args.args[0]
            self.assertEqual(new['bindings'], {})
            self.assertIn('value', new['input_schema']['properties'])
        self.scenario(run)

    def test_double_submit_creates_once(self):
        async def run():
            dialog = await self.open()
            original = self.controller.call
            entered, release = asyncio.Event(), asyncio.Event()
            async def blocked(operation, **params):
                if operation == 'step.reuse':
                    entered.set()
                    await release.wait()
                return await original(operation, **params)
            self.controller.call = blocked
            pending = asyncio.create_task(self.click(dialog, '确认复用'))
            await entered.wait()
            self.assertTrue(dialog._props.get('no-backdrop-dismiss'))
            self.assertFalse(self.field(dialog, '目标输入绑定（JSON）').enabled)
            self.assertFalse(dialog._props.get('persistent'))
            await self.click(dialog, '取消')
            self.assertTrue(dialog.value)
            await self.click(dialog, '确认复用')
            release.set()
            await pending
            self.created.assert_awaited_once()
            self.assertEqual(len(self.app.steps.list(self.task_id)), 2)
        self.scenario(run)

    def test_late_source_response_cannot_replace_new_selection(self):
        other = self.app.repo.create_task('Other')['task_id']
        latest = self.step(other, bindings={'value': {'literal': 'latest'}})
        async def run():
            dialog = await self.open()
            original = self.controller.call
            entered, release = asyncio.Event(), asyncio.Event()
            async def blocked(operation, **params):
                if operation == 'step.get' and params['step_id'] == self.source['step_id']:
                    entered.set()
                    await release.wait()
                return await original(operation, **params)
            self.controller.call = blocked
            pending = asyncio.create_task(self.change(self.field(dialog, '来源步骤'), self.source['step_id']))
            await entered.wait()
            await self.change(self.field(dialog, '来源任务'), other)
            release.set()
            await pending
            self.assertEqual(self.field(dialog, '来源步骤').value, latest['step_id'])
            self.assertEqual(json.loads(self.field(dialog, '目标输入绑定（JSON）').value), latest['bindings'])
            self.created.assert_not_called()
        self.scenario(run)

    def test_invalid_json_and_concurrent_source_edit_preserve_dialog(self):
        async def run():
            dialog = await self.open()
            bindings = self.field(dialog, '目标输入绑定（JSON）')
            bindings.value = '{invalid'
            await self.click(dialog, '确认复用')
            self.assertEqual(bindings.value, '{invalid')
            self.assertTrue(dialog.value)
            self.assertEqual(len(self.app.steps.list(self.task_id)), 1)
            bindings.value = json.dumps(self.source['bindings'])
            self.app.steps.save(self.task_id, {**self.source, 'name': 'Concurrent'}, self.source['step_id'], self.source['content_hash'])
            await self.click(dialog, '确认复用')
            self.assertTrue(dialog.value)
            self.assertEqual(len(self.app.steps.list(self.task_id)), 1)
            self.created.assert_not_called()
        self.scenario(run)

    def test_stale_canvas_slot_is_rejected_before_opening_dialog(self):
        from taskweave.core.validation import TaskError
        from taskweave.presentation.flow_editor import move_node
        async def run():
            other = self.step(self.task_id)
            old = self.app.tasks.flow(self.task_id)
            moved = move_node(old, other['step_id'], 'root', 0)
            self.app.tasks.save_flow(self.task_id, moved, self.app.tasks.describe_flow(self.task_id)['definition_hash'])
            with self.assertRaises(TaskError) as raised:
                await show_step_reuse(self.controller, task_id=self.task_id, parent_id='root', index=1,
                    expected_flow=old, is_current=lambda: True, on_created=self.created)
            self.assertEqual(raised.exception.code, 'EDIT_CONFLICT')
            self.assertEqual(self.app.tasks.flow(self.task_id), moved)
            self.created.assert_not_awaited()
        self.scenario(run)

    def test_searchable_sources_collapsed_previews_and_fixed_footer(self):
        from nicegui import ui
        async def run():
            dialog = await self.open()
            self.assertTrue(self.field(dialog, '来源任务')._props.get('use-input'))
            self.assertTrue(self.field(dialog, '来源步骤')._props.get('use-input'))
            expansions = {e._props.get('label'): e for e in dialog.descendants() if isinstance(e, ui.expansion)}
            for label in ('步骤代码预览', '高级编辑：完整输入绑定 JSON'):
                self.assertIn(label, expansions)
                self.assertFalse(expansions[label].value)
            footer = next(e for e in dialog.descendants() if 'tw-step-operation-footer' in e.classes)
            self.assertTrue(any(getattr(e, 'text', '') == '确认复用' for e in footer.descendants()))
            self.assertTrue(any('text-negative' in e.classes for e in footer.descendants()))
        self.scenario(run)

    def test_missing_source_has_clear_state_and_cannot_confirm(self):
        async def run():
            dialog = await self.open()
            await self.change(self.field(dialog, '来源步骤'), None)
            self.assertIn('请选择来源步骤，查看依赖后再复制。', [getattr(e, 'text', '') for e in dialog.descendants()])
            confirm = next(e for e in dialog.descendants() if getattr(e, 'text', '') == '确认复用')
            self.assertFalse(confirm.enabled)
            self.created.assert_not_awaited()
        self.scenario(run)

    def test_dependency_candidates_match_destination_branch_scope(self):
        target, before = self.cross_source()
        local = self.step(target, name='当前分支前一步')
        sibling = self.step(target, name='兄弟分支步骤')
        after = self.step(target, name='后续步骤')
        def action(step):
            return {'id': step['step_id'], 'kind': 'action', 'step_id': step['step_id']}
        def body(identity, step):
            return {'id': identity, 'kind': 'sequence', 'children': [action(step)]}
        flow = {'version': 2, 'root': {'id': 'root', 'kind': 'sequence', 'children': [action(before),
            {'id': 'branch', 'kind': 'if', 'cases': [{'id': 'match', 'condition': {'op': 'exists', 'value': {'literal': True}},
             'body': body('yes', local)}], 'default': {'id': 'default', 'body': body('no', sibling)}}, action(after)]}}
        self.app.tasks.save_flow(target, flow, self.app.tasks.describe_flow(target)['definition_hash'])
        async def run():
            dialog = await show_step_reuse(self.controller, task_id=target, parent_id='yes', index=1,
                expected_flow=flow, is_current=lambda: True, on_created=self.created)
            await self.select_source(dialog)
            choices = self.field(dialog, '输入 value 的依赖处理').options
            self.assertIn(before['step_id'], choices)
            self.assertIn(local['step_id'], choices)
            self.assertTrue(choices[before['step_id']].startswith('1 · '))
            self.assertTrue(choices[local['step_id']].startswith('2 · '))
            self.assertNotIn(sibling['step_id'], choices)
            self.assertNotIn(after['step_id'], choices)
            header = next(e for e in dialog.descendants() if 'tw-step-operation-header' in e.classes)
            text = ' '.join(getattr(e, 'text', '') for e in header.descendants())
            self.assertIn('Destination', text)
            self.assertIn('分支 1', text)
            self.assertIn('当前分支前一步', text)
        self.scenario(run)

    def test_cancelled_dialog_ignores_queued_submit(self):
        async def run():
            dialog = await self.open()
            await self.click(dialog, '取消')
            await self.click(dialog, '确认复用')
            self.created.assert_not_awaited()
            self.assertEqual(len(self.app.steps.list(self.task_id)), 1)
        self.scenario(run)
