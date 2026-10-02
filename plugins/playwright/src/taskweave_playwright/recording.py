"""Optional manual evidence recorder, scoped to one retained browser context.

No execution or automatic replay. The browser sends trusted operations only;
reads are repeatable and acknowledgment is separate from collecting evidence.
"""
import asyncio
import base64
import json
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from playwright.async_api import Error
from taskweave.plugins.sdk import ContextCollection, ContextItem, ContextView, ContextRecordingBatch, PluginError
from .observation import DESCRIBE_JS, attach_frame, frame_path
from .protocol import reply

MAX_EVENTS = 1000
MAX_BUFFER_BYTES = 2 * 1024 * 1024
MAX_EVENT_BYTES = 128 * 1024
MAX_READ_BYTES = 192 * 1024


def now():
    return datetime.now(timezone.utc).isoformat()


class Recording:
    def __init__(self, page, pages):
        self.id = uuid.uuid4().hex
        self.page = page
        self.pages = {page}
        self.previous_pages = set(pages)
        self.state = 'RECORDING'
        self.events = []
        self.sequence = self.available_after = self.dropped = self.delivered = self.bytes = 0
        self.documents = set()

    def append(self, entry):
        self.sequence += 1
        entry = dict(entry, sequence=self.sequence)
        size = len(json.dumps(entry, ensure_ascii=False).encode('utf-8'))
        if size > MAX_EVENT_BYTES:
            entry = {'kind': 'evidence_missing', 'sequence': self.sequence,
                     'reason': 'EVENT_TOO_LARGE', 'created_at': now()}
            size = len(json.dumps(entry).encode('utf-8'))
        self.events.append((entry, size))
        self.bytes += size
        while len(self.events) > MAX_EVENTS or self.bytes > MAX_BUFFER_BYTES:
            old, amount = self.events.pop(0)
            self.bytes -= amount
            self.available_after = old['sequence']
            self.dropped += 1


class Recorder:
    def __init__(self, resource):
        self.resource = resource
        self.context = resource['context']
        self.binding = '__tw_record_' + uuid.uuid4().hex
        self.namespace = '__tw_evidence_' + uuid.uuid4().hex
        self.recordings = {}
        self.active = None
        self.tasks = set()
        self.closed = False
        self.receive_lock = asyncio.Lock()
        self.finished = []
        self.script = self._script()

    def _script(self):
        # Never send raw event objects, HTML, cookies or keyboard text. Value
        # redaction happens in the browser before crossing the binding.
        return '(() => {' + DESCRIBE_JS + r'''
const ns=NS, binding=BINDING;
if(window[ns])return;
const pending=new Set(), elements=new Map();let serial=0;
window[ns]={elements,flush:async()=>{while(pending.size)await Promise.allSettled(Array.from(pending));}};
for(const action of ['click','input','change'])document.addEventListener(action,event=>{
  if(!event.isTrusted)return;
  const actual=event.composedPath()[0];if(!(actual instanceof Element))return;
  let target=actual.closest('input,textarea,select,button,a,[role],label')||actual;
  if(target.localName==='label'&&target.control)target=target.control;
  const token=String(++serial);elements.set(token,target);
  const payload={kind:'operation',action,target:describe(target,true),actual_target:describe(actual,false),token,
    created_at:new Date().toISOString(),document_id:window[ns].document_id,
    document_url:location.origin==='null'?location.protocol:location.origin+location.pathname,
    document_title:document.title.slice(0,240)};
  const promise=window[binding](payload).catch(()=>{}).finally(()=>{pending.delete(promise);elements.delete(token);});
  pending.add(promise);
},true);
window[ns].document_id=crypto.randomUUID?.()||Array.from(crypto.getRandomValues(new Uint8Array(16)),v=>v.toString(16).padStart(2,'0')).join('');
})();'''.replace('NS', json.dumps(self.namespace)).replace('BINDING', json.dumps(self.binding))

    async def install(self):
        await self.context.expose_binding(self.binding, self.receive)
        await self.context.add_init_script(self.script)
        self.context.on('page', self.watch_page)
        for page in self.context.pages:
            self.watch_page(page)
        await self.drain_tasks()

    def watch_page(self, page):
        if self.closed:
            return
        page.on('framenavigated', self.watch_frame)
        for frame in page.frames:
            self.watch_frame(frame)

    def watch_frame(self, frame):
        if not self.closed:
            task = asyncio.create_task(self.inject(frame))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)

    async def inject(self, frame):
        try:
            await frame.evaluate(self.script)
        except Error:
            # Navigation/closed frames are not evidence of an operation.
            pass

    async def drain_tasks(self):
        while self.tasks:
            await asyncio.gather(*tuple(self.tasks), return_exceptions=True)

    async def flush(self):
        await self.drain_tasks()
        for page in tuple(self.context.pages):
            for frame in tuple(page.frames):
                try:
                    await frame.evaluate('(ns)=>window[ns]?.flush()', self.namespace)
                except Error:
                    pass

    def accepts(self, recording, page):
        if page in recording.pages:
            return True
        if page not in recording.previous_pages:
            recording.pages.add(page)
            return True
        return False

    def target_id(self, page):
        from . import _live_context_targets
        return next((key for key, candidate in _live_context_targets(self.resource) if candidate is page), None)

    async def baseline(self, recording, page, document_id, *, timing="first_operation_observation",
                       frame=None, document_url=None):
        from . import snapshot
        identity = (page, document_id)
        if identity in recording.documents:
            return
        recording.documents.add(identity)
        frame = frame or page.main_frame
        def missing(reason):
            recording.append({'kind': 'evidence_missing', 'target_id': self.target_id(page),
                              'document_id': document_id, 'document_url': document_url,
                              'reason': reason, 'created_at': now()})
        async def same_document():
            return await reply(frame.evaluate('(ns)=>window[ns]?.document_id', self.namespace)) == document_id
        try:
            if not await same_document():
                missing('PAGE_DOCUMENT_CHANGED')
                return
            data = await snapshot(page, scope='viewport')
            if not await same_document():
                missing('PAGE_DOCUMENT_CHANGED')
                return
            parsed = urlparse(data.get('url', page.url))
            data['url'] = parsed._replace(netloc=parsed.netloc.rsplit('@', 1)[-1], query='', fragment='').geturl()
            recording.append({'kind': 'baseline', 'target_id': self.target_id(page),
                              'document_id': document_id, 'created_at': now(), 'observation_timing': timing, 'page': data})
        except Error:
            missing('PAGE_BASELINE_UNAVAILABLE')

    async def receive(self, source, payload):
        recording = self.active
        page, frame = source['page'], source['frame']
        if not recording or recording.state != 'RECORDING' or not self.accepts(recording, page):
            return
        if not isinstance(payload, dict) or payload.get('action') not in {'click', 'input', 'change'}:
            return
        # Serialize callbacks to preserve baseline-before-operation ordering.
        async with self.receive_lock:
            await self.baseline(recording, page, payload.get('document_id'), frame=frame,
                                document_url=payload.get('document_url'))
            target = payload['target']
            payload['captured_target'] = json.loads(json.dumps(target))
            token = payload.pop('token')
            try:
                # Verify the actual captured element identity, not merely a CSS
                # path that may now point at a replacement DOM node.
                observed = await frame.evaluate('args=>{' + DESCRIBE_JS + '''
const e=window[args.ns]?.elements.get(args.token);
if(window[args.ns]?.document_id!==args.document_id||!e||!e.isConnected)return null;
return describe(e,true);
}''', {'ns': self.namespace, 'token': token, 'document_id': payload.get('document_id')})
                if observed:
                    target = observed
                    css = target['css_selector']
                    match = await frame.locator(css).evaluate_all(
                        '(els,args)=>({count:els.length,same:els.length===1&&els[0]===window[args.ns]?.elements.get(args.token)})',
                        {'ns': self.namespace, 'token': token})
                    target['selector'] = {'kind': 'css', 'value': css} if match['same'] else None
                    target['match_count'] = match['count']
                    target['candidate_selectors'] = [{'selector': {'kind': 'css', 'value': css},
                                                       'match_count': match['count'], 'matches_element': match['same']}]
                else:
                    target['selector'] = None
                    target['candidate_selectors'] = []
                chain = await frame_path(page, frame)
                if frame != page.main_frame and chain is None:
                    target['selector'] = None
                    target['candidate_selectors'] = []
                attach_frame(target, chain)
                payload['after_state_available'] = observed is not None
            except Error:
                target['selector'] = None
                target['candidate_selectors'] = []
                payload['after_state_available'] = False
            payload['target'] = target
            payload['target_id'] = self.target_id(page)
            recording.append(payload)

    async def command(self, command, page=None, *, include_view=False):
        await self.flush()
        if command.operation == 'start':
            pending = sum(key not in self.finished for key in self.recordings)
            if self.active or pending >= 16:
                raise PluginError('CONTEXT_RECORDING_BUSY', 'Finish or discard the existing recording first')
            recording = Recording(page, self.context.pages)
            self.recordings[recording.id] = recording
            document_id = await page.evaluate('(ns)=>window[ns]?.document_id', self.namespace)
            await self.baseline(recording, page, document_id, timing="recording_start")
            self.active = recording
        else:
            recording = self.recordings.get(command.recording_id)
            if recording is None:
                raise PluginError('CONTEXT_RECORDING_UNAVAILABLE')
            operation = command.operation
            if operation in {'pause', 'resume', 'stop'}:
                if recording.state in {'STOPPED', 'DISCARDED'}:
                    if operation != 'stop' or recording.state != 'STOPPED':
                        raise PluginError('CONTEXT_RECORDING_STATE_INVALID')
                else:
                    recording.state = {'pause': 'PAUSED', 'resume': 'RECORDING', 'stop': 'STOPPED'}[operation]
                    if operation == 'stop':
                        self.active = None
            elif operation == 'ack':
                if command.through > recording.delivered:
                    raise PluginError('CONTEXT_RECORDING_ACK_INVALID', 'Cannot acknowledge unread evidence')
                recording.events = [(entry, size) for entry, size in recording.events if entry['sequence'] > command.through]
                recording.bytes = sum(size for _, size in recording.events)
                recording.available_after = max(recording.available_after, command.through)
                if recording.state == 'STOPPED' and command.through == recording.sequence:
                    # Retain the receipt for duplicate acknowledgement retries,
                    # but it no longer occupies the pending recording budget.
                    self.remember_finished(recording.id)
            elif operation == 'discard':
                recording.events = []
                recording.bytes = 0
                recording.available_after = recording.sequence
                recording.state = 'DISCARDED'
                self.remember_finished(recording.id)
                if self.active is recording:
                    self.active = None
        entries, views, more = [], (), False
        cursor = recording.sequence
        preview_status = None
        if command.operation == 'read':
            if command.after > recording.sequence:
                raise PluginError('CONTEXT_RECORDING_CURSOR_INVALID')
            cursor = max(command.after, recording.available_after)
            size = 0
            for entry, amount in recording.events:
                if entry['sequence'] <= cursor:
                    continue
                if len(entries) >= command.limit or size + amount > MAX_READ_BYTES:
                    more = True
                    break
                entries.append(entry)
                size += amount
            if entries:
                cursor = entries[-1]['sequence']
            recording.delivered = max(recording.delivered, cursor)
            if include_view and recording.page.is_closed():
                preview_status = 'PAGE_CLOSED'
            elif include_view:
                image = await recording.page.screenshot(type='png', full_page=False)
                preview_status = 'AVAILABLE' if len(image) <= 512 * 1024 else 'IMAGE_TOO_LARGE'
                if len(image) <= 512 * 1024:
                    views = (ContextView('读取时页面预览（非每次操作截图）', 'playwright.screenshot',
                              {'image_base64': base64.b64encode(image).decode('ascii'), 'mime_type': 'image/png'}),)
        collection = ContextCollection((ContextItem('text', 'application/json', json.dumps(
            {'recording_id': recording.id, 'events': entries,
             **({'preview_status': preview_status} if preview_status is not None else {})}, ensure_ascii=False), 'playwright.recording',
            truncated=recording.dropped > 0),), views)
        return ContextRecordingBatch(recording.id, recording.state, cursor, collection,
                                     recording.available_after, recording.dropped, more)

    def remember_finished(self, recording_id):
        if recording_id not in self.finished:
            self.finished.append(recording_id)
        if len(self.finished) > 64:
            self.recordings.pop(self.finished.pop(0), None)

    async def close(self):
        self.closed = True
        self.active = None
        self.context.remove_listener('page', self.watch_page)
        for page in self.context.pages:
            page.remove_listener('framenavigated', self.watch_frame)
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*tuple(self.tasks), return_exceptions=True)


async def record(resource, page, command, *, include_view):
    recorder = resource.get('context_recorder')
    if recorder is None:
        recorder = Recorder(resource)
        await recorder.install()
        resource['context_recorder'] = recorder
    return await recorder.command(command, page, include_view=include_view)
