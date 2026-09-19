import json
import tempfile
import unittest
from taskweave.application.service import Application
from taskweave.core.validation import TaskError
from taskweave.desktop.chat import parse_chat_reply

SOURCE = 'async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n'

class WebChatTests(unittest.TestCase):
    def test_paste_json_or_fenced_code(self):
        for reply in [SOURCE, '```python\n' + SOURCE + '```', json.dumps({'step_content': SOURCE, 'explanation': '说明'}), '```json\n'+json.dumps({'step_content': SOURCE})+'\n```']:
            self.assertEqual(parse_chat_reply(reply)[0], SOURCE)
        for reply in ['', '这里是建议', '{"step_content": 42}']:
            with self.assertRaises(TaskError):
                parse_chat_reply(reply)

    def test_chinese_context_uses_utf8_budget(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task('中文')['task_id']
            step = app.repo.save_step(task, {'step_content': SOURCE})
            result = app.dispatch('step.generate', {'step_id':step['step_id'], 'expected_hash':step['content_hash'], 'export_only':True, 'contexts':[{'kind':'text', 'content':'中文'*6000}]})
            self.assertIn('中文'*6000, result['prompt'])

    def test_oversized_history_keeps_latest_two_rounds(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            task = app.repo.create_task('history')['task_id']
            step = app.repo.save_step(task, {'step_content': SOURCE})
            history = []
            for index in range(5):
                history.extend([{'role':'user','content':'round-'+str(index)+' '+('x'*15000)}, {'role':'assistant','content':'reply-'+str(index)}])
            app.authoring.conversations[step['step_id']] = history
            result = app.dispatch('step.generate', {'step_id':step['step_id'], 'expected_hash':step['content_hash'], 'export_only':True, 'use_history':True})
            self.assertTrue(result['history_trimmed'])
            self.assertNotIn('round-2', result['prompt'])
            self.assertIn('round-3', result['prompt'])
            self.assertIn('round-4', result['prompt'])

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
            repaired = app.dispatch('step.generate', {**args, 'use_history':True, 'feedback':{'error_code':'BROWSER_TIMEOUT'}, 'supplement':'沿用页面'})
            self.assertIn('上一轮失败说明', repaired['prompt'])
            self.assertIn('沿用页面', repaired['prompt'])
            self.assertIn('BROWSER_TIMEOUT', repaired['prompt'])
            self.assertEqual(len(app.authoring.conversations[step['step_id']]), 1)
            self.assertEqual(app.repo.step(step['step_id'])['step_content'], SOURCE)
