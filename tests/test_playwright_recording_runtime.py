"""Local Chromium + real retained worker + storage/package recording path."""
import asyncio
import json
import socket
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from playwright.async_api import async_playwright
from taskweave.application.service import Application
from taskweave.infrastructure.storage import uid
from taskweave.plugins.registry import Registry
from taskweave_playwright import PlaywrightPlugin, BrowserSession, locate
from taskweave.desktop.contexts import ContextCaptureDraft
from taskweave.desktop.context_recording import RecordingDraft


class RecordingBrowser(BrowserSession):
    async def open(self, ctx, role):
        runtime = await async_playwright().start()
        browser = await runtime.chromium.launch(headless=True,
            args=['--remote-debugging-address=127.0.0.1',
                  '--remote-debugging-port='+str(ctx.task_parameters['recording_test_port'])])
        context = await browser.new_context()
        page = await context.new_page()
        return {'runtime':runtime,'browser':browser,'context':context,'page':page,'role':role}


class RecordingPlugin(PlaywrightPlugin):
    def resource_providers(self): return {'playwright.session':RecordingBrowser()}


def build_registry(): return Registry([RecordingPlugin()])


class LocalPage(BaseHTTPRequestHandler):
    def do_GET(self):
        content = '<fieldset id="open"><legend>开口保单</legend><label><input type=radio name=open>是</label><label><input type=radio name=open>否</label></fieldset><fieldset><legend>代出单</legend><label><input type=radio name=agent>否</label></fieldset><input id=password type=password>'
        if self.path == '/frame':
            content = '<button id="frame-confirm">框架确认</button>'
        elif self.path == '/complex':
            content += ''.join(f'<fieldset id="group-{index}"><legend>附加字段{index}</legend><label><input type=radio name="extra-{index}">否</label></fieldset>' for index in range(3))
            content += '''<button id="date" onclick="document.querySelector('#calendar').hidden=false">签署日期</button>
                <div id="calendar" hidden><a id="today" onclick="document.querySelector('#date').textContent='今天已选择'">今天</a></div>
                <button id="dropdown" onclick="document.querySelector('#choices').hidden=false">终止方式</button>
                <div id="choices" role="listbox" hidden><div id="natural" role="option">自然终止</div><div role="option">结清终止</div></div>
                <iframe id="subform" src="/frame"></iframe><a id="new-tab" href="/next" target="_blank">打开新页面</a>'''
        elif self.path == '/next':
            content = '<button id="next-confirm">新页面确认</button><a id="navigate" href="/final">进入最终页面</a>'
        elif self.path == '/final':
            content = '<button id="final-confirm">最终页面确认</button>'
        self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers()
        self.wfile.write(content.encode())
    def log_message(self,*args): pass


class RetainedBrowserRecordingTests(unittest.TestCase):
    def test_manual_target_persist_failure_retry_and_task_package(self):
        self._manual_target_persist_failure_retry_and_task_package()

    def test_independent_snapshot_then_recording_and_task_package(self):
        self._manual_target_persist_failure_retry_and_task_package(independent=True)

    def test_complex_page_recording_live_selectors_preview_and_package_roundtrip(self):
        self._manual_target_persist_failure_retry_and_task_package(independent=True, complex_page=True)

    def _manual_target_persist_failure_retry_and_task_package(self, independent=False, complex_page=False):
        server = ThreadingHTTPServer(('127.0.0.1',0),LocalPage)
        thread = threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        with socket.socket() as reserved:
            reserved.bind(('127.0.0.1',0)); port=reserved.getsockname()[1]
        try:
            with tempfile.TemporaryDirectory() as home, Application(home,registry_factory=f'{__name__}:build_registry') as app:
                task = app.repo.create_task('真实录制临时任务', {'type':'object','properties':{'recording_test_port':{'type':'integer','default':port}},'required':[]})
                url=f'http://127.0.0.1:{server.server_port}/' + ('complex' if complex_page else '')
                step = app.repo.save_step(task['task_id'], {'name':'页面快照兼容录制','capabilities':['playwright.page_open'],
                    'step_content':f'async def run(ctx, inputs):\n    await ctx.call("playwright.page_open", {{"url": {url!r}}})\n    return ctx.result(data={{}})\n'})
                params={'step_id':step['step_id'],'provider_id':'playwright.page'}
                if independent:
                    capture=app.dispatch('context.read',{**params,'request':{'url':url},'include_view':True})
                    self.assertTrue(capture['items']);self.assertTrue(capture['views'])
                    self.assertEqual(app.repo.list_runs(), [])
                else:
                    run = app.trial_step(step['step_id'], {}, uid())
                    done=app.coordinator.wait(run['run_id']);self.assertEqual(done['status'],'SUCCEEDED',done)
                    params['run_id']=run['run_id']
                targets=app.dispatch('context.targets',params)
                target=next(row for row in targets['targets'] if url in row['label'])
                async def scenario():
                    async def invoke(operation,**options):
                        return await asyncio.to_thread(app.dispatch,'context.record',{**params,'operation':operation,**options})
                    draft=ContextCaptureDraft();recording=RecordingDraft(draft,invoke,source_page='draft' if independent else 'debug',source_session_id=params.get('run_id'))
                    await recording.start({'request':target['request'],'expected_session_id':targets['session_id']},include_view=True)
                    # Drive the retained worker's actual page via a separate CDP
                    # connection. Events are browser-trusted, not fabricated JSON.
                    runtime=await async_playwright().start()
                    try:
                        remote=await runtime.chromium.connect_over_cdp(f'http://127.0.0.1:{port}')
                        page=next(page for context in remote.contexts for page in context.pages if page.url==url)
                        await page.locator('#open').get_by_label('否',exact=True).click()
                        await page.locator('#password').fill('never-store-this-password')
                        if complex_page:
                            for index in range(3):
                                await page.locator(f'#group-{index}').get_by_label('否', exact=True).click()
                            await page.locator('#date').click()
                            await page.locator('#dropdown').click()
                            snapshot = await asyncio.to_thread(app.dispatch, 'context.read', {
                                **params, 'request': target['request'], 'expected_session_id': targets['session_id'],
                                'include_view': False})
                            observed = json.loads(snapshot['items'][0]['content'])
                            for identifier in ('today', 'natural'):
                                element = next(el for el in observed['elements'] if el['id'] == identifier)
                                self.assertEqual(element['match_count'], 1)
                                self.assertEqual(await locate(page, element['preferred_selector']).count(), 1)
                            await page.locator('#today').click()
                            await page.locator('#natural').click()
                            await page.frame_locator('#subform').locator('#frame-confirm').click()
                            async with page.expect_popup() as popup_event:
                                await page.locator('#new-tab').click()
                            popup = await popup_event.value
                            await popup.locator('#next-confirm').click()
                            await popup.locator('#navigate').click()
                            await popup.locator('#final-confirm').click()
                        await asyncio.sleep(.1)
                        await recording.stage()
                    finally:
                        await runtime.stop()
                    entry=draft.entries[0];text=json.dumps(entry['capture'],ensure_ascii=False)
                    events = [event for item in entry['capture']['items'] if item.get('source') == 'playwright.recording'
                              for event in json.loads(item['content'])['events']]
                    clicks = [event for event in events if event['kind']=='operation' and event['action']=='click']
                    self.assertTrue(clicks)
                    self.assertEqual(clicks[0]['target']['field_group']['name'], '开口保单')
                    self.assertTrue(clicks[0]['target']['checked'])
                    if complex_page:
                        groups = {event['target'].get('field_group', {}).get('name') for event in clicks
                                  if event['target'].get('field_group')}
                        self.assertTrue({'开口保单', '附加字段0', '附加字段1', '附加字段2'} <= groups)
                        names = {event['captured_target']['name'] for event in clicks}
                        self.assertTrue({'今天', '自然终止', '框架确认', '新页面确认', '最终页面确认'} <= names)
                        self.assertTrue(any(event['target'].get('selector', {}).get('frame') == '#subform'
                                            for event in clicks if event['target'].get('selector')))
                        baselines = [event for event in events if event['kind'] == 'baseline']
                        # A fast navigation can invalidate an in-flight snapshot.
                        # Preserve the captured URL and explicit missing evidence,
                        # never assign the next document's DOM to the old one.
                        next_operations = [event for event in clicks if '/next' in event.get('document_url', '')]
                        self.assertTrue(next_operations)
                        next_documents = {event['document_id'] for event in next_operations}
                        self.assertTrue(any(event['document_id'] in next_documents and
                            ((event['kind'] == 'baseline' and '/next' in event['page']['url']) or
                             (event['kind'] == 'evidence_missing' and event['reason'] in
                              {'PAGE_DOCUMENT_CHANGED', 'PAGE_BASELINE_UNAVAILABLE'}))
                            for event in events if event['kind'] in {'baseline', 'evidence_missing'}))
                        self.assertTrue(any('/final' in event['page']['url'] for event in baselines))
                        self.assertGreaterEqual(len({event['target_id'] for event in baselines}), 2)
                    self.assertNotIn('never-store-this-password',text)
                    self.assertTrue(entry['capture']['views']);self.assertFalse(entry['send_preview'])
                    entry.update(label='选择开口保单',operation_notes='先选择否，再检查选中状态。')
                    if complex_page:
                        entry['send_preview'] = True
                    async def save():
                        return await asyncio.to_thread(app.dispatch,'context.save_batch',{
                            'step_id':step['step_id'],'context_id':None,'expected_revision':None,
                            'provider_id':'playwright.page','name':'人工操作上下文','context_notes':'临时录制证据',
                            'captures':draft.payload()})
                    with patch.object(app.contexts.contexts,'save_step_context_batch',side_effect=RuntimeError('临时保存失败')):
                        with self.assertRaises(RuntimeError):await recording.persist(save)
                    self.assertTrue(recording.pending)
                    self.assertEqual(app.repo.list_step_contexts(step['step_id']),[])
                    await recording.persist(save)
                    self.assertFalse(recording.pending)
                asyncio.run(scenario())
                saved=app.dispatch('context.list',{'step_id':step['step_id']})
                self.assertEqual(len(saved),1);self.assertEqual(saved[0]['captures'][0]['label'],'选择开口保单')
                original_capture = app.dispatch('context.capture.get', {'step_id':step['step_id'],
                    'context_id':saved[0]['context_id'],'capture_id':saved[0]['captures'][0]['capture_id']})
                package=app.export_task(task['task_id'])
                imported=app.import_task(package)
                imported_task=imported['task_id']
                imported_step=app.repo.steps(imported_task)[0]
                captures=app.dispatch('context.list',{'step_id':imported_step['step_id']})
                self.assertEqual(captures[0]['captures'][0]['operation_notes'],'先选择否，再检查选中状态。')
                self.assertEqual(captures[0]['captures'][0]['send_preview'], complex_page)
                restored = app.dispatch('context.capture.get',{'step_id':imported_step['step_id'],
                    'context_id':captures[0]['context_id'],'capture_id':captures[0]['captures'][0]['capture_id']})
                self.assertEqual(restored['items'], original_capture['items'])
                self.assertEqual(restored['views'], original_capture['views'])
                if independent:
                    self.assertEqual(app.repo.list_runs(), [])
                    self.assertTrue(app.dispatch('instance.end',{'instance_type':'step','owner_id':step['step_id']})['ended'])
        finally:
            server.shutdown();server.server_close();thread.join(timeout=2)
