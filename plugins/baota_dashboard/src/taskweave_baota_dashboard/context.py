"""Passive site identity/status and metadata summary; never reads creating getters."""
import json
from taskweave.plugins.sdk import ContextCollection, ContextItem, ContextView
from .actions import obj, SITE, COMMON, target, require
from .client import redact

CONTEXT_INPUT=obj({**SITE,'role':COMMON['role'],'max_output_bytes':COMMON['max_output_bytes']},['site_id'])
CONTEXT_INPUT['x-taskweave-context-form'] = {'rows': [['$provider', '$session', 'site_id', 'role', 'max_output_bytes', '$preview']]}


async def collect_site(provider_id,ctx,request,*,include_view=True):
    from jsonschema import Draft202012Validator
    require(provider_id=='baota_dashboard.site','CONTEXT_PROVIDER_UNAVAILABLE')
    request={} if request is None else request
    require(Draft202012Validator(CONTEXT_INPUT).is_valid(request),'BAOTA_CONTEXT_REQUEST_INVALID')
    if ctx.cancelled():
        from .client import BaotaError
        raise BaotaError('CANCELLED')
    client=await ctx.resources.acquire('baota_dashboard.connection',request.get('role','default'))
    require(not client.busy,'BAOTA_CONNECTION_BUSY')
    client.busy=True
    try:
        client.start_operation({}); await client.identify(ctx)
        site=await target(client,ctx,'site',request['site_id'])
    finally: client.busy=False
    # Summary has no path content / GetFileBody / repair-prone ServiceAdmin.
    output={k:site[k] for k in ('id','name','path','status','project_type','ps') if k in site}
    output['profile']='bt-linux-11.7.0'; output=redact(output,client.secrets)
    text=json.dumps(output,ensure_ascii=False)
    if len(text.encode())>request.get('max_output_bytes',65536):
        output={k:v for k,v in output.items() if k in ('id','name','status','profile')}; output['truncated']=True; text=json.dumps(output,ensure_ascii=False)
    require(len(text.encode())<=request.get('max_output_bytes',65536),'BAOTA_OUTPUT_TOO_LARGE')
    return ContextCollection([ContextItem('text','application/json',text,'baota_dashboard.site',output.get('truncated',False))],[ContextView('BaoTa site','json',output)] if include_view else [])
