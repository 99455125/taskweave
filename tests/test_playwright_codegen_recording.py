"""Real browser evidence is reusable after the recording browser is closed."""
import asyncio
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
from playwright.async_api import async_playwright
from taskweave.plugins.sdk import ContextRecordingCommand
from taskweave_playwright import PlaywrightPlugin, _live_context_targets


class FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers()
        self.wfile.write(b'''<input id="order"><input id="password" type="password"><input id="check" type="checkbox"><select id="select" size="2"><option>A</option><option>B</option></select><button id="search" onclick="document.querySelector('#result').textContent=document.querySelector('#order').value">Search</button><output id="result"></output>''')
    def log_message(self,*args): pass


class PlaywrightCodegenRecordingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server=ThreadingHTTPServer(('127.0.0.1',0),FixtureHandler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.runtime=await async_playwright().start();self.browser=await self.runtime.chromium.launch(headless=True)
        self.context=await self.browser.new_context();self.page=await self.context.new_page()
        self.url=f'http://127.0.0.1:{self.server.server_port}/orders'
        await self.page.goto(self.url)
        self.resource={'page':self.page,'context':self.context,'role':'operator'}
        self.ctx=SimpleNamespace(resources=SimpleNamespace(active=lambda _:[('operator',self.resource)],acquire=AsyncMock(return_value=self.resource)),environment={},task_parameters={})
        self.plugin=PlaywrightPlugin();self.request={'role':'operator','target_id':_live_context_targets(self.resource)[0][0]}
    async def asyncTearDown(self):
        if self.resource.get('context_recorder'): await self.resource['context_recorder'].close()
        await self.browser.close();await self.runtime.stop()
        await asyncio.to_thread(self.server.shutdown);self.server.server_close();self.thread.join()
    async def command(self,operation,**params):
        return await self.plugin.record_context('playwright.page',self.ctx,ContextRecordingCommand(operation,**params),self.request,include_view=False)
    async def stop_capture(self,key):
        await self.command('stop',recording_id=key)
        batch=await self.command('read',recording_id=key)
        data=json.loads(batch.collection.items[0].content)
        self.assertIn('codegen',data)
        return {'items':[{'source':'playwright.recording','content':json.dumps(data),'truncated':False}], 'request':self.request}

    async def test_fill_click_roundtrip_after_browser_closed_and_runtime_url_guard(self):
        key=(await self.command('start')).recording_id
        await self.page.locator('#order').fill('O-100')
        await self.page.locator('#search').click()
        capture=await self.stop_capture(key)
        codegen=json.loads(capture['items'][0]['content'])['codegen']
        self.assertTrue(codegen['complete'],codegen['issues'])
        self.assertEqual([a['operation'] for a in codegen['actions']],['fill','click'])
        await self.command('ack',recording_id=key,through=(await self.command('read',recording_id=key)).cursor)
        await self.browser.close()
        from taskweave.application.service import Application
        with tempfile.TemporaryDirectory() as home, Application(home,registry_factory='tests.test_local_codegen:build_registry') as app:
            task=app.repo.create_task('Persisted real recording')
            step=app.repo.save_step(task['task_id'],{'name':'Replay','capabilities':list(app.registry.actions),
                'input_schema':{'type':'object','properties':{'order_no':{'type':'string'}}}})
            app.contexts.save(step['step_id'],'playwright.page','Real recording','draft',capture['items'])
            source=app.dispatch('step.codegen.sources',{'step_id':step['step_id'],'document':step})[0]
            result=app.dispatch('step.codegen.generate',{'step_id':step['step_id'],'document':step,
                'generator_id':source['generator_id'],'context_id':source['context_id'],
                'capture_id':source['capture_id'],'expected_source_digest':source['source_digest'],
                'bindings':{'action:1:value':{'input':'order_no'}}})
        self.assertTrue(result['applicable'],result['diagnostics'])
        self.browser=await self.runtime.chromium.launch(headless=True)
        self.context=await self.browser.new_context()
        replay=await self.context.new_page();await replay.goto(self.url+'?fixture=yes')
        from taskweave_playwright.browser_actions import BrowserAction
        resource={'page':replay,'context':self.context}
        ctx=SimpleNamespace(resources=SimpleNamespace(acquire=AsyncMock(return_value=resource)),environment={},task_parameters={},scope=SimpleNamespace(task_id='t',run_id='r'),emit=lambda *args:None)
        calls=[]
        async def call(action,params):
            calls.append(action);return await self.plugin.actions()[action].execute(ctx,params)
        namespace={};exec(result['source'],namespace)
        await namespace['run'](SimpleNamespace(call=call,result=lambda **kwargs:kwargs),{'order_no':'REPLAY'})
        self.assertEqual(await replay.locator('#result').inner_text(),'REPLAY')
        self.assertNotIn('page_open',' '.join(calls))

    async def test_checkbox_select_and_input_change_are_normalized_once(self):
        key=(await self.command('start')).recording_id
        await self.page.locator('#order').fill('a');await self.page.locator('#order').fill('ab')
        await self.page.locator('#check').check();await self.page.locator('#select option').nth(1).click()
        capture=await self.stop_capture(key);data=json.loads(capture['items'][0]['content'])['codegen']
        self.assertEqual([a['operation'] for a in data['actions']],['fill','check','select'])
        self.assertEqual(data['actions'][0]['value'],'ab')
        self.assertTrue(data['complete'],data['issues'])

    async def test_password_pause_keyboard_and_navigation_never_claim_complete(self):
        key=(await self.command('start')).recording_id
        await self.page.locator('#password').fill('DO-NOT-PERSIST')
        await self.command('pause',recording_id=key);await self.command('resume',recording_id=key)
        await self.page.locator('#order').press('Enter')
        await self.page.goto(self.url+'?new-document=1')
        capture=await self.stop_capture(key);self.assertNotIn('DO-NOT-PERSIST',json.dumps(capture))
        data=json.loads(capture['items'][0]['content'])['codegen'];self.assertFalse(data['complete'])
        self.assertIn('PAUSED',data['issues']);self.assertIn('UNSUPPORTED_INTERACTION',data['issues'])
        self.assertFalse(self.plugin.generate_code('playwright.recording',capture,{}, {})['applicable'])

    async def test_scroll_is_a_missing_interaction_and_discard_stops_collection(self):
        await self.page.evaluate('''() => {const s=document.createElement('div');s.id='scroll';s.style='height:60px;overflow:auto';s.innerHTML='<div style="height:600px">rows</div>';document.body.append(s);}''')
        key=(await self.command('start')).recording_id
        await self.page.locator('#scroll').evaluate('(e)=>e.scrollTop=100')
        await self.page.wait_for_function('document.querySelector("#scroll").scrollTop === 100')
        await self.page.locator('#search').click()
        capture=await self.stop_capture(key)
        codegen=json.loads(capture['items'][0]['content'])['codegen']
        self.assertFalse(codegen['complete'])
        self.assertIn('UNSUPPORTED_INTERACTION',codegen['issues'])
        second=(await self.command('start')).recording_id
        await self.command('discard',recording_id=key)
        self.assertEqual(self.resource['context_recorder'].codegen.current['id'],second)
        await self.command('discard',recording_id=second)
        recorder=self.resource['context_recorder'].codegen
        self.assertIsNone(recorder.current)
        state=await self.page.evaluate('(ns)=>window[ns].recording_id',recorder.namespace)
        self.assertIsNone(state)

    async def test_discard_releases_active_codegen_recording_only(self):
        first=(await self.command('start')).recording_id
        await self.command('stop',recording_id=first)
        second=(await self.command('start')).recording_id
        await self.command('discard',recording_id=first)
        recorder=self.resource['context_recorder'].codegen
        self.assertEqual(recorder.current['id'],second)
        await self.command('discard',recording_id=second)
        self.assertIsNone(recorder.current)
        self.assertIsNone(await self.page.evaluate('(ns)=>window[ns].recording_id',recorder.namespace))

    async def test_new_url_on_fresh_session_reuses_its_initial_blank_main_page(self):
        await self.page.goto('about:blank')
        active=[]
        async def acquire(provider,role):
            if not active:active.append((role,self.resource))
            return self.resource
        self.ctx.resources.active=lambda _:active
        self.ctx.resources.acquire=AsyncMock(side_effect=acquire)
        self.request={'role':'operator','url':self.url}
        key=(await self.command('start')).recording_id
        self.assertEqual(len(self.context.pages),1,'Starting recording must not leave an unused blank tab')
        self.assertEqual(self.resource['page'].url,self.url)
        from taskweave.plugins.sdk import PluginError
        with self.assertRaises(PluginError):await self.command('start')
        self.assertEqual(len(self.context.pages),1,'Repeated start must not create a page before reporting busy')
        await self.page.locator('#order').fill('new-session')
        capture=await self.stop_capture(key)
        evidence=json.loads(capture['items'][0]['content'])['codegen']
        self.assertTrue(evidence['primary'])
        self.assertTrue(evidence['complete'],evidence['issues'])

    async def test_selected_existing_tab_records_and_replays_without_replacing_main(self):
        await self.page.evaluate('window.sessionMarker="preserved"')
        selected=await self.context.new_page();await selected.goto(self.url.replace('/orders','/selected'))
        target=next(key for key,page in _live_context_targets(self.resource) if page is selected)
        self.request={'role':'operator','target_id':target}
        key=(await self.command('start')).recording_id
        self.assertEqual(len(self.context.pages),2)
        await selected.locator('#order').fill('recorded')
        await selected.locator('#search').click()
        capture=await self.stop_capture(key)
        evidence=json.loads(capture['items'][0]['content'])['codegen']
        self.assertFalse(evidence['primary'])
        self.assertEqual(evidence['target_mode'],'selected')
        self.assertTrue(evidence['complete'],evidence['issues'])
        result=self.plugin.generate_code('playwright.recording',capture,{'action:1:value':{'input':'order_no'}},{})
        self.assertTrue(result['applicable'],result['diagnostics'])
        self.assertNotIn(target,result['source'])
        self.ctx.emit=lambda *args:None
        async def call(action,params):return await self.plugin.actions()[action].execute(self.ctx,params)
        namespace={};exec(result['source'],namespace)
        await namespace['run'](SimpleNamespace(call=call,result=lambda **kw:kw),{'order_no':'EXISTING'})
        self.assertEqual(await selected.locator('#result').inner_text(),'EXISTING')
        self.assertIs(self.resource['page'],self.page)
        self.assertEqual(await self.page.evaluate('window.sessionMarker'),'preserved')
        self.assertEqual(await self.page.locator('#order').input_value(),'')
        opened=self.plugin.generate_code('playwright.recording',capture,{'action:1:value':{'input':'order_no'}},
            {'start':'open','url':selected.url+'?replay=open'})
        self.assertTrue(opened['applicable'],opened['diagnostics'])
        open_namespace={};exec(opened['source'],open_namespace)
        await open_namespace['run'](SimpleNamespace(call=call,result=lambda **kw:kw),{'order_no':'OPENED'})
        self.assertEqual(await selected.locator('#result').inner_text(),'OPENED')
        self.assertEqual(await self.page.evaluate('window.sessionMarker'),'preserved')
        duplicate=await self.context.new_page();await duplicate.goto(selected.url)
        with self.assertRaisesRegex(ValueError,'唯一'):
            await namespace['run'](SimpleNamespace(call=call,result=lambda **kw:kw),{'order_no':'MUST-NOT-RUN'})
        self.assertEqual(await selected.locator('#order').input_value(),'OPENED')

    async def test_existing_session_with_unused_blank_main_reuses_it_for_recording(self):
        await self.page.goto('about:blank')
        self.request={'role':'operator','url':self.url}
        key=(await self.command('start')).recording_id
        self.assertEqual(len(self.context.pages),1)
        self.assertEqual(self.resource['page'].url,self.url)
        await self.page.locator('#order').fill('existing-empty-session')
        capture=await self.stop_capture(key)
        self.assertTrue(json.loads(capture['items'][0]['content'])['codegen']['primary'])

    async def test_blank_url_with_existing_dom_is_not_discarded_as_unused(self):
        await self.page.goto('about:blank')
        await self.page.set_content('<input id="draft" value="keep-unsaved">')
        self.request={'role':'operator','url':self.url}
        key=(await self.command('start')).recording_id
        self.assertEqual(len(self.context.pages),2)
        self.assertEqual(await self.page.locator('#draft').input_value(),'keep-unsaved')
        selected=self.context.pages[-1]
        await selected.locator('#order').fill('selected')
        capture=await self.stop_capture(key)
        evidence=json.loads(capture['items'][0]['content'])['codegen']
        self.assertEqual(evidence['target_mode'],'selected')
        self.assertTrue(evidence['complete'],evidence['issues'])


class CodegenOrderingTests(unittest.IsolatedAsyncioTestCase):
    async def test_frame_path_wait_does_not_reorder_subsequent_main_page_click(self):
        from unittest.mock import patch
        from taskweave_playwright.recording_codegen import CodegenRecording
        main=object();page=SimpleNamespace(main_frame=main)
        recorder=CodegenRecording({'context':None,'page':page})
        recorder.current={'id':'r','page':page,'actions':[],'issues':[],'receipts':{},'paused':False}
        entered,release=asyncio.Event(),asyncio.Event()
        async def frame_path(*args):entered.set();await release.wait();return ['iframe']
        first={'recording_id':'r','document_id':'frame','source_sequence':1,'operation':'fill',
               'selector':{'kind':'css','value':'#field'},'verified':True,'value':'value','value_state':'complete','element_id':'a'}
        second={**first,'document_id':'main','operation':'click','element_id':'b'}
        with patch('taskweave_playwright.observation.frame_path',side_effect=frame_path):
            one=asyncio.create_task(recorder.receive({'page':page,'frame':object()},first))
            await entered.wait()
            two=asyncio.create_task(recorder.receive({'page':page,'frame':main},second))
            await asyncio.sleep(0);release.set();await asyncio.gather(one,two)
        self.assertEqual([a['operation'] for a in recorder.current['actions']],['fill','click'])
