"""Explicit private compiled fixture acceptance; never opens caller/user roots implicitly.

Set TW_WECHAT_REAL_CONFIG to a 0600 explicitly prepared own config and
TW_WECHAT_REAL_RECEIPT to a new private receipt pathname. Default discovery
never executes this target. This is genuine DevTools testing, not a SDK double.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
import uuid
from taskweave.core.ports import Scope
from taskweave.core.validation import TaskError,validate
from taskweave.infrastructure.storage import Results,uid
from taskweave.infrastructure.worker import PluginContext,Resources
from taskweave.plugins.registry import Registry
from taskweave_wechat_dev import WechatDevPlugin

class WechatRealToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        reference=os.environ.get('TW_WECHAT_REAL_CONFIG')
        if not reference:self.skipTest('Explicit prepared owned fixture config required')
        source=Path(reference);self.assertEqual(source.stat().st_mode&0o077,0)
        self.config=json.loads(source.read_text());self.root=Path(self.config['project_root'])
        self.assertTrue(self.root.name.startswith('tw-wechat-'))
        self.receipt=Path(os.environ['TW_WECHAT_REAL_RECEIPT']);self.assertFalse(os.path.lexists(self.receipt))
        self.home=self.receipt.parent/('tw-wechat-test-home-'+uuid.uuid4().hex);self.home.mkdir(mode=0o700)
        self.plugin=WechatDevPlugin();self.registry=Registry([self.plugin]);self.resources=Resources(self.registry)
        self.results=Results(self.home,Scope(uid(),uid(),uid(),uid()),self.registry)
        self.ctx=PluginContext(self.results.scope,self.results,self.resources,{'wechat_dev_config':self.config},{},threading.Event(),lambda *a:None)
        self.resources.context=self.ctx;self.records=[];self.started=time.time();self.addAsyncCleanup(self.finalize)
    async def finalize(self):
        sessions=list(self.plugin.evidence.sessions.values())
        await self.resources.release_all()
        result={'started_at':self.started,'finished_at':time.time(),'owned_results_home':str(self.home),'configured_root':str(self.root),'config_sha256':hashlib.sha256(json.dumps(self.config,sort_keys=True).encode()).hexdigest(),'identity_level':'appid_and_page','root_verified':False,'observations':self.records,'operations':self.plugin.evidence.entries.get(self.ctx.scope.attempt_id,[]),'processes':[{'pid':session.bridge.process.process.pid,'returncode':session.bridge.process.process.returncode} for session in sessions],'all_bridge_processes_terminal':all(session.bridge.process.process.returncode is not None for session in sessions)}
        fd=os.open(self.receipt,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f:json.dump(result,f,indent=2,ensure_ascii=False)
    async def action(self,name,**inputs):
        started=time.monotonic();record={'action':name,'inputs':inputs};self.records.append(record)
        try:
            action=self.registry.actions['wechat_dev.'+name];validate(inputs,action.spec.input_schema)
            out=await action.execute(self.ctx,{'timeout_seconds':30,**inputs});validate(out,action.spec.output_schema)
            record.update(result=out,state='completed');return out['result']
        except BaseException as error:record.update(state='failed',error_code=getattr(error,'code',type(error).__name__),error_detail=str(error)[:1024]);raise
        finally:record['duration_ms']=round((time.monotonic()-started)*1000)
    async def test_native_or_compiled_uniapp_actual_actions(self):
        async with asyncio.timeout(180):
            if os.environ.get('TW_WECHAT_REAL_SCENARIO')=='mock_callbacks':await self.mock_callbacks()
            else:await self.actual_actions()
    async def mock_callbacks(self):
        await self.action('connect')
        for method,selector,state in [('request','#mockrequest','request'),('login','#mocklogin','login')]:
            for outcome in ('ok','fail'):
                value={'errMsg':method+':'+outcome,'marker':'taskweave-owned-mock','data':{'owned':True},'code':'owned-static-code'}
                await self.action('mock_method',method=method,value=value)
                await self.action('tap',selector=selector)
                expected='success' if outcome=='ok' else 'fail'
                await self.action('wait_for',kind='data',path=state+'State',value=expected,timeout_ms=2000)
                await self.action('assert_page_data',path=state+'Result.marker',value='taskweave-owned-mock')
                await self.action('restore_mock',method=method)
        await self.action('mock_method',method='getSystemInfoSync',value={'marker':'taskweave-owned-sync'})
        await self.action('tap',selector='#mocksync')
        await self.action('assert_page_data',path='syncResult.marker',value='taskweave-owned-sync')
        await self.action('restore_mock',method='getSystemInfoSync')
        await self.action('disconnect')
    async def actual_actions(self):
        await self.action('check_environment');connected=await self.action('connect')
        self.assertEqual(connected['runtime_appid'],'touristappid');self.assertIs(connected['root_verified'],False)
        await self.action('current_page');await self.action('page_stack')
        await self.action('observe',selectors=['#marker','#tap'],paths=['marker','count'])
        element=await self.action('get_element',selector='#tap');await self.action('tap',element_id=element['element_id'])
        await self.action('wait_for',kind='data',path='count',value=1,timeout_ms=2000)
        await self.action('assert_page_data',path='count',value=1)
        await self.action('input',selector='#input',value='owned-input');await self.action('wait_for',kind='data',path='input',value='owned-input',timeout_ms=2000);await self.action('assert_element',selector='#input',value='owned-input')
        await self.action('scroll',selector='#scroll',x=0,y=20)
        for phase in ('start','move','end'):await self.action('touch',selector='#touch',phase=phase,touches=[{'identifier':1,'pageX':1,'pageY':1}],changeTouches=[{'identifier':1,'pageX':1,'pageY':1}])
        await self.action('call_component_method',selector='#component',method='increment',args=[2])
        await self.action('assert_page',path='pages/main/main');await self.action('get_page_data',paths=['marker','count'])
        for kind,params in [('page',{'path':'pages/main/main'}),('element',{'selector':'#marker'}),('data',{'path':'count','value':1})]:await self.action('wait_for',kind=kind,timeout_ms=1000,**params)
        await self.action('set_storage',key='acceptance',value={'owned':True});self.assertTrue((await self.action('get_storage',key='acceptance'))['exists'])
        await self.action('remove_storage',key='acceptance');await self.action('clear_storage',scope='namespace')
        await self.action('mock_method',method='request',value={'statusCode':200,'data':{'owned':True}});await self.action('restore_mock',method='request')
        await self.action('read_logs',limit=20)
        image=await self.action('screenshot');self.assertGreater(image['artifact']['size_bytes'],48)
        from taskweave.plugins.sdk import StepResult,ResultRequest
        refs=self.results.persist(StepResult(outputs=[ResultRequest('wechat_dev.image','simulator',image['artifact'])]))
        self.records.append({'action':'persist_image','state':'completed','refs':refs})
        for name,inputs in [('assert_page',{'path':'pages/nonexistent/nonexistent'}),('get_element',{'selector':'#missing-owned-marker'}),('wait_for',{'kind':'element','selector':'#missing-owned-marker','timeout_ms':100})]:
            with self.assertRaises(TaskError):await self.action(name,**inputs)
        await self.action('navigate',mode='navigateTo',url='/pages/second/second')
        with self.assertRaises(TaskError):await self.action('tap',element_id=element['element_id'])
        await self.action('navigate',mode='navigateBack');await self.action('navigate',mode='redirectTo',url='/pages/second/second')
        await self.action('navigate',mode='switchTab',url='/pages/tabone/tabone');await self.action('navigate',mode='reLaunch',url='/pages/main/main')
        disconnected=await self.action('disconnect');self.assertTrue(disconnected['mocks_restored'])
        self.assertEqual(disconnected['window_closed'],True if connected['ownership']=='owned' else 'not_owned')
