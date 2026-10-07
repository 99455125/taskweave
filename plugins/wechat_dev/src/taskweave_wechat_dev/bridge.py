"""Bounded protocol client; SDK objects and simulator ownership stay in Node."""
import asyncio
import json
import math
import re
from pathlib import Path
import time
import uuid

from taskweave.plugins.sdk import PluginError
from taskweave_process import OwnedProcessSession, RedactingContext

BRIDGE_FILE = Path(__file__).parent/'node'/'bridge.cjs'
METHODS = set(('connect disconnect current_page page_stack navigate observe get_element get_page_data tap input scroll touch call_component_method assert_page assert_element assert_page_data wait_for get_storage set_storage remove_storage clear_storage mock_method restore_mock screenshot read_logs screenshot_chunk screenshot_release').split())
MAX_LINE = 1048576

class BridgeOperationError(PluginError):
    """A matched, complete SDK failure; transport still supports cleanup."""


def require(condition, code, message=None):
    if not condition:
        raise PluginError(code, message)


def representations(values):
    patterns=set(filter(None,values));previous=list(patterns)
    for _ in range(2):
        previous=[json.dumps(v,ensure_ascii=mode)[1:-1] for v in previous for mode in (True,False)]
        patterns.update(previous)
    return tuple(sorted(patterns,key=len,reverse=True))


def mask(value, patterns):
    def redact(text):
        # A single longest-match pass avoids recursively masking the marker
        # inserted for another known literal, keeping byte growth bounded.
        if not patterns:return text
        return re.sub('|'.join(re.escape(part) for part in patterns),lambda match:'[REDACTED]',text)
    if isinstance(value,str):return redact(value)
    if isinstance(value,list):return [mask(item,patterns) for item in value]
    if isinstance(value,dict):return {redact(key):mask(item,patterns) for key,item in value.items()}
    return value


class SimulatorBridge:
    def __init__(self,ctx,process,patterns):
        self.ctx,self.process,self.patterns=ctx,process,patterns
        self.pending={};self.abandoned=set();self.closed=False;self.closing=False;self.failure=None
        self.lock=asyncio.Lock();self.close_task=None;self.cleanup={'state':'not_connected'}
        self.remote_session=None;self.remote_page=None;self.page_revision=-1
        self.tainted=False
        self.reader=asyncio.create_task(self._read())

    @classmethod
    async def start(cls,ctx,config):
        node=config.get('node_path');root=config.get('module_root')
        require(isinstance(node,str) and Path(node).is_file(),'WECHAT_PREPARATION_REQUIRED','Explicit compatible Node executable required')
        require(isinstance(root,str),'WECHAT_PREPARATION_REQUIRED','Explicit prepared pinned SDK resolution root required')
        package=Path(root)/'node_modules/miniprogram-automator/package.json'
        try:
            require(package.stat().st_size<=65536,'WECHAT_PREPARATION_REQUIRED')
            metadata=json.loads(package.read_text())
        except (OSError,ValueError):
            raise PluginError('WECHAT_PREPARATION_REQUIRED','Prepare official miniprogram-automator0.12.1 dependencies explicitly')
        require(metadata.get('name')=='miniprogram-automator' and metadata.get('version')=='0.12.1','WECHAT_SDK_VERSION_UNSUPPORTED')
        values=[ctx.resolve_secret(ref) for ref in config.get('env_secret_refs',{}).values()]
        require(len(values)<=32 and all(isinstance(value,str) and len(value)<=4096 for value in values),'WECHAT_SECRET_LIMIT')
        patterns=representations(values);env=dict(config.get('env',{}))
        env.update({name:ctx.resolve_secret(ref) for name,ref in config.get('env_secret_refs',{}).items()})
        env['TASKWEAVE_WECHAT_MODULE_ROOT']=str(Path(root).resolve())
        # Internal producer policy overwrites any caller value. Producers mask
        # complete literal/JSON representations before clipping observations.
        policy=json.dumps(patterns,ensure_ascii=True);require(len(policy.encode())<=65536,'WECHAT_SECRET_LIMIT')
        env['TASKWEAVE_WECHAT_REDACTION_PATTERNS']=policy
        project=Path(config['project_root']).resolve(strict=True)
        process=await OwnedProcessSession.start(RedactingContext(ctx,patterns),node,[str(BRIDGE_FILE)],
            cwd=str(project),env=env,max_line_bytes=MAX_LINE,max_stderr_bytes=config.get('max_output_bytes',65536))
        return cls(ctx,process,patterns)

    def _poison(self,error,*,usable=False):
        if self.failure is None:self.failure=error
        self.closed=not usable;self.tainted=True
        self.cleanup={'state':'unknown','mocks_restored':False,'window_closed':'unconfirmed'}
        for future in list(self.pending.values()):
            if not future.done():future.set_exception(error)
        if self.close_task is None:self.close_task=asyncio.create_task(self._shutdown() if usable else self._dispose())

    async def _read(self):
        try:
            while not self.closing:
                line=await self.process.read_line(timeout_seconds=1800)
                try:reply=json.loads(line.decode('utf-8'))
                except (ValueError,UnicodeError):raise PluginError('WECHAT_PROTOCOL_INVALID')
                require(isinstance(reply,dict) and set(reply) in ({'id','result'},{'id','error'}) and isinstance(reply.get('id'),str),'WECHAT_PROTOCOL_INVALID')
                if 'error' in reply:
                    error=reply['error'];require(isinstance(error,dict) and isinstance(error.get('code'),str),'WECHAT_PROTOCOL_INVALID')
                else:
                    result=reply['result'];require(isinstance(result,dict),'WECHAT_PROTOCOL_INVALID')
                if reply['id'] in self.abandoned:
                    self.abandoned.remove(reply['id']);continue
                future=self.pending.pop(reply['id'],None)
                require(future is not None and not future.done(),'WECHAT_REPLY_ID_INVALID')
                if 'error' in reply:
                    if isinstance(error.get('cleanup'),dict):self.cleanup=mask(error['cleanup'],self.patterns)
                    future.set_exception(BridgeOperationError(mask(error['code'],self.patterns)[:128],mask(str(error.get('message','Bridge operation failed')),self.patterns)[:1024]))
                else:
                    future.set_result(result)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if not self.closing:self._poison(error if isinstance(error,PluginError) else PluginError('WECHAT_PROTOCOL_FAILED'))

    async def request(self,method,params,*,timeout_seconds=60):
        require(method in METHODS,'WECHAT_METHOD_UNSUPPORTED')
        require(isinstance(params,dict) and type(timeout_seconds) in (int,float) and math.isfinite(timeout_seconds) and 0<timeout_seconds<=1800,'WECHAT_INPUT_INVALID')
        deadline=time.monotonic()+timeout_seconds
        # Waiting callers own no transport state. Expiry/cancel here cannot
        # poison the request holding the lock or dispatch a queued mutation.
        acquire=asyncio.create_task(self.lock.acquire())
        try:
            while not acquire.done():
                require(not self.ctx.cancelled(),'CANCELLED')
                remaining=deadline-time.monotonic();require(remaining>0,'WECHAT_RPC_TIMEOUT')
                await asyncio.wait([acquire],timeout=min(.02,remaining))
            acquire.result()
        except BaseException:
            acquire.cancel();await asyncio.gather(acquire,return_exceptions=True)
            if not acquire.cancelled() and acquire.exception() is None:self.lock.release()
            # A global cancellation of an idle bridge has no innocent active
            # caller to protect; finish its ownership cleanup before returning.
            if self.ctx.cancelled() and not self.lock.locked():
                self._poison(PluginError('CANCELLED'))
                if asyncio.current_task() is not self.close_task:await self.close()
            raise
        try:
            if self.ctx.cancelled():
                # This caller owns the acquired idle lock but has dispatched
                # nothing. Mark uncertainty and use the same sole close owner;
                # finally releases the lock and waits for finite reclamation.
                self._poison(PluginError('CANCELLED'))
                require(False,'CANCELLED')
            require(time.monotonic()<deadline,'WECHAT_RPC_TIMEOUT')
            return await self._request_locked(method,params,deadline)
        finally:
            self.lock.release()
            if self.close_task is not None and asyncio.current_task() is not self.close_task:
                await self.close()

    async def _request_locked(self,method,params,deadline):
        require(not self.closed and (not self.tainted or method=='disconnect'),'WECHAT_SESSION_INVALID')
        request_id=uuid.uuid4().hex
        try:line=json.dumps({'id':request_id,'method':method,'params':params},ensure_ascii=False,allow_nan=False).encode()
        except (ValueError,TypeError):raise PluginError('WECHAT_INPUT_INVALID')
        require(len(line)<=MAX_LINE,'WECHAT_REQUEST_LIMIT')
        future=asyncio.get_running_loop().create_future();self.pending[request_id]=future
        dispatched=False
        try:
            remaining=deadline-time.monotonic();require(remaining>0,'WECHAT_RPC_TIMEOUT')
            dispatched=True
            await self.process.write_line(line,timeout_seconds=remaining)
            while not future.done():
                if self.ctx.cancelled():raise PluginError('CANCELLED')
                if time.monotonic()>=deadline:raise PluginError('WECHAT_RPC_TIMEOUT')
                await asyncio.wait([future],timeout=.02)
            result=future.result()
            require(set(result)=={'session_id','page_path','page_revision','result'} and isinstance(result['session_id'],str) and re.fullmatch(r'[A-Za-z0-9-]{1,128}',result['session_id']) is not None and type(result['page_revision']) is int and result['page_revision']>=0 and (result['page_path'] is None or isinstance(result['page_path'],str)) and isinstance(result['result'],dict),'WECHAT_PROTOCOL_INVALID')
            require(self.remote_session in (None,result['session_id']) and result['page_revision']>=self.page_revision,'WECHAT_REPLY_IDENTITY_INVALID')
            if params.get('session_id') is not None:require(params['session_id']==result['session_id'],'WECHAT_REPLY_IDENTITY_INVALID')
            if params.get('page_revision') is not None and method not in ('navigate','wait_for','disconnect'):require(params['page_revision']==result['page_revision'],'WECHAT_REPLY_IDENTITY_INVALID')
            self.remote_session=result['session_id'];self.remote_page=result['page_path'];self.page_revision=result['page_revision']
            if method=='screenshot_chunk':
                # Complete binary evidence is not a textual observation.
                encoded=result['result'].get('data');result=mask(result,self.patterns);result['result']['data']=encoded
            else:result=mask(result,self.patterns)
            if method=='connect':self.cleanup={'state':'not_connected'}
            if method=='disconnect':self.cleanup=result.get('result',{'state':'unknown'})
            return result
        except BaseException as error:
            self.pending.pop(request_id,None)
            if not future.done():future.cancel()
            elif not future.cancelled():future.exception()
            if not dispatched:raise
            if isinstance(error,BridgeOperationError):
                if error.code=='WECHAT_SDK_TIMEOUT':
                    self.tainted=True
                    if self.close_task is None:self.close_task=asyncio.create_task(self._shutdown())
                raise
            # Even a READ timeout leaves the SDK connection untrustworthy.
            # No request is replayed; future protocol traffic cannot revive it.
            usable=isinstance(error,asyncio.CancelledError) and not self.ctx.cancelled() and not self.process.closed and not self.reader.done()
            if usable:self.abandoned.add(request_id)
            self._poison(error if isinstance(error,PluginError) else PluginError('WECHAT_TRANSPORT_FAILED'),usable=usable)
            raise

    async def _dispose(self):
        self.closed=True;self.closing=True
        if not self.reader.done():self.reader.cancel()
        await self.process.close()
        await asyncio.gather(self.reader,return_exceptions=True)

    async def _shutdown(self):
        if not self.closed and self.cleanup.get('state') not in ('disconnected','partial'):
            try:
                reply=await self.request('disconnect',{},timeout_seconds=5)
                self.cleanup=reply.get('result',{'state':'unknown'})
            except BaseException:
                self.cleanup={'state':'unknown','mocks_restored':False,'window_closed':'unconfirmed'}
        await self._dispose()

    async def close(self):
        if self.close_task is None:self.close_task=asyncio.create_task(self._shutdown())
        while not self.close_task.done():
            try:await asyncio.shield(self.close_task)
            except asyncio.CancelledError:continue
        self.close_task.result()
