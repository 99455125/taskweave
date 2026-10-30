"""Step editor saves keep the identity they started with."""

import asyncio
import tempfile
import unittest
from unittest.mock import AsyncMock

from taskweave.desktop.state import StepEditorState
from taskweave.desktop.workbench import Workbench


class StepEditorStateTests(unittest.TestCase):
    def test_action_insertion_uses_cursor_line_indentation_and_preserves_return(self):
        from taskweave.desktop.components.step_editor import insert_action_source
        source = ('async def run(ctx, inputs):\n'
                  '    title = "记录📄"\n'
                  '    if inputs:\n'
                  '        title = inputs["title"]\n'
                  '    return ctx.result(data=inputs)\n')
        position = source.index('title = inputs') + 5
        result = insert_action_source(source, "value = await ctx.call('file.read', {'path': 'local.txt'})", position)
        self.assertIn("        value = await ctx.call('file.read', {'path': 'local.txt'})\n        title", result)
        self.assertIn('    return ctx.result(data=inputs)', result)
        self.assertEqual(result.replace("        value = await ctx.call('file.read', {'path': 'local.txt'})\n", ''), source)
        from taskweave.core.validation import TaskError
        with self.assertRaises(TaskError):
            insert_action_source(source, 'value = 1', 0)

    def test_action_insertion_respects_multiline_statement_boundaries(self):
        import ast
        from taskweave.desktop.components.step_editor import insert_action_source
        source = ('async def run(ctx, inputs):\n'
                  '    title = """记录\n'
                  '第二行\n'
                  '    最后一行"""\n'
                  '    return ctx.result(\n'
                  '        data={"title": title}\n'
                  '    )\n')
        invocation = "value = await ctx.call('demo.echo', {})"
        for marker, before in [('第二行', '    title ='), ('data={', '    return')]:
            result = insert_action_source(source, invocation, source.index(marker) + 2)
            ast.parse(result)
            self.assertIn('    ' + invocation + '\n' + before, result)
            self.assertEqual(result.replace('    ' + invocation + '\n', ''), source)

    def test_action_preview_tracks_parameters_without_editing_code(self):
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page
        from taskweave.application.service import Application
        from taskweave.desktop.controller import DesktopController
        with tempfile.TemporaryDirectory() as home, Application(home, registry_factory="taskweave.plugins.demo:build_registry") as app:
            task = app.repo.create_task('action preview')
            step = app.repo.save_step(task['task_id'], {'name': 'local',
                'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n'})
            client = Client(page('/action-preview'))
            async def scenario():
                with client:
                    wb = Workbench(DesktopController(app))
                    await wb.navigate('editor', task_id=task['task_id'], step_id=step['step_id'])
                    action = next(e for e in client.elements.values() if e.props.get('label') == '插件动作')
                    wb.edit_controls['caps'].set_value(['demo'])
                    self.assertNotIn('text.upper', action.options)
                    wb.edit_controls['caps'].set_value(['demo', 'text'])
                    action.set_value('text.upper')
                    preview = next((e for e in client.elements.values() if 'tw-action-preview' in e.classes), None)
                    self.assertIsNotNone(preview, 'Action parameters need a live code preview')
                    text = next(e for e in client.elements.values() if e.props.get('aria-label') == 'text · 必录')
                    text.set_value('记录📄')
                    self.assertIn("'text': '记录📄'", preview.content)
                    self.assertEqual(wb.edit_controls['code'].value, step['step_content'])
                    self.assertEqual(wb.edit_controls['caps'].value, ['demo', 'text'])
                    wb.edit_controls['caps'].set_value(['demo'])
                    self.assertNotIn('text.upper', action.options)
                    self.assertNotEqual(action.value, 'text.upper')
            try:
                asyncio.run(scenario())
            finally:
                client.delete()

    def test_web_candidate_review_closes_export_and_can_return_to_reply(self):
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page
        from taskweave.application.service import Application
        from taskweave.desktop.controller import DesktopController
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task('inline web candidate')
            step = app.repo.save_step(task['task_id'], {'name': 'read local',
                'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n'})
            client = Client(page('/inline-web-review'))
            async def scenario():
                with client:
                    wb = Workbench(DesktopController(app))
                    await wb.navigate('editor', task_id=task['task_id'], step_id=step['step_id'])
                    source = 'async def run(ctx, inputs):\n    return ctx.result(data={"review": 2})\n'
                    import json
                    reply_text = json.dumps({'step_content': source, 'explanation': 'local reply'})
                    callbacks = {}
                    original_button = wb.step_ai_editor.button
                    def button(label, callback, **kwargs):
                        callbacks[label] = callback
                        return original_button(label, callback, **kwargs)
                    wb.step_ai_editor.button = button
                    await wb.step_ai_editor.web_chat_dialog(step,
                        {'prompt': 'local fixture', 'expected_hash': step['content_hash'], 'messages': []},
                        False, repaint=wb.paint)
                    self.assertFalse(any(isinstance(e, ui.dialog) and e.value for e in client.elements.values()),
                                     'Web Chat prompt and reply belong beside the current code')
                    reply = next(e for e in client.elements.values() if e.props.get('label') == '粘贴网页 AI 回复')
                    reply.set_value(reply_text)
                    await callbacks['解析并预览']()
                    self.assertFalse(any(isinstance(e, ui.dialog) and e.value for e in client.elements.values()),
                                     'Export must close before inline review')
                    side = next(e for e in client.elements.values() if 'tw-candidate-side' in e.classes)
                    self.assertTrue(side.visible)
                    back = next(e for e in side.descendants() if isinstance(e, ui.button) and e.text == '返回修改粘贴内容')
                    next(v.handler for v in back._event_listeners.values() if v.type == 'click')(None)
                    self.assertEqual(reply.value, reply_text)
                    self.assertEqual(sum(isinstance(e, ui.dialog) and bool(e.value) for e in client.elements.values()), 0)
                    chat = next(e for e in client.elements.values() if 'tw-chat-side' in e.classes)
                    self.assertTrue(chat.visible)
                    self.assertFalse(side.visible)
                    self.assertEqual(wb.edit_controls['code'].value, step['step_content'])
            try:
                asyncio.run(scenario())
            finally:
                client.delete()

    def test_ai_candidate_review_is_inline_and_discard_keeps_the_same_code(self):
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page
        from taskweave.application.service import Application
        from taskweave.desktop.controller import DesktopController
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task('inline candidate')
            step = app.repo.save_step(task['task_id'], {'name': 'read local',
                'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n'})
            client = Client(page('/inline-review'))
            async def scenario():
                with client:
                    wb = Workbench(DesktopController(app))
                    await wb.navigate('editor', task_id=task['task_id'], step_id=step['step_id'])
                    code = wb.edit_controls['code']
                    candidate = {'explanation': 'local review', 'diagnostics': [], 'stale': False,
                                 'proposed_content': 'async def run(ctx, inputs):\n    return ctx.result(data={"review": 1})\n'}
                    await wb.step_ai_editor.present_content_candidate(step, candidate, wb.step_ai_editor.identity(), wb.paint)
                    main = next((e for e in client.elements.values() if 'tw-candidate-main' in e.classes), None)
                    self.assertIsNotNone(main, 'Review belongs inside the code workspace')
                    self.assertTrue(main.visible)
                    self.assertFalse(any(isinstance(e, ui.dialog) and e.value for e in client.elements.values()))
                    side = next(e for e in client.elements.values() if 'tw-candidate-side' in e.classes)
                    self.assertTrue(side.visible)
                    labels = [getattr(e, 'text', '') for e in side.descendants()]
                    self.assertIn('仅采纳', labels)
                    self.assertIn('采纳并调试', labels)
                    discard = next(e for e in side.descendants() if isinstance(e, ui.button) and e.text == '舍弃')
                    next(v.handler for v in discard._event_listeners.values() if v.type == 'click')(None)
                    self.assertFalse(main.visible)
                    self.assertIs(wb.edit_controls['code'], code)
                    self.assertEqual(code.value, step['step_content'])
                    self.assertEqual(app.repo.step(step['step_id'])['step_content'], step['step_content'])
            try:
                asyncio.run(scenario())
            finally:
                client.delete()

    def test_code_assistant_switching_preserves_code_plugin_and_form_drafts(self):
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page
        from taskweave.application.service import Application
        from taskweave.desktop.controller import DesktopController

        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task('assistant layout')
            step = app.repo.save_step(task['task_id'], {'name': '查询记录', 'capabilities': []})
            client = Client(page('/code-assistant-switching'))
            async def scenario():
                with client:
                    wb = Workbench(DesktopController(app))
                    await wb.navigate('editor', task_id=task['task_id'], step_id=step['step_id'])
                    tabs = next(e for e in client.elements.values() if 'tw-step-workspace-tabs' in e.classes)
                    tabs.set_value('code')
                    await asyncio.sleep(0)
                    code = wb.edit_controls['code']
                    code.set_value('async def run(ctx, inputs):\n    return ctx.result(data={"draft": True})\n')
                    supplement = next(e for e in client.elements.values() if e.props.get('label') == '本轮编写要求')
                    supplement.set_value('保留当前查询')
                    action_panel = next((e for e in client.elements.values() if 'tw-action-panel' in e.classes), None)
                    self.assertIsNotNone(action_panel, 'Actions need a switchable assistant panel')
                    ai_panel = next(e for e in client.elements.values() if 'tw-code-assistant' in e.classes)
                    action_selection = next(e for e in client.elements.values() if e.props.get('label') == '插件动作')
                    original_action = action_selection.value
                    toolbar = next(e for e in client.elements.values() if 'tw-code-toolbar' in e.classes)
                    def click(label, container=toolbar):
                        button = next(e for e in container.descendants() if isinstance(e, ui.button)
                                      and (e.text == label or e.props.get('aria-label') == label))
                        next(v.handler for v in button._event_listeners.values() if v.type == 'click')(None)
                    click('插入动作')
                    self.assertTrue(action_panel.visible)
                    self.assertFalse(ai_panel.visible)
                    click('AI 编写')
                    self.assertTrue(ai_panel.visible)
                    self.assertFalse(action_panel.visible)
                    self.assertEqual(supplement.value, '保留当前查询')
                    click('收起辅助区', next(e for e in client.elements.values() if 'tw-code-tools' in e.classes))
                    self.assertFalse(next(e for e in client.elements.values() if 'tw-code-tools' in e.classes).visible)
                    click('插入动作')
                    self.assertTrue(action_panel.visible)
                    self.assertEqual(action_selection.value, original_action)
                    tabs.set_value('basic')
                    tabs.set_value('code')
                    await asyncio.sleep(0)
                    self.assertTrue(action_panel.visible)
                    self.assertIs(wb.edit_controls['code'], code)
                    self.assertIn('"draft": True', wb.step_editor.document()['step_content'])
                    self.assertEqual(wb.step_editor.document()['capabilities'], [])
                    flow_toggle = next(e for e in client.elements.values()
                                       if e.props.get('aria-label') == '展开或收起流程')
                    next(v.handler for v in flow_toggle._event_listeners.values() if v.type == 'click')(None)
                    flow_zoom = next(e for e in client.elements.values() if 'tw-flow-zoom' in e.classes)
                    flow_zoom.set_value(0.75)
                    # Full page rebuilds follow the existing save-then-paint contract.
                    await wb.save_editor()
                    await wb.paint()
                    self.assertFalse(next(e for e in client.elements.values() if 'tw-flow-canvas' in e.classes).visible)
                    self.assertEqual(next(e for e in client.elements.values() if 'tw-flow-zoom' in e.classes).value, 0.75)
                    self.assertTrue(next(e for e in client.elements.values() if 'tw-action-panel' in e.classes).visible)
                    self.assertEqual(next(e for e in client.elements.values() if e.props.get('label') == '本轮编写要求').value, '保留当前查询')
                    tabs = next(e for e in client.elements.values() if 'tw-step-workspace-tabs' in e.classes)
                    tabs.set_value('basic')
                    await asyncio.sleep(0)
                    heading = next(e for e in client.elements.values() if 'tw-step-config-heading' in e.classes)
                    click('AI 编写', heading)
                    self.assertEqual(tabs.value, 'code')
                    self.assertTrue(next(e for e in client.elements.values() if 'tw-code-assistant' in e.classes).visible)
                    self.assertIn('"draft": True', wb.step_editor.document()['step_content'])
            try:
                asyncio.run(scenario())
            finally:
                client.delete()

    def test_opening_step_preserves_capabilities_and_timeout_until_edited(self):
        from nicegui.client import Client
        from nicegui.page import page
        from taskweave.application.service import Application
        from taskweave.desktop.controller import DesktopController
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task('unchanged step')
            step = app.repo.save_step(task['task_id'], {
                'name': 'one capability', 'capabilities': ['fixture.read'], 'timeout_ms': 1500,
            })
            client = Client(page('/unchanged-step'))
            async def scenario():
                with client:
                    controller = DesktopController(app)
                    original_call = controller.call
                    async def call(operation, **params):
                        result = await original_call(operation, **params)
                        if operation == 'capabilities':
                            result['versions']['fixture'] = '1'
                            result['actions'].extend([
                                {'id': 'fixture.' + action, 'description': action, 'input_schema': {'type': 'object'}}
                                for action in ('read', 'write')
                            ])
                        return result
                    controller.call = call
                    wb = Workbench(controller)
                    await wb.navigate('editor', task_id=task['task_id'], step_id=step['step_id'])
                    tabs = next(e for e in client.elements.values() if 'tw-step-workspace-tabs' in e.classes)
                    self.assertEqual([e.props.get('label') for e in tabs.default_slot.children],
                                     ['基础配置', '步骤代码', '输入输出', '上下文', '调试'])
                    original_code = wb.edit_controls['code']
                    assistant = [e for e in client.elements.values() if 'tw-code-assistant' in e.classes]
                    self.assertEqual(len(assistant), 1, 'Code page needs its inline AI assistant')
                    recovery = [e for e in assistant[0].descendants() if getattr(e, 'text', '') == '查看上次 AI 结果']
                    self.assertEqual(len(recovery), 1, 'Recovery must remain reachable after the first request without repainting')
                    supplement = next(e for e in client.elements.values() if e.props.get('label') == '本轮编写要求')
                    supplement.set_value('保留查询逻辑')
                    tabs.set_value('code')
                    tabs.set_value('basic')
                    self.assertIs(wb.edit_controls['code'], original_code)
                    tabs.set_value('code')
                    await asyncio.sleep(0)
                    await wb.paint()
                    tabs = next(e for e in client.elements.values() if 'tw-step-workspace-tabs' in e.classes)
                    self.assertEqual(tabs.value, 'code')
                    supplement = next(e for e in client.elements.values() if e.props.get('label') == '本轮编写要求')
                    self.assertEqual(supplement.value, '保留查询逻辑')
                    doc = wb.step_editor.document()
                    self.assertEqual(doc['capabilities'], step['capabilities'])
                    self.assertEqual(doc['timeout_ms'], 1500)
                    self.assertFalse(wb._step_editor_is_dirty())
                    wb.edit_controls['name'].value = 'changed'
                    self.assertTrue(wb._step_editor_is_dirty())
                    wb.edit_controls['name'].value = step['name']
                    self.assertFalse(wb._step_editor_is_dirty())
                    wb.edit_controls['caps'].value = []
                    self.assertEqual(wb.step_editor.document()['capabilities'], [])
                    self.assertTrue(wb._step_editor_is_dirty())
                    wb.edit_controls['caps'].value = ['fixture']
                    self.assertFalse(wb._step_editor_is_dirty())
                    self.assertTrue(await wb.navigate('home'))
            try:
                asyncio.run(scenario())
            finally:
                client.delete()

    def test_control_selection_edits_below_canvas_and_saves_existing_flow(self):
        from unittest.mock import patch
        from nicegui import ui
        original_button = ui.button
        def tracked_button(*args, **kwargs):
            button = original_button(*args, **kwargs)
            button.test_click = kwargs.get('on_click')
            return button
        from nicegui.client import Client
        from nicegui.page import page
        from taskweave.application.service import Application
        from taskweave.desktop.controller import DesktopController
        from taskweave.presentation.flow_editor import insert_control, find_node
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task('flow editor')
            step = app.repo.save_step(task['task_id'], {'name': '查询'})
            baseline = app.dispatch('task.flow.describe', {'task_id': task['task_id']})
            flow, node_id = insert_control(baseline['flow'], 'foreach')
            app.dispatch('task.flow.save', {'task_id': task['task_id'], 'flow': flow,
                                          'expected_hash': baseline['definition_hash']})
            client = Client(page('/inline-control'))
            async def scenario():
                with client, patch('nicegui.ui.button', side_effect=tracked_button):
                    wb = Workbench(DesktopController(app))
                    await wb.navigate('editor', task_id=task['task_id'], step_id=step['step_id'])
                    branch = next(e for e in client.elements.values()
                                  if e.props.get('aria-label') == '配置列表遍历')
                    wb.edit_controls['name'].value = '尚未保存的步骤名称'
                    await branch.test_click()
                    self.assertEqual(app.repo.step(step['step_id'])['name'], '查询')
                    panel = next(e for e in client.elements.values() if 'tw-control-panel' in e.classes)
                    self.assertTrue(panel.visible)
                    step_panel = next(e for e in client.elements.values() if 'tw-editor-panel' in e.classes)
                    self.assertFalse(step_panel.visible)
                    limit = next(e for e in client.elements.values() if e.props.get('label') == '最多项数')
                    limit.value = 42
                    self.assertTrue(any(getattr(e, 'text', '') == '未保存修改' for e in panel.descendants()),
                                    'Control inputs must update their own saved-state indicator')
                    class StayDialog:
                        def __enter__(self): return self
                        def __exit__(self, *_args): return False
                        def __await__(self):
                            async def choice(): return 'stay'
                            return choice().__await__()
                    with patch('taskweave.desktop.components.step_editor.ui.dialog', return_value=StayDialog()):
                        self.assertFalse(await wb.step_editor.view['prepare_control_leave']())
                    self.assertEqual(limit.value, 42)
                    save = next(e for e in client.elements.values() if getattr(e, 'text', '') == '保存配置')
                    await save.test_click()
                    stored = app.dispatch('task.flow.get', {'task_id': task['task_id']})
                    node, _ = find_node(stored, node_id)
                    self.assertEqual(node['max_items'], 42)
                    self.assertFalse(any(getattr(e, 'text', '') == '未保存修改' for e in panel.descendants()))
                    back = next(e for e in client.elements.values() if getattr(e, 'text', '') == '返回步骤')
                    await back.test_click()
                    self.assertTrue(step_panel.visible)
                    self.assertFalse(panel.visible)
                    self.assertEqual(wb.edit_controls['name'].value, '尚未保存的步骤名称')
                    wb.edit_controls['name'].value = '查询'
                    self.assertTrue(await wb.navigate('home'))
            try:
                asyncio.run(scenario())
            finally:
                client.delete()

    def test_multi_exit_branch_save_redraws_canvas_and_preserves_step_draft(self):
        from unittest.mock import patch
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page
        from taskweave.application.service import Application
        from taskweave.desktop.controller import DesktopController
        from taskweave.presentation.flow_editor import insert_control, find_node
        from taskweave.desktop.components.flow_branches import split_branches
        original_button = ui.button
        def tracked_button(*args, **kwargs):
            button = original_button(*args, **kwargs)
            button.test_click = kwargs.get('on_click')
            return button
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task('multiple exits')
            step = app.repo.save_step(task['task_id'], {'name': '查询'})
            baseline = app.dispatch('task.flow.describe', {'task_id': task['task_id']})
            flow, node_id = insert_control(baseline['flow'], 'if')
            app.dispatch('task.flow.save', {'task_id': task['task_id'], 'flow': flow,
                                          'expected_hash': baseline['definition_hash']})
            client = Client(page('/multi-exit-control'))
            def button(text):
                return next(e for e in client.elements.values() if getattr(e, 'text', '') == text)
            async def scenario():
                with client, patch('nicegui.ui.button', side_effect=tracked_button):
                    wb = Workbench(DesktopController(app))
                    await wb.navigate('editor', task_id=task['task_id'], step_id=step['step_id'])
                    wb.edit_controls['name'].set_value('尚未保存的步骤名称')
                    configure = next(e for e in client.elements.values()
                                     if e.props.get('aria-label') == '配置条件分支')
                    await configure.test_click()
                    button('添加分支').test_click()
                    button('添加分支').test_click()
                    panel = next(e for e in client.elements.values() if 'tw-control-panel' in e.classes)
                    self.assertTrue(any(getattr(e, 'text', '') == '未保存修改' for e in panel.descendants()))
                    await button('保存配置').test_click()
                    stored = app.dispatch('task.flow.get', {'task_id': task['task_id']})
                    node, _ = find_node(stored, node_id)
                    cases, _ = split_branches(node)
                    self.assertEqual(len(cases), 3)
                    canvas = next(e for e in client.elements.values() if 'tw-flow-canvas' in e.classes)
                    self.assertTrue(any(getattr(e, 'text', '') == '分支 3' for e in canvas.descendants()))
                    selected = next(e for e in canvas.descendants()
                                    if e.props.get('aria-label') == '选择步骤：查询')
                    self.assertIs(wb.step_editor.view['selected_step_control'], selected)
                    self.assertFalse(selected.is_deleted)
                    self.assertEqual(app.repo.step(step['step_id'])['name'], '查询')
                    await button('返回步骤').test_click()
                    self.assertEqual(wb.edit_controls['name'].value, '尚未保存的步骤名称')
                    configure = next(e for e in client.elements.values()
                                     if e.props.get('aria-label') == '配置条件分支')
                    await configure.test_click()
                    cards = [e for e in client.elements.values() if 'tw-branch-case' in e.classes]
                    self.assertEqual(len(cards), 3)
                    self.assertFalse(any(getattr(e, 'text', '') == '未保存修改' for e in panel.descendants()))
                    field = next(e for e in cards[0].descendants()
                                 if e.props.get('label') == '固定值（文本或 JSON）')
                    field.set_value('2')
                    original_call = wb.controller.call
                    started, release = asyncio.Event(), asyncio.Event()
                    async def delayed_call(operation, **params):
                        if operation == 'task.flow.save':
                            started.set()
                            await release.wait()
                        return await original_call(operation, **params)
                    wb.controller.call = delayed_call
                    pending = asyncio.create_task(button('保存配置').test_click())
                    await started.wait()
                    field.set_value('3')
                    release.set()
                    await pending
                    self.assertEqual(field.value, '3')
                    self.assertTrue(any(getattr(e, 'text', '') == '未保存修改' for e in panel.descendants()),
                                    'An edit during save must remain marked unsaved')
            try:
                asyncio.run(scenario())
            finally:
                client.delete()

    def test_arriving_result_metadata_is_saved_without_another_input_change(self):
        from nicegui.client import Client
        from nicegui.page import page
        from taskweave.application.service import Application
        from taskweave.desktop.controller import DesktopController
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task('metadata')
            previous = app.repo.save_step(task['task_id'], {'name': 'source'})
            step = app.repo.save_step(task['task_id'], {
                'name': 'consumer',
                'bindings': {'payload': {'ref': {'source': 'step', 'step_id': previous['step_id'], 'output': 'data', 'pointer': '/payload'}}},
            })
            controller = DesktopController(app)
            controller.previous_result = AsyncMock(return_value={'payload': 'initial'})
            client = Client(page('/result-metadata'))
            async def scenario():
                with client:
                    wb = Workbench(controller)
                    await wb.navigate('editor', task_id=task['task_id'], step_id=step['step_id'])
                    row = wb.edit_controls['bindings'][0]
                    self.assertEqual(wb.step_editor.document()['input_schema']['properties']['payload']['type'], 'string')
                    controller.previous_result.return_value = {'payload': {'nested': 1}}
                    # A delayed metadata response must update the plain draft even
                    # when the user makes no further changes before saving.
                    await row[3]._change_handlers[-1](None)
                    saved = await wb.step_editor.save()
                    self.assertEqual(saved['input_schema']['properties']['payload']['type'], 'object')
            try:
                asyncio.run(scenario())
            finally:
                client.delete()

    def test_reload_keeps_failed_debug_run_and_raw_inputs_without_starting_again(self):
        from nicegui.client import Client
        from nicegui.page import page
        from taskweave.application.service import Application
        from taskweave.desktop.controller import DesktopController
        from taskweave.core.validation import TaskError

        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task('debug reload')
            step = app.repo.save_step(task['task_id'], {
                'name': 'failed debug',
                'input_schema': {'type': 'object', 'properties': {'details': {'type': 'object'}}},
                'step_content': 'async def run(ctx, inputs):\n    raise RuntimeError("temporary failure")\n',
            })
            # Seed two frozen run records: no worker is needed to verify that
            # rebuilding this tab must retain its explicitly selected record.
            trial = app.repo.create_run(task['task_id'], {}, app.registry.versions,
                                        trial_step_id=step['step_id'])
            later = app.repo.create_run(task['task_id'], {}, app.registry.versions,
                                        trial_step_id=step['step_id'])
            for row, timestamp in ((trial, '2026-09-30T00:00:00'), (later, '2026-09-30T00:00:01')):
                app.repo.execute('UPDATE task_runs SET status=?, started_at=? WHERE run_id=?',
                                 ('FAILED', timestamp, row['run_id']))
            controller, recovery = DesktopController(app), {}
            first, second = Client(page('/debug-reload-first')), Client(page('/debug-reload-second'))
            async def scenario():
                with first:
                    wb = Workbench(controller, reload_state=recovery)
                    wb.trials[step['step_id']] = trial['run_id']
                    await wb.restore_route('editor', task['task_id'], step['step_id'], True)
                    await wb.paint()
                    wb.step_editor.view['trial_form'].step_form.controls['details'][1].value = '{未完成'
                    wb.step_editor.view['trial_ai_supplement'].value = '保留中文修复说明，不能重复执行'
                    wb.debug_state.removed_feedback.add('trial_logs')
                    wb.capture_reload_state()
                first.delete()
                with second:
                    restored = Workbench(controller, reload_state=recovery)
                    await restored.restore_route('editor', task['task_id'], step['step_id'], True)
                    await restored.paint()
                    self.assertEqual(restored.trials.get(step['step_id']), trial['run_id'])
                    self.assertIn('trial_logs', restored.debug_state.removed_feedback)
                    self.assertEqual(restored.step_editor.view['trial_ai_supplement'].value,
                                     '保留中文修复说明，不能重复执行')
                    form = restored.step_editor.view['trial_form']
                    self.assertEqual(form.step_form.controls['details'][1].value, '{未完成')
                    with self.assertRaises(TaskError):
                        form.step_values()
                    # The run and its original attempt are unchanged by restore.
                    actual = await controller.call('run.get', run_id=trial['run_id'])
                    self.assertEqual(actual['status'], 'FAILED')
                    self.assertEqual(len(actual['attempts']), 0)
            try:
                asyncio.run(scenario())
            finally:
                for client in (first, second):
                    if client.id in Client.instances:
                        client.delete()

    def test_new_tab_recovery_uses_the_stored_mapping_and_detaches_a_copied_tab(self):
        from nicegui.observables import ObservableDict
        from taskweave.desktop.launcher import tab_reload_state
        original = ObservableDict()
        first = tab_reload_state(original)
        first['step'] = {'fields': {'name': 'first draft'}}
        self.assertEqual(original['workbench_reload']['step']['fields']['name'], 'first draft')
        # NiceGUI copies tab storage values when a document gets a new tab ID.
        copied = ObservableDict(original)
        second = tab_reload_state(copied)
        second['step']['fields']['name'] = 'second draft'
        self.assertEqual(original['workbench_reload']['step']['fields']['name'], 'first draft')
        self.assertEqual(copied['workbench_reload']['step']['fields']['name'], 'second draft')

    def test_reload_retains_incomplete_bindings_and_input_drafts_in_its_own_tab(self):
        from unittest.mock import patch
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page
        from taskweave.application.service import Application
        from taskweave.desktop.controller import DesktopController
        original_button = ui.button
        def tracked_button(*args, **kwargs):
            button = original_button(*args, **kwargs)
            button.test_click = kwargs.get('on_click')
            return button
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task('incomplete reload')
            step = app.repo.save_step(task['task_id'], {'name': 'original',
                'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n'})
            controller, recovery = DesktopController(app), {}
            first = Client(page('/incomplete-first'))
            reloaded = Client(page('/incomplete-reloaded'))
            other = Client(page('/separate-tab'))
            async def scenario():
                with first, patch('nicegui.ui.button', side_effect=tracked_button):
                    wb = Workbench(controller, reload_state=recovery)
                    await wb.navigate('editor', task_id=task['task_id'], step_id=step['step_id'])
                    add = next(e for e in first.elements.values() if getattr(e, 'text', None) == '添加绑定')
                    await add.test_click()
                    wb.edit_controls['name'].value = 'draft in this tab'
                    row = wb.edit_controls['bindings'][0]
                    row[2].value = '{unfinished 中文'
                    wb.run_input_dialog.state.drafts[('run', 'request')] = {'step': {'json': '{unfinished'}}
                    wb.capture_reload_state()
                    first.delete()
                with reloaded:
                    wb = Workbench(controller, reload_state=recovery)
                    await wb.restore_route('editor', task['task_id'], step['step_id'])
                    await wb.paint()
                    row = wb.edit_controls['bindings'][0]
                    self.assertEqual(row[0].value, '')
                    self.assertEqual(row[2].value, '{unfinished 中文')
                    self.assertEqual(wb.run_input_dialog.state.drafts[('run', 'request')]['step']['json'], '{unfinished')
                with other:
                    wb = Workbench(controller, reload_state={})
                    await wb.navigate('editor', task_id=task['task_id'], step_id=step['step_id'])
                    self.assertEqual(wb.edit_controls['name'].value, 'original')
                    self.assertEqual(wb.edit_controls['bindings'], [])
                    self.assertEqual(wb.run_input_dialog.state.drafts, {})
                    self.assertEqual(app.repo.step(step['step_id'])['name'], 'original')
            try:
                asyncio.run(scenario())
            finally:
                if not first.is_deleted:
                    first.delete()
                reloaded.delete()
                other.delete()

    def test_disconnect_does_not_cache_clean_saved_or_discarded_steps(self):
        from unittest.mock import patch
        from nicegui.client import Client
        from nicegui.page import page
        from taskweave.application.service import Application
        from taskweave.desktop.controller import DesktopController

        class DiscardDialog:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def __await__(self):
                async def choice(): return 'discard'
                return choice().__await__()

        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task('clean reload')
            step = app.repo.save_step(task['task_id'], {'name': 'original',
                'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n'})
            client, recovery = Client(page('/clean-step-reload')), {}
            async def scenario():
                with client:
                    wb = Workbench(DesktopController(app), reload_state=recovery)
                    await wb.navigate('editor', task_id=task['task_id'], step_id=step['step_id'])
                    wb.capture_reload_state()
                    self.assertNotIn('step', recovery)
                    wb.edit_controls['name'].value = 'explicitly saved'
                    await wb.save_editor()
                    wb.capture_reload_state()
                    self.assertNotIn('step', recovery)
                    wb.edit_controls['name'].value = 'discarded'
                    wb.capture_reload_state()
                    self.assertIn('step', recovery)
                    with patch('taskweave.desktop.workbench.ui.dialog', return_value=DiscardDialog()):
                        await wb.navigate('home')
                    wb.capture_reload_state()
                    self.assertNotIn('step', recovery)
                    self.assertEqual(app.repo.step(step['step_id'])['name'], 'explicitly saved')
            try:
                asyncio.run(scenario())
            finally:
                client.delete()

    def test_reload_restores_raw_step_draft_without_saving_or_relaxing_conflicts(self):
        from unittest.mock import patch
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page
        from taskweave.application.service import Application
        from taskweave.desktop.controller import DesktopController
        from taskweave.core.validation import TaskError

        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task('reload drafts')
            step = app.repo.save_step(task['task_id'], {'name': 'persisted',
                'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n'})
            controller, recovery = DesktopController(app), {}
            first = Client(page('/raw-draft-first'))
            second = Client(page('/raw-draft-reload'))
            async def scenario():
                with first:
                    wb = Workbench(controller, reload_state=recovery)
                    await wb.navigate('editor', task_id=task['task_id'], step_id=step['step_id'])
                    wb.edit_controls['name'].value = '未保存中文标题'
                    wb.edit_controls['step_notes'].value = '长说明保留\n' * 20
                    schema = wb.edit_controls['schema']
                    schema.add('金额', {'type': 'number'})
                    schema.rows[0][2].value = '{invalid-json'
                    wb.capture_reload_state()
                    self.assertEqual(app.repo.step(step['step_id'])['name'], 'persisted')
                first.delete()
                # A concurrent saved version must not become the recovered
                # draft's new optimistic-lock baseline.
                app.repo.save_step(task['task_id'], {**step, 'name': 'other saved version'},
                                   step_id=step['step_id'], expected_hash=step['content_hash'])
                with second:
                    wb = Workbench(controller, reload_state=recovery)
                    await wb.restore_route('editor', task['task_id'], step['step_id'])
                    await wb.paint()
                    self.assertEqual(wb.edit_controls['name'].value, '未保存中文标题')
                    self.assertEqual(wb.edit_controls['step_notes'].value, '长说明保留\n' * 20)
                    self.assertEqual(wb.edit_controls['schema'].rows[0][2].value, '{invalid-json')
                    self.assertTrue(wb._step_editor_is_dirty())
                    self.assertEqual(wb.old_step['content_hash'], step['content_hash'])
                    with self.assertRaises(TaskError):
                        wb.document()
                    wb.edit_controls['schema'].rows[0][2].value = '12'
                    with self.assertRaises(TaskError) as conflict:
                        await wb.save_editor()
                    self.assertEqual(conflict.exception.code, 'EDIT_CONFLICT')
                    self.assertEqual(wb.edit_controls['name'].value, '未保存中文标题')
                    self.assertEqual(app.repo.step(step['step_id'])['name'], 'other saved version')
            try:
                asyncio.run(scenario())
            finally:
                if not first.is_deleted:
                    first.delete()
                second.delete()

    def test_step_editor_is_manual_and_builds_debug_only_on_open(self):
        from nicegui.client import Client
        from nicegui.page import page
        from taskweave.application.service import Application
        from taskweave.desktop.controller import DesktopController

        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task("autosave")
            step = app.repo.save_step(task['task_id'], {
                'name': 'original',
                'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n',
            })
            client = Client(page('/ui2-autosave-success'))
            async def scenario():
                with client:
                    workbench = Workbench(DesktopController(app))
                    self.assertTrue(await workbench.navigate('editor', task_id=task['task_id'], step_id=step['step_id']))
                    workbench.edit_controls['name'].value = 'edited-name'
                    self.assertEqual(workbench._step_editor().timers, [])
                    self.assertIsNone(workbench._editor_view('trial_form'))
                    self.assertEqual(app.repo.step(step['step_id'])['name'], 'original')
                    elements = list(client.elements.values())
                    self.assertNotIn('确认验证并保存', [getattr(e, 'text', None) for e in elements])
                    self.assertIn('确认验证', [getattr(e, 'text', None) for e in elements])
                    await workbench.save_editor()
                    self.assertEqual(app.repo.step(step['step_id'])['name'], 'edited-name')
                    self.assertEqual(workbench._editor_view('save_state').text, '已保存')
            try:
                asyncio.run(scenario())
            finally:
                client.delete()

    def test_debug_hosts_reopen_without_rebuilding_inputs_or_writing_draft(self):
        from unittest.mock import patch
        from nicegui import ui
        from nicegui.client import Client
        from nicegui.page import page
        from taskweave.application.service import Application
        from taskweave.desktop.controller import DesktopController
        original_button = ui.button
        def tracked_button(*args, **kwargs):
            button = original_button(*args, **kwargs)
            button.test_click = kwargs.get('on_click')
            return button
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task('debug lazy')
            step = app.repo.save_step(task['task_id'], {'name': 'original',
                'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n'})
            from taskweave.presentation.flow_editor import insert_control
            original_flow = app.dispatch('task.flow.describe', {'task_id': task['task_id']})
            flow, _ = insert_control(original_flow['flow'], 'if')
            app.dispatch('task.flow.save', {'task_id': task['task_id'], 'flow': flow,
                                          'expected_hash': original_flow['definition_hash']})
            client = Client(page('/debug-lazy-sibling'))
            async def scenario():
                with client, patch('nicegui.ui.button', side_effect=tracked_button):
                    wb = Workbench(DesktopController(app))
                    await wb.navigate('editor', task_id=task['task_id'], step_id=step['step_id'])
                    debug = next(e for e in client.elements.values() if 'tw-debug-column' in e.classes)
                    config = next(e for e in client.elements.values() if 'tw-editor-panel' in e.classes)
                    code_workspace = next(e for e in client.elements.values() if 'tw-step-code' in e.classes)
                    self.assertIs(debug.parent_slot.parent, code_workspace)
                    self.assertFalse(debug.visible)
                    toggle = next(e for e in client.elements.values() if getattr(e, 'text', None) == '调试')
                    wb.edit_controls['name'].value = 'unsaved draft'
                    await toggle.test_click()
                    form = wb._editor_view('trial_form')
                    self.assertIsNotNone(form)
                    self.assertTrue(debug.visible)
                    toolbar = next((e for e in client.elements.values() if 'tw-debug-session-toolbar' in e.classes), None)
                    self.assertIsNotNone(toolbar, 'Debug actions need their own session toolbar')
                    self.assertIs(toolbar.parent_slot.parent, config)
                    self.assertIsNotNone(wb._editor_view('trial_ai_channel'), 'Repair channel belongs in the sidebar')
                    self.assertIsNotNone(wb._editor_view('trial_ai_history'))
                    self.assertIsNotNone(wb.step_debug_panel.repair_evidence_area)
                    supplement = wb._editor_view('trial_ai_supplement')
                    supplement.value = '保留当前输入与业务逻辑'
                    original_code = wb.edit_controls['code']
                    environment = wb._editor_view('trial_environment')
                    parent = environment.parent_slot.parent
                    while parent is not toolbar and parent.parent_slot:
                        parent = parent.parent_slot.parent
                    self.assertIs(parent, toolbar)
                    self.assertEqual(app.repo.step(step['step_id'])['name'], 'original')
                    await toggle.test_click()
                    self.assertFalse(debug.visible)
                    self.assertFalse(toolbar.visible)
                    await toggle.test_click()
                    self.assertIs(wb._editor_view('trial_form'), form)
                    self.assertIs(wb.edit_controls['code'], original_code)
                    self.assertEqual(wb._editor_view('trial_ai_supplement').value, '保留当前输入与业务逻辑')
                    configure = next(e for e in client.elements.values() if e.props.get('aria-label') == '配置条件分支')
                    await configure.test_click()
                    self.assertFalse(toolbar.visible)
                    self.assertFalse(debug.visible)
                    return_step = next(e for e in client.elements.values() if getattr(e, 'text', '') == '返回步骤')
                    await return_step.test_click()
                    self.assertTrue(toolbar.visible)
                    self.assertIs(wb._editor_view('trial_form'), form)
                    self.assertEqual(wb.edit_controls['name'].value, 'unsaved draft')
                    with self.assertRaisesRegex(Exception, '先保存步骤'):
                        await wb.step_for_confirmation()
                    await wb.save_editor()
                    self.assertEqual((await wb.step_for_confirmation())['name'], 'unsaved draft')
            try:
                asyncio.run(scenario())
            finally:
                client.delete()

    def test_step_editor_manual_save_failure_keeps_dirty_draft(self):
        from nicegui.client import Client
        from nicegui.page import page
        from taskweave.application.service import Application
        from taskweave.core.validation import TaskError
        from taskweave.desktop.controller import DesktopController

        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task("autosave failure")
            step = app.repo.save_step(task['task_id'], {
                'name': 'original',
                'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n',
            })
            client = Client(page('/ui2-autosave-failure'))
            async def scenario():
                with client:
                    workbench = Workbench(DesktopController(app))
                    await workbench.navigate('editor', task_id=task['task_id'], step_id=step['step_id'])
                    workbench.edit_controls['name'].value = 'draft-after-failure'
                    workbench.controller.save_draft = AsyncMock(side_effect=TaskError('EDIT_CONFLICT'))
                    with self.assertRaises(TaskError):
                        await workbench.save_editor()
                    self.assertEqual(app.repo.step(step['step_id'])['name'], 'original')
                    self.assertEqual(workbench._editor_view('save_state').text, '保存失败，点击重试')
                    self.assertTrue(workbench._step_editor_is_dirty())
            try:
                asyncio.run(scenario())
            finally:
                client.delete()

    def test_late_manual_save_response_cannot_mutate_next_editor(self):
        from types import SimpleNamespace
        from nicegui.client import Client
        from nicegui.page import page
        from taskweave.application.service import Application
        from taskweave.desktop.controller import DesktopController

        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task("late autosave")
            first = app.repo.save_step(task['task_id'], {
                'name': 'first', 'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n',
            })
            second = app.repo.save_step(task['task_id'], {
                'name': 'second', 'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n',
            })
            client = Client(page('/ui2-autosave-late'))
            async def scenario():
                with client:
                    workbench = Workbench(DesktopController(app))
                    await workbench.navigate('editor', task_id=task['task_id'], step_id=first['step_id'])
                    entered, release = asyncio.Event(), asyncio.Event()
                    original_save = workbench.controller.save_draft
                    async def delayed_save(*args):
                        entered.set()
                        await release.wait()
                        return await original_save(*args)
                    workbench.controller.save_draft = delayed_save
                    workbench.edit_controls['name'].value = 'first autosaved'
                    pending = asyncio.create_task(workbench.save_editor())
                    await entered.wait()
                    new_state_control = SimpleNamespace(text='second saved', is_deleted=False)
                    workbench.step_state.step_id = second['step_id']
                    workbench.step_state.old_step = second
                    workbench.step_state.generation += 1
                    workbench._step_editor().view['save_state'] = new_state_control
                    release.set()
                    await pending
                    self.assertEqual(app.repo.step(first['step_id'])['name'], 'first autosaved')
                    self.assertEqual(app.repo.step(second['step_id'])['name'], 'second')
                    self.assertEqual(workbench.step_state.old_step['step_id'], second['step_id'])
                    self.assertEqual(new_state_control.text, 'second saved')
            try:
                asyncio.run(scenario())
            finally:
                client.delete()

    def test_late_step_context_list_cannot_publish_into_next_editor(self):
        async def scenario():
            from dataclasses import MISSING, fields
            from types import SimpleNamespace
            from taskweave.desktop.components.step_editor import StepEditor, StepEditorRenderContext

            entered, release = asyncio.Event(), asyncio.Event()
            identity = {"page_generation": 1}
            state = StepEditorState(task_id="task-a", step_id="step-a", generation=1)
            context_state = SimpleNamespace(entries=["old-a"], ai_contexts=["old-ai-a"])
            async def call(operation, **kwargs):
                if operation == "step.list":
                    return [{"step_id": "step-a", "name": "A", "position": 0}]
                if operation == "context.list":
                    entered.set()
                    await release.wait()
                    return ["late-a"]
                raise AssertionError(operation)

            required = {
                item.name: None for item in fields(StepEditorRenderContext)
                if item.default is MISSING and item.default_factory is MISSING
            }
            required.update(
                state=state,
                context_state=context_state,
                controller=SimpleNamespace(call=call),
                page_getter=lambda: "editor",
                page_generation_getter=lambda: identity["page_generation"],
            )
            context = StepEditorRenderContext(**required)
            editor = StepEditor(context.controller, state, lambda: identity["page_generation"])
            rendering = asyncio.create_task(editor.render(context))
            await entered.wait()
            state.task_id, state.step_id = "task-b", "step-b"
            state.generation += 1
            identity["page_generation"] += 1
            context_state.entries = ["current-b"]
            context_state.ai_contexts = ["current-ai-b"]
            release.set()
            await rendering

            self.assertEqual(context_state.entries, ["current-b"])
            self.assertEqual(context_state.ai_contexts, ["current-ai-b"])

        asyncio.run(scenario())

    def test_step_editor_owns_pending_state_refresh_and_input_apply(self):
        async def scenario():
            from types import SimpleNamespace
            from taskweave.desktop.components.step_editor import StepEditor

            identity = ["task", "step", 3, 4]
            saved = {"step_id": "step", "input_schema": {}}
            calls = []
            class Control:
                is_deleted = False
                def __init__(self): self.text = "已保存"
                def props(self, *args, **kwargs): calls.append(("props", args, kwargs))
                def style(self, value): calls.append(("style", value))
            class Area:
                is_deleted = False
                def clear(self): calls.append(("clear",))
                def __enter__(self): return self
                def __exit__(self, *_): pass
            class Form:
                def task_edits(self): return {"a": "draft"}
                def step_edits(self): return {"b": 2}
                async def refresh(self, step, environment, task_edits, step_edits):
                    calls.append(("refresh", step, environment, task_edits, step_edits))
                def apply_task_values(self, values): calls.append(("task_values", values))
                def apply_step_values(self, values): calls.append(("step_values", values))
            state = StepEditorState(task_id="task", step_id="step", old_step={"step_id":"step"}, generation=3)
            controller = SimpleNamespace(call=AsyncMock(return_value={"step_id":"step", "name":"Step"}))
            editor = StepEditor(controller, state, lambda: identity[3])
            form = Form()
            editor.view.update(
                save_state=Control(), selected_step_control=Control(),
                trial_variables_area=Area(), trial_form=form,
                trial_environment=SimpleNamespace(value="uat"),
            )

            result = await editor.mark_step_pending()
            self.assertEqual(result["step_id"], "step")
            self.assertEqual(state.old_step["name"], "Step")
            self.assertEqual(editor.view["save_state"].text, "已保存 · 待确认")
            self.assertEqual(calls[-2][0], "props")

            await editor.refresh_trial_inputs(saved)
            self.assertEqual(calls[-1], ("refresh", saved, "uat", {"a":"draft"}, {"b":2}))
            self.assertTrue(editor.apply_trial_values({"scope":"task"}, {"x":1}, editor.identity()))
            self.assertEqual(calls[-1], ("task_values", {"x":1}))

        asyncio.run(scenario())

    def test_step_editor_pending_read_ignores_stale_editor_identity(self):
        async def scenario():
            from types import SimpleNamespace
            from taskweave.desktop.components.step_editor import StepEditor
            entered, release = asyncio.Event(), asyncio.Event()
            identity = ["task-a", "step-a", 1, 2]
            async def get_step(*_args, **_kwargs):
                entered.set()
                await release.wait()
                return {"step_id":"step-a", "name":"A"}
            state = StepEditorState(task_id="task-a", step_id="step-a", old_step={"step_id":"step-a"}, generation=1)
            editor = StepEditor(SimpleNamespace(call=get_step), state, lambda: identity[3])
            from unittest.mock import MagicMock
            original = dict(state.old_step)
            editor.view.update(save_state=SimpleNamespace(is_deleted=False, text="已保存"), selected_step_control=SimpleNamespace(is_deleted=False, props=MagicMock(), style=MagicMock()))
            pending = asyncio.create_task(editor.mark_step_pending())
            await entered.wait()
            identity[:] = ["task-b", "step-b", 2, 3]
            state.task_id, state.step_id, state.generation = "task-b", "step-b", 2
            release.set()
            await pending
            self.assertEqual(state.old_step, original)
            self.assertEqual(editor.view["save_state"].text, "已保存")
        asyncio.run(scenario())

    def test_trial_input_rebuild_clears_container_before_factory_renders(self):
        async def scenario():
            from types import SimpleNamespace
            from taskweave.desktop.components.step_editor import StepEditor
            events = []
            class Area:
                is_deleted = False
                active = False
                def clear(self): events.append("clear")
                def __enter__(self):
                    self.active = True
                    events.append("enter")
                    return self
                def __exit__(self, *_): self.active = False
            area = Area()
            state = StepEditorState(task_id="task", step_id="step", generation=2)
            async def factory(step, environment, values=None):
                events.append(("factory", area.active))
                return object()
            editor = StepEditor(SimpleNamespace(), state, lambda: 4, trial_variables=factory)
            editor.view.update(
                trial_variables_area=area, trial_form=None,
                trial_environment=SimpleNamespace(value="uat"),
            )
            await editor.refresh_trial_inputs({"step_id":"step"}, preserve_values=False)
            self.assertEqual(events, ["clear", "enter", ("factory", True)])
            self.assertIsNotNone(editor.view["trial_form"])
        asyncio.run(scenario())

    def test_queued_save_rechecks_identity_after_acquiring_the_serial_lock(self):
        async def scenario():
            from taskweave.core.validation import TaskError

            state = StepEditorState(task_id="task-a", step_id="step-a", old_step={"step_id": "step-a"})
            workbench = object.__new__(Workbench)
            workbench.step_state = state
            workbench.page_generation = 1
            workbench.controller = AsyncMock()
            workbench.document = lambda: {"name": "draft A"}
            await state.save_lock.acquire()
            queued = asyncio.create_task(workbench.save_editor())
            await asyncio.sleep(0)
            state.task_id, state.step_id = "task-b", "step-b"
            state.old_step = {"step_id": "step-b"}
            state.generation += 1
            workbench.page_generation += 1
            state.save_lock.release()

            with self.assertRaises(TaskError) as raised:
                await queued
            self.assertEqual(raised.exception.code, "EDITOR_CHANGED")
            workbench.controller.save_draft.assert_not_awaited()
            self.assertEqual(state.old_step, {"step_id": "step-b"})

        asyncio.run(scenario())

    def test_queued_save_uses_latest_old_step_and_keeps_triggered_document_snapshot(self):
        async def scenario():
            from taskweave.desktop.components.step_editor import StepEditor

            entered, release = asyncio.Event(), asyncio.Event()
            calls = []
            async def save_draft(task_id, document, old_step):
                calls.append((document, old_step))
                if len(calls) == 1:
                    entered.set()
                    await release.wait()
                    return {"step_id": "step-a", "content_hash": "h1"}
                return {"step_id": "step-a", "content_hash": "h2"}

            state = StepEditorState(task_id="task-a", step_id="step-a", old_step={"step_id": "step-a", "content_hash": "h0"})
            editor = StepEditor(SimpleNamespace(save_draft=save_draft), state, lambda: 1)
            first = asyncio.create_task(editor.save({"draft": "first"}))
            await entered.wait()
            second = asyncio.create_task(editor.save({"draft": "second"}))
            await asyncio.sleep(0)
            release.set()
            await asyncio.gather(first, second)

            self.assertEqual([item[1]["content_hash"] for item in calls], ["h0", "h1"])
            self.assertEqual([item[0] for item in calls], [{"draft": "first"}, {"draft": "second"}])
            self.assertEqual(state.old_step["content_hash"], "h2")

        from types import SimpleNamespace
        from unittest.mock import MagicMock
        asyncio.run(scenario())

    def test_non_endable_debug_run_disables_stale_end_action(self):
        async def scenario():
            from unittest.mock import MagicMock

            workbench = object.__new__(Workbench)
            workbench.page = "editor"
            workbench.page_generation = 2
            workbench.step_state = StepEditorState(task_id="task", step_id="step", old_step={"step_id": "step"})
            workbench.trials = {"step": "run"}
            panel = MagicMock()
            panel.end = AsyncMock()
            panel.refresh_trial = AsyncMock()
            workbench.step_debug_panel = panel
            workbench.controller = SimpleNamespace(call=AsyncMock(return_value={"can_end": False, "status": "SUCCEEDED", "request_json": "{}"}))
            workbench.confirm_end = AsyncMock()

            await workbench.end_trial()

            panel.end.assert_awaited_once_with(workbench.confirm_end, panel.refresh_trial)
            workbench.confirm_end.assert_not_awaited()

        from types import SimpleNamespace
        from unittest.mock import MagicMock
        asyncio.run(scenario())

    def test_late_debug_end_lookup_does_not_change_next_editor_button(self):
        async def scenario():
            from unittest.mock import MagicMock
            from taskweave.desktop.components.step_debug import StepDebugPanel

            entered, release = asyncio.Event(), asyncio.Event()
            async def get_run(*args, **kwargs):
                entered.set()
                await release.wait()
                return {"can_end": True}

            identity = ["task", "step-a", 8, 4]
            end_button = MagicMock(is_deleted=False)
            callbacks = {}
            def button(title, callback, **kwargs):
                callbacks[title] = kwargs
                return end_button if title == "结束调试" else MagicMock(is_deleted=False)
            panel = StepDebugPanel(button, SimpleNamespace(call=AsyncMock(side_effect=get_run)), lambda: tuple(identity), lambda step: "run-a", lambda: None)
            panel.render_actions(MagicMock(), AsyncMock(), AsyncMock(), AsyncMock())

            pending = asyncio.create_task(callbacks["结束调试"]["on_settled"]())
            await entered.wait()
            identity[:] = ["task", "step-b", 9, 5]
            release.set()
            await pending
            end_button.set_enabled.assert_not_called()

        from types import SimpleNamespace
        from unittest.mock import MagicMock
        asyncio.run(scenario())

    def test_late_save_persists_original_step_without_mutating_new_editor(self):
        async def scenario():
            entered = asyncio.Event()
            release = asyncio.Event()
            controller = AsyncMock()

            async def save(task_id, document, old_step):
                entered.set()
                await release.wait()
                return {"task_id": task_id, "step_id": old_step["step_id"], "document": document}

            controller.save_draft.side_effect = save
            workbench = object.__new__(Workbench)
            workbench.step_state = StepEditorState(
                task_id="task-a", step_id="step-a", old_step={"step_id": "step-a"},
            )
            workbench.controller = controller
            workbench.document = lambda: {"name": "A draft"}

            pending = asyncio.create_task(workbench.save_editor())
            await entered.wait()
            workbench.step_state.task_id = "task-b"
            workbench.step_state.step_id = "step-b"
            workbench.step_state.old_step = {"step_id": "step-b"}
            workbench.step_state.generation += 1
            release.set()
            saved = await pending

            controller.save_draft.assert_awaited_once_with("task-a", {"name": "A draft"}, {"step_id": "step-a"})
            self.assertEqual(saved["step_id"], "step-a")
            self.assertEqual(workbench.old_step, {"step_id": "step-b"})
            self.assertEqual(workbench.step_id, "step-b")

        asyncio.run(scenario())


    def test_debug_panel_owns_end_run_state_transition(self):
        async def scenario():
            from types import SimpleNamespace
            from taskweave.desktop.components.step_debug import StepDebugPanel
            from unittest.mock import MagicMock

            identity = ("task", "step", 1, 2)
            controller = SimpleNamespace(call=AsyncMock(return_value={"can_end": False, "status": "SUCCEEDED", "request_json": "{}"}))
            panel = StepDebugPanel(MagicMock(), controller, lambda: identity, lambda step: "run", lambda: None)
            panel.actions = {"end": MagicMock(is_deleted=False)}
            confirm = AsyncMock()
            refresh = AsyncMock()
            await panel.end(confirm, refresh)
            confirm.assert_not_awaited()
            refresh.assert_not_awaited()
            panel.actions["end"].set_enabled.assert_called_once_with(False)

        asyncio.run(scenario())

    def test_step_editor_disposes_owned_refresh_timers_on_navigation(self):
        from taskweave.desktop.components.step_editor import StepEditor
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        state = StepEditorState(task_id="task", step_id="step")
        editor = StepEditor(SimpleNamespace(), state, lambda: 1)
        timer = SimpleNamespace(is_deleted=False, delete=MagicMock())
        editor.own_timer(timer)
        editor.dispose()
        editor.dispose()

        timer.delete.assert_called_once_with()
        self.assertEqual(editor.timers, [])


if __name__ == "__main__":
    unittest.main()


class RouteRestoreTests(unittest.TestCase):
    def test_restore_editor_checks_identity_and_remembers_debug(self):
        async def scenario():
            from unittest.mock import AsyncMock, MagicMock, patch
            from types import SimpleNamespace
            controller = SimpleNamespace(call=AsyncMock(side_effect=[{"task_id": "t"}, {"task_id": "t", "step_id": "s"}]), plugin_contributions=MagicMock(return_value=[]), reset_debug_conversation=MagicMock())
            writer = MagicMock()
            with patch("taskweave.desktop.workbench.ui", MagicMock()):
                workbench = Workbench(controller, route_writer=writer)
            await workbench.restore_route("editor", "t", "s", True)
            self.assertEqual((workbench.page, workbench.task_id, workbench.step_id), ("editor", "t", "s"))
            self.assertTrue(workbench._open_debug_on_navigation)
            workbench.debug_visibility_changed(True)
            self.assertEqual(writer.call_args.args[0]["debug"], "true")
        asyncio.run(scenario())
