import asyncio
from io import BytesIO
import json
import logging
import tempfile
import unittest
from unittest.mock import patch

from taskweave.core.validation import TaskError
from taskweave.infrastructure.model import HttpModel
from taskweave.desktop.server_logs import ServerLogs


class ModelLogTests(unittest.TestCase):
    CODE_CONTRACT = {
        'type': 'object',
        'properties': {'step_content': {'type': 'string'}, 'explanation': {'type': 'string'}},
        'required': ['step_content'],
    }

    def reply(self, message, finish='stop', contract=None):
        raw=json.dumps({'choices':[{'message':message,'finish_reason':finish}]}).encode()
        model=HttpModel('https://api.deepseek.com/chat/completions','deepseek-flash','test-secret')
        with patch('taskweave.infrastructure.model.urlopen',side_effect=lambda *args, **kwargs: BytesIO(raw)) as request:
            result=asyncio.run(model.complete([],[],contract or self.CODE_CONTRACT))
            payload=json.loads(request.call_args.args[0].data)
            self.assertEqual(payload['thinking'], {'type':'disabled'})
            return result

    def test_nullable_tools_and_json_fence(self):
        result=self.reply({'tool_calls':None,'content':'```json\n'+json.dumps({'step_content':'async def run(ctx, inputs):\n    return ctx.result(data={})','explanation':'ok'})+'\n```'})
        self.assertIn('async def run',result.proposed_content)

    def test_invalid_and_truncated_output_never_success(self):
        for message,finish,code in [({'content':'   '},'stop','MODEL_CONTENT_EMPTY'),({'content':'{}'},'stop','MODEL_RESPONSE_CONTRACT_INVALID'),({'content':'{}'},'length','MODEL_OUTPUT_TRUNCATED')]:
            with self.assertRaises(TaskError) as error:
                self.reply(message,finish)
            self.assertEqual(error.exception.code,code)

    def test_server_log_cursor_redaction_and_file(self):
        with tempfile.TemporaryDirectory() as home:
            logs=ServerLogs(home)
            logs.protect('test-secret')
            logs.emit(logging.LogRecord('model',logging.INFO,'',0,'key test-secret',(),None))
            rows,cursor=logs.after()
            self.assertEqual(len(rows),1)
            self.assertNotIn('test-secret',rows[0][1])
            self.assertNotIn('test-secret',logs.path.read_text())
            self.assertEqual(logs.after(cursor)[0],[])
            logs.close()

    def test_malformed_model_json_repaired_once(self):
        model=HttpModel('https://api.deepseek.com/chat/completions','deepseek-flash')
        def envelope(content):
            return BytesIO(json.dumps({'choices':[{'message':{'content':content,'tool_calls':None}}]}).encode())
        with patch('taskweave.infrastructure.model.urlopen', side_effect=[envelope('{bad'), envelope(json.dumps({'step_content':'async def run(ctx, inputs):\n    return ctx.result(data={})'}))]) as request:
            result=asyncio.run(model.complete([],[],self.CODE_CONTRACT))
            self.assertTrue(result.proposed_content)
            self.assertEqual(request.call_count,2)
        with patch('taskweave.infrastructure.model.urlopen', side_effect=lambda *a, **k: envelope('{bad')) as request:
            with self.assertRaises(TaskError) as error:
                asyncio.run(model.complete([],[],self.CODE_CONTRACT))
            self.assertEqual(error.exception.code,'MODEL_JSON_INVALID')
            self.assertEqual(request.call_count,2)

    def test_response_contract_supports_description_fields_and_drives_repair(self):
        model=HttpModel('https://api.deepseek.com/chat/completions','deepseek-flash')
        contract={
            'type':'object',
            'properties':{
                'step_description':{'type':'string'},
                'step_notes':{'type':'string'},
            },
            'required':['step_description','step_notes'],
            'additionalProperties':False,
        }
        def envelope(content):
            return BytesIO(json.dumps({'choices':[{'message':{'content':content,'tool_calls':None}}]}).encode())
        valid=json.dumps({'step_description':'填写账号密码并保存截图','step_notes':'不点击登录'})
        with patch('taskweave.infrastructure.model.urlopen', side_effect=[envelope('{}'),envelope(valid)]) as request:
            reply=asyncio.run(model.complete([],[],contract))
        self.assertEqual(reply.structured_content['step_description'],'填写账号密码并保存截图')
        self.assertIsNone(reply.proposed_content)
        repair_payload=json.loads(request.call_args_list[1].args[0].data)
        repair_text=repair_payload['messages'][-1]['content']
        self.assertEqual(repair_payload['messages'][-2], {'role': 'assistant', 'content': '{}'})
        self.assertIn('step_description',repair_text)
        self.assertIn('step_notes',repair_text)
        self.assertNotIn('async def run',repair_text)

    def test_description_generation_returns_two_fields_without_code_guidance(self):
        from taskweave.application.service import Application
        from taskweave.core.ports import ModelReply
        class Model:
            messages = None
            contract = None
            def capabilities(self): return {'images': False}
            async def complete(self, messages, specs, contract):
                self.messages, self.contract = messages, contract
                return ModelReply(structured_content={
                    'step_description':'填写账号密码并保存截图',
                    'step_notes':'不填写验证码，不点击登录',
                })
        with tempfile.TemporaryDirectory() as home:
            model=Model()
            with Application(home, model) as app:
                app.dispatch('plugin.configure', {'plugin_id':'playwright','enabled':True})
                environment=app.repo.save_environment(
                    'uat', {'login_url':'https://example.test'},
                    {'org_secret':'env:ORG_SECRET'},
                    descriptions={'login_url':'登录地址','org_secret':'登录密码'},
                )['environment_id']
                task=app.repo.create_task('登录', {'type':'object','properties':{
                    'org_code':{'type':'string','description':'机构代码'},
                }})['task_id']
                capabilities=[key for key in app.registry.actions if key.startswith('playwright.')]
                step=app.repo.save_step(task, {'step_description':'填写登录信息','step_notes':'保留页面','capabilities':capabilities,'step_content':'async def run(ctx, inputs):\n    return ctx.result()'})
                result=asyncio.run(app.authoring.generate_goal(
                    step['step_id'], step['content_hash'], contexts=[{'kind':'text','content':'登录页'}], environment_id=environment,
                ))
        self.assertEqual(result['step_description'],'填写账号密码并保存截图')
        self.assertEqual(result['step_notes'],'不填写验证码，不点击登录')
        self.assertEqual(model.contract['required'],['step_description','step_notes'])
        prompt=json.dumps(model.messages,ensure_ascii=False)
        self.assertIn('login_url',prompt)
        self.assertIn('org_secret',prompt)
        self.assertIn('org_code',prompt)
        request=json.loads(model.messages[-1]['content'])
        self.assertEqual(request['step_description'],'填写登录信息')
        self.assertEqual(request['step_notes'],'保留页面')
        self.assertNotIn('examples',json.dumps(request['plugin_guidance']))
        self.assertNotIn('async def run',json.dumps(request['plugin_guidance']))

    def test_ai_variable_catalog_contains_one_effective_definition_per_name(self):
        from taskweave.application.service import Application
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            environment = app.repo.save_environment(
                'uat', {'shared': 'environment', 'env_only': 'value'},
                descriptions={'shared': '环境说明'},
            )['environment_id']
            task = app.repo.create_task('变量覆盖', {
                'type': 'object',
                'properties': {
                    'shared': {'type': 'string', 'description': '任务说明'},
                    'task_only': {'type': 'string', 'description': '任务变量'},
                },
            })['task_id']
            step = app.repo.save_step(task, {
                'step_description': '读取变量',
                'input_schema': {
                    'type': 'object',
                    'properties': {'shared': {'type': 'string', 'description': '步骤说明'}},
                    'required': ['shared'],
                },
                'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data=inputs["shared"])',
            })
            catalog = app.authoring._variable_catalog(app.repo.step(step['step_id']), environment)
            exported = asyncio.run(app.authoring.generate(
                step['step_id'], step['content_hash'], environment_id=environment,
                export_only=True,
            ))
        self.assertEqual({item['name'] for item in catalog}, {'shared', 'env_only', 'task_only'})
        self.assertEqual(len(catalog), 3)
        self.assertEqual(next(item for item in catalog if item['name'] == 'shared')['schema']['description'], '步骤说明')
        self.assertTrue(next(item for item in catalog if item['name'] == 'shared')['required'])
        self.assertTrue(all('source' not in item for item in catalog))
        self.assertEqual(json.loads(exported['messages'][-1]['content'])['available_variables'], catalog)
        self.assertNotIn('priority', exported['messages'][0]['content'].lower())

    def test_variable_catalog_preserves_schema_constraints_without_defaults(self):
        from taskweave.application.service import Application
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task('约束', {
                'type': 'object',
                'properties': {
                    'kind': {
                        'type': 'string', 'enum': ['A', 'B'], 'format': 'code',
                        'description': '业务类别', 'default': 'A',
                    },
                },
                'required': ['kind'],
                'additionalProperties': False,
            })['task_id']
            step = app.repo.save_step(task, {'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data=inputs)'})
            item = app.authoring._variable_catalog(app.repo.step(step['step_id']), None)[0]
        self.assertEqual(item['name'], 'kind')
        self.assertEqual(item['schema']['enum'], ['A', 'B'])
        self.assertEqual(item['schema']['format'], 'code')
        self.assertNotIn('default', item['schema'])
        self.assertTrue(item['required'])

    def test_repair_payload_uses_three_unambiguous_fields(self):
        from taskweave.application.service import Application
        from taskweave.core.ports import ModelReply
        source='async def run(ctx, inputs):\n    return ctx.result()'
        class Model:
            messages = None
            def capabilities(self): return {'images':False}
            async def complete(self,messages,specs,contract):
                self.messages=json.loads(json.dumps(messages))
                return ModelReply(source,'fixed')
        with tempfile.TemporaryDirectory() as home:
            model=Model()
            with Application(home,model) as app:
                task=app.repo.create_task('repair')['task_id']
                step=app.repo.save_step(task,{'step_description':'提交并验证','step_notes':'不要重新打开页面','step_content':source})
                asyncio.run(app.authoring.generate(
                    step['step_id'],step['content_hash'],feedback={'error_code':'FAILED'},repair_notes='使用当前标签页',
                ))
        request=json.loads(model.messages[-1]['content'])
        self.assertEqual(request['step_description'],'提交并验证')
        self.assertEqual(request['step_notes'],'不要重新打开页面')
        self.assertEqual(request['repair_notes'],'使用当前标签页')
        self.assertNotIn('goal',request)
        self.assertNotIn('ai_authoring_notes',request)
        self.assertNotIn('user_supplement',request)

    def test_non_json_http_response_not_retried_as_model_content(self):
        model=HttpModel('https://api.deepseek.com/chat/completions','deepseek-flash')
        with patch('taskweave.infrastructure.model.urlopen', side_effect=lambda *a, **k: BytesIO(b'<html>proxy error</html>')) as request:
            with self.assertRaises(TaskError) as error:
                asyncio.run(model.complete([],[],{}))
            self.assertEqual(error.exception.code,'MODEL_ENVELOPE_INVALID')
            self.assertEqual(request.call_count,1)

    def test_authoring_corrects_unknown_action_without_executing(self):
        from taskweave.application.service import Application
        from taskweave.core.ports import ModelReply
        class Model:
            calls = 0
            def capabilities(self): return {}
            async def complete(self, messages, specs, contract):
                self.calls += 1
                action = 'demo.nonexistent' if self.calls == 1 else 'demo.echo'
                return ModelReply('async def run(ctx, inputs):\n    return ctx.result(data=await ctx.call("'+action+'", inputs))')
        with tempfile.TemporaryDirectory() as home:
            model=Model()
            with Application(home,model,registry_factory='taskweave.plugins.demo:build_registry') as app:
                task=app.repo.create_task('test')['task_id']
                step=app.repo.save_step(task,{'name':'test','capabilities':['demo.echo'],'step_content':'async def run(ctx, inputs):\n    return ctx.result(data=inputs)'})
                result=asyncio.run(app.authoring.generate(step['step_id'],step['content_hash']))
                self.assertEqual(model.calls,2)
                self.assertIn('demo.echo',result['proposed_content'])
                self.assertNotIn('demo.echo',app.repo.step(step['step_id'])['step_content'])

    def test_ai_conversation_logged_without_auth_header(self):
        model=HttpModel('https://api.deepseek.com/chat/completions','deepseek-flash','test-header-key')
        raw=json.dumps({'choices':[{'message':{'content':json.dumps({'step_content':'async def run(ctx, inputs):\n    return ctx.result(data={})'}),'tool_calls':None}}]}).encode()
        with self.assertLogs('taskweave.infrastructure.model',level='INFO') as logs:
            with patch('taskweave.infrastructure.model.urlopen',side_effect=lambda *a, **k: BytesIO(raw)):
                asyncio.run(model.complete([{'role':'user','content':'fix current step using trial logs'}],[],{}))
        text='\n'.join(logs.output)
        self.assertIn('fix current step using trial logs',text)
        self.assertIn('AI 对话回复',text)
        self.assertNotIn('test-header-key',text)

    def test_keyword_action_permissions_and_step_conversation_reset(self):
        from taskweave.application.service import Application
        from taskweave.core.ports import ModelReply
        from taskweave.core.validation import content_tree
        from taskweave.infrastructure.storage import uid
        source='async def run(ctx, inputs):\n    return ctx.result(data=inputs)'
        with self.assertRaises(TaskError) as error:
            content_tree('async def run(ctx, inputs):\n    return ctx.result(data=await ctx.call(action_id="browser.click", inputs={}))', ['playwright.page_click'])
        self.assertEqual(error.exception.code,'CAPABILITY_DENIED')
        content_tree('async def run(ctx, inputs):\n    return ctx.result(data=await ctx.call(action_id="demo.echo", inputs={}))',['demo.echo'])
        class Model:
            def __init__(self): self.requests=[]
            def capabilities(self): return {}
            async def complete(self,messages,specs,contract):
                self.requests.append(json.loads(json.dumps(messages)))
                return ModelReply(source,'previous repair suggestion')
        with tempfile.TemporaryDirectory() as home:
            model=Model()
            with Application(home,model) as app:
                task=app.repo.create_task('test')['task_id']
                one=app.repo.save_step(task,{'name':'one','step_content':source})
                two=app.repo.save_step(task,{'name':'two','step_content':source})
                asyncio.run(app.authoring.generate(one['step_id'],one['content_hash'],repair_notes='continue on existing page',use_history=True))
                asyncio.run(app.authoring.generate(one['step_id'],one['content_hash'],repair_notes='second repair',use_history=True))
                self.assertIn('continue on existing page',json.dumps(model.requests[-1]))
                self.assertIn('previous repair suggestion',json.dumps(model.requests[-1]))
                asyncio.run(app.authoring.generate(two['step_id'],two['content_hash']))
                self.assertNotIn('continue on existing page',json.dumps(model.requests[-1]))
                asyncio.run(app.authoring.generate(one['step_id'],one['content_hash']))
                self.assertNotIn('second repair',json.dumps(model.requests[-1]))
                continued=app.trial_step(one['step_id'],{},uid(),continue_session=True)
                app.coordinator.wait(continued['run_id'])
                asyncio.run(app.authoring.generate(one['step_id'],one['content_hash'],use_history=True,repair_notes='third repair'))
                self.assertIn('second repair',json.dumps(model.requests[-1]))
                self.assertIn('continue on existing page',json.dumps(model.requests[-1]))
                run=app.trial_step(one['step_id'],{},uid())
                app.coordinator.wait(run['run_id'])
                self.assertNotIn(one['step_id'],app.authoring.conversations)
                asyncio.run(app.authoring.generate(one['step_id'],one['content_hash']))
                self.assertNotIn('second repair',json.dumps(model.requests[-1]))

    def test_repair_history_keeps_contexts_without_repeating_static_step_fields(self):
        from taskweave.application.service import Application
        from taskweave.core.ports import ModelReply
        source = 'async def run(ctx, inputs):\n    return ctx.result()'
        class Model:
            requests = []
            def capabilities(self): return {}
            async def complete(model, messages, specs, contract):
                model.requests.append(json.loads(json.dumps(messages)))
                return ModelReply(source, 'repair')
        with tempfile.TemporaryDirectory() as home:
            model = Model()
            with Application(home, model) as app:
                task = app.repo.create_task('history')['task_id']
                step = app.repo.save_step(task, {'step_content': source})
                for index in range(4):
                    context = {'kind': 'text', 'mime_type': 'application/json', 'source': 'plugin.page', 'content': json.dumps({'captured_at': str(index), 'elements': [{'label': 'x'*16000}]})}
                    asyncio.run(app.authoring.generate(step['step_id'], step['content_hash'], contexts=[context], use_history=True, repair_notes='round '+str(index)))
                sent = [json.loads(m['content']) for m in model.requests[-1] if m['role'] == 'user']
                self.assertEqual(len(sent), 4)
                self.assertEqual([d['repair_notes'] for d in sent], ['round '+str(i) for i in range(4)])
                self.assertIn('elements', json.loads(sent[-1]['contexts'][0]['content']))
                self.assertIn('elements', json.loads(sent[0]['contexts'][0]['content']))
                self.assertNotIn('step_content', sent[0])
                self.assertIn('step_content', sent[-1])
                stored = [json.loads(m['content']) for m in app.authoring.conversations[step['step_id']] if m['role'] == 'user']
                self.assertIn('elements', json.loads(stored[0]['contexts'][0]['content']))

    def test_trial_executes_latest_saved_draft(self):
        from taskweave.application.service import Application
        from taskweave.desktop.controller import DesktopController
        with tempfile.TemporaryDirectory() as home:
            with Application(home) as app:
                controller=DesktopController(app)
                task=app.repo.create_task('test')['task_id']
                old=app.repo.save_step(task, {'name':'step','step_content':'async def run(ctx, inputs):\n    return ctx.result(data={"value": 1})'})
                first=asyncio.run(controller.trial(old,{}))
                app.coordinator.wait(first['run_id'])
                latest=asyncio.run(controller.save_draft(task,{**old,'step_content':'async def run(ctx, inputs):\n    return ctx.result(data={"value": 2})'},old))
                second=asyncio.run(controller.repeat_trial(latest,first["run_id"]))
                app.coordinator.wait(second['run_id'])
                self.assertEqual(app.repo.read_output(second['run_id'],latest['step_id'],'data',app.registry), {'value':2})
                self.assertEqual(app.repo.read_output(first['run_id'],old['step_id'],'data',app.registry), {'value':1})
