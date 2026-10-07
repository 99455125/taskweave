"""Pinned bridge boundaries and typed simulator actions; no GUI in fast tests."""
import asyncio
import importlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from taskweave.plugins.registry import Registry
from taskweave.core.validation import TaskError,validate
from tests.fixtures.uniapp_project import compatible_test_node

NAMES=('check_environment connect disconnect current_page page_stack navigate observe get_element get_page_data tap input scroll touch call_component_method assert_page assert_element assert_page_data wait_for get_storage set_storage remove_storage clear_storage mock_method restore_mock screenshot read_logs').split()
RELEASE_NAMES=['preview','upload']
MINIMUM={name:{} for name in NAMES+RELEASE_NAMES}
MINIMUM['upload']={'version':'1.0.0'}
MINIMUM.update(navigate={'mode':'navigateBack'},get_element={'selector':'#tap'},get_page_data={'paths':['count']},tap={'selector':'#tap'},input={'selector':'#input','value':''},scroll={'y':0},touch={'selector':'#tap','phase':'start'},call_component_method={'selector':'#component','method':'increment'},assert_page={'path':'pages/main/main'},assert_element={'selector':'#tap'},assert_page_data={'path':'count','value':0},wait_for={'kind':'page','path':'pages/main/main','timeout_ms':100},get_storage={'key':'key'},set_storage={'key':'key','value':None},remove_storage={'key':'key'},clear_storage={'scope':'namespace'},mock_method={'method':'request','value':{}},restore_mock={'method':'request'})

class WechatContractTests(unittest.TestCase):
    def test_all_26_registered_actions_resources_results_and_strict_schemas(self):
        try:module=importlib.import_module('taskweave_wechat_dev')
        except ModuleNotFoundError:self.fail('All 26 wechat_dev plugin actions missing')
        registry=Registry([module.WechatDevPlugin()])
        self.assertEqual(set(registry.actions),{'wechat_dev.'+n for n in NAMES+RELEASE_NAMES})
        self.assertEqual(set(registry.providers),{'wechat_dev.simulator'})
        self.assertEqual(set(registry.handlers),{'wechat_dev.file','wechat_dev.image','wechat_dev.json','wechat_dev.operation_failure'})
        registry.contributions(list(registry.actions))
        for action in registry.actions.values():
            self.assertIs(action.spec.input_schema.get('additionalProperties'),False)
            valid=MINIMUM[action.name];validate(valid,action.spec.input_schema)
            with self.subTest(action=action.spec.id),self.assertRaises(TaskError):validate({**valid,'unexpected':True},action.spec.input_schema)
            if action.spec.effect=='WRITE':self.assertFalse(action.spec.retry_safe)
        self.assertIn('wechat_dev.inspect_page',registry.tools)

class WechatProtocolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.cancel=threading.Event();self.ctx=SimpleNamespace(cancelled=self.cancel.is_set,
             log=lambda *args,**kw:None,resolve_secret=lambda ref:'fixture-secret')
        prepared=Path(self.temp.name)/'node_modules/miniprogram-automator';prepared.mkdir(parents=True)
        (prepared/'package.json').write_text('{"name":"miniprogram-automator","version":"0.12.1"}')
        self.config={'node_path':compatible_test_node(),'module_root':self.temp.name,
                     'project_root':self.temp.name,'env':{},'env_secret_refs':{'TOKEN':'logical'}}
    async def bridge(self,mode=''):
        try:module=importlib.import_module('taskweave_wechat_dev.bridge')
        except ModuleNotFoundError:self.fail('SimulatorBridge missing')
        self.config['env']['TW_WECHAT_PROTOCOL_MODE']=mode
        with patch.object(module,'BRIDGE_FILE',Path('tests/fixtures/wechat_bridge.cjs').resolve()):
            bridge=await module.SimulatorBridge.start(self.ctx,self.config)
        self.addAsyncCleanup(bridge.close);return bridge
    async def test_real_node_request_id_and_identity(self):
        bridge=await self.bridge();result=await bridge.request('current_page',{},timeout_seconds=1)
        self.assertEqual(result['session_id'],'fixture-session');self.assertEqual(result['page_path'],'pages/main/main')
    async def test_malformed_wrong_duplicate_oversize_and_exit_poison_session(self):
        for mode in ('malformed','wrong-id','duplicate','oversize','exit'):
            bridge=await self.bridge(mode)
            with self.subTest(mode=mode):
                try:await bridge.request('current_page',{},timeout_seconds=1)
                except TaskError:pass
                await asyncio.sleep(.1)
                self.assertTrue(bridge.closed)
                self.assertIsNotNone(bridge.process.process.returncode)
    async def test_timeout_and_cancel_close_own_bridge(self):
        bridge=await self.bridge('missing')
        with self.assertRaises(TaskError):await bridge.request('tap',{},timeout_seconds=1)
        self.assertTrue(bridge.closed)
        self.cancel.clear();bridge=await self.bridge('missing');self.cancel.set()
        with self.assertRaises(TaskError):await bridge.request('current_page',{},timeout_seconds=1)
        self.assertTrue(bridge.closed)
    async def test_arbitrary_eval_and_generic_wx_are_not_protocol_methods(self):
        bridge=await self.bridge()
        for method in ('evaluate','callWxMethod','send','remote'):
            with self.subTest(method=method),self.assertRaises(TaskError):await bridge.request(method,{},timeout_seconds=1)
    async def test_late_reply_after_page_change_is_not_used(self):
        bridge=await self.bridge()
        first=await bridge.request('current_page',{},timeout_seconds=1)
        with self.assertRaises(TaskError):await bridge.request('observe',{'page_revision':first['page_revision']+1},timeout_seconds=1)
        self.assertTrue(bridge.closed)

class WechatSdkFixture:
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        package=self.root/'deps/node_modules/miniprogram-automator';package.mkdir(parents=True)
        (package/'package.json').write_text('{"name":"miniprogram-automator","version":"0.12.1","main":"index.cjs"}')
        (package/'index.cjs').write_bytes(Path('tests/fixtures/wechat_sdk.cjs').read_bytes())
        self.cancel=threading.Event();self.ctx=SimpleNamespace(cancelled=self.cancel.is_set,resolve_secret=lambda ref:'fixture-secret',log=lambda *a,**k:None)
        self.config={'node_path':compatible_test_node(),'module_root':str(self.root/'deps'),'project_root':str(self.root)}
    async def start(self):
        try:module=importlib.import_module('taskweave_wechat_dev.bridge')
        except ModuleNotFoundError:self.fail('Official-method bridge adapter missing')
        self.bridge=await module.SimulatorBridge.start(self.ctx,self.config);self.addAsyncCleanup(self.bridge.close)
        return await self.bridge.request('connect',{'endpoint':'ws://127.0.0.1:19560','appid':'touristappid','pages':['pages/main/main','pages/second/second'],'owned':False,'storage_namespace':'tw-fixture:','allow_borrowed_mock':True,'component_methods':['increment']},timeout_seconds=2)
    async def req(self,action,**params):return (await self.bridge.request(action,params,timeout_seconds=2))['result']
class WechatSdkAdapterTests(WechatSdkFixture,unittest.IsolatedAsyncioTestCase):
    async def test_navigation_invalidates_element_and_assertions_are_real(self):
        await self.start();element=await self.req('get_element',selector='#tap')
        await self.req('tap',element_id=element['element_id']);self.assertEqual((await self.req('get_page_data',paths=['count']))['data']['count'],1)
        await self.req('navigate',mode='navigateTo',url='/pages/second/second')
        with self.assertRaises(TaskError):await self.req('tap',element_id=element['element_id'])
        with self.assertRaises(TaskError):await self.req('assert_page',path='pages/main/main')
    async def test_namespace_clear_preserves_other_storage_and_static_mock_restore(self):
        await self.start();await self.req('set_storage',key='key',value={'nested':True})
        self.assertEqual((await self.req('get_storage',key='key'))['value'],{'nested':True})
        await self.req('clear_storage',scope='namespace');self.assertFalse((await self.req('get_storage',key='key'))['exists'])
        await self.req('mock_method',method='request',value={'data':{'ok':True}});restored=await self.req('restore_mock',method='request');self.assertTrue(restored['restored'])
        for value in ('function () {}','() => 1'):
            with self.assertRaises(TaskError):await self.req('mock_method',method='request',value=value)
    async def test_wait_deadline_and_restore_failure_are_errors(self):
        await self.start()
        with self.assertRaises(TaskError):await self.req('wait_for',kind='element',selector='#missing',timeout_ms=100)
        self.config['env']={'TW_WECHAT_RESTORE_FAIL':'1'};await self.bridge.close();await self.start()
        await self.req('mock_method',method='request',value={'ok':True})
        with self.assertRaises(TaskError):await self.req('restore_mock',method='request')
    async def test_known_secret_is_masked_before_producer_text_and_log_clip(self):
        secret='quoted"\\secret-跨界'
        self.ctx.resolve_secret=lambda ref:secret
        self.config['env_secret_refs']={'TW_WECHAT_SECRET':'logical'}
        await self.start()
        element=await self.req('get_element',selector='#secret',max_text_chars=4096)
        await self.req('mock_method',method='request',value={})
        logs=await self.req('read_logs')
        serialized=json.dumps([element,logs],ensure_ascii=False)
        self.assertNotIn('quoted',serialized)
        self.assertIn('[REDACTED]',serialized)
    async def test_explicit_disconnect_cleanup_survives_resource_close(self):
        await self.start();result=await self.req('disconnect')
        self.bridge.cleanup=result
        await self.bridge.close()
        self.assertEqual(self.bridge.cleanup,result)
    async def test_connect_waits_for_bounded_readonly_startup_metadata_without_replaying_writes(self):
        self.config['env']={'TW_WECHAT_READY_DELAY':'2'}
        result=await self.start();self.assertTrue(result['result']['connected'])
        self.assertEqual((await self.req('get_page_data',paths=['count']))['data']['count'],0)
    async def test_sdk_timeout_taints_session_and_finite_cleanup_reaps_without_next_call(self):
        self.config['env']={'TW_WECHAT_STALL':'1'}
        await self.start();await self.req('mock_method',method='request',value={})
        with self.assertRaises(TaskError):await self.bridge.request('tap',{'selector':'#tap','rpc_timeout_ms':30},timeout_seconds=1)
        with self.assertRaises(TaskError):await self.bridge.request('tap',{'selector':'#tap'},timeout_seconds=1)
        await asyncio.sleep(.2)
        self.assertIsNotNone(self.bridge.process.process.returncode)
        self.assertTrue(self.bridge.cleanup['mocks_restored'])

class WechatActionsFixture(WechatSdkFixture):
    def setUp(self):
        super().setUp()
        from taskweave_wechat_dev import WechatDevPlugin
        from taskweave.core.ports import Scope
        from taskweave.infrastructure.storage import Results,uid
        from taskweave.infrastructure.worker import PluginContext,Resources
        (self.root/'project.config.json').write_text(json.dumps({'appid':'touristappid','miniprogramRoot':'./'}))
        (self.root/'app.json').write_text(json.dumps({'pages':['pages/main/main','pages/second/second']}))
        self.config.update(endpoint='ws://127.0.0.1:19560',storage_namespace='tw-actions:',component_methods=['increment'],allow_borrowed_mock=True)
        self.plugin=WechatDevPlugin();self.registry=Registry([self.plugin]);self.resources=Resources(self.registry)
        self.results=Results(self.root/'host',Scope(uid(),uid(),uid(),uid()),self.registry)
        self.ctx=PluginContext(self.results.scope,self.results,self.resources,{'wechat_dev_config':self.config},{},self.cancel,lambda *args:None)
        self.resources.context=self.ctx;self.addAsyncCleanup(self.resources.release_all)
    async def action(self,name,**inputs):
        action=self.registry.actions['wechat_dev.'+name];validate(inputs,action.spec.input_schema)
        out=await action.execute(self.ctx,inputs);validate(out,action.spec.output_schema);return out
class WechatActionsTests(WechatActionsFixture,WechatSdkAdapterTests):
    async def test_all_26_actions_have_valid_outputs_and_effects(self):
        seen=set()
        async def call(name,**inputs):seen.add(name);return (await self.action(name,**inputs))['result']
        await call('check_environment');await call('connect')
        self.assertEqual((await call('current_page'))['path'],'pages/main/main')
        self.assertEqual(len((await call('page_stack'))['pages']),1)
        self.assertEqual((await call('observe',selectors=['#tap'],paths=['count']))['data']['count'],0)
        element=await call('get_element',selector='#tap');await call('tap',element_id=element['element_id'])
        await call('input',selector='#input',value='typed');await call('scroll',y=3)
        for phase in ('start','move','end'):await call('touch',selector='#tap',phase=phase,touches=[{'identifier':1,'pageX':1,'pageY':2}])
        self.assertEqual((await call('call_component_method',selector='#component',method='increment',args=[2]))['value'],3)
        await call('assert_page',path='pages/main/main');await call('assert_element',selector='#input',value='typed')
        await call('assert_page_data',path='count',value=3);await call('wait_for',kind='data',path='count',value=3,timeout_ms=100)
        self.assertEqual((await call('get_page_data',paths=['count']))['data']['count'],3)
        await call('set_storage',key='test',value={'ok':True});self.assertTrue((await call('get_storage',key='test'))['exists'])
        await call('remove_storage',key='test');await call('clear_storage',scope='namespace')
        await call('mock_method',method='request',value={});await call('restore_mock',method='request')
        self.assertEqual(len((await call('read_logs'))['entries']),1)
        image=await call('screenshot');self.assertEqual(image['artifact']['size_bytes'],68)
        prepared=self.plugin.result_handlers()['wechat_dev.image'].prepare(SimpleNamespace(payload=image['artifact']))
        self.assertEqual(prepared.kind,'file')
        for mode in ('navigateTo','redirectTo','switchTab','reLaunch'):await call('navigate',mode=mode,url='/pages/second/second')
        await call('navigate',mode='navigateBack');await call('disconnect')
        self.assertEqual(seen,set(NAMES))
    async def test_missing_connection_failed_assertion_and_budget_do_not_report_success(self):
        with self.assertRaises(TaskError):await self.action('tap',selector='#tap')
        await self.action('connect')
        for name,inputs in [('assert_page',{'path':'wrong'}),('get_element',{'selector':'#missing'}),('wait_for',{'kind':'element','selector':'#missing','timeout_ms':10}),('screenshot',{'max_bytes':8})]:
            with self.subTest(name=name),self.assertRaises(TaskError):await self.action(name,**inputs)
        with self.assertRaises(TaskError):await self.action('clear_storage',scope='all')
        with self.assertRaises(TaskError):await self.action('mock_method',method='request',value='function () {}')
    async def test_cumulative_write_failure_retains_earlier_write_after_read_and_other_role(self):
        await self.action('connect');await self.action('tap',selector='#tap');await self.action('current_page')
        await self.action('connect',role='second');await self.action('input',role='second',selector='#input',value='second')
        saved=await self.plugin.failure_results(self.ctx,TaskError('LATER_ERROR'))
        entries=saved[0].payload['operations'];self.assertEqual(len(entries),4)
        self.assertEqual([e['action_id'] for e in entries],['wechat_dev.connect','wechat_dev.tap','wechat_dev.connect','wechat_dev.input'])
        self.assertEqual(saved[0].payload['effect_state'],'UNKNOWN');self.assertTrue(all('cleanup' in e for e in entries))
    async def test_caller_flag_and_remote_attach_never_gain_window_close(self):
        with self.assertRaises(TaskError):await self.action('connect',owned=True)
        self.config.update(owned=True,endpoint='wss://remote.example.test:19560')
        connected=await self.action('connect');self.assertEqual(connected['result']['ownership'],'borrowed')
        result=await self.action('disconnect');self.assertEqual(result['result']['window_closed'],'not_owned')
    async def test_occupied_endpoint_launch_never_gains_window_close(self):
        from taskweave_wechat_dev import actions
        self.config.update(mode='launch',cli_path=compatible_test_node(),port=19560)
        response={'command':'agent-start','status':'ok','autoPort':19560,'openedProjectWindow':True}
        command={'exit_code':0,'stdout':json.dumps(response),'stderr':'','stdout_truncated':False,'stderr_truncated':False}
        with patch.object(actions,'owned_root_proof',return_value={'creation':'fixture'}),patch.object(actions,'port_available',return_value=False),patch.object(actions,'run_command',return_value=command):
            out=await self.action('connect')
        self.assertEqual(out['result']['ownership'],'borrowed');self.assertEqual(out['result']['launch']['ownership'],'uncertain')
        self.assertIs(out['result']['launch']['endpoint_was_free'],False)
        self.assertEqual((await self.action('disconnect'))['result']['window_closed'],'not_owned')
    async def test_passive_context_does_not_start_or_connect_and_active_observation_is_read(self):
        with patch('taskweave_wechat_dev.bridge.SimulatorBridge.start',side_effect=AssertionError('implicit start')):
            passive=await self.plugin.collect_context('wechat_dev.page',self.ctx,{},include_view=False)
        self.assertFalse(json.loads(passive.items[0].content)['connected'])
        await self.action('connect');before=len(self.plugin.evidence.entries[self.ctx.scope.attempt_id])
        observed=await self.plugin.collect_context('wechat_dev.page',self.ctx,{'selectors':['#tap'],'paths':['count'],'screenshot':True})
        self.assertTrue(json.loads(observed.items[0].content)['connected'])
        self.assertEqual(observed.views[1].renderer,'wechat_dev.screenshot')
        self.assertEqual(len(self.plugin.evidence.entries[self.ctx.scope.attempt_id]),before)
        with self.assertRaises(TaskError):await self.registry.tools['wechat_dev.inspect_page'].execute(self.ctx,{'unexpected':True})
    async def test_diagnostic_capacity_is_reserved_before_mutation(self):
        await self.action('connect')
        for _ in range(31):await self.action('tap',selector='#tap')
        with self.assertRaises(TaskError):await self.action('tap',selector='#tap')
        self.assertEqual((await self.action('get_page_data',paths=['count']))['result']['data']['count'],31)
        saved=await self.plugin.failure_results(self.ctx,TaskError('LATER'))
        self.assertLessEqual(len(json.dumps(saved[0].payload).encode()),65536)
    async def test_real_default_discovery_worker_failure_persists_cumulative_operations(self):
        from taskweave.application.service import Application
        from taskweave.infrastructure.storage import uid
        def run():
            with tempfile.TemporaryDirectory() as home,Application(home) as app:
                app.configure_plugin('wechat_dev',True)
                environment=app.environments.save('owned SDK boundary fixture',{'wechat_dev_config':self.config},{})['environment_id']
                task=app.tasks.create('wechat prior writes then failure')['task_id']
                code='async def run(ctx, inputs):\n    await ctx.call("wechat_dev.connect", {})\n    await ctx.call("wechat_dev.tap", {"selector":"#tap"})\n    await ctx.call("wechat_dev.current_page", {})\n    await ctx.call("wechat_dev.connect", {"role":"other"})\n    await ctx.call("wechat_dev.input", {"role":"other","selector":"#input","value":"other"})\n    raise RuntimeError("later error")'
                step=app.steps.save(task,{'name':'cumulative mutation evidence','capabilities':['wechat_dev.connect','wechat_dev.tap','wechat_dev.current_page','wechat_dev.input'],'step_content':code})
                app.confirm_step_manual(step['step_id'],step['content_hash'],environment_id=environment)
                run_id=app.runs.create(task,environment_id=environment)['run_id'];app.runs.start(run_id,uid());done=app.runs.wait(run_id,timeout=15)
                self.assertEqual(done['status'],'FAILED');self.assertEqual(len(done['results']),1)
                result=done['results'][0];self.assertEqual(result['handler_id'],'wechat_dev.operation_failure')
                data=app.runs.read_result(result['result_id'])['data'];self.assertEqual(len(data['operations']),4)
                self.assertEqual([row['action_id'] for row in data['operations']],['wechat_dev.connect','wechat_dev.tap','wechat_dev.connect','wechat_dev.input'])
                self.assertTrue(all(row['cleanup']['window_closed']=='not_owned' for row in data['operations']))
        await asyncio.to_thread(run)
    async def test_known_secret_in_launch_provenance_is_masked_before_failure_persistence(self):
        import os
        from taskweave_wechat_dev import actions
        secret=self.root.name
        self.ctx.secret_refs={'logical':'env:TW_WECHAT_JOURNAL_SECRET'}
        self.config.update(mode='launch',cli_path=compatible_test_node(),port=19560,env_secret_refs={'TOKEN':'logical'})
        response={'command':'agent-start','status':'ok','autoPort':19560,'openedProjectWindow':True}
        command={'exit_code':0,'stdout':json.dumps(response),'stderr':'','stdout_truncated':False,'stderr_truncated':False}
        with patch.dict(os.environ,{'TW_WECHAT_JOURNAL_SECRET':secret}),patch.object(actions,'owned_root_proof',return_value=None),patch.object(actions,'port_available',return_value=False),patch.object(actions,'run_command',return_value=command):
            await self.action('connect')
            saved=await self.plugin.failure_results(self.ctx,TaskError('E'*125+secret))
        self.assertNotIn(secret,json.dumps(saved[0].payload))
        self.assertIn('[REDACTED]',json.dumps(saved[0].payload))
        self.assertEqual(saved[0].payload['error_code'],'E'*125+'[RE')

class WechatFixLifecycleTests(WechatSdkFixture,unittest.IsolatedAsyncioTestCase):
    async def test_queued_deadline_and_cancel_do_not_dispatch_or_poison_active(self):
        self.config['env']={'TW_WECHAT_STALL':'1'}
        await self.start()
        active=asyncio.create_task(self.bridge.request('tap',{'selector':'#tap'},timeout_seconds=2))
        await asyncio.sleep(.04)
        started=asyncio.get_running_loop().time()
        with self.assertRaises(TaskError):
            await self.bridge.request('tap',{'selector':'#tap'},timeout_seconds=.05)
        self.assertLess(asyncio.get_running_loop().time()-started,.2)
        self.assertFalse(self.bridge.closed)
        queued=asyncio.create_task(self.bridge.request('current_page',{},timeout_seconds=2))
        await asyncio.sleep(.03);queued.cancel()
        with self.assertRaises(asyncio.CancelledError):await queued
        await active
        self.assertEqual((await self.req('get_page_data',paths=['count']))['data']['count'],1)

    async def test_cancelled_mocked_transport_reports_unknown_and_reaps(self):
        self.config['env']={'TW_WECHAT_STALL':'1'}
        await self.start();await self.req('mock_method',method='request',value={})
        task=asyncio.create_task(self.bridge.request('tap',{'selector':'#tap'},timeout_seconds=2))
        await asyncio.sleep(.05);self.cancel.set()
        with self.assertRaises(TaskError):await task
        self.assertEqual(self.bridge.cleanup['state'],'unknown')
        self.assertFalse(self.bridge.cleanup['mocks_restored'])
        self.assertEqual(self.bridge.cleanup['window_closed'],'unconfirmed')
        self.assertIsNotNone(self.bridge.process.process.returncode)

    async def test_external_cancel_with_usable_transport_restores_mock(self):
        self.config['env']={'TW_WECHAT_STALL':'1'}
        await self.start();await self.req('mock_method',method='request',value={})
        task=asyncio.create_task(self.bridge.request('tap',{'selector':'#tap'},timeout_seconds=2))
        await asyncio.sleep(.05);task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertTrue(self.bridge.cleanup['mocks_restored'])
        self.assertEqual(self.bridge.cleanup['window_closed'],'not_owned')
        self.assertIsNotNone(self.bridge.process.process.returncode)

    async def test_active_observe_keeps_ownership_when_queued_read_and_write_expire(self):
        self.config['env']={'TW_WECHAT_READ_STALL':'1'}
        await self.start()
        active=asyncio.create_task(self.bridge.request('observe',{'paths':['count']},timeout_seconds=1))
        await asyncio.sleep(.03)
        async def queued(method,params):
            started=asyncio.get_running_loop().time()
            with self.assertRaises(TaskError):await self.bridge.request(method,params,timeout_seconds=.05)
            self.assertLess(asyncio.get_running_loop().time()-started,.15)
        await asyncio.gather(queued('current_page',{}),queued('tap',{'selector':'#tap'}))
        self.assertFalse(self.bridge.closed)
        self.assertEqual((await active)['result']['data']['count'],0)
        self.assertEqual((await self.req('get_page_data',paths=['count']))['data']['count'],0)

class WechatFixActionsTests(WechatActionsFixture,unittest.IsolatedAsyncioTestCase):
    async def test_clean_disconnect_releases_exact_marker_for_same_scope_reconnect(self):
        from taskweave_wechat_dev import actions
        self.config.update(mode='launch',cli_path=compatible_test_node(),port=19560)
        response={'command':'agent-start','status':'ok','autoPort':19560,'openedProjectWindow':True}
        command={'exit_code':0,'stdout':json.dumps(response),'stderr':'','stdout_truncated':False,'stderr_truncated':False}
        with patch.object(actions,'owned_root_proof',return_value=None),patch.object(actions,'port_available',return_value=False),patch.object(actions,'run_command',return_value=command):
            await self.action('connect');await self.action('disconnect')
            self.assertFalse((self.root/'.taskweave-wechat-active').exists())
            await self.action('connect');await self.action('disconnect')
            await self.action('connect',role='other');await self.action('disconnect',role='other')

    async def test_cumulative_long_metadata_reserves_before_mutation_and_retains_all(self):
        from taskweave_wechat_dev import actions
        page='pages/'+'跨"界'*650
        (self.root/'app.json').write_text(json.dumps({'pages':['pages/main/main',page]}))
        await self.action('connect');await self.action('navigate',mode='navigateTo',url='/'+page)
        accepted=0
        for _ in range(30):
            try:await self.action('tap',selector='#tap');accepted+=1
            except TaskError as error:
                self.assertEqual(error.code,'WECHAT_DIAGNOSTIC_CAPACITY');break
        self.assertLess(accepted,30)
        self.assertEqual((await self.action('get_page_data',paths=['count']))['result']['data']['count'],accepted)
        saved=await self.plugin.failure_results(self.ctx,TaskError('LATER'))
        payload=saved[0].payload
        self.assertLessEqual(len(json.dumps(payload).encode()),65536)
        self.assertEqual(len(payload['operations']),accepted+2)
        self.assertTrue(all(row['state']=='completed' for row in payload['operations']))

    async def test_unknown_partial_foreign_and_symlink_markers_are_not_released(self):
        from taskweave_wechat_dev.actions import Session
        import os
        await self.action('connect')
        session=next(iter(self.plugin.evidence.sessions.values()))
        path=self.root/'.taskweave-wechat-active';path.mkdir()
        identity=(path.stat().st_dev,path.stat().st_ino);session.launch_lock=(path,identity)
        clean={'state':'disconnected','mocks_restored':True,'window_closed':'not_owned'}
        for cleanup in ({**clean,'state':'unknown'},{**clean,'state':'partial'},{**clean,'mocks_restored':False}):
            session.release_marker(cleanup);self.assertTrue(path.is_dir())
        path.rmdir();target=self.root/'foreign';target.mkdir();os.symlink(target,path)
        session.release_marker(clean);self.assertTrue(path.is_symlink());self.assertTrue(target.is_dir())
        path.unlink();path.mkdir();session.launch_lock=(path,(-1,-1))
        session.release_marker(clean);self.assertTrue(path.is_dir())
        session.launch_lock=None

    async def worker_failure(self,code,*,warning=False):
        from taskweave.application.service import Application
        from taskweave.infrastructure.storage import uid
        def run():
            with tempfile.TemporaryDirectory() as home,Application(home) as app:
                app.configure_plugin('wechat_dev',True)
                environment=app.environments.save('bounded fix boundary',{'wechat_dev_config':self.config},{})['environment_id']
                task=app.tasks.create('fix durable failure')['task_id']
                step=app.steps.save(task,{'name':'fix failure','capabilities':['wechat_dev.connect','wechat_dev.navigate','wechat_dev.tap','wechat_dev.mock_method'],'step_content':code})
                app.confirm_step_manual(step['step_id'],step['content_hash'],environment_id=environment)
                run_id=app.runs.create(task,environment_id=environment)['run_id'];app.runs.start(run_id,uid());done=app.runs.wait(run_id,timeout=15)
                self.assertEqual(done['status'],'FAILED');self.assertEqual(len(done['results']),1)
                result=done['results'][0];self.assertEqual(result['handler_id'],'wechat_dev.operation_failure')
                if warning:
                    events=[json.loads(row['payload_json']) for row in app.runs.events(run_id) if row['kind']=='Log']
                    self.assertTrue(any(row.get('level')=='WARNING' and row.get('message','').startswith('WECHAT_CLEANUP_UNCONFIRMED:') for row in events))
                return app.runs.read_result(result['result_id'])['data']
        return await asyncio.to_thread(run)

    async def test_real_worker_capacity_failure_preserves_every_accepted_long_page_write(self):
        page='pages/'+'跨"界'*650
        (self.root/'app.json').write_text(json.dumps({'pages':['pages/main/main',page]}))
        code='async def run(ctx, inputs):\n    await ctx.call("wechat_dev.connect", {})\n    await ctx.call("wechat_dev.navigate", '+repr({'mode':'navigateTo','url':'/'+page})+')\n    for i in range(30):\n        await ctx.call("wechat_dev.tap", {"selector":"#tap"})'
        data=await self.worker_failure(code)
        self.assertEqual(data['error_code'],'WECHAT_DIAGNOSTIC_CAPACITY')
        self.assertGreaterEqual(len(data['operations']),3);self.assertLess(len(data['operations']),32)
        self.assertTrue(all(row['state']=='completed' for row in data['operations']))
        self.assertLessEqual(len(json.dumps(data).encode()),65536)
        self.assertTrue(all(row['cleanup']['mocks_restored'] for row in data['operations']))

    async def test_real_worker_mocked_unusable_transport_persists_unknown_and_warning(self):
        self.config['env']={'TW_WECHAT_BREAK_PROTOCOL':'1'}
        data=await self.worker_failure('async def run(ctx, inputs):\n    await ctx.call("wechat_dev.connect", {})\n    await ctx.call("wechat_dev.mock_method", {"method":"request","value":{}})\n    await ctx.call("wechat_dev.tap", {"selector":"#tap"})',warning=True)
        self.assertEqual(len(data['operations']),3)
        self.assertEqual(data['operations'][1]['state'],'completed')
        self.assertEqual(data['operations'][2]['state'],'UNKNOWN')
        for row in data['operations']:
            self.assertEqual(row['cleanup']['state'],'unknown');self.assertFalse(row['cleanup']['mocks_restored'])
            self.assertEqual(row['cleanup']['window_closed'],'unconfirmed')

    async def test_launch_provenance_over_capacity_is_rejected_before_cli_and_marker(self):
        from taskweave_wechat_dev import actions
        await self.action('connect');await self.action('tap',selector='#tap')
        # A second-role launch has the same policy/configuration as its own
        # newly opened resource; prior accepted writes remain untouched.
        self.config.update(mode='launch',cli_path=compatible_test_node(),port=19560)
        with patch.object(actions,'owned_root_proof',return_value={'source':'跨"界'*10000}),patch.object(actions,'port_available',return_value=True),patch.object(actions,'run_command') as command:
            with self.assertRaises(TaskError) as failed:await self.action('connect',role='launch')
            self.assertEqual(failed.exception.code,'WECHAT_DIAGNOSTIC_CAPACITY');command.assert_not_called()
        self.assertFalse((self.root/'.taskweave-wechat-active').exists())
        saved=await self.plugin.failure_results(self.ctx,TaskError('LATER'))
        operations=saved[0].payload['operations']
        self.assertEqual([row['state'] for row in operations],['completed','completed','NOT_STARTED'])
        self.assertLessEqual(len(json.dumps(saved[0].payload).encode()),65536)


class WechatFix2AcquireTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_becomes_true_at_acquired_lock_reaps_before_return_without_dispatch(self):
        from taskweave_wechat_dev.bridge import SimulatorBridge
        class Process:
            def __init__(self):self.closed=False;self.writes=[];self.queue=asyncio.Queue()
            async def read_line(self,**kwargs):return await self.queue.get()
            async def write_line(self,line,**kwargs):self.writes.append(line)
            async def close(self):self.closed=True
        checks=0
        def cancelled():
            nonlocal checks
            checks+=1;return checks>=2
        process=Process();bridge=SimulatorBridge(SimpleNamespace(cancelled=cancelled),process,())
        # Previously connected state models the cleanup truth requirement;
        # there is deliberately no SDK/native target in this deterministic probe.
        bridge.remote_session='fixture-session';self.addAsyncCleanup(bridge.close)
        with self.assertRaises(TaskError) as failed:await bridge.request('tap',{'selector':'#tap'},timeout_seconds=1)
        self.assertEqual(failed.exception.code,'CANCELLED');self.assertEqual(checks,2)
        self.assertEqual(process.writes,[]);self.assertFalse(bridge.lock.locked())
        self.assertTrue(bridge.closed);self.assertTrue(process.closed);self.assertTrue(bridge.reader.done())
        self.assertTrue(bridge.close_task.done())
        self.assertEqual(bridge.cleanup,{'state':'unknown','mocks_restored':False,'window_closed':'unconfirmed'})

class WechatFix2CounterTests(WechatActionsFixture,unittest.IsolatedAsyncioTestCase):
    async def test_failure_receipt_uses_actual_nonzero_bounded_stderr_counter(self):
        package=self.root/'deps/node_modules/miniprogram-automator/index.cjs'
        with package.open('a') as source:source.write("\nprocess.stderr.write('x'.repeat(8192));\n")
        self.config['max_output_bytes']=1024
        await self.action('connect')
        session=next(iter(self.plugin.evidence.sessions.values()))
        for _ in range(25):
            if session.bridge.process.stderr_total>=8192:break
            await asyncio.sleep(.02)
        self.assertEqual(session.bridge.process.stderr_total,8192)
        with self.assertRaises(TaskError):await self.action('tap',selector='#missing')
        saved=await self.plugin.failure_results(self.ctx,TaskError('LATER'))
        stderr=saved[0].payload['operations'][-1]['stderr']
        self.assertEqual(stderr['stderr_total_bytes'],8192);self.assertTrue(stderr['stderr_truncated'])
        self.assertEqual(stderr['stderr'],'x'*64)
        self.assertLessEqual(len(json.dumps(saved[0].payload).encode()),65536)


class WechatFinalRetainedTests(WechatActionsFixture,unittest.IsolatedAsyncioTestCase):
    def next_context(self):
        from taskweave.core.ports import Scope
        from taskweave.infrastructure.worker import PluginContext
        from taskweave.infrastructure.storage import uid
        scope=Scope(self.ctx.scope.task_id,self.ctx.scope.run_id,uid(),uid())
        resolver=self.ctx.resolve_secret
        self.ctx=PluginContext(scope,self.results,self.resources,{'wechat_dev_config':self.config},{},self.cancel,lambda *a:None)
        self.ctx.resolve_secret=resolver;self.resources.context=self.ctx
        return self.ctx
    async def test_cached_public_actions_rebind_cleanup_mask_and_prune_last_owner(self):
        await self.action('connect');first=self.ctx.scope.attempt_id
        await self.action('connect',role='peer');peer=self.resources.items[('wechat_dev.simulator','peer')]
        self.next_context();await self.plugin.collect_context('wechat_dev.page',self.ctx,{})
        await self.action('mock_method',method='request',value={})
        session=self.resources.items[('wechat_dev.simulator','default')]
        self.assertEqual(session.attempt,self.ctx.scope.attempt_id);self.assertIs(session.ctx,self.ctx)
        self.assertIs(session.bridge.ctx,self.ctx);self.assertIs(session.bridge.process.ctx._context,self.ctx)
        self.assertIn(first,self.plugin.evidence.entries)
        saved=await self.plugin.failure_results(self.ctx,TaskError('LATER'))
        self.assertTrue(saved[0].payload['operations'][0]['cleanup']['mocks_restored'])
        self.assertEqual(saved[0].payload['operations'][0]['cleanup']['state'],'disconnected')
        self.assertFalse(peer.closed);self.assertIn(first,self.plugin.evidence.entries)
        self.next_context()
        with patch('taskweave_wechat_dev.bridge.SimulatorBridge.start',side_effect=AssertionError('silent revival')):
            with self.assertRaises(TaskError):await self.action('connect')
        await self.registry.providers['wechat_dev.simulator'].close(peer)
        self.assertFalse(self.plugin.evidence.entries);self.assertFalse(self.plugin.evidence.patterns);self.assertFalse(self.plugin.evidence.reserved)
    async def test_cached_read_across_40_contexts_and_changed_policy_rejects_without_dispatch(self):
        self.config['env_secret_refs']={'TOKEN':'logical'};self.ctx.resolve_secret=lambda ref:'initial-private-literal'
        await self.action('connect');session=self.resources.items[('wechat_dev.simulator','default')]
        for _ in range(40):
            self.next_context();await self.action('current_page')
        self.assertLessEqual(len(self.plugin.evidence.entries),1)
        self.next_context();self.ctx.resolve_secret=lambda ref:'new-private-literal'
        with patch.object(session.bridge,'request',side_effect=AssertionError('dispatched changed policy')):
            with self.assertRaises(TaskError):await self.action('tap',selector='#tap')

    async def test_real_two_step_worker_retains_resource_and_masks_current_launch_cleanup(self):
        import os,sys
        from taskweave.application.service import Application
        from taskweave.infrastructure.storage import uid
        secret=self.root.name;cli=self.root/'owned-cli'
        cli.write_text('#!'+sys.executable+'\nimport json\nprint(json.dumps({"command":"agent-start","status":"ok","autoPort":19560,"openedProjectWindow":False}))\n');cli.chmod(0o700)
        self.config.update(mode='launch',cli_path=str(cli),port=19560,env_secret_refs={'TOKEN':'logical'})
        def run():
            with tempfile.TemporaryDirectory() as home,patch.dict(os.environ,{'TW_FINAL_WECHAT_SECRET':secret}),Application(home) as app:
                app.configure_plugin('wechat_dev',True)
                env=app.environments.save('retained two step',{'wechat_dev_config':self.config},{'logical':'env:TW_FINAL_WECHAT_SECRET'})['environment_id']
                task=app.tasks.create('retained resource current failure')['task_id']
                codes=['async def run(ctx, inputs):\n    await ctx.call("wechat_dev.connect", {})\n    await ctx.call("wechat_dev.disconnect", {})\n    return ctx.result(data={"first":True})','async def run(ctx, inputs):\n    await ctx.call("wechat_dev.connect", {})\n    await ctx.call("wechat_dev.mock_method", {"method":"request","value":{}})\n    raise RuntimeError("current failure")']
                for i,code in enumerate(codes):
                    step=app.steps.save(task,{'name':'step'+str(i),'capabilities':['wechat_dev.connect','wechat_dev.disconnect','wechat_dev.mock_method'],'step_content':code});app.confirm_step_manual(step['step_id'],step['content_hash'],environment_id=env)
                run_id=app.runs.create(task,environment_id=env)['run_id'];app.runs.start(run_id,uid());done=app.runs.wait(run_id,timeout=15)
                self.assertEqual(done['status'],'FAILED');self.assertEqual(done['attempts'][0]['status'],'SUCCEEDED')
                row=next(r for r in done['results'] if r['handler_id']=='wechat_dev.operation_failure');data=app.runs.read_result(row['result_id'])['data']
                self.assertNotIn(secret,json.dumps(data));self.assertIn('[REDACTED]',json.dumps(data))
                self.assertEqual(len(data['operations']),2)
                self.assertTrue(all(r['cleanup']['mocks_restored'] and r['cleanup']['state']=='disconnected' for r in data['operations']))
                receipt=os.getenv('TW_FINAL_FIXWAVE_WECHAT_RECEIPT')
                if receipt:
                    Path(receipt).write_text(json.dumps({'scope':'real Application/default discovery/two-step retained worker; owned CLI+SDK protocols, not native GUI','run_status':done['status'],'attempt_statuses':[r['status'] for r in done['attempts']],'known_literal_absent':True,'current_failure_payload':data},indent=2)+'\n');Path(receipt).chmod(0o600)
        await asyncio.to_thread(run)
