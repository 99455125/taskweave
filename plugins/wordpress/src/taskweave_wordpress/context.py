"""Passive bounded version, theme/plugin and page summaries."""
import json
from taskweave.plugins.sdk import ContextCollection,ContextItem,ContextView
from .actions import obj,COMMON,perform
from .commands import require
from jsonschema import Draft202012Validator

CONTEXT_INPUT=obj({'role':COMMON['role'],'limit':{'type':'integer','minimum':1,'maximum':20,'default':5},'max_output_bytes':COMMON['max_output_bytes']})

async def collect_site(provider_id,ctx,request,*,include_view=True):
    require(provider_id=='wordpress.site','CONTEXT_PROVIDER_UNAVAILABLE')
    request=request or {};require(Draft202012Validator(CONTEXT_INPUT).is_valid(request),'WORDPRESS_CONTEXT_INVALID')
    site=await ctx.resources.acquire('wordpress.site',request.get('role','default'))
    require(not site.busy,'WORDPRESS_SITE_BUSY');site.busy=True
    try:
        site.start(ctx,'context',request.get('role','default'),request)
        version=(await site.execute(ctx,['core','version']))['stdout'].strip()
        result={'version':version,'site_path':str(site.site),'themes':(await perform(ctx,site,'list_themes',{'limit':request.get('limit',5)}))['result']['items'],'plugins':(await perform(ctx,site,'list_plugins',{'limit':request.get('limit',5)}))['result']['items'],'pages':(await perform(ctx,site,'list_posts',{'post_type':'page','limit':request.get('limit',5)}))['result']['items'],'truncated':False}
    finally: site.busy=False
    budget=request.get('max_output_bytes',65536)
    text=json.dumps(result,ensure_ascii=False)
    while len(text.encode())>budget:
        rows=max((result[key] for key in ('themes','plugins','pages')),key=len)
        require(rows,'WORDPRESS_OUTPUT_TOO_LARGE');rows.pop();result['truncated']=True;text=json.dumps(result,ensure_ascii=False)
    return ContextCollection([ContextItem('text','application/json',text,'wordpress.site',result['truncated'])],[ContextView('WordPress site','json',result)] if include_view else [])
