"""Explicit SSH/SFTP capabilities; all write actions are non-retryable."""
import asyncio
from contextlib import aclosing
import base64
import hashlib
import json
import posixpath
import time
import asyncssh
from taskweave.plugins.sdk import CapabilitySpec, PreparedResult, ResultRequest
from taskweave_process import RedactingContext
from taskweave_process.actions import object_schema, TEXT, TIMEOUT, OUTPUT_BYTES, STRINGS, TRANSFER_BYTES, COMMAND_SCHEMA
from taskweave_process.artifacts import ARTIFACT_SCHEMA
from .paths import SshError, destination_path
from .transport import configuration, _finish
from .transfer import read_bytes, upload, download, owned, remove_tree


ROLE={'type':'string','minLength':1,'maxLength':128,'default':'default'}
INT={'type':'integer','minimum':0}
BOOL={'type':'boolean'}
CHECKSUM={'type':'string','pattern':'^[0-9a-f]{64}$'}
PATH_OUTPUT=object_schema({'path':TEXT,'size_bytes':INT,'checksum':CHECKSUM},['path','size_bytes','checksum'])
STAT_OUTPUT=object_schema({'path':TEXT,'size_bytes':{'type':['integer','null']},'type':INT,
                          'permissions':{'type':['integer','null']},'mtime':{'type':['integer','null']}},
                         ['path','size_bytes','type','permissions','mtime'])
LIST_INPUT=object_schema({'role':ROLE,'path':TEXT,'max_entries':{'type':'integer','minimum':1,'maximum':1000,'default':100},'max_output_bytes':OUTPUT_BYTES})
LIST_OUTPUT=object_schema({'path':TEXT,'entries':{'type':'array','items':object_schema({'name':TEXT,'type':INT,'size_bytes':{'type':['integer','null']}},['name','type','size_bytes'])},'truncated':BOOL},['path','entries','truncated'])
COMMAND_INPUT={'role':ROLE,'cwd':TEXT,'env':STRINGS,'env_secret_refs':{'type':'object','additionalProperties':TEXT},
               'stdin':{'type':'string'},'stdin_secret_ref':TEXT,'timeout_seconds':TIMEOUT,'max_output_bytes':OUTPUT_BYTES}
TRANSFER_RESULT=object_schema({'bytes_transferred':INT,'completed':{'type':'array','items':{'type':'string'},'maxItems':100},'completed_count':INT},['bytes_transferred','completed','completed_count'])


class FailureEvidence:
    def __init__(self): self.attempt=None; self.payload=None; self.handler=None
    def begin(self,ctx): self.attempt=ctx.scope.attempt_id; self.payload=None; self.handler=None
    def capture(self,ctx,action_id,error,command):
        result=getattr(error,'result',None)
        if result is not None:
            self.attempt=ctx.scope.attempt_id
            self.handler='ssh.command_failure' if command else 'ssh.transfer_failure'
            self.payload={'action_id':action_id,'error_code':getattr(error,'code','CANCELLED'),'effect_state':'UNKNOWN','result':result}
    async def results(self,ctx,error):
        if self.attempt!=ctx.scope.attempt_id or self.payload is None: return []
        return [ResultRequest(self.handler,self.handler.replace('.','_'),self.payload)]


class TransferFailureResultHandler:
    def schema(self): return {'tables':{},'indexes':{}}
    def prepare(self,request):
        from jsonschema import Draft202012Validator
        schema=object_schema({'action_id':TEXT,'error_code':TEXT,'effect_state':{'enum':['UNKNOWN']},'result':TRANSFER_RESULT},['action_id','error_code','effect_state','result'])
        if not Draft202012Validator(schema).is_valid(request.payload): raise SshError('SSH_FAILURE_RESULT_INVALID')
        return PreparedResult('json',payload=request.payload)
    def parse(self,stored): return stored
    def preview(self,parsed): return {'renderer':'json','data':parsed}


async def list_directory(session,inputs):
    path=await session.resolve_path(inputs.get('path','.'),must_exist=True)
    maximum=inputs.get('max_entries',100); budget=inputs.get('max_output_bytes',65536)
    output={'path':path,'entries':[],'truncated':False}
    async with aclosing(session.sftp.scandir(path)) as entries:
        async for item in entries:
            if item.filename in ('.','..'): continue
            row={'name':item.filename,'type':item.attrs.type,'size_bytes':item.attrs.size}
            candidate={**output,'entries':output['entries']+[row]}
            if len(output['entries'])>=maximum or len(json.dumps(candidate,ensure_ascii=False).encode())>budget:
                output['truncated']=True; break
            output['entries'].append(row)
    return output


DECLARATIONS={
'check_connection':({},(),object_schema({'target':TEXT,'server_version':TEXT},['target','server_version']),'READ'),
'exec':({**COMMAND_INPUT,'argv':{'type':'array','items':{'type':'string'},'minItems':1,'maxItems':1000}},('argv',),COMMAND_SCHEMA,'WRITE'),
'run_script':({**COMMAND_INPUT,'script':{'type':'string','minLength':1,'maxLength':1048576}},('script',),COMMAND_SCHEMA,'WRITE'),
'stat':({'path':TEXT},('path',),STAT_OUTPUT,'READ'),
'list_directory':(LIST_INPUT['properties'],(),LIST_OUTPUT,'READ'),
'read_file':({'path':TEXT,'encoding':{'enum':['text','base64'],'default':'text'},'max_bytes':TRANSFER_BYTES},('path',),object_schema({'path':TEXT,'content':{'type':'string'},'encoding':{'enum':['text','base64']},'size_bytes':INT,'checksum':CHECKSUM},['path','content','encoding','size_bytes','checksum']),'READ'),
'read_logs':({'path':TEXT,'cursor':INT,'max_bytes':{'type':'integer','minimum':1,'maximum':1048576,'default':65536}},('path',),object_schema({'content':{'type':'string'},'cursor':INT,'truncated':BOOL,'rotated':BOOL},['content','cursor','truncated','rotated']),'READ'),
'checksum':({'path':TEXT,'max_bytes':TRANSFER_BYTES},('path',),PATH_OUTPUT,'READ'),
'upload':({'local_path':TEXT,'remote_path':TEXT,'overwrite':BOOL,'max_bytes':TRANSFER_BYTES,'checksum':CHECKSUM},('local_path','remote_path'),PATH_OUTPUT,'WRITE'),
'download':({'remote_path':TEXT,'name':{'type':'string','minLength':1,'maxLength':255,'pattern':'^[^/\\\\]+$'},'max_bytes':TRANSFER_BYTES},('remote_path',),object_schema({'artifact':ARTIFACT_SCHEMA},['artifact']),'READ'),
'mkdir':({'path':TEXT},('path',),object_schema({'path':TEXT},['path']),'WRITE'),
'move':({'source':TEXT,'destination':TEXT,'overwrite':BOOL},('source','destination'),object_schema({'path':TEXT},['path']),'WRITE'),
'remove':({'path':TEXT,'recursive':BOOL},('path',),object_schema({'path':TEXT,'removed_count':INT},['path','removed_count']),'WRITE'),
}


class SshAction:
    def __init__(self,name,evidence):
        self.name,self.evidence=name,evidence
        props,required,output,effect=DECLARATIONS[name]
        self.spec=CapabilitySpec('ssh.'+name,'Explicit '+name+' within the configured remote root',
            object_schema({'role':ROLE,**props,'timeout_seconds':TIMEOUT},required),output,effect,
            timeout_ms=1810000,retry_safe=effect=='READ',resource_ids=('ssh.connection',))

    async def preflight(self,ctx,inputs):
        # Do not authenticate or probe commands during preflight.
        configuration(ctx)
        if 'stdin' in inputs and 'stdin_secret_ref' in inputs: raise SshError('SSH_STDIN_INVALID')
        return []

    async def execute(self,ctx,inputs):
        self.evidence.begin(ctx)
        if ctx.cancelled(): raise SshError('CANCELLED')
        await self.preflight(ctx,inputs)
        # Resolve all references before acquiring or starting a command.
        env=dict(inputs.get('env',{})); secrets=[]
        for key,ref in inputs.get('env_secret_refs',{}).items():
            value=ctx.resolve_secret(ref); env[key]=value; secrets.append(value)
        stdin=inputs.get('stdin')
        if 'stdin_secret_ref' in inputs:
            stdin=ctx.resolve_secret(inputs['stdin_secret_ref']); secrets.append(stdin)
        session=await ctx.resources.acquire('ssh.connection',inputs.get('role','default'))
        command=self.name in ('exec','run_script')
        progress={'bytes_transferred':0,'completed':[],'completed_count':0}
        try:
            if command:
                argv=inputs['argv'] if self.name=='exec' else ['/bin/sh','-c',inputs['script']]
                return await session.run(RedactingContext(ctx,secrets),argv,cwd=inputs.get('cwd','.'),env=env,
                    stdin=None if stdin is None else stdin.encode(),timeout_seconds=inputs.get('timeout_seconds',60),
                    max_output_bytes=inputs.get('max_output_bytes',65536))
            task=asyncio.create_task(self._operation(ctx,session,inputs,progress))
            deadline=time.monotonic()+inputs.get('timeout_seconds',60)
            async def stop():
                task.cancel()
                done,_=await asyncio.wait({task},timeout=5)
                if not done:
                    # A lost peer cannot hold cancellation forever. Closing
                    # the owned connection unblocks outstanding SFTP replies.
                    await session.close()
                await asyncio.gather(task,return_exceptions=True)
            try:
                while not task.done():
                    if ctx.cancelled() or time.monotonic()>=deadline:
                        await _finish(asyncio.create_task(stop()))
                        raise SshError('CANCELLED' if ctx.cancelled() else 'SSH_OPERATION_TIMEOUT',
                                       result=progress,effect_state='UNKNOWN')
                    await asyncio.wait({task},timeout=.03)
                return await task
            except asyncio.CancelledError as exc:
                await _finish(asyncio.create_task(stop()))
                exc.result=progress; exc.code='CANCELLED'; exc.effect_state='UNKNOWN'
                raise
        except asyncssh.SFTPError:
            error=SshError('SSH_SFTP_FAILED',result=progress,effect_state='UNKNOWN')
            self.evidence.capture(ctx,self.spec.id,error,command)
            raise error from None
        except (SshError,asyncio.CancelledError) as error:
            if not command and getattr(error,'result',None) is None and (progress['bytes_transferred'] or progress['completed_count']):
                error.result=progress; error.effect_state='UNKNOWN'
            self.evidence.capture(ctx,self.spec.id,error,command)
            raise

    async def _operation(self,ctx,session,inputs,progress):
        op=self.name
        if op=='check_connection':
            return {'target':session.config['host']+':'+str(session.config.get('port',22)),
                    'server_version':session.connection.get_extra_info('server_version')}
        if op=='list_directory': return await list_directory(session,inputs)
        if op=='upload': return await upload(ctx,session,inputs,progress)
        if op=='download': return await download(ctx,session,inputs,progress)
        if op in ('read_file','checksum'):
            path=await session.resolve_path(inputs['path'],must_exist=True)
            data=await read_bytes(ctx,session,path,inputs.get('max_bytes',16*1024*1024))
            result={'path':path,'size_bytes':len(data),'checksum':hashlib.sha256(data).hexdigest()}
            if op=='read_file':
                encoding=inputs.get('encoding','text')
                try: content=data.decode('utf-8') if encoding=='text' else base64.b64encode(data).decode('ascii')
                except UnicodeDecodeError: raise SshError('SSH_ENCODING_INVALID') from None
                result.update(content=content,encoding=encoding)
            return result
        if op=='read_logs':
            path=await session.resolve_path(inputs['path'],must_exist=True)
            attrs=await session.sftp.stat(path)
            if attrs.type!=asyncssh.FILEXFER_TYPE_REGULAR: raise SshError('SSH_FILE_REQUIRED')
            cursor=inputs.get('cursor',0); rotated=cursor>(attrs.size or 0)
            if rotated: cursor=0
            maximum=inputs.get('max_bytes',65536)
            async with session.sftp.open(path,'rb') as stream:
                await stream.seek(cursor); data=await stream.read(maximum+1)
            content=data[:maximum]
            return {'content':content.decode('utf-8',errors='replace'),'cursor':cursor+len(content),'truncated':len(data)>maximum,'rotated':rotated}
        path=await session.resolve_path(inputs.get('path',inputs.get('source')),must_exist=op!='mkdir')
        if op in ('move','remove'):
            path=posixpath.normpath(posixpath.join(session.root,inputs.get('path',inputs.get('source'))))
        attrs=await session.sftp.lstat(path) if op!='mkdir' else None
        if op=='stat':
            return {'path':path,'size_bytes':attrs.size,'type':attrs.type,'permissions':attrs.permissions,'mtime':attrs.mtime}
        if path==session.root: raise SshError('SSH_ROOT_REMOVE_DENIED' if op=='remove' else 'SSH_ROOT_WRITE_DENIED')
        def completed(_):
            progress['completed'].append(path)
            progress['completed_count']+=1
        if op=='mkdir': await owned(session.sftp.mkdir(path),completed)
        elif op=='move':
            target=await destination_path(session,inputs['destination'])
            if target==session.root: raise SshError('SSH_ROOT_WRITE_DENIED')
            source=path
            path=target
            if inputs.get('overwrite',False): await owned(session.sftp.posix_rename(source,target),completed)
            else: await owned(session.sftp.rename(source,target),completed)
        elif op=='remove':
            if inputs.get('recursive',False):
                await remove_tree(ctx,session,path,progress)
                return {'path':path,'removed_count':progress['completed_count']}
            if attrs.type==asyncssh.FILEXFER_TYPE_DIRECTORY: await owned(session.sftp.rmdir(path),completed)
            else: await owned(session.sftp.remove(path),completed)
        return {'path':path,'removed_count':1} if op=='remove' else {'path':path}

    async def verify(self,ctx,inputs,output): return []
