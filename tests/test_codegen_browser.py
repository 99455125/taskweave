"""Isolated local browser acceptance for the code page, without models or user data."""
from pathlib import Path
import socket
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
from tests.test_local_codegen import recorded_capture
app=Application(sys.argv[1],registry_factory='tests.test_local_codegen:build_registry')
task=app.repo.create_task('Code generation acceptance')
step=app.repo.save_step(task['task_id'],{'name':'Search order','capabilities':list(app.registry.actions),
 'step_content':'async def run(ctx, inputs):\\n    return ctx.result(data=inputs)\\n',
 'input_schema':{'type':'object','properties':{'order_no':{'type':'string'}}}})
app.contexts.save(step['step_id'],'playwright.page','Order recording','draft',recorded_capture()['items'])
@ui.page('/')
async def index():
 wb=Workbench(DesktopController(app))
 await wb.navigate('editor',task_id=task['task_id'],step_id=step['step_id'])
ui.run(host='127.0.0.1',port=int(sys.argv[2]),show=False,reload=False)
'''


class LocalCodegenBrowserTests(unittest.TestCase):
    def test_saved_context_candidate_preview_and_replace_real_browser(self):
        from playwright.sync_api import sync_playwright,expect
        with tempfile.TemporaryDirectory(prefix='taskweave-codegen-ui-') as home:
            with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
            log=Path(home)/'server.log'
            with log.open('w') as output:
                process=subprocess.Popen([sys.executable,'-c',SERVER,home,str(port)],stdout=output,stderr=output)
                try:
                    url=f'http://127.0.0.1:{port}/'
                    deadline=time.monotonic()+30
                    while True:
                        try:
                            with urlopen(url,timeout=1):break
                        except Exception:
                            if process.poll() is not None or time.monotonic()>deadline:
                                self.fail(log.read_text()[-4000:])
                            time.sleep(.1)
                    with sync_playwright() as p:
                        browser=p.chromium.launch(headless=True)
                        page=browser.new_page(viewport={'width':1440,'height':1000});errors=[]
                        page.on('pageerror',lambda error:errors.append(str(error)))
                        page.goto(url);page.get_by_role('tab',name='步骤代码',exact=True).click()
                        page.get_by_role('button',name='本地代码生成',exact=True).click()
                        expect(page.get_by_text('Order recording · 采集 1',exact=True)).to_be_visible()
                        page.get_by_role('button',name='生成代码',exact=True).click()
                        expect(page.locator('.tw-codegen-source')).to_have_count(0)
                        expect(page.get_by_text('未生成可用代码',exact=True)).to_be_visible()
                        binding=page.locator('.q-select').filter(has_text='操作 1 的输入值').first
                        expect(binding).to_be_visible();binding.click()
                        page.get_by_role('option',name='绑定已有输入：order_no',exact=True).click()
                        page.get_by_role('button',name='生成代码',exact=True).click()
                        expect(page.locator('.tw-codegen-source')).to_contain_text("inputs['order_no']")
                        page.get_by_role('button',name='在左侧预览',exact=True).click()
                        expect(page.locator('.tw-codegen-full-preview')).to_contain_text("inputs['order_no']")
                        page.get_by_role('button',name='替换步骤代码',exact=True).click()
                        expect(page.get_by_role('button',name='确认替换',exact=True)).to_be_visible()
                        page.get_by_role('button',name='确认替换',exact=True).click()
                        expect(page.locator('.cm-content')).to_contain_text("inputs['order_no']")
                        expect(page.get_by_role('dialog')).not_to_be_visible()
                        self.assertFalse(errors,errors)
                        evidence=Path('.superpowers/sdd/2026-10-27-local-codegen/codegen-browser.png')
                        page.screenshot(path=str(evidence),full_page=True)
                        browser.close()
                finally:
                    process.terminate()
                    try:process.wait(timeout=10)
                    except subprocess.TimeoutExpired:process.kill();process.wait()
