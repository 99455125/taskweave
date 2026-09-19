import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from taskweave.application.service import Application
from taskweave.core.validation import automatic_inputs
from taskweave.desktop.forms import SchemaEditor, ValueForm
from taskweave.infrastructure.storage import uid

class VariablesTests(unittest.TestCase):
    def test_local_environment_task_defaults_and_trials_without_bindings(self):
        before = dict(os.environ)
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            environment = app.repo.save_environment('本地', {'loginurl':'https://example.test/login', 'orgcode':'env-code', 'orgsecret':'test-local-secret'})['environment_id']
            task = app.repo.create_task('登录参数', {'type':'object','properties': {'orgcode':{'type':'string','default':'task-code'}, 'orgsecret':{'type':'string','default':'task-secret'}}})['task_id']
            source = '''async def run(ctx, inputs):
    assert inputs["loginurl"] == "https://example.test/login"
    assert inputs["orgcode"] == "task-code"
    assert inputs["orgsecret"] == "task-secret"
    return ctx.result(data={"parameters_ok": True})
'''
            step = app.repo.save_step(task, {'step_content':source})
            app.confirm_step_manual(step['step_id'],step['content_hash'],environment)
            formal = app.create_run(task, {}, environment)
            app.coordinator.start(formal['run_id'], uid())
            self.assertEqual(app.coordinator.wait(formal['run_id'])['status'], 'SUCCEEDED')
            app.coordinator.control(formal['run_id'], uid(), 'abandon')
            trial = app.trial_step(step['step_id'], {}, uid(), environment)
            self.assertEqual(app.coordinator.wait(trial['run_id'])['status'], 'SUCCEEDED')
            prompt = app.dispatch('step.generate', {'step_id':step['step_id'], 'expected_hash':step['content_hash'], 'environment_id':environment,'export_only':True})['prompt']
            self.assertIn('orgsecret', prompt)
            self.assertIn('available_variables', prompt)
        self.assertEqual(dict(os.environ), before)

    def test_declared_required_task_variable_can_come_from_environment(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            env = app.repo.save_environment('local', {'loginurl':'https://example.test'})['environment_id']
            task = app.repo.create_task('env task', {'type':'object','properties':{'loginurl':{'type':'string'}},'required':['loginurl'],'additionalProperties':False})['task_id']
            step = app.repo.save_step(task, {'step_content':'async def run(ctx, inputs):\n    return ctx.result(data={"url": inputs["loginurl"]})'})
            app.confirm_step_manual(step['step_id'],step['content_hash'],env)
            run = app.create_run(task, {}, env)
            self.assertEqual(json.loads(app.repo.run(run['run_id'])['inputs_json'])['loginurl'], 'https://example.test')

    def test_environment_change_updates_defaults_and_preserves_edits(self):
        form = object.__new__(ValueForm)
        form.schema = {'properties':{'url':{'type':'string'},'code':{'type':'string'}}}
        url, code = SimpleNamespace(value='old-url'), SimpleNamespace(value='edited-code')
        form.controls = {'url':('string',url),'code':('string',code)}
        form.defaults = {'url':'old-url','code':'old-code'}
        form.apply_defaults({'url':'new-url','code':'new-code'})
        self.assertEqual(url.value,'new-url')
        self.assertEqual(code.value,'edited-code')

    def test_input_precedence_and_closed_schema(self):
        schema={'type':'object','properties':{'x':{'type':'string'}},'additionalProperties':False}
        self.assertEqual(automatic_inputs(schema, {'x':'env','extra':1}, {'x':'task'}, {'x':'step'}), {'x':'step'})

    def test_empty_parameter_rows_do_not_block_saving(self):
        editor=object.__new__(SchemaEditor)
        editor.original={'type':'object','properties':{}}
        def row(name,default=''):
            return (SimpleNamespace(value=name),SimpleNamespace(value='string'),SimpleNamespace(value=default),SimpleNamespace(value=False),{'type':'string'})
        editor.rows=[row(''),row('loginurl','https://example.test')]
        self.assertEqual(list(editor.schema()['properties']), ['loginurl'])
