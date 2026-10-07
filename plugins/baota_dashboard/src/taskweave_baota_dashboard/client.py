"""Owned async transport with POST signing, TLS verification and bounded reads."""
import asyncio
import hashlib
import json
import math
import re
import ssl
import time
from urllib.parse import urlsplit
import httpx
from taskweave.plugins.sdk import PluginError
from .endpoints import ENDPOINTS, DOWNLOAD, SUPPORTED_VERSION, PROFILE

SUMMARY_FIELDS=('status','siteStatus','siteId','ftpStatus','databaseStatus','index','msg')
SUMMARY_CHAR_LIMIT=128

CONFIG_KEYS=('url','api_secret_ref','ca_file','allow_http','timeout_seconds','max_response_bytes')
SENSITIVE={'password','ftppass','databasepass','key','private_key','privatekey','api_secret','mysql_root','request_token','token','secret','dns','auths','authorizations','shell','other','panel','admin_path','csr','cert','fullchain','ca'}

class BaotaError(PluginError):
    pass


def redact(value,secrets=()):
    if isinstance(value,dict):
        return {k:redact(v,secrets) for k,v in value.items() if (k=='password_changed' and type(v) is bool) or (str(k).lower() not in SENSITIVE and not any(x in str(k).lower() for x in ('password','private_key','secret','credential')))}
    if isinstance(value,list): return [redact(v,secrets) for v in value]
    if isinstance(value,str):
        value=re.sub(r'-----BEGIN (?:[A-Z ]*PRIVATE KEY)-----.*?-----END (?:[A-Z ]*PRIVATE KEY)-----','[REDACTED]',value,flags=re.S)
        for secret in sorted((s for s in secrets if s),key=len,reverse=True): value=value.replace(secret,'[REDACTED]')
    return value


def configuration(ctx):
    merged={**ctx.environment,**ctx.task_parameters}
    return {k:merged['baota_'+k] for k in CONFIG_KEYS if 'baota_'+k in merged}


class PanelClient:
    def __init__(self,config):
        self.config=dict(config); self.url=self.config.get('url','').rstrip('/')
        parsed=urlsplit(self.url)
        if parsed.scheme not in ('https','http') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
            raise BaotaError('BAOTA_URL_INVALID')
        if parsed.scheme=='http' and self.config.get('allow_http') is not True: raise BaotaError('BAOTA_TLS_REQUIRED')
        if not self.config.get('api_secret_ref'): raise BaotaError('BAOTA_SECRET_REFERENCE_REQUIRED')
        try: verify=ssl.create_default_context(cafile=self.config.get('ca_file'))
        except (OSError,ssl.SSLError) as error: raise BaotaError('BAOTA_CA_INVALID') from error
        self.transport=httpx.AsyncClient(verify=verify,follow_redirects=False,trust_env=False,headers={'Accept-Encoding':'identity'})
        self.version=None; self.secrets=[]; self.used_bytes=0; self.max_bytes=16777216; self.timeout=60
        self.sent_writes=[]; self.busy=False; self.write_observer=None; self.write_finalizer=None
    async def close(self): await self.transport.aclose()
    def start_operation(self,inputs):
        self.used_bytes=0; self.sent_writes=[]
        self.timeout=inputs.get('timeout_seconds',self.config.get('timeout_seconds',60))
        self.max_bytes=inputs.get('max_response_bytes',self.config.get('max_response_bytes',16777216))
        if type(self.timeout) is not int or not 1<=self.timeout<=1800 or type(self.max_bytes) is not int or not 1024<=self.max_bytes<=67108864: raise BaotaError('BAOTA_BUDGET_INVALID')
    def secret(self,ctx,reference):
        value=ctx.resolve_secret(reference)
        if not isinstance(value,str) or not value: raise BaotaError('SECRET_UNAVAILABLE')
        if value not in self.secrets: self.secrets.append(value)
        return value
    async def _request(self,ctx,spec,params,*,binary=False,max_bytes=None,on_send=None,on_response=None):
        if ctx.cancelled(): raise BaotaError('CANCELLED')
        if set(params)-set(spec.fields)-set(spec.fixed_params) or any(str(params[k])!=str(v) for k,v in spec.fixed_params.items() if k in params): raise BaotaError('BAOTA_ENDPOINT_PARAMETERS_INVALID')
        secret=self.secret(ctx,self.config['api_secret_ref']); timestamp=str(int(time.time()))
        fields={**spec.fixed_params,**params,'request_time':timestamp,'request_token':hashlib.md5((timestamp+hashlib.md5(secret.encode()).hexdigest()).encode()).hexdigest()}

        # Values are form-encoded by httpx; there is no caller-supplied endpoint.
        limit=min(max_bytes if max_bytes is not None else self.max_bytes,self.max_bytes-self.used_bytes)
        if limit<0: raise BaotaError('BAOTA_RESPONSE_TOO_LARGE')
        request_kwargs={'params':fields} if spec.method=='GET' else {'params':{'action':spec.action},'data':{k:str(v) for k,v in fields.items()}}
        try:
            async with asyncio.timeout(self.timeout) if hasattr(asyncio,'timeout') else _Timeout(self.timeout):
                if on_send: on_send()
                async with self.transport.stream(spec.method,self.url+spec.path,timeout=self.timeout,**request_kwargs) as response:
                    if 300<=response.status_code<400: raise BaotaError('BAOTA_REDIRECT_REJECTED')
                    if response.status_code!=200: raise BaotaError('BAOTA_HTTP_ERROR')
                    if response.headers.get('Content-Encoding','identity').lower()!='identity': raise BaotaError('BAOTA_RESPONSE_INVALID')
                    chunks=[]; size=0
                    async for chunk in response.aiter_bytes():
                        if ctx.cancelled(): raise BaotaError('CANCELLED')
                        size+=len(chunk)
                        if size>limit: raise BaotaError('BAOTA_RESPONSE_TOO_LARGE')
                        chunks.append(chunk)
                    self.used_bytes+=size; data=b''.join(chunks)
        except (httpx.HTTPError,TimeoutError) as error: raise BaotaError('BAOTA_TRANSPORT_FAILED') from error
        if binary: return data
        try: result=json.loads(data)
        except (ValueError,UnicodeError) as error: raise BaotaError('BAOTA_RESPONSE_INVALID') from error
        self._remember_secrets(result)
        if on_response: on_response(result)
        if spec.action in ('GetSiteLogs','get_site_errlog') and isinstance(result,dict) and result.get('status') is False and result.get('msg')=='日志为空':
            return {'status':True,'msg':'','availability':'missing'}
        if isinstance(result,dict) and result.get('status') is False and spec.action!='GetSSL':
            raise BaotaError('BAOTA_BUSINESS_FAILED',str(redact(result.get('msg','Operation rejected'),self.secrets))[:2048])
        return result
    def _remember_secrets(self,value):
        if isinstance(value,list):
            for item in value: self._remember_secrets(item)
        elif isinstance(value,dict):
            for key,item in value.items():
                if str(key).lower() in SENSITIVE and isinstance(item,str) and item and str(key).lower() not in ('shell','other','panel','csr','cert','ca','fullchain'):
                    if item not in self.secrets: self.secrets.append(item)
                else: self._remember_secrets(item)

    async def request(self,ctx,endpoint:str,params:dict,*,response_kind:str)->dict|list:
        if endpoint not in ENDPOINTS: raise BaotaError('BAOTA_DASHBOARD_CAPABILITY_UNSUPPORTED')
        spec=ENDPOINTS[endpoint]
        if response_kind!=spec.response_kind: raise BaotaError('BAOTA_RESPONSE_KIND_INVALID')
        result=await self._request(ctx,spec,params)
        if result is None and endpoint in ('access_log','error_log'): return {'status':True,'msg':'','availability':'unavailable'}
        if not isinstance(result,list if response_kind=='array' else dict): raise BaotaError('BAOTA_RESPONSE_INVALID')
        return result
    async def identify(self,ctx):
        total=await self.request(ctx,'system',{},response_kind='object')
        if not isinstance(total.get('version'),str) or not isinstance(total.get('system'),str): raise BaotaError('BAOTA_RESPONSE_INVALID')
        self.version=total['version']
        if self.version!=SUPPORTED_VERSION: raise BaotaError('BAOTA_DASHBOARD_CAPABILITY_UNSUPPORTED','Only Chinese LinuxPanel 11.7.0 is supported')
        return total
    async def call(self,ctx,endpoint,params=None):
        return await self.request(ctx,endpoint,params or {},response_kind=ENDPOINTS[endpoint].response_kind)
    async def write(self,ctx,endpoint,params):
        if self.version!=SUPPORTED_VERSION: raise BaotaError('BAOTA_DASHBOARD_CAPABILITY_UNSUPPORTED')
        if ctx.cancelled(): raise BaotaError('CANCELLED')
        spec=ENDPOINTS[endpoint]
        entry=None
        def sent():
            nonlocal entry
            entry=self.write_observer(endpoint) if self.write_observer else {'endpoint':endpoint,'completion':'unknown'}
            self.sent_writes.append(entry)
        def received(output):
            if not isinstance(output,dict): return
            # Fixed scalar fields only, bounded before entering the journal.
            safe=redact(output,self.secrets); summary={}
            for key in SUMMARY_FIELDS:
                value=safe.get(key)
                if type(value) in (bool,int,float):
                    summary[key]=value if (type(value) is not float or math.isfinite(value)) and len(str(value))<=128 else '[NON_JSON_OR_TRUNCATED]'
                elif isinstance(value,str): summary[key]=value[:SUMMARY_CHAR_LIMIT].encode('utf-8','replace').decode('utf-8')
            entry['response']=summary
            if output.get('siteStatus') is True and (output.get('ftpStatus') is False or output.get('databaseStatus') is False): entry['completion']='partial'
        try:
            output=await self._request(ctx,spec,params,on_send=sent,on_response=received)
            if not isinstance(output,list if spec.response_kind=='array' else dict): raise BaotaError('BAOTA_RESPONSE_INVALID')
            return output
        finally:
            if entry is not None and self.write_finalizer: self.write_finalizer(entry)
    async def binary(self,ctx,path,max_bytes):
        return await self._request(ctx,DOWNLOAD,{'filename':path},binary=True,max_bytes=max_bytes)


class _Timeout:
    """Python 3.10 equivalent of asyncio.timeout; task cancellation stays observable."""
    def __init__(self,seconds): self.seconds=seconds; self.expired=False
    async def __aenter__(self):
        self.task=asyncio.current_task(); self.handle=asyncio.get_running_loop().call_later(self.seconds,self.cancel)
    def cancel(self): self.expired=True; self.task.cancel()
    async def __aexit__(self,kind,value,tb):
        self.handle.cancel()
        if kind is asyncio.CancelledError and self.expired: raise TimeoutError from value
