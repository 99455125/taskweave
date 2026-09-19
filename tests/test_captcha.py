import asyncio
import base64
import json
from io import BytesIO
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from taskweave.application.service import Application
from taskweave.core.validation import TaskError
from taskweave.infrastructure.storage import uid


def sample_image():
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new('RGB', (180, 75), 'white')
    font = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf', 52) if Path('/System/Library/Fonts/Supplemental/Arial.ttf').exists() else ImageFont.load_default(size=52)
    ImageDraw.Draw(image).text((15, 8), '1234', font=font, fill='black')
    buffer = BytesIO()
    image.save(buffer, 'PNG')
    return buffer.getvalue()


class CaptchaTests(unittest.TestCase):
    def test_bad_images_rejected_without_opening_engine(self):
        from taskweave_captcha import image_bytes
        for text in ['bad-base64!', '', base64.b64encode(b'not-an-image').decode()]:
            with self.assertRaises(TaskError):
                image_bytes(text)

    def test_actual_local_ocr_without_network(self):
        from taskweave_captcha import LocalOcr
        from types import SimpleNamespace
        async def recognize():
            resource = await LocalOcr().open(SimpleNamespace(environment={}, task_parameters={}), 'local')
            try:
                return await asyncio.get_running_loop().run_in_executor(resource['executor'], resource['engine'].classification, sample_image())
            finally:
                await LocalOcr().close(resource)
        with patch('socket.socket.connect', side_effect=AssertionError('OCR must stay offline')):
            self.assertEqual(asyncio.run(recognize()), '1234')

    def test_browser_image_to_ocr_and_login(self):
        image = sample_image()
        class Site(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/code.png':
                    data, kind = image, 'image/png'
                else:
                    data = b'''<html><body><label>Code<input id="code"></label><label>Password<input type="password" id="secret" value="never-forwarded"></label><img id="captcha" src="/code.png"><button onclick="if(document.querySelector('#code').value==='1234'){history.pushState({},'', '/home');document.title='Logged in';document.querySelector('#status').textContent='Welcome'}">Login</button><div id="status"></div></body></html>'''
                    kind = 'text/html'
                self.send_response(200); self.send_header('Content-Type',kind); self.end_headers(); self.wfile.write(data)
            def log_message(self,*args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1',0), Site)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as home, Application(home) as app:
                app.configure_plugin('playwright',True); app.configure_plugin('captcha',True)
                env=app.repo.save_environment('test',{'playwright_headless':True,'loginurl':f'http://127.0.0.1:{server.server_port}/'})['environment_id']
                task=app.repo.create_task('local OCR login')['task_id']
                source='''async def run(ctx, inputs):
    await ctx.call("playwright.page_open", {"url": inputs["loginurl"]})
    image = await ctx.call("playwright.page_element_image", {"selector": "#captcha"})
    code = await ctx.call("captcha.recognize", {"image_base64": image["image_base64"], "expected_length": 4})
    await ctx.call("playwright.page_fill", {"selector": "#code", "value": code["text"]})
    await ctx.call("playwright.page_click", {"selector": {"kind":"role", "value":"button", "name":"Login"}})
    await ctx.call("playwright.page_assert_url", {"url":"**/home"})
    await ctx.call("playwright.page_assert_title", {"text":"Logged in"})
    return ctx.result(data={"logged_in":True})
'''
                caps=['playwright.page_open','playwright.page_element_image','captcha.recognize','playwright.page_fill','playwright.page_click','playwright.page_assert_url','playwright.page_assert_title']
                step=app.repo.save_step(task, {'step_content':source,'capabilities':caps})
                run=app.trial_step(step['step_id'],{},uid(),env)
                result=app.coordinator.wait(run['run_id'], timeout=60)
                self.assertEqual(result['status'],'SUCCEEDED', result['attempts'])
                self.assertEqual(app.repo.read_output(run['run_id'],step['step_id']),{'logged_in':True})
                contexts = app.dispatch('context.read', {'step_id':step['step_id'], 'provider_id':'playwright.page', 'run_id':run['run_id']})
                data = json.loads(contexts[0]['content'])
                elements = {item['id']:item for item in data['elements']}
                self.assertEqual(elements['captcha']['selector'], {'kind':'css','value':'#captcha'})
                self.assertEqual(elements['secret']['type'], 'password')
                self.assertNotIn('never-forwarded', contexts[0]['content'])
        finally:
            server.shutdown(); server.server_close(); thread.join()
