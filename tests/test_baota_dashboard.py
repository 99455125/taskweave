"""Transport, fixed 11.7 protocol and action orchestration on temporary HTTP/TLS."""
import asyncio
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import threading
import unittest
from unittest.mock import patch
from taskweave.core.ports import Scope
from taskweave.core.validation import TaskError, validate
from taskweave.infrastructure.storage import Results, uid
from taskweave.infrastructure.worker import PluginContext, Resources
from taskweave.plugins.registry import Registry
from taskweave_baota_dashboard import BaotaDashboardPlugin, PanelClient
from taskweave_baota_dashboard.endpoints import ENDPOINTS
from tests.fixtures.baota_server import BaotaServer

NAMES='check_connection system_status list_software list_php_versions list_sites create_site configure_site set_site_status list_domains add_domain remove_domain get_site_config set_site_config get_rewrite set_rewrite set_php_version check_config reload_service list_databases create_database set_database_credentials set_database_access delete_database get_certificate deploy_certificate request_certificate renew_certificate set_https create_backup list_backups restore_backup task_status read_logs'.split()

class BaotaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().slow_callback_duration=1
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.server=BaotaServer(self.root).start(); self.plugin=BaotaDashboardPlugin(); self.registry=Registry([self.plugin]); self.cancel=threading.Event()
        self.results=Results(self.root/'host',Scope(uid(),uid(),uid(),uid()),self.registry); self.resources=Resources(self.registry)
        self.ctx=PluginContext(self.results.scope,self.results,self.resources,{'baota_url':self.server.url,'baota_api_secret_ref':'api','baota_allow_http':True}, {'api':'env:TW_BAOTA_API','password':'env:TW_BAOTA_PASSWORD','key':'env:TW_BAOTA_KEY'},self.cancel,lambda *a:None)
        self.resources.context=self.ctx
        self.env=patch.dict(os.environ,{'TW_BAOTA_API':self.server.secret,'TW_BAOTA_PASSWORD':'safe123-password'}); self.env.start()
    async def asyncTearDown(self):
        await self.resources.release_all(); await asyncio.to_thread(self.server.close); self.env.stop(); self.temp.cleanup()
    async def action(self,action_name,**inputs):
        action=self.registry.actions['baota_dashboard.'+action_name]; validate(inputs,action.spec.input_schema)
        output=await action.execute(self.ctx,inputs); validate(output,action.spec.output_schema); return output

    async def test_official_file_mtime_string_is_typed_and_preserves_stale_guard(self):
        # Official files.py:2448 emits str(int(stat.st_mtime)), not JSON int.
        try:
            config=await self.action('get_site_config',site_id=1)
            rewrite=await self.action('get_rewrite',site_id=1)
        except TaskError as error: self.fail('genuine official digit-string mtime rejected: '+error.code)
        self.assertEqual(config['mtime'],1); self.assertIs(type(config['mtime']),int)
        self.assertEqual(rewrite['mtime'],1)
        await self.action('set_site_config',site_id=1,content='server { valid; }',expected_mtime=1)
        self.assertEqual(self.server.files['/www/server/panel/vhost/nginx/example.test.conf'],b'server { valid; }')
        before=sum(a=='SaveFileBody' for _,_,a,_ in self.server.requests)
        with self.assertRaises(TaskError) as failure:
            await self.action('set_rewrite',site_id=1,content='changed',expected_mtime=2)
        self.assertEqual(failure.exception.code,'BAOTA_MTIME_CONFLICT')
        self.assertEqual(sum(a=='SaveFileBody' for _,_,a,_ in self.server.requests),before)
        self.assertEqual(self.server.files['/www/server/panel/vhost/rewrite/example.test.conf'],b'')

    async def test_file_mtime_rejects_noncanonical_or_invalid_numeric_values_before_save(self):
        for mtime in ('01','+1','-1','1.0',' 1','1 ','','١','18446744073709551616',-1,2**63,True,1.0,None):
            with self.subTest(mtime=mtime):
                self.server.overrides['GetFileBody']={'status':True,'data':'server {}','st_mtime':mtime}
                with self.assertRaises(TaskError) as failure:
                    await self.action('set_site_config',site_id=1,content='changed',expected_mtime=1)
                self.assertEqual(failure.exception.code,'BAOTA_RESPONSE_INVALID')
        self.assertFalse(any(a=='SaveFileBody' for _,_,a,_ in self.server.requests))
        for mtime in (0,1,'0','1790989923'):
            self.server.overrides['GetFileBody']={'status':True,'data':'server {}','st_mtime':mtime}
            actual=await self.action('get_site_config',site_id=1)
            self.assertEqual(actual['mtime'],int(mtime)); self.assertIs(type(actual['mtime']),int)

    async def test_official_domains_only_add_reply_and_exact_domain_port_postverification(self):
        # Official panelSite.py:1283-1285 /7386-7411 uses per-domain status only.
        try: result=await self.action('add_domain',site_id=1,domain='official.test',port=8080)
        except TaskError as error: self.fail('official domains-only success rejected: '+error.code)
        self.assertEqual(result['completion'],'completed')
        self.assertTrue(any(d['name']=='official.test' and d['port']==8080 for d in result['domains']))
        self.assertNotIn('status',result['response'])
        self.assertEqual(result['response']['domains'],[{'name':'official.test','status':True,'msg':'添加成功'}])
        await self.action('remove_domain',site_id=1,domain='official.test',port=8080)
        self.assertFalse(any(d['name']=='official.test' for d in self.server.domains))

    async def test_add_domain_rejects_vacuous_mixed_wrong_target_or_false_success(self):
        replies=[{}, {'status':True}, {'domains':[]}, {'domains':{}},
                 {'domains':[{'name':'wanted.test','status':'true'}]},
                 {'domains':[{'name':'wrong.test','status':True}]},
                 {'domains':[{'name':'wanted.test','status':False}]},
                 {'domains':[{'name':'wanted.test','status':True},{'name':'wrong.test','status':False}]}]
        for reply in replies:
            with self.subTest(reply=reply):
                self.server.overrides['AddDomain']=reply
                with self.assertRaises(TaskError): await self.action('add_domain',site_id=1,domain='wanted.test')
        self.server.overrides['AddDomain']={'domains':[{'name':'wanted.test','status':True}]}
        with self.assertRaises(TaskError) as failure: await self.action('add_domain',site_id=1,domain='wanted.test')
        self.assertEqual(failure.exception.code,'BAOTA_POSTVERIFY_FAILED')

    async def test_official_pem_strip_and_line_endings_preserve_verified_certificate(self):
        await asyncio.to_thread(self.server.generate_tls); os.environ['TW_BAOTA_KEY']=self.server.key_pem
        supplied=' \n'+self.server.cert_pem.replace('\n','\r\n')+'\t\n'
        try: out=await self.action('deploy_certificate',site_id=1,key_ref='key',certificate=supplied)
        except TaskError as error: self.fail('valid official PEM normalization rejected: '+error.code)
        self.assertTrue(out['deployment_verified']); self.assertNotEqual(self.server.ssl['csr'],supplied)
        self.assertNotIn('PRIVATE KEY',json.dumps(out)); self.assertTrue(out['certificate']['key_present'])

    async def test_certificate_postverify_rejects_different_identity_chain_junk_and_key(self):
        await asyncio.to_thread(self.server.generate_tls); original=self.server.cert_pem; key=self.server.key_pem
        os.environ['TW_BAOTA_KEY']=key
        await asyncio.to_thread(self.server.generate_tls); other=self.server.cert_pem; other_key=self.server.key_pem
        # The received leaf differs, the received chain has an extra cert, and
        # junk may surround a parseable cert. None is legal PEM equivalence.
        for csr,received_key in [(other,key),(original+other,key),('unrelated text\n'+original,key),(original,other_key)]:
            def replace_after(params,csr=csr,received_key=received_key):
                self.server.ssl.update(csr=csr,key=received_key,status=True)
                return {'status':True,'msg':'saved'}
            self.server.overrides['SetSSL']=replace_after
            with self.assertRaises(TaskError) as failure:
                await self.action('deploy_certificate',site_id=1,key_ref='key',certificate=original)
            self.assertEqual(failure.exception.code,'BAOTA_POSTVERIFY_FAILED')
            payload=(await self.plugin.failure_results(self.ctx,failure.exception))[0].payload
            self.assertEqual(payload['requests'][-1]['action_state'],'partial')
        before=sum(a=='SetSSL' for _,_,a,_ in self.server.requests)
        with self.assertRaises(TaskError) as failure:
            await self.action('deploy_certificate',site_id=1,key_ref='key',certificate='unrelated text\n'+original)
        self.assertEqual(failure.exception.code,'BAOTA_CERTIFICATE_INVALID')
        self.assertEqual(sum(a=='SetSSL' for _,_,a,_ in self.server.requests),before)

    async def test_real_worker_domains_partial_failure_keeps_durable_evidence(self):
        from taskweave.application.service import Application
        def partial(params):
            self.server.dispatch('/site','AddDomain',params)
            return {'domains':[{'name':'partial.test','status':True},{'name':'other.test','status':False}]}
        self.server.overrides['AddDomain']=partial
        def run():
            with tempfile.TemporaryDirectory() as home, Application(home) as app:
                app.configure_plugin('baota_dashboard',True)
                env=app.environments.save('official reply fixture',dict(self.ctx.environment),dict(self.ctx.secret_refs))['environment_id']
                task=app.tasks.create('partial official domain')['task_id']
                step=app.steps.save(task,{'name':'partial domain','capabilities':['baota_dashboard.add_domain'],
                    'step_content':'async def run(ctx, inputs):\n    await ctx.call("baota_dashboard.add_domain", {"site_id":1,"domain":"partial.test"})\n    return ctx.result(data={})'})
                app.confirm_step_manual(step['step_id'],step['content_hash'],environment_id=env)
                run_id=app.runs.create(task,environment_id=env)['run_id'];app.runs.start(run_id,uid())
                finished=app.runs.wait(run_id,timeout=8)
                self.assertEqual(finished['status'],'FAILED'); self.assertEqual(finished['attempts'][0]['effect_state'],'UNKNOWN')
                self.assertEqual(len(finished['results']),1)
                stored=app.runs.read_result(finished['results'][0]['result_id'])['data']
                self.assertEqual(stored['requests'][-1]['action_state'],'partial')
                self.assertEqual(stored['requests'][-1]['completion'],'partial')
                self.assertNotIn(self.server.secret,json.dumps(stored))
        await asyncio.to_thread(run)
        self.assertEqual(sum(a=='AddDomain' for _,_,a,_ in self.server.requests),1)
        self.assertTrue(any(d['name']=='partial.test' for d in self.server.domains))

    async def test_create_site_real_directory_ancestry_before_addsite(self):
        for link,path in [('/www/wwwroot','/www/wwwroot/new.test'),('/www/wwwroot/link','/www/wwwroot/link/new.test'),('/www/wwwroot/new.test','/www/wwwroot/new.test')]:
            self.server.links={link:'/outside'}
            before=len(self.server.requests)
            with self.assertRaises(TaskError): await self.action('create_site',domain='new.test',path=path)
            self.assertFalse(any(r[2]=='AddSite' for r in self.server.requests[before:]))
        self.server.links={}; self.server.files['/www/wwwroot/file']=b'not a directory'
        with self.assertRaises(TaskError): await self.action('create_site',domain='new.test',path='/www/wwwroot/file/new.test')
        out=await self.action('create_site',domain='new.test',path='/www/wwwroot/missing/tail/new.test')
        self.assertEqual(out['completion'],'completed')
        checks=[p['filename'] for _,_,a,p in self.server.requests if a=='get_file_attribute']
        self.assertIn('/www/wwwroot',checks)

    async def test_configure_combined_paths_final_root_and_runpath_postverify(self):
        self.server.directories.update({'/www/wwwroot/next','/www/wwwroot/example.test/public'})
        with self.assertRaises(TaskError): await self.action('configure_site',site_id=1,path='/www/wwwroot/next',run_path='/public')
        self.assertFalse(any(r[2]=='SetPath' for r in self.server.requests))
        self.server.directories.remove('/www/wwwroot/example.test/public'); self.server.directories.add('/www/wwwroot/next/public')
        out=await self.action('configure_site',site_id=1,path='/www/wwwroot/next',run_path='/public')
        self.assertEqual(out['completion'],'completed'); self.assertEqual(self.server.run_paths[1],'/public')
        self.server.overrides['GetSiteRunPath']={'runPath':'/','dirs':['/']}
        with self.assertRaises(TaskError) as error: await self.action('configure_site',site_id=1,run_path='/public')
        self.assertEqual(error.exception.code,'BAOTA_POSTVERIFY_FAILED')
        payload=(await self.plugin.failure_results(self.ctx,error.exception))[0].payload
        self.assertTrue(any(r.get('action_state')=='partial' for r in payload['requests']))

    async def test_official_web_service_summary(self):
        out=await self.action('system_status')
        self.assertEqual(out['services']['web'],{'type':'nginx','setup':True,'version':'1.26','status':True})
        self.assertNotIn('never expose',json.dumps(out))

    async def test_attempt_journal_survives_real_worker_later_failures(self):
        from taskweave.application.service import Application
        scripts=[
            ('await ctx.call("baota_dashboard.set_site_status", {"site_id":1,"enabled":False})\n    await ctx.call("baota_dashboard.list_software", {})', ['baota_dashboard.set_site_status','baota_dashboard.list_software'], 'read'),
            ('await ctx.call("baota_dashboard.set_site_status", {"site_id":1,"enabled":False})\n    await ctx.call("baota_dashboard.set_site_status", {"site_id":1,"enabled":True,"role":"second"})\n    raise ValueError("after write")', ['baota_dashboard.set_site_status'], 'script'),
            ('try:\n        await ctx.call("baota_dashboard.create_site", {"domain":"new.test","path":"/www/wwwroot/new.test"})\n    except Exception:\n        pass\n    await ctx.call("baota_dashboard.list_sites", {})\n    raise ValueError("after observation")', ['baota_dashboard.create_site','baota_dashboard.list_sites'], 'caught'),
            ('await ctx.call("baota_dashboard.set_site_status", {"site_id":1,"enabled":False})', ['baota_dashboard.set_site_status'], 'invalid_json_values')]
        def run():
            for body,capabilities,case in scripts:
                self.server.overrides.clear()
                if case=='read': self.server.overrides['GetSoftList']={'status':False,'msg':'read failure'}
                if case=='caught': self.server.overrides['AddSite']={'siteStatus':True,'siteId':2,'databaseStatus':False}
                if case=='invalid_json_values': self.server.overrides['SiteStop']={'status':float('nan'),'siteId':float('inf'),'msg':'invalid '+chr(0xd800)}
                with tempfile.TemporaryDirectory() as home, Application(home) as app:
                    app.configure_plugin('baota_dashboard',True)
                    env=app.repo.save_environment('journal fixture',dict(self.ctx.environment),dict(self.ctx.secret_refs))['environment_id']
                    task=app.repo.create_task('journal failure')['task_id']
                    step=app.repo.save_step(task,{'name':'journal','capabilities':capabilities,'step_content':'async def run(ctx, inputs):\n    '+body+'\n    return ctx.result(data={})'})
                    app.confirm_step_manual(step['step_id'],step['content_hash'],environment_id=env)
                    created=app.create_run(task,environment_id=env); app.coordinator.start(created['run_id'],uid())
                    finished=app.coordinator.wait(created['run_id'],8); self.assertEqual(finished['status'],'FAILED',finished)
                    attempt=finished['attempts'][0]; self.assertEqual(attempt['effect_state'],'UNKNOWN')
                    refs=app.repo.repositories.results.refs_for_attempt(attempt['attempt_id']); self.assertEqual(len(refs),1,case)
                    stored=app.repo.read_result(refs[0]['result_id'],Registry([BaotaDashboardPlugin()]))['data']
                    self.assertEqual(len(stored['requests']),2 if case=='script' else 1); record=stored['requests'][-1]
                    if case=='script': self.assertEqual([r['role'] for r in stored['requests']],['default','second'])
                    self.assertEqual(record['completion'],'partial' if case=='caught' else 'unknown' if case=='invalid_json_values' else 'completed')
                    self.assertEqual(record['role'],'second' if case=='script' else 'default')
                    self.assertIn('action_id',record); self.assertLessEqual(len(json.dumps(stored,ensure_ascii=False).encode()),65536)
                    self.assertNotIn(self.server.secret,json.dumps(stored))
                    with self.assertRaisesRegex(TaskError,'OUTPUT_NOT_AVAILABLE'): app.repo.read_output(created['run_id'],step['step_id'])
        await asyncio.to_thread(run)


    async def test_independent_source_business_fields_and_response_shapes(self):
        from tests.fixtures.baota_server import FIELD_CONTRACTS
        self.server.enforce_fields=True
        self.server.directories.update({'/www/wwwroot/next','/www/wwwroot/next/public'})
        out=await self.action('configure_site',site_id=1,path='/www/wwwroot/next',run_path='/public',default_documents=['index.php','index.html'],remark='source contract')
        self.assertEqual(out['site']['path'],'/www/wwwroot/next')
        software=await self.action('list_software',include_plugins=True,page=2,limit=7)
        self.assertEqual(software['plugins'],[{'name':'plugin','setup':True}])
        versions=await self.action('list_php_versions',include_uninstalled=True)
        self.assertEqual(versions['versions'],[{'version':'00','name':'Static','status':True}])
        await self.action('set_database_access',database_id=1,access=['10.0.0.1'])
        await self.action('create_backup',kind='database',target_id=1)
        backups=await self.action('list_backups',kind='database',target_id=1,page=3,limit=9)
        self.assertEqual(backups['backups'][0]['path'],'/www/backup/database/mysql/example/example.sql.gz')
        restored=await self.action('restore_backup',kind='database',target_id=1,backup_name='example.sql.gz',expected_tables=['example_table'])
        self.assertEqual(restored['verified_tables'],['example_table'])
        tasks=await self.action('task_status',task_id=1,status=1)
        self.assertEqual(tasks['tasks'][0]['id'],1); self.assertFalse(tasks['business_success_verified'])
        issued=await self.action('request_certificate',site_id=1,domains=['example.test'],auth_type='http',ca='zerossl'); self.assertEqual(issued['completion'],'issued')
        renewed=await self.action('renew_certificate',site_id=1); self.assertEqual(renewed['completion'],'issued')
        await asyncio.to_thread(self.server.generate_tls); os.environ['TW_BAOTA_KEY']=self.server.key_pem
        await self.action('deploy_certificate',site_id=1,key_ref='key',certificate=self.server.cert_pem)
        seen={a for _,_,a,_ in self.server.requests}; self.assertTrue(set(FIELD_CONTRACTS)<=seen)
        for _,_,action,params in self.server.requests:
            if action in FIELD_CONTRACTS:
                required,optional=FIELD_CONTRACTS[action]; fields=set(params)-{'action','request_time','request_token'}
                self.assertTrue(required<=fields); self.assertFalse(fields-(required|optional))
        maps={a:p for _,_,a,p in self.server.requests}
        self.assertEqual({k:maps['SetSiteRunPath'][k] for k in ('id','runPath')},{'id':'1','runPath':'/public'})
        self.assertEqual(maps['SetIndex']['Index'],'index.php,index.html')
        self.assertEqual({k:maps['get_soft_list'][k] for k in ('type','p','row')},{'type':'-1','p':'2','row':'7'})
        self.assertTrue(any(a=='GetPHPVersion' and p.get('all')=='1' for _,_,a,p in self.server.requests))
        self.assertEqual(maps['apply_cert_api']['auth_to'],'/www/wwwroot/next/public')
        self.assertEqual(maps['apply_cert_api']['ca'],'zerossl'); self.assertEqual(json.loads(maps['apply_cert_api']['domains']),['example.test'])
        self.assertEqual(maps['renew_cert']['index'],'order1')
        self.assertEqual(maps['SetSSL']['csr'],self.server.cert_pem)
        self.assertEqual(maps['setPs']['table'],'sites'); self.assertEqual(maps['SetDatabaseAccess']['access'],'10.0.0.1')
        self.assertEqual(maps['GetInfo']['db_name'],'example')
        self.assertEqual({k:maps['get_task_lists'][k] for k in ('num','task_id','status')},{'num':'15','task_id':'1','status':'1'})

    async def test_journal_parallel_attempts_isolation_capacity_and_cleanup(self):
        other_results=Results(self.root/'other',Scope(uid(),uid(),uid(),uid()),self.registry)
        other_resources=Resources(self.registry)
        other=PluginContext(other_results.scope,other_results,other_resources,self.ctx.environment,self.ctx.secret_refs,threading.Event(),lambda *a:None)
        other_resources.context=other
        action=self.registry.actions['baota_dashboard.check_config']
        try:
            await asyncio.gather(action.execute(self.ctx,{'service':'nginx'}),action.execute(other,{'service':'nginx','role':'other'}))
            own=(await self.plugin.failure_results(self.ctx,None))[0].payload
            foreign=(await self.plugin.failure_results(other,None))[0].payload
            self.assertEqual([r['role'] for r in own['requests']],['default'])
            self.assertEqual([r['role'] for r in foreign['requests']],['other'])
            await other_resources.release_all()
            self.assertEqual(await self.plugin.failure_results(other,None),[])
            self.assertEqual(len((await self.plugin.failure_results(self.ctx,None))[0].payload['requests']),1)
            self.server.overrides['ServiceAdmin']={'status':True,'msg':'中'*100000}
            count=0
            while count<200:
                before=sum(a=='ServiceAdmin' for _,_,a,_ in self.server.requests)
                try: await self.action('check_config',service='nginx',max_output_bytes=1048576)
                except TaskError as error:
                    self.assertEqual(error.code,'BAOTA_DIAGNOSTIC_CAPACITY')
                    self.assertEqual(sum(a=='ServiceAdmin' for _,_,a,_ in self.server.requests),before)
                    break
                count+=1
            else: self.fail('journal must stop writes before unbounded growth')
            payload=(await self.plugin.failure_results(self.ctx,None))[0].payload
            self.assertEqual(len(payload['requests']),count+1)
            self.assertTrue(all(r['completion']=='completed' for r in payload['requests']))
            self.assertLessEqual(len(json.dumps(payload,ensure_ascii=False).encode()),65536)
            previous=self.ctx.scope.attempt_id; self.ctx.scope=Scope(uid(),uid(),uid(),uid())
            await self.action('check_connection')
            self.assertEqual(await self.plugin.failure_results(self.ctx,None),[])
            self.assertNotIn(previous,self.plugin.evidence.journals)
            await self.resources.release_all()
            self.assertEqual(self.plugin.evidence.journals,{})
            self.assertEqual(self.plugin.evidence.owners,{})
        finally: await other_resources.release_all()

    async def test_before_send_rejection_has_no_write_record(self):
        await self.action('check_connection')
        client=await self.resources.acquire('baota_dashboard.connection','default')
        before=len(self.server.requests)
        with self.assertRaises(TaskError): await client.write(self.ctx,'stop_site',{'bad':'parameter'})
        self.assertEqual(len(self.server.requests),before); self.assertEqual(client.sent_writes,[])
        self.assertEqual(await self.plugin.failure_results(self.ctx,None),[])

    async def test_official_uninstalled_web_version_and_bounded_summary(self):
        self.server.overrides['GetConcifInfo']={'webserver':'','web':{'type':'nginx','version':False,'setup':False,'status':False}}
        out=await self.action('system_status'); self.assertIs(out['services']['web']['version'],False)
        self.server.overrides['GetConcifInfo']['web']['version']='x'*129
        with self.assertRaises(TaskError): await self.action('system_status')


    async def test_source_shaped_endpoint_validation_rejects_malformed_fields(self):
        cases=[('list_software',{'include_plugins':True},'get_soft_list',{'list':[]}),
               ('list_php_versions',{},'GetPHPVersion',[{'version':117}]),
               ('list_backups',{'kind':'database','target_id':1},'GetBackup',{'data':{},'page':''}),
               ('task_status',{},'get_task_lists',[{}])]
        for name,inputs,endpoint,payload in cases:
            self.server.overrides[endpoint]=payload
            with self.assertRaises(TaskError) as error: await self.action(name,**inputs)
            self.assertEqual(error.exception.code,'BAOTA_RESPONSE_INVALID')
            self.server.overrides.clear()
        await self.action('create_backup',kind='database',target_id=1)
        self.server.overrides['GetInfo']={'database':'example','tables':None}
        with self.assertRaises(TaskError) as error: await self.action('restore_backup',kind='database',target_id=1,backup_name='example.sql.gz',expected_tables=['example_table'])
        self.assertEqual(error.exception.code,'BAOTA_RESPONSE_INVALID')
        journal=(await self.plugin.failure_results(self.ctx,error.exception))[0].payload
        self.assertEqual(journal['requests'][-1]['endpoint'],'restore_database')
        self.assertEqual(journal['requests'][-1]['action_state'],'partial')

    async def test_real_worker_schema_failure_stays_not_started(self):
        from taskweave.application.service import Application
        def run():
            with tempfile.TemporaryDirectory() as home, Application(home) as app:
                app.configure_plugin('baota_dashboard',True)
                env=app.repo.save_environment('preflight fixture',dict(self.ctx.environment),dict(self.ctx.secret_refs))['environment_id']
                task=app.repo.create_task('no write')['task_id']
                step=app.repo.save_step(task,{'name':'invalid','capabilities':['baota_dashboard.create_site'],
                    'step_content':'async def run(ctx, inputs):\n    await ctx.call("baota_dashboard.create_site", {"domain":"new.test"})\n    return ctx.result(data={})'})
                app.confirm_step_manual(step['step_id'],step['content_hash'],environment_id=env)
                created=app.create_run(task,environment_id=env); app.coordinator.start(created['run_id'],uid())
                finished=app.coordinator.wait(created['run_id'],8); self.assertEqual(finished['status'],'FAILED')
                attempt=finished['attempts'][0]; self.assertEqual(attempt['effect_state'],'NOT_STARTED')
                self.assertEqual(app.repo.repositories.results.refs_for_attempt(attempt['attempt_id']),[])
        await asyncio.to_thread(run); self.assertEqual(self.server.requests,[])

    async def test_later_invalid_budget_preserves_completed_write_state(self):
        await self.action('check_config',service='nginx')
        client=await self.resources.acquire('baota_dashboard.connection','default')
        client.config['timeout_seconds']='bad configuration'
        with self.assertRaises(TaskError): await self.action('check_connection')
        payload=(await self.plugin.failure_results(self.ctx,None))[0].payload
        self.assertEqual(payload['requests'][0]['completion'],'completed')
        self.assertEqual(payload['requests'][0]['action_state'],'completed')


    async def test_same_attempt_concurrent_role_writes_hold_capacity(self):
        import time
        # Normal official status/msg envelope, UTF-8 worst case within 128 chars.
        body={'status':True,'msg':'😀'*128}; self.server.overrides['ServiceAdmin']=body
        for _ in range(82): await self.action('check_config',service='nginx')
        journal=self.plugin.evidence.journals[self.ctx.scope.attempt_id]
        before=len(journal['requests']); bytes_before=len(json.dumps(journal,ensure_ascii=False).encode())
        self.assertGreater(bytes_before,58000)
        started=threading.Event(); release=threading.Event()
        def delayed(params): started.set(); release.wait(3); return body
        self.server.overrides['ServiceAdmin']=delayed
        pending=asyncio.gather(*(self.action('check_config',service='nginx',role='concurrent'+str(n)) for n in range(16)),return_exceptions=True)
        try:
            self.assertTrue(await asyncio.to_thread(started.wait,3))
            self.assertGreater(len(self.plugin.evidence.reservations),0)
            self.assertLessEqual(self.plugin.evidence.accounted_bytes(self.ctx.scope.attempt_id),65536)
        finally: release.set()
        outputs=await pending
        self.assertLessEqual(len(json.dumps(journal,ensure_ascii=False).encode()),65536)
        completed=[r for r in outputs if isinstance(r,dict)]
        rejected=[r for r in outputs if isinstance(r,Exception)]
        self.assertGreater(len(completed),0); self.assertGreater(len(rejected),0)
        self.assertTrue(all(getattr(r,'code',None)=='BAOTA_DIAGNOSTIC_CAPACITY' for r in rejected))
        self.assertEqual(len(journal['requests']),before+len(completed))
        self.assertEqual(sum(a=='ServiceAdmin' for _,_,a,_ in self.server.requests),before+len(completed))
        self.assertEqual(self.plugin.evidence.reservations,{})
        self.assertTrue(all(r['completion']=='completed' for r in journal['requests']))
        refs=self.results.persist_diagnostics(await self.plugin.failure_results(self.ctx,TaskError('STEP_FAILED')))
        self.assertEqual(len(refs),1)

    async def test_concurrent_write_reservations_release_failure_cancellation(self):
        started=threading.Event(); finish=threading.Event()
        def pending(params):
            started.set(); finish.wait(3)
            return {'status':True,'msg':'done'}
        self.server.overrides['ServiceAdmin']=pending
        cancelled=asyncio.create_task(self.action('check_config',service='nginx',role='cancelled'))
        try:
            self.assertTrue(await asyncio.to_thread(started.wait,3))
            self.assertEqual(len(self.plugin.evidence.reservations),1)
            self.server.overrides['ServiceAdmin']={'status':False,'msg':'business rejection'}
            with self.assertRaises(TaskError) as error: await self.action('check_config',service='httpd',role='failed')
            self.assertEqual(error.exception.code,'BAOTA_BUSINESS_FAILED')
            self.assertEqual(len(self.plugin.evidence.reservations),1)
            cancelled.cancel()
            with self.assertRaises(asyncio.CancelledError): await cancelled
            self.assertEqual(self.plugin.evidence.reservations,{})
            import time
            def timeout(params): time.sleep(1.2); return {'status':True,'msg':'late'}
            self.server.overrides['ServiceAdmin']=timeout
            with self.assertRaises(TaskError) as error: await self.action('check_config',service='nginx',role='timed-out',timeout_seconds=1)
            self.assertEqual(error.exception.code,'BAOTA_TRANSPORT_FAILED'); self.assertEqual(self.plugin.evidence.reservations,{})
            self.server.overrides['ServiceAdmin']={'status':True,'msg':'released'}
            await self.action('check_config',service='nginx',role='after')
            journal=(await self.plugin.failure_results(self.ctx,TaskError('STEP_FAILED')))[0].payload
            self.assertEqual([(r['role'],r['completion']) for r in journal['requests']],[('cancelled','unknown'),('failed','unknown'),('timed-out','unknown'),('after','completed')])
            refs=self.results.persist_diagnostics(await self.plugin.failure_results(self.ctx,TaskError('STEP_FAILED')))
            self.assertEqual(len(refs),1)
            await self.resources.release_all(); self.assertEqual(self.plugin.evidence.reservations,{})
        finally:
            finish.set()
            if not cancelled.done():
                cancelled.cancel(); await asyncio.gather(cancelled,return_exceptions=True)

    async def test_write_reservations_cover_escaped_scalars_and_metadata_growth(self):
        body={'status':True,**{key:chr(0)*128 for key in ('siteStatus','siteId','ftpStatus','databaseStatus','index','msg')}}
        self.server.overrides['ServiceAdmin']=body
        for _ in range(100):
            await self.action('check_config',service='nginx')
            journal=self.plugin.evidence.journals[self.ctx.scope.attempt_id]
            if len(json.dumps(journal,ensure_ascii=False).encode())>52000: break
        else: self.fail('did not approach capacity')
        before=len(journal['requests']); before_sends=sum(a=='ServiceAdmin' for _,_,a,_ in self.server.requests)
        started=threading.Event(); release=threading.Event()
        def delayed(params): started.set(); release.wait(3); return body
        self.server.overrides['ServiceAdmin']=delayed
        pending=asyncio.gather(*(self.action('check_config',service='nginx',role='escape'+str(n)) for n in range(8)),return_exceptions=True)
        try:
            self.assertTrue(await asyncio.to_thread(started.wait,3))
            self.assertLessEqual(self.plugin.evidence.accounted_bytes(self.ctx.scope.attempt_id),65536)
        finally: release.set()
        outputs=await pending
        successes=sum(isinstance(item,dict) for item in outputs)
        self.assertGreater(successes,0); self.assertLess(successes,8)
        self.assertEqual(len(journal['requests']),before+successes)
        self.assertEqual(sum(a=='ServiceAdmin' for _,_,a,_ in self.server.requests),before_sends+successes)
        # Hook error metadata may grow to its full public length after sends.
        payload=(await self.plugin.failure_results(self.ctx,TaskError('X'*128)))[0].payload
        self.assertLessEqual(len(json.dumps(payload,ensure_ascii=False).encode()),65536)
        self.assertEqual(payload['error_code'],'X'*128); self.assertEqual(self.plugin.evidence.reservations,{})
        self.assertEqual(len(self.results.persist_diagnostics(await self.plugin.failure_results(self.ctx,TaskError('X'*128)))),1)

    async def test_real_worker_concurrent_role_journal_durable_after_script_failure(self):
        from taskweave.application.service import Application
        import time
        body={'status':True,'msg':'😀'*128}
        def response(params):
            if sum(a=='ServiceAdmin' for _,_,a,_ in self.server.requests)>82: time.sleep(.3)
            return body
        self.server.overrides['ServiceAdmin']=response
        def run():
            with tempfile.TemporaryDirectory() as home, Application(home,registry_factory='tests.fixtures.baota_server:concurrent_journal_registry') as app:
                env=app.repo.save_environment('concurrent fixture',dict(self.ctx.environment),dict(self.ctx.secret_refs))['environment_id']
                task=app.repo.create_task('concurrent journal failure')['task_id']
                step=app.repo.save_step(task,{'name':'concurrent roles','capabilities':['baota_dashboard.check_config'],
                    'step_content':'async def run(ctx, inputs):\n    await ctx.call("baota_dashboard.check_config", {"service":"nginx"})\n    raise ValueError("after concurrent writes")'})
                app.confirm_step_manual(step['step_id'],step['content_hash'],environment_id=env)
                created=app.create_run(task,environment_id=env); app.coordinator.start(created['run_id'],uid())
                finished=app.coordinator.wait(created['run_id'],12); self.assertEqual(finished['status'],'FAILED',finished)
                attempt=finished['attempts'][0]; self.assertEqual(attempt['effect_state'],'UNKNOWN')
                refs=app.repo.repositories.results.refs_for_attempt(attempt['attempt_id']); self.assertEqual(len(refs),1)
                stored=app.repo.read_result(refs[0]['result_id'],Registry([BaotaDashboardPlugin()]))['data']
                self.assertLessEqual(len(json.dumps(stored,ensure_ascii=False).encode()),65536)
                self.assertGreater(len(stored['requests']),82); self.assertLess(len(stored['requests']),98)
                self.assertTrue(all(r['completion']=='completed' for r in stored['requests']))
                self.assertEqual(len(stored['requests']),sum(a=='ServiceAdmin' for _,_,a,_ in self.server.requests))
                self.assertNotIn(self.server.secret,json.dumps(stored))
                with self.assertRaisesRegex(TaskError,'OUTPUT_NOT_AVAILABLE'): app.repo.read_output(created['run_id'],step['step_id'])
        await asyncio.to_thread(run)

    async def test_33_typed_actions_resource_effect_and_unknown_fields(self):
        self.assertEqual(set(self.registry.actions),{'baota_dashboard.'+n for n in NAMES})
        self.assertEqual(len(NAMES),33)
        for name,action in self.registry.actions.items():
            with self.subTest(name=name):
                self.assertEqual(action.spec.resource_ids,('baota_dashboard.connection',))
                self.assertFalse(action.spec.input_schema.get('additionalProperties',True))
                with self.assertRaises(TaskError): validate({'operation':'arbitrary'},action.spec.input_schema)
        self.assertEqual(self.registry.actions['baota_dashboard.check_config'].spec.effect,'WRITE')
        self.assertFalse(self.registry.actions['baota_dashboard.check_config'].spec.retry_safe)
        self.registry.contributions(list(self.registry.actions))
    async def test_endpoint_transport_smoke_and_business_error(self):
        client=PanelClient({'url':self.server.url,'api_secret_ref':'api','allow_http':True})
        try:
            for name,spec in ENDPOINTS.items():
                with self.subTest(name=name):
                    self.server.overrides[spec.action]=[] if spec.response_kind=='array' else {'status':True,'data':[], 'version':'11.7.0'}
                    await client.request(self.ctx,name,dict(spec.fixed_params),response_kind=spec.response_kind)
                    method,path,action,params=self.server.requests[-1]
                    self.assertEqual((method,path,action),(spec.method,spec.path,spec.action)); self.assertIn('request_token',params)
                    self.server.overrides[spec.action]=[] if name=='certificate' else {'status':False,'msg':'failure '+self.server.secret}
                    with self.assertRaises(TaskError) as failure: await client.request(self.ctx,name,dict(spec.fixed_params),response_kind=spec.response_kind)
                    self.assertNotIn(self.server.secret,str(failure.exception))
                    self.server.overrides.pop(spec.action)
        finally: await client.close()
    async def test_read_groups_and_password_private_key_redaction(self):
        for name,inputs in [('check_connection',{}),('system_status',{}),('list_software',{'include_plugins':True}),('list_php_versions',{}),('list_sites',{}),('list_domains',{'site_id':1}),('list_databases',{}),('get_certificate',{'site_id':1}),('task_status',{'task_id':1}),('read_logs',{'site_id':1})]:
            with self.subTest(name=name):
                out=await self.action(name,**inputs); text=json.dumps(out)
                for secret in ('db-secret','root-secret','secret-path','secret shell','secret other',self.server.secret): self.assertNotIn(secret,text)
        self.server.ssl.update(key='private-key-value',csr='certificate',status=True)
        out=await self.action('get_certificate',site_id=1); self.assertNotIn('private-key-value',json.dumps(out)); self.assertTrue(out['certificate']['key_present'])
    async def test_add_site_reports_partial_failure_without_passwords(self):
        self.server.overrides['AddSite']={'siteStatus':True,'siteId':2,'databaseStatus':False,'ftpStatus':True,'ftpPass':'leaked-ftp','databasePass':'leaked-db'}
        with self.assertRaises(TaskError): await self.action('create_site',domain='new.test',path='/www/wwwroot/new.test',database_name='newdb',database_password_ref='password',database_username='newdb')
        results=await self.plugin.failure_results(self.ctx,TaskError('failure'))
        self.assertEqual(len(results),1); text=json.dumps(results[0].payload)
        self.assertIn('siteStatus',text); self.assertNotIn('leaked',text)
        prepared=self.registry.handlers['baota_dashboard.operation_failure'].prepare(results[0]); self.assertEqual(prepared.kind,'json')
    async def test_existing_create_site_rejected_before_write(self):
        with self.assertRaises(TaskError): await self.action('create_site',domain='example.test',path='/www/wwwroot/example.test')
        self.assertFalse(any(r[2]=='AddSite' for r in self.server.requests))
    async def test_site_mutations_and_exact_domain_and_php_postverification(self):
        await self.action('configure_site',site_id=1,default_documents=['index.html'],remark='fixture')
        await self.action('set_site_status',site_id=1,enabled=False)
        await self.action('add_domain',site_id=1,domain='second.test',port=8080)
        await self.action('remove_domain',site_id=1,domain='second.test',port=8080)
        await self.action('set_php_version',site_id=1,version='00')
        await self.action('check_config',service='nginx'); await self.action('reload_service',service='nginx')
        maps={a:p for _,_,a,p in self.server.requests}
        self.assertEqual(maps['SiteStop']['name'],'example.test'); self.assertEqual(maps['DelDomain']['id'],'1'); self.assertEqual(maps['SetIndex']['Index'],'index.html')
    async def test_config_mtime_invalid_no_reload_and_missing_rewrite_no_create(self):
        await self.action('get_site_config',site_id=1); await self.action('get_rewrite',site_id=1)
        await self.action('set_site_config',site_id=1,content='server { valid; }',expected_mtime=1)
        await self.action('set_rewrite',site_id=1,content='valid',expected_mtime=1)
        with self.assertRaises(TaskError): await self.action('set_site_config',site_id=1,content='invalid',expected_mtime=1)
        self.assertFalse(any(r[2]=='ServiceAdmin' for r in self.server.requests))
        self.server.files.pop('/www/server/panel/vhost/rewrite/example.test.conf')
        before=len(self.server.requests)
        with self.assertRaises(TaskError): await self.action('get_rewrite',site_id=1)
        self.assertFalse(any(r[2]=='GetFileBody' for r in self.server.requests[before:])); self.assertNotIn('/www/server/panel/vhost/rewrite/example.test.conf',self.server.files)
    async def test_database_all_actions_and_swallowed_access_failure(self):
        await self.action('create_database',name='newdb',username='newdb',password_ref='password',access='127.0.0.1')
        await self.action('set_database_credentials',database_id=1,password_ref='password',username='example')
        await self.action('set_database_access',database_id=1,access=['127.0.0.1','10.0.0.1'])
        self.server.overrides['SetDatabaseAccess']={'status':True,'msg':'pretend success'}
        with self.assertRaises(TaskError): await self.action('set_database_access',database_id=1,access=['%'])
        with self.assertRaises(TaskError): await self.action('set_database_credentials',database_id=1,password_ref='password',username='renamed')
        await self.action('delete_database',database_id=2)
        maps={a:p for _,_,a,p in self.server.requests}; self.assertEqual(maps['AddDatabase']['codeing'],'utf8mb4'); self.assertEqual(maps['ResDatabasePassword']['name'],'example')
    async def test_certificate_pending_issued_renew_deploy_and_https(self):
        await asyncio.to_thread(self.server.generate_tls); os.environ['TW_BAOTA_KEY']=self.server.key_pem
        pending=await self.action('request_certificate',site_id=1,domains=['example.test'],auth_type='dns')
        self.assertEqual(pending['completion'],'accepted'); self.assertNotIn('dns-secret',json.dumps(pending))
        issued=await self.action('request_certificate',site_id=1,domains=['example.test'],auth_type='http'); self.assertEqual(issued['completion'],'issued')
        await self.action('deploy_certificate',site_id=1,key_ref='key',certificate=self.server.cert_pem)
        await self.action('set_https',site_id=1,enabled=True,redirect=True)
        renewed=await self.action('renew_certificate',site_id=1); self.assertEqual(renewed['completion'],'issued'); self.assertFalse(renewed['deployment_verified'])
        self.assertNotIn('PRIVATE KEY',json.dumps(renewed))
    async def test_backup_create_list_restore_overlay_and_database_integrity(self):
        for kind in ('site','database'):
            out=await self.action('create_backup',kind=kind,target_id=1); self.assertEqual(out['completion'],'completed')
            out=await self.action('list_backups',kind=kind,target_id=1); self.assertEqual(len(out['backups']),1)
            inputs={'backup_id':1} if kind=='site' else {'backup_name':'example.sql.gz','expected_tables':['example_table']}
            out=await self.action('restore_backup',kind=kind,target_id=1,**inputs); self.assertEqual(out['completion'],'completed')
            if kind=='site': self.assertEqual(out['restore_mode'],'overlay')
    async def test_restore_wrong_owner_and_unsafe_archive_rejected_before_unzip(self):
        await self.action('create_backup',kind='site',target_id=1); self.server.backups[0]['pid']=2
        with self.assertRaises(TaskError): await self.action('restore_backup',kind='site',target_id=1,backup_id=1)
        self.server.backups[0]['pid']=1
        bio=io.BytesIO()
        with tarfile.open(fileobj=bio,mode='w:gz') as t:
            m=tarfile.TarInfo('../escape'); m.size=1; t.addfile(m,io.BytesIO(b'x'))
        file=self.server.backups[0]['filename']; self.server.files[file]=bio.getvalue()
        with self.assertRaises(TaskError): await self.action('restore_backup',kind='site',target_id=1,backup_id=1)
        self.assertFalse(any(r[2]=='UnZip' for r in self.server.requests))
    async def test_transport_limits_malformed_redirect_unsupported_and_no_retries(self):
        for response,code in [(b'<html>login</html>','BAOTA_RESPONSE_INVALID'),(b'x'*2000,'BAOTA_RESPONSE_TOO_LARGE'),((302,b'',{'Location':'http://localhost:1/leak'}),'BAOTA_REDIRECT_REJECTED')]:
            self.server.overrides['GetSystemTotal']=response
            with self.assertRaises(TaskError) as failure: await self.action('check_connection',max_response_bytes=1024)
            self.assertEqual(failure.exception.code,code)
        self.server.overrides.clear(); self.server.version='13.0.0'
        with self.assertRaises(TaskError) as failure: await self.action('set_site_status',site_id=1,enabled=False)
        self.assertEqual(failure.exception.code,'BAOTA_DASHBOARD_CAPABILITY_UNSUPPORTED'); self.assertFalse(any(r[2]=='SiteStop' for r in self.server.requests))
    async def test_tls_default_rejects_fixture_and_explicit_ca_succeeds(self):
        tls=await asyncio.to_thread(BaotaServer(self.root,tls=True).start)
        try:
            client=PanelClient({'url':tls.url,'api_secret_ref':'api'})
            with self.assertRaises(TaskError): await client.request(self.ctx,'system',{},response_kind='object')
            await client.close(); client=PanelClient({'url':tls.url,'api_secret_ref':'api','ca_file':str(tls.cert_path)})
            self.assertEqual((await client.request(self.ctx,'system',{},response_kind='object'))['version'],'11.7.0'); await client.close()
        finally: await asyncio.to_thread(tls.close)
    async def test_context_passive_bounded_and_pre_cancel(self):
        collection=await self.plugin.collect_context('baota_dashboard.site',self.ctx,{'site_id':1,'max_output_bytes':1024})
        self.assertLessEqual(len(collection.items[0].content.encode()),1024)
        self.assertFalse(any(r[2] in ('GetFileBody','ServiceAdmin') for r in self.server.requests))
        before=len(self.server.requests); self.cancel.set()
        with self.assertRaises(TaskError): await self.action('set_site_status',site_id=1,enabled=False)
        self.assertEqual(len(self.server.requests),before)

    async def test_real_host_failure_diagnostic_persisted_and_unknown_timeout_once(self):
        from taskweave.application.service import Application
        import time
        def slow(params):
            time.sleep(2)
            return {'siteStatus':True,'siteId':2,'databaseStatus':False,'databasePass':'must-not-save'}
        self.server.overrides['AddSite']=slow
        def run():
            with tempfile.TemporaryDirectory() as home, Application(home) as app:
                app.configure_plugin('baota_dashboard',True)
                env=app.repo.save_environment('BaoTa isolated protocol',dict(self.ctx.environment),dict(self.ctx.secret_refs))['environment_id']
                task=app.repo.create_task('BaoTa unknown request')['task_id']
                inputs={'domain':'new.test','path':'/www/wwwroot/new.test','timeout_seconds':1}
                step=app.repo.save_step(task,{'name':'single request','capabilities':['baota_dashboard.create_site'],
                    'step_content':'async def run(ctx, inputs):\n'+f'    result = await ctx.call("baota_dashboard.create_site", {inputs!r})\n'+'    return ctx.result(data=result)'})
                app.confirm_step_manual(step['step_id'],step['content_hash'],environment_id=env)
                created=app.create_run(task,environment_id=env); app.coordinator.start(created['run_id'],uid())
                finished=app.coordinator.wait(created['run_id'],8)
                self.assertEqual(finished['status'],'FAILED',finished)
                attempt=finished['attempts'][0]; self.assertEqual(attempt['effect_state'],'UNKNOWN')
                refs=app.repo.repositories.results.refs_for_attempt(attempt['attempt_id'])
                self.assertEqual(len(refs),1,'own diagnostic must survive host failure')
                self.assertEqual(refs[0]['handler_id'],'baota_dashboard.operation_failure')
                stored=app.repo.read_result(refs[0]['result_id'],Registry([BaotaDashboardPlugin()]))['data']
                self.assertEqual([(r['endpoint'],r['completion']) for r in stored['requests']],[('create_site','unknown')])
                self.assertNotIn(self.server.secret,json.dumps(stored))
                with self.assertRaisesRegex(TaskError,'OUTPUT_NOT_AVAILABLE'): app.repo.read_output(created['run_id'],step['step_id'])
        await asyncio.to_thread(run)
        self.assertEqual(sum(r[2]=='AddSite' for r in self.server.requests),1)

    async def test_fixed_parameters_cannot_be_overridden(self):
        client=PanelClient({'url':self.server.url,'api_secret_ref':'api','allow_http':True})
        try:
            with self.assertRaises(TaskError): await client.request(self.ctx,'sites',{'table':'users'},response_kind='object')
            self.assertFalse(self.server.requests)
        finally: await client.close()

    async def test_create_site_success_and_configuration_partial_durable(self):
        out=await self.action('create_site',domain='new.test',path='/www/wwwroot/new.test')
        self.assertEqual(out['site_id'],2)
        creation=next(r[3] for r in self.server.requests if r[2]=='AddSite')
        self.assertEqual(json.loads(creation['webname']),{'domain':'new.test','domainlist':[],'count':0})
        self.assertEqual((creation['ftp'],creation['sql'],creation['version']),('false','false','00'))
        self.server.overrides['setPs']={'status':False,'msg':'rejected '+self.server.secret}
        with self.assertRaises(TaskError): await self.action('configure_site',site_id=1,default_documents=['index.html'],remark='partial')
        evidence=(await self.plugin.failure_results(self.ctx,None))[0].payload
        self.assertEqual([(r['endpoint'],r['completion']) for r in evidence['requests']],[('create_site','completed'),('index','completed'),('remark','unknown')])
        refs=self.results.persist_diagnostics(await self.plugin.failure_results(self.ctx,None)); self.assertEqual(len(refs),1)
        self.ctx.scope=Scope(uid(),uid(),uid(),uid()); self.assertEqual(await self.plugin.failure_results(self.ctx,None),[])

    async def test_archive_links_bomb_symlink_and_size_guards(self):
        await self.action('create_backup',kind='site',target_id=1)
        archive_path=self.server.backups[0]['filename']
        for link in (True,False):
            bio=io.BytesIO()
            with tarfile.open(fileobj=bio,mode='w:gz') as archive:
                member=tarfile.TarInfo('./evil')
                if link: member.type=tarfile.SYMTYPE; member.linkname='/outside'
                else: member.size=2048
                archive.addfile(member,None if link else io.BytesIO(b'x'*2048))
            self.server.files[archive_path]=bio.getvalue()
            with self.assertRaises(TaskError): await self.action('restore_backup',kind='site',target_id=1,backup_id=1,max_unpacked_bytes=1024)
        self.server.files[archive_path]=self.server.archive
        self.server.overrides['GetDirNew']=lambda p:{'path':p['path'],'dir':[{'nm':p.get('search',''),'lnk':'->/outside'}],'files':[]}
        with self.assertRaises(TaskError): await self.action('restore_backup',kind='site',target_id=1,backup_id=1)
        self.assertFalse(any(r[2]=='UnZip' for r in self.server.requests))

    async def test_pagination_aggregate_budget_and_mtime_conflict(self):
        self.server.overrides['getData']=lambda p:{'data':[dict(id=1,name='example.test',path='/www/wwwroot/example.test',status='1',project_type='PHP')]*100,'page':'next'}
        with self.assertRaises(TaskError) as failure: await self.action('create_site',domain='absent.test',path='/www/wwwroot/absent.test',max_response_bytes=20000)
        self.assertEqual(failure.exception.code,'BAOTA_RESPONSE_TOO_LARGE')
        self.assertFalse(any(r[2]=='AddSite' for r in self.server.requests))
        self.server.overrides.clear()
        with self.assertRaises(TaskError) as failure: await self.action('set_site_config',site_id=1,content='valid',expected_mtime=2)
        self.assertEqual(failure.exception.code,'BAOTA_MTIME_CONFLICT'); self.assertFalse(any(r[2]=='SaveFileBody' for r in self.server.requests))

    async def test_malformed_success_deferred_certificate_and_access_postverify(self):
        self.server.overrides['SiteStop']={'status':True,'msg':'claimed'}
        with self.assertRaises(TaskError) as failure: await self.action('set_site_status',site_id=1,enabled=False)
        self.assertEqual(failure.exception.code,'BAOTA_POSTVERIFY_FAILED')
        self.server.overrides['renew_cert']={'status':True,'msg':'nothing renewed'}
        with self.assertRaises(TaskError): await self.action('renew_certificate',site_id=1)
        self.server.overrides['GetSSL']={'status':False,'msg':'permission denied'}
        with self.assertRaises(TaskError): await self.action('get_certificate',site_id=1)

    async def test_logs_distinguish_missing_empty_unavailable_and_business_error(self):
        for body,state in [({'status':False,'msg':'日志为空'},'missing'),({'status':True,'msg':''},'empty'),((200,b'null',{}),'unavailable')]:
            self.server.overrides['GetSiteLogs']=body
            out=await self.action('read_logs',site_id=1)
            self.assertEqual(out['availability'],state); self.assertEqual(out['text'],'')
        self.server.overrides['GetSiteLogs']={'status':False,'msg':'permission denied'}
        with self.assertRaises(TaskError) as failure: await self.action('read_logs',site_id=1)
        self.assertEqual(failure.exception.code,'BAOTA_BUSINESS_FAILED')

    async def test_all_33_actions_have_business_or_shape_error_contracts(self):
        await asyncio.to_thread(self.server.generate_tls); os.environ['TW_BAOTA_KEY']=self.server.key_pem
        await self.action('create_backup',kind='site',target_id=1)
        self.server.domains.append(dict(id=2,pid=1,name='second.test',port=80))
        cases={
            'check_connection':('GetSystemTotal',{}), 'system_status':('GetConcifInfo',{}),
            'list_software':('GetSoftList',{}), 'list_php_versions':('GetPHPVersion',{}),
            'list_sites':('getData',{}), 'create_site':('AddSite',dict(domain='new.test',path='/www/wwwroot/new.test')),
            'configure_site':('SetIndex',dict(site_id=1,default_documents=['index.html'])),
            'set_site_status':('SiteStop',dict(site_id=1,enabled=False)), 'list_domains':('getData',dict(site_id=1)),
            'add_domain':('AddDomain',dict(site_id=1,domain='new-domain.test')),
            'remove_domain':('DelDomain',dict(site_id=1,domain='second.test')),
            'get_site_config':('GetFileBody',dict(site_id=1)), 'set_site_config':('SaveFileBody',dict(site_id=1,content='valid',expected_mtime=1)),
            'get_rewrite':('GetFileBody',dict(site_id=1)), 'set_rewrite':('SaveFileBody',dict(site_id=1,content='valid',expected_mtime=1)),
            'set_php_version':('SetPHPVersion',dict(site_id=1,version='00')),
            'check_config':('ServiceAdmin',dict(service='nginx')), 'reload_service':('ServiceAdmin',dict(service='nginx')),
            'list_databases':('getData',{}), 'create_database':('AddDatabase',dict(name='newdb',username='newdb',password_ref='password',access='127.0.0.1')),
            'set_database_credentials':('ResDatabasePassword',dict(database_id=1,password_ref='password')),
            'set_database_access':('SetDatabaseAccess',dict(database_id=1,access=['%'])), 'delete_database':('DeleteDatabase',dict(database_id=1)),
            'get_certificate':('GetSSL',dict(site_id=1)), 'deploy_certificate':('SetSSL',dict(site_id=1,key_ref='key',certificate=self.server.cert_pem)),
            'request_certificate':('apply_cert_api',dict(site_id=1,domains=['example.test'],auth_type='http')),
            'renew_certificate':('renew_cert',dict(site_id=1)), 'set_https':('CloseSSLConf',dict(site_id=1,enabled=False)),
            'create_backup':('ToBackup',dict(kind='site',target_id=1)), 'list_backups':('getData',dict(kind='site',target_id=1)),
            'restore_backup':('UnZip',dict(kind='site',target_id=1,backup_id=1)), 'task_status':('get_task_lists',dict(task_id=1)),
            'read_logs':('GetSiteLogs',dict(site_id=1))}
        self.assertEqual(set(cases),set(NAMES))
        for name,(endpoint,inputs) in cases.items():
            with self.subTest(action=name):
                self.server.overrides[endpoint]={'status':False,'msg':'rejected fixture-only-api-secret'}
                with self.assertRaises(TaskError) as failure: await self.action(name,**inputs)
                self.assertIn(failure.exception.code,('BAOTA_BUSINESS_FAILED','BAOTA_PARTIAL_FAILURE','BAOTA_RESPONSE_INVALID'))
                self.assertNotIn(self.server.secret,str(failure.exception)); self.server.overrides.clear()

    async def test_cancellation_after_write_durable_unknown_and_no_followup(self):
        import time
        started=threading.Event()
        def delayed(params): started.set(); time.sleep(2); return {'status':True,'msg':'late'}
        self.server.overrides['SiteStop']=delayed
        task=asyncio.create_task(self.action('set_site_status',site_id=1,enabled=False))
        for _ in range(100):
            if started.is_set(): break
            await asyncio.sleep(.01)
        self.assertTrue(started.is_set()); task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        requests=await self.plugin.failure_results(self.ctx,None); self.assertEqual(len(requests),1)
        self.assertEqual([(r['endpoint'],r['completion']) for r in requests[0].payload['requests']],[('stop_site','unknown')])
        self.assertEqual(requests[0].payload['error_code'],'CANCELLED')
        self.assertEqual(sum(r[2]=='SiteStop' for r in self.server.requests),1)

    async def test_concurrent_same_resource_is_rejected_without_changing_first_budget(self):
        import time
        started=threading.Event()
        def delayed(params): started.set(); time.sleep(.2); return {'status':True,'msg':'ok'}
        self.server.overrides['ServiceAdmin']=delayed
        first=asyncio.create_task(self.action('check_config',service='nginx'))
        for _ in range(100):
            if started.is_set(): break
            await asyncio.sleep(.01)
        self.assertTrue(started.is_set())
        with self.assertRaises(TaskError) as failure: await self.action('system_status',max_response_bytes=1024)
        self.assertEqual(failure.exception.code,'BAOTA_CONNECTION_BUSY')
        await first

    async def test_log_json_escaping_and_unicode_cursor_stay_within_output_budget(self):
        self.server.overrides['GetSiteLogs']={'status':True,'msg':'\"\n'*2000+'中文'*1000}
        out=await self.action('read_logs',site_id=1,max_output_bytes=1024)
        self.assertTrue(out['truncated']); self.assertLessEqual(len(json.dumps(out,ensure_ascii=False).encode()),1024)
        self.assertEqual(out['cursor'],len(out['text'].encode()))
