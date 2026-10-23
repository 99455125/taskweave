"""Real workbench: external tool opens persisted evidence; human accepts."""
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest

from taskweave.application.service import Application
from taskweave.infrastructure.agent_connection import AgentClient


@unittest.skipUnless(importlib.util.find_spec('playwright'), 'optional browser dependency')
class AgentBrowserTests(unittest.TestCase):
    def test_external_open_evidence_and_human_acceptance(self):
        from playwright.sync_api import sync_playwright, expect
        with tempfile.TemporaryDirectory(prefix='taskweave-agent-browser-') as root:
            with Application(root) as app:
                task = app.tasks.create('通用示例总额验收')
                step = app.steps.save(task['task_id'], {'name': '计算总额',
                    'step_content': "async def run(ctx, inputs):\n    return ctx.result(data={'total': 42, 'items': 2})\n"})
                app.confirm_step_manual(step['step_id'], step['content_hash'])
                version = app.tasks.definition_hash(task['task_id'])
                spec = app.agent.review('prepare', {'target_kind': 'task', 'target_id': task['task_id'], 'expected_version': version,
                    'title': '核对通用示例总额为 42', 'checks': [{'id': 'total', 'label': '通用示例总额等于 42',
                    'source': {'step_id': step['step_id'], 'pointer': '/total'}, 'op': 'eq', 'expected': 42}]})
                run = app.agent.execute('task.run', {'task_id': task['task_id'], 'expected_hash': version}, 'browser-launch', spec['review_spec_id'])
                self.assertEqual(app.runs.wait(run['run_id'])['status'], 'SUCCEEDED')
            with socket.socket() as reservation:
                reservation.bind(('127.0.0.1', 0))
                port = reservation.getsockname()[1]
            log_path = Path(root) / 'browser.log'
            with log_path.open('w') as log:
                process = subprocess.Popen([sys.executable, '-m', 'taskweave', '--home', root, 'workbench', '--browser', '--port', str(port)], stdout=log, stderr=log)
                try:
                    url = None
                    deadline = time.monotonic() + 40
                    while time.monotonic() < deadline and not url:
                        for line in log_path.read_text().splitlines():
                            if line.startswith('{"url":'):
                                url = json.loads(line)['url']
                        if process.poll() is not None:
                            self.fail(log_path.read_text())
                        time.sleep(.1)
                    self.assertIsNotNone(url, log_path.read_text())
                    with sync_playwright() as playwright:
                        browser = playwright.chromium.launch(headless=True, channel='chromium')
                        try:
                            page = browser.new_page(viewport={'width': 1440, 'height': 1100})
                            page.set_default_timeout(12000)
                            errors = []
                            page.on('pageerror', lambda error: errors.append(str(error)))
                            page.goto(url)
                            expect(page.get_by_role('button', name='设置', exact=True)).to_be_visible()
                            client = AgentClient(root)
                            opened = client.call('agent.review', {'action': 'open', 'params': {'kind': 'run', 'identity': run['run_id']}})
                            self.assertTrue(opened['opened'])
                            expect(page.get_by_text('核对通用示例总额为 42', exact=True)).to_be_visible()
                            expect(page.get_by_text('自动核对：通过', exact=True)).to_be_visible()
                            page.get_by_role('button', name='查看原始结果', exact=True).click()
                            expect(page.get_by_text('计算总额 · 运行结果', exact=True)).to_be_visible()
                            expect(page.locator('code').filter(has_text='42').last).to_be_visible()
                            page.get_by_role('button', name='关闭', exact=True).last.click()
                            page.get_by_label('人工验收依据 / 未通过原因').fill('已核对原始结果和总额')
                            page.get_by_role('button', name='验收通过', exact=True).click()
                            expect(page.get_by_text('人工验收通过', exact=True)).to_be_visible()
                            report = client.call('agent.review', {'action': 'read', 'params': {'kind': 'run', 'identity': run['run_id']}})
                            self.assertEqual(report['human_status'], 'ACCEPTED')
                            self.assertFalse(errors, errors)
                            page.screenshot(path='/tmp/taskweave-ai-acceptance.png', full_page=True)
                        finally:
                            browser.close()
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=10)
