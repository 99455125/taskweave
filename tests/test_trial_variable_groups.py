import asyncio
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from taskweave.application.service import Application
from taskweave.desktop.controller import DesktopController
from taskweave.desktop.workbench import Workbench
from taskweave.infrastructure.storage import uid


class TrialVariableGroups(unittest.TestCase):
    def test_environment_switch_renders_values_and_preserves_task_and_step_edits(self):
        async def scenario():
            schema = {'type': 'object', 'properties': {'code': {'type': 'string'}}}
            environments = [dict(environment_id=name, public_config_json=json.dumps({'url':name, 'code':name})) for name in ('uat','dev')]
            async def call(operation, **kwargs):
                return {'input_schema_json':json.dumps(schema)} if operation=='task.get' else environments
            bench=object.__new__(Workbench)
            bench.task_id='task'
            bench.controller=SimpleNamespace(call=AsyncMock(side_effect=call))
            environment=SimpleNamespace(value='uat')
            handlers=[]
            environment.on_value_change=handlers.append
            labels=[]
            forms=[]
            fake_ui=MagicMock()
            fake_ui.label.side_effect=lambda text: labels.append(text) or MagicMock()
            def build(schema, values):
                controls = {key: ('string', SimpleNamespace(value=values.get(key, spec.get('default')))) for key, spec in schema['properties'].items()}
                form=SimpleNamespace(controls=controls, defaults={key:control.value for key, (_,control) in controls.items()},
                    values=lambda:{key:control.value for key, (_,control) in controls.items() if control.value is not None})
                forms.append(form)
                return form
            step={'input_schema':{'properties':{'url':{'type':'string'},'code':{'type':'string'},'result':{'default':7}}},'bindings':{}}
            with patch('taskweave.desktop.workbench.ui',fake_ui),patch('taskweave.desktop.workbench.ValueForm',side_effect=build):
                form=await bench.trial_variables(step,environment)
                self.assertEqual(form.values(),{'code':'uat','url':'uat','result':7})
                labels.clear()
                await handlers[0](SimpleNamespace(value='dev'))
                self.assertEqual(form.values(),{'code':'dev','url':'dev','result':7})
                self.assertTrue(any('url = "dev"' in text and '环境' in text for text in labels))
                self.assertEqual(list(forms[-2].controls), ['code'])
                self.assertEqual(list(forms[-1].controls), ['url', 'code', 'result'])
                forms[-1].controls['code'][1].value='manual'
                await handlers[0](SimpleNamespace(value='uat'))
                self.assertEqual(form.values(),{'code':'manual','url':'uat','result':7})
        asyncio.run(scenario())

    def test_feedback_trial_routes_current_environment_and_inputs(self):
        async def scenario():
            for previous_env, can_end in [('uat', True), ('dev', True), ('uat', False)]:
                with self.subTest(previous_env=previous_env, can_end=can_end):
                    bench=object.__new__(Workbench)
                    saved={'step_id':'step'}
                    bench.save_editor=AsyncMock(return_value=saved)
                    bench.trials={'step':'previous'}
                    bench.trial_environment=SimpleNamespace(value='uat')
                    bench.trial_form=SimpleNamespace(values=lambda:{'code':'edited'})
                    bench.confirm_end=AsyncMock(return_value=True)
                    bench.refresh_trial=AsyncMock()
                    previous={'environment_id':previous_env,'status':'SUCCEEDED','can_end':can_end,'attempts':[]}
                    bench.controller=SimpleNamespace(call=AsyncMock(return_value=previous),
                        trial=AsyncMock(return_value={'run_id':'new'}),
                        repeat_trial=AsyncMock(return_value={'run_id':'repeat'}))
                    tabs=SimpleNamespace(value=None)
                    with patch('taskweave.desktop.workbench.ui',MagicMock()) as fake_ui:
                        await bench.start_trial(tabs,'feedback',continue_session=True)
                        fake_ui.dialog.assert_not_called()
                    if previous_env=='uat' and can_end:
                        bench.controller.repeat_trial.assert_awaited_once_with(saved,'previous',overrides={'code':'edited'})
                        bench.controller.trial.assert_not_awaited()
                    else:
                        bench.controller.trial.assert_awaited_once_with(saved,{'code':'edited'},'uat')
                        bench.controller.repeat_trial.assert_not_awaited()
                    if previous_env!='uat' and can_end:
                        bench.confirm_end.assert_awaited_once_with(previous)
                        self.assertEqual(bench.controller.call.await_args.kwargs['operation'],'abandon')
        asyncio.run(scenario())

    def test_repeated_trial_uses_edited_task_input(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task=app.repo.create_task('inputs',{'type':'object','properties':{'n':{'type':'number','default':1}}})['task_id']
            step=app.repo.save_step(task,{'input_schema':{'type':'object','properties':{'n':{'type':'number'}}},'step_content':'async def run(ctx, inputs):\n    return ctx.result(data={"n": inputs["n"]})'})
            run=app.trial_step(step['step_id'],{'n':1},uid())
            self.assertEqual(app.coordinator.wait(run['run_id'])['status'],'SUCCEEDED')
            repeated=asyncio.run(DesktopController(app).repeat_trial(step,run['run_id'],overrides={'n':9}))
            self.assertEqual(app.coordinator.wait(repeated['run_id'])['status'],'SUCCEEDED')
            self.assertEqual(app.repo.read_output(repeated['run_id'],step['step_id']),{'n':9})
