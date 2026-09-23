import json
import tempfile
import unittest
from taskweave.application.service import Application
from taskweave.core.validation import TaskError
from taskweave.desktop.chat import parse_chat_reply, parse_goal_reply

SOURCE = 'async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n'

class WebChatTests(unittest.TestCase):
    def test_unicode_space_json_and_plain_description_reply(self):
        reply = r'{"step_content":"async def run(ctx, inputs):\n\u0020\u0020\u0020\u0020role = \"operator\"\n\u0020\u0020\u0020\u0020return ctx.result(data={\"role\": role}, outputs=[])","explanation":"ok"}'
        source, explanation = parse_chat_reply(reply)
        self.assertIn('\n    role = "operator"', source)
        self.assertEqual(explanation, 'ok')
        self.assertEqual(
            parse_goal_reply('{"step_description":"进入合约管理并创建合同。","step_notes":"不要重复打开页面"}'),
            ('进入合约管理并创建合同。', '不要重复打开页面'),
        )
        with self.assertRaises(TaskError):
            parse_goal_reply('进入合约管理并创建合同。')
    def test_paste_json_or_fenced_code(self):
        source_with_document_like_data = 'async def run(ctx, inputs):\n    return ctx.result(data={"step_content": "business value"})\n'
        for reply in [SOURCE, source_with_document_like_data, '```python\n' + SOURCE + '```', json.dumps({'step_content': SOURCE, 'explanation': '说明'}), '```json\n'+json.dumps({'step_content': SOURCE})+'\n```']:
            expected = source_with_document_like_data if reply == source_with_document_like_data else SOURCE
            self.assertEqual(parse_chat_reply(reply)[0], expected)
        surrounded = '以下是结果：\n' + json.dumps({'step_content': SOURCE, 'explanation': '已修订'}) + '\n\n你还可以继续优化定位器。'
        self.assertEqual(parse_chat_reply(surrounded), (SOURCE, '已修订'))
        malformed = '{"step_content":"async def run(ctx, inputs):\\n    role = "operator"\\n    return ctx.result(data={"role": role})\\n","explanation":"修复“确认”按钮"}'
        self.assertEqual(
            parse_chat_reply(malformed),
            ('async def run(ctx, inputs):\n    role = "operator"\n    return ctx.result(data={"role": role})\n', '修复“确认”按钮'),
        )
        for reply in ['', '这里是建议', '{"step_content": 42}', '{"step_content":"async def run(ctx, inputs)\\n    return None"}']:
            with self.assertRaises(TaskError):
                parse_chat_reply(reply)

    def test_chinese_context_uses_utf8_budget(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task('中文')['task_id']
            step = app.repo.save_step(task, {'step_content': SOURCE})
            result = app.dispatch('step.generate', {'step_id':step['step_id'], 'expected_hash':step['content_hash'], 'export_only':True, 'contexts':[{'kind':'text', 'content':'中文'*6000}]})
            self.assertIn('中文'*6000, result['prompt'])
            self.assertIn(r'\u0020', result['prompt'])
            self.assertIn(r'\"ok\"', result['prompt'])

    def test_oversized_history_keeps_latest_two_rounds(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task('history')['task_id']
            step = app.repo.save_step(task, {'step_content': SOURCE})
            history = []
            for index in range(5):
                history.extend([{'role':'user','content':'round-'+str(index)+' '+('x'*40000)}, {'role':'assistant','content':'reply-'+str(index)}])
            app.authoring.conversations[step['step_id']] = history
            result = app.dispatch('step.generate', {'step_id':step['step_id'], 'expected_hash':step['content_hash'], 'export_only':True, 'use_history':True, 'history_rounds':2})
            self.assertTrue(result['history_trimmed'])
            self.assertNotIn('round-2', result['prompt'])
            self.assertIn('round-3', result['prompt'])
            self.assertIn('round-4', result['prompt'])

    def test_selected_history_is_not_silently_dropped_when_it_does_not_fit(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task('history fallback')['task_id']
            step = app.repo.save_step(task, {'step_content': SOURCE})
            history = []
            for index in range(3):
                historical = {
                    'step_description': 'repeated goal', 'step_content': SOURCE,
                    'input_schema': {}, 'output_schema': {}, 'available_variables': [],
                    'repair_notes': 'round-' + str(index),
                    'contexts': [{'kind':'text', 'content':'x' * 300000}],
                }
                history.extend([
                    {'role':'user', 'content':json.dumps(historical)},
                    {'role':'assistant', 'content':'reply-' + str(index)},
                ])
            app.authoring.conversations[step['step_id']] = history
            with self.assertRaises(TaskError) as error:
                app.dispatch('step.generate', {'step_id':step['step_id'], 'expected_hash':step['content_hash'], 'export_only':True, 'use_history':True, 'history_rounds':2})
            self.assertEqual(error.exception.code, 'CONTEXT_TOO_LARGE')
            result = app.dispatch('step.generate', {'step_id':step['step_id'], 'expected_hash':step['content_hash'], 'export_only':True, 'use_history':True, 'history_rounds':0})
            self.assertNotIn('round-2', result['prompt'])
            self.assertNotIn('reply-2', result['prompt'])

    def test_history_static_field_deduplication_is_optional(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task('deduplicate')['task_id']
            step = app.repo.save_step(task, {'step_content': SOURCE})
            prior = {'step_description':'old goal', 'step_content':'old source', 'input_schema':{}, 'output_schema':{}, 'available_variables':[], 'repair_notes':'keep me'}
            app.authoring.conversations[step['step_id']] = [{'role':'user', 'content':json.dumps(prior)}, {'role':'assistant', 'content':'old reply'}]
            common = {'step_id':step['step_id'], 'expected_hash':step['content_hash'], 'export_only':True, 'use_history':True, 'history_rounds':1}
            compact = app.dispatch('step.generate', {**common, 'deduplicate_history':True})
            full = app.dispatch('step.generate', {**common, 'deduplicate_history':False})
            compact_history = json.loads(compact['messages'][2]['content'])
            full_history = json.loads(full['messages'][2]['content'])
            self.assertNotIn('step_content', compact_history)
            self.assertEqual(full_history['step_content'], 'old source')
            self.assertEqual(compact_history['repair_notes'], 'keep me')

    def test_full_current_context_above_old_limit_is_not_compacted(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task('large current context')['task_id']
            step = app.repo.save_step(task, {'step_content': SOURCE})
            snapshot = {
                'captured_at': 'now',
                'elements': [
                    {'tag': 'img', 'name': '验证码-' + str(index), 'selector': {'kind': 'css', 'value': '#captcha-' + str(index)}}
                    for index in range(600)
                ],
            }
            context = {'kind':'text', 'mime_type':'application/json', 'source':'playwright.page', 'content':json.dumps(snapshot, ensure_ascii=False)}
            result = app.dispatch('step.generate', {'step_id':step['step_id'], 'expected_hash':step['content_hash'], 'export_only':True, 'contexts':[context]})
            sent = json.loads(result['messages'][-1]['content'])
            received = json.loads(sent['contexts'][0]['content'])
            self.assertEqual(len(received['elements']), 600)
            self.assertEqual(received['elements'][-1]['selector']['value'], '#captcha-599')

    def test_no_key_export_with_plugin_channel_and_optional_history(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task('网页生成')['task_id']
            app.dispatch('plugin.configure', {'plugin_id':'playwright', 'enabled':True})
            capabilities = [key for key in app.registry.actions if key.startswith('playwright.')]
            self.assertTrue(capabilities)
            step = app.repo.save_step(task, {'name': '搜索', 'step_content': SOURCE, 'capabilities': capabilities})
            app.authoring.conversations[step['step_id']] = [{'role':'user', 'content':'上一轮失败说明'}]
            args = {'step_id':step['step_id'], 'expected_hash':step['content_hash'], 'export_only':True, 'contexts':[{'kind':'text','content':'最新页面快照'}]}
            result = app.dispatch('step.generate', args)
            self.assertIn('不能访问用户本机', result['prompt'])
            self.assertIn('最新页面快照', result['prompt'])
            self.assertNotIn('上一轮失败说明', result['prompt'])
            plugin = json.loads(result['messages'][1]['content'])['plugins'][0]
            self.assertEqual(plugin['tool_ids'], [])
            repaired = app.dispatch('step.generate', {**args, 'use_history':True, 'feedback':{'error_code':'BROWSER_TIMEOUT'}, 'repair_notes':'沿用页面'})
            self.assertIn('上一轮失败说明', repaired['prompt'])
            self.assertIn('沿用页面', repaired['prompt'])
            self.assertIn('BROWSER_TIMEOUT', repaired['prompt'])
            self.assertEqual(len(app.authoring.conversations[step['step_id']]), 1)
            self.assertEqual(app.repo.step(step['step_id'])['step_content'], SOURCE)
