"""Real canvas insertion, dependency rejection and cross-branch drag persistence."""
from pathlib import Path
import json
import os
import re
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.request import urlopen

SERVER = '''
import sys
from nicegui import ui
from taskweave.application.service import Application
from taskweave.desktop.controller import DesktopController
from taskweave.desktop.workbench import Workbench
from taskweave.presentation.flow_editor import insert_control
app=Application(sys.argv[1])
library=app.repo.create_task('Library')
up=app.steps.save(library['task_id'],{'name':'Library producer'})
app.steps.save(library['task_id'],{'name':'Reusable bound','step_content':'async def run(ctx, inputs):\\n    return ctx.result(data=inputs)\\n',
 'bindings':{'value':{'ref':{'source':'step','step_id':up['step_id'],'pointer':'/value'}}}})
task=app.repo.create_task('Canvas editing')
a=app.steps.save(task['task_id'],{'name':'Producer','step_content':'async def run(ctx, inputs):\\n    return ctx.result(data=inputs)\\n'})
b=app.steps.save(task['task_id'],{'name':'Consumer','step_content':a['step_content'],'bindings':{'v':{'ref':{'source':'step','step_id':a['step_id'],'pointer':''}}}})
c=app.steps.save(task['task_id'],{'name':'Independent','step_content':a['step_content']})
d=app.tasks.describe_flow(task['task_id'])
flow,control=insert_control(d['flow'],'if')
app.tasks.save_flow(task['task_id'],flow,d['definition_hash'])
@ui.page('/')
async def index():
 wb=Workbench(DesktopController(app))
 await wb.navigate('editor',task_id=task['task_id'],step_id=a['step_id'])
ui.run(host='127.0.0.1',port=int(sys.argv[2]),show=False,reload=False)
'''


class CanvasBrowserTests(unittest.TestCase):
    def test_drag_insert_delete_and_dependency_rejection(self):
        from playwright.sync_api import sync_playwright, expect
        with tempfile.TemporaryDirectory(prefix='taskweave-canvas-browser-') as home:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
            log = Path(home) / 'server.log'
            with log.open('w') as output:
                process = subprocess.Popen([sys.executable, '-c', SERVER, home, str(port)], stdout=output, stderr=output)
                try:
                    url = f'http://127.0.0.1:{port}/'
                    deadline = time.monotonic() + 25
                    while True:
                        try:
                            with urlopen(url, timeout=1): break
                        except OSError:
                            if process.poll() is not None or time.monotonic() > deadline:
                                self.fail(log.read_text()[-4000:])
                            time.sleep(.1)
                    with sync_playwright() as p:
                        browser = p.chromium.launch(headless=True)
                        page = browser.new_page(viewport={'width': 1600, 'height': 1100})
                        errors = []; page.on('pageerror', lambda e: errors.append(str(e)))
                        page.goto(url)
                        consumer = page.locator('.tw-flow-node').filter(has_text='Consumer')
                        expect(consumer).to_be_visible()
                        first_gap = page.locator('.tw-flow-insert[data-parent-id="root"][data-index="0"]')
                        consumer.drag_to(first_gap)
                        expect(page.get_by_text('无法移动：', exact=False)).to_be_visible()
                        expect(page.locator('.tw-flow-node').first).to_contain_text('Producer')
                        page.locator('.tw-flow-node').filter(has_text='Producer').get_by_role('button', name='节点操作').click()
                        page.get_by_text('移动到其他分组', exact=True).last.click()
                        page.get_by_role('dialog').get_by_role('button', name='移动', exact=True).click()
                        expect(page.get_by_role('dialog').get_by_text('无法移动：', exact=False)).to_be_visible()
                        page.get_by_role('dialog').get_by_role('button', name='取消', exact=True).click()
                        expect(page.locator('.tw-flow-node').first).to_contain_text('Producer')
                        target = page.locator('.tw-flow-branch').first.locator('.tw-flow-insert').first
                        page.locator('.tw-flow-node').filter(has_text='Independent').drag_to(target)
                        expect(page.locator('.tw-flow-branch').first).to_contain_text('Independent')
                        # Reload validates stored branch membership, not only DOM movement.
                        page.reload()
                        expect(page.locator('.tw-flow-branch').first).to_contain_text('Independent')
                        page.locator('.tw-flow-node').first.get_by_role('button', name='节点操作').click()
                        page.get_by_text('在后面插入', exact=True).last.click()
                        page.get_by_role('dialog').get_by_role('button', name='步骤', exact=True).click()
                        expect(page.locator('.tw-flow-node').nth(1)).to_contain_text('新步骤')
                        page.locator('.tw-flow-node').nth(1).get_by_role('button', name='节点操作').click()
                        page.get_by_text('删除步骤', exact=True).last.click()
                        page.get_by_role('dialog').get_by_role('button', name='删除', exact=True).click()
                        expect(page.locator('.tw-flow-node')).to_have_count(3)
                        page.reload()
                        expect(page.locator('.tw-flow-node')).to_have_count(3)
                        producer = page.locator('.tw-flow-node').filter(has_text='Producer').first
                        producer.get_by_role('button', name='节点操作').click()
                        page.get_by_text('复制步骤', exact=True).last.click()
                        page.get_by_role('dialog').get_by_role('button', name='确认复制', exact=True).click()
                        expect(page.locator('.tw-flow-node')).to_have_count(4)
                        page.locator('.tw-flow-node.is-selected').get_by_role('button', name='节点操作').click()
                        page.get_by_text('拆分步骤', exact=True).last.click()
                        expect(page.locator('.tw-step-derivation-part')).to_have_count(2)
                        page.get_by_label('第二份名称', exact=True).fill('Split result')
                        split_dialog = page.locator('.tw-step-derivation-dialog')
                        for tab in ('上下文', '输入输出', '代码'):
                            split_dialog.get_by_role('tab', name=tab, exact=True).click()
                            expect(split_dialog.get_by_role('tab', name=tab, exact=True)).to_have_attribute('aria-selected', 'true')
                            expect(page.get_by_label('第二份名称', exact=True)).to_have_value('Split result')
                        for width, height in ((1600, 1100), (650, 800)):
                            page.set_viewport_size({'width': width, 'height': height})
                            footer = split_dialog.locator('.tw-step-operation-footer')
                            expect(footer.get_by_role('button', name='确认拆分', exact=True)).to_be_in_viewport()
                            bounds = split_dialog.bounding_box()
                            self.assertGreaterEqual(bounds['x'], 0)
                            self.assertLessEqual(bounds['x'] + bounds['width'], width)
                            body_bounds = split_dialog.locator('.tw-step-operation-body').bounding_box()
                            self.assertLessEqual(body_bounds['y'] + body_bounds['height'], footer.bounding_box()['y'] + 1)
                            if os.getenv('TASKWEAVE_QA_SCREENSHOT_DIR'):
                                page.screenshot(path=str(Path(os.environ['TASKWEAVE_QA_SCREENSHOT_DIR']) / f'split-{width}.png'), animations='disabled')
                        page.set_viewport_size({'width': 1600, 'height': 1100})
                        if os.getenv('TASKWEAVE_QA_SCREENSHOT_DIR'):
                            page.locator('.tw-step-derivation-dialog').evaluate('(element) => element.scrollTop = 0')
                            page.screenshot(path=str(Path(os.environ['TASKWEAVE_QA_SCREENSHOT_DIR']) / 'split-dialog.png'), full_page=True, animations='disabled')
                        page.get_by_role('dialog').get_by_role('button', name='确认拆分', exact=True).click()
                        expect(page.locator('.tw-flow-node')).to_have_count(5)
                        expect(page.locator('.tw-flow-node.is-selected')).to_contain_text('Split result')
                        page.reload()
                        expect(page.locator('.tw-flow-node')).to_have_count(5)
                        page.locator('.tw-flow-node').first.get_by_role('button', name='节点操作').click()
                        page.get_by_text('在后面插入', exact=True).last.click()
                        page.get_by_role('dialog').get_by_role('button', name='从已有步骤复制', exact=True).click()
                        page.get_by_role('dialog').get_by_role('button', name='确认复用', exact=True).click()
                        expect(page.locator('.tw-flow-node')).to_have_count(6)
                        page.locator('.tw-flow-node').first.get_by_role('button', name='节点操作').click()
                        page.get_by_text('在后面插入', exact=True).last.click()
                        page.get_by_role('dialog').get_by_role('button', name='从已有步骤复制', exact=True).click()
                        page.get_by_label('来源任务', exact=True).click()
                        page.get_by_role('option', name=re.compile(r'\d+ · Library$')).click()
                        page.get_by_label('来源步骤', exact=True).click()
                        page.get_by_role('option', name=re.compile(r'\d+ · Reusable bound$')).click()
                        expect(page.get_by_role('option', name=re.compile(r'\d+ · Reusable bound$'))).not_to_be_visible()
                        if os.getenv('TASKWEAVE_QA_SCREENSHOT_DIR'):
                            page.screenshot(path=str(Path(os.environ['TASKWEAVE_QA_SCREENSHOT_DIR']) / 'reuse-dependencies.png'), animations='disabled')
                        page.get_by_role('dialog').get_by_role('button', name='确认复用', exact=True).click()
                        expect(page.get_by_text('输入 value 的步骤依赖尚未解决', exact=False)).to_be_visible()
                        page.get_by_label('输入 value 的依赖处理', exact=True).click()
                        page.get_by_role('option', name='删除依赖绑定', exact=True).click()
                        page.get_by_role('dialog').get_by_role('button', name='确认复用', exact=True).click()
                        expect(page.locator('.tw-flow-node')).to_have_count(7)
                        page.reload()
                        expect(page.locator('.tw-flow-node')).to_have_count(7)
                        self.assertEqual(errors, [])
                        browser.close()
                finally:
                    process.terminate()
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
