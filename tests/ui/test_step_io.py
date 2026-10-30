"""Input/output schema editing keeps saved definitions, bindings and raw drafts."""
import asyncio
import tempfile
import unittest

from nicegui.client import Client
from nicegui.page import page
from taskweave.application.service import Application
from taskweave.core.validation import TaskError
from taskweave.desktop.controller import DesktopController
from taskweave.desktop.workbench import Workbench


class StepIOTests(unittest.TestCase):
    def test_changing_string_field_type_does_not_keep_its_empty_string_default(self):
        from taskweave.desktop.forms import StepSchemaEditor
        client=Client(page('/step-io-type-change'))
        try:
            with client:
                editor=StepSchemaEditor('输入 Schema',{'type':'object','properties':{'value':{'type':'string','default':''}}})
                editor.rows[0][1].set_value('integer')
                self.assertNotIn('default',editor.schema()['properties']['value'])
        finally:client.delete()

    def test_opening_switching_and_noop_save_preserve_empty_defaults_and_confirmation(self):
        async def scenario(app,client):
            task=app.repo.create_task('lossless schema')
            original={'type':'object','properties':{
                'empty':{'type':'string','default':'','description':'  保留说明  '},
                'note':{'type':'string','description':''}},'additionalProperties':False}
            step=app.repo.save_step(task['task_id'], {'name':'lossless','input_schema':original,'output_schema':original,
                'step_content':'async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n'})
            await asyncio.to_thread(app.confirm_step_manual,step['step_id'],step['content_hash'])
            with client:
                wb=Workbench(DesktopController(app))
                await wb.navigate('editor',task_id=task['task_id'],step_id=step['step_id'])
                self.assertEqual(wb.step_editor.document()['input_schema'],original)
                self.assertEqual(wb.step_editor.document()['output_schema'],original)
                self.assertFalse(wb._step_editor_is_dirty())
                for key in ('schema','output_schema'):
                    wb.edit_controls[key].edit_mode.set_value('json')
                    wb.edit_controls[key].edit_mode.set_value('form')
                self.assertFalse(wb._step_editor_is_dirty())
                self.assertEqual(next(e for e in client.elements.values() if 'tw-save-state' in e.classes).text,'已保存')
                await wb.step_editor.save()
                saved=app.repo.step(step['step_id'])
                self.assertEqual(saved['content_hash'],step['content_hash'])
                self.assertEqual(saved['validation_state'],'VALIDATED')
        self.run_scenario(scenario)

    def test_field_json_switch_is_lossless_and_invalid_or_complex_json_stays_editable(self):
        from nicegui import ui
        from taskweave.desktop.forms import StepSchemaEditor
        client=Client(page('/step-io-mode-switch'))
        try:
            with client:
                editor=StepSchemaEditor('输出 Schema',{})
                editor.add('count',{'type':'integer','default':0},True)
                editor.edit_mode.set_value('json')
                self.assertIn('"count"',editor.json_editor.value)
                editor.edit_mode.set_value('form')
                self.assertEqual(editor.schema()['properties']['count']['default'],0)
                editor.edit_mode.set_value('json')
                editor.json_editor.set_value('{"type":"unknown"}')
                with self.assertRaises(TaskError):editor.schema()
                editor.edit_mode.set_value('form')
                self.assertEqual(editor.edit_mode.value,'json')
                self.assertEqual(editor.json_editor.value,'{"type":"unknown"}')
                editor.json_editor.set_value('{"type":"array","items":{"type":"integer"}}')
                editor.edit_mode.set_value('form')
                self.assertEqual(editor.edit_mode.value,'json')
                self.assertEqual(editor.schema(),{'type':'array','items':{'type':'integer'}})
        finally:client.delete()

    def test_default_schema_definitions_are_visible_and_noop_keeps_output_unrestricted(self):
        async def scenario(app, client):
            task=app.repo.create_task('schema defaults')
            step=app.repo.save_step(task['task_id'], {'name':'defaults',
                'step_content':'async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n'})
            with client:
                wb=Workbench(DesktopController(app))
                await wb.navigate('editor',task_id=task['task_id'],step_id=step['step_id'])
                self.assertIn('输入输出',[e._props.get('label') for e in client.elements.values()])
                self.assertIn('output_schema',wb.edit_controls)
                self.assertEqual(wb.step_editor.document()['input_schema'],{'type':'object'})
                self.assertEqual(wb.step_editor.document()['output_schema'],{})
        self.run_scenario(scenario)

    def test_form_input_output_and_binding_edits_save_and_invalidate_old_confirmation(self):
        async def scenario(app,client):
            task=app.repo.create_task('schema forms')
            step=app.repo.save_step(task['task_id'], {'name':'forms',
                'step_content':'async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n',
                'input_schema':{'type':'object','properties':{'source':{'type':'integer'}}},
                'bindings':{'source':{'literal':7}}})
            await asyncio.to_thread(app.confirm_step_manual,step['step_id'],step['content_hash'])
            with client:
                wb=Workbench(DesktopController(app))
                await wb.navigate('editor',task_id=task['task_id'],step_id=step['step_id'])
                self.assertIn('output_schema',wb.edit_controls)
                wb.edit_controls['schema'].add('count',{'type':'integer','default':0},True)
                wb.edit_controls['output_schema'].add('summary',{'type':'string'},True)
                wb.edit_controls['bindings'][0][2].set_value('0')
                wb.step_editor.sync_draft()
                await wb.save_editor()
                saved=app.repo.step(step['step_id'])
                self.assertEqual(saved['input_schema']['properties']['count']['default'],0)
                self.assertIn('count',saved['input_schema']['required'])
                self.assertEqual(saved['bindings'],{'source':{'literal':0}})
                self.assertEqual(saved['output_schema'],{'type':'object','properties':{'summary':{'type':'string'}},'required':['summary']})
                self.assertEqual(saved['validation_state'],'DRAFT')
                self.assertNotEqual(saved['content_hash'],step['content_hash'])
                node=next(e for e in client.elements.values() if 'tw-flow-node' in e.classes and 'is-selected' in e.classes)
                self.assertFalse(any('tw-flow-validated' in e.classes and e.visible for e in node.descendants()))
        self.run_scenario(scenario)

    def test_complex_output_schema_is_preserved_and_both_json_editors_save(self):
        async def scenario(app,client):
            task=app.repo.create_task('schema json')
            schema={'type':'array','items':{'type':'object','properties':{'id':{'type':'integer'}},'required':['id']},'minItems':1}
            step=app.repo.save_step(task['task_id'], {'name':'json', 'output_schema':schema,
                'step_content':'async def run(ctx, inputs):\n    return ctx.result(data=[])\n'})
            with client:
                wb=Workbench(DesktopController(app))
                await wb.navigate('editor',task_id=task['task_id'],step_id=step['step_id'])
                self.assertIn('output_schema',wb.edit_controls)
                output=wb.edit_controls['output_schema']
                self.assertEqual(output.edit_mode.value,'json')
                self.assertEqual(wb.step_editor.document()['output_schema'],schema)
                inputs=wb.edit_controls['schema']
                inputs.edit_mode.set_value('json')
                inputs.json_editor.set_value('{"type":"object","properties":{"count":{"type":"integer","default":0}},"additionalProperties":false}')
                output.json_editor.set_value('{"type":"array","items":{"type":"integer"},"minItems":2}')
                wb.step_editor.sync_draft()
                await wb.step_editor.save()
                saved=app.repo.step(step['step_id'])
                self.assertFalse(saved['input_schema']['additionalProperties'])
                self.assertEqual(saved['output_schema'],{'type':'array','items':{'type':'integer'},'minItems':2})
        self.run_scenario(scenario)

    def test_invalid_output_json_survives_reload_and_never_overwrites_saved_definition(self):
        async def scenario(app,client):
            task=app.repo.create_task('schema recovery')
            original={'type':'object','properties':{'id':{'type':'integer'}},'additionalProperties':False}
            step=app.repo.save_step(task['task_id'], {'name':'recover','output_schema':original,
                'step_content':'async def run(ctx, inputs):\n    return ctx.result(data={"id": 1})\n'})
            recovery={}
            with client:
                wb=Workbench(DesktopController(app),reload_state=recovery)
                await wb.navigate('editor',task_id=task['task_id'],step_id=step['step_id'])
                self.assertIn('output_schema',wb.edit_controls)
                output=wb.edit_controls['output_schema']
                output.edit_mode.set_value('json')
                output.json_editor.set_value('{"type": unfinished 中文')
                wb.step_editor.sync_draft()
                with self.assertRaises(TaskError):wb.step_editor.document()
                wb.capture_reload_state()
            other=Client(page('/step-io-restored'))
            try:
                with other:
                    restored=Workbench(DesktopController(app),reload_state=recovery)
                    await restored.restore_route('editor',task['task_id'],step['step_id'])
                    await restored.paint()
                    output=restored.edit_controls['output_schema']
                    self.assertEqual(output.edit_mode.value,'json')
                    self.assertEqual(output.json_editor.value,'{"type": unfinished 中文')
                    with self.assertRaises(TaskError):await restored.step_editor.save()
                    self.assertEqual(app.repo.step(step['step_id'])['output_schema'],original)
                    self.assertEqual(app.repo.step(step['step_id'])['content_hash'],step['content_hash'])
            finally:other.delete()
        self.run_scenario(scenario)

    def test_configured_binding_fields_and_names_are_offered_without_manual_entry(self):
        from types import SimpleNamespace
        async def scenario(app, client):
            task = app.repo.create_task('binding choices', {'type': 'object', 'properties': {
                'count': {'type': 'integer'}, 'nested': {'type': 'object', 'properties': {
                    'a/b~c': {'type': 'boolean'}}}}})
            env = app.repo.save_environment('binding-env', {'base_url': 'https://example.test', 'limit': 3})
            step = app.repo.save_step(task['task_id'], {'name': 'bindings',
                'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n',
                'bindings': {'existing': {'ref': {'source': 'environment', 'pointer': '/base_url'}}}})
            with client:
                wb = Workbench(DesktopController(app))
                wb.environment_id = env['environment_id']
                await wb.navigate('editor', task_id=task['task_id'], step_id=step['step_id'])
                await wb.step_editor.view['open_debug']()
                row = wb.edit_controls['bindings'][0]
                self.assertIn('/limit', row[5].options)
                self.assertEqual(row[0].value, 'existing')
                row[0].value = ''
                row[5].value = '/limit'
                await row[5]._change_handlers[-1](SimpleNamespace(value='/limit'))
                self.assertEqual(row[0].value, 'limit')
                row[5].value = '/limit'
                self.assertEqual(wb.step_editor.document()['input_schema']['properties']['limit']['type'], 'integer')
                row[1].value = 'task'
                await row[1]._change_handlers[-1](None)
                self.assertIn('/count', row[5].options)
                self.assertIn('/nested/a~1b~0c', row[5].options)
                self.assertNotIn('/base_url', row[5].options)
                row[0].value = ''
                await row[5]._change_handlers[-1](SimpleNamespace(value='/nested/a~1b~0c'))
                self.assertEqual(row[0].value, 'a/b~c')
                row[0].value = 'custom'
                await row[5]._change_handlers[-1](SimpleNamespace(value='/count'))
                self.assertEqual(row[0].value, 'custom')
                row[1].value = 'environment'
                await row[1]._change_handlers[-1](None)
                environment = wb.step_editor.view['trial_environment']
                environment.value = ''
                # Drive the real environment handlers in order, as the UI does.
                import inspect
                for handler in environment._change_handlers:
                    result = handler(SimpleNamespace(value=''))
                    if inspect.isawaitable(result):
                        await result
                self.assertNotIn('/base_url', row[5].options)
                self.assertEqual(row[5].value, '/limit')
                self.assertEqual(row[0].value, 'custom')
                self.assertEqual(row[5].field_types, {'': 'object'})
        self.run_scenario(scenario)

    def test_previous_schema_fields_can_bind_before_any_successful_run(self):
        from types import SimpleNamespace
        async def scenario(app, client):
            task = app.repo.create_task('schema binding')
            producer = app.repo.save_step(task['task_id'], {'name': 'producer',
                'output_schema': {'type': 'object', 'properties': {
                    'contract_suffix': {'type': 'string'},
                    'duplicate_count': {'type': 'integer'},
                    'nested': {'type': 'object', 'properties': {'a/b': {'type': 'boolean'}}}}}})
            consumer = app.repo.save_step(task['task_id'], {'name': 'consumer',
                'bindings': {'count': {'ref': {'source': 'step', 'step_id': producer['step_id'],
                    'output': 'data', 'pointer': '/duplicate_count'}}}})
            with client:
                wb = Workbench(DesktopController(app))
                await wb.navigate('editor', task_id=task['task_id'], step_id=consumer['step_id'])
                row = wb.edit_controls['bindings'][0]
                self.assertIn('/contract_suffix', row[5].options)
                self.assertIn('/nested/a~1b', row[5].options)
                self.assertEqual(row[5].field_types['/duplicate_count'], 'integer')
                row[0].value = ''
                row[5].value = '/contract_suffix'
                await row[5]._change_handlers[-1](SimpleNamespace(value='/contract_suffix'))
                await wb.step_editor.save()
                saved = app.repo.step(consumer['step_id'])
                self.assertEqual(saved['bindings']['contract_suffix']['ref']['pointer'], '/contract_suffix')
                from unittest.mock import AsyncMock
                wb.controller.previous_result = AsyncMock(return_value={
                    'contract_suffix': 'C-123', 'duplicate_count': 'old-format', 'observed_only': True})
                row = wb.edit_controls['bindings'][0]
                await row[3]._change_handlers[-1](None)
                self.assertIn('/nested/a~1b', row[5].options)
                self.assertIn('/observed_only', row[5].options)
                self.assertIn('C-123', row[5].options['/contract_suffix'])
                self.assertEqual(row[5].field_types['/duplicate_count'], 'integer')
                # The output Schema describes data, never other result containers.
                wb.controller.previous_result = AsyncMock(side_effect=TaskError('OUTPUT_NOT_AVAILABLE'))
                row = wb.edit_controls['bindings'][0]
                row[4].value = 'artifacts'
                await row[4]._change_handlers[-1](None)
                self.assertNotIn('/duplicate_count', row[5].options)
        self.run_scenario(scenario)

    def run_scenario(self, scenario):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            client=Client(page('/step-io'))
            try:asyncio.run(scenario(app,client))
            finally:client.delete()
