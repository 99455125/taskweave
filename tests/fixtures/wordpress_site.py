"""Explicit WordPress integration context and protocol worker registry."""
import json
from pathlib import Path
import tempfile
import threading
from taskweave.core.ports import Scope
from taskweave.infrastructure.storage import Results,uid
from taskweave.infrastructure.worker import PluginContext,Resources
from taskweave.plugins.registry import Registry
from taskweave_wordpress import WordPressPlugin

class WordPressContext:
    def __init__(self,configuration,secrets):
        self.temp=tempfile.TemporaryDirectory(prefix='taskweave-wp-results-')
        self.registry=Registry([WordPressPlugin()]);self.plugin=self.registry.plugins[0]
        self.results=Results(Path(self.temp.name),Scope(uid(),uid(),uid(),uid()),self.registry)
        import os
        self.variables=[]
        references={}
        for key,value in secrets.items():
            name='TW_WP_FIXTURE_'+key.upper();os.environ[name]=value;references[key]='env:'+name;self.variables.append(name)
        self.ctx=PluginContext(self.results.scope,self.results,Resources(self.registry),configuration,references,threading.Event(),lambda *args:None)
        self.ctx.resources.context=self.ctx
    async def action(self,action_id,**inputs): return await self.registry.actions['wordpress.'+action_id].execute(self.ctx,inputs)
    async def close(self):
        import os
        await self.ctx.resources.release_all()
        for name in self.variables: os.environ.pop(name,None)
        self.temp.cleanup()

def worker_registry(): return Registry([WordPressPlugin()])


def concurrent_worker_registry():
    import asyncio
    class ConcurrentPlugin(WordPressPlugin):
        def actions(self):
            actions=super().actions();inner=actions['wordpress.config_set']
            class Action:
                spec=inner.spec
                preflight=inner.preflight
                verify=inner.verify
                async def execute(self,ctx,inputs):
                    replies=await asyncio.gather(inner.execute(ctx,{'name':'FIELD_A','value':'a','role':'a'}),inner.execute(ctx,{'name':'FIELD_B','value':'b','role':'b'}))
                    return replies[0]
            actions['wordpress.config_set']=Action();return actions
    return Registry([ConcurrentPlugin()])


def cleanup_failure_worker_registry():
    """Test-only filesystem fault; production failure hooks/worker stay real."""
    from taskweave_wordpress import SiteProvider
    from taskweave_wordpress.transport import SiteTransport
    import os
    class Provider(SiteProvider):
        async def open(self,ctx,role):
            site=await super().open(ctx,role)
            async def delete(path):
                if path in site.scratch_files: raise OSError('injected own scratch deletion failure')
                await SiteTransport.delete(site,path)
            site.delete=delete
            return site
        async def close(self,site):
            # The real worker saves the failure receipt before this resource
            # cleanup; remove only fault-injected test-owned temporary data.
            for path,directory in list(site.scratch_files.items()):
                await SiteTransport.delete(site,path);os.rmdir(directory)
            await super().close(site)
    class Plugin(WordPressPlugin):
        def resource_providers(self):return {'wordpress.site':Provider(self.evidence)}
    return Registry([Plugin()])
