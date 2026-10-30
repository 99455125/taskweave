"""Real browser edits a conditional combination and executes its saved flow."""

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


class SequenceCanvasBrowserTests(unittest.TestCase):
    def test_parallel_toggle_save_and_run_from_canvas(self):
        from playwright.sync_api import sync_playwright, expect
        with tempfile.TemporaryDirectory(prefix='taskweave-flow-browser-') as temporary:
            with Application(temporary) as app:
                nodes = []
                for name in ('First branch', 'Second branch'):
                    task = app.repo.create_task(name)
                    step = app.repo.save_step(task['task_id'], {
                        'name': 'Return', 'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data={"done": True})\n'})
                    app.confirm_step_manual(step['step_id'], step['content_hash'])
                    nodes.append({'node_id': name, 'task_id': task['task_id'], 'environment_id': None, 'inputs': {}, 'step_inputs': {}})
                body = lambda name, children: {'id': name, 'kind': 'sequence', 'children': children}
                group = {'id': 'choose', 'kind': 'if', 'parallel': False,
                         'cases': [{'id': str(index), 'condition': {'op': 'eq', 'left': {'literal': True}, 'right': {'literal': True}},
                                    'body': body('body-' + str(index), [{'id': node['node_id'], 'kind': 'action', 'step_id': node['node_id']}])}
                                   for index, node in enumerate(nodes)],
                         'default': {'id': 'fallback', 'body': body('fallback-body', [])}}
                app.sequences.save('Browser flow', nodes, {'type': 'object'}, flow={'version': 2, 'root': body('root', [group])})
            with socket.socket() as reservation:
                reservation.bind(('127.0.0.1', 0))
                port = reservation.getsockname()[1]
            log_path = Path(temporary) / 'browser.log'
            with log_path.open('w') as log:
                process = subprocess.Popen([sys.executable, '-m', 'taskweave', '--home', temporary,
                    'workbench', '--browser', '--port', str(port)], stdout=log, stderr=log)
                try:
                    url = None
                    deadline = time.monotonic() + 30
                    while time.monotonic() < deadline and url is None:
                        for line in log_path.read_text().splitlines():
                            if line.startswith('{"url":'):
                                url = json.loads(line)['url']
                        if process.poll() is not None:
                            self.fail(log_path.read_text())
                        time.sleep(.1)
                    self.assertIsNotNone(url, log_path.read_text())
                    with sync_playwright() as playwright:
                        browser = playwright.chromium.launch(headless=True)
                        try:
                            page = browser.new_page(viewport={'width': 1440, 'height': 1100})
                            page.set_default_timeout(12000)
                            errors = []
                            page.on('pageerror', lambda error: errors.append(str(error)))
                            page.goto(url)
                            page.get_by_role('button', name='任务组合', exact=True).click()
                            page.get_by_role('button', name='Browser flow', exact=True).click()
                            page.get_by_role('button', name='配置条件分支', exact=True).click()
                            page.get_by_role('checkbox', name='允许并行', exact=True).click()
                            expect(page.get_by_role('checkbox', name='允许并行', exact=True)).to_be_checked()
                            page.get_by_role('button', name='保存组合', exact=True).click()
                            expect(page.get_by_text('组合已保存', exact=True)).to_be_visible()
                            page.get_by_role('button', name='执行组合', exact=True).click()
                            page.get_by_role('button', name='执行整个组合', exact=True).click()
                            expect(page.get_by_text('状态：成功', exact=True)).to_be_visible(timeout=20000)
                            with sqlite3.connect(Path(temporary) / 'taskweave.db') as db:
                                saved_flow = json.loads(db.execute('SELECT flow_json FROM task_sequences').fetchone()[0])
                                children = db.execute("SELECT run_id,status FROM sequence_instances WHERE kind='action'").fetchall()
                            self.assertTrue(saved_flow['root']['children'][0]['parallel'])
                            self.assertEqual(len(children), 2)
                            self.assertEqual([status for _, status in children], ['SUCCEEDED', 'SUCCEEDED'])
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

    def test_empty_canvases_selection_view_state_and_narrow_window(self):
        from playwright.sync_api import sync_playwright, expect
        from urllib.request import urlopen
        server = '''
import sys
from nicegui import ui
from taskweave.application.service import Application
from taskweave.desktop.controller import DesktopController
from taskweave.desktop.workbench import Workbench
app = Application(sys.argv[1])
task = app.repo.create_task('Empty canvas')
library = app.repo.create_task('Library task')
library_step = app.steps.save(library['task_id'], {'name': 'Library step', 'step_content': 'async def run(ctx, inputs):\\n    return ctx.result(data=inputs)\\n'})
app.confirm_step_manual(library_step['step_id'], library_step['content_hash'])
@ui.page('/steps')
async def steps():
    wb = Workbench(DesktopController(app))
    wb.tasks_page.workspace_tab = 'steps'
    await wb.navigate('editor', task_id=task['task_id'])
@ui.page('/sequence')
async def sequence():
    wb = Workbench(DesktopController(app))
    await wb.navigate('sequences')
ui.run(host='127.0.0.1', port=int(sys.argv[2]), show=False, reload=False)
'''
        screenshots = Path('/tmp/taskweave-canvas-unification-20261029-screenshots')
        screenshots.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='taskweave-unified-browser-') as home:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            log_path = Path(home) / 'server.log'
            with log_path.open('w') as output:
                process = subprocess.Popen([sys.executable, '-c', server, home, str(port)], stdout=output, stderr=output)
                try:
                    url = f'http://127.0.0.1:{port}'
                    deadline = time.monotonic() + 30
                    while True:
                        try:
                            with urlopen(url + '/steps', timeout=1):
                                break
                        except OSError:
                            if process.poll() is not None or time.monotonic() > deadline:
                                self.fail(log_path.read_text()[-4000:])
                            time.sleep(.1)
                    with sync_playwright() as p:
                        browser = p.chromium.launch(headless=True)
                        try:
                            page = browser.new_page(viewport={'width': 1440, 'height': 1100})
                            page.set_default_timeout(10000)
                            errors = []
                            page.on('pageerror', lambda e: errors.append(str(e)))
                            def add_menu(label):
                                page.get_by_role('button', name='添加节点', exact=True).click()
                                page.locator('.q-menu:visible').get_by_text(label, exact=True).click()
                            def zoom(value):
                                page.get_by_label('流程缩放', exact=True).click()
                                page.get_by_role('option', name=value, exact=True).click()
                            def no_overflow():
                                self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), page.viewport_size['width'])
                            page.goto(url + '/steps')
                            expect(page.locator('.tw-flow-node')).to_have_count(0)
                            expect(page.locator('.tw-flow-empty')).to_be_visible()
                            add_menu('列表遍历')
                            expect(page.get_by_label('最多项数', exact=True)).to_be_visible()
                            expect(page.locator('.tw-flow-block-heading.is-selected')).to_have_count(1)
                            page.get_by_label('最多项数', exact=True).fill('12')
                            add_menu('步骤')
                            expect(page.get_by_text('流程配置有未保存的更改', exact=True)).to_be_visible()
                            page.get_by_role('button', name='继续编辑', exact=True).click()
                            expect(page.locator('.tw-flow-node')).to_have_count(0)
                            page.locator('.tw-flow-empty').click()
                            page.get_by_role('button', name='保存并切换', exact=True).click()
                            page.get_by_role('dialog').get_by_role('button', name='步骤', exact=True).click()
                            expect(page.locator('.tw-flow-node.is-selected')).to_have_count(1)
                            expect(page.locator('.tw-flow-block')).to_contain_text('新步骤')
                            expect(page.get_by_text('1 个步骤 · 1 个控制节点', exact=True)).to_be_visible()
                            page.get_by_role('button', name='配置列表遍历', exact=True).click()
                            add_menu('从已有步骤复制')
                            page.get_by_role('dialog').get_by_role('button', name='确认复用', exact=True).click()
                            expect(page.locator('.tw-flow-node')).to_have_count(2)
                            expect(page.locator('.tw-flow-node.is-selected')).to_have_count(1)
                            expect(page.get_by_role('button', name='保存步骤', exact=True)).to_be_visible()
                            zoom('125%')
                            page.get_by_role('button', name='展开或收起流程', exact=True).click()
                            add_menu('条件循环')
                            expect(page.locator('.tw-flow-canvas')).to_be_hidden()
                            page.get_by_role('button', name='展开或收起流程', exact=True).click()
                            self.assertEqual(page.locator('.tw-flow-root').evaluate('e => e.style.zoom'), '1.25')
                            page.screenshot(path=str(screenshots / 'steps-desktop.png'), full_page=True)
                            page.set_viewport_size({'width': 620, 'height': 1000})
                            no_overflow()
                            add_menu('条件分支')
                            expect(page.get_by_role('checkbox', name='允许并行', exact=True)).to_be_visible()
                            no_overflow()
                            page.screenshot(path=str(screenshots / 'steps-narrow.png'), full_page=True)
                            page.goto(url + '/sequence')
                            expect(page.locator('.tw-flow-node')).to_have_count(0)
                            add_menu('列表遍历')
                            page.get_by_label('最多项数', exact=True).fill('8')
                            add_menu('任务')
                            page.get_by_label('选择任务', exact=True).click()
                            page.get_by_role('option', name='Library task', exact=True).click()
                            page.get_by_role('button', name='添加到末尾', exact=True).click()
                            expect(page.get_by_role('tab', name='任务配置', exact=True)).to_be_visible()
                            expect(page.locator('.tw-flow-node.is-selected')).to_have_count(1)
                            add_menu('任务')
                            page.get_by_label('选择任务', exact=True).click()
                            page.get_by_role('option', name='Library task', exact=True).click()
                            page.get_by_role('button', name='添加到末尾', exact=True).click()
                            expect(page.locator('.tw-flow-node')).to_have_count(2)
                            first = page.locator('.tw-flow-node').first
                            identity = first.get_attribute('data-node-id')
                            body_gap = page.locator('.tw-flow-foreach .tw-flow-insert').first
                            first.drag_to(body_gap)
                            expect(page.locator('.tw-flow-node.is-selected')).to_have_attribute('data-node-id', identity)
                            expect(page.locator('.tw-flow-location')).to_contain_text('列表遍历')
                            expect(page.get_by_text('2 个任务 · 1 个控制节点', exact=True)).to_be_visible()
                            page.locator('.tw-flow-node').last.get_by_role('button', name='节点操作').click()
                            page.locator('.q-menu:visible').get_by_text('在前面插入', exact=True).click()
                            page.get_by_role('dialog').get_by_role('button', name='任务', exact=True).click()
                            page.get_by_label('选择任务', exact=True).click()
                            page.get_by_role('option', name='Library task', exact=True).click()
                            page.get_by_role('button', name='添加到此处', exact=True).click()
                            expect(page.locator('.tw-flow-node')).to_have_count(3)
                            page.locator('.tw-flow-node.is-selected').get_by_role('button', name='节点操作').click()
                            page.locator('.q-menu:visible').get_by_text('移除任务', exact=True).click()
                            expect(page.locator('.tw-flow-node')).to_have_count(2)
                            expect(page.locator('.tw-flow-node.is-selected')).to_have_count(1)
                            zoom('75%')
                            page.get_by_role('button', name='展开或收起流程', exact=True).click()
                            page.get_by_role('tab', name='基础配置', exact=True).click()
                            page.get_by_label('组合名称', exact=True).fill('Unified canvas')
                            page.get_by_role('button', name='保存组合', exact=True).click()
                            expect(page.get_by_role('button', name='Unified canvas', exact=True)).to_be_visible()
                            page.get_by_role('tab', name='任务编排', exact=True).click()
                            expect(page.locator('.tw-flow-canvas')).to_be_hidden()
                            page.get_by_role('button', name='展开或收起流程', exact=True).click()
                            self.assertEqual(page.locator('.tw-flow-root').evaluate('e => e.style.zoom'), '0.75')
                            no_overflow()
                            page.screenshot(path=str(screenshots / 'sequence-narrow.png'), full_page=True)
                            page.set_viewport_size({'width': 1440, 'height': 1100})
                            page.screenshot(path=str(screenshots / 'sequence-desktop.png'), full_page=True)
                            # Explicit save persists reference identity and flushed control configuration.
                            with sqlite3.connect(Path(home) / 'taskweave.db') as db:
                                flow = json.loads(db.execute('SELECT flow_json FROM task_sequences').fetchone()[0])
                            self.assertEqual(flow['root']['children'][0]['max_items'], 8)
                            self.assertEqual(flow['root']['children'][0]['body']['children'][0]['step_id'], identity)
                            self.assertFalse(errors, errors)
                        except Exception:
                            page.screenshot(path=str(screenshots / 'failure.png'), full_page=True)
                            (screenshots / 'failure.txt').write_text(page.locator('body').inner_text())
                            raise
                        finally:
                            browser.close()
                finally:
                    (screenshots / 'server.log').write_text(log_path.read_text())
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=10)
