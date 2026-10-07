"""Optional official miniprogram-automator simulator integration."""
from dataclasses import replace
from taskweave.plugins.sdk import AuthoringContribution
from taskweave_process.artifacts import FileResultHandler
from .actions import Action,DEFINITIONS,Evidence,Provider,JsonHandler
from .context import REQUEST,collect_page
from .release import ReleaseAction,ReleaseEvidence

class FileHandler(FileResultHandler):
 def preview(self,parsed):return {'file':parsed}

class ImageHandler(FileHandler):
 def prepare(self,request):
  from .bridge import require
  require(isinstance(request.payload,dict) and request.payload.get('media_type') in ('image/png','image/jpeg'),'WECHAT_IMAGE_RESULT_INVALID')
  return super().prepare(request)

class WechatDevPlugin:
 def __init__(self):self.evidence=Evidence();self.provider=Provider(self.evidence);self.release_evidence=ReleaseEvidence()
 def manifest(self):return {'id':'wechat_dev','api_version':1,'package_version':'0.1.0','core_requires':'>=0.1,<1','dependencies':{},'config_variables':[{'key':'wechat_dev_config','type':'json','required':False,'description':'Compiled project root, explicit Node/prepared SDK0.12.1 root, attach endpoint or official launch CLI/port, test storage namespace and owned preparation receipt'},{'key':'wechat_release_config','type':'json','required':False,'description':'Compiled project_root, explicit node_path, prepared miniprogram-ci2.1.48 module_root and private_key_ref'}],'context_requests':{'wechat_dev.page':REQUEST}}
 def actions(self):return {**{'wechat_dev.'+name:Action(name,self.provider) for name in DEFINITIONS},**{'wechat_dev.'+name:ReleaseAction(name,self.release_evidence) for name in ('preview','upload')}}
 def tools(self):return {'wechat_dev.inspect_page':InspectPage(self.provider)}
 def resource_providers(self):return {'wechat_dev.simulator':self.provider}
 def result_handlers(self):return {'wechat_dev.file':FileHandler(),'wechat_dev.image':ImageHandler(),'wechat_dev.json':JsonHandler(),'wechat_dev.operation_failure':JsonHandler()}
 def result_views(self):return {'wechat_dev.screenshot':{'type':'image','description':'Simulator PNG evidence via {output: saved image result name} or bounded {image_base64, mime_type} page context'}}
 def authoring(self,selected_ids):return AuthoringContribution('preview/upload use separate wechat_release_config and official miniprogram-ci2.1.48, real mini-program AppID, private_key_ref and upload IP whitelist. Save preview artifact through wechat_dev.image/file; upload creates development version, not experience-version selection or review/publication. WRITE/no automatic retry. Explicit compiled project, Node and prepared SDK0.12.1. Passive environment/page observation never connects or launches. Connect attach proves AppID/page only, root_verified=false; official agent-start launch ownership requires private-root preparation proof and real new-window return. Borrowed/uncertain only disconnect; no global quit or caller CLI args. Opaque elements/session/page_revision expire on navigation. No eval/generic wx/function source. Namespaced storage; full clear needs scope=all and confirm_all. Static allowlisted mocks reserve restoration; borrowed mock requires allow_borrowed_mock and restores original, not a previous user mock. Explicit restore/disconnect before returning makes failures visible; automatic cleanup warns and failure hook retains UNKNOWN. WRITE/no retry, cumulative diagnostics survive later READ/role/failure. Screenshot returns staged simulator evidence: save with wechat_dev.image/file output; not true-device/login/backend proof.',examples=('''async def run(ctx, inputs):
    await ctx.call("wechat_dev.connect", {})
    await ctx.call("wechat_dev.assert_page", {"path": inputs["path"]})
    capture = await ctx.call("wechat_dev.screenshot", {})
    await ctx.call("wechat_dev.disconnect", {})
    return ctx.result(data={"capture": {"output": "simulator"}}, outputs=[ctx.output("wechat_dev.image", "simulator", capture["result"]["artifact"])], views=[{"title": "Simulator", "renderer": "wechat_dev.screenshot", "pointer": "/capture"}])''',),context_provider_ids=('wechat_dev.page',),tool_ids=('wechat_dev.inspect_page',),constraints={'content_format':'python-async-v1'})
 async def collect_context(self,provider_id,ctx,request,*,include_view=True):return await collect_page(provider_id,ctx,request,include_view=include_view)
 async def failure_results(self,ctx,error):return [*(await self.evidence.results(ctx,error)),*(await self.release_evidence.results(ctx,error))]
 async def lint(self,document):return []
 async def diagnose(self,error,refs):return []

class InspectPage(Action):
 def __init__(self,provider):
  from .actions import OUTPUT
  super().__init__('observe',provider)
  schema={**REQUEST,'properties':{key:value for key,value in REQUEST['properties'].items() if key!='screenshot'}}
  self.spec=replace(self.spec,id='wechat_dev.inspect_page',input_schema=schema,output_schema=OUTPUT)
 async def execute(self,ctx,inputs):
  await self.preflight(ctx,inputs)
  collection=await collect_page('wechat_dev.page',ctx,{key:value for key,value in inputs.items() if key in ('role','selectors','paths')},include_view=False)
  from json import loads
  return {'session_id':None,'page_path':None,'page_revision':0,'result':loads(collection.items[0].content)}
