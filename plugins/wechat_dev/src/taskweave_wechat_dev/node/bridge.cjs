'use strict';
// Fixed official SDK methods only. stdout is reserved for newline JSON.
const fs=require('fs'),path=require('path'),crypto=require('crypto');
for(const method of ['log','info','debug','warn','error'])console[method]=(...args)=>process.stderr.write(args.map(String).join(' ')+'\n');
const LIMIT=1048576,session=crypto.randomUUID();
const redactions=JSON.parse(process.env.TASKWEAVE_WECHAT_REDACTION_PATTERNS||'[]');
function masked(string){for(const secret of redactions)if(secret)string=string.split(secret).join('[REDACTED]');return string;}
let mini=null,current=null,revision=0,settings={},poisoned=false,lastCleanup=null;
const elements=new Map(),mocks=new Set(),captures=new Map(),logs=[];
let nextLog=1,queued=0;
const MOCKS=new Set(['request','login','getSystemInfo','getSystemInfoSync','getNetworkType','getStorageSync']);
function fail(code){const error=new Error(code);error.code=code;throw error;}
function need(value,code='WECHAT_INPUT_INVALID'){if(!value)fail(code);}
function jsonBytes(value){return Buffer.byteLength(JSON.stringify(value));}
function finite(value){return typeof value==='number'&&Number.isFinite(value);}
function text(value,limit=4096){const string=typeof value==='string'?value:JSON.stringify(value===undefined?null:value);return masked(string).slice(0,limit);}
function same(left,right){return JSON.stringify(left)===JSON.stringify(right);}
function dataPath(value){need(typeof value==='string'&&value.length<=256&&/^[A-Za-z_$][\w$]*(?:\.[\w$]+|\[\d+\])*$/.test(value));return value;}
function output(result,budget=65536){need(jsonBytes(result)<=budget,'WECHAT_OBSERVATION_LIMIT');return result;}
function endpoint(value){need(typeof value==='string');const url=new URL(value);need(['ws:','wss:'].includes(url.protocol)&&!url.username&&!url.password&&!url.search&&!url.hash);return value;}
async function fresh(){
 need(mini&&!poisoned,'WECHAT_NOT_CONNECTED');const page=await mini.currentPage();need(page&&typeof page.path==='string','WECHAT_PAGE_UNAVAILABLE');
 need(settings.pages.includes(page.path),'WECHAT_PROJECT_IDENTITY_MISMATCH');
 // Public returned SDK objects are cached by the SDK; no private pageId is
 // exposed as a stable contract. Explicit navigation also invalidates handles.
 if(page!==current){current=page;revision++;elements.clear();}
 return page;
}
function envelope(result){return {session_id:session,page_path:current?current.path:null,page_revision:revision,result};}
async function getElement(p){
 const page=await fresh();let element;
 if(p.element_id){const record=elements.get(p.element_id);need(record&&record.revision===revision,'WECHAT_ELEMENT_STALE');element=record.element;}
 else{need(typeof p.selector==='string'&&p.selector.length>0&&p.selector.length<=512);element=await page.$(p.selector);need(element,'WECHAT_ELEMENT_MISSING');}
 return element;
}
function route(value){need(typeof value==='string'&&value.startsWith('/')&&!value.startsWith('//')&&value.length<=4096&&!value.includes('\\'));const page=value.slice(1).split('?')[0];need(settings.pages.includes(page),'WECHAT_ROUTE_INVALID');return value;}
function storageKey(key){need(typeof key==='string'&&key.length>0&&key.length<=256&&!key.includes('\0'));return settings.storage_namespace+key;}
async function readData(paths){need(Array.isArray(paths)&&paths.length>0&&paths.length<=20);const page=await fresh(),data={};for(const name of paths)data[dataPath(name)]=await page.data(name);return data;}
function addLog(kind,payload){logs.push({cursor:nextLog++,timestamp:Date.now(),session_id:session,page_path:current?current.path:null,kind,payload:text(payload,4096)});while(logs.length>100)logs.shift();}
async function capped(promise,ms,code){let timer;try{return await Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>{const e=new Error(code);e.code=code;reject(e)},ms)})]);}finally{clearTimeout(timer);}}
async function cleanup(){
 const errors=[];const connected=mini;
 if(!connected)return lastCleanup||{state:'disconnected',mocks_restored:true,window_closed:'not_owned'};
 await Promise.all([...mocks].map(async method=>{try{await capped(connected.restoreWxMethod(method),1500,'WECHAT_MOCK_RESTORE_FAILED');mocks.delete(method);}catch(e){errors.push({method,code:'WECHAT_MOCK_RESTORE_FAILED'});}}));
 let windowClosed='not_owned';
 try{if(settings.owned){await capped(connected.close(),2500,'WECHAT_WINDOW_CLOSE_UNKNOWN');windowClosed=true;}}
 catch(e){windowClosed='unknown';errors.push({code:'WECHAT_WINDOW_CLOSE_UNKNOWN'});}
 finally{try{await connected.disconnect();}catch(e){errors.push({code:'WECHAT_DISCONNECT_FAILED'});}mini=null;current=null;revision++;elements.clear();captures.clear();}
 return lastCleanup={state:errors.length?'partial':'disconnected',mocks_restored:mocks.size===0,window_closed:windowClosed,errors};
}
async function dispatch(method,p){
 if(method==='connect'){
  need(!mini&&!poisoned&&mocks.size===0&&(!lastCleanup||lastCleanup.state==='disconnected'),'WECHAT_ALREADY_CONNECTED');need(typeof p.appid==='string'&&p.appid.length>0&&Array.isArray(p.pages)&&p.pages.length>0&&p.pages.length<=500);need(typeof p.storage_namespace==='string'&&p.storage_namespace.length>0&&p.storage_namespace.length<=128);
  const root=process.env.TASKWEAVE_WECHAT_MODULE_ROOT;need(root,'WECHAT_PREPARATION_REQUIRED');
  const packagePath=path.join(root,'node_modules/miniprogram-automator/package.json');const meta=JSON.parse(fs.readFileSync(packagePath,'utf8'));need(meta.name==='miniprogram-automator'&&meta.version==='0.12.1','WECHAT_SDK_VERSION_UNSUPPORTED');
  const sdk=require(path.dirname(packagePath));settings={...p};settings.owned=p.owned===true;settings.component_methods=Array.isArray(p.component_methods)?p.component_methods:[];
  lastCleanup=null;mini=await sdk.connect({wsEndpoint:endpoint(p.endpoint)});
  try{
   const account=await mini.callWxMethod('getAccountInfoSync');const appid=account&&account.miniProgram&&account.miniProgram.appId;
   need(appid===p.appid,'WECHAT_PROJECT_IDENTITY_MISMATCH');
   // agent-start can return before the renderer has its first page metadata.
   // Poll only fixed READ methods; never replay a launch or simulator write.
   const readyStart=Date.now(),readyEnd=readyStart+Math.min(15000,Math.max(1,(p.rpc_timeout_ms||30000)-250));let stack,readyReads=0;
   for(;;){try{readyReads++;await fresh();stack=await mini.pageStack();need(stack.every(page=>p.pages.includes(page.path)),'WECHAT_PROJECT_IDENTITY_MISMATCH');break;}
    catch(error){const pending=error.code==='WECHAT_PAGE_UNAVAILABLE'||String(error.message).startsWith("Cannot destructure property 'rawPath' of 't.getPageMetaByWebviewId(");if(!pending)throw error;if(Date.now()>=readyEnd)fail('WECHAT_RUNTIME_NOT_READY');await new Promise(resolve=>setTimeout(resolve,100));}}
   mini.on('console',payload=>addLog('console',payload));mini.on('exception',payload=>addLog('exception',payload));
   return {connected:true,runtime_appid:appid,sdk_version:meta.version,node_version:process.version,identity_level:'appid_and_page',root_verified:false,ownership:settings.owned?'owned':'borrowed',observed_pages:stack.map(page=>page.path),readiness_reads:readyReads,readiness_ms:Date.now()-readyStart};
  }catch(e){await cleanup();throw e;}
 }
 if(method==='disconnect')return cleanup();
 const page=await fresh();const before=revision;
 if(p.page_revision!==undefined)need(p.page_revision===revision,'WECHAT_PAGE_CHANGED');
 if(p.session_id!==undefined)need(p.session_id===session,'WECHAT_SESSION_INVALID');
 let result;
 switch(method){
 case 'current_page':result={path:page.path,query:page.query};break;
 case 'page_stack':{const stack=await mini.pageStack();need(stack.length<=100,'WECHAT_OBSERVATION_LIMIT');need(stack.every(row=>settings.pages.includes(row.path)),'WECHAT_PROJECT_IDENTITY_MISMATCH');result={pages:stack.map(row=>({path:row.path,query:row.query}))};break;}
 case 'navigate':{
  need(['navigateTo','redirectTo','navigateBack','switchTab','reLaunch'].includes(p.mode));elements.clear();revision++;
  const target=p.mode==='navigateBack'?await mini.navigateBack():await mini[p.mode](route(p.url));need(target,'WECHAT_PAGE_UNAVAILABLE');await fresh();result={path:current.path};break;
 }
 case 'get_element':{const element=await getElement(p);need(elements.size<200,'WECHAT_ELEMENT_LIMIT');const id=crypto.randomUUID();elements.set(id,{element,revision});result={element_id:id,tag_name:element.tagName||'unknown',text:text(await element.text(),p.max_text_chars||4096)};break;}
 case 'get_page_data':result={data:await readData(p.paths)};break;
 case 'observe':{
  need(Array.isArray(p.selectors||[])&&(p.selectors||[]).length<=20);const observed=[];
  for(const selector of p.selectors||[]){need(typeof selector==='string'&&selector.length<=512);const element=await page.$(selector);observed.push({selector,exists:!!element,...(element?{tag_name:element.tagName||'unknown',text:text(await element.text(),p.max_text_chars||1024)}:{})});}
  result={path:page.path,query:page.query,elements:observed,data:p.paths?await readData(p.paths):{},selection:'first_match_per_selector'};break;
 }
 case 'tap':await (await getElement(p)).tap();result={performed:true};break;
 case 'input':{const element=await getElement(p);need(['input','textarea'].includes(element.tagName)&&typeof element.input==='function','WECHAT_ELEMENT_TYPE_INVALID');need(typeof p.value==='string'&&p.value.length<=65536);await element.input(p.value);result={performed:true};break;}
 case 'scroll':{
  need(finite(p.y)&&Math.abs(p.y)<=1000000);if(p.selector||p.element_id){const element=await getElement(p);need(typeof element.scrollTo==='function','WECHAT_ELEMENT_TYPE_INVALID');need(finite(p.x||0));await element.scrollTo(p.x||0,p.y);}else await mini.pageScrollTo(p.y);result={performed:true};break;
 }
 case 'touch':{
  need(['start','move','end'].includes(p.phase));const element=await getElement(p);const options={};
  for(const key of ['touches','changeTouches'])if(p[key]){need(Array.isArray(p[key])&&p[key].length<=10);options[key]=p[key].map(touch=>{need(touch&&typeof touch==='object'&&!Array.isArray(touch));need(Object.keys(touch).every(key=>['identifier','pageX','pageY','clientX','clientY'].includes(key)&&finite(touch[key])));return touch;});}
  await element['touch'+p.phase](options);result={performed:true};break;
 }
 case 'call_component_method':{
  need(typeof p.method==='string'&&/^[A-Za-z_]\w*$/.test(p.method)&&!['constructor','__proto__','prototype'].includes(p.method)&&settings.component_methods.includes(p.method),'WECHAT_COMPONENT_METHOD_UNSUPPORTED');need(Array.isArray(p.args||[])&&(p.args||[]).length<=20);
  const element=await getElement(p);need(typeof element.callMethod==='function','WECHAT_ELEMENT_TYPE_INVALID');result={value:(await element.callMethod(p.method,...(p.args||[])))??null};break;
 }
 case 'assert_page':need(page.path===p.path,'WECHAT_ASSERTION_FAILED');result={passed:true};break;
 case 'assert_element':{
  let element;try{element=await getElement(p);}catch(e){if(e.code!=='WECHAT_ELEMENT_MISSING')throw e;}
  need((!!element)===(p.exists!==false),'WECHAT_ASSERTION_FAILED');
  if(element&&p.text!==undefined)need((await element.text())===p.text,'WECHAT_ASSERTION_FAILED');
  if(element&&p.value!==undefined){need(typeof element.value==='function','WECHAT_ELEMENT_TYPE_INVALID');need(same(await element.value(),p.value),'WECHAT_ASSERTION_FAILED');}
  result={passed:true};break;
 }
 case 'assert_page_data':{const data=await readData([p.path]);need(same(data[p.path],p.value),'WECHAT_ASSERTION_FAILED');result={passed:true};break;}
 case 'wait_for':{
  need(['page','element','data'].includes(p.kind));need(Number.isInteger(p.timeout_ms)&&p.timeout_ms>=1&&p.timeout_ms<=1800000);const end=Date.now()+p.timeout_ms;let passed=false;
  do{const active=await fresh();if(p.kind==='page')passed=active.path===p.path;
   else if(p.kind==='element'){need(typeof p.selector==='string'&&p.selector.length<=512);passed=!!(await active.$(p.selector));}
   else passed=same((await readData([p.path]))[p.path],p.value);
   if(passed)break;await new Promise(resolve=>setTimeout(resolve,Math.min(100,Math.max(1,end-Date.now()))));
  }while(Date.now()<end);
  need(passed,'WECHAT_WAIT_TIMEOUT');result={passed:true};break;
 }
 case 'get_storage':{const key=storageKey(p.key),info=await mini.callWxMethod('getStorageInfoSync');need(info&&Array.isArray(info.keys),'WECHAT_SDK_RESULT_INVALID');result={exists:info.keys.includes(key),value:info.keys.includes(key)?await mini.callWxMethod('getStorageSync',key):null,namespace:settings.storage_namespace};break;}
 case 'set_storage':need(jsonBytes(p.value)<=65536,'WECHAT_INPUT_LIMIT');await mini.callWxMethod('setStorageSync',storageKey(p.key),p.value);result={written:true};break;
 case 'remove_storage':await mini.callWxMethod('removeStorageSync',storageKey(p.key));result={removed:true};break;
 case 'clear_storage':{
  need(['namespace','all'].includes(p.scope));if(p.scope==='all'){need(p.confirm_all===true,'WECHAT_FULL_CLEAR_NOT_CONFIRMED');await mini.callWxMethod('clearStorageSync');result={scope:'all',cleared:true};}
  else{const info=await mini.callWxMethod('getStorageInfoSync');need(info&&Array.isArray(info.keys)&&info.keys.length<=2000,'WECHAT_STORAGE_LIMIT');const keys=info.keys.filter(key=>typeof key==='string'&&key.startsWith(settings.storage_namespace));for(const key of keys)await mini.callWxMethod('removeStorageSync',key);result={scope:'namespace',removed:keys.length};}break;
 }
 case 'mock_method':{
  need(MOCKS.has(p.method),'WECHAT_MOCK_METHOD_UNSUPPORTED');need(settings.owned||settings.allow_borrowed_mock===true,'WECHAT_BORROWED_MOCK_NOT_AUTHORIZED');need(!mocks.has(p.method)&&mocks.size<8,'WECHAT_MOCK_OWNERSHIP_INVALID');
  need(!(typeof p.value==='string'&&/^\s*(?:function\b|\(\s*\)\s*=>|(?:async\s+)?(?:\([^)]*\)|[\w$]+)\s*=>)/.test(p.value)),'WECHAT_FUNCTION_MOCK_FORBIDDEN');need(jsonBytes(p.value)<=65536,'WECHAT_INPUT_LIMIT');
  // Reserve ownership before the mutation: rejected/timed-out installation
  // can still require restoring the original method during cleanup.
  mocks.add(p.method);await mini.mockWxMethod(p.method,p.value);result={mocked:true,method:p.method,restoration_pending:true,restores_original_not_previous_mock:true};break;
 }
 case 'restore_mock':need(mocks.has(p.method),'WECHAT_MOCK_NOT_OWNED');try{await mini.restoreWxMethod(p.method);}catch(e){fail('WECHAT_MOCK_RESTORE_FAILED');}mocks.delete(p.method);result={restored:true,method:p.method};break;
 case 'read_logs':{
  need(Number.isInteger(p.cursor||0)&&(p.cursor||0)>=0);const count=p.limit||20;need(Number.isInteger(count)&&count>=1&&count<=100);const selected=logs.filter(log=>log.cursor>(p.cursor||0)).slice(0,count);result={entries:selected,next_cursor:selected.length?selected[selected.length-1].cursor:(p.cursor||0),oldest_cursor:logs.length?logs[0].cursor:nextLog,lost_before_cursor:logs.length&&p.cursor&&p.cursor<logs[0].cursor-1?logs[0].cursor-1:null};break;
 }
 case 'screenshot':{
  const max=p.max_bytes||16777216;need(Number.isInteger(max)&&max>=1&&max<=67108864);need(captures.size<2,'WECHAT_CAPTURE_LIMIT');
  const encoded=await mini.screenshot();need(typeof encoded==='string'&&encoded.length<=Math.ceil(max/3)*4+4,'WECHAT_SCREENSHOT_LIMIT');need(/^[A-Za-z0-9+/]*={0,2}$/.test(encoded),'WECHAT_SCREENSHOT_INVALID');const bytes=Buffer.from(encoded,'base64');need(bytes.length<=max&&bytes.subarray(0,8).equals(Buffer.from('89504e470d0a1a0a','hex')),'WECHAT_SCREENSHOT_INVALID');const id=crypto.randomUUID();captures.set(id,bytes);result={capture_id:id,size_bytes:bytes.length,sha256:crypto.createHash('sha256').update(bytes).digest('hex'),media_type:'image/png'};break;
 }
 case 'screenshot_chunk':{const bytes=captures.get(p.capture_id);need(bytes&&Number.isInteger(p.offset)&&p.offset>=0&&p.offset<bytes.length,'WECHAT_CAPTURE_INVALID');const part=bytes.subarray(p.offset,p.offset+65536);result={offset:p.offset,data:part.toString('base64'),next_offset:p.offset+part.length};break;}
 case 'screenshot_release':need(captures.has(p.capture_id),'WECHAT_CAPTURE_INVALID');captures.delete(p.capture_id);result={released:true};break;
 default:fail('WECHAT_METHOD_UNSUPPORTED');
 }
 if(!['navigate','wait_for'].includes(method)){await fresh();need(revision===before,'WECHAT_PAGE_CHANGED');}
 return output(result,p.max_output_bytes||65536);
}
function reply(value){const data=JSON.stringify(value);if(Buffer.byteLength(data)>LIMIT){value={id:value.id,error:{code:'WECHAT_RESPONSE_LIMIT',message:'Response exceeds protocol limit'}};}process.stdout.write(JSON.stringify(value)+'\n');}
const methods=new Set('connect disconnect current_page page_stack navigate observe get_element get_page_data tap input scroll touch call_component_method assert_page assert_element assert_page_data wait_for get_storage set_storage remove_storage clear_storage mock_method restore_mock screenshot read_logs screenshot_chunk screenshot_release'.split(' '));
async function handle(frame){
 let req;try{req=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(frame));need(req&&typeof req==='object'&&!Array.isArray(req)&&Object.keys(req).sort().join(',')==='id,method,params'&&typeof req.id==='string'&&req.id.length<=128&&methods.has(req.method)&&req.params&&typeof req.params==='object'&&!Array.isArray(req.params),'WECHAT_PROTOCOL_INVALID');
  const ms=req.params.rpc_timeout_ms||30000;need(Number.isInteger(ms)&&ms>=1&&ms<=1800000);
  const result=await capped(dispatch(req.method,req.params),ms,'WECHAT_SDK_TIMEOUT');reply({id:req.id,result:envelope(result)});
 }catch(error){if(error.code==='WECHAT_SDK_TIMEOUT')poisoned=true;reply({id:req&&typeof req.id==='string'?req.id:'invalid',error:{code:error.code||'WECHAT_SDK_ERROR',message:text(String(error.message||'Fixed SDK operation failed'),1024),...(lastCleanup?{cleanup:lastCleanup}:{})}});}
}
let buffer=Buffer.alloc(0),chain=Promise.resolve();
process.stdin.on('data',chunk=>{
 buffer=Buffer.concat([buffer,chunk]);let offset;
 while((offset=buffer.indexOf(10))>=0){const frame=buffer.subarray(0,offset);buffer=buffer.subarray(offset+1);if(frame.length>LIMIT||++queued>8){process.stderr.write('WECHAT_PROTOCOL_INPUT_LIMIT');process.exit(2);}chain=chain.then(()=>handle(frame)).finally(()=>{queued--;});}
 if(buffer.length>LIMIT){process.stderr.write('WECHAT_PROTOCOL_INPUT_LIMIT');process.exit(2);}
});
process.stdin.on('end',()=>{chain.then(async()=>{await cleanup();process.exit(0);});});
process.on('uncaughtException',()=>{process.stderr.write('WECHAT_BRIDGE_FATAL');process.exit(2);});
