"""Additional code-generation evidence on the existing context recording lifecycle."""
import asyncio
from copy import deepcopy
import json
from urllib.parse import urlsplit
from uuid import uuid4
from playwright.async_api import Error
from .observation import DESCRIBE_JS

# Raw values are reduced/redacted inside the page before the host binding is called.
SCRIPT = r'''
(() => {
DESCRIBE
const ns=NAMESPACE, binding=BINDING;
if(window[ns])return;
const s={document_id:crypto.randomUUID?.()||Array.from(crypto.getRandomValues(new Uint8Array(16)),x=>x.toString(16)).join(''),
 recording_id:null,sent:0,acknowledged:0,failed:false,pending:new Set(),tokens:new WeakMap(),serial:0};
window[ns]=s;
s.start=id=>{s.recording_id=id;s.sent=s.acknowledged=0;s.failed=false;s.tokens=new WeakMap();s.serial=0;};
s.flush=async()=>{while(s.pending.size)await Promise.allSettled([...s.pending]);return {document_id:s.document_id,sent:s.sent,acknowledged:s.acknowledged,failed:s.failed};};
s.stop=async()=>{s.recording_id=null;return await s.flush();};
function send(operation,e,event){
 if(!s.recording_id)return;
 const sequence=++s.sent;
 let payload={recording_id:s.recording_id,document_id:s.document_id,source_sequence:sequence,operation};
 if(e){
  let target=describe(e,true),selector={kind:'css',value:target.css_selector};
  let verified=false;try{const found=document.querySelectorAll(target.css_selector);verified=found.length===1&&found[0]===e;}catch(_){}
  if(!s.tokens.has(e))s.tokens.set(e,String(++s.serial));
  payload={...payload,selector,verified,element_id:s.tokens.get(e),
   value_state:target.value_redacted?'redacted':target.value_truncated?'truncated':typeof target.value==='string'?'complete':'missing',
   ...(typeof target.value==='string'&&!target.value_redacted&&!target.value_truncated?{value:target.value}:{}),
   ...(typeof target.checked==='boolean'&&!target.mixed?{checked:target.checked}:{})};
 }
 const promise=window[binding](payload).then(ok=>{if(ok===true)s.acknowledged++;else s.failed=true;}).catch(()=>{s.failed=true;}).finally(()=>s.pending.delete(promise));
 s.pending.add(promise);
}
for(const name of ['click','input','change','keydown','dblclick','dragstart','drop','contextmenu','wheel','scroll'])document.addEventListener(name,event=>{
 if(!event.isTrusted||!s.recording_id)return;
 let e=event.composedPath()[0];if(!(e instanceof Element)){send('unsupported');return;}
 if(name==='keydown'){
  const text=e.matches('input:not([type=checkbox]):not([type=radio]):not([type=file]),textarea');
  if(text&&!event.ctrlKey&&!event.metaKey&&!event.altKey&&(event.key.length===1||['Backspace','Delete','ArrowLeft','ArrowRight','Home','End','Shift'].includes(event.key)))return;
  send('unsupported');return;
 }
 if(['dblclick','dragstart','drop','contextmenu','wheel','scroll'].includes(name)||event.ctrlKey||event.metaKey||event.altKey){send('unsupported');return;}
 let target=e.closest('input,textarea,select,button,a,[role],label')||e;
 if(target.localName==='label'&&target.control)target=target.control;
 const checkable=target.matches('input[type=checkbox],input[type=radio]');
 if(name==='click'){
  if(checkable||target.localName==='select')return;
  send('click',target,event);return;
 }
 if(checkable){send('check',target,event);return;}
 if(target.localName==='select'){
  if(target.multiple){send('unsupported');return;}
  send('select',target,event);return;
 }
 if(target.matches('input:not([type=file]),textarea'))send('fill',target,event);else send('unsupported');
},true);
})();
'''


class CodegenRecording:
    def __init__(self, resource):
        self.resource=resource;self.context=resource['context'];self.namespace='__tw_codegen_'+uuid4().hex
        self.binding=self.namespace+'_send';self.current=None;self.records={};self.documents={}
        self.tasks=set();self.closed=False
        self.receive_lock=asyncio.Lock()

    async def install(self):
        await self.context.expose_binding(self.binding,self.receive)
        self.script=SCRIPT.replace('DESCRIBE',DESCRIBE_JS).replace('NAMESPACE',json.dumps(self.namespace)).replace('BINDING',json.dumps(self.binding))
        await self.context.add_init_script(self.script)
        self.context.on('page',self.watch_page)
        for page in self.context.pages:self.watch_page(page)
        if self.tasks:await asyncio.gather(*tuple(self.tasks))

    def watch_page(self,page):
        if self.current and page is not self.current['page']:
            self.issue('EXTRA_PAGE')
        page.on('framenavigated',self.watch_frame)
        for frame in page.frames:self.watch_frame(frame)

    def watch_frame(self,frame):
        if not self.closed:
            task=asyncio.create_task(self.inject(frame));self.tasks.add(task);task.add_done_callback(self.tasks.discard)

    async def inject(self,frame):
        try:
            await frame.evaluate(self.script)
            if self.current and frame.page is self.current['page']:
                document=await frame.evaluate('(ns)=>window[ns].document_id',self.namespace)
                if frame in self.documents and self.documents[frame]!=document:
                    self.issue('DOCUMENT_UNSEALED')
                self.documents[frame]=document
                self.current['receipts'].setdefault(document,{'document_id':document,'sent':0,'acknowledged':0,'sealed':False})
                await frame.evaluate('(a)=>window[a.ns].start(a.id)',{'ns':self.namespace,'id':self.current['id']})
        except Error:
            if self.current:self.issue('FRAME_UNAVAILABLE')

    def issue(self,name):
        if self.current and name not in self.current['issues']:
            self.current['issues'].append(name)

    async def start(self,key,page,role):
        self.current={'id':key,'page':page,'role':role,'primary':page is self.resource['page'],
                      'target_mode':'primary' if page is self.resource['page'] else 'selected',
                      'start_url':self._url(page.url),'actions':[],'issues':[],'receipts':{},'paused':False,'state':'RECORDING'}
        self.records[key]=self.current;self.documents={}
        for frame in page.frames:await self.inject(frame)

    @staticmethod
    def _url(url):
        parsed=urlsplit(url)
        return parsed._replace(netloc=parsed.netloc.rsplit('@',1)[-1],query='',fragment='').geturl()

    async def receive(self,source,payload):
        async with self.receive_lock:
            return await self._receive(source,payload)

    async def _receive(self,source,payload):
        r=self.current
        if not r or not isinstance(payload,dict) or payload.get('recording_id')!=r['id']:return False
        if source['page'] is not r['page']:
            self.issue('EXTRA_PAGE');return False
        doc=payload.get('document_id');seq=payload.get('source_sequence')
        if not isinstance(doc,str) or type(seq) is not int:
            self.issue('SOURCE_INVALID');return False
        receipt=r['receipts'].setdefault(doc,{'document_id':doc,'sent':0,'acknowledged':0,'sealed':False})
        if seq!=receipt['sent']+1:self.issue('SOURCE_GAP')
        receipt['sent']=max(receipt['sent'],seq);receipt['acknowledged']+=1
        if r['paused']:
            self.issue('PAUSED');return True
        if payload.get('operation')=='unsupported':
            self.issue('UNSUPPORTED_INTERACTION');return True
        selector=payload.get('selector')
        from .observation import frame_path
        if source['frame']!=source['page'].main_frame:
            chain=await frame_path(source['page'],source['frame'])
            if chain is None:
                self.issue('FRAME_UNAVAILABLE');return True
            selector=deepcopy(selector)
            if isinstance(selector,dict):selector['frame']=chain
        action={k:payload[k] for k in ('operation','verified','document_id','element_id','value','value_state','checked') if k in payload}
        action['selector']=selector
        actions=r['actions']
        # Only adjacent writes to the same captured DOM element may collapse.
        same=actions and all(actions[-1].get(k)==action.get(k) for k in ('operation','document_id','element_id'))
        if same and action.get('operation') in {'fill','check','select'}:
            if action.get('operation')!='fill' and any(actions[-1].get(k)!=action.get(k) for k in ('value','checked')):
                same=False
        if same and action.get('operation') in {'fill','check','select'}:actions[-1]=action
        else:actions.append(action)
        if len(actions)>1000:
            del actions[1000:];self.issue('ACTION_LIMIT')
        return True

    async def pause(self,key,paused):
        if self.current and self.current['id']==key:
            self.issue('PAUSED');self.current['paused']=paused

    async def stop(self,key):
        r=self.records.get(key)
        if not r or r['state']=='STOPPED':return
        for frame,document in list(self.documents.items()):
            try:
                status=await asyncio.wait_for(frame.evaluate('(ns)=>window[ns]?.stop()',self.namespace),5)
                receipt=r['receipts'][document]
                if (not status or status['document_id']!=document or status['failed']
                        or status['sent']!=status['acknowledged'] or status['sent']!=receipt['sent']):
                    self.issue('SOURCE_UNCONFIRMED')
                else:receipt['sealed']=True
            except (Error,asyncio.TimeoutError,KeyError):self.issue('DOCUMENT_UNSEALED')
        for receipt in r['receipts'].values():
            if not receipt['sealed']:self.issue('DOCUMENT_UNSEALED')
        r['state']='STOPPED'
        if self.current is r:self.current=None

    def snapshot(self,key):
        r=self.records.get(key)
        if not r:return None
        actions=deepcopy(r['actions'])
        for i,a in enumerate(actions,1):a['sequence']=i;a.pop('element_id',None)
        return {'schema_version':1,'recording_id':key,'state':r['state'],
                'complete':r['state']=='STOPPED' and not r['issues'], 'primary':r['primary'],
                'target_mode':r['target_mode'],
                'role':r['role'],'start_url':r['start_url'],'issues':list(r['issues']),
                'documents':deepcopy(list(r['receipts'].values())),'actions':actions}

    async def close(self):
        if self.current:
            await self.stop(self.current['id'])
        self.closed=True;self.current=None;self.records.clear()
        self.context.remove_listener('page',self.watch_page)
        for page in self.context.pages:page.remove_listener('framenavigated',self.watch_frame)
        if self.tasks:await asyncio.gather(*tuple(self.tasks),return_exceptions=True)
