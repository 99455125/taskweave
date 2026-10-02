"""Real Chromium manual-operation evidence; no external websites or user data."""
import asyncio,json,unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from playwright.async_api import async_playwright
from taskweave.plugins.sdk import ContextRecordingCommand
from taskweave.core.validation import TaskError
from taskweave_playwright import PlaywrightPlugin, _live_context_targets, locate

class PlaywrightRecordingTests(unittest.IsolatedAsyncioTestCase):
    async def test_after_state_does_not_use_recycled_token_from_new_document(self):
        from taskweave_playwright.recording import Recording, Recorder
        recorder = Recorder(self.resource)
        await recorder.install()
        old_document = await self.page.evaluate('(ns)=>window[ns].document_id', recorder.namespace)
        self.assertIsInstance(old_document, str)
        recording = Recording(self.page, [self.page])
        recorder.active = recording
        try:
            await self.page.goto('data:text/html,<button id=replacement>另一个页面</button>')
            await self.page.evaluate('(ns)=>window[ns].elements.set("1",document.querySelector("button"))', recorder.namespace)
            await recorder.receive({'page': self.page, 'frame': self.page.main_frame}, {
                'kind': 'operation', 'action': 'click', 'document_id': old_document,
                'token': '1', 'target': {'name': '原按钮', 'selector': {'kind': 'css', 'value': '#plain'}},
            })
            operation = recording.events[-1][0]
            self.assertFalse(operation['after_state_available'])
            self.assertEqual(operation['target']['name'], '原按钮')
            self.assertIsNone(operation['target']['selector'])
        finally:
            await recorder.close()

    async def test_baseline_does_not_label_a_new_document_as_the_old_document(self):
        from unittest.mock import patch
        from taskweave_playwright.recording import Recording, Recorder
        recorder = Recorder(self.resource)
        await recorder.install()
        recording = Recording(self.page, [self.page])
        old_document = await self.page.evaluate('(ns)=>window[ns].document_id', recorder.namespace)
        self.assertIsInstance(old_document, str)
        entered, release = asyncio.Event(), asyncio.Event()
        from taskweave_playwright import snapshot
        async def delayed_snapshot(page, **kwargs):
            entered.set()
            await release.wait()
            return await snapshot(page, **kwargs)
        try:
            with patch('taskweave_playwright.snapshot', side_effect=delayed_snapshot):
                pending = asyncio.create_task(recorder.baseline(recording, self.page, old_document))
                await entered.wait()
                await self.page.goto('data:text/html,<button>另一个页面</button>')
                release.set()
                await pending
            entries = [entry for entry, _ in recording.events]
            self.assertFalse(any(entry['kind'] == 'baseline' for entry in entries))
            self.assertEqual(entries[0]['reason'], 'PAGE_DOCUMENT_CHANGED')
            self.assertEqual(entries[0]['document_id'], old_document)
        finally:
            release.set()
            await recorder.close()

    async def asyncSetUp(self):
        self.runtime=await async_playwright().start()
        self.browser=await self.runtime.chromium.launch(headless=True)
        self.context=await self.browser.new_context()
        self.page=await self.context.new_page()
        await self.page.set_content('''<fieldset id="open"><legend>开口保单</legend><label><input type=radio name=open>是</label><label><input type=radio name=open>否</label></fieldset><fieldset id="agent"><legend>代出单</legend><label><input type=radio name=agent>是</label><label><input type=radio name=agent>否</label></fieldset><input id=account><input id=password type=password><button id=plain>按钮</button>''')
        self.resource={'context':self.context,'page':self.page}
        self.ctx=SimpleNamespace(resources=SimpleNamespace(acquire=AsyncMock(return_value=self.resource),active=lambda name:[('operator',self.resource)]),environment={},task_parameters={},scope=SimpleNamespace(task_id='t',run_id='r'))
        self.plugin=PlaywrightPlugin()
        self.target=_live_context_targets(self.resource)[0][0]
        self.request={'role':'operator','target_id':self.target}
    async def asyncTearDown(self):
        if self.resource.get('context_recorder'):
            await self.resource['context_recorder'].close()
        await self.browser.close();await self.runtime.stop()
    async def command(self, operation, **params):
        return await self.plugin.record_context('playwright.page',self.ctx,ContextRecordingCommand(operation,**params),self.request,include_view=False)
    async def events(self, recording_id):
        batch=await self.command('read',recording_id=recording_id)
        return batch,json.loads(batch.collection.items[0].content)['events']
    async def test_selected_target_in_nondefault_role_survives_target_close(self):
        self.ctx.resources.active=lambda name:[('secondary',self.resource)]
        self.request={'target_id':self.target}
        started=await self.command('start')
        await self.page.locator('#plain').click()
        _,captured=await self.events(started.recording_id)
        self.assertTrue(any(event['kind']=='operation' for event in captured))
        await self.page.close()
        await self.command('stop',recording_id=started.recording_id)
        batch,events=await self.events(started.recording_id)
        self.assertTrue(any(event['kind']=='operation' for event in events))
        await self.command('ack',recording_id=started.recording_id,through=batch.cursor)

    async def test_real_target_field_group_input_redaction_and_repeat_read(self):
        start=await self.command('start');key=start.recording_id
        await self.page.locator('#open').get_by_label('否',exact=True).click()
        await self.page.locator('#account').fill('temporary-user')
        await self.page.locator('#password').fill('private-password-value')
        await self.command('stop',recording_id=key)
        batch,events=await self.events(key)
        clicks=[e for e in events if e['kind']=='operation' and e['action']=='click']
        self.assertTrue(clicks)
        target=clicks[0]['target']
        self.assertEqual(target['field_group']['name'],'开口保单')
        self.assertTrue(target['checked'])
        self.assertEqual(await locate(self.page,target['selector']).count(),1)
        self.assertTrue(any(e['kind']=='baseline' for e in events))
        self.assertNotIn('private-password-value',batch.collection.items[0].content)
        self.assertIn('redacted',batch.collection.items[0].content)
        self.assertEqual(batch,(await self.events(key))[0])
        with self.assertRaises(TaskError):await self.command('ack',recording_id=key,through=batch.cursor+1)
        await self.command('ack',recording_id=key,through=batch.cursor)
        _,remaining=await self.events(key);self.assertEqual(remaining,[])
    async def test_pause_resume_stop_and_untrusted_events(self):
        start=await self.command('start');key=start.recording_id
        await self.command('pause',recording_id=key)
        await self.page.locator('#plain').click()
        await self.command('resume',recording_id=key)
        await self.page.locator('#plain').evaluate('e=>e.click()')
        await self.page.locator('#plain').click()
        await self.command('stop',recording_id=key)
        _,before=await self.events(key)
        self.assertEqual(len([e for e in before if e['kind']=='operation']),1)
        await self.page.locator('#plain').click()
        _,after=await self.events(key);self.assertEqual(before,after)
    async def test_new_page_and_nested_frame_keep_target_identity(self):
        start=await self.command('start');key=start.recording_id
        popup=await self.context.new_page()
        await popup.set_content('<iframe id=frame srcdoc="&lt;button id=confirm&gt;确认&lt;/button&gt;"></iframe>')
        await popup.frame_locator('#frame').locator('#confirm').click()
        await self.command('stop',recording_id=key)
        _,events=await self.events(key)
        clicks=[e for e in events if e['kind']=='operation']
        self.assertTrue(clicks)
        target=clicks[-1]['target'];self.assertEqual(target['selector']['frame'],'#frame')
        self.assertEqual(await locate(popup,target['selector']).count(),1)
        popup_id=next(key for key,page in _live_context_targets(self.resource) if page is popup)
        self.assertEqual(clicks[-1]['target_id'],popup_id)

    async def test_finished_receipts_do_not_exhaust_pending_budget(self):
        for _ in range(17):
            started = await self.command('start')
            await self.command('stop', recording_id=started.recording_id)
            batch, _ = await self.events(started.recording_id)
            await self.command('ack', recording_id=started.recording_id, through=batch.cursor)
            await self.command('ack', recording_id=started.recording_id, through=batch.cursor)

    async def test_capture_and_after_state_are_distinct_and_buffer_is_bounded(self):
        from taskweave_playwright.recording import Recording, MAX_EVENTS, MAX_BUFFER_BYTES
        started = await self.command('start')
        await self.page.locator('#plain').evaluate("e=>e.addEventListener('click',()=>e.textContent='更新后')")
        await self.page.locator('#plain').click()
        await self.command('stop', recording_id=started.recording_id)
        _, events = await self.events(started.recording_id)
        event = next(entry for entry in events if entry['kind'] == 'operation')
        self.assertEqual(event['captured_target']['name'], '按钮')
        self.assertEqual(event['target']['name'], '更新后')
        recording = Recording(self.page, [self.page])
        for index in range(MAX_EVENTS + 20):
            recording.append({'kind':'operation','value':str(index)})
        self.assertEqual(len(recording.events), MAX_EVENTS)
        self.assertEqual(recording.dropped, 20)
        self.assertEqual(recording.available_after, 20)
        self.assertLessEqual(recording.bytes, MAX_BUFFER_BYTES)

    async def test_preview_is_optional_and_uses_existing_renderer(self):
        started = await self.command('start')
        await self.command('stop', recording_id=started.recording_id)
        plain, _ = await self.events(started.recording_id)
        self.assertEqual(plain.collection.views, ())
        preview = await self.plugin.record_context('playwright.page', self.ctx,
            ContextRecordingCommand('read', recording_id=started.recording_id), self.request, include_view=True)
        self.assertEqual(preview.collection.views[0].renderer, 'playwright.screenshot')

    async def test_oversized_preview_has_explicit_missing_evidence(self):
        from unittest.mock import patch
        started = await self.command('start')
        await self.command('stop', recording_id=started.recording_id)
        with patch.object(self.page, 'screenshot', AsyncMock(return_value=b'x' * (512 * 1024 + 1))):
            batch = await self.plugin.record_context('playwright.page', self.ctx,
                ContextRecordingCommand('read', recording_id=started.recording_id), self.request, include_view=True)
        self.assertEqual(batch.collection.views, ())
        self.assertEqual(json.loads(batch.collection.items[0].content)['preview_status'], 'IMAGE_TOO_LARGE')
