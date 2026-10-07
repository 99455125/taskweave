"""Explicit owned real-tool acceptance. Never selected by fast module targets."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from taskweave.core.ports import Scope
from taskweave.infrastructure.storage import Results,uid
from taskweave.infrastructure.worker import PluginContext,Resources
from taskweave.plugins.registry import Registry
from taskweave_uniapp import UniappPlugin

class UniappToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        path=os.environ.get('TW_UNIAPP_TOOL_CONFIG');self.assertTrue(path,'Explicit owned TW_UNIAPP_TOOL_CONFIG required; no automatic installation/import')
        self.config=json.loads(Path(path).read_text());self.assertIn('tw-uniapp-',Path(self.config['project_root']).name)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.plugin=UniappPlugin();self.registry=Registry([self.plugin]);self.resources=Resources(self.registry)
        self.results=Results(Path(self.temp.name)/'host',Scope(uid(),uid(),uid(),uid()),self.registry)
        self.ctx=PluginContext(self.results.scope,self.results,self.resources,{'uniapp_config':self.config},{},threading.Event(),lambda *a:None);self.resources.context=self.ctx
        self.addAsyncCleanup(self.resources.release_all)
        self.receipts=[];self.addCleanup(self.write_receipt)
    def write_receipt(self):
        target=os.environ.get('TW_UNIAPP_TOOL_RECEIPT')
        if target:target=target.replace('{test}',self._testMethodName)
        if target:
            with os.fdopen(os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as stream:json.dump({'scope':'explicit actual owned tools via UniappPlugin actions; not protocol fixture','config_root':self.config['project_root'],'records':self.receipts},stream,ensure_ascii=False,indent=2)
            os.chmod(target,0o600)
    async def action(self,name,**inputs):
        from taskweave.core.validation import validate
        action=self.registry.actions['uniapp.'+name];validate(inputs,action.spec.input_schema)
        try:out=await action.execute(self.ctx,inputs)
        except BaseException as error:
            failures=await self.plugin.failure_results(self.ctx,error)
            self.receipts.append({'action':name,'inputs':inputs,'error_code':getattr(error,'code',type(error).__name__),'command_result':getattr(error,'result',None),'failure_evidence':[r.payload for r in failures],'owned_build_records':[record for session in self.plugin.provider.sessions.values() for record in session.builds.values()],'owned_test_records':[record for session in self.plugin.provider.sessions.values() for record in session.tests.values()]})
            raise
        validate(out,action.spec.output_schema);self.receipts.append({'action':name,'inputs':inputs,'output':out});return out
    async def test_actual_cli_wechat_and_h5_builds_then_filtered_jest(self):
        self.assertEqual(self.config['kind'],'cli')
        for platform in ('mp-weixin','h5'):
            out=await self.action('build',platform=platform,timeout_seconds=120,max_output_bytes=1048576)
            self.assertTrue(out['artifact_verified']);self.assertEqual(out['completion'],'completed')
            checked=await self.action('check_artifact',build_id=out['build_id'],started_at=out['started_at'],platform=platform,max_output_bytes=1048576);self.assertTrue(checked['provenance_verified'])
        tests=await self.action('run_tests',platform='mp-weixin',file='src/pages/index/compiler.test.js',case='compiler output has declared WeChat page',timeout_seconds=60)
        self.assertTrue(tests['passed']);self.assertEqual(tests['summary']['executed'],1);self.assertEqual(tests['summary']['pending'],1)
        collected=await self.action('collect_report',paths=[tests['report_path']],test_run_id=tests['test_run_id']);self.assertTrue(collected['test_run_verified'])
    async def test_actual_cli_h5_filtered_jest_and_report(self):
        self.assertEqual(self.config['kind'],'cli')
        out=await self.action('run_tests',platform='h5',file='src/pages/index/compiler.test.js',case='compiler H5 entry references real generated scripts',timeout_seconds=60)
        self.assertTrue(out['passed']);self.assertEqual(out['summary']['executed'],1);self.assertEqual(out['summary']['pending'],1)
        saved=await self.action('collect_report',paths=[out['report_path']],test_run_id=out['test_run_id']);self.assertTrue(saved['test_run_verified'])
    async def test_actual_native_wechat_development(self):
        self.assertEqual(self.config['kind'],'hbuilderx');out=await self.action('build',platform='mp-weixin',environment='development',timeout_seconds=120,max_output_bytes=1048576)
        self.assertTrue(out['artifact_verified']);self.assertEqual(out['completion'],'completed')
        checked=await self.action('check_artifact',build_id=out['build_id'],started_at=out['started_at'],platform='mp-weixin',max_output_bytes=1048576);self.assertTrue(checked['structure_verified'])
    async def test_actual_native_h5_development_in_memory(self):
        self.assertEqual(self.config['kind'],'hbuilderx');out=await self.action('build',platform='h5',environment='development',timeout_seconds=120,max_output_bytes=1048576)
        self.assertEqual(out['completion'],'compiled_in_memory');self.assertFalse(out['artifact_verified'])
    async def test_actual_native_production_h5(self):
        self.assertEqual(self.config['kind'],'hbuilderx');out=await self.action('build',platform='h5',timeout_seconds=120,max_output_bytes=1048576);self.assertTrue(out['artifact_verified'])
    async def test_actual_native_existing_tests_and_report(self):
        self.assertEqual(self.config['kind'],'hbuilderx');out=await self.action('run_tests',platform=os.environ.get('TW_UNIAPP_TEST_PLATFORM','mp-weixin'),file=os.environ.get('TW_UNIAPP_TEST_FILE'),timeout_seconds=int(os.environ.get('TW_UNIAPP_TEST_TIMEOUT','120')),max_output_bytes=1048576)
        self.assertTrue(out['passed']);collected=await self.action('collect_report',paths=[out['report_path']],test_run_id=out['test_run_id']);self.assertTrue(collected['test_run_verified'])

    async def test_actual_cli_worker_prior_build_survives_later_exception(self):
        from taskweave.application.service import Application
        self.assertEqual(self.config['kind'],'cli')
        def run():
            with tempfile.TemporaryDirectory() as home,Application(home) as app:
                app.configure_plugin('uniapp',True);env=app.environments.save('owned real compiler',{'uniapp_config':self.config},{})['environment_id'];task=app.tasks.create('real compiler durable failure')['task_id']
                step=app.steps.save(task,{'name':'compile then later error','capabilities':['uniapp.build','uniapp.inspect'],'step_content':'async def run(ctx, inputs):\n    await ctx.call("uniapp.build", {"platform":"h5","timeout_seconds":120,"max_output_bytes":1048576})\n    await ctx.call("uniapp.inspect", {"role":"later-reader"})\n    raise RuntimeError("expected later failure")'})
                app.confirm_step_manual(step['step_id'],step['content_hash'],environment_id=env);run_id=app.runs.create(task,environment_id=env)['run_id'];app.runs.start(run_id,uid());done=app.runs.wait(run_id,timeout=140)
                self.assertEqual(done['status'],'FAILED');result=next(r for r in done['results'] if r['handler_id']=='uniapp.operation_failure');data=app.runs.read_result(result['result_id'])['data'];self.assertEqual(data['operations'][0]['action_state'],'completed');self.assertEqual(data['operations'][0]['command']['exit_code'],0)
                self.receipts.append({'actual_worker_run_status':done['status'],'handler_id':result['handler_id'],'durable_evidence':data})
        await asyncio.to_thread(run)
