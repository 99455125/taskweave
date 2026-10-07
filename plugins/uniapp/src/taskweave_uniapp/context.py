"""Passive project observations with no application launch or JS evaluation."""
import json
from taskweave.plugins.sdk import ContextCollection,ContextItem,ContextView
from .project import configuration,inspect_project,require
from .actions import obj,redact_data

REQUEST=obj({})
async def collect_project(provider_id,ctx,request,*,include_view=True,provider=None):
    require(provider_id=='uniapp.project' and request in (None,{}),'UNIAPP_CONTEXT_REQUEST_INVALID')
    config=configuration(ctx);output=inspect_project(ctx,config);output['builds']=provider.observations(config['project_root']) if provider else [];output=redact_data(output,[ctx.resolve_secret(ref) for ref in config.get('env_secret_refs',{}).values()]);text=json.dumps(output,ensure_ascii=False)
    require(len(text.encode())<=65536,'UNIAPP_OUTPUT_TOO_LARGE')
    return ContextCollection([ContextItem('text','application/json',text,'uniapp.project',False)],[ContextView('uni-app project','json',output)] if include_view else [])
