"""Uploads and native dialog handling in actual Chromium, with temporary data."""
import asyncio
import base64
import tempfile
import unittest
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from playwright.async_api import async_playwright
from taskweave.core.validation import TaskError, validate
from taskweave_playwright import PlaywrightPlugin


class PlaywrightProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancellation_before_protocol_task_starts_does_not_issue_command(self):
        from taskweave_playwright.protocol import reply
        issued = []
        async def command():
            issued.append('click')
        parent = asyncio.create_task(reply(command()))
        asyncio.get_running_loop().call_soon(parent.cancel)
        with self.assertRaises(asyncio.CancelledError):
            await parent
        await asyncio.sleep(0)
        self.assertEqual(issued, [])


class PlaywrightFilesDialogTests(unittest.IsolatedAsyncioTestCase):
    async def test_snapshot_budget_timeout_then_close_observes_reply(self):
        from taskweave_playwright import snapshot
        await self.page.set_content('<button id=target>采集</button>')
        await self.page.evaluate('''()=>{
            const original=Element.prototype.getAttribute;
            Element.prototype.getAttribute=function(name){
                if(name==='role'){
                    const until=performance.now()+5000;
                    while(performance.now()<until){}
                }
                return original.call(this,name);
            };
        }''')
        await self._assert_timed_call_observed(asyncio.wait_for(snapshot(self.page), .1), asyncio.TimeoutError)

    async def test_list_budget_timeout_then_close_observes_reply(self):
        await self.page.set_content('<div class=item>完整中文明细</div>')
        await self.page.evaluate('''()=>{
            const original=Object.getOwnPropertyDescriptor(Node.prototype,'textContent');
            Object.defineProperty(Node.prototype,'textContent',{...original,get(){
                if(this.nodeType===3){
                    const until=performance.now()+5000;
                    while(performance.now()<until){}
                }
                return original.get.call(this);
            }});
        }''')
        await self._assert_timed_call_observed(self.call('page_list', selector='.item', timeout_ms=100), TaskError)

    async def _assert_timed_call_observed(self, awaitable, error_type):
        import gc
        loop = asyncio.get_running_loop()
        previous = loop.get_exception_handler()
        errors = []
        loop.set_exception_handler(lambda _loop, context: errors.append(context))
        try:
            with self.assertRaises(error_type) as timeout:
                await awaitable
            if error_type is TaskError:
                self.assertEqual(timeout.exception.code, 'BROWSER_TIMEOUT')
            await self.browser.close()
            del timeout, awaitable
            gc.collect()
            await asyncio.sleep(0)
            self.assertEqual(errors, [], [(entry.get('message'), str(entry.get('exception'))) for entry in errors])
        finally:
            loop.set_exception_handler(previous)

    async def test_preflight_timeout_then_browser_close_observes_inflight_reply(self):
        import gc
        await self.page.set_content('<button id=trigger>打开</button>')
        await self.page.evaluate('''()=>{
            const original=Element.prototype.matches;
            Element.prototype.matches=function(selector){
                if(selector==='input,textarea,select'){
                    const until=performance.now()+5000;
                    while(performance.now()<until){}
                }
                return original.call(this,selector);
            };
        }''')
        loop = asyncio.get_running_loop()
        previous = loop.get_exception_handler()
        errors = []
        loop.set_exception_handler(lambda _loop, context: errors.append(context))
        try:
            with self.assertRaises(TaskError) as timeout:
                await self.call('page_click', selector='#trigger')
            self.assertEqual(timeout.exception.code, 'BROWSER_TIMEOUT')
            await self.browser.close()
            del timeout  # Release its cancelled-await traceback before collection.
            gc.collect()
            await asyncio.sleep(0)
            self.assertEqual(errors, [], [(entry.get('message'), str(entry.get('exception'))) for entry in errors])
        finally:
            loop.set_exception_handler(previous)

    async def test_blocked_chooser_timeout_observes_protocol_error_without_orphan_future(self):
        import gc
        await self.page.set_content('''<button id=choose onclick="this.dataset.clicked='yes'">选择文件</button>
            <div style="position:fixed;inset:0;z-index:1000">遮挡</div>''')
        loop = asyncio.get_running_loop()
        previous = loop.get_exception_handler()
        errors = []
        loop.set_exception_handler(lambda _loop, context: errors.append(context))
        try:
            for _ in range(3):
                with self.assertRaises(TaskError) as timeout:
                    await self.call('page_upload', selector='#choose', mode='chooser',
                                    files=[self.file()], timeout_ms=100)
                self.assertEqual(timeout.exception.code, 'BROWSER_TIMEOUT')
                self.assertEqual(len(self.page._impl_obj.listeners('filechooser')), 0)
                # Allow the protocol's 100ms deadline response to arrive after
                # the enclosing Python timeout, then collect abandoned futures.
                await asyncio.sleep(.15)
                gc.collect()
                await self.page.evaluate('()=>true')
            self.assertIsNone(await self.page.locator('#choose').get_attribute('data-clicked'))
            self.assertEqual(errors, [], [(entry.get('message'), str(entry.get('exception'))) for entry in errors])
        finally:
            loop.set_exception_handler(previous)

    async def asyncSetUp(self):
        self.runtime = await async_playwright().start()
        self.browser = await self.runtime.chromium.launch(headless=True)
        self.context = await self.browser.new_context()
        self.page = await self.context.new_page()
        self.resource = {'page': self.page, 'context': self.context}
        self.ctx = SimpleNamespace(resources=SimpleNamespace(acquire=AsyncMock(return_value=self.resource)),
            environment={}, task_parameters={}, emit=lambda *args: None)
        self.actions = PlaywrightPlugin().actions()

    async def asyncTearDown(self):
        await self.browser.close()
        await self.runtime.stop()

    async def call(self, action_name, **inputs):
        action = self.actions['playwright.' + action_name]
        validate(inputs, action.spec.input_schema)
        result = await action.execute(self.ctx, inputs)
        validate(result, action.spec.output_schema)
        return result

    def file(self, name='样本.txt', content=b'fixture'):
        return {'name': name, 'mime_type': 'text/plain', 'content_base64': base64.b64encode(content).decode('ascii')}

    async def test_file_plugin_read_then_upload_hidden_input_in_frame_preserves_bytes(self):
        from taskweave_file import FilePlugin
        with tempfile.TemporaryDirectory() as root:
            data = b'\x00\xff' + '中文文件'.encode()
            Path(root, 'sample.bin').write_bytes(data)
            file_ctx = SimpleNamespace(environment={'file_root': root}, task_parameters={}, cancelled=lambda: False)
            document = await FilePlugin().actions()['file.read'].execute(file_ctx, {'path': 'sample.bin', 'format': 'base64'})
        await self.page.set_content('<iframe id=frame srcdoc="&lt;input id=file type=file style=display:none&gt;"></iframe>')
        file = {'name': document['path'], 'mime_type': 'application/octet-stream', 'content_base64': document['content']}
        result = await self.call('page_upload', selector={'kind': 'css', 'value': '#file', 'frame': '#frame'}, files=[file])
        self.assertEqual(result['total_bytes'], len(data))
        control = self.page.frame_locator('#frame').locator('#file')
        uploaded = await control.evaluate('async e=>({name:e.files[0].name,bytes:Array.from(new Uint8Array(await e.files[0].arrayBuffer()))})')
        self.assertEqual(uploaded, {'name': 'sample.bin', 'bytes': list(data)})

    async def test_upload_multiple_and_clear_files_are_explicit(self):
        await self.page.set_content('<input id=file type=file multiple>')
        result = await self.call('page_upload', selector='#file', files=[self.file(), self.file('empty.txt', b'')])
        self.assertEqual(result['files'][1]['size_bytes'], 0)
        self.assertEqual(await self.page.locator('#file').evaluate('e=>e.files.length'), 2)
        await self.call('page_upload', selector='#file', files=[])
        self.assertEqual(await self.page.locator('#file').evaluate('e=>e.files.length'), 0)

    async def test_chooser_upload_handles_dynamic_input_and_removes_listener(self):
        await self.page.set_content('''<button id=choose onclick="const e=document.createElement('input');e.type='file';e.id='dynamic';document.body.append(e);e.click()">选择文件</button>''')
        await self.call('page_upload', selector='#choose', mode='chooser', files=[self.file()])
        self.assertEqual(await self.page.locator('#dynamic').evaluate('e=>e.files[0].name'), '样本.txt')
        self.assertEqual(len(self.page._impl_obj.listeners('filechooser')), 0)

    async def test_upload_rejects_multiple_for_single_and_wrong_control(self):
        await self.page.set_content('<input id=file type=file><input id=disabled type=file disabled><button id=wrong>不是文件框</button>')
        for inputs, code in [({'selector': '#file', 'files': [self.file(), self.file('two.txt')]}, 'UPLOAD_MULTIPLE_UNSUPPORTED'),
                             ({'selector': '#wrong', 'files': [self.file()]}, 'LOCATOR_NOT_FILE_INPUT'),
                             ({'selector': '#disabled', 'files': [self.file()]}, 'LOCATOR_DISABLED')]:
            with self.assertRaises(TaskError) as error:
                await self.call('page_upload', **inputs)
            self.assertEqual(error.exception.code, code)
        self.assertEqual(await self.page.locator('#file').evaluate('e=>e.files.length'), 0)

    async def test_invalid_or_oversized_content_fails_before_click(self):
        await self.page.set_content('<button id=choose onclick="this.dataset.clicked=1">选择文件</button>')
        invalid = self.file(); invalid['content_base64'] = '%%%'
        oversized = self.file(content=b'x' * (1024 * 1024 + 1))
        for file in [invalid, oversized]:
            with self.assertRaises(TaskError):
                await self.call('page_upload', selector='#choose', mode='chooser', files=[file])
        self.assertIsNone(await self.page.locator('#choose').get_attribute('data-clicked'))
        with self.assertRaises(TaskError) as error:
            await self.call('page_upload', selector='#choose', mode='chooser',
                files=[self.file(str(index)+'.txt', b'x' * (1024 * 1024)) for index in range(9)])
        self.assertEqual(error.exception.code, 'UPLOAD_TOO_LARGE')
        self.assertIsNone(await self.page.locator('#choose').get_attribute('data-clicked'))
        for name in ['../private.txt', '/absolute.txt', 'C:\\private.txt']:
            with self.assertRaises(TaskError):
                await self.call('page_upload', selector='#choose', mode='chooser', files=[self.file(name)])

    async def test_chooser_timeout_and_cancellation_leave_no_listener(self):
        await self.page.set_content('<button id=choose>不弹文件选择</button>')
        with self.assertRaises(TaskError) as error:
            await self.call('page_upload', selector='#choose', mode='chooser', files=[self.file()], timeout_ms=100)
        self.assertEqual(error.exception.code, 'BROWSER_TIMEOUT')
        self.assertEqual(len(self.page._impl_obj.listeners('filechooser')), 0)
        task = asyncio.create_task(self.call('page_upload', selector='#choose', mode='chooser', files=[self.file()]))
        for _ in range(100):
            if self.page._impl_obj.listeners('filechooser'):
                break
            await asyncio.sleep(.01)
        self.assertTrue(self.page._impl_obj.listeners('filechooser'))
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(len(self.page._impl_obj.listeners('filechooser')), 0)

    async def test_multiple_choosers_from_one_click_do_not_pick_arbitrarily(self):
        await self.page.set_content('''<input id=first type=file hidden><input id=second type=file hidden>
          <button id=choose onclick="document.querySelector('#first').click();document.querySelector('#second').click()">选择</button>''')
        with self.assertRaises(TaskError) as error:
            await self.call('page_upload', selector='#choose', mode='chooser', files=[self.file()])
        self.assertEqual(error.exception.code, 'UPLOAD_CHOOSER_AMBIGUOUS')
        self.assertEqual(await self.page.locator('#first').evaluate('e=>e.files.length'), 0)
        self.assertEqual(await self.page.locator('#second').evaluate('e=>e.files.length'), 0)
        self.assertEqual(len(self.page._impl_obj.listeners('filechooser')), 0)

    async def test_confirm_dismiss_and_prompt_accept_are_observed_not_assumed(self):
        await self.page.set_content('''<button id=confirm onclick="this.dataset.answer=String(confirm('是否提交？'))">确认</button>
          <button id=prompt onclick="this.dataset.answer=prompt('输入名称','默认')">输入</button>''')
        response = await self.call('page_dialog', selector='#confirm', dialogs=[{'type': 'confirm', 'message': '是否提交？', 'response': 'dismiss'}])
        self.assertEqual(response['handled'], [{'type': 'confirm', 'response': 'dismiss'}])
        self.assertEqual(await self.page.locator('#confirm').get_attribute('data-answer'), 'false')
        await self.call('page_dialog', selector='#prompt', dialogs=[{'type': 'prompt', 'message': '输入名称', 'response': 'accept', 'prompt_text': '人工指定'}])
        self.assertEqual(await self.page.locator('#prompt').get_attribute('data-answer'), '人工指定')
        self.assertEqual(len(self.page._impl_obj.listeners('dialog')), 0)

    async def test_multiple_dialogs_use_explicit_order_and_frame_trigger(self):
        await self.page.set_content('''<iframe id=frame srcdoc="&lt;button id=trigger onclick=&quot;alert('第一项');this.dataset.answer=String(confirm('第二项'))&quot;&gt;打开&lt;/button&gt;"></iframe>''')
        result = await self.call('page_dialog', selector={'kind': 'css', 'value': '#trigger', 'frame': '#frame'},
            dialogs=[{'type': 'alert', 'message': '第一项', 'response': 'accept'}, {'type': 'confirm', 'message': '第二项', 'response': 'accept'}])
        self.assertEqual(len(result['handled']), 2)
        self.assertEqual(await self.page.frame_locator('#frame').locator('#trigger').get_attribute('data-answer'), 'true')

    async def test_keyboard_and_double_click_dialog_triggers(self):
        await self.page.set_content('''<input id=key onkeydown="if(event.key==='Enter')alert('键盘确认')">
          <button id=double ondblclick="alert('双击确认')">双击</button>''')
        await self.call('page_dialog', selector='#key', trigger='press', key='Enter',
            dialogs=[{'type': 'alert', 'message': '键盘确认', 'response': 'accept'}])
        await self.call('page_dialog', selector='#double', trigger='double_click',
            dialogs=[{'type': 'alert', 'message': '双击确认', 'response': 'accept'}])

    async def test_beforeunload_can_cancel_then_allow_real_navigation(self):
        async def serve(reader, writer):
            request = await reader.readuntil(b'\r\n\r\n')
            destination = b'GET /destination ' in request
            html = b'finished' if destination else b'''<button id=activate onclick="window.onbeforeunload=e=>{e.preventDefault();e.returnValue=''}">activate</button><a id=leave href=/destination>leave</a>'''
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: ' + str(len(html)).encode() + b'\r\nConnection: close\r\n\r\n' + html)
            await writer.drain(); writer.close(); await writer.wait_closed()
        server = await asyncio.start_server(serve, '127.0.0.1', 0)
        url = 'http://127.0.0.1:' + str(server.sockets[0].getsockname()[1])
        try:
            await self.page.goto(url)
            await self.page.locator('#activate').click()
            await self.call('page_dialog', selector='#leave', dialogs=[{'type': 'beforeunload', 'message': '', 'response': 'dismiss'}])
            self.assertEqual(self.page.url, url + '/')
            await self.call('page_dialog', selector='#leave', dialogs=[{'type': 'beforeunload', 'message': '', 'response': 'accept'}])
            self.assertEqual(self.page.url, url + '/destination')
        finally:
            server.close(); await server.wait_closed()

    async def test_wrong_dialog_is_dismissed_without_accepting_business(self):
        await self.page.set_content('<button id=trigger onclick="this.dataset.answer=String(confirm(\'实际提示\'))">打开</button>')
        with self.assertRaises(TaskError) as error:
            await self.call('page_dialog', selector='#trigger', dialogs=[{'type': 'confirm', 'message': '不同提示', 'response': 'accept'}])
        self.assertEqual(error.exception.code, 'DIALOG_EXPECTATION_MISMATCH')
        self.assertEqual(await self.page.locator('#trigger').get_attribute('data-answer'), 'false')
        self.assertEqual(len(self.page._impl_obj.listeners('dialog')), 0)
        await self.page.locator('#trigger').click(timeout=1000)
        self.assertEqual(await self.page.locator('#trigger').get_attribute('data-answer'), 'false')

    async def test_unexpected_extra_dialog_is_never_automatically_accepted(self):
        await self.page.set_content('<button id=trigger onclick="alert(\'第一项\');this.dataset.answer=String(confirm(\'意外提交\'))">打开</button>')
        with self.assertRaises(TaskError) as error:
            await self.call('page_dialog', selector='#trigger', dialogs=[{'type': 'alert', 'message': '第一项', 'response': 'accept'}])
        self.assertEqual(error.exception.code, 'DIALOG_EXPECTATION_MISMATCH')
        self.assertEqual(await self.page.locator('#trigger').get_attribute('data-answer'), 'false')

    async def test_delayed_dialog_is_waited_and_missing_dialog_times_out(self):
        await self.page.set_content('<button id=trigger onclick="setTimeout(()=>alert(\'稍后显示\'),100)">打开</button><button id=none>无弹窗</button>')
        await self.call('page_dialog', selector='#trigger', dialogs=[{'type': 'alert', 'message': '稍后显示', 'response': 'accept'}], timeout_ms=2000)
        with self.assertRaises(TaskError) as error:
            await self.call('page_dialog', selector='#none', dialogs=[{'type': 'alert', 'message': '不存在', 'response': 'accept'}], timeout_ms=100)
        self.assertEqual(error.exception.code, 'BROWSER_TIMEOUT')
        self.assertEqual(len(self.page._impl_obj.listeners('dialog')), 0)

    async def test_dialog_cancellation_removes_handler_without_late_accept(self):
        await self.page.set_content('<button id=trigger onclick="this.dataset.started=1;setTimeout(()=>{this.dataset.answer=String(confirm(\'晚到确认\'))},300)">打开</button>')
        task = asyncio.create_task(self.call('page_dialog', selector='#trigger', dialogs=[{'type': 'confirm', 'message': '晚到确认', 'response': 'accept'}]))
        for _ in range(100):
            if self.page._impl_obj.listeners('dialog'):
                break
            await asyncio.sleep(.01)
        self.assertTrue(self.page._impl_obj.listeners('dialog'))
        await self.page.wait_for_function("document.querySelector('#trigger').dataset.started === '1'")
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(len(self.page._impl_obj.listeners('dialog')), 0)
        # A separate click after cancellation has Playwright's default dismiss,
        # never an accepting handler retained by the previous action.
        await self.page.locator('#trigger').click()
        await self.page.wait_for_function("document.querySelector('#trigger').dataset.answer === 'false'", timeout=1500)

    async def test_cancel_during_dialog_response_releases_the_open_dialog(self):
        from playwright.async_api import Dialog
        await self.page.set_content('<button id=trigger onclick="this.dataset.answer=String(confirm(\'中途取消\'))">打开</button>')
        responding = asyncio.Event()
        async def blocked_accept(dialog, prompt_text=None):
            responding.set()
            await asyncio.Event().wait()
        with patch.object(Dialog, 'accept', blocked_accept):
            task = asyncio.create_task(self.call('page_dialog', selector='#trigger', dialogs=[{'type': 'confirm', 'message': '中途取消', 'response': 'accept'}]))
            await asyncio.wait_for(responding.wait(), 2)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(len(self.page._impl_obj.listeners('dialog')), 0)
        self.assertEqual(await self.page.locator('#trigger').get_attribute('data-answer', timeout=1000), 'false')

    async def test_invalid_dialog_request_is_rejected_before_business_click(self):
        await self.page.set_content('<button id=trigger onclick="this.dataset.clicked=1">打开</button>')
        with self.assertRaises(TaskError):
            await self.call('page_dialog', selector='#trigger', dialogs=[{'type': 'confirm', 'message': '', 'response': 'accept', 'prompt_text': 'not-prompt'}])
        self.assertIsNone(await self.page.locator('#trigger').get_attribute('data-clicked'))
        for action in ['page_upload', 'page_dialog']:
            self.assertEqual(self.actions['playwright.' + action].spec.effect, 'WRITE')
            self.assertFalse(self.actions['playwright.' + action].spec.retry_safe)


class UploadFixturePage(BaseHTTPRequestHandler):
    def do_GET(self):
        html = '''<meta charset=utf-8><input type=file id=file hidden
          onchange="this.files[0].text().then(t=>document.querySelector('#content').textContent=t)">
          <pre id=content></pre><button id=confirm
          onclick="document.querySelector('#answer').textContent=String(confirm('接受临时文件？'))">确认</button><span id=answer></span>'''
        content = html.encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, *args):
        pass


class WorkerFileUploadTests(unittest.TestCase):
    def test_file_read_binding_upload_and_dialog_use_actual_worker_and_browser(self):
        from taskweave.application.service import Application
        from taskweave.infrastructure.storage import uid
        server = ThreadingHTTPServer(('127.0.0.1', 0), UploadFixturePage)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        text = '完整中文文件\n第二行：保留空格 与分号;'
        try:
            with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as root, Application(home) as app:
                Path(root, 'upload.txt').write_text(text, encoding='utf-8')
                for plugin in ('file', 'playwright'):
                    app.configure_plugin(plugin, True)
                task = app.repo.create_task('临时文件到浏览器', {'type': 'object', 'properties': {
                    'file_root': {'type': 'string', 'default': root},
                    'playwright_headless': {'type': 'boolean', 'default': True}}})['task_id']
                first = app.repo.save_step(task, {'name': '读取完整文件', 'capabilities': ['file.read'],
                    'step_content': 'async def run(ctx, inputs):\n    document = await ctx.call("file.read", {"path":"upload.txt", "format":"base64"})\n    return ctx.result(data=document)\n'})
                url = f'http://127.0.0.1:{server.server_port}/'
                source = f'''async def run(ctx, inputs):
    await ctx.call("playwright.page_open", {{"url": {url!r}}})
    result = await ctx.call("playwright.page_upload", {{"selector":"#file", "files":[{{"name":"upload.txt", "mime_type":"text/plain", "content_base64": inputs["document"]["content"]}}]}})
    await ctx.call("playwright.page_assert_text", {{"selector":"#content", "text": {text!r}}})
    await ctx.call("playwright.page_dialog", {{"selector":"#confirm", "dialogs":[{{"type":"confirm", "message":"接受临时文件？", "response":"accept"}}]}})
    await ctx.call("playwright.page_assert_text", {{"selector":"#answer", "text":"true"}})
    content = await ctx.call("playwright.page_text", {{"selector":"#content"}})
    return ctx.result(data={{"upload":result, "content":content["text"]}})
'''
                second = app.repo.save_step(task, {'name': '上传并核对文件',
                    'capabilities': ['playwright.page_open', 'playwright.page_upload', 'playwright.page_assert_text', 'playwright.page_dialog', 'playwright.page_text'],
                    'input_schema': {'type': 'object', 'properties': {'document': {'type': 'object'}}, 'required': ['document']},
                    'bindings': {'document': {'ref': {'source': 'step', 'step_id': first['step_id'], 'output': 'data', 'pointer': ''}}},
                    'step_content': source})
                for step in (first, second):
                    app.confirm_step_manual(step['step_id'], step['content_hash'])
                run = app.create_run(task)
                app.coordinator.start(run['run_id'], uid())
                done = app.coordinator.wait(run['run_id'])
                self.assertEqual(done['status'], 'SUCCEEDED', done['attempts'])
                output = app.repo.read_output(run['run_id'], second['step_id'])
                self.assertEqual(output['content'], text)
                self.assertEqual(output['upload']['total_bytes'], len(text.encode()))
                self.assertEqual(output['upload']['files'][0]['name'], 'upload.txt')
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
