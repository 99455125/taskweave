"""Optional uni-app CLI/HBuilderX project/build/test integration."""
from taskweave.plugins.sdk import AuthoringContribution
from taskweave_process.artifacts import FileResultHandler
from .actions import Action,DEFINITIONS,Evidence,ProjectProvider,JsonHandler
from .context import REQUEST,collect_project

class UniappPlugin:
    def __init__(self):self.evidence=Evidence();self.provider=ProjectProvider(self.evidence)
    def manifest(self):return {'id':'uniapp','api_version':1,'package_version':'0.1.0','core_requires':'>=0.1,<1','dependencies':{},'config_variables':[{'key':'uniapp_config','type':'json','required':True,'description':'Explicit project root, CLI/HBuilderX tools/scripts/output/report mappings and secret references'}],'context_requests':{'uniapp.project':REQUEST}}
    def actions(self):return {'uniapp.'+name:Action(name,self.provider) for name in DEFINITIONS}
    def tools(self):return {'uniapp.inspect_project':InspectTool(self.provider)}
    def resource_providers(self):return {'uniapp.project':self.provider}
    def result_handlers(self):return {'uniapp.file':FileResultHandler(),'uniapp.json':JsonHandler(),'uniapp.operation_failure':JsonHandler()}
    def authoring(self,selected_ids):return AuthoringContribution('Configure uniapp_config with explicit project_root/kind/tools and existing build/test script mappings. inspect/context are passive: no CLI help, application open, project JS execution or installs. Build/run_tests are WRITE/no retry. check_artifact needs the exact build_id/started_at/platform in the same owned project role. Native H5 development may be compiled_in_memory, without deployable static files. Native production requires imported_project name/root/evidence and never uploads/hosts. Jest CLI filters require a direct verified Jest script; native testcaseFile follows installed schema, case names need a configured Jest route. Native test runner may rewrite Jest config; use explicitly prepared owned test project. Complete THISRUN report with positive executed tests is necessary. collect_report returns staged artifacts: save them with uniapp.file outputs. Started failed/cancelled commands and prior writes persist as operation_failure diagnostics; no rollback. Native UNKNOWN persists a private v1 root lease across workers/roles/session close; inspect/context remain passive, recovery uses an independently owned new root. Caller cleanup flags cannot release it; secure POSIX primitives are required. Secrets use env_secret_refs logical references; never argv.',examples=('''async def run(ctx, inputs):
    build = await ctx.call("uniapp.build", {"platform": "mp-weixin"})
    checked = await ctx.call("uniapp.check_artifact", {"build_id": build["build_id"], "started_at": build["started_at"], "platform": "mp-weixin"})
    return ctx.result(data=checked)''',),context_provider_ids=('uniapp.project',),tool_ids=('uniapp.inspect_project',),constraints={'content_format':'python-async-v1'})
    async def collect_context(self,provider_id,ctx,request,*,include_view=True):return await collect_project(provider_id,ctx,request,include_view=include_view,provider=self.provider)
    async def failure_results(self,ctx,error):return await self.evidence.results(ctx,error)
    async def lint(self,document):return []
    async def diagnose(self,error,refs):return []

class InspectTool(Action):
    def __init__(self,provider):
        from dataclasses import replace
        super().__init__('inspect',provider);self.spec=replace(self.spec,id='uniapp.inspect_project')
