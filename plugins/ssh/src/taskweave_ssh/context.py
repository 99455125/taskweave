"""Passive authenticated SFTP observation; no shell command probes."""
import json
from jsonschema import Draft202012Validator
from taskweave.plugins.sdk import ContextCollection, ContextItem, ContextView
from .actions import LIST_INPUT, list_directory
from .paths import SshError


async def collect_server(provider_id,ctx,request,*,include_view=True):
    if provider_id!='ssh.server': raise SshError('CONTEXT_PROVIDER_UNAVAILABLE')
    request={} if request is None else request
    if not Draft202012Validator(LIST_INPUT).is_valid(request): raise SshError('SSH_CONTEXT_REQUEST_INVALID')
    if ctx.cancelled(): raise SshError('CANCELLED')
    session=await ctx.resources.acquire('ssh.connection',request.get('role','default'))
    output=await list_directory(session,request)
    output['target']=session.config['host']+':'+str(session.config.get('port',22))
    budget=request.get('max_output_bytes',65536)
    text=json.dumps(output,ensure_ascii=False)
    while len(text.encode())>budget and output['entries']:
        output['entries'].pop(); output['truncated']=True
        text=json.dumps(output,ensure_ascii=False)
    if len(text.encode())>budget: raise SshError('SSH_CONTEXT_BUDGET_TOO_SMALL')
    return ContextCollection([ContextItem('text','application/json',text,'ssh.server',output['truncated'])],
        [ContextView('SSH server directory','json',output)] if include_view else [])
