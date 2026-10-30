"""Real NiceGUI component wiring for the local generation panel."""
import asyncio
import tempfile
import unittest
from tests.test_local_codegen import build_registry,recorded_capture
from taskweave.application.service import Application
from taskweave.desktop.controller import DesktopController
from taskweave.desktop.workbench import Workbench


class StepCodegenTests(unittest.TestCase):
    def test_selected_plugin_shows_shared_recording_panel_and_applies_candidate(self):
        from nicegui.client import Client
        from nicegui.page import page
        with tempfile.TemporaryDirectory() as home, Application(home,registry_factory='tests.test_local_codegen:build_registry') as app:
            task=app.repo.create_task('Codegen panel')
            step=app.repo.save_step(task['task_id'],{'name':'Search','capabilities':list(app.registry.actions),
                'step_content':'async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n',
                'input_schema':{'type':'object','properties':{'order_no':{'type':'string'}}}})
            app.contexts.save(step['step_id'],'playwright.page','Search recording','draft',recorded_capture()['items'])
            client=Client(page('/local-codegen'))
            async def run():
                with client:
                    wb=Workbench(DesktopController(app))
                    await wb.navigate('editor',task_id=task['task_id'],step_id=step['step_id'])
                    self.assertTrue(any(getattr(e,'text',None)=='本地代码生成' for e in client.elements.values()))
                    panel=wb.step_editor.view['local_codegen']
                    await panel.open()
                    self.assertEqual(len(panel.flow.sources),1)
                    await panel.generate()
                    self.assertFalse(panel.flow.result['applicable'])
                    self.assertFalse(any('# 完整候选在左侧预览' in str(getattr(e,'content','')) for e in client.elements.values()))
                    panel.flow.bindings={'action:1:value':{'input':'order_no'}}
                    await panel.generate()
                    self.assertTrue(panel.flow.result['applicable'])
                    actual=[e for e in client.elements.values() if 'tw-codegen-source' in e.classes]
                    self.assertTrue(actual,'The code panel must show the generated source')
                    self.assertEqual(actual[-1].content.rstrip(),panel.flow.result['source'].rstrip())
                    await panel.apply('replace',confirmed=True)
                    self.assertIn("inputs['order_no']",wb.edit_controls['code'].value)
                    self.assertEqual(app.repo.step(step['step_id'])['step_content'],step['step_content'])
                    self.assertFalse(any(getattr(e,'text',None)=='开始录制' for e in client.elements.values() if 'tw-local-codegen' in e.classes))
            try:asyncio.run(run())
            finally:client.delete()

    def test_incomplete_recording_shows_reason_without_fake_code_or_editor_change(self):
        from nicegui.client import Client
        from nicegui.page import page
        with tempfile.TemporaryDirectory() as home, Application(home,registry_factory='tests.test_local_codegen:build_registry') as app:
            task=app.repo.create_task('Incomplete recording')
            original='async def run(ctx, inputs):\n    return ctx.result(data={"keep": True})\n'
            step=app.repo.save_step(task['task_id'],{'name':'Keep source','capabilities':list(app.registry.actions),'step_content':original})
            capture=recorded_capture(complete=False,issues=['DOCUMENT_UNSEALED'])
            app.contexts.save(step['step_id'],'playwright.page','Incomplete','draft',capture['items'])
            client=Client(page('/incomplete-codegen'))
            async def run():
                with client:
                    wb=Workbench(DesktopController(app));await wb.navigate('editor',task_id=task['task_id'],step_id=step['step_id'])
                    panel=wb.step_editor.view['local_codegen'];await panel.open();await panel.generate()
                    self.assertFalse(panel.flow.result['applicable'])
                    self.assertEqual(wb.edit_controls['code'].value,original)
                    self.assertFalse(any('tw-codegen-source' in e.classes for e in client.elements.values()))
                    errors=[e for e in client.elements.values() if 'tw-codegen-error' in e.classes]
                    self.assertTrue(errors,'Blocking diagnostics must be visible without switching result tabs')
                    self.assertTrue(any('未生成可用代码' in str(getattr(e,'text','')) for e in errors))
            try:asyncio.run(run())
            finally:client.delete()

    def test_refresh_changed_material_removes_previous_full_preview(self):
        from nicegui.client import Client
        from nicegui.page import page
        with tempfile.TemporaryDirectory() as home, Application(home,registry_factory='tests.test_local_codegen:build_registry') as app:
            task=app.repo.create_task('Preview invalidation')
            original='async def run(ctx, inputs):\n    return ctx.result(data={"keep": True})\n'
            step=app.repo.save_step(task['task_id'],{'name':'Keep draft','capabilities':list(app.registry.actions),'step_content':original})
            app.contexts.save(step['step_id'],'playwright.page','Recording','draft',recorded_capture()['items'])
            client=Client(page('/changed-preview'))
            async def run():
                with client:
                    wb=Workbench(DesktopController(app));await wb.navigate('editor',task_id=task['task_id'],step_id=step['step_id'])
                    panel=wb.step_editor.view['local_codegen'];await panel.open()
                    panel.flow.bindings={'action:1:value':{'constant':True}};await panel.generate();panel.preview()
                    self.assertTrue(panel.previewing)
                    row=panel.flow.sources[0];capture=recorded_capture(complete=False,issues=['EXTRA_PAGE'])
                    app.contexts.replace_capture(row['context_id'],row['capture_id'],{'items':capture['items']},step_id=step['step_id'])
                    await panel.open()
                    self.assertFalse(panel.previewing)
                    self.assertTrue(wb.edit_controls['code'].visible)
                    self.assertIsNone(panel.flow.result)
                    self.assertEqual(panel.flow.bindings,{})
                    await panel.generate()
                    self.assertFalse(panel.flow.result['applicable'])
                    self.assertFalse(panel.previewing)
                    self.assertEqual(wb.edit_controls['code'].value,original)
            try:asyncio.run(run())
            finally:client.delete()

    def test_refresh_contexts_button_loads_new_recordings_without_switching_page(self):
        from nicegui.client import Client
        from nicegui.page import page
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as home, Application(home,registry_factory='tests.test_local_codegen:build_registry') as app:
            task=app.repo.create_task('Refresh contexts')
            original='async def run(ctx, inputs):\n    return ctx.result(data={"draft": True})\n'
            step=app.repo.save_step(task['task_id'],{'name':'Keep editor','capabilities':list(app.registry.actions),'step_content':original})
            client=Client(page('/refresh-codegen-contexts'))
            async def run():
                with client:
                    wb=Workbench(DesktopController(app));await wb.navigate('editor',task_id=task['task_id'],step_id=step['step_id'])
                    panel=wb.step_editor.view['local_codegen'];await panel.open()
                    self.assertEqual(panel.flow.sources,[])
                    app.contexts.save(step['step_id'],'playwright.page','New recording','draft',recorded_capture()['items'])
                    async def refresh_click():
                        button=next(e for e in client.elements.values() if getattr(e,'text',None)=='刷新上下文')
                        with patch('nicegui.elements.button.handle_event') as dispatch:
                            next(v.handler for v in button._event_listeners.values() if v.type=='click')(None)
                        with patch('taskweave.desktop.components.step_codegen.ui.notify') as feedback:
                            await dispatch.call_args.args[0]()
                        return feedback
                    notify=await refresh_click()
                    notify.assert_called_once()
                    self.assertEqual(len(panel.flow.sources),1)
                    selected=panel.flow.selected
                    app.contexts.save(step['step_id'],'playwright.page','Another recording','draft',recorded_capture()['items'])
                    await refresh_click()
                    self.assertEqual(len(panel.flow.sources),2)
                    self.assertEqual(panel.flow.selected,selected)
                    choice=next(e for e in client.elements.values() if getattr(e,'label',None)=='录制上下文')
                    self.assertEqual(len(choice.options),2)
                    self.assertEqual(wb.edit_controls['code'].value,original)
                    self.assertIs(wb.step_editor.view['local_codegen'],panel)
            try:asyncio.run(run())
            finally:client.delete()
