"""Real bounded Node commands and host persistence; compiler protocol fixtures only."""
import asyncio
import importlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from taskweave.core.ports import Scope
from taskweave.infrastructure.storage import Results,uid
from taskweave.infrastructure.worker import PluginContext,Resources
from taskweave.plugins.registry import Registry
from taskweave.core.validation import TaskError
from tests.fixtures.uniapp_project import project,compatible_test_node

class UniappTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        try: module=importlib.import_module('taskweave_uniapp')
        except ModuleNotFoundError: self.fail('uniapp five-action plugin is missing')
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);project(self.root)
        self.plugin=module.UniappPlugin();self.registry=Registry([self.plugin]);self.resources=Resources(self.registry)
        self.results=Results(self.root/'host',Scope(uid(),uid(),uid(),uid()),self.registry);self.cancel=threading.Event()
        node=compatible_test_node()
        self.config={'project_root':str(self.root),'kind':'cli','node_path':node,'node_major':22,'package_manager':shutil.which('npm'),
          'build_scripts':{'production:mp-weixin':{'script':'build:mp-weixin','completion':'BUILD_COMPLETE'},'production:h5':{'script':'build:h5','completion':'BUILD_COMPLETE'}},
          'outputs':{'production:mp-weixin':'dist/build/mp-weixin','production:h5':'dist/build/h5'},'report_root':'.reports'}
        self.ctx=PluginContext(self.results.scope,self.results,self.resources,{'uniapp_config':self.config},{},self.cancel,lambda *a:None);self.resources.context=self.ctx
        self.addAsyncCleanup(self.resources.release_all)
    async def action(self,name,**inputs):
        from taskweave.core.validation import validate
        action=self.registry.actions['uniapp.'+name];validate(inputs,action.spec.input_schema)
        out=await action.execute(self.ctx,inputs);validate(out,action.spec.output_schema);return out
    async def test_inspect_is_passive_jsonc_layout_and_five_registered_actions(self):
        out=await self.action('inspect');self.assertEqual(out['vue_version'],'2');self.assertEqual(out['appid'],'touristappid')
        self.assertEqual(set(self.registry.actions),{'uniapp.'+n for n in ('inspect','build','check_artifact','run_tests','collect_report')})
        self.assertFalse((self.root/'dist').exists());self.assertEqual(out['pages'],['pages/index/index','pkg/second'])
        other=self.root/'other';project(other,src=True);self.config['project_root']=str(other)
        out=await self.action('inspect',role='other');self.assertEqual(out['layout'],'src')
    async def test_fresh_build_identity_same_byte_rewrite_and_artifact_check(self):
        first=await self.action('build',platform='mp-weixin');self.assertTrue(first['artifact_verified']);self.assertEqual(first['command']['exit_code'],0)
        second=await self.action('build',platform='mp-weixin');self.assertNotEqual(first['build_id'],second['build_id']);self.assertTrue(second['artifact_verified'])
        checked=await self.action('check_artifact',build_id=second['build_id'],started_at=second['started_at'],platform='mp-weixin');self.assertTrue(checked['provenance_verified']);self.assertTrue(Path(checked['output_path']).is_dir())
        with self.assertRaises(TaskError):await self.action('check_artifact',build_id='invented',started_at=second['started_at'],platform='mp-weixin')
        with self.assertRaises(TaskError):await self.action('check_artifact',build_id=second['build_id'],started_at=second['started_at'],platform='h5')
    async def test_successful_command_with_stale_artifact_is_rejected(self):
        await self.action('build',platform='mp-weixin');self.config['env']={'MODE':'noop'}
        with self.assertRaises(TaskError) as e:await self.action('build',platform='mp-weixin')
        self.assertEqual(e.exception.code,'UNIAPP_ARTIFACT_STALE')
    async def test_failure_with_files_and_later_read_keeps_failure_evidence(self):
        self.config['env']={'MODE':'fail'}
        with self.assertRaises(TaskError):await self.action('build',platform='h5')
        await self.action('inspect',role='read')
        saved=await self.plugin.failure_results(self.ctx,TaskError('LATER_ERROR'))
        self.assertTrue(saved);self.assertEqual(saved[0].handler_id,'uniapp.operation_failure');self.assertEqual(saved[0].payload['operations'][0]['command']['exit_code'],9)
    async def test_artifact_symlink_and_complete_budget_are_rejected(self):
        out=await self.action('build',platform='h5');asset=self.root/'dist/build/h5/assets/app.js';asset.unlink();asset.symlink_to('/etc/hosts')
        with self.assertRaises(TaskError):await self.action('check_artifact',build_id=out['build_id'],started_at=out['started_at'],platform='h5')
        with self.assertRaises(TaskError):await self.action('collect_report',paths=['dist/build/h5/assets/app.js'])
    async def test_missing_tools_scripts_and_dependencies_return_preparation(self):
        self.config['build_scripts']['production:h5']['script']='missing'
        with self.assertRaises(TaskError) as e:await self.action('build',platform='h5')
        self.assertEqual(e.exception.code,'UNIAPP_PREPARATION_REQUIRED')
        self.config['kind']='hbuilderx';self.config['hbuilderx_path']='/no/tool'
        out=await self.action('inspect',role='hx');self.assertTrue(out['preparation_required'])
    async def test_json_report_is_current_complete_positive_and_filtered(self):
        from taskweave_uniapp.tests import validate_jest_report
        start=1700000000000
        report={'success':True,'wasInterrupted':False,'startTime':start,'numTotalTests':1,'numPassedTests':1,'numFailedTests':0,'numPendingTests':0,'numTodoTests':0,'numTotalTestSuites':1,'numPassedTestSuites':1,'numFailedTestSuites':0,'numPendingTestSuites':0,'numRuntimeErrorTestSuites':0,'testResults':[{'name':str(self.root/'a.test.js'),'status':'passed','startTime':start,'endTime':start+1,'message':'','assertionResults':[{'fullName':'selected','status':'passed'}]}]}
        self.assertTrue(validate_jest_report(report,self.root,start,start+1000,file='a.test.js',case='selected')['passed'])
        for change in ({'numTotalTests':0},{'success':False},{'wasInterrupted':True},{'numRuntimeErrorTestSuites':1},{'startTime':start-10000}):
            with self.subTest(change=change),self.assertRaises(TaskError):validate_jest_report({**report,**change},self.root,start,start+1000,file='a.test.js',case='selected')
        with self.assertRaises(TaskError):validate_jest_report(report,self.root,start,start+1000,file='other.test.js')
    async def test_official_jest_focused_suite_requires_positive_consistent_assertions(self):
        from taskweave_uniapp.tests import validate_jest_report
        start=1700000000000
        report={'success':True,'wasInterrupted':False,'startTime':start,'numTotalTests':2,'numPassedTests':1,'numFailedTests':0,'numPendingTests':1,'numTodoTests':0,'numTotalTestSuites':1,'numPassedTestSuites':1,'numFailedTestSuites':0,'numPendingTestSuites':0,'numRuntimeErrorTestSuites':0,'testResults':[{'name':str(self.root/'a.test.js'),'status':'focused','startTime':start,'endTime':start+1,'message':'','assertionResults':[{'fullName':'selected','status':'passed'},{'fullName':'other','status':'pending'}]}]}
        self.assertTrue(validate_jest_report(report,self.root,start,start+1000,file='a.test.js',case='selected')['passed'])
        report['testResults'][0]['assertionResults'][0]['status']='pending'
        with self.assertRaises(TaskError):validate_jest_report(report,self.root,start,start+1000)
    async def test_native_test_missing_installed_schema_is_preparation_not_cli_success(self):
        self.config['kind']='hbuilderx';self.config['hbuilderx_path']='/Applications/HBuilderX.app/Contents/MacOS/cli'
        self.config['test_plugin_root']=str(self.root/'missing');self.config['owned_test_project']=True
        with self.assertRaises(TaskError) as e:await self.action('run_tests',platform='mp-weixin')
        self.assertEqual(e.exception.code,'UNIAPP_PREPARATION_REQUIRED')
    async def test_started_cancel_keeps_partial_and_does_not_pass_artifacts(self):
        self.config['env']={'MODE':'delay'}
        task=asyncio.create_task(self.action('build',platform='h5',timeout_seconds=10))
        await asyncio.sleep(.3);self.cancel.set()
        with self.assertRaises(TaskError):await task
        evidence=await self.plugin.failure_results(self.ctx,TaskError('CANCELLED'))
        self.assertTrue(evidence);self.assertEqual(evidence[0].payload['operations'][-1]['action_state'],'unknown')
    async def test_success_write_then_other_role_read_and_failure_is_durable(self):
        await self.action('build',platform='h5');await self.action('inspect',role='reader')
        saved=await self.plugin.failure_results(self.ctx,TaskError('LATER_ERROR'))
        self.assertEqual(saved[0].payload['operations'][0]['action_state'],'completed')
        self.assertEqual(saved[0].payload['operations'][0]['completion'],'completed')
    async def test_changed_build_configuration_cannot_reuse_prior_identity(self):
        result=await self.action('build',platform='h5');self.config['env']={'NEW_CONTEXT':'changed'}
        with self.assertRaises(TaskError):await self.action('check_artifact',platform='h5',build_id=result['build_id'],started_at=result['started_at'])
    async def test_report_collection_full_budget_and_host_file_save(self):
        directory=self.root/'.reports';directory.mkdir();(directory/'log.txt').write_text('full report')
        with self.assertRaises(TaskError):await self.action('collect_report',paths=['.reports/log.txt'],max_bytes=4)
        output=await self.action('collect_report',paths=['.reports/log.txt'])
        self.assertEqual(output['total_bytes'],11)
        from taskweave.core.ports import StepResult,ResultRequest
        request=ResultRequest('uniapp.file','report',output['artifacts'][0])
        stored=self.results.persist(StepResult(data={},outputs=[request]))
        self.assertEqual(sum(r['kind']=='file' for r in stored),1)
    async def test_concurrent_roles_on_same_root_are_rejected_before_second_command(self):
        self.config['env']={'MODE':'delay'}
        task=asyncio.create_task(self.action('build',platform='h5',timeout_seconds=1))
        await asyncio.sleep(.2)
        with self.assertRaises(TaskError) as e:await self.action('build',platform='h5',role='second')
        self.assertEqual(e.exception.code,'UNIAPP_PROJECT_BUSY')
        with self.assertRaises(TaskError):await task
    async def test_secret_reference_redaction_before_logs_journal_and_result(self):
        os.environ['TW_UNIAPP_SECRET']='x"quoted\\secret';self.addCleanup(os.environ.pop,'TW_UNIAPP_SECRET',None)
        self.ctx.secret_refs['token']='env:TW_UNIAPP_SECRET';self.config['env_secret_refs']={'TOKEN':'token'}
        script=self.root/'build.cjs';script.write_text(script.read_text()+"\nconsole.log(process.env.TOKEN);console.error(process.env.TOKEN);")
        output=await self.action('build',platform='h5')
        self.assertNotIn('quoted',json.dumps(output));self.assertIn('[REDACTED]',output['command']['stdout'])
        saved=await self.plugin.failure_results(self.ctx,TaskError('LATER_ERROR'));self.assertNotIn('quoted',json.dumps(saved[0].payload))
    async def test_real_worker_prior_success_then_exception_saves_own_handler(self):
        from taskweave.application.service import Application
        def run():
            with tempfile.TemporaryDirectory() as home,Application(home) as app:
                app.configure_plugin('uniapp',True)
                env=app.environments.save('owned protocol build',{'uniapp_config':self.config},{})['environment_id'];task=app.tasks.create('prior success journal')['task_id']
                step=app.steps.save(task,{'name':'build then error','capabilities':['uniapp.build','uniapp.inspect'],'step_content':'async def run(ctx, inputs):\n    await ctx.call("uniapp.build", {"platform":"h5"})\n    await ctx.call("uniapp.inspect", {"role":"reader"})\n    raise RuntimeError("later error")'})
                app.confirm_step_manual(step['step_id'],step['content_hash'],environment_id=env);run_id=app.runs.create(task,environment_id=env)['run_id'];app.runs.start(run_id,uid());done=app.runs.wait(run_id,timeout=10)
                self.assertEqual(done['status'],'FAILED');self.assertEqual(len(done['results']),1)
                result=done['results'][0];self.assertEqual(result['handler_id'],'uniapp.operation_failure')
                parsed=app.runs.read_result(result['result_id'])['data'];self.assertEqual(parsed['operations'][0]['action_state'],'completed')
        await asyncio.to_thread(run)
    async def test_direct_jest_script_verification_supports_official_cross_env_and_rejects_shell(self):
        from taskweave_uniapp.tests import verify_jest_script
        self.assertTrue(verify_jest_script('cross-env UNI_PLATFORM=mp-weixin jest -i'))
        self.assertTrue(verify_jest_script('jest --config jest.config.js'))
        for script in ('jest; echo ok','node test.js','jest --outputFile old.json','jest | cat','cross-env A=$(whoami) jest'):
            with self.subTest(script=script),self.assertRaises(TaskError):verify_jest_script(script)
    async def test_referenced_wechat_component_or_h5_asset_cannot_be_missing(self):
        wx=await self.action('build',platform='mp-weixin');out=self.root/'dist/build/mp-weixin'
        (out/'pages/index/index.json').write_text('{"usingComponents":{"widget":"../../components/widget"}}')
        # Static checker should diagnose the absent component, not merely
        # notice the changed page manifest fingerprint.
        from taskweave_uniapp.build import artifact_structure
        with self.assertRaises(TaskError):artifact_structure(self.config,'mp-weixin','dist/build/mp-weixin')
        await self.action('build',platform='h5');(self.root/'dist/build/h5/assets/app.js').unlink()
        with self.assertRaises(TaskError):artifact_structure(self.config,'h5','dist/build/h5')
    async def test_journal_capacity_reserves_before_the_next_real_write(self):
        for _ in range(16):await self.action('build',platform='h5')
        before=(self.root/'dist/build/h5/index.html').stat().st_mtime_ns
        with self.assertRaises(TaskError) as e:await self.action('build',platform='h5')
        self.assertEqual(e.exception.code,'UNIAPP_DIAGNOSTIC_CAPACITY');self.assertEqual((self.root/'dist/build/h5/index.html').stat().st_mtime_ns,before)
        data=(await self.plugin.failure_results(self.ctx,TaskError('LATER')))[0].payload;self.assertLessEqual(len(json.dumps(data).encode()),65536)
    async def test_delayed_file_after_zero_exit_is_not_build_completion(self):
        script=self.root/'build.cjs';script.write_text("console.log('BUILD_COMPLETE');")
        with self.assertRaises(TaskError):await self.action('build',platform='h5')
    async def test_inspect_does_not_evaluate_jest_or_environment_configuration(self):
        (self.root/'jest.config.js').write_text('require("fs").writeFileSync("unexpected","bad");module.exports={};')
        (self.root/'env.js').write_text('throw Error("must not evaluate");')
        await self.action('inspect');await self.plugin.collect_context('uniapp.project',self.ctx,{})
        self.assertFalse((self.root/'unexpected').exists())
    async def test_collected_known_secret_text_is_redacted_before_persistence(self):
        directory=self.root/'.reports';directory.mkdir();(directory/'secret.log').write_text('token=private-known-token')
        os.environ['TW_COLLECT_SECRET']='private-known-token';self.addCleanup(os.environ.pop,'TW_COLLECT_SECRET',None)
        self.ctx.secret_refs['token']='env:TW_COLLECT_SECRET';self.config['env_secret_refs']={'TOKEN':'token'}
        out=await self.action('collect_report',paths=['.reports/secret.log'])
        from taskweave.core.ports import StepResult,ResultRequest
        refs=self.results.persist(StepResult(outputs=[ResultRequest('uniapp.file','report',out['artifacts'][0])]))
        text=(self.results.root/refs[0]['locator']).read_text();self.assertEqual(text,'token=[REDACTED]')
    async def test_own_action_output_schemas_reject_incomplete_success(self):
        from taskweave.core.validation import validate
        for action in self.registry.actions.values():
            with self.subTest(action=action.spec.id),self.assertRaises(TaskError):validate({},action.spec.output_schema)
    async def test_missing_declared_dependency_is_passive_preparation(self):
        shutil.rmtree(self.root/'node_modules/jest')
        out=await self.action('inspect');self.assertIn('dependency missing: jest',out['preparation_required'])
        with self.assertRaises(TaskError) as e:await self.action('build',platform='h5')
        self.assertEqual(e.exception.code,'UNIAPP_PREPARATION_REQUIRED');self.assertFalse((self.root/'dist').exists())
    async def test_context_includes_actual_build_provenance_without_new_resource(self):
        result=await self.action('build',platform='h5');collection=await self.plugin.collect_context('uniapp.project',self.ctx,{})
        output=json.loads(collection.items[0].content);self.assertEqual(output['builds'][0]['build_id'],result['build_id']);self.assertEqual(output['builds'][0]['state'],'verified')
        self.assertEqual(output['outputs'],self.config['outputs'])
    async def test_explicit_external_report_root_is_confined_and_collectable(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);(base/'report.log').write_text('owned external native report')
            self.config['report_root']=str(base)
            out=await self.action('collect_report',paths=[str(base/'report.log')]);self.assertEqual(out['total_bytes'],28)
            with self.assertRaises(TaskError):await self.action('collect_report',paths=['/etc/hosts'])
    async def test_jest_route_forwards_literal_filters_and_rejects_missing_old_failed_report(self):
        from tests.fixtures.uniapp_project import install_jest_report_protocol
        install_jest_report_protocol(self.root);self.config['test_scripts']={'mp-weixin':{'script':'test:mp-weixin','forwards_jest_args':True}}
        out=await self.action('run_tests',platform='mp-weixin',file='a.test.js',case='selected case');self.assertTrue(out['passed']);self.assertEqual(out['summary']['executed'],1)
        forwarded=json.loads((self.root/'.reports/forwarded.json').read_text());self.assertEqual(forwarded,{'file':'a.test.js','selected':'^selected\\ case$'})
        (self.root/'.reports/later.log').write_text('later independent log')
        collected=await self.action('collect_report',test_run_id=out['test_run_id'],paths=[out['report_path']]);self.assertTrue(collected['test_run_verified'])
        for mode in ('missing','stale','failed'):
            self.config['env']={'REPORT_MODE':mode}
            with self.subTest(mode=mode),self.assertRaises(TaskError):await self.action('run_tests',platform='mp-weixin',file='a.test.js',case='selected case')
    async def test_redaction_expansion_cannot_escape_complete_file_budget(self):
        directory=self.root/'.reports';directory.mkdir();(directory/'secret.log').write_text('secret'*100)
        os.environ['TW_BUDGET_SECRET']='secret';self.addCleanup(os.environ.pop,'TW_BUDGET_SECRET',None);self.ctx.secret_refs['token']='env:TW_BUDGET_SECRET';self.config['env_secret_refs']={'TOKEN':'token'}
        with self.assertRaises(TaskError) as e:await self.action('collect_report',paths=['.reports/secret.log'],max_bytes=600)
        self.assertEqual(e.exception.code,'UNIAPP_ARTIFACT_LIMIT')

    async def test_node_compatibility_checks_minor_and_patch_before_build(self):
        (self.root/'.nvmrc').write_text('22.99.0')
        with self.assertRaises(TaskError) as e:await self.action('build',platform='h5')
        self.assertEqual(e.exception.code,'UNIAPP_NODE_INCOMPATIBLE');self.assertFalse((self.root/'dist').exists())
        (self.root/'.nvmrc').unlink();package=json.loads((self.root/'package.json').read_text());package['engines']={'node':'>=22.99.0'};(self.root/'package.json').write_text(json.dumps(package))
        with self.assertRaises(TaskError) as e:await self.action('build',platform='h5')
        self.assertEqual(e.exception.code,'UNIAPP_NODE_INCOMPATIBLE')

    async def test_node_minor_range_accepts_current_compatible_major(self):
        package=json.loads((self.root/'package.json').read_text());package['engines']={'node':'~22'};(self.root/'package.json').write_text(json.dumps(package))
        output=await self.action('build',platform='h5');self.assertTrue(output['artifact_verified'])

    async def test_inspect_tool_versions_use_passive_installed_metadata(self):
        (self.root/'node_modules/vue').mkdir();(self.root/'node_modules/vue/package.json').write_text('{"name":"vue","version":"2.6.14"}')
        output=await self.action('inspect');self.assertEqual(output['tool_versions']['jest'],'29.7.0');self.assertEqual(output['tool_versions']['vue'],'2.6.14');self.assertFalse((self.root/'dist').exists())

    async def test_json_report_redacts_known_secret_with_json_escaping(self):
        token='quoted"slash\\秘密';directory=self.root/'.reports';directory.mkdir();(directory/'secret.json').write_text(json.dumps({'token':token,'failureMessage':'Expected token: '+json.dumps(token)}).replace('\\u79d8','\\u79D8',1))
        os.environ['TW_JSON_SECRET']=token;self.addCleanup(os.environ.pop,'TW_JSON_SECRET',None);self.ctx.secret_refs['token']='env:TW_JSON_SECRET';self.config['env_secret_refs']={'TOKEN':'token'}
        out=await self.action('collect_report',paths=['.reports/secret.json'])
        from taskweave.core.ports import StepResult,ResultRequest
        saved=self.results.persist(StepResult(outputs=[ResultRequest('uniapp.file','report',out['artifacts'][0])]))
        content=json.loads((self.results.root/saved[0]['locator']).read_text());self.assertEqual(content['token'],'[REDACTED]');self.assertEqual(content['failureMessage'],'Expected token: "[REDACTED]"')

    async def test_json_escaped_command_and_metadata_keys_are_masked_before_worker_persistence(self):
        from taskweave.application.service import Application
        from taskweave_uniapp.actions import redact_data
        token='x"quoted\\秘密'
        os.environ['TW_WORKER_JSON_SECRET']=token;self.addCleanup(os.environ.pop,'TW_WORKER_JSON_SECRET',None)
        self.config['env_secret_refs']={'TOKEN':'token'};script=self.root/'build.cjs';script.write_text(script.read_text()+"\nconsole.log(JSON.stringify(process.env.TOKEN));console.error(JSON.stringify({token:JSON.stringify(process.env.TOKEN)}));")
        def run():
            with tempfile.TemporaryDirectory() as home,Application(home) as app:
                app.configure_plugin('uniapp',True);env=app.environments.save('escaped secret worker',{'uniapp_config':self.config},{'token':'env:TW_WORKER_JSON_SECRET'})['environment_id'];task=app.tasks.create('escaped secret persistence')['task_id']
                step=app.steps.save(task,{'name':'escaped output then error','capabilities':['uniapp.build','uniapp.inspect'],'step_content':'async def run(ctx, inputs):\n    await ctx.call("uniapp.build", {"platform":"h5"})\n    await ctx.call("uniapp.inspect", {"role":"reader"})\n    raise RuntimeError("later error")'})
                app.confirm_step_manual(step['step_id'],step['content_hash'],environment_id=env);run_id=app.runs.create(task,environment_id=env)['run_id'];app.runs.start(run_id,uid());done=app.runs.wait(run_id,timeout=10);self.assertEqual(done['status'],'FAILED')
                result=next(r for r in done['results'] if r['handler_id']=='uniapp.operation_failure');data=app.runs.read_result(result['result_id'])['data'];text=json.dumps(data,ensure_ascii=False);self.assertNotIn('quoted',text);self.assertIn('[REDACTED]',data['operations'][0]['command']['stderr'])
        await asyncio.to_thread(run)
        self.assertEqual(redact_data({token:json.dumps(token)},[token]),{'[REDACTED]':'"[REDACTED]"'})
    async def test_json_secret_lookahead_precedes_process_byte_clip(self):
        import sys
        from taskweave_uniapp.build import command_environment,execute_command
        token='quoted"slash\\秘密';os.environ['TW_LOOKAHEAD_SECRET']=token;self.addCleanup(os.environ.pop,'TW_LOOKAHEAD_SECRET',None);self.ctx.secret_refs['token']='env:TW_LOOKAHEAD_SECRET';self.config['env_secret_refs']={'TOKEN':'token'}
        safe,env=command_environment(self.ctx,self.config);session=await self.resources.acquire('uniapp.project','default')
        result,_=await execute_command(session,safe,'build',sys.executable,['-c','import os,json,sys;sys.stdout.write("a"*1000+json.dumps(os.environ["TOKEN"]))'],env,{'max_output_bytes':1024})
        self.assertNotIn('quoted',result['stdout']);self.assertTrue(result['stdout_truncated'])

    async def test_fresh_wechat_build_rejects_omitted_source_subpackage(self):
        script=self.root/'build.cjs';script.write_text(script.read_text().replace(",subPackages:[{root:'pkg',pages:['second']}]",''))
        with self.assertRaises(TaskError) as e:await self.action('build',platform='mp-weixin')
        self.assertEqual(e.exception.code,'UNIAPP_PAGES_MISMATCH')
    async def test_conditional_source_topology_is_selected_and_immutable(self):
        source=self.root/'pages.json';source.write_text('{"pages":[{"path":"pages/index/index"}]\n// #ifdef H5\n,"subPackages":[{"root":"pkg","pages":[{"path":"second"}]}]\n// #endif\n}')
        script=self.root/'build.cjs';script.write_text(script.read_text().replace(",subPackages:[{root:'pkg',pages:['second']}]",''))
        out=await self.action('build',platform='mp-weixin');session=await self.resources.acquire('uniapp.project','default');record=session.builds[out['build_id']];self.assertEqual(record['source_plan']['pages'],['pages/index/index'])
        source.write_text(source.read_text()+'\n// changed source')
        with self.assertRaises(TaskError) as e:await self.action('check_artifact',build_id=out['build_id'],started_at=out['started_at'],platform='mp-weixin')
        self.assertEqual(e.exception.code,'UNIAPP_SOURCE_PAGES_CHANGED')
    async def test_unknown_source_condition_is_preparation_before_command(self):
        source=self.root/'pages.json';source.write_text('// #ifdef CUSTOM_FLAG\n'+source.read_text()+'\n// #endif')
        with self.assertRaises(TaskError) as e:await self.action('build',platform='mp-weixin')
        self.assertEqual(e.exception.code,'UNIAPP_PREPARATION_REQUIRED');self.assertFalse((self.root/'dist').exists())

    async def test_h5_css_imports_are_complete_decoded_and_confined(self):
        from taskweave_uniapp.build import artifact_structure
        await self.action('build',platform='h5');base=self.root/'dist/build/h5';(base/'index.html').write_text('<link href="a.css" rel="stylesheet"><script src="assets/app.js"></script>')
        for css in ('@import "missing.css";', '@import url("missing.css");'):
            (base/'a.css').write_text(css)
            with self.subTest(css=css),self.assertRaises(TaskError):artifact_structure(self.config,'h5','dist/build/h5')
        (base/'ok.css').write_text('body{}');(base/'a.css').write_text('@import url("ok.css"); @import "https://example.invalid/external.css";');self.assertIn('ok.css',artifact_structure(self.config,'h5','dist/build/h5'))
        outside=self.root/'outside.css';outside.write_text('body{}');(base/'link.css').symlink_to(outside)
        for css in ('@import "link.css";', '@import "\\2e\\2e/\\2e\\2e/\\2e\\2e/outside.css";', '@import "%2e%2e/%2e%2e/%2e%2e/outside.css";'):
            (base/'a.css').write_text(css)
            with self.subTest(css=css),self.assertRaises(TaskError):artifact_structure(self.config,'h5','dist/build/h5')
    async def test_snapshot_empty_directories_have_cumulative_entry_budget(self):
        from taskweave_uniapp.project import snapshot
        directory=self.root/'empty-tree';directory.mkdir()
        for number in range(4001):(directory/str(number)).mkdir()
        with self.assertRaises(TaskError) as e:snapshot(self.root,'empty-tree')
        self.assertEqual(e.exception.code,'UNIAPP_ARTIFACT_LIMIT')

    async def test_native_unknown_quarantine_survives_roles_close_and_new_provider(self):
        import sys
        from unittest.mock import patch,AsyncMock
        from taskweave_process.runner import ProcessError
        self.config.update(kind='hbuilderx',hbuilderx_path=sys.executable)
        result={'exit_code':-15,'duration_ms':10,'stdout':'native started','stderr':'','stdout_truncated':False,'stderr_truncated':False}
        for code in ('PROCESS_TIMEOUT','CANCELLED'):
            root=self.root/code;project(root);self.config['project_root']=str(root)
            with patch('taskweave_uniapp.build.run_command',new=AsyncMock(side_effect=ProcessError(code,result=result,effect_state='UNKNOWN'))):
                with self.assertRaises(TaskError):await self.action('build',platform='h5',environment='development',role=code)
            passive=await self.action('inspect',role='read-'+code);self.assertEqual(passive['native_write_state']['state'],'quarantined')
            await self.resources.release_all();new_plugin=importlib.import_module('taskweave_uniapp').UniappPlugin();registry=Registry([new_plugin]);resources=Resources(registry);resources.context=self.ctx;self.ctx.resources=resources;self.addAsyncCleanup(resources.release_all)
            self.ctx.scope=Scope(uid(),uid(),uid(),uid())
            with patch('taskweave_uniapp.build.run_command',new=AsyncMock()) as command:
                with self.assertRaises(TaskError) as e:await registry.actions['uniapp.build'].execute(self.ctx,{'platform':'h5','environment':'development','role':'next-attempt'})
                self.assertEqual(e.exception.code,'UNIAPP_NATIVE_ROOT_QUARANTINED');command.assert_not_called()
            collection=await new_plugin.collect_context('uniapp.project',self.ctx,{});self.assertEqual(json.loads(collection.items[0].content)['native_write_state']['state'],'quarantined')
        fresh=self.root/'fresh-independent';project(fresh);self.config['project_root']=str(fresh)
        success={**result,'exit_code':0,'stdout':'编译成功 已停止运行'}
        with patch('taskweave_uniapp.build.run_command',new=AsyncMock(return_value=success)):
            output=await registry.actions['uniapp.build'].execute(self.ctx,{'platform':'h5','environment':'development'});self.assertEqual(output['completion'],'compiled_in_memory')
        self.assertEqual(new_plugin.provider.busy,set())
    async def test_native_not_started_releases_only_owned_lease(self):
        import sys
        from unittest.mock import patch,AsyncMock
        from taskweave_process.runner import ProcessError
        from taskweave_uniapp.lease import native_write_state
        self.config.update(kind='hbuilderx',hbuilderx_path=sys.executable)
        with patch('taskweave_uniapp.build.run_command',new=AsyncMock(side_effect=ProcessError('PROCESS_EXECUTABLE_NOT_FOUND',effect_state='NOT_STARTED'))),self.assertRaises(TaskError):
            await self.action('build',platform='h5',environment='development')
        self.assertEqual(native_write_state(self.root)['state'],'clear')
        self.assertEqual(self.plugin.provider.busy,set())

    async def test_native_lease_atomic_cross_process_and_existing_file_not_overwritten(self):
        import sys,subprocess
        from taskweave_uniapp.lease import claim_native_lease,native_write_state
        root=self.root/'lease-race';root.mkdir();script='from taskweave_uniapp.lease import claim_native_lease;from taskweave.core.validation import TaskError;import sys\ntry:claim_native_lease(sys.argv[1],sys.argv[2]);print("CLAIMED")\nexcept TaskError as e:print(e.code)'
        processes=[subprocess.Popen([sys.executable,'-c',script,str(root),str(number)],stdout=subprocess.PIPE,text=True) for number in range(2)];outputs=[process.communicate(timeout=10)[0].strip() for process in processes]
        self.assertEqual(sorted(outputs),['CLAIMED','UNIAPP_NATIVE_ROOT_QUARANTINED']);self.assertEqual(native_write_state(root)['state'],'quarantined')
        with self.assertRaises(TaskError):claim_native_lease(root,'new-worker')
        other=self.root/'existing-user-file';other.mkdir();marker=other/'.taskweave-uniapp-native-lease';marker.write_text('do not overwrite')
        with self.assertRaises(TaskError):claim_native_lease(other,'other')
        self.assertEqual(marker.read_text(),'do not overwrite')

    async def test_portable_explicit_node_prerequisite_is_verified(self):
        from unittest.mock import patch
        alternate=self.root/'node22';alternate.symlink_to(self.config['node_path'])
        with patch.dict(os.environ,{'TW_UNIAPP_TEST_NODE':str(alternate)}):self.assertEqual(compatible_test_node(),self.config['node_path'])
        with patch.dict(os.environ,{'TW_UNIAPP_TEST_NODE':str(self.root/'absent')}),self.assertRaises(AssertionError):compatible_test_node()

    async def test_native_jest_unknown_and_cli0_noop_keep_lease_and_guard_release(self):
        import sys
        from unittest.mock import patch,AsyncMock
        from taskweave_process.runner import ProcessError
        from taskweave_uniapp.lease import claim_native_lease,release_confirmed_lease,native_write_state
        plugin_root=self.root/'installed-double';plugin_root.mkdir();(plugin_root/'package.json').write_text(json.dumps({'name':'hbuilderx-for-uniapp-test','version':'5.4.0','contributes':{'clicommands':[{'name':'uniapp.test mp-weixin','args':[{'name':'project','type':'string'}]}]}}))
        lib=self.root/'prepared-double-lib';(lib/'node_modules/jest/bin').mkdir(parents=True);(lib/'node_modules/jest/bin/jest.js').write_text('// bounded native-double prerequisite')
        (self.root/'jest.config.js').write_text('module.exports={}');(self.root/'env.js').write_text('module.exports={}')
        self.config.update(kind='hbuilderx',hbuilderx_path=sys.executable,test_plugin_root=str(plugin_root),native_test_lib_root=str(lib),owned_test_project=True);(self.root/'.reports').mkdir()
        result={'exit_code':-15,'duration_ms':10,'stdout':'started','stderr':'','stdout_truncated':False,'stderr_truncated':False}
        with patch('taskweave_uniapp.build.run_command',new=AsyncMock(side_effect=ProcessError('PROCESS_TIMEOUT',result=result,effect_state='UNKNOWN'))),self.assertRaises(TaskError):await self.action('run_tests',platform='mp-weixin')
        self.assertEqual(native_write_state(self.root)['state'],'quarantined');self.config.update(kind='cli',cleanup=True,cleanup_timestamp=999999999999)
        with patch('taskweave_uniapp.build.run_command',new=AsyncMock()) as command:
            with self.assertRaises(TaskError):await self.action('build',platform='h5',role='switch-adapter')
            command.assert_not_called()
        fresh=self.root/'lease-owner-edit';fresh.mkdir();lease=claim_native_lease(fresh,'owner');owner=fresh/'.taskweave-uniapp-native-lease/owner.json';owner.write_text('{"other":"owner"}')
        with self.assertRaises(TaskError):release_confirmed_lease(lease)
        self.assertTrue(owner.is_file())
        symlinkroot=self.root/'symlink-marker';symlinkroot.mkdir();marker=symlinkroot/'.taskweave-uniapp-native-lease';marker.symlink_to(fresh,target_is_directory=True)
        with self.assertRaises(TaskError):claim_native_lease(symlinkroot,'symlink')
        noop=self.root/'native-noop';project(noop);self.config.update(kind='hbuilderx',project_root=str(noop));self.config.pop('test_plugin_root');self.config.pop('native_test_lib_root')
        with patch('taskweave_uniapp.build.run_command',new=AsyncMock(return_value={**result,'exit_code':0,'stdout':'nothing'})),self.assertRaises(TaskError):await self.action('build',platform='h5',environment='development',role='noop')
        self.assertEqual(native_write_state(noop)['state'],'quarantined')

    async def test_source_main_page_and_platform_or_ifndef_topology(self):
        from taskweave_uniapp.project import selected_page_plan
        source=self.root/'pages.json';source.write_text('{"pages":[{"path":"pages/index/index"}]\n// #ifndef H5\n// #ifdef MP-WEIXIN || H5\n,"subPackages":[{"root":"pkg","pages":[{"path":"second"}]}]\n// #endif\n// #endif\n}')
        self.assertEqual(selected_page_plan(self.config,'mp-weixin')['pages'],['pages/index/index','pkg/second']);self.assertEqual(selected_page_plan(self.config,'h5')['pages'],['pages/index/index'])
        script=self.root/'build.cjs';script.write_text(script.read_text().replace("pages:['pages/index/index']","pages:[]"))
        with self.assertRaises(TaskError) as e:await self.action('build',platform='mp-weixin')
        self.assertEqual(e.exception.code,'UNIAPP_PAGES_MISMATCH')

    async def test_wechat_main_page_order_preserves_homepage_with_complete_files(self):
        from taskweave_uniapp.build import artifact_structure
        await self.action('build',platform='mp-weixin');base=self.root/'dist/build/mp-weixin'
        (self.root/'pages.json').write_text(json.dumps({'pages':[{'path':'a'},{'path':'b'}]}))
        for page in ('a','b'):
            for extension,value in (('.js','Page({})'),('.json','{}'),('.wxml','<view/>')):(base/(page+extension)).write_text(value)
        (base/'app.json').write_text(json.dumps({'pages':['a','b']}))
        self.assertIn('a.js',artifact_structure(self.config,'mp-weixin','dist/build/mp-weixin'))
        (base/'app.json').write_text(json.dumps({'pages':['b','a']}))
        with self.assertRaises(TaskError) as e:artifact_structure(self.config,'mp-weixin','dist/build/mp-weixin')
        self.assertEqual(e.exception.code,'UNIAPP_PAGES_MISMATCH')

    async def test_wechat_subpage_order_is_preserved_packages_are_root_keyed(self):
        from taskweave_uniapp.build import artifact_structure
        await self.action('build',platform='mp-weixin');base=self.root/'dist/build/mp-weixin'
        packages=[{'root':'pkg','pages':['first','second']},{'root':'other','pages':['only']}]
        (self.root/'pages.json').write_text(json.dumps({'pages':['pages/index/index'],'subPackages':packages}))
        for page in ('pkg/first','other/only'):
            for extension,value in (('.js','Page({})'),('.json','{}'),('.wxml','<view/>')):
                file=base/(page+extension);file.parent.mkdir(parents=True,exist_ok=True);file.write_text(value)
        (base/'app.json').write_text(json.dumps({'pages':['pages/index/index'],'subPackages':packages}))
        self.assertIn('pkg/first.js',artifact_structure(self.config,'mp-weixin','dist/build/mp-weixin'))
        (base/'app.json').write_text(json.dumps({'pages':['pages/index/index'],'subPackages':list(reversed(packages))}))
        self.assertIn('other/only.js',artifact_structure(self.config,'mp-weixin','dist/build/mp-weixin'))
        packages[0]['pages'].reverse();(base/'app.json').write_text(json.dumps({'pages':['pages/index/index'],'subPackages':packages}))
        with self.assertRaises(TaskError) as e:artifact_structure(self.config,'mp-weixin','dist/build/mp-weixin')
        self.assertEqual(e.exception.code,'UNIAPP_PAGES_MISMATCH')


class UniappFinalRetainedTests(unittest.IsolatedAsyncioTestCase):
    setUp=UniappTests.setUp
    action=UniappTests.action
    async def test_40_cached_public_passive_contexts_prune_and_keep_peer_evidence(self):
        await self.action('inspect');first=self.ctx.scope.attempt_id
        build=await self.action('build',role='peer',platform='h5');peer=self.resources.items[('uniapp.project','peer')]
        peer_evidence=json.loads(json.dumps(self.plugin.evidence.journals[first]))
        for _ in range(40):
            scope=Scope(self.ctx.scope.task_id,self.ctx.scope.run_id,uid(),uid())
            self.ctx=PluginContext(scope,self.results,self.resources,{'uniapp_config':self.config},{},self.cancel,lambda *a:None);self.resources.context=self.ctx
            await self.action('inspect');await self.plugin.collect_context('uniapp.project',self.ctx,{})
        self.assertLessEqual(len(self.plugin.evidence.journals),2)
        self.assertEqual(self.plugin.evidence.journals[first],peer_evidence)
        self.assertIn(build['build_id'],peer.builds)
        await self.resources.release_all()
        self.assertFalse(self.plugin.evidence.journals);self.assertFalse(self.plugin.evidence.owners)
