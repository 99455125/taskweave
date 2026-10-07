"""Reusable SSH sessions, independent of enabled SSH plugin actions."""
import asyncio
import os
import re
import shlex
import time
import asyncssh
from taskweave_process.runner import redact_text, validate_limits
from .paths import SshError, resolve_path


CONFIG_KEYS=('host','port','username','known_hosts','key_path','key_passphrase_ref','password_ref',
             'use_agent','agent_path','remote_root','local_root','timeout_seconds')


def configuration(ctx):
    values={**ctx.environment, **ctx.task_parameters}
    return {key:values['ssh_'+key] for key in CONFIG_KEYS if 'ssh_'+key in values}


async def _finish(task):
    """Recover ownership even if cancellation lands during resource creation."""
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
        except Exception:
            break
    return task.result()


async def connect_ssh(ctx, config: dict):
    if ctx.cancelled():
        raise SshError('CANCELLED')
    if not isinstance(config,dict) or set(config)-set(CONFIG_KEYS):
        raise SshError('SSH_CONFIG_INVALID')
    for key in ('host','username','remote_root'):
        if not isinstance(config.get(key),str) or not config[key] or '\0' in config[key]:
            raise SshError('SSH_CONFIG_INVALID')
    port=config.get('port',22)
    timeout=config.get('timeout_seconds',60)
    if type(port) is not int or not 1<=port<=65535 or type(timeout) is not int or not 1<=timeout<=1800:
        raise SshError('SSH_CONFIG_INVALID')
    known_hosts=config.get('known_hosts',os.path.expanduser('~/.ssh/known_hosts'))
    if not isinstance(known_hosts,str) or not known_hosts or not os.path.isfile(os.path.expanduser(known_hosts)):
        raise SshError('SSH_KNOWN_HOSTS_REQUIRED')
    if not config['remote_root'].startswith('/'):
        raise SshError('SSH_CONFIG_INVALID','remote_root must be an absolute POSIX path')
    use_agent=config.get('use_agent',False)
    if type(use_agent) is not bool:
        raise SshError('SSH_CONFIG_INVALID')
    agent_path=config.get('agent_path',os.getenv('SSH_AUTH_SOCK')) if use_agent else None
    if use_agent and (not isinstance(agent_path,str) or not agent_path):
        raise SshError('SSH_AGENT_UNAVAILABLE')
    values=[]
    password=None
    if config.get('password_ref'):
        password=ctx.resolve_secret(config['password_ref']); values.append(password)
    passphrase=None
    if config.get('key_passphrase_ref'):
        passphrase=ctx.resolve_secret(config['key_passphrase_ref']); values.append(passphrase)
    keys=[]
    if config.get('key_path'):
        try:
            keys=[asyncssh.read_private_key(os.path.expanduser(config['key_path']),passphrase)]
        except (OSError,ValueError,asyncssh.Error):
            raise SshError('SSH_KEY_INVALID') from None
    connection=None
    success=False
    task=asyncio.ensure_future(asyncssh.connect(config['host'],port=port,username=config['username'],
        known_hosts=os.path.expanduser(known_hosts), client_keys=keys,password=password,
        agent_path=agent_path,agent_forwarding=False,config=None,
        preferred_auth=('publickey','password'),connect_timeout=timeout,login_timeout=timeout))
    try:
        deadline=time.monotonic()+timeout
        while not task.done():
            if ctx.cancelled() or time.monotonic()>=deadline:
                task.cancel()
                raise SshError('CANCELLED' if ctx.cancelled() else 'SSH_CONNECT_TIMEOUT')
            await asyncio.wait({task},timeout=.05)
        connection=await task
        async def stage(awaitable):
            pending=asyncio.ensure_future(awaitable)
            try:
                while not pending.done():
                    if ctx.cancelled() or time.monotonic()>=deadline:
                        raise SshError('CANCELLED' if ctx.cancelled() else 'SSH_CONNECT_TIMEOUT')
                    await asyncio.wait({pending},timeout=.03)
                return await pending
            finally:
                if not pending.done(): pending.cancel()
                await asyncio.gather(pending,return_exceptions=True)
        sftp=await stage(connection.start_sftp_client())
        root=await stage(sftp.realpath(config['remote_root']))
        attrs=await stage(sftp.stat(root))
        if attrs.type != asyncssh.FILEXFER_TYPE_DIRECTORY:
            raise SshError('SSH_ROOT_INVALID')
        if ctx.cancelled(): raise SshError('CANCELLED')
        success=True
        return SshSession(connection,sftp,root,config,values)
    except asyncio.CancelledError:
        if not task.done(): task.cancel()
        if connection is None:
            try: connection=await _finish(task)
            except (Exception,asyncio.CancelledError): pass
        raise
    except asyncssh.HostKeyNotVerifiable:
        raise SshError('SSH_HOST_KEY_INVALID') from None
    except asyncssh.PermissionDenied:
        raise SshError('SSH_AUTH_FAILED') from None
    except (asyncio.TimeoutError,TimeoutError):
        raise SshError('SSH_CONNECT_TIMEOUT') from None
    except (asyncssh.Error,OSError):
        raise SshError('SSH_CONNECT_FAILED') from None
    finally:
        # Failed attempts cannot leak handles, including cancelled handshakes.
        if task.cancelled() or not task.done():
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
        if connection is not None and not success:
            connection.close()
            await connection.wait_closed()


class SshSession:
    def __init__(self,connection,sftp,root,config,secrets):
        self.connection,self.sftp,self.root=connection,sftp,root
        self.config=dict(config)
        self.redaction_values=tuple(secrets)
        self.closed=False

    async def close(self):
        if not self.closed:
            self.closed=True
            self.connection.close()
            await self.connection.wait_closed()

    async def resolve_path(self,path: str, *, must_exist: bool):
        return await resolve_path(self.sftp,self.root,path,must_exist=must_exist)

    async def run(self,ctx,argv: list[str], *, cwd: str,env: dict,stdin: bytes | None,
                  timeout_seconds: int=60,max_output_bytes: int=65536):
        started=time.monotonic()
        validate_limits(timeout_seconds,max_output_bytes)
        deadline=started+timeout_seconds
        if ctx.cancelled(): raise SshError('CANCELLED')
        if not isinstance(argv,list) or not argv or any(not isinstance(x,str) or '\0' in x for x in argv):
            raise SshError('SSH_ARGV_INVALID')
        if not isinstance(env,dict) or any(not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',key) or not isinstance(value,str) or '\0' in value for key,value in env.items()):
            raise SshError('SSH_ENV_INVALID')
        async def prepare(awaitable):
            pending=asyncio.ensure_future(awaitable)
            try:
                while True:
                    if ctx.cancelled() or time.monotonic()>=deadline:
                        raise SshError('CANCELLED' if ctx.cancelled() else 'SSH_COMMAND_TIMEOUT')
                    if pending.done(): return await pending
                    await asyncio.wait({pending},timeout=.03)
            finally:
                if not pending.done(): pending.cancel()
                await asyncio.gather(pending,return_exceptions=True)
        try:
            directory=await prepare(self.resolve_path(cwd,must_exist=True))
            if (await prepare(self.sftp.stat(directory))).type != asyncssh.FILEXFER_TYPE_DIRECTORY:
                raise SshError('SSH_DIRECTORY_INVALID')
        except asyncio.CancelledError as exc:
            exc.result=None; exc.effect_state='NOT_STARTED'; exc.code='CANCELLED'
            raise
        # Remote exec necessarily invokes the server's shell. Every token is
        # quoted; env assignments are arguments to env, not shell syntax.
        command='cd '+shlex.quote(directory)+' && exec env -- '+shlex.join([key+'='+value for key,value in env.items()]+argv)
        secrets=self.redaction_values+tuple(getattr(ctx,'redaction_values',()))
        capture=max_output_bytes+max((len(x.encode()) for x in secrets),default=0)
        buffers={key:bytearray() for key in ('stdout','stderr')}; totals={key:0 for key in buffers}
        process=None
        tasks=[]
        def result():
            output={'exit_code':process.exit_status if process and process.exit_status is not None and process.exit_status>=0 else None,
                    'duration_ms':round((time.monotonic()-started)*1000)}
            for key in buffers:
                text=redact_text(bytes(buffers[key]).decode('utf-8',errors='replace'),secrets).encode()
                output[key]=text[:max_output_bytes].decode('utf-8',errors='ignore')
                output[key+'_truncated']=totals[key]>max_output_bytes or len(text)>max_output_bytes
            return output
        async def drain(stream,key):
            while data:=await stream.read(8192):
                totals[key]+=len(data)
                buffers[key].extend(data[:max(0,capture-len(buffers[key]))])
        async def feed():
            try:
                if stdin:
                    process.stdin.write(stdin); await process.stdin.drain()
            except (asyncssh.Error,BrokenPipeError,ConnectionResetError): pass
            finally: process.stdin.write_eof()
        if ctx.cancelled() or time.monotonic()>=deadline:
            raise SshError('CANCELLED' if ctx.cancelled() else 'SSH_COMMAND_TIMEOUT')
        spawn=asyncio.ensure_future(self.connection.create_process(command,encoding=None))
        async def cleanup():
            nonlocal process
            if process is None:
                await self.close()
                try: process=await _finish(spawn)
                except (Exception,asyncio.CancelledError): pass
            if process is not None:
                try: process.terminate()
                except (asyncssh.Error,OSError): pass
                process.close()
            await self.close()
            for task in tasks:
                if not task.done(): task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
        try:
            while not spawn.done():
                if ctx.cancelled() or time.monotonic()>=deadline:
                    await cleanup()
                    raise SshError('CANCELLED' if ctx.cancelled() else 'SSH_COMMAND_TIMEOUT',result=result(),effect_state='UNKNOWN')
                await asyncio.wait({spawn},timeout=.03)
            process=await asyncio.shield(spawn)
            tasks=[asyncio.create_task(drain(process.stdout,'stdout')),asyncio.create_task(drain(process.stderr,'stderr')),
                   asyncio.create_task(feed()),asyncio.create_task(process.wait_closed())]
            complete=asyncio.gather(*tasks,return_exceptions=True)
            while not complete.done():
                if ctx.cancelled() or time.monotonic()>=deadline:
                    await cleanup()
                    raise SshError('CANCELLED' if ctx.cancelled() else 'SSH_COMMAND_TIMEOUT',result=result(),effect_state='UNKNOWN')
                await asyncio.wait({complete},timeout=.03)
            if any(isinstance(item,BaseException) for item in await complete):
                raise SshError('SSH_COMMAND_FAILED',result=result(),effect_state='UNKNOWN')
            output=result()
            ctx.log('INFO',f'ssh exit_code={output["exit_code"]} stdout_truncated={output["stdout_truncated"]} stderr_truncated={output["stderr_truncated"]}')
            return output
        except asyncio.CancelledError as exc:
            await _finish(asyncio.create_task(cleanup()))
            exc.result=result(); exc.effect_state='UNKNOWN'; exc.code='CANCELLED'
            raise
        except (asyncssh.Error,OSError):
            await cleanup()
            raise SshError('SSH_COMMAND_FAILED',result=result(),effect_state='UNKNOWN') from None
        finally:
            for task in tasks:
                if not task.done(): task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
