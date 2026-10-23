"""Passive existing-session observation; no implicit connection or launch."""
import json
import base64
import time
from taskweave.plugins.sdk import ContextCollection,ContextItem,ContextView
from .actions import obj,inspect_environment
from .configuration import configuration
from .bridge import require,mask,representations

REQUEST=obj({'role':{'type':'string','minLength':1,'maxLength':256},'selectors':{'type':'array','items':{'type':'string','minLength':1,'maxLength':512},'maxItems':20},'paths':{'type':'array','items':{'type':'string','minLength':1,'maxLength':256},'minItems':1,'maxItems':20},'screenshot':{'type':'boolean'}})
REQUEST['x-taskweave-context-form'] = {'rows': [['$provider', '$session', 'role', 'screenshot', '$preview'], ['selectors'], ['paths']]}

async def collect_page(provider_id,ctx,request,*,include_view=True):
 from jsonschema import Draft202012Validator
 request=request or {};require(provider_id=='wechat_dev.page' and Draft202012Validator(REQUEST).is_valid(request),'WECHAT_CONTEXT_INVALID')
 config=configuration(ctx);role=request.get('role','default');active=[session for name,session in ctx.resources.active('wechat_dev.simulator') if name==role and session.connected and not session.closed]
 output={'environment':inspect_environment(config),'connected':False}
 if active:active[0].bind(ctx,config);output={'connected':True,'observation':await active[0].bridge.request('observe',{key:value for key,value in request.items() if key not in ('role','screenshot')},timeout_seconds=10)}
 output=mask(output,representations([ctx.resolve_secret(ref) for ref in config.get('env_secret_refs',{}).values()]));encoded=json.dumps(output,ensure_ascii=False);require(len(encoded.encode())<=65536,'WECHAT_OUTPUT_LIMIT')
 views=[ContextView('WeChat simulator page','json',output)] if include_view else []
 if include_view and request.get('screenshot') and active:
  from .capture import capture_bytes
  data=await capture_bytes(active[0].bridge,max_bytes=1048576,deadline=time.monotonic()+10)
  views.append(ContextView('WeChat simulator screenshot','wechat_dev.screenshot',{'image_base64':base64.b64encode(data).decode(),'mime_type':'image/png'}))
 return ContextCollection([ContextItem('text','application/json',encoded,'wechat_dev.page',False)],views)
