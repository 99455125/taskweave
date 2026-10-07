"""Optional local/SSH WordPress 2.12 plugin; independent owned transport."""
from taskweave.plugins.sdk import AuthoringContribution,PreparedResult
from taskweave_process.artifacts import FileResultHandler
from .actions import DEFINITIONS,WordPressAction
from .transport import SiteTransport,WriteEvidence,configuration,CONFIG_KEYS
from .context import CONTEXT_INPUT,collect_site
from .commands import require

class SiteProvider:
    def __init__(self,evidence):
        self.evidence=evidence;self.opening=set();self.active=set()
    async def open(self,ctx,role):
        key=(id(ctx),role)
        require(key not in self.opening,'WORDPRESS_SITE_OPEN_BUSY')
        require(len(self.active)+len(self.opening)<128,'WORDPRESS_RESOURCE_CAPACITY')
        self.opening.add(key)
        try:
            resource=await SiteTransport(configuration(ctx),self.evidence).open(ctx)
            self.active.add(id(resource));return resource
        finally: self.opening.discard(key)
    async def close(self,resource):
        try: await resource.close()
        finally: self.active.discard(id(resource))

class JsonResultHandler:
    def schema(self): return {'version':1,'tables':{},'migrations':{},'indexes':{}}
    def prepare(self,request):
        require(isinstance(request.payload,dict),'WORDPRESS_RESULT_INVALID');return PreparedResult('json',payload=request.payload)
    def parse(self,stored): return stored
    def preview(self,parsed): return {'renderer':'json','data':parsed}

class WordPressPlugin:
    def __init__(self): self.evidence=WriteEvidence()
    def manifest(self):
        return {'id':'wordpress','api_version':1,'package_version':'0.1.0','core_requires':'>=0.1,<1','dependencies':{},'config_variables':[{'key':'wordpress_'+key,'type':'json' if key in ('ssh','owned_tables','secret_refs') else 'integer' if key in ('max_output_bytes','timeout_seconds','max_transfer_bytes') else 'string','required':key=='site_path','description':'WordPress '+key} for key in CONFIG_KEYS],'context_requests':{'wordpress.site':CONTEXT_INPUT}}
    def actions(self): return {'wordpress.'+name:WordPressAction(name,self.evidence) for name in DEFINITIONS}
    def tools(self): return {}
    def resource_providers(self): return {'wordpress.site':SiteProvider(self.evidence)}
    def result_handlers(self): return {'wordpress.file':FileResultHandler(),'wordpress.json':JsonResultHandler(),'wordpress.operation_failure':JsonResultHandler()}
    def authoring(self,selected_ids):
        return AuthoringContribution('WordPress 53 typed independent actions over wordpress.site local/ssh transport. Configure wordpress_site_path and wordpress_local_root; optional wordpress_wp_path/php_path. SSH config is wordpress_ssh with mandatory known_hosts and remote_root; no enabled SSH action dependency. WP-CLI 2.12 prompt transcript supported. Secrets are logical references resolved via ctx.resolve_secret and sent only through stdin; config getters reject secret fields. Output is bounded/redacted before clipping. WRITE actions never automatically retry. Configure explicit wordpress_owned_tables for database/backup/search actions. Backup contains protected files+SQL+hashed manifest; restore validates site/table identity and applies overlay then SQL, with durable partial/unknown receipts, not atomic rollback. Search replacement defaults to preview; execution requires fresh matching preview_token and count budget; external writers must be quiesced. File artifacts require ctx.output("wordpress.file", name, result["artifact"]) inside ctx.result(outputs=...). No automatic tools/dependencies installation, allow-root, force or arbitrary PHP evaluation.',examples=('''async def run(ctx, inputs):
    result = await ctx.call("wordpress.list_posts", {"post_type": "page", "limit": 10})
    return ctx.result(data=result)''',),context_provider_ids=('wordpress.site',),constraints={'content_format':'python-async-v1'})
    async def collect_context(self,provider_id,ctx,request,*,include_view=True): return await collect_site(provider_id,ctx,request,include_view=include_view)
    async def failure_results(self,ctx,error): return await self.evidence.results(ctx,error)
    async def lint(self,document): return []
    async def diagnose(self,error,refs): return []
