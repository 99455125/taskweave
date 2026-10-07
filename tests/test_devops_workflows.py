"""Scoped real host workflows; controlled protocols are not external acceptance."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from taskweave.application.service import Application
from taskweave.core.validation import content_tree,TaskError
from taskweave.infrastructure.storage import uid
from tests.fixtures.baota_server import BaotaServer

ROOT=Path(__file__).resolve().parents[1]
WP_CAPS=['baota_dashboard.create_site','baota_dashboard.create_database','ssh.upload','wordpress.core_download','wordpress.config_create','wordpress.core_install','wordpress.create_post','playwright.page_open','playwright.page_assert_text','playwright.page_screenshot','wordpress.backup','baota_dashboard.create_backup','wordpress.file','wordpress.json','playwright.image']
MINI_CAPS=['uniapp.inspect','uniapp.build','uniapp.check_artifact','uniapp.run_tests','uniapp.collect_report','wechat_dev.connect','wechat_dev.navigate','wechat_dev.tap','wechat_dev.assert_page','wechat_dev.assert_element','wechat_dev.screenshot','wechat_dev.read_logs','wechat_dev.disconnect','tidb.query','uniapp.file','uniapp.json','wechat_dev.image','wechat_dev.json']

def example(name):return (ROOT/'examples/devops'/name).read_text()

def save_confirm(app,task,source,capabilities,env):
    step=app.steps.save(task,{'name':'controlled workflow','capabilities':capabilities,'step_content':source})
    app.confirm_step_manual(step['step_id'],step['content_hash'],environment_id=env)
    return step

def execute(app,task,env,inputs=None):
    run=app.runs.create(task,environment_id=env,inputs=inputs or {})['run_id'];app.runs.start(run,uid());return run,app.runs.wait(run,timeout=25)

class DevopsWorkflowTests(unittest.TestCase):
    def test_both_examples_are_import_free_registered_step_functions(self):
        for name,caps in [('wordpress_site.py',WP_CAPS),('miniprogram_selftest.py',MINI_CAPS),('miniprogram_preview.py',MINI_CAPS+['wechat_dev.check_environment','wechat_dev.preview','wechat_dev.upload'])]:
            tree=content_tree(example(name),caps);self.assertTrue(tree)

    def test_workflow_persists_real_command_artifact(self):
        with tempfile.TemporaryDirectory() as home,tempfile.TemporaryDirectory() as root,Application(home) as app:
            app.configure_plugin('process',True);env=app.environments.save('owned process',{'process_root':root},{})['environment_id'];task=app.tasks.create('finite real process')['task_id']
            source='async def run(ctx, inputs):\n    command = await ctx.call("process.run", '+repr({'executable':sys.executable,'args':['-c','from pathlib import Path;Path("report.txt").write_text("real worker report");print("completed")']})+')\n    files = await ctx.call("process.collect_artifacts", {"paths":["report.txt"]})\n    return ctx.result(data=command, outputs=[ctx.output("process.file","report",files["artifacts"][0])])'
            step=save_confirm(app,task,source,['process.run','process.collect_artifacts','process.file'],env);run,done=execute(app,task,env)
            self.assertEqual(done['status'],'SUCCEEDED');self.assertEqual(app.repo.read_output(run,step['step_id'])['stdout'],'completed\n');self.assertEqual(len([r for r in done['results'] if r['handler_id']=='process.file']),1)
            result=app.runs.read_result(next(r['result_id'] for r in done['results'] if r['handler_id']=='process.file'));self.assertIn('data',result);self.assertEqual(next((Path(home)/'tasks'/task/'artifacts').rglob('report')).read_text(),'real worker report')

    def test_failed_business_action_does_not_produce_success_report(self):
        source=example('wordpress_site.py')
        with tempfile.TemporaryDirectory() as home,tempfile.TemporaryDirectory() as root:
            server=BaotaServer(root).start();self.addCleanup(server.close);server.overrides['AddDatabase']={'status':False,'msg':'owned controlled database rejection'}
            with patch.dict(os.environ,{'TW_WORKFLOW_PANEL':server.secret,'TW_WORKFLOW_DB':'owned-database-secret'}),Application(home) as app:
                for plugin in ('process','baota_dashboard','ssh','wordpress','playwright'):app.configure_plugin(plugin,True)
                env=app.environments.save('owned protocol',{'process_root':root,'baota_url':server.url,'baota_allow_http':True,'baota_api_secret_ref':'panel'},{'panel':'env:TW_WORKFLOW_PANEL','db':'env:TW_WORKFLOW_DB'})['environment_id'];task=app.tasks.create('earlier committed artifact then real business rejection')['task_id']
                inputs={'site':{'domain':'workflow.test','path':'/www/wwwroot/workflow.test'},'database':{'name':'wf_db','username':'wf_user','password_ref':'db','access':'127.0.0.1'},'page_assertion':{'selector':'#owned','text':'Owned'}}
                app.tasks.update(task,name='controlled workflow',input_schema={'type':'object','properties':{k:{'type':'object','default':v} for k,v in inputs.items()}})
                first='async def run(ctx, inputs):\n    await ctx.call("process.run", '+repr({'executable':sys.executable,'args':['-c','from pathlib import Path;Path("report.txt").write_text("earlier evidence")']})+')\n    files=await ctx.call("process.collect_artifacts", {"paths":["report.txt"]})\n    return ctx.result(data={"stage":"prepared"},outputs=[ctx.output("process.file","prior",files["artifacts"][0])])'
                prior=save_confirm(app,task,first,['process.run','process.collect_artifacts','process.file'],env)
                second=save_confirm(app,task,source,WP_CAPS,env)
                run,done=execute(app,task,env);self.assertEqual(done['status'],'FAILED');self.assertEqual(done['attempts'][-1]['error_code'],'BAOTA_BUSINESS_FAILED')
                self.assertEqual(app.repo.read_output(run,prior['step_id']),{'stage':'prepared'})
                with self.assertRaises(TaskError):app.repo.read_output(run,second['step_id'])
                self.assertTrue(any(row['handler_id']=='baota_dashboard.operation_failure' for row in done['results']));self.assertFalse(any(row['handler_id']=='wordpress.json' for row in done['results']))
                failure=app.runs.read_result(next(row['result_id'] for row in done['results'] if row['handler_id']=='baota_dashboard.operation_failure'))['data'];self.assertEqual(failure['action_id'],'baota_dashboard.create_database');self.assertEqual(failure['error_code'],'BAOTA_BUSINESS_FAILED')
                decoded=[app.runs.read_result(row['result_id']) for row in done['results']];self.assertEqual(next((Path(home)/'tasks'/task/'artifacts').rglob('prior')).read_text(),'earlier evidence');self.assertNotIn(server.secret,json.dumps(decoded));self.assertNotIn('owned-database-secret',json.dumps(decoded));self.assertTrue(any(action=='AddDatabase' for _,_,action,_ in server.requests))

    def test_miniprogram_example_real_worker_protocol_outputs_and_existing_suite(self):
        import shutil
        from tests.fixtures.uniapp_project import project,compatible_test_node,install_jest_report_protocol
        with tempfile.TemporaryDirectory() as home,tempfile.TemporaryDirectory() as directory,Application(home) as app:
            root=Path(directory);project(root);install_jest_report_protocol(root)
            sdk=root/'deps/node_modules/miniprogram-automator';sdk.mkdir(parents=True);(sdk/'package.json').write_text('{"name":"miniprogram-automator","version":"0.12.1","main":"index.cjs"}');(sdk/'index.cjs').write_bytes((ROOT/'tests/fixtures/wechat_sdk.cjs').read_bytes().replace(b'pages/main/main',b'pages/index/index'))
            node=compatible_test_node();output=root/'dist/build/mp-weixin'
            config={'project_root':str(root),'kind':'cli','node_path':node,'node_major':22,'package_manager':shutil.which('npm'),'build_scripts':{'production:mp-weixin':{'script':'build:mp-weixin','completion':'BUILD_COMPLETE'}},'outputs':{'production:mp-weixin':'dist/build/mp-weixin'},'test_scripts':{'mp-weixin':{'script':'test:mp-weixin','forwards_jest_args':True}},'report_root':'.reports'}
            wechat={'project_root':str(output),'node_path':node,'module_root':str(root/'deps'),'mode':'attach','endpoint':'ws://127.0.0.1:19560','storage_namespace':'tw-workflow:'}
            for plugin in ('uniapp','wechat_dev','tidb'):app.configure_plugin(plugin,True)
            env=app.environments.save('owned compiler/SDK protocols',{'uniapp_config':config,'wechat_dev_config':wechat},{})['environment_id']
            inputs={'environment':'production','expected_page':'pages/index/index','element_assertion':{'selector':'#marker','text':'owned-fixture'},'test_suite':{'platform':'mp-weixin','file':'a.test.js','case':'selected case'}}
            task=app.tasks.create('whole mini example controlled boundary',input_schema={'type':'object','properties':{k:{'default':v} for k,v in inputs.items()}})['task_id']
            step=save_confirm(app,task,example('miniprogram_selftest.py'),MINI_CAPS,env);run,done=execute(app,task,env)
            self.assertEqual(done['status'],'SUCCEEDED',done['attempts']);report=app.repo.read_output(run,step['step_id']);self.assertTrue(report['passed']);self.assertTrue(report['suite']['passed']);self.assertEqual(report['connection']['result']['identity_level'],'appid_and_page');self.assertFalse(report['connection']['result']['root_verified'])
            handlers={r['handler_id'] for r in done['results']};self.assertTrue({'uniapp.file','uniapp.json','wechat_dev.image','wechat_dev.json'}<=handlers)
            for reference in done['results']:self.assertIsNotNone(app.runs.read_result(reference['result_id']))
            self.assertTrue(next((Path(home)/'tasks'/task/'artifacts').rglob('simulator_screenshot')).read_bytes().startswith(b'\x89PNG'))

    def test_preview_example_builds_selftests_and_persists_qr_with_real_worker(self):
        import shutil
        from tests.fixtures.uniapp_project import project,compatible_test_node,install_jest_report_protocol
        with tempfile.TemporaryDirectory() as home,tempfile.TemporaryDirectory() as directory,Application(home) as app:
            root=Path(directory);project(root);install_jest_report_protocol(root)
            for name in ('manifest.json','build.cjs'):
                source=root/name;source.write_text(source.read_text().replace('touristappid','wx0123456789abcdef'))
            ci=root/'ci/node_modules/miniprogram-ci';ci.mkdir(parents=True)
            (ci/'package.json').write_text('{"name":"miniprogram-ci","version":"2.1.48","main":"index.js"}')
            (ci/'index.js').write_bytes((ROOT/'tests/fixtures/wechat_ci.cjs').read_bytes())
            sdk=root/'deps/node_modules/miniprogram-automator';sdk.mkdir(parents=True);(sdk/'package.json').write_text('{"name":"miniprogram-automator","version":"0.12.1","main":"index.cjs"}');(sdk/'index.cjs').write_bytes((ROOT/'tests/fixtures/wechat_sdk.cjs').read_bytes().replace(b'pages/main/main',b'pages/index/index').replace(b'touristappid',b'wx0123456789abcdef'))
            node=compatible_test_node();output=root/'dist/build/mp-weixin'
            config={'project_root':str(root),'kind':'cli','node_path':node,'node_major':22,'package_manager':shutil.which('npm'),'build_scripts':{'production:mp-weixin':{'script':'build:mp-weixin','completion':'BUILD_COMPLETE'}},'outputs':{'production:mp-weixin':'dist/build/mp-weixin'},'test_scripts':{'mp-weixin':{'script':'test:mp-weixin','forwards_jest_args':True}},'report_root':'.reports'}
            wechat={'project_root':str(output),'node_path':node,'module_root':str(root/'deps'),'mode':'attach','endpoint':'ws://127.0.0.1:19560','storage_namespace':'tw-workflow:'}
            for plugin in ('uniapp','wechat_dev','tidb'):app.configure_plugin(plugin,True)
            env=app.environments.save('owned compiler/SDK protocols',{'uniapp_config':config,'wechat_dev_config':wechat,'wechat_release_config':{'project_root':str(output),'node_path':node,'module_root':str(root/'ci'),'private_key_ref':'release'}},{'release':'env:TW_RELEASE_KEY'})['environment_id']
            inputs={'allow_unverified_simulator_root':True,'preview':{'page_path':'pages/index/index','search_query':'a=1&b=2','scene':1011},'upload_version':'1.2.3','environment':'production','expected_page':'pages/index/index','element_assertion':{'selector':'#marker','text':'owned-fixture'},'test_suite':{'platform':'mp-weixin','file':'a.test.js','case':'selected case'}}
            task=app.tasks.create('whole mini example controlled boundary',input_schema={'type':'object','properties':{k:{'default':v} for k,v in inputs.items()}})['task_id']
            step=save_confirm(app,task,example('miniprogram_preview.py'),MINI_CAPS+['wechat_dev.check_environment','wechat_dev.preview','wechat_dev.upload'],env);
            with patch.dict(os.environ,{'TW_RELEASE_KEY':'fixture-private-key'}):run,done=execute(app,task,env)
            self.assertEqual(done['status'],'SUCCEEDED',done['attempts']);report=app.repo.read_output(run,step['step_id']);self.assertTrue(report['passed']);self.assertTrue(report['suite']['passed']);self.assertEqual(report['connection']['result']['identity_level'],'appid_and_page');self.assertFalse(report['connection']['result']['root_verified'])
            handlers={r['handler_id'] for r in done['results']};self.assertTrue({'uniapp.file','uniapp.json','wechat_dev.image','wechat_dev.json'}<=handlers)
            for reference in done['results']:self.assertIsNotNone(app.runs.read_result(reference['result_id']))
            self.assertTrue(next((Path(home)/'tasks'/task/'artifacts').rglob('simulator_screenshot')).read_bytes().startswith(b'\x89PNG'))
            self.assertEqual(report['preview']['remote_state'],'completed')
            self.assertEqual(report['upload']['version'],'1.2.3')
            self.assertTrue(next((Path(home)/'tasks'/task/'artifacts').rglob('preview_qr')).read_bytes().startswith(b'\x89PNG'))
            rejected_run,rejected=execute(app,task,env,{'allow_unverified_simulator_root':False})
            self.assertEqual(rejected['status'],'FAILED')
            self.assertIn('runtime project root is unverified',rejected['attempts'][-1]['error_summary'])
            self.assertFalse(any(row['handler_id']=='wechat_dev.image' for row in rejected['results']))

@unittest.skipUnless(os.getenv('TW_DEVOPS_BROWSER_PATH'),'explicit owned Chromium path required')
class DevopsControlledBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def test_wordpress_example_full_registered_controlled_route_and_saved_outputs(self):
        """WP/panel protocols + genuine SSH/process/HTTP/Chromium/worker, not PHP E2E."""
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        import tarfile
        from tests.fixtures.ssh_server import SshServer
        with tempfile.TemporaryDirectory() as directory,tempfile.TemporaryDirectory() as home:
            root=Path(directory).resolve();site=root/'site';site.mkdir();ssh=await SshServer(root).start()
            panel=BaotaServer(root).start()
            def owned_site(params):
                response=panel.dispatch('/site','AddSite',params);panel.directories.add(params['path']);return response
            panel.overrides['AddSite']=owned_site
            def owned_backup(params):
                response=panel.dispatch('/site','ToBackup',params);backup=panel.backups[-1];backup.update(pid=int(params['id']),name='controlled.test_20261003_120000.tar.gz',filename='/www/backup/site/controlled.test/controlled.test_20261003_120000.tar.gz');panel.files[backup['filename']]=panel.archive;return response
            panel.overrides['ToBackup']=owned_backup
            self.addAsyncCleanup(ssh.close);self.addCleanup(panel.close)
            transfer=root/'transfer.txt';transfer.write_text('owned uploaded deployment marker')
            wp=root/'protocol-wp';wp.write_text('#!'+sys.executable+'\n'+r'''import json,sys
from pathlib import Path
a=[x for x in sys.argv[1:] if not x.startswith('--path=') and x!='--no-color'];args={x[2:].split('=',1)[0]:x.split('=',1)[1] for x in a if x.startswith('--') and '=' in x};p=Path.cwd();op=a[:2]
if op==['core','download']: (p/'version').write_text(args['version']);print('Success')
elif op==['core','version']: print((p/'version').read_text())
elif op==['config','create']: sys.stdin.read();(p/'wp-config.php').write_text('<?php // owned protocol config');(p/'configuration.json').write_text(json.dumps({'DB_NAME':args['dbname'],'DB_HOST':args['dbhost'],'table_prefix':args['dbprefix']}));print('Success')
elif op==['config','path']: print(p/'wp-config.php')
elif op==['config','get']: print(json.loads((p/'configuration.json').read_text())[a[2]])
elif op==['config','has']: sys.exit(1)
elif op==['core','is-installed']: sys.exit(0 if (p/'installed').exists() else 1)
elif op==['db','query']: print('1')
elif op==['core','install']: sys.stdin.read();(p/'installed').write_text('yes');(p/'url').write_text(args['url']);print('Success')
elif op==['post','create']: row={'ID':1,'post_type':args['post_type'],'post_title':args['post_title'],'post_status':args['post_status'],'post_content':sys.stdin.read()};(p/'post.json').write_text(json.dumps(row));print('1')
elif op==['post','get']: print((p/'post.json').read_text())
elif op==['option','get'] and a[2]=='siteurl': print(json.dumps((p/'url').read_text()))
elif op==['db','tables']: print('wf_posts')
elif op==['db','export']: Path(a[2]).write_text('CREATE TABLE `wf_posts` (`ID` bigint);\nINSERT INTO `wf_posts` VALUES (1);\n');print('Success')
else: print('unsupported owned protocol command',a,file=sys.stderr);sys.exit(7)
''');wp.chmod(0o700)
            class Page(BaseHTTPRequestHandler):
                def do_GET(self):
                    row=json.loads((site/'post.json').read_text());body=('<html><h1 id="owned">'+row['post_title']+'</h1><p>'+row['post_content']+'</p></html>').encode();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write(body)
                def log_message(self,*args):pass
            http=ThreadingHTTPServer(('127.0.0.1',0),Page);thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start();self.addCleanup(thread.join,2);self.addCleanup(http.server_close);self.addCleanup(http.shutdown)
            url='http://127.0.0.1:'+str(http.server_port)
            environment={'baota_url':panel.url,'baota_api_secret_ref':'panel','baota_allow_http':True,'wordpress_site_path':str(site),'wordpress_local_root':str(root),'wordpress_wp_path':str(wp),'wordpress_owned_tables':['wf_posts'],'ssh_local_root':str(root),'browser':{'headless':True,'executable_path':os.environ['TW_DEVOPS_BROWSER_PATH']}}
            environment.update({'ssh_'+k:v for k,v in ssh.config().items()})
            inputs={'site':{'domain':'controlled.test','path':'/www/wwwroot/controlled.test'},'database':{'name':'wf_db','username':'wf_user','password_ref':'db','access':'127.0.0.1'},'transfer':{'local_path':str(transfer),'remote_path':str(root/'uploaded.txt')},'core':{'version':'7.1.2','locale':'en_US'},'configuration':{'dbname':'wf_db','dbuser':'wf_user','dbhost':'127.0.0.1','dbprefix':'wf_','db_password_ref':'db'},'install':{'url':url,'title':'Owned controlled','admin_user':'owner','admin_email':'owner@controlled.test','admin_password_ref':'admin'},'content':{'post_type':'page','title':'Owned controlled','status':'publish','content':'Verified controlled route'},'page_url':url,'page_assertion':{'selector':'#owned','text':'Owned controlled'},'backup':{'tables':['wf_posts']}}
            def run():
                with patch.dict(os.environ,{'TW_DEPLOY_PANEL':panel.secret,'TW_DEPLOY_DB':'owned-db-secret','TW_DEPLOY_ADMIN':'owned-admin-secret','TW_SSH_PASSWORD':'test-password'}),Application(home) as app:
                    for plugin in ('baota_dashboard','ssh','wordpress','playwright'):app.configure_plugin(plugin,True)
                    env=app.environments.save('controlled complete route',environment,{'panel':'env:TW_DEPLOY_PANEL','db':'env:TW_DEPLOY_DB','admin':'env:TW_DEPLOY_ADMIN','password':'env:TW_SSH_PASSWORD'})['environment_id'];task=app.tasks.create('full controlled WordPress example',input_schema={'type':'object','properties':{k:{'default':v} for k,v in inputs.items()}})['task_id'];step=save_confirm(app,task,example('wordpress_site.py'),WP_CAPS,env);run_id,done=execute(app,task,env)
                    self.assertEqual(done['status'],'SUCCEEDED',{'attempts':[(a['error_code'],a['error_phase']) for a in done['attempts']],'panel_actions':[(action,params.get('path'),params.get('filename')) for _,_,action,params in panel.requests]});self.assertTrue(app.repo.read_output(run_id,step['step_id'])['passed'])
                    handlers={r['handler_id'] for r in done['results']};self.assertTrue({'wordpress.json','wordpress.file','playwright.image'}<=handlers)
                    for result in done['results']:self.assertIsNotNone(app.runs.read_result(result['result_id']))
                    files=Path(home)/'tasks'/task/'artifacts';archive=next(files.rglob('site_backup'));image=next(files.rglob('site_screenshot'));self.assertTrue(image.read_bytes().startswith(b'\x89PNG'))
                    with tarfile.open(archive,mode='r:gz') as saved:
                        self.assertTrue(saved.getnames());self.assertTrue(any('wf_posts' in saved.extractfile(member).read().decode() for member in saved if member.isfile() and member.name.endswith('.sql')))
                    self.assertEqual((root/'uploaded.txt').read_text(),transfer.read_text())
                    evidence={'scope':'complete registered route / panel+WP CLI protocols / real SFTP/process/HTTP/Chromium/host persistence; not native PHP/WordPress or coherent external deployment','run_status':done['status'],'outputs':[r['handler_id'] for r in done['results']],'archive_bytes':archive.stat().st_size,'png_bytes':image.stat().st_size,'all_panels_actions':[action for _,_,action,_ in panel.requests]}
                    receipt=os.getenv('TW_DEVOPS_ROUTE_RECEIPT')
                    if receipt:Path(receipt).write_text(json.dumps(evidence,indent=2));Path(receipt).chmod(0o600)
            await asyncio.to_thread(run)
