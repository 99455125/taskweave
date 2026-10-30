"""Real local browser: formal launch, nested children, isolated debug, scoped deletion."""
import importlib.util
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

from taskweave.application.service import Application


@unittest.skipUnless(importlib.util.find_spec('playwright'), 'Playwright is not installed')
class UnifiedExecutionsBrowserTests(unittest.TestCase):
    def test_formal_and_debug_combinations_have_separate_records_and_controls(self):
        from playwright.sync_api import sync_playwright, expect
        with tempfile.TemporaryDirectory(prefix='taskweave-unified-browser-') as home:
            with Application(home) as app:
                task = app.tasks.create('Nested task')['task_id']
                step = app.steps.save(task, {'name': 'Return business result',
                    'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data={"checked": True})'})
                app.steps.confirm_manual(step['step_id'], step['content_hash'])
                app.tasks.confirm_flow(task, app.tasks.definition_hash(task))
                definition = app.sequences.save('Browser combination', [
                    {'node_id': key, 'task_id': task, 'environment_id': None,
                     'inputs': {}, 'step_inputs': {}} for key in ('first', 'second')], {})
            with socket.socket() as reservation:
                reservation.bind(('127.0.0.1', 0))
                port = reservation.getsockname()[1]
            log_path = Path(home) / 'browser.log'
            with log_path.open('w') as log:
                process = subprocess.Popen([sys.executable, '-m', 'taskweave', '--home', home,
                    'workbench', '--browser', '--port', str(port)], stdout=log, stderr=log)
                try:
                    url = None
                    deadline = time.monotonic() + 30
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
                            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                            page.set_default_timeout(10000)
                            errors = []
                            page.on('pageerror', lambda exc: errors.append(str(exc)))
                            page.goto(url)
                            page.get_by_role('button', name='新建执行', exact=True).first.click()
                            page.get_by_label('选择任务', exact=True).click()
                            page.get_by_role('option', name='任务组合 · Browser combination', exact=True).click()
                            page.get_by_role('button', name='执行整个组合', exact=True).click()
                            expect(page.locator('.tw-sequence-execution-detail').get_by_text('状态：成功', exact=True)).to_be_visible(timeout=20000)
                            expect(page.locator('.tw-run-card')).to_have_count(1)
                            expect(page.locator('.tw-sequence-run-row')).to_have_count(2)
                            page.locator('.tw-sequence-run-row').first.get_by_role('button', name='查看执行').click()
                            expect(page.get_by_role('dialog').get_by_text('Nested task', exact=True)).to_be_visible()
                            page.get_by_role('dialog').get_by_role('button', name='关闭', exact=True).click()
                            page.get_by_role('button', name='任务组合', exact=True).click()
                            page.get_by_role('button', name='Browser combination', exact=True).click()
                            expect(page.get_by_role('button', name='调试组合', exact=True)).to_be_visible()
                            expect(page.get_by_role('button', name='执行组合', exact=True)).to_have_count(0)
                            page.get_by_role('button', name='调试组合', exact=True).click()
                            page.get_by_role('button', name='开始调试', exact=True).click()
                            expect(page.locator('.tw-sequence-execution-detail').get_by_text('状态：成功', exact=True)).to_be_visible(timeout=20000)
                            with sqlite3.connect(Path(home) / 'taskweave.db') as db:
                                modes = [json.loads(row[0]).get('mode', 'EXECUTION') for row in db.execute('SELECT snapshot_json FROM sequence_runs')]
                                self.assertCountEqual(modes, ['EXECUTION', 'TRIAL'])
                                self.assertEqual(db.execute("SELECT count(*) FROM task_runs WHERE mode='EXECUTION'").fetchone()[0], 2)
                                self.assertEqual(db.execute("SELECT count(*) FROM task_runs WHERE mode='TRIAL'").fetchone()[0], 2)
                            page.get_by_role('button', name='执行', exact=True).click()
                            expect(page.locator('.tw-run-card')).to_have_count(1)
                            page.get_by_role('button', name='删除执行', exact=True).click()
                            page.get_by_role('button', name='确认删除执行', exact=True).click()
                            expect(page.locator('.tw-run-card')).to_have_count(0)
                            with sqlite3.connect(Path(home) / 'taskweave.db') as db:
                                self.assertEqual(db.execute('SELECT count(*) FROM task_sequences WHERE sequence_id=?', (definition['sequence_id'],)).fetchone()[0], 1)
                                self.assertEqual(db.execute("SELECT count(*) FROM task_runs WHERE mode='EXECUTION'").fetchone()[0], 0)
                                self.assertEqual(db.execute("SELECT count(*) FROM task_runs WHERE mode='TRIAL'").fetchone()[0], 2)
                            self.assertFalse(errors, errors)
                        finally:
                            browser.close()
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=10)
