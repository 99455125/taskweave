"""Five typed actions over an owned project resource and attempt journal."""
import asyncio
import json
from taskweave.plugins.sdk import CapabilitySpec,ResultRequest,PreparedResult
from taskweave_process.runner import redact_text
from .redaction import representations,mask_data
from .lease import native_write_state,claim_native_lease,release_confirmed_lease
from .project import configuration,require,inspect_project
from .build import build_project,check_artifact
from .tests import run_tests,collect_report

def obj(properties,required=()):return {'type':'object','properties':properties,'required':list(required),'additionalProperties':False}
TEXT={'type':'string','minLength':1,'maxLength':4096};PLATFORM={'enum':['mp-weixin','h5']};COMMON={'role':TEXT,'timeout_seconds':{'type':'integer','minimum':1,'maximum':1800},'max_output_bytes':{'type':'integer','minimum':1024,'maximum':1048576}}
from taskweave_process.actions import COMMAND_SCHEMA
from taskweave_process.artifacts import ARTIFACT_SCHEMA
DATA={'type':'object'};INTEGER={'type':'integer','minimum':0};BOOL={'type':'boolean'}
OUTPUTS={
'inspect':obj({'project_root':TEXT,'kind':{'enum':['cli','hbuilderx']},'layout':{'enum':['.','src']},'vue_version':TEXT,'appid':{'type':'string'},'uniapp_appid':{'type':'string'},'pages':{'type':'array','items':TEXT},'scripts':DATA,'outputs':DATA,'build_scripts':DATA,'test_scripts':DATA,'engines':DATA,'node_major_configured':{'type':['integer','null']},'preparation_required':{'type':'array','items':TEXT},'native_write_state':DATA,'tool_versions':DATA,'test_plugin_installed':BOOL},['project_root','kind','layout','vue_version','appid','pages','scripts','preparation_required']),
'build':obj({'build_id':TEXT,'started_at':INTEGER,'platform':PLATFORM,'environment':{'enum':['production','development']},'command':COMMAND_SCHEMA,'completion':{'enum':['completed','compiled_in_memory']},'artifact_verified':BOOL,'artifacts':DATA},['build_id','started_at','platform','environment','command','completion','artifact_verified','artifacts']),
'check_artifact':obj({'output_path':TEXT,'build_id':TEXT,'provenance_verified':BOOL,'structure_verified':BOOL,'artifacts':DATA},['build_id','provenance_verified','structure_verified','artifacts']),
'run_tests':obj({'test_run_id':TEXT,'started_at':INTEGER,'passed':BOOL,'summary':DATA,'command':COMMAND_SCHEMA,'cli_exit':{'type':'integer'},'jest_exit':{'oneOf':[{'type':'integer'},{'const':'unavailable'}]},'runner_version':TEXT,'report_path':TEXT},['test_run_id','started_at','passed','summary','command','cli_exit','jest_exit','runner_version','report_path']),
'collect_report':obj({'artifacts':{'type':'array','items':ARTIFACT_SCHEMA},'total_bytes':INTEGER,'test_run_verified':BOOL},['artifacts','total_bytes','test_run_verified'])}

DEFINITIONS={
'inspect':({},[],'READ'),
'build':({'platform':PLATFORM,'environment':{'enum':['production','development']}},['platform'],'WRITE'),
'check_artifact':({'build_id':TEXT,'started_at':{'type':'integer','minimum':0},'platform':PLATFORM},['build_id','started_at','platform'],'READ'),
'run_tests':({'platform':PLATFORM,'file':TEXT,'case':TEXT},['platform'],'WRITE'),
'collect_report':({'paths':{'type':'array','items':TEXT,'minItems':1,'maxItems':100},'test_run_id':TEXT,'max_bytes':{'type':'integer','minimum':1,'maximum':67108864}},['paths'],'READ')}

def redact_data(value,secrets):
    return mask_data(value,representations(secrets))

class Evidence:
    def __init__(self):self.journals={};self.owners={}
    def operations(self,ctx):
        key=ctx.scope.attempt_id
        require(key in self.journals or len(self.journals)<32,'UNIAPP_DIAGNOSTIC_CAPACITY')
        return self.journals.setdefault(key,[])
    async def results(self,ctx,error):
        operations=self.journals.get(ctx.scope.attempt_id,[])
        if not operations:return []
        output={'error_code':str(getattr(error,'code','UNKNOWN'))[:128],'effect_state':'UNKNOWN','operations':operations}
        require(len(json.dumps(output).encode())<=65536,'UNIAPP_DIAGNOSTIC_CAPACITY')
        return [ResultRequest('uniapp.operation_failure','uniapp_operation_failure',output)]

    def retain(self,attempt):self.owners[attempt]=self.owners.get(attempt,0)+1
    def release(self,attempt):
        self.owners[attempt]-=1
        if not self.owners[attempt]:self.owners.pop(attempt);self.journals.pop(attempt,None)

class ProjectSession:
    def __init__(self,root,evidence,attempt):self.root=root;self.evidence=evidence;self.attempt=attempt;self.builds={};self.tests={};self.closed=False;evidence.retain(attempt)
    def bind(self,ctx):
        require(not self.closed,'UNIAPP_PROJECT_IDENTITY_CHANGED')
        attempt=ctx.scope.attempt_id
        if attempt!=self.attempt:
            self.evidence.retain(attempt);self.evidence.release(self.attempt);self.attempt=attempt
    async def close(self):
        if self.closed:return
        self.closed=True;self.builds.clear();self.tests.clear();self.evidence.release(self.attempt)

class ProjectProvider:
    def __init__(self,evidence):self.evidence=evidence;self.active=set();self.busy=set();self.sessions={}
    async def open(self,ctx,role):
        require(len(self.active)<128,'UNIAPP_RESOURCE_CAPACITY');session=ProjectSession(configuration(ctx)['project_root'],self.evidence,ctx.scope.attempt_id);self.active.add(id(session));self.sessions[id(session)]=session;return session
    async def close(self,session):
        await session.close();self.active.discard(id(session));self.sessions.pop(id(session),None)

    def observations(self,root):
        result=[]
        for session in list(self.sessions.values()):
            if session.root!=root:continue
            for record in list(session.builds.values()):result.append({k:record[k] for k in ('build_id','started_at','platform','environment','state')})
        return result[-32:]

class JsonHandler:
    def schema(self):return {'version':1,'tables':{},'migrations':{},'indexes':{}}
    def prepare(self,request):require(isinstance(request.payload,dict),'UNIAPP_RESULT_INVALID');return PreparedResult('json',payload=request.payload)
    def parse(self,stored):return stored
    def preview(self,parsed):return {'renderer':'json','data':parsed}

class Action:
    def __init__(self,name,provider):
        self.name=name;self.provider=provider;properties,required,effect=DEFINITIONS[name]
        self.spec=CapabilitySpec('uniapp.'+name,'uni-app '+name,obj({**COMMON,**properties},required),OUTPUTS[name],effect,timeout_ms=1810000,retry_safe=effect=='READ',resource_ids=('uniapp.project',))
    async def preflight(self,ctx,inputs):
        from jsonschema import Draft202012Validator
        require(Draft202012Validator(self.spec.input_schema).is_valid(inputs),'UNIAPP_INPUT_INVALID');configuration(ctx);return []
    async def execute(self,ctx,inputs):
        await self.preflight(ctx,inputs);require(not ctx.cancelled(),'CANCELLED');config=configuration(ctx)
        session=await ctx.resources.acquire('uniapp.project',inputs.get('role','default'));require(not session.closed and session.root==config['project_root'],'UNIAPP_PROJECT_IDENTITY_CHANGED')
        require(session.root not in self.provider.busy,'UNIAPP_PROJECT_BUSY');require(len(session.builds)+len(session.tests)<64,'UNIAPP_HISTORY_CAPACITY')
        if self.spec.effect=='WRITE':require(native_write_state(session.root)['state']=='clear','UNIAPP_NATIVE_ROOT_QUARANTINED')
        session.bind(ctx);operations=session.evidence.operations(ctx);start=len(operations)
        lease=claim_native_lease(session.root,ctx.scope.attempt_id) if self.spec.effect=='WRITE' and config['kind']=='hbuilderx' else None
        self.provider.busy.add(session.root)
        try:
            if self.name=='inspect':out=inspect_project(ctx,config)
            elif self.name=='build':out=await build_project(ctx,config,inputs,session)
            elif self.name=='check_artifact':out=check_artifact(ctx,config,inputs,session)
            elif self.name=='run_tests':out=await run_tests(ctx,config,inputs,session)
            else:out=await collect_report(ctx,config,inputs,session)
            secrets=[ctx.resolve_secret(ref) for ref in config.get('env_secret_refs',{}).values()]
            out=redact_data(out,secrets) if self.name!='collect_report' else out;encoded=json.dumps(out,ensure_ascii=False);require(len(encoded.encode())<=inputs.get('max_output_bytes',65536),'UNIAPP_OUTPUT_TOO_LARGE');
            for entry in operations[start:]:entry['action_state']='completed'
            if lease:release_confirmed_lease(lease)
            return json.loads(encoded)
        except BaseException:
            if lease and not operations[start:]:release_confirmed_lease(lease)
            for entry in operations[start:]:
                entry['native_effects']='quarantined' if lease else 'ordinary_process'
                entry['action_state']='partial' if entry['completion'] in ('completed','partial') else 'unknown'
            raise
        finally:self.provider.busy.discard(session.root)
    async def verify(self,ctx,inputs,output):return []
