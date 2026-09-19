import asyncio
import json
import tempfile
import unittest
from taskweave.application.service import Application
from taskweave.core.validation import TaskError
from taskweave.desktop.controller import DesktopController
from taskweave.desktop.dependencies import result_fields
from taskweave.infrastructure.storage import uid


class RuntimeInputs(unittest.TestCase):
    def setup_task(self, app):
        task=app.repo.create_task('human inputs',{'type':'object','properties':{'org':{'type':'string'}},'required':['org']})['task_id']
        first=app.repo.save_step(task,{'name':'first','step_content':'async def run(ctx, inputs):\n    return ctx.result(data={"org": inputs["org"]})'})
        second=app.repo.save_step(task,{'name':'second','input_schema':{'type':'object','properties':{'number':{'type':'integer'}},'required':['number']},'step_content':'async def run(ctx, inputs):\n    return ctx.result(data={"number": inputs["number"], "org":inputs["org"]})'})
        for step in [first,second]:
            app.confirm_step_manual(step['step_id'],step['content_hash'])
        return task,first,second

    def test_missing_task_and_step_inputs_pause_before_actions_and_resume_same_run(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task,first,second=self.setup_task(app)
            with self.assertRaises(TaskError):
                app.create_run(task)  # Existing callers retain strict creation semantics.
            run=app.create_run(task,defer_inputs=True)
            app.coordinator.start(run['run_id'],uid(),mode='UNTIL',target_step_id=second['step_id'])
            paused=app.coordinator.wait(run['run_id'])
            self.assertEqual(paused['status'],'PAUSED')
            self.assertFalse(paused['attempts'])
            self.assertEqual(json.loads(paused['request_json'])['waiting_input']['scope'],'task')
            command=uid()
            app.dispatch('run.inputs',{'run_id':run['run_id'],'command_id':command,'inputs':{'org':'one'}})
            app.dispatch('run.inputs',{'run_id':run['run_id'],'command_id':command,'inputs':{'org':'one'}})
            app.coordinator.start(run['run_id'],uid(),mode='UNTIL',target_step_id=second['step_id'])
            paused=app.coordinator.wait(run['run_id'])
            self.assertEqual(paused['status'],'PAUSED')
            self.assertEqual(len(paused['attempts']),1)
            self.assertEqual(paused['attempts'][0]['step_id'],first['step_id'])
            self.assertEqual(json.loads(paused['request_json'])['waiting_input']['step_id'],second['step_id'])
            pid=app.coordinator.process.pid
            with self.assertRaises(TaskError):
                app.coordinator.provide_inputs(run['run_id'],uid(),{'number':'wrong'})
            app.coordinator.provide_inputs(run['run_id'],uid(),{'number':8})
            app.coordinator.start(run['run_id'],uid(),mode='UNTIL',target_step_id=second['step_id'])
            self.assertEqual(app.coordinator.wait(run['run_id'])['status'],'SUCCEEDED')
            self.assertEqual(app.coordinator.process.pid,pid)
            self.assertEqual(app.repo.read_output(run['run_id'],second['step_id']),{'number':8,'org':'one'})
            self.assertEqual(len(app.repo.run_details(run['run_id'])['attempts']),2)
            app.coordinator.restart(run['run_id'],uid(),second['step_id'],start_step_id=second['step_id'])
            partial=app.coordinator.wait(run['run_id'])
            self.assertEqual(partial['status'],'PAUSED')
            self.assertEqual(json.loads(partial['request_json'])['waiting_input']['step_id'],second['step_id'])
            self.assertEqual(len(partial['attempts']),1)
            app.coordinator.restart(run['run_id'],uid(),second['step_id'])
            restarted=app.coordinator.wait(run['run_id'])
            self.assertEqual(restarted['status'],'PAUSED')
            self.assertEqual(json.loads(restarted['request_json'])['waiting_input']['scope'],'step')
            self.assertNotIn('step_inputs',json.loads(restarted['request_json']))

    def test_bound_required_result_is_not_requested_as_manual_input(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task,first,second=self.setup_task(app)
            second=app.repo.save_step(task,{**second,
                'input_schema':{'type':'object','properties':{'number':{'type':'integer'},'id':{'type':'string'}},'required':['number','id']},
                'bindings':{'id':{'ref':{'source':'step','step_id':first['step_id'],'pointer':'/org'}}}},second['step_id'],second['content_hash'])
            app.confirm_step_manual(second['step_id'],second['content_hash'])
            run=app.create_run(task,{'org':'one'})
            app.coordinator.start(run['run_id'],uid())
            paused=app.coordinator.wait(run['run_id'])
            waiting=json.loads(paused['request_json'])['waiting_input']
            self.assertEqual(waiting['schema']['required'],['number'])
            self.assertNotIn('id',waiting['schema']['properties'])
            self.assertNotIn('id',waiting['values'])  # Bound result stays in the task DB.
            app.coordinator.provide_inputs(run['run_id'],uid(),{'number':4})
            app.coordinator.start(run['run_id'],uid())
            self.assertEqual(app.coordinator.wait(run['run_id'])['status'],'SUCCEEDED')

    def test_flow_trial_uses_task_inputs_and_only_current_step_override(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task,first,second=self.setup_task(app)
            command=uid()
            run=app.trial_flow(second['step_id'],{'org':'trial'},command,step_inputs={second['step_id']:{'number':5}})
            done=app.coordinator.wait(run['run_id'])
            self.assertEqual(done['status'],'SUCCEEDED',done)
            self.assertEqual(app.repo.read_output(run['run_id'],second['step_id']),{'number':5,'org':'trial'})
            repeated=app.trial_flow(second['step_id'],{'org':'trial'},command,step_inputs={second['step_id']:{'number':5}})
            self.assertEqual(repeated['run_id'],run['run_id'])

    def test_dependency_choices_use_actual_successful_result_and_escape_json_paths(self):
        fields=result_fields({'a/b':{'~key':'base64'},'items':[2]})
        self.assertIn('/a~1b/~0key',fields)
        self.assertEqual(fields['/items/0']['type'],'integer')
        self.assertEqual(len(result_fields(dict.fromkeys(range(200),'x'),limit=8)),8)
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task=app.repo.create_task('dependency')['task_id']
            first=app.repo.save_step(task,{'step_content':'async def run(ctx, inputs):\n    return ctx.result(data={"image_base64":"observed"})'})
            run=app.trial_step(first['step_id'],{},uid())
            app.coordinator.wait(run['run_id'])
            controller=DesktopController(app)
            self.assertEqual(asyncio.run(controller.previous_result(task,first['step_id'])),{'image_base64':'observed'})
            second=app.repo.save_step(task,{'input_schema':{'type':'object','properties':{'image_base64':{'type':'string'}},'required':['image_base64']},'bindings':{'image_base64':{'ref':{'source':'step','step_id':first['step_id'],'output':'data','pointer':'/image_base64'}}},'step_content':'async def run(ctx, inputs):\n    return ctx.result(data=inputs)'})
            current=asyncio.run(controller.trial(second,{}))
            self.assertEqual(app.coordinator.wait(current['run_id'])['status'],'SUCCEEDED')
            self.assertEqual(app.repo.read_output(current['run_id'],second['step_id'])['image_base64'],'observed')

    def test_partial_restart_preserves_prefix_and_clears_suffix(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task('rerun')['task_id']
            steps = [app.repo.save_step(task, {'name':str(i), 'step_content':f'async def run(ctx, inputs):\n    return ctx.result(data={{"value":{i}}})'}) for i in range(3)]
            env = app.repo.save_environment('other', {'x':'y'})['environment_id']
            for step in steps:
                app.confirm_step_manual(step['step_id'], step['content_hash'])
            run = app.create_run(task, environment_id=env)
            rid = run['run_id']
            app.coordinator.start(rid, uid())
            original = app.coordinator.wait(rid)
            prefix = original['attempts'][0]['attempt_id']
            worker_pid = app.coordinator.process.pid
            command = uid()
            app.coordinator.restart(rid, command, steps[1]['step_id'], start_step_id=steps[1]['step_id'])
            updated = app.coordinator.wait(rid)
            self.assertEqual(updated['attempts'][0]['attempt_id'], prefix)
            self.assertEqual(app.coordinator.process.pid, worker_pid)
            self.assertEqual(len(updated['attempts']), 2)
            self.assertEqual(app.repo.read_output(rid, steps[0]['step_id']), {'value':0})
            with self.assertRaises(TaskError):
                app.repo.read_output(rid, steps[2]['step_id'])
            app.coordinator.restart(rid, command, steps[1]['step_id'], start_step_id=steps[1]['step_id'])
            self.assertEqual(len(app.coordinator.wait(rid)['attempts']), 2)
            app.coordinator.control(rid, uid(), 'abandon')
            app.repo.save_environment('updated', {'x':'z'}, environment_id=env)
            self.assertTrue(all(s['validation_state']=='VALIDATED' for s in app.repo.steps(task)))

    def test_flow_repair_feedback_uses_this_failed_run(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task('flow feedback')['task_id']
            app.repo.save_step(task, {'name':'open', 'step_content':'async def run(ctx, inputs):\n    return ctx.result(data={"opened":True})'})
            second = app.repo.save_step(task, {'name':'fail', 'step_content':'async def run(ctx, inputs):\n    raise ValueError("THIS_FLOW_FAILURE")'})
            run = app.trial_flow(second['step_id'], {}, uid())
            failed = app.coordinator.wait(run['run_id'])
            self.assertEqual(failed['status'], 'FAILED')
            feedback = asyncio.run(DesktopController(app).trial_feedback(run['run_id'], second['step_id']))
            self.assertIn('THIS_FLOW_FAILURE', json.dumps(feedback))
            self.assertTrue(all(event['run_id']==run['run_id'] for event in feedback['trial_logs']))

    def test_delete_one_execution_preserves_task_and_other_results(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task=app.repo.create_task('delete run')['task_id']
            step=app.repo.save_step(task, {'step_content':'async def run(ctx, inputs):\n    return ctx.result(data={"value":1})'})
            app.confirm_step_manual(step['step_id'],step['content_hash'])
            runs=[]
            for _ in range(2):
                run=app.create_run(task)
                app.coordinator.start(run['run_id'], uid())
                app.coordinator.wait(run['run_id'])
                app.coordinator.control(run['run_id'],uid(),'abandon')
                runs.append(run['run_id'])
            app.dispatch('run.delete',{'run_id':runs[0]})
            self.assertFalse(app.repo.query('SELECT 1 FROM task_runs WHERE run_id=?',(runs[0],)))
            self.assertEqual(app.repo.read_output(runs[1],step['step_id']), {'value':1})
            self.assertEqual(app.repo.task(task)['name'], 'delete run')

    def test_pending_popup_reads_local_inputs_not_public_summary(self):
        from unittest.mock import MagicMock, patch
        from taskweave.desktop.workbench import Workbench
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task,first,second=self.setup_task(app)
            run=app.create_run(task,defer_inputs=True)
            app.coordinator.start(run['run_id'],uid())
            paused=app.coordinator.wait(run['run_id'])
            self.assertNotIn('inputs_json',paused)
            bench=object.__new__(Workbench)
            bench.task_id=task
            bench.controller=DesktopController(app)
            bench.button=MagicMock()
            fake=MagicMock()
            fake.dialog.return_value.is_deleted=False
            with patch('taskweave.desktop.workbench.ui',fake),patch('taskweave.desktop.forms.ui',fake):
                asyncio.run(bench.pending_inputs(paused))
                asyncio.run(bench.pending_inputs(paused))
                self.assertEqual(fake.dialog.call_count,1)
            titles=[call.args[0] for call in fake.expansion.call_args_list]
            self.assertEqual(titles,['环境变量 · 只读','任务变量 · 本次运行输入','步骤变量与依赖 · 本次步骤输入'])

    def test_combined_first_inputs_and_default_environment_persistence(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            controller=DesktopController(app)
            env=app.repo.save_environment('uat',{})['environment_id']
            asyncio.run(controller.set_default_environment(env))
            self.assertEqual(asyncio.run(DesktopController(app).default_environment()),env)
            task=app.repo.create_task('combined',{'type':'object','properties':{'org':{'type':'string'}},'required':['org']})['task_id']
            step=app.repo.save_step(task,{'input_schema':{'type':'object','properties':{'first':{'type':'integer'}},'required':['first']},'step_content':'async def run(ctx, inputs):\n    return ctx.result(data=inputs)'})
            app.confirm_step_manual(step['step_id'],step['content_hash'])
            run=app.create_run(task,defer_inputs=True)
            app.coordinator.start(run['run_id'],uid())
            waiting=app.coordinator.wait(run['run_id'])
            self.assertEqual(json.loads(waiting['request_json'])['waiting_input']['scope'],'task')
            app.coordinator.provide_inputs(run['run_id'],uid(),{'org':'one'},step_inputs={step['step_id']:{'first':7}})
            app.coordinator.start(run['run_id'],uid())
            done=app.coordinator.wait(run['run_id'])
            self.assertEqual(done['status'],'SUCCEEDED')
            self.assertEqual(app.repo.read_output(run['run_id'],step['step_id']), {'org':'one','first':7})
