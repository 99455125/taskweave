"""Site-owned local/SSH execution, file bounds and cumulative attempt receipts."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import posixpath
import re
import stat
import tempfile
import time
import uuid

from taskweave.plugins.sdk import PluginError, ResultRequest
from taskweave_process.runner import run_command, validate_limits
from taskweave_process.context import RedactingContext
from taskweave_process.artifacts import read_artifact, stage_artifact
from taskweave_ssh.transport import connect_ssh
from .commands import require

CONFIG_KEYS=('mode','site_path','wp_path','php_path','local_root','ssh','max_output_bytes','timeout_seconds','max_transfer_bytes','owned_tables','secret_refs')


def configuration(ctx):
    values={**ctx.environment,**ctx.task_parameters}
    return {key:values['wordpress_'+key] for key in CONFIG_KEYS if 'wordpress_'+key in values}


class WriteEvidence:
    """No command/argv/stdin persisted; reserve bounded metadata before a write."""
    MAX_ATTEMPTS=32
    MAX_OWNERS=128
    MAX_WRITES=96
    def __init__(self):
        self.journals={};self.owners={}
    def begin(self,ctx,owner):
        attempt=ctx.scope.attempt_id
        require(id(owner) in self.owners or len(self.owners)<self.MAX_OWNERS,'WORDPRESS_DIAGNOSTIC_CAPACITY')
        previous=self.owners.get(id(owner)); self.owners[id(owner)]=attempt
        if previous!=attempt and previous not in self.owners.values(): self.journals.pop(previous,None)
        require(attempt in self.journals or len(self.journals)<self.MAX_ATTEMPTS,'WORDPRESS_DIAGNOSTIC_CAPACITY')
        self.journals.setdefault(attempt,{'effect_state':'UNKNOWN','requests':[]})
    def dispatch(self,ctx,name,role,stage):
        journal=self.journals[ctx.scope.attempt_id]
        require(len(journal['requests'])<self.MAX_WRITES,'WORDPRESS_DIAGNOSTIC_CAPACITY')
        role=role if re.fullmatch(r'[A-Za-z0-9_.-]{1,64}',role) else hashlib.sha256(role.encode()).hexdigest()
        entry={'action_id':'wordpress.'+name,'role':role,'stage':stage[:64],'sequence':len(journal['requests'])+1,'completion':'unknown'}
        journal['requests'].append(entry);return entry
    def capture(self,ctx,error,result=None):
        journal=self.journals.get(ctx.scope.attempt_id)
        if journal is not None:
            journal['error_code']=getattr(error,'code','CANCELLED' if isinstance(error,asyncio.CancelledError) else 'WORDPRESS_FAILED')[:128]
            if result:
                # Safe already-redacted output is only an observation; avoid
                # unbounded diagnostics when concurrent role replies accumulate.
                journal['last_command']={k:(v[:256] if isinstance(v,str) else v) for k,v in result.items() if k in ('exit_code','stdout','stderr','stdout_truncated','stderr_truncated')}
    async def results(self,ctx,error):
        journal=self.journals.get(ctx.scope.attempt_id)
        if not journal or not journal['requests']: return []
        payload=json.loads(json.dumps(journal))
        return [ResultRequest('wordpress.operation_failure','wordpress_operation_failure',payload)]
    def close(self,owner):
        previous=self.owners.pop(id(owner),None)
        if previous not in self.owners.values(): self.journals.pop(previous,None)


class SiteTransport:
    def __init__(self,config,evidence=None):
        require(isinstance(config,dict) and not set(config)-set(CONFIG_KEYS),'WORDPRESS_CONFIG_INVALID')
        require(config.get('mode','local') in ('local','ssh') and isinstance(config.get('site_path'),str),'WORDPRESS_CONFIG_INVALID')
        self.config=dict(config);self.session=None;self.evidence=evidence
        self.root=None;self.site=None;self.busy=False;self.previews={}
        self.current_action=None;self.role='default';self.deadline=None;self.scratch_files={};self.scratch_receipts={}
    async def open(self,ctx):
        if self.config.get('mode','local')=='ssh':
            self.session=await connect_ssh(ctx,self.config.get('ssh',{}))
            try:
                self.root=self.session.root
                self.site=await self.session.resolve_path(self.config['site_path'],must_exist=True)
                attrs=await self.session.sftp.stat(self.site)
                require(stat.S_ISDIR(attrs.permissions),'WORDPRESS_SITE_INVALID')
            except BaseException:
                await self.session.close();raise
        else:
            try:
                self.root=Path(self.config.get('local_root',self.config['site_path'])).expanduser().resolve(strict=True)
                self.site=Path(self.config['site_path']).expanduser().resolve(strict=True)
                self.site.relative_to(self.root)
                require(self.root.is_dir() and self.site.is_dir(),'WORDPRESS_SITE_INVALID')
            except (OSError,ValueError,RuntimeError): raise PluginError('WORDPRESS_SITE_INVALID') from None
        return self
    async def close(self):
        if self.session: await self.session.close()
        if self.evidence: self.evidence.close(self)
    def start(self,ctx,name,role,inputs):
        self.current_action=name;self.role=role
        self.deadline=time.monotonic()+inputs.get('timeout_seconds',self.config.get('timeout_seconds',60))
        self.max_output=inputs.get('max_output_bytes',self.config.get('max_output_bytes',65536))
        validate_limits(inputs.get('timeout_seconds',self.config.get('timeout_seconds',60)),self.max_output)
        if self.evidence: self.evidence.begin(ctx,self)
    def remaining(self):
        remaining=(self.deadline-time.monotonic()) if self.deadline else self.config.get('timeout_seconds',60)
        require(remaining>0,'WORDPRESS_TIMEOUT')
        return max(1,int(remaining))
    async def path(self,path,*,must_exist=True,site_only=False):
        if self.session:
            try: resolved=await self.session.resolve_path(path,must_exist=must_exist)
            except PluginError as exc:
                if exc.code=='SSH_PATH_NOT_FOUND': raise PluginError('WORDPRESS_PATH_NOT_FOUND') from None
                raise
            if site_only: require(resolved==self.site or resolved.startswith(self.site.rstrip('/')+'/'),'WORDPRESS_PATH_INVALID')
            return resolved
        try:
            value=Path(path)
            resolved=(self.root/value).resolve(strict=must_exist)
            resolved.relative_to(self.site if site_only else self.root)
            return str(resolved)
        except FileNotFoundError: raise PluginError('WORDPRESS_PATH_NOT_FOUND') from None
        except (OSError,ValueError,RuntimeError): raise PluginError('WORDPRESS_PATH_INVALID') from None
    async def scratch(self,ctx):
        """Reserve bounded cleanup evidence before creating any owned file."""
        entry=self.evidence.dispatch(ctx,self.current_action,self.role,'scratch_cleanup') if self.evidence else None
        if entry: entry['completion']='not_started'
        if self.session:
            directory='/tmp/taskweave-wp-'+uuid.uuid4().hex
            await self.session.sftp.mkdir(directory,attrs=__import__('asyncssh').SFTPAttrs(permissions=0o700))
        else: directory=tempfile.mkdtemp(prefix='taskweave-wp-')
        path=directory+'/database.sql';self.scratch_files[path]=directory;self.scratch_receipts[path]=entry
        if entry: entry['completion']='unknown'
        return path
    async def cleanup_scratch(self,ctx,path):
        entry=self.scratch_receipts.get(path)
        try:
            await self.delete(path)
            directory=self.scratch_files[path]
            if self.session: await self.session.sftp.rmdir(directory)
            else: os.rmdir(directory)
            del self.scratch_files[path];self.scratch_receipts.pop(path,None)
            if entry: entry['completion']='completed'
        except BaseException as exc:
            if self.evidence: self.evidence.capture(ctx,PluginError('WORDPRESS_SCRATCH_CLEANUP_FAILED'))
            raise PluginError('WORDPRESS_SCRATCH_CLEANUP_FAILED') from exc
    async def read(self,path,max_bytes):
        require(type(max_bytes) is int and 1<=max_bytes<=67108864,'WORDPRESS_TRANSFER_LIMIT_INVALID')
        resolved=path if path in self.scratch_files else await self.path(path)
        if not self.session and path in self.scratch_files:
            require(Path(path).stat().st_size<=max_bytes,'WORDPRESS_FILE_TOO_LARGE')
            return Path(path).read_bytes()
        if not self.session: return (await asyncio.to_thread(read_artifact,str(self.root),resolved,max_bytes))[1]
        attrs=await self.session.sftp.stat(resolved)
        require(stat.S_ISREG(attrs.permissions) and attrs.size<=max_bytes,'WORDPRESS_FILE_TOO_LARGE')
        async with self.session.sftp.open(resolved,'rb') as source:
            data=await source.read(max_bytes+1)
        require(len(data)<=max_bytes and len(data)==attrs.size,'WORDPRESS_FILE_TOO_LARGE')
        return data
    async def write(self,path,data,mode=0o600):
        scratch=path in self.scratch_files
        resolved=path if scratch else await self.path(path,must_exist=False,site_only=True)
        require(len(data)<=67108864,'WORDPRESS_FILE_TOO_LARGE')
        parent=posixpath.dirname(resolved)
        if self.session:
            await self.session.sftp.makedirs(parent,exist_ok=True)
            if not scratch: await self.path(parent,site_only=True)
            async with self.session.sftp.open(resolved,'wb') as target: await target.write(data)
            await self.session.sftp.chmod(resolved,mode&0o777)
        else:
            Path(parent).mkdir(parents=True,exist_ok=True)
            if not scratch: await self.path(parent,site_only=True)
            descriptor=os.open(resolved,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,mode&0o777)
            with os.fdopen(descriptor,'wb') as target: target.write(data)
            os.chmod(resolved,mode&0o777)
    async def mkdir(self,path,mode=0o755):
        resolved=await self.path(path,must_exist=False,site_only=True)
        if self.session:
            await self.session.sftp.makedirs(resolved,exist_ok=True)
            await self.path(resolved,site_only=True)
            await self.session.sftp.chmod(resolved,mode&0o777)
        else:
            Path(resolved).mkdir(parents=True,exist_ok=True)
            await self.path(resolved,site_only=True)
            os.chmod(resolved,mode&0o777)

    async def delete(self,path):
        resolved=path if path in self.scratch_files else await self.path(path,site_only=True)
        try:
            if self.session: await self.session.sftp.remove(resolved)
            else: Path(resolved).unlink()
        except (FileNotFoundError,__import__('asyncssh').SFTPNoSuchFile):
            if path not in self.scratch_files: raise
    async def files(self,max_bytes,max_members,member_bytes=67108864):
        result={}; total=0; self.snapshot_directories={}
        async def walk(directory,prefix=''):
            nonlocal total
            if self.session:
                entries=[(entry.filename,entry.attrs) for entry in await self.session.sftp.readdir(directory) if entry.filename not in ('.','..')]
            else:
                entries=[(entry.name,entry.lstat()) for entry in Path(directory).iterdir()]
            for name,attrs in sorted(entries,key=lambda item:item[0]):
                require(name not in ('.','..') and '/' not in name and '\\' not in name,'WORDPRESS_PATH_INVALID')
                mode=attrs.permissions if self.session else attrs.st_mode
                require(not stat.S_ISLNK(mode),'WORDPRESS_BACKUP_LINK_REJECTED')
                path=posixpath.join(directory,name); relative=prefix+name
                require(len(result)+len(self.snapshot_directories)<max_members,'WORDPRESS_BACKUP_MEMBER_LIMIT')
                if stat.S_ISDIR(mode):
                    self.snapshot_directories[relative]=mode&0o777
                    await walk(path,relative+'/')
                else:
                    require(stat.S_ISREG(mode),'WORDPRESS_BACKUP_SPECIAL_FILE_REJECTED')
                    require(len(result)<max_members,'WORDPRESS_BACKUP_MEMBER_LIMIT')
                    data=await self.read(path,min(member_bytes,max_bytes-total));total+=len(data)
                    require(total<=max_bytes,'WORDPRESS_BACKUP_TOO_LARGE')
                    result[relative]=(data,mode&0o777)
        await walk(str(self.site));return result
    async def execute(self,ctx,command,*,stdin=None,secrets=(),parse_json=False,write=False,allow_exit=()):
        require(not ctx.cancelled(),'CANCELLED')
        if self.site is None: await self.open(ctx)
        refs=self.config.get('secret_refs',{})
        require(isinstance(refs,dict) and all(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',key) and isinstance(value,str) for key,value in refs.items()),'WORDPRESS_SECRET_REFS_INVALID')
        env={key:ctx.resolve_secret(value) for key,value in refs.items()}
        safe=RedactingContext(ctx,tuple(secrets)+tuple(env.values()))
        argv=([self.config['php_path']] if self.config.get('php_path') else [])+[self.config.get('wp_path','wp'),'--path='+str(self.site),'--no-color',*command]
        entry=self.evidence.dispatch(ctx,self.current_action,self.role,' '.join(command[:2])) if write and self.evidence else None
        result=None
        try:
            options={'cwd':str(self.site),'env':env,'stdin':stdin,'timeout_seconds':self.remaining(),'max_output_bytes':getattr(self,'max_output',self.config.get('max_output_bytes',65536))}
            result=await self.session.run(safe,argv,**options) if self.session else await run_command(safe,argv[0],argv[1:],**options)
            require(result['exit_code']==0 or result['exit_code'] in allow_exit,'WORDPRESS_COMMAND_FAILED')
            if parse_json:
                require(not result['stdout_truncated'] and not result['stderr_truncated'],'WORDPRESS_OUTPUT_TRUNCATED')
                try: result['data']=json.loads(result['stdout'])
                except (ValueError,TypeError): raise PluginError('WORDPRESS_JSON_INVALID') from None
            if entry: entry['completion']='completed'
            return result
        except BaseException as exc:
            if self.evidence: self.evidence.capture(ctx,exc,result or getattr(exc,'result',None))
            raise


def prompt_input(ctx,secret_inputs):
    require(isinstance(secret_inputs,dict) and len(secret_inputs)<=1,'WORDPRESS_SECRET_INPUT_INVALID')
    values=[]
    for field,ref in secret_inputs.items():
        require(field in ('admin_password','dbpass','user_pass','config_value'),'WORDPRESS_SECRET_INPUT_INVALID')
        value=ctx.resolve_secret(ref)
        require(isinstance(value,str) and value not in ('','0') and not any(c in value for c in '\x00\r\n') and len(value.encode())<=1023,'WORDPRESS_SECRET_INPUT_INVALID')
        values.append(value)
    stdin=(values[0]+('\nY\nn\n\n\n\n' if 'config_value' in secret_inputs else '\n')).encode() if values else None
    return stdin,values


async def run_wp(ctx,config:dict,command:list[str],*,secret_inputs:dict,parse_json:bool)->dict:
    """Reusable single command with resource cleanup; actions reuse owned transport."""
    stdin,values=prompt_input(ctx,secret_inputs)
    site=SiteTransport(config)
    try:
        return await site.execute(ctx,command,stdin=stdin,secrets=values,parse_json=parse_json)
    finally: await site.close()
