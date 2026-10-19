import asyncio
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from taskweave.application.service import Application
from taskweave.desktop.controller import DesktopController
from taskweave.desktop.workbench import Workbench
from taskweave.desktop.components.step_debug import StepDebugSession
from taskweave.infrastructure.storage import uid


def input_draft(values=None, environment_id=None):
    from taskweave.presentation.debug import TrialInputDraft
    draft = TrialInputDraft()
    draft.task.configure({'properties': {key: {'type': 'integer' if isinstance(value, int) else 'string'} for key, value in (values or {}).items()}}, values or {})
    draft.step.configure({'properties': {}}, {})
    draft.set_environment(environment_id)
    return draft


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
            class Control:
                def __init__(self, value):
                    self._value, self.handlers = value, []
                def on_value_change(self, handler): self.handlers.append(handler)
                @property
                def value(self): return self._value
                @value.setter
                def value(self, value):
                    self._value = value
                    for handler in self.handlers: handler(SimpleNamespace(value=value))
            def build(schema, values):
                controls = {key: ('string', Control(values.get(key, spec.get('default')))) for key, spec in schema['properties'].items()}
                form=SimpleNamespace(schema=schema, controls=controls, defaults={key:control.value for key, (_,control) in controls.items()},
                    values=lambda:{key:control.value for key, (_,control) in controls.items() if control.value is not None})
                forms.append(form)
                return form
            step={'input_schema':{'properties':{'url':{'type':'string'},'code':{'type':'string'},'result':{'type':'integer','default':7}}},'bindings':{}}
            with patch('taskweave.desktop.components.trial_inputs.ui',fake_ui),patch('taskweave.desktop.components.trial_inputs.ValueForm',side_effect=build):
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
                    saved={'step_id':'step'}
                    trials={'step':'previous'}
                    form=SimpleNamespace(input_draft=input_draft({'code':'edited'}, 'uat'))
                    environment=SimpleNamespace(value='uat')
                    previous={'environment_id':previous_env,'status':'SUCCEEDED','can_end':can_end,'attempts':[]}
                    controller=SimpleNamespace(call=AsyncMock(return_value=previous), run_request=AsyncMock(return_value={}),
                        trial=AsyncMock(return_value={'run_id':'new'}), repeat_trial=AsyncMock(return_value={'run_id':'repeat'}))
                    confirm_end=AsyncMock(return_value=True); refresh=AsyncMock(); settle=AsyncMock(); update_env=Mock(); reset=AsyncMock()
                    session=StepDebugSession(controller=controller, identity=lambda:('task','step',1,1), task_id=lambda:'task',
                        save_editor=AsyncMock(return_value=saved), trial_form=lambda:form, trial_environment=lambda:environment,
                        environment_select=AsyncMock(), trial_variables=AsyncMock(), trials=trials, button=AsyncMock(),
                        confirm_end=confirm_end, resume_inputs=AsyncMock(), refresh_trial=refresh,
                        refresh_trial_inputs=AsyncMock(), update_environment=update_env, reset_feedback=reset,
                        trial_start_status=lambda:None, debug_state=form.input_draft.state)
                    session.settle_trial_start = settle
                    with patch('taskweave.desktop.components.step_debug.ui',MagicMock()) as fake_ui:
                        await session.start_trial(continue_session=True)
                        fake_ui.dialog.assert_not_called()
                    if previous_env=='uat' and can_end:
                        controller.repeat_trial.assert_awaited_once_with(saved,'previous',overrides={'code':'edited'})
                        controller.trial.assert_not_awaited()
                    else:
                        controller.trial.assert_awaited_once_with(saved,{'code':'edited'},'uat')
                        controller.repeat_trial.assert_not_awaited()
                    if previous_env!='uat' and can_end:
                        confirm_end.assert_awaited_once_with(previous)
                        self.assertEqual(controller.call.await_args.kwargs['operation'],'abandon')
                    if previous_env=='uat' and can_end:
                        update_env.assert_called_once_with('uat')
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
