"""Real workbench checks for dependency choices and staged human inputs."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.request import urlopen
from taskweave.application.service import Application
from taskweave.infrastructure.storage import uid


class InputUi(unittest.TestCase):
    def test_dependency_picker_and_task_then_step_input(self):
        from playwright.sync_api import sync_playwright, expect
        with tempfile.TemporaryDirectory(prefix='taskweave-input-ui-') as home:
            with Application(home) as app:
                app.repo.save_environment('dev', {'url':'dev'})
                app.repo.save_environment('uat', {'url':'uat'})
                task=app.repo.create_task('输入验收',{'type':'object','properties':{'org':{'type':'string'}},'required':['org']})['task_id']
                first=app.repo.save_step(task,{'name':'前一步','step_content':'async def run(ctx, inputs):\n    return ctx.result(data={"image_base64":"sample"})'})
                second=app.repo.save_step(task,{'name':'当前步骤','input_schema':{'type':'object','properties':{'number':{'type':'integer'}},'required':['number']},'step_content':'async def run(ctx, inputs):\n    return ctx.result(data={"number": inputs["number"], "report": {"passed": True, "message": "核对通过", "tables": [{"title": "核对明细", "columns": [{"key": "number", "label": "录入值"}], "rows": [{"number": inputs["number"]}]}]}}, views=[{"title": "核对报告", "renderer": "core.report", "pointer": "/report"}, {"title": "输入摘要", "renderer": "core.json", "pointer": "/number"}])'})
                for step in [first,second]:
                    app.confirm_step_manual(step['step_id'],step['content_hash'])
                run=app.trial_step(first['step_id'],{'org':'seed'},uid())
                app.coordinator.wait(run['run_id'])
            with socket.socket() as reserve:
                reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
            output=Path(home)/'server.log'
            with output.open('w') as log:
                process=subprocess.Popen([sys.executable,'-m','taskweave','--home',home,'workbench','--browser','--port',str(port)],stdout=log,stderr=log)
                try:
                    url=None
                    deadline=time.monotonic()+60
                    while time.monotonic()<deadline:
                        for line in output.read_text().splitlines():
                            if line.startswith('{"url":'):
                                url=json.loads(line)['url']
                        if url:
                            try:
                                urlopen(url,timeout=1).close();break
                            except OSError:
                                pass
                        if process.poll() is not None:
                            self.fail(output.read_text())
                        time.sleep(.1)
                    self.assertIsNotNone(url)
                    with sync_playwright() as runtime:
                        browser=runtime.chromium.launch(headless=True)
                        page=browser.new_page(viewport={'width':1280,'height':950})
                        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                        page.goto(url)
                        page.get_by_role('button',name='打开',exact=True).click()
                        first_button=page.get_by_role('button',name='1. 前一步',exact=True)
                        expect(first_button).to_be_visible()
                        self.assertEqual(first_button.evaluate('e=>getComputedStyle(e).backgroundColor'),'rgb(22, 163, 74)')
                        self.assertEqual(first_button.locator('.q-icon').inner_text(),'check')
                        self.assertEqual(first_button.evaluate('e=>getComputedStyle(e).color'),'rgb(255, 255, 255)')
                        page.get_by_role('button',name='2. 当前步骤',exact=True).click()
                        expect(page.get_by_label('步骤名称',exact=True)).to_have_value('当前步骤')
                        page.get_by_role('tab',name='输入依赖',exact=True).click()
                        page.get_by_role('button',name='添加绑定',exact=True).click()
                        source=page.locator('.q-select').filter(has=page.get_by_text('来源',exact=True))
                        source.click()
                        options=page.get_by_role('option')
                        self.assertEqual(options.nth(0).inner_text(),'固定值')
                        self.assertEqual(options.nth(1).inner_text(),'前序结果')
                        page.get_by_role('option',name='前序结果',exact=True).click()
                        expect(page.get_by_label('固定值（文本或 JSON 值）',exact=True)).not_to_be_visible()
                        previous=page.locator('.q-select').filter(has=page.get_by_text('前序步骤',exact=True))
                        previous.click();page.get_by_role('option',name='前一步',exact=True).click()
                        expect(page.get_by_text('字段与示例值来自最近成功运行；执行仍读取本次运行结果。',exact=True)).to_be_visible()
                        field=page.locator('.q-select').filter(has=page.get_by_text('结果字段（可选择或填写 /字段名）',exact=True))
                        field.click();page.get_by_role('option',name='/image_base64 · sample',exact=True).click()
                        expect(page.get_by_label('步骤输入名称',exact=True)).to_have_value('image_base64')
                        # Inspect only, then remove the binding so this flow tests unbound input.
                        page.get_by_role('button',name='移除此绑定',exact=True).click()
                        evidence=Path(__file__).resolve().parents[1]/'.runtime/req005-ui-evidence'
                        evidence.mkdir(parents=True,exist_ok=True)
                        page.screenshot(path=str(evidence/'dependency-picker.png'),full_page=True)
                        page.get_by_role('tab',name='步骤详情',exact=True).click()
                        page.get_by_role('button',name='调试',exact=True).click()
                        env=page.locator('.q-select').filter(has=page.get_by_text('运行 / 试跑环境',exact=True))
                        env.click();page.get_by_role('option',name='uat',exact=True).click()
                        expect(page.get_by_label('org · 必录',exact=True)).to_have_attribute('placeholder','未配置默认值，请录入')
                        expect(page.get_by_label('org · 必录',exact=True)).to_have_value('')
                        page.get_by_label('org · 必录',exact=True).fill('uat-org')
                        page.get_by_label('number · 必录',exact=True).fill('17')
                        page.get_by_role('button',name='执行试跑',exact=True).click()
                        expect(page.get_by_text('试跑状态：成功',exact=True)).to_be_visible(timeout=15000)
                        self.assertEqual(page.get_by_role('button',name='执行试跑',exact=True).evaluate('e=>getComputedStyle(e).backgroundColor'),'rgb(240, 253, 250)')
                        expect(page.get_by_label('org · 必录',exact=True)).to_have_value('uat-org')
                        expect(page.get_by_label('number · 必录',exact=True)).to_have_value('17')
                        actions=[page.get_by_role('button',name=title,exact=True).bounding_box() for title in ['执行试跑','从首步开始','结束测试']]
                        self.assertLess(max(b['y'] for b in actions)-min(b['y'] for b in actions),2)
                        page.screenshot(path=str(evidence/'trial-actions.png'),full_page=True)
                        self.assertEqual(page.get_by_role('button',name='结束测试',exact=True).count(),1)
                        env=page.locator('.q-select').filter(has=page.get_by_text('运行 / 试跑环境',exact=True))
                        expect(env).to_contain_text('uat')
                        page.get_by_role('button',name='执行试跑',exact=True).click()
                        expect(page.get_by_role('button',name='执行试跑',exact=True)).to_be_enabled(timeout=15000)
                        expect(page.get_by_text('试跑状态：成功',exact=True)).to_be_visible(timeout=15000)
                        page.get_by_role('button',name='结束测试',exact=True).click()
                        page.get_by_role('button',name='确认结束',exact=True).click()
                        expect(page.get_by_role('button',name='结束测试',exact=True)).to_be_disabled(timeout=10000)
                        page.get_by_role('button',name='执行',exact=True).click()
                        page.get_by_role('button',name='新建执行',exact=True).click()
                        self.assertEqual(page.get_by_label('org · 必录',exact=True).count(),0)
                        page.get_by_role('button',name='创建执行',exact=True).click()
                        page.get_by_role('button',name='2. 当前步骤',exact=True).click()
                        page.get_by_role('button',name='从前面未执行的步骤继续到此步',exact=True).click()
                        try:
                            expect(page.get_by_text('任务运行输入 · 补充必录参数',exact=True)).to_be_visible(timeout=15000)
                        except Exception:
                            page.screenshot(path=str(evidence/'input-failure.png'),full_page=True)
                            (evidence/'input-failure-server.log').write_text(output.read_text())
                            (evidence/'input-failure-body.txt').write_text(page.locator('body').inner_text())
                            raise
                        footer=[page.get_by_role('button',name=title,exact=True).evaluate('e=>e.parentElement.id') for title in ['提交输入并继续','稍后填写']]
                        self.assertEqual(footer[0],footer[1])
                        self.assertEqual(page.get_by_role('button',name='提交输入并继续',exact=True).evaluate('e=>getComputedStyle(e.parentElement).flexDirection'),'row')
                        page.get_by_label('org · 必录',exact=True).fill('one')
                        page.get_by_role('button',name='提交输入并继续',exact=True).click()
                        expect(page.get_by_text('当前步骤输入 · 补充必录参数',exact=True)).to_be_visible(timeout=15000)
                        modal=page.get_by_role('dialog')
                        self.assertEqual(modal.locator('.q-expansion-item').count(),3)
                        modal.get_by_text('任务变量 · 本次运行输入',exact=True).click()
                        expect(modal.get_by_label('org · 必录',exact=True)).to_be_disabled()
                        modal.get_by_text('任务变量 · 本次运行输入',exact=True).click()
                        page.get_by_label('number · 必录',exact=True).fill('8')
                        page.get_by_role('button',name='提交输入并继续',exact=True).click()
                        expect(page.get_by_text('运行状态：成功',exact=True)).to_be_visible(timeout=15000)
                        expect(page.get_by_text('执行 · 未开始',exact=False)).to_have_count(0)
                        evidence=Path(__file__).resolve().parents[1]/'.runtime/req005-ui-evidence'
                        evidence.mkdir(parents=True,exist_ok=True)
                        page.screenshot(path=str(evidence/'staged-inputs.png'),full_page=True)
                        page.get_by_role('button',name='2. 当前步骤',exact=True).click()
                        expect(page.get_by_text('开始步骤',exact=True)).to_be_visible()
                        page.get_by_role('button',name='从所选步骤重新执行到此步',exact=True).click()
                        expect(page.get_by_label('number · 必录',exact=True)).to_be_visible(timeout=15000)
                        page.get_by_label('number · 必录',exact=True).fill('9')
                        page.get_by_role('button',name='提交输入并继续',exact=True).click()
                        expect(page.get_by_text('运行状态：成功',exact=True)).to_be_visible(timeout=15000)
                        expect(page.get_by_role('button',name='详情',exact=True)).to_be_visible()
                        expect(page.get_by_role('button',name='收起',exact=True)).to_have_count(0)
                        self.assertEqual(page.get_by_role('button',name='查看步骤结果',exact=True).count(),2)
                        page.get_by_role('button',name='查看步骤结果',exact=True).nth(1).click()
                        result_modal=page.get_by_role('dialog')
                        expect(result_modal.get_by_role('tab',name='核对报告',exact=True)).to_be_visible()
                        expect(result_modal.get_by_role('columnheader',name='录入值',exact=True)).to_be_visible()
                        expect(result_modal.get_by_text('核对通过',exact=True)).to_be_visible()
                        result_modal.get_by_role('tab',name='输入摘要',exact=True).click()
                        expect(result_modal.get_by_role('code').get_by_text('9',exact=True)).to_be_visible()
                        result_modal.get_by_role('tab',name='原始数据',exact=True).click()
                        expect(result_modal.get_by_text('"number": 9',exact=False)).to_be_visible()
                        result_modal.get_by_role('tab',name='核对报告',exact=True).click()
                        expect(result_modal.get_by_role('columnheader',name='录入值',exact=True)).to_be_visible()
                        page.wait_for_timeout(400)
                        page.screenshot(path=str(evidence/'result-views.png'),full_page=True)
                        result_modal.get_by_role('button',name='关闭',exact=True).click()
                        # The detail panel belongs to this execution card.
                        state=page.get_by_text('运行状态：成功',exact=True)
                        self.assertEqual(state.evaluate('e=>e.closest(".tw-panel").parentElement.closest(".tw-panel")!==null'),True)
                        page.get_by_role('button',name='删除执行',exact=True).click()
                        page.get_by_role('button',name='确认删除执行',exact=True).click()
                        expect(page.get_by_role('button',name='2. 当前步骤',exact=True)).to_have_count(0)
                        self.assertFalse(page.locator('.tw-panel').evaluate_all('nodes=>nodes.some(e=>!e.textContent.trim())'))
                        self.assertFalse(page.locator('button').evaluate_all('nodes=>nodes.some(e=>getComputedStyle(e).backgroundColor==="rgb(52, 90, 219)")'))
                        page.get_by_role('button',name='返回任务列表',exact=True).click()
                        expect(page.get_by_role('button',name='删除',exact=True)).to_be_visible()
                        page.get_by_role('button',name='导出',exact=True).click()
                        export_dialog=page.get_by_role('dialog')
                        package=export_dialog.get_by_label('任务 JSON',exact=True).input_value()
                        self.assertEqual(json.loads(package)['format'],'taskweave-task-1')
                        expect(export_dialog.get_by_role('button',name='复制 JSON',exact=True)).to_be_visible()
                        export_dialog.get_by_role('button',name='关闭',exact=True).click()
                        page.get_by_role('button',name='导入任务',exact=True).click()
                        page.get_by_role('dialog').get_by_label('任务 JSON',exact=True).fill(package)
                        page.get_by_role('button',name='导入为新任务',exact=True).click()
                        expect(page.get_by_role('button',name='打开',exact=True)).to_have_count(2)
                        page.get_by_role('button',name='环境',exact=True).click()
                        uat=page.locator('.tw-panel').filter(has=page.get_by_text('uat',exact=True))
                        uat.get_by_role('button',name='删除环境',exact=True).click()
                        page.get_by_role('button',name='确认删除环境',exact=True).click()
                        expect(page.get_by_text('uat',exact=True)).to_have_count(0)

                        self.assertFalse(errors,errors)
                        browser.close()
                    self.assertNotIn('Traceback',output.read_text())
                finally:
                    evidence=Path(__file__).resolve().parents[1]/'.runtime/req005-ui-evidence'
                    evidence.mkdir(parents=True,exist_ok=True)
                    (evidence/'latest-input-server.log').write_text(output.read_text())
                    if process.poll() is None:
                        process.send_signal(signal.SIGINT if os.name!='nt' else signal.SIGTERM)
                        try:process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            process.kill();process.wait()
