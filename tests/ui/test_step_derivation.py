"""Real derivation dialogs preserve drafts and write only on explicit submission."""
import asyncio
import inspect
from unittest.mock import AsyncMock
from nicegui import ui
from nicegui.client import Client
from nicegui.page import page
from tests._core_fixture import CoreFixture, SOURCE
from taskweave.desktop.controller import DesktopController
from taskweave.desktop.components.step_derivation import show_step_derivation


class StepDerivationUITests(CoreFixture):
    def setUp(self):
        super().setUp()
        self.task_id = self.task()
        self.source = self.step(self.task_id, input_schema={'type': 'object', 'properties': {'value': {'type': 'string'}}},
                                bindings={'value': {'literal': 'shared'}})
        self.contexts = self.app.contexts.contexts
        self.group = self.contexts.create_step_context_group(self.source['step_id'], 'demo.context', 'Group')
        self.capture = self.contexts.append_step_context_capture(self.group['context_id'], {'items': [{'content': 'evidence'}]}, label='Evidence')
        self.controller = DesktopController(self.app)
        self.client = Client(page('/derivation-test'))
        self.created = AsyncMock()

    def tearDown(self):
        self.client.delete()
        super().tearDown()

    def scenario(self, fn):
        async def run():
            with self.client:
                await fn()
        asyncio.run(run())

    async def open(self, mode):
        return await show_step_derivation(self.controller, self.source, mode=mode,
            is_current=lambda: True, on_created=self.created)

    @staticmethod
    async def click(dialog, text):
        button = next(e for e in dialog.descendants() if getattr(e, 'text', '') == text)
        handler = next(e.handler for e in button._event_listeners.values() if e.type == 'click')
        callback = inspect.getclosurevars(handler).nonlocals['callback']
        value = callback()
        if inspect.iscoroutine(value): await value

    def field(self, dialog, label):
        return next(e for e in dialog.descendants() if e._props.get('label') == label)

    def test_copy_submits_real_service_and_inherits_materials(self):
        async def run():
            dialog = await self.open('copy')
            self.assertEqual(len(self.app.steps.list(self.task_id)), 1)
            await self.click(dialog, '确认复制')
            self.created.assert_awaited_once()
            new = self.created.await_args.args[0]
            self.assertNotEqual(new['step_id'], self.source['step_id'])
            self.assertEqual(new['bindings'], self.source['bindings'])
            self.assertEqual(len(self.contexts.list_step_contexts(new['step_id'])[0]['captures']), 1)
        self.scenario(run)

    def test_split_edits_both_documents_and_shares_selected_material(self):
        async def run():
            dialog = await self.open('split')
            self.field(dialog, '第一份名称').value = 'First'
            self.field(dialog, '第二份名称').value = 'Second'
            self.field(dialog, '第一份输出 Schema（JSON）').value = '{"type":"object"}'
            self.field(dialog, '第二份输出 Schema（JSON）').value = '{"type":"object","properties":{"next":{"type":"string"}}}'
            await self.click(dialog, '确认拆分')
            self.created.assert_awaited_once()
            new = self.created.await_args.args[0]
            self.assertEqual(self.app.steps.get(self.source['step_id'])['name'], 'First')
            self.assertEqual(new['name'], 'Second')
            self.assertEqual(new['input_schema'], self.source['input_schema'])
            self.assertEqual(new['bindings'], self.source['bindings'])
            self.assertIn('next', new['output_schema']['properties'])
            self.assertEqual(len(self.contexts.list_step_contexts(self.source['step_id'])[0]['captures']), 1)
            self.assertEqual(len(self.contexts.list_step_contexts(new['step_id'])[0]['captures']), 1)
        self.scenario(run)

    def test_cancel_and_invalid_code_do_not_write(self):
        async def run():
            dialog = await self.open('split')
            code = [e for e in dialog.descendants() if e.__class__.__name__.lower() == 'codemirror'][1]
            code.value = 'invalid python!'
            await self.click(dialog, '确认拆分')
            self.assertEqual(len(self.app.steps.list(self.task_id)), 1)
            self.assertTrue(dialog.value)
            self.assertEqual(code.value, 'invalid python!')
            await self.click(dialog, '取消')
            self.assertEqual(len(self.app.steps.list(self.task_id)), 1)
            self.created.assert_not_called()
        self.scenario(run)

    def test_invalid_json_and_stale_editor_keep_database_unchanged(self):
        async def run():
            dialog = await self.open('split')
            self.field(dialog, '第一份输入 Schema（JSON）').value = '{bad'
            await self.click(dialog, '确认拆分')
            self.assertTrue(dialog.value)
            self.assertEqual(len(self.app.steps.list(self.task_id)), 1)
            stale = await show_step_derivation(self.controller, self.source, mode='copy',
                is_current=lambda: False, on_created=self.created)
            self.assertIsNone(stale)
            self.created.assert_not_called()
        self.scenario(run)

    def test_split_saves_independent_code_and_capture_choices(self):
        async def run():
            dialog = await self.open('split')
            codes = [e for e in dialog.descendants() if e.__class__.__name__.lower() == 'codemirror']
            first_code = 'async def run(ctx, inputs):\n    return ctx.result(data={"part": "first"})\n'
            second_code = 'async def run(ctx, inputs):\n    return ctx.result(data={"part": "second"})\n'
            codes[0].value, codes[1].value = first_code, second_code
            self.field(dialog, '第一份上下文材料（可多选）').value = []
            await self.click(dialog, '确认拆分')
            new = self.created.await_args.args[0]
            self.assertEqual(self.app.steps.get(self.source['step_id'])['step_content'], first_code)
            self.assertEqual(new['step_content'], second_code)
            self.assertEqual(self.contexts.list_step_contexts(self.source['step_id'])[0]['captures'], [])
            self.assertEqual(len(self.contexts.list_step_contexts(new['step_id'])[0]['captures']), 1)
        self.scenario(run)

    def test_double_submit_only_creates_one_step(self):
        async def run():
            dialog = await self.open('copy')
            original = self.controller.call
            entered, release = asyncio.Event(), asyncio.Event()
            async def blocked(operation, **params):
                if operation == 'step.copy':
                    entered.set()
                    await release.wait()
                return await original(operation, **params)
            self.controller.call = blocked
            pending = asyncio.create_task(self.click(dialog, '确认复制'))
            await entered.wait()
            await self.click(dialog, '确认复制')
            release.set()
            await pending
            self.assertEqual(len(self.app.steps.list(self.task_id)), 2)
            self.created.assert_awaited_once()
        self.scenario(run)

    def test_statement_and_schema_checkboxes_update_each_part_independently(self):
        import json
        async def run():
            source = 'async def run(ctx, inputs):\n    first = 1\n    if inputs.get("keep"):\n        first = 2\n    last = 3\n    return ctx.result(data={})\n'
            schema = {'type': 'object', 'properties': {'keep': {'type': 'boolean'}, 'drop': {'type': 'string'}}, 'required': ['keep', 'drop'], 'additionalProperties': False}
            self.source = self.app.steps.save(self.task_id, {**self.source, 'step_content': source,
                'input_schema': schema, 'output_schema': schema, 'bindings': {'keep': {'literal': True}, 'drop': {'literal': 'x'}}},
                self.source['step_id'], self.source['content_hash'])
            dialog = await self.open('split')
            def check(label):
                return next(e for e in dialog.descendants() if getattr(e, 'text', '') == label)
            check('第一份代码段 2 · 第 3–4 行 · if inputs.get("keep"):').value = False
            check('第二份代码段 3 · 第 5 行 · last = 3').value = False
            check('第一份输入字段 · drop').value = False
            check('第二份输出字段 · keep').value = False
            await self.click(dialog, '确认拆分')
            self.created.assert_awaited_once()
            first = self.app.steps.get(self.source['step_id'])
            second = self.created.await_args.args[0]
            self.assertNotIn('if inputs.get', first['step_content'])
            self.assertIn('last = 3', first['step_content'])
            self.assertIn('if inputs.get', second['step_content'])
            self.assertNotIn('last = 3', second['step_content'])
            self.assertEqual(list(first['input_schema']['properties']), ['keep'])
            self.assertEqual(first['input_schema']['required'], ['keep'])
            self.assertEqual(first['bindings'], {'keep': {'literal': True}})
            self.assertFalse(first['input_schema']['additionalProperties'])
            self.assertEqual(list(second['output_schema']['properties']), ['drop'])
            self.assertEqual(second['output_schema']['required'], ['drop'])
            self.assertEqual(second['input_schema'], schema)
        self.scenario(run)

    def test_selection_never_overwrites_manual_code_or_schema_edits(self):
        async def run():
            dialog = await self.open('split')
            code = [e for e in dialog.descendants() if e.__class__.__name__.lower() == 'codemirror'][0]
            code.value = SOURCE + '\n# manual draft\n'
            code_check = next(e for e in dialog.descendants() if getattr(e, 'text', '').startswith('第一份代码段 1'))
            code_check.value = False
            self.assertTrue(code_check.value)
            self.assertIn('manual draft', code.value)
            inputs = self.field(dialog, '第一份输入 Schema（JSON）')
            inputs.value = '{"type":"object","properties":{"manual":{"type":"string"}}}'
            schema_check = next(e for e in dialog.descendants() if getattr(e, 'text', '') == '第一份输入字段 · value')
            schema_check.value = False
            self.assertTrue(schema_check.value)
            self.assertIn('manual', inputs.value)
            self.assertEqual(len(self.app.steps.list(self.task_id)), 1)
        self.scenario(run)

    def test_invalid_source_has_explanation_and_keeps_full_editor(self):
        async def run():
            self.source = {**self.source, 'step_content': 'invalid python!'}
            dialog = await self.open('split')
            texts = [getattr(e, 'text', '') for e in dialog.descendants()]
            self.assertTrue(any('代码段暂不可选' in text for text in texts))
            codes = [e for e in dialog.descendants() if e.__class__.__name__.lower() == 'codemirror']
            self.assertEqual([code.value for code in codes], ['invalid python!'] * 2)
            self.assertEqual(len(self.app.steps.list(self.task_id)), 1)
        self.scenario(run)

    def test_old_step_with_new_flow_snapshot_does_not_overwrite_concurrent_edit(self):
        async def run():
            updated = self.app.steps.save(self.task_id, {**self.source, 'name': 'Concurrent edit'},
                self.source['step_id'], self.source['content_hash'])
            dialog = await self.open('split')
            await self.click(dialog, '确认拆分')
            self.assertEqual(self.app.steps.get(self.source['step_id'])['name'], updated['name'])
            self.assertEqual(len(self.app.steps.list(self.task_id)), 1)
            self.assertTrue(dialog.value)
            self.created.assert_not_called()
        self.scenario(run)

    def test_category_tabs_keep_drafts_and_footer_outside_scroll_body(self):
        async def run():
            dialog = await self.open('split')
            elements = list(dialog.descendants())
            tabs = next(e for e in elements if e.__class__.__name__ == 'Tabs')
            panels = next(e for e in elements if e.__class__.__name__ == 'TabPanels')
            self.assertTrue(panels._props.get('keep-alive'))
            self.assertEqual({e._props.get('label') for e in tabs.descendants() if e.__class__.__name__ == 'Tab'}, {'代码', '上下文', '输入输出'})
            code = [e for e in elements if e.__class__.__name__.lower() == 'codemirror'][0]
            code.value = SOURCE + '\n# keep across tabs\n'
            names = self.field(dialog, '第一份名称')
            names.value = 'Draft name'
            tabs.value = 'contexts'
            tabs.value = 'io'
            tabs.value = 'code'
            self.assertIn('keep across tabs', code.value)
            self.assertEqual(names.value, 'Draft name')
            advanced = [e for e in elements if e.__class__.__name__ == 'Expansion' and '高级' in e._props.get('label', '')]
            self.assertEqual(len(advanced), 2)
            self.assertTrue(all(not e.value for e in advanced))
            footer = next(e for e in elements if 'tw-step-derivation-footer' in e._classes)
            self.assertIn('确认拆分', [getattr(e, 'text', '') for e in footer.descendants()])
            self.assertNotIn(footer, list(panels.descendants()))
        self.scenario(run)

    def test_copy_review_is_compact_with_reachable_actions(self):
        async def run():
            dialog = await self.open('copy')
            elements = list(dialog.descendants())
            code_preview = next(e for e in elements if e.__class__.__name__ == 'Expansion' and e._props.get('label') == '查看完整代码')
            self.assertFalse(code_preview.value)
            footer = next(e for e in elements if 'tw-step-operation-footer' in e._classes)
            self.assertIn('确认复制', [getattr(e, 'text', '') for e in footer.descendants()])
            self.assertTrue(any('插件配置' in getattr(e, 'text', '') for e in elements))
            self.assertEqual(len(self.app.steps.list(self.task_id)), 1)
        self.scenario(run)

    def test_pending_split_locks_dialog_and_inputs_then_restores_after_failure(self):
        from taskweave.core.validation import TaskError
        async def run():
            dialog = await self.open('split')
            original = self.controller.call
            entered, release = asyncio.Event(), asyncio.Event()
            async def blocked(operation, **params):
                if operation == 'step.split':
                    entered.set()
                    await release.wait()
                    raise TaskError('EDIT_CONFLICT', 'retry fixture')
                return await original(operation, **params)
            self.controller.call = blocked
            pending = asyncio.create_task(self.click(dialog, '确认拆分'))
            await entered.wait()
            try:
                self.assertFalse(dialog._props.get('persistent'))
                self.assertTrue(dialog._props.get('no-backdrop-dismiss'))
                status = next(e for e in dialog.descendants() if getattr(e, 'text', '') == '正在保存，关闭窗口不会取消已提交的操作')
                self.assertTrue(status.visible)
                confirm = next(e for e in dialog.descendants() if getattr(e, 'text', '') == '确认拆分')
                self.assertTrue(confirm._props.get('loading'))
                editable = [e for e in dialog.descendants() if hasattr(e, 'set_enabled')]
                self.assertTrue(editable)
                self.assertTrue(all(not e.enabled for e in editable))
                await self.click(dialog, '取消')
                self.assertTrue(dialog.value)
                await self.click(dialog, '确认拆分')
            finally:
                release.set()
                await pending
            self.assertFalse(dialog._props.get('no-backdrop-dismiss'))
            self.assertFalse(status.visible)
            self.assertFalse(confirm._props.get('loading'))
            self.assertTrue(all(e.enabled for e in editable))
            self.assertTrue(dialog.value)
            self.assertEqual(len(self.app.steps.list(self.task_id)), 1)
            self.controller.call = original
            self.field(dialog, '第二份名称').value = 'Retry draft'
            await self.click(dialog, '确认拆分')
            self.created.assert_awaited_once()
            self.assertEqual(self.created.await_args.args[0]['name'], 'Retry draft')
        self.scenario(run)

    def test_cancelled_dialog_ignores_queued_submit(self):
        async def run():
            dialog = await self.open('copy')
            await self.click(dialog, '取消')
            await self.click(dialog, '确认复制')
            self.created.assert_not_called()
            self.assertEqual(len(self.app.steps.list(self.task_id)), 1)
        self.scenario(run)

    def test_escape_close_during_pending_save_does_not_cancel_or_repeat_write(self):
        async def run():
            dialog = await self.open('copy')
            original = self.controller.call
            entered, release = asyncio.Event(), asyncio.Event()
            async def blocked(operation, **params):
                if operation == 'step.copy':
                    entered.set()
                    await release.wait()
                return await original(operation, **params)
            self.controller.call = blocked
            pending = asyncio.create_task(self.click(dialog, '确认复制'))
            await entered.wait()
            self.assertFalse(dialog._props.get('persistent'))
            self.assertFalse(dialog._props.get('no-esc-dismiss'))
            dialog.close()
            await self.click(dialog, '确认复制')
            release.set()
            await pending
            self.created.assert_awaited_once()
            self.assertEqual(len(self.app.steps.list(self.task_id)), 2)
        self.scenario(run)
