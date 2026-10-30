"""26 typed actions, owned resources and cumulative write diagnostics."""
import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import time

from taskweave.plugins.sdk import CapabilitySpec, PreparedResult, ResultRequest
from taskweave_process import run_command, RedactingContext
from taskweave_process.artifacts import ARTIFACT_SCHEMA, _stage_bytes
from .bridge import SimulatorBridge, require, representations, mask
from .configuration import configuration, owned_root_proof


def obj(properties,required=()):return {'type':'object','properties':properties,'required':list(required),'additionalProperties':False}
TEXT={'type':'string','minLength':1,'maxLength':4096};SHORT={'type':'string','minLength':1,'maxLength':256}
NUMBER={'type':'number','minimum':-1000000,'maximum':1000000};VALUE={'type':['object','array','string','number','boolean','null']}
PATHS={'type':'array','items':SHORT,'minItems':1,'maxItems':20}
ELEMENT={'selector':{'type':'string','minLength':1,'maxLength':512},'element_id':SHORT}
TOUCH=obj({key:NUMBER for key in ('identifier','pageX','pageY','clientX','clientY')})
COMMON={'role':SHORT,'timeout_seconds':{'type':'integer','minimum':1,'maximum':1800},'max_output_bytes':{'type':'integer','minimum':1024,'maximum':1048576},'session_id':SHORT,'page_revision':{'type':'integer','minimum':0}}
DEFINITIONS={
 'check_environment':({},[],'READ'),'connect':({'mode':{'enum':['attach','launch']}},[],'WRITE'),'disconnect':({},[],'WRITE'),
 'current_page':({},[],'READ'),'page_stack':({},[],'READ'),
 'navigate':({'mode':{'enum':['navigateTo','redirectTo','navigateBack','switchTab','reLaunch']},'url':TEXT},['mode'],'WRITE'),
 'observe':({'selectors':{'type':'array','items':ELEMENT['selector'],'maxItems':20},'paths':PATHS,'max_text_chars':{'type':'integer','minimum':1,'maximum':4096}},[],'READ'),
 'get_element':({**ELEMENT,'max_text_chars':{'type':'integer','minimum':1,'maximum':4096}},[],'READ'),
 'get_page_data':({'paths':PATHS},['paths'],'READ'),
 'tap':(ELEMENT,[],'WRITE'),'input':({**ELEMENT,'value':{'type':'string','maxLength':65536}},['value'],'WRITE'),
 'scroll':({**ELEMENT,'x':NUMBER,'y':NUMBER},['y'],'WRITE'),
 'touch':({**ELEMENT,'phase':{'enum':['start','move','end']},'touches':{'type':'array','items':TOUCH,'maxItems':10},'changeTouches':{'type':'array','items':TOUCH,'maxItems':10}},['phase'],'WRITE'),
 'call_component_method':({**ELEMENT,'method':SHORT,'args':{'type':'array','items':VALUE,'maxItems':20}},['method'],'WRITE'),
 'assert_page':({'path':TEXT},['path'],'READ'),'assert_element':({**ELEMENT,'exists':{'type':'boolean'},'text':{'type':'string','maxLength':4096},'value':VALUE},[],'READ'),
 'assert_page_data':({'path':SHORT,'value':VALUE},['path','value'],'READ'),
 'wait_for':({'kind':{'enum':['page','element','data']},'selector':ELEMENT['selector'],'path':TEXT,'value':VALUE,'timeout_ms':{'type':'integer','minimum':1,'maximum':1800000}},['kind','timeout_ms'],'READ'),
 'get_storage':({'key':SHORT},['key'],'READ'),'set_storage':({'key':SHORT,'value':VALUE},['key','value'],'WRITE'),
 'remove_storage':({'key':SHORT},['key'],'WRITE'),'clear_storage':({'scope':{'enum':['namespace','all']},'confirm_all':{'type':'boolean'}},['scope'],'WRITE'),
 'mock_method':({'method':{'enum':['request','login','getSystemInfo','getSystemInfoSync','getNetworkType','getStorageSync']},'value':VALUE},['method','value'],'WRITE'),
 'restore_mock':({'method':SHORT},['method'],'WRITE'),
 'screenshot':({'max_bytes':{'type':'integer','minimum':1,'maximum':67108864}},[],'READ'),
 'read_logs':({'cursor':{'type':'integer','minimum':0},'limit':{'type':'integer','minimum':1,'maximum':100}},[],'READ')}
OUTPUT=obj({'session_id':{'type':['string','null']},'page_path':{'type':['string','null']},'page_revision':{'type':'integer','minimum':0},'result':{'type':'object'}},['session_id','page_path','page_revision','result'])
RESULT_FIELDS={
 'check_environment':('expected_project_root','expected_appid','pages','preparation_required','root_verified'),
 'connect':('connected','runtime_appid','sdk_version','identity_level','root_verified','ownership','observed_pages'),
 'disconnect':('state','mocks_restored','window_closed'),
 'current_page':('path','query'),'page_stack':('pages',),'navigate':('path',),
 'observe':('path','query','elements','data','selection'),'get_element':('element_id','tag_name','text'),'get_page_data':('data',),
 'tap':('performed',),'input':('performed',),'scroll':('performed',),'touch':('performed',),'call_component_method':('value',),
 'assert_page':('passed',),'assert_element':('passed',),'assert_page_data':('passed',),'wait_for':('passed',),
 'get_storage':('exists','value'),'set_storage':('written',),'remove_storage':('removed',),'clear_storage':('scope',),
 'mock_method':('mocked','method','restoration_pending','restores_original_not_previous_mock'),'restore_mock':('restored','method'),
 'screenshot':('artifact','simulator_only'),'read_logs':('entries','next_cursor','oldest_cursor','lost_before_cursor')}


DIAGNOSTIC_LIMIT=65536

def diagnostic_size(value,patterns=()):
 return len(json.dumps(mask(value,patterns)).encode())

def cleanup_receipt(value):
 # Fixed SDK cleanup fields, never arbitrary remote diagnostic payloads.
 errors=value.get('errors',[])
 known={'WECHAT_MOCK_RESTORE_FAILED','WECHAT_WINDOW_CLOSE_UNKNOWN','WECHAT_DISCONNECT_FAILED'}
 return {'state':value.get('state') if value.get('state') in ('disconnected','partial','unknown','not_connected') else 'unknown',
         'mocks_restored':value.get('mocks_restored') is True,
         'window_closed':value.get('window_closed') if value.get('window_closed') in (True,'not_owned','unknown','unconfirmed') else 'unconfirmed',
         'errors':[{'code':row.get('code') if isinstance(row.get('code'),str) and row.get('code') in known else 'UNKNOWN',
                    **({'method':row['method']} if row.get('method') in DEFINITIONS['mock_method'][0]['method']['enum'] else {})}
                   for row in errors[:8] if isinstance(row,dict)] if isinstance(errors,list) else [{'code':'UNKNOWN'}]}



class JsonHandler:
 def schema(self):return {'tables':{},'indexes':{}}
 def prepare(self,request):require(isinstance(request.payload,dict),'WECHAT_RESULT_INVALID');return PreparedResult('json',payload=request.payload)
 def parse(self,stored):return stored
 def preview(self,parsed):return {'renderer':'json','data':parsed}


class Evidence:
 def __init__(self):self.entries={};self.sessions={};self.reserved={};self.patterns={};self.owners={}
 def journal(self,ctx):
  attempt=ctx.scope.attempt_id;require(attempt in self.entries or len(self.entries)<32,'WECHAT_DIAGNOSTIC_CAPACITY');return self.entries.setdefault(attempt,[])
 def discard(self,attempt):
  for entry in self.entries.pop(attempt,[]):self.reserved.pop(id(entry),None)
  self.patterns.pop(attempt,None)
 def bind(self,session,ctx):
  attempt=ctx.scope.attempt_id;owner=id(session);previous=self.owners.get(owner)
  policy=self.patterns.get(attempt)
  require(policy is None or policy==session.bridge.patterns,'WECHAT_SESSION_CONFIGURATION_CHANGED','Known-secret policy cannot change within an attempt')
  attempts=set(self.owners.values())|{attempt}
  if previous!=attempt and list(self.owners.values()).count(previous)==1:attempts.discard(previous)
  require(len(attempts)<=32 and (owner in self.owners or len(self.owners)<128),'WECHAT_DIAGNOSTIC_CAPACITY')
  self.owners[owner]=attempt;self.patterns[attempt]=session.bridge.patterns
  if previous!=attempt and previous not in self.owners.values():self.discard(previous)
 def release(self,session):
  previous=self.owners.pop(id(session),None)
  if previous not in self.owners.values():self.discard(previous)
 def reserve(self,ctx,session,entry,*,launch=None):
  journal=self.journal(ctx);patterns=session.bridge.patterns
  longest=max(session.config['pages'],key=lambda value:diagnostic_size(value,patterns),default='')
  # Complete configured metadata and known literal/JSON masking growth are
  # accounted for before dispatch. Stable cleanup fields are bounded below.
  known_codes=['WECHAT_MOCK_RESTORE_FAILED','WECHAT_WINDOW_CLOSE_UNKNOWN','WECHAT_DISCONNECT_FAILED','UNKNOWN']
  methods=DEFINITIONS['mock_method'][0]['method']['enum']
  longest_value=lambda values:max(values,key=lambda value:diagnostic_size(value,patterns))
  cleanup={'state':longest_value(['disconnected','partial','unknown','not_connected']),
           'mocks_restored':False,'window_closed':longest_value(['not_owned','unknown','unconfirmed']),
           'errors':[{'code':longest_value(known_codes),'method':longest_value(methods)} for _ in range(8)]}
  future={**entry,'state':'completed','session_id':session.bridge.remote_session or '', 'page_path':longest,
          'cleanup':cleanup,'stderr':{'stderr_total_bytes':999999999999999999999,'stderr_truncated':False,'stderr':'😀'*64}}
  if launch is not None:future['launch']=launch;future['command']={'exit_code':-9999999999,'stdout_truncated':False,'stderr_truncated':False}
  capacity=diagnostic_size(future,patterns)+128
  # The initial fixed UUID reply is not yet observed. The protocol bounds
  # identifiers to 128 ASCII chars; one redaction pass can expand each to 10.
  if session.bridge.remote_session is None:capacity+=1280
  previous=self.reserved.get(id(entry),0)
  total=sum(self.reserved.get(id(row),0) for row in journal)-previous+capacity
  envelope=diagnostic_size({mask('error_code',patterns):'😀'*128,mask('effect_state',patterns):mask('UNKNOWN',patterns),mask('operations',patterns):[]})+128
  require((entry in journal or len(journal)<32) and total+envelope<=DIAGNOSTIC_LIMIT,'WECHAT_DIAGNOSTIC_CAPACITY')
  self.reserved[id(entry)]=capacity
  if entry not in journal:journal.append(entry)
 async def results(self,ctx,error):
  # Failure hooks run before host resource release. Finalize this attempt's
  # owned sessions here so cleanup failures are visible in the same artifact.
  # Keep the accepted entry objects/policy before last-owner cleanup prunes
  # historical maps. Close annotates these same objects before serialization.
  entries=list(self.entries.get(ctx.scope.attempt_id,[]));patterns=self.patterns.get(ctx.scope.attempt_id,())
  for session in list(self.sessions.values()):
   if session.attempt==ctx.scope.attempt_id:await session.close()
  if not entries:return []
  operations=[]
  for entry in entries:
   # Bridge/stderr producers already mask before their text clip. Do not
   # repeatedly expand redaction tokens on final persistence; raw provenance
   # and stable fields get their single complete masking pass here.
   operation=mask({key:value for key,value in entry.items() if key!='stderr'},patterns)
   if 'stderr' in entry:operation[mask('stderr',patterns)]={mask(key,patterns):value for key,value in entry['stderr'].items()}
   operations.append(operation)
  payload={mask('error_code',patterns):mask(str(getattr(error,'code','UNKNOWN')),patterns)[:128],mask('effect_state',patterns):mask('UNKNOWN',patterns),mask('operations',patterns):operations}
  require(len(json.dumps(payload).encode())<=DIAGNOSTIC_LIMIT,'WECHAT_DIAGNOSTIC_CAPACITY')
  return [ResultRequest('wechat_dev.operation_failure','wechat_operation_failure',payload)]


class Session:
 def __init__(self,ctx,config,bridge,evidence):
  self.ctx,self.config,self.bridge,self.evidence=ctx,config,bridge,evidence;self.attempt=ctx.scope.attempt_id
  self.connected=False;self.closed=False;self.identity=None;self.launch_lock=None;self.launch_info=None
  evidence.bind(self,ctx)
 def bind(self,ctx,config):
  require(not self.closed and not self.bridge.closed and not self.bridge.tainted and self.config==config,'WECHAT_SESSION_CONFIGURATION_CHANGED')
  values=[ctx.resolve_secret(ref) for ref in config.get('env_secret_refs',{}).values()]
  require(len(values)<=32 and all(isinstance(value,str) and len(value)<=4096 for value in values),'WECHAT_SECRET_LIMIT')
  require(representations(values)==self.bridge.patterns,'WECHAT_SESSION_CONFIGURATION_CHANGED','Retained transport requires unchanged resolved secrets; use a separately prepared role/transport')
  self.evidence.bind(self,ctx);self.attempt=ctx.scope.attempt_id;self.ctx=ctx
  self.bridge.ctx=ctx;self.bridge.process.ctx=RedactingContext(ctx,self.bridge.patterns)
 async def close(self):
  if self.closed:return
  self.closed=True;await self.bridge.close();cleanup=cleanup_receipt(self.bridge.cleanup);self.bridge.cleanup=cleanup
  if self.launch_info and self.launch_info['ownership']=='owned' and cleanup.get('window_closed')=='not_owned':
   cleanup={'state':'unknown','mocks_restored':cleanup.get('mocks_restored',False),'window_closed':'unconfirmed'};self.bridge.cleanup=cleanup
  for entry in self.evidence.entries.get(self.attempt,[]):
   if entry.get('resource_id')==id(self):entry['cleanup']=cleanup
  if cleanup.get('state')=='partial' or cleanup.get('state')=='unknown':self.ctx.log('WARNING','WECHAT_CLEANUP_UNCONFIRMED: owned mocks/window may need identity-based follow-up')
  self.release_marker(cleanup);self.evidence.release(self)
 def release_marker(self,cleanup):
  if not self.launch_lock or cleanup.get('state')!='disconnected' or cleanup.get('mocks_restored') is not True or cleanup.get('window_closed') not in (True,'not_owned'):return
  path,identity=self.launch_lock
  try:
   metadata=path.lstat()
   if stat.S_ISDIR(metadata.st_mode) and (metadata.st_dev,metadata.st_ino)==identity and not list(path.iterdir()):
    path.rmdir();self.launch_lock=None
  except OSError:pass


class Provider:
 def __init__(self,evidence):self.evidence=evidence;self.busy=set()
 async def open(self,ctx,role):
  config=configuration(ctx);require(len(self.evidence.sessions)<128,'WECHAT_RESOURCE_CAPACITY');bridge=await SimulatorBridge.start(ctx,config)
  try:session=Session(ctx,config,bridge,self.evidence)
  except BaseException:
   await bridge.close();raise
  self.evidence.sessions[id(session)]=session;return session
 async def close(self,session):await session.close();self.evidence.sessions.pop(id(session),None)


def inspect_environment(config):
 issues=[]
 if not isinstance(config.get('node_path'),str) or not Path(config['node_path']).is_file():issues.append('explicit Node executable missing')
 package=Path(config.get('module_root',''))/'node_modules/miniprogram-automator/package.json'
 if not package.is_file():issues.append('prepared official SDK0.12.1 dependencies missing')
 else:
  try:require(package.stat().st_size<=65536,'WECHAT_PREPARATION_REQUIRED');meta=json.loads(package.read_text());require(meta.get('name')=='miniprogram-automator' and meta.get('version')=='0.12.1','WECHAT_PREPARATION_REQUIRED')
  except (ValueError,OSError):issues.append('invalid SDK metadata')
 if config.get('mode')=='launch' and not Path(config.get('cli_path','')).is_file():issues.append('official agent-start CLI missing')
 return {'expected_project_root':config['project_root'],'expected_appid':config['appid'],'pages':config['pages'],'preparation_required':issues,'sdk_version':'0.12.1','login_service_permissions':'requires_actual_connection','root_verified':False}

def port_available(port):
 # Exclusive loopback bind observes occupancy without interacting with a
 # borrowed service. Release before the official CLI binds its listener.
 try:
  with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as probe:probe.bind(('127.0.0.1',port))
  return True
 except OSError:return False


class Action:
 def __init__(self,name,provider):
  self.name,self.provider=name,provider;properties,required,effect=DEFINITIONS[name];schema=obj({**COMMON,**properties},required)
  if name in ('get_element','tap','input','touch','call_component_method','assert_element'):schema['anyOf']=[{'required':['selector']},{'required':['element_id']}]
  output={**OUTPUT,'properties':{**OUTPUT['properties'],'result':{'type':'object','required':list(RESULT_FIELDS[name])}}}
  if name=='screenshot':output['properties']['result']['properties']={'artifact':ARTIFACT_SCHEMA,'simulator_only':{'const':True}}
  self.spec=CapabilitySpec('wechat_dev.'+name,'WeChat simulator '+name,schema,output,effect,timeout_ms=1810000,retry_safe=effect=='READ',resource_ids=() if name=='check_environment' else ('wechat_dev.simulator',))
 async def preflight(self,ctx,inputs):
  from jsonschema import Draft202012Validator
  require(Draft202012Validator(self.spec.input_schema).is_valid(inputs),'WECHAT_INPUT_INVALID');configuration(ctx);return []
 async def execute(self,ctx,inputs):
  await self.preflight(ctx,inputs);require(not ctx.cancelled(),'CANCELLED');config=configuration(ctx)
  if self.name=='check_environment':return {'session_id':None,'page_path':None,'page_revision':0,'result':inspect_environment(config)}
  session=await ctx.resources.acquire('wechat_dev.simulator',inputs.get('role','default'));require(not session.closed and session.config==config,'WECHAT_SESSION_CONFIGURATION_CHANGED')
  require(id(session) not in self.provider.busy,'WECHAT_SESSION_BUSY');session.bind(ctx,config);self.provider.busy.add(id(session));journal=session.evidence.journal(ctx);entry=None
  params={key:value for key,value in inputs.items() if key not in ('role','timeout_seconds')};timeout=inputs.get('timeout_seconds',60)
  params['rpc_timeout_ms']=max(1,timeout*1000-100)
  deadline=time.monotonic()+timeout
  async def request(method,arguments):
   remaining=deadline-time.monotonic();require(remaining>0,'WECHAT_RPC_TIMEOUT')
   if entry and method==self.name:entry['state']='UNKNOWN'
   return await session.bridge.request(method,arguments,timeout_seconds=remaining)
  try:
   if self.spec.effect=='WRITE':
    entry={'action_id':self.spec.id,'resource_id':id(session),'role':hashlib.sha256(inputs.get('role','default').encode()).hexdigest(),'state':'NOT_STARTED'};session.evidence.reserve(ctx,session,entry)
   if self.name=='connect':
    require(not session.connected,'WECHAT_ALREADY_CONNECTED');mode=inputs.get('mode',config.get('mode','attach'));owned=False;endpoint=config.get('endpoint');launch=None
    if mode=='launch':
     require(isinstance(config.get('cli_path'),str) and Path(config['cli_path']).is_file() and type(config.get('port')) is int and 1<=config['port']<=65535,'WECHAT_PREPARATION_REQUIRED')
     proof=owned_root_proof(config);endpoint_was_free=await asyncio.to_thread(port_available,config['port']);lock=Path(config['project_root'])/'.taskweave-wechat-active'
     args=['agent','start','--project',config['project_root'],'--auto-port',str(config['port'])]
     prospective={'argv':[config['cli_path'],*args],'endpoint_was_free':endpoint_was_free,'opened_project_window':False,'ownership':'uncertain','preparation':proof,'root_verified':False,'configured_launch_root':config['project_root']}
     session.evidence.reserve(ctx,session,entry,launch=prospective)
     try:lock.mkdir(mode=0o700)
     except FileExistsError:require(False,'WECHAT_LAUNCH_ROOT_BUSY')
     session.launch_lock=(lock,(lock.stat().st_dev,lock.stat().st_ino))
     args=['agent','start','--project',config['project_root'],'--auto-port',str(config['port'])]
     safe=RedactingContext(ctx,session.bridge.patterns);entry['state']='UNKNOWN';command=await run_command(safe,config['cli_path'],args,cwd=config['project_root'],env={},stdin=None,timeout_seconds=timeout,max_output_bytes=65536)
     entry['command']={key:command[key] for key in ('exit_code','stdout_truncated','stderr_truncated')}
     require(command['exit_code']==0 and not command['stdout_truncated'] and not command['stderr_truncated'],'WECHAT_LAUNCH_FAILED')
     decoder=json.JSONDecoder();matches=[]
     for match in re.finditer(r'\{',command['stdout']+command['stderr']):
      try:value,_=decoder.raw_decode((command['stdout']+command['stderr'])[match.start():])
      except ValueError:continue
      if isinstance(value,dict) and value.get('command')=='agent-start':matches.append(value)
     require(len(matches)==1 and matches[0].get('status')=='ok' and matches[0].get('autoPort')==config['port'] and type(matches[0].get('openedProjectWindow')) is bool,'WECHAT_LAUNCH_UNCONFIRMED')
     owned=bool(proof and endpoint_was_free and matches[0]['openedProjectWindow']);endpoint='ws://127.0.0.1:'+str(config['port'])
     launch={'argv':[config['cli_path'],*args],'endpoint_was_free':endpoint_was_free,'opened_project_window':matches[0]['openedProjectWindow'],'ownership':'owned' if owned else ('borrowed' if not matches[0]['openedProjectWindow'] else 'uncertain'),'preparation':proof,'root_verified':False,'configured_launch_root':config['project_root']};session.launch_info=launch;entry['launch']=launch
    require(isinstance(endpoint,str),'WECHAT_PREPARATION_REQUIRED','Prepared automation endpoint required')
    params={'endpoint':endpoint,'appid':config['appid'],'pages':config['pages'],'owned':owned,'storage_namespace':config['storage_namespace'],'component_methods':config.get('component_methods',[]),'allow_borrowed_mock':config.get('allow_borrowed_mock') is True,'rpc_timeout_ms':params['rpc_timeout_ms']}
    out=await request('connect',params);session.connected=True;session.identity=out
    if launch:out['result']['launch']=launch
   else:
    require(session.connected,'WECHAT_NOT_CONNECTED')
    out=await request(self.name,params)
    if self.name=='disconnect':
     session.connected=False;session.bridge.cleanup=out['result'];session.release_marker(out['result']);require(out['result'].get('mocks_restored') is True and out['result'].get('state')=='disconnected','WECHAT_CLEANUP_FAILED')
    if self.name=='screenshot':
     from .capture import validate_png
     capture=out['result'];require(type(capture.get('size_bytes')) is int and 0<capture['size_bytes']<=inputs.get('max_bytes',16777216),'WECHAT_SCREENSHOT_LIMIT');data=bytearray();offset=0
     try:
      while offset<capture['size_bytes']:
       chunk=(await request('screenshot_chunk',{'capture_id':capture['capture_id'],'offset':offset}))['result'];raw=base64.b64decode(chunk['data'],validate=True);require(chunk['offset']==offset and 0<len(raw)<=65536 and chunk['next_offset']==offset+len(raw),'WECHAT_CAPTURE_INVALID');data.extend(raw);offset+=len(raw);require(offset<=capture['size_bytes'],'WECHAT_CAPTURE_INVALID')
      require(hashlib.sha256(data).hexdigest()==capture['sha256'],'WECHAT_CAPTURE_INVALID');validate_png(data);artifact=await _stage_bytes(ctx,'wechat-simulator.png',bytes(data));out['result']={'artifact':artifact,'simulator_only':True}
     finally:
      if not session.bridge.closed:await session.bridge.request('screenshot_release',{'capture_id':capture['capture_id']},timeout_seconds=2)
   out=mask(out,session.bridge.patterns);require(len(json.dumps(out,ensure_ascii=False).encode())<=inputs.get('max_output_bytes',65536),'WECHAT_OUTPUT_LIMIT')
   if entry:
    require(session.bridge.remote_page is None or session.bridge.remote_page in config['pages'],'WECHAT_REPLY_IDENTITY_INVALID')
    entry['state']='completed';entry['session_id']=session.bridge.remote_session;entry['page_path']=session.bridge.remote_page
   return out
  except BaseException:
   if entry:
    stderr=session.bridge.process.stderr_result();entry['stderr']={'stderr_total_bytes':min(999999999999999999999,session.bridge.process.stderr_total),'stderr_truncated':bool(stderr.get('stderr_truncated')),'stderr':mask(str(stderr.get('stderr','')),session.bridge.patterns)[:64]};entry['cleanup']=cleanup_receipt(session.bridge.cleanup)
   raise
  finally:self.provider.busy.discard(id(session))
 async def verify(self,ctx,inputs,out):return []
