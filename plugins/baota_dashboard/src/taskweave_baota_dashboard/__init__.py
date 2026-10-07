"""Optional Chinese BaoTa 11.7.0 plugin. No generic endpoint/shell capability."""
from dataclasses import replace
from taskweave.plugins.sdk import AuthoringContribution
from .actions import DEFINITIONS, PanelAction, FailureEvidence, OperationResultHandler, JsonResultHandler
from .client import PanelClient, CONFIG_KEYS, configuration
from .context import CONTEXT_INPUT, collect_site

__all__=['BaotaDashboardPlugin','PanelClient']

class ConnectionProvider:
    def __init__(self,evidence): self.evidence=evidence
    async def open(self,ctx,role): return PanelClient(configuration(ctx))
    async def close(self,resource):
        try: await resource.close()
        finally: self.evidence.close(resource)

class BaotaDashboardPlugin:
    def __init__(self): self.evidence=FailureEvidence()
    def manifest(self):
        return {'id':'baota_dashboard','api_version':1,'package_version':'0.1.0','core_requires':'>=0.1,<1','dependencies':{},
            'config_variables':[{'key':'baota_'+key,'type':'boolean' if key=='allow_http' else 'integer' if key in ('timeout_seconds','max_response_bytes') else 'string','required':key in ('url','api_secret_ref'),'description':'BaoTa '+key+'; task parameters override environment'} for key in CONFIG_KEYS],
            'context_requests':{'baota_dashboard.site':CONTEXT_INPUT}}
    def actions(self): return {'baota_dashboard.'+name:PanelAction(name,self.evidence) for name in DEFINITIONS}
    def tools(self):
        tool=PanelAction('list_sites',self.evidence); tool.spec=replace(tool.spec,id='baota_dashboard.inspect_sites',description='Observe bounded site inventory; no configuration repair')
        return {'baota_dashboard.inspect_sites':tool}
    def resource_providers(self): return {'baota_dashboard.connection':ConnectionProvider(self.evidence)}
    def result_handlers(self): return {'baota_dashboard.json':JsonResultHandler(),'baota_dashboard.operation_failure':OperationResultHandler()}
    def authoring(self,selected_ids):
        return AuthoringContribution('Configure baota_url and baota_api_secret_ref (logical secret reference), optional baota_ca_file; TLS verifies by default. Explicit baota_allow_http permits isolated HTTP fixtures. Only Chinese LinuxPanel 11.7.0 fixed profile; unsupported versions fail before writes. Every action is independent with strict schemas; no arbitrary endpoint/shell. WRITE actions, including check_config, never automatically retry. Timeout 60 seconds (1–1800); aggregate response default 16 MiB (1024 bytes–64 MiB); model/output default 64 KiB (1 KiB–1 MiB). List pagination is explicit, truncated means more may exist. PHP projects and nginx/apache configuration only; local MySQL/MariaDB database actions only. AddSite suboperations and multi-step configuration failures preserve actual partial outcomes through baota_dashboard.operation_failure diagnostics. Failed attempts stay failed/UNKNOWN. HTTP success is not business success. Certificate pending is accepted, actual issued certificate is issued, issuance does not imply deployed. Database access replaces Host grants and must postverify. Site restore validates own tar.gz archive and bounded members, rejects links/escape, applies overlay and verifies all member hashes; this requires stable remote files throughout verification. SQL restore requires expected_tables; schema proof is not full data equivalence. Save explicit successful output with ctx.output("baota_dashboard.json", name, result) in ctx.result(outputs=...). Read context is passive site/configuration metadata, no missing rewrite-file creation.',
            examples=('''async def run(ctx, inputs):
    result = await ctx.call("baota_dashboard.check_connection", {})
    return ctx.result(data=result)''',),context_provider_ids=('baota_dashboard.site',),tool_ids=('baota_dashboard.inspect_sites',),constraints={'content_format':'python-async-v1'})
    async def collect_context(self,provider_id,ctx,request,*,include_view=True): return await collect_site(provider_id,ctx,request,include_view=include_view)
    async def failure_results(self,ctx,error): return await self.evidence.results(ctx,error)
    async def lint(self,document): return []
    async def diagnose(self,error,refs): return []
