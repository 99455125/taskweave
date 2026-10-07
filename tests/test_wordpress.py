"""WordPress typed argv, transport and safe full-site envelope regressions."""
import importlib.util
import unittest

# Independent expected argv is based on pinned WP-CLI 2.12 command contracts.
CASES = {
 'check_environment': ({}, ['cli','info','--format=json']),
 'is_installed': ({}, ['core','is-installed']),
 'core_download': ({'version':'7.1.2','locale':'en_US'}, ['core','download','--version=7.1.2','--locale=en_US']),
 'core_install': ({'url':'http://fixture.test','title':'A;$(x)','admin_user':'owner','admin_email':'owner@fixture.test','admin_password_ref':'admin'}, ['core','install','--url=http://fixture.test','--title=A;$(x)','--admin_user=owner','--admin_email=owner@fixture.test','--prompt=admin_password','--quiet']),
 'core_update': ({'version':'7.1.2'}, ['core','update','--version=7.1.2']),
 'verify_checksums': ({}, ['core','verify-checksums']),
 'config_create': ({'dbname':'fixture','dbuser':'fixture','dbhost':'db','dbprefix':'tw_','db_password_ref':'db'}, ['config','create','--dbname=fixture','--dbuser=fixture','--dbhost=db','--dbprefix=tw_','--prompt=dbpass','--quiet']),
 'config_get': ({'name':'WP_DEBUG'}, ['config','get','WP_DEBUG','--type=constant']),
 'config_set': ({'name':'WP_DEBUG','value':'false'}, ['config','set','WP_DEBUG','false','--type=constant']),
 'option_get': ({'key':'blogname'}, ['option','get','blogname','--format=json']),
 'option_set': ({'key':'blogname','value':{'x':2}}, ['option','update','blogname','--format=json']),
 'set_permalink_structure': ({'structure':'/%postname%/'}, ['rewrite','structure','/%postname%/']),
 'list_themes': ({}, ['theme','list','--format=json','--fields=name,status,update,version']),
 'install_theme': ({'slug':'twentytwentyfive'}, ['theme','install','twentytwentyfive']),
 'activate_theme': ({'slug':'twentytwentyfive'}, ['theme','activate','twentytwentyfive']),
 'update_theme': ({'slug':'twentytwentyfive'}, ['theme','update','twentytwentyfive','--format=json']),
 'delete_theme': ({'slug':'twentytwentyfive'}, ['theme','delete','twentytwentyfive']),
 'list_plugins': ({}, ['plugin','list','--format=json','--fields=name,status,update,version']),
 'install_plugin': ({'slug':'hello-dolly'}, ['plugin','install','hello-dolly']),
 'activate_plugin': ({'slug':'hello-dolly'}, ['plugin','activate','hello-dolly']),
 'deactivate_plugin': ({'slug':'hello-dolly'}, ['plugin','deactivate','hello-dolly']),
 'update_plugin': ({'slug':'hello-dolly'}, ['plugin','update','hello-dolly','--format=json']),
 'delete_plugin': ({'slug':'hello-dolly'}, ['plugin','delete','hello-dolly']),
 'list_posts': ({'limit':3,'offset':4,'post_type':'page'}, ['post','list','--post_type=page','--posts_per_page=3','--offset=4','--orderby=ID','--order=ASC','--format=json','--fields=ID,post_title,post_name,post_status,post_type']),
 'create_post': ({'title':'x;$(bad)','content':'body','post_type':'page','status':'draft'}, ['post','create','-','--post_type=page','--post_title=x;$(bad)','--post_status=draft','--porcelain']),
 'update_post': ({'id':7,'content':'body','title':'new','post_type':'page'}, ['post','update','7','-','--post_title=new']),
 'delete_post': ({'id':7,'post_type':'page'}, ['post','delete','7']),
 'list_terms': ({'taxonomy':'category','limit':3,'offset':4}, ['term','list','category','--number=3','--offset=4','--orderby=id','--order=ASC','--format=json','--fields=term_id,name,slug,parent,count']),
 'create_term': ({'taxonomy':'category','name':'cats'}, ['term','create','category','cats','--porcelain']),
 'update_term': ({'taxonomy':'category','id':9,'name':'dogs'}, ['term','update','category','9','--name=dogs']),
 'delete_term': ({'taxonomy':'category','id':9}, ['term','delete','category','9']),
 'list_menus': ({}, ['menu','list','--format=json','--fields=term_id,name,slug,locations,count']),
 'create_menu': ({'name':'main'}, ['menu','create','main','--porcelain']),
 'delete_menu': ({'menu':2}, ['menu','delete','2']),
 'add_menu_item': ({'menu':2,'kind':'custom','title':'one','link':'https://example.test'}, ['menu','item','add-custom','2','one','https://example.test','--porcelain']),
 'update_menu_item': ({'menu':2,'id':8,'title':'two','parent_id':0}, ['menu','item','update','8','--title=two','--parent-id=0']),
 'delete_menu_item': ({'menu':2,'id':8}, ['menu','item','delete','8']),
 'list_media': ({'limit':3,'offset':4}, ['post','list','--post_type=attachment','--post_status=inherit','--posts_per_page=3','--offset=4','--orderby=ID','--order=ASC','--format=json','--fields=ID,post_title,post_excerpt,post_content,post_mime_type,guid,post_parent']),
 'import_media': ({'source':'https://example.test/image.jpg','description':'photo'}, ['media','import','https://example.test/image.jpg','--porcelain','--desc=photo']),
 'update_media': ({'id':8,'caption':'c','description':'d'}, ['post','update','8','--post_excerpt=c','--post_content=d']),
 'delete_media': ({'id':8}, ['post','delete','8','--force']),
 'list_users': ({'limit':3,'offset':4}, ['user','list','--number=3','--offset=4','--orderby=ID','--order=ASC','--format=json','--fields=ID,user_login,user_email,display_name,roles']),
 'create_user': ({'login':'bob','email':'bob@example.test','user_role':'editor','password_ref':'bob'}, ['user','create','bob','bob@example.test','--role=editor','--prompt=user_pass','--porcelain','--quiet']),
 'set_user_role': ({'id':3,'user_role':'editor'}, ['user','set-role','3','editor']),
 'set_user_password': ({'id':3,'password_ref':'bob'}, ['user','update','3','--prompt=user_pass','--quiet']),
 'delete_user': ({'id':3,'reassign':1}, ['user','delete','3','--yes','--reassign=1']),
 'db_export': ({'path':'/site/export.sql','tables':['tw_posts','tw_options']}, ['db','export','/site/export.sql','--porcelain','--tables=tw_posts,tw_options','--single-transaction']),
 'db_import': ({'path':'/site/import.sql','tables':['tw_posts'],'checksum':'0'*64}, ['db','import','/site/import.sql']),
 'search_replace': ({'old':'old','new':'new','tables':['tw_posts']}, ['search-replace','old','new','tw_posts','--format=count','--skip-columns=guid','--dry-run']),
 'cache_flush': ({'exclusive_cache':True}, ['cache','flush']),
 'set_maintenance_mode': ({'enabled':True}, ['maintenance-mode','activate']),
}

class CommandTests(unittest.TestCase):
 def setUp(self):
  self.assertIsNotNone(importlib.util.find_spec('taskweave_wordpress'), 'WordPress plugin is not implemented')
  from taskweave_wordpress.commands import build_command
  self.build=build_command
 def test_all_53_independent_actions(self):
  from taskweave_wordpress.actions import DEFINITIONS
  self.assertEqual(set(DEFINITIONS), set(CASES)|{'backup','restore'})
  self.assertEqual(len(DEFINITIONS),53)
 def test_exact_argv_all_business_groups(self):
  for name,(inputs,expected) in CASES.items():
   with self.subTest(action=name):
    self.assertEqual(self.build('wordpress.'+name,inputs),expected)
    self.assertNotIn('--allow-root',self.build(name,inputs))
 def test_secret_config_read_rejected(self):
  from taskweave.plugins.sdk import PluginError
  for name in ('DB_PASSWORD','AUTH_KEY','secure_auth_salt','api_token','password'):
   with self.subTest(name=name),self.assertRaises(PluginError): self.build('config_get',{'name':name})
 def test_secret_config_set_prompt_never_argv(self):
  self.assertEqual(self.build('config_set',{'name':'DB_PASSWORD','value_ref':'db'}),['config','set','DB_PASSWORD','--type=constant','--prompt','--quiet'])
 def test_menu_variants(self):
  self.assertEqual(self.build('add_menu_item',{'menu':2,'kind':'post','post_id':5,'link':'https://example.test'}),['menu','item','add-post','2','5','--porcelain','--link=https://example.test'])
  self.assertEqual(self.build('add_menu_item',{'menu':2,'kind':'term','taxonomy':'category','term_id':5}),['menu','item','add-term','2','category','5','--porcelain'])
 def test_reject_missing_target_unknown_flags_and_unbounded_lists(self):
  from taskweave.plugins.sdk import PluginError
  for action,data in [('delete_plugin',{}),('list_posts',{'limit':-1}),('core_update',{'version':'7','force':True}),('config_set',{'name':'DB_PASSWORD','value':'raw'}),('search_replace',{'old':'x','new':'y','tables':['tw_*']}),('create_post',{'title':'x','post_type':'post','status':'draft','content':'x','extra':'bad'})]:
   with self.subTest(action=action),self.assertRaises(PluginError): self.build(action,data)

if __name__=='__main__': unittest.main()

import asyncio
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
from types import SimpleNamespace

class TestContext:
 def __init__(self):
  self.scope=SimpleNamespace(attempt_id='attempt-1')
  self.environment={}; self.task_parameters={}; self.logs=[]
  self.secrets={'password':'confidential-secret-value'}
 def cancelled(self): return False
 def resolve_secret(self,key): return self.secrets[key]
 def log(self,level,text): self.logs.append(text)

class TransportTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.assertIsNotNone(importlib.util.find_spec('taskweave_wordpress.transport'),'WordPress transport is missing')
  from taskweave_wordpress.transport import SiteTransport, run_wp
  self.Transport=SiteTransport; self.run_wp=run_wp
  self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
  self.ctx=TestContext()
  program=Path(self.temp.name,'wp-fixture')
  program.write_text('#!'+sys.executable+'\nimport sys\nargs=[a for a in sys.argv[1:] if not a.startswith("--path=") and a!="--no-color"]\nexec(args[1])\n')
  program.chmod(0o700)
  self.config={'mode':'local','site_path':self.temp.name,'local_root':self.temp.name,'wp_path':str(program)}
 async def test_secret_redacted_before_output_clipping(self):
  result=await self.run_wp(self.ctx,self.config,['-c','import sys; print("x"*1010+sys.stdin.read())'],secret_inputs={'user_pass':'password'},parse_json=False)
  self.assertNotIn('confidential',json.dumps(result)+str(self.ctx.logs))
 async def test_json_truncation_nonzero_and_limits_are_failures(self):
  from taskweave.plugins.sdk import PluginError
  for code,config in [('print("["+"0,"*2000+"0]")',{'max_output_bytes':1024}),('import sys;sys.exit(5)',{}),('print("{}")',{'timeout_seconds':0}),('print("not-json")',{})]:
   with self.subTest(code=code),self.assertRaises(PluginError): await self.run_wp(self.ctx,{**self.config,**config},['-c',code],secret_inputs={},parse_json=True)
 async def test_site_symlink_escape_rejected_before_dispatch(self):
  from taskweave.plugins.sdk import PluginError
  other=tempfile.TemporaryDirectory();self.addCleanup(other.cleanup)
  Path(self.temp.name,'escape').symlink_to(other.name,target_is_directory=True)
  with self.assertRaises(PluginError): await self.run_wp(self.ctx,{**self.config,'site_path':str(Path(self.temp.name,'escape'))},['-c','print(1)'],secret_inputs={},parse_json=False)
 async def test_journal_preserves_writes_across_roles_and_later_read_failure(self):
  from taskweave_wordpress.transport import WriteEvidence
  journal=WriteEvidence(); a=object(); b=object()
  journal.begin(self.ctx,a); journal.begin(self.ctx,b)
  first=journal.dispatch(self.ctx,'create_post','role-a','post create'); first['completion']='completed'
  second=journal.dispatch(self.ctx,'config_set','role-b','config set')
  journal.capture(self.ctx,RuntimeError(),{'stderr':'safe'})
  results=await journal.results(self.ctx,RuntimeError())
  self.assertEqual([r['completion'] for r in results[0].payload['requests']],['completed','unknown'])
  journal.close(a);self.assertEqual(len((await journal.results(self.ctx,RuntimeError()))[0].payload['requests']),2)
  journal.close(b);self.assertEqual(await journal.results(self.ctx,RuntimeError()),[])
 async def test_journal_capacity_refuses_before_dispatch_and_is_attempt_scoped(self):
  from taskweave_wordpress.transport import WriteEvidence
  from taskweave.plugins.sdk import PluginError
  journal=WriteEvidence(); owner=object();journal.begin(self.ctx,owner)
  for i in range(128):
   try: journal.dispatch(self.ctx,'create_post','r','post create')
   except PluginError: break
  else: self.fail('bounded journal did not refuse')
  self.ctx.scope.attempt_id='attempt-2';self.assertEqual(await journal.results(self.ctx,RuntimeError()),[])

class BackupTests(unittest.TestCase):
 def setUp(self):
  self.assertIsNotNone(importlib.util.find_spec('taskweave_wordpress.backup'),'WordPress backup is missing')
  from taskweave_wordpress.backup import validate_archive, make_archive
  self.validate=validate_archive;self.make=make_archive
  self.identity={'site_path':'/site','url':'http://site.test','db_name':'db','db_host':'db:3306','table_prefix':'tw_','version':'7.1.2'}
 def test_full_package_contains_files_sql_and_hashes(self):
  raw=self.make(self.identity,['tw_posts'],{'wp-config.php':(b'config',0o600),'.htaccess':(b'rewrite',0o644)},b'CREATE TABLE `tw_posts` (`ID` int);',max_bytes=16384,max_members=10)
  manifest,files,sql=self.validate(raw,self.identity,['tw_posts'],max_bytes=16384,max_members=10)
  self.assertEqual(set(files),{'wp-config.php','.htaccess'})
  self.assertIn(b'tw_posts',sql)
  self.assertEqual(manifest['files']['wp-config.php']['sha256'],hashlib.sha256(b'config').hexdigest())
 def test_restore_rejects_absolute_and_symlink_escape_members(self):
  from taskweave.plugins.sdk import PluginError
  for path,link in [('/etc/passwd',None),('../outside',None),('files/wp-config.php','../../outside')]:
   raw=io.BytesIO()
   with tarfile.open(fileobj=raw,mode='w:gz') as archive:
    entry=tarfile.TarInfo(path)
    if link: entry.type=tarfile.SYMTYPE;entry.linkname=link
    else: entry.size=1
    archive.addfile(entry,None if link else io.BytesIO(b'x'))
   with self.subTest(path=path),self.assertRaises(PluginError): self.validate(raw.getvalue(),self.identity,['tw_posts'],max_bytes=16384,max_members=10)
 def test_sql_scope_and_wrong_site_rejected(self):
  from taskweave.plugins.sdk import PluginError
  for sql in [b'DROP TABLE `other_posts`;',b'USE other; CREATE TABLE `tw_posts` (`x` int);',b'CREATE DATABASE other;',b'/*!50000 DROP TABLE other */;']:
   with self.subTest(sql=sql),self.assertRaises(PluginError): self.make(self.identity,['tw_posts'],{'index.php':(b'x',0o644)},sql,max_bytes=16384,max_members=10)
  raw=self.make(self.identity,['tw_posts'],{'index.php':(b'x',0o644)},b'CREATE TABLE `tw_posts` (`ID` int);',max_bytes=16384,max_members=10)
  with self.assertRaises(PluginError): self.validate(raw,{**self.identity,'url':'http://other.test'},['tw_posts'],max_bytes=16384,max_members=10)

class BusinessTests(unittest.IsolatedAsyncioTestCase):
 async def test_restore_selected_expanded_budget_precedes_writes(self):
  from unittest.mock import AsyncMock,patch
  from taskweave_wordpress.backup import restore_site,make_archive,digest
  from taskweave_wordpress.transport import SiteTransport
  from taskweave.plugins.sdk import PluginError
  identity={'site_path':'/site'}
  raw=make_archive(identity,['tw_posts'],{'a.php':(b'a'*4096,0o600)},b'CREATE TABLE `tw_posts` (`ID` int);',max_bytes=16384,max_members=10)
  site=SiteTransport({'site_path':'/site'});site.site='/site';site.read=AsyncMock(return_value=raw);site.write=AsyncMock();site.path=AsyncMock(return_value='/site/a.php')
  with patch('taskweave_wordpress.backup.site_identity',return_value=identity),patch('taskweave_wordpress.backup.verified_tables',return_value=['tw_posts']):
   with self.assertRaises(PluginError): await restore_site(TestContext(),site,{'path':'/site/backup','checksum':digest(raw),'tables':['tw_posts'],'max_bytes':16384,'max_unpacked_bytes':2048})
  site.write.assert_not_awaited()
 async def asyncSetUp(self):
  import taskweave_wordpress
  self.assertTrue(hasattr(taskweave_wordpress,"WordPressPlugin"),"plugin registration is missing")
  from taskweave_wordpress import WordPressPlugin
  from taskweave.plugins.registry import Registry
  self.plugin=WordPressPlugin();self.registry=Registry([self.plugin])
 def test_registry_all_actions_have_owned_resource_and_strict_schemas(self):
  from taskweave.core.validation import TaskError,validate
  self.assertEqual(len(self.registry.actions),53)
  self.assertEqual(set(self.registry.providers),{'wordpress.site'})
  self.assertEqual(set(self.registry.handlers),{'wordpress.file','wordpress.json','wordpress.operation_failure'})
  self.registry.contributions(list(self.registry.actions))
  for action in self.registry.actions.values():
   self.assertEqual(action.spec.resource_ids,('wordpress.site',))
   with self.assertRaises(TaskError): validate({'unknown':True},action.spec.input_schema)
   if action.spec.effect=='WRITE':self.assertFalse(action.spec.retry_safe)
 async def test_core_install_existing_does_not_dispatch_install(self):
  from taskweave_wordpress.actions import perform
  class Site:
   def __init__(self): self.calls=[]
   async def execute(self,ctx,argv,**options):
    self.calls.append(argv);return {'exit_code':0,'stdout':'','stderr':'','stdout_truncated':False,'stderr_truncated':False}
  site=Site();result=await perform(TestContext(),site,'core_install',CASES['core_install'][0])
  self.assertEqual(result['completion'],'noop');self.assertEqual(site.calls,[['core','is-installed']])
 async def test_installed_failure_is_not_reported_false(self):
  from taskweave_wordpress.actions import installed
  from taskweave.plugins.sdk import PluginError
  class Site:
   async def execute(self,ctx,argv,**options): return {'exit_code':1,'stdout':'','stderr':'database authentication failed','stdout_truncated':False,'stderr_truncated':False}
  with self.assertRaises(PluginError): await installed(TestContext(),Site())
 async def test_restore_reports_partial_failure(self):
  from unittest.mock import patch
  from taskweave_wordpress.backup import restore_site,make_archive,digest
  from taskweave_wordpress.transport import SiteTransport,WriteEvidence
  identity=BackupTests().identity if hasattr(BackupTests(),'identity') else {'site_path':'/site','url':'http://site.test','db_name':'db','db_host':'db:3306','table_prefix':'tw_','version':'7.1.2'}
  data=make_archive(identity,['tw_posts'],{'a.php':(b'a',0o600),'b.php':(b'b',0o600)},b'CREATE TABLE `tw_posts` (`ID` int);',max_bytes=16384,max_members=10)
  ctx=TestContext();evidence=WriteEvidence();site=SiteTransport({'site_path':'/site'},evidence);site.site='/site';site.root='/site';site.start(ctx,'restore','default',{})
  async def read(path,limit): return data if path=='/site/backup' else b'a'
  async def write(path,content,mode=0o600):
   if path.endswith('b.php'): raise OSError('disk failure')
  async def path(value,**options): return value
  site.read=read;site.write=write;site.path=path
  with patch('taskweave_wordpress.backup.site_identity',return_value=identity),patch('taskweave_wordpress.backup.verified_tables',return_value=['tw_posts']):
   with self.assertRaises(OSError): await restore_site(ctx,site,{'path':'/site/backup','checksum':digest(data),'tables':['tw_posts'],'max_bytes':16384})
  receipts=(await evidence.results(ctx,RuntimeError()))[0].payload['requests']
  self.assertEqual(receipts[0]['completion'],'partial')
  self.assertEqual(receipts[0]['completed_files'],1)
  self.assertIn('pending_file_sha256',receipts[0])

class ArchiveBudgetsTests(unittest.TestCase):
 def test_transfer_and_expanded_site_have_independent_budgets(self):
  import inspect
  from taskweave_wordpress.backup import make_archive,validate_archive
  self.assertIn('max_unpacked_bytes',inspect.signature(make_archive).parameters,'expanded site budget is missing')
  identity={'site_path':'/site'};files={'a.php':(b'a'*4096,0o600),'b.php':(b'b'*4096,0o600)};sql=b'CREATE TABLE `tw_posts` (`id` int);'
  raw=make_archive(identity,['tw_posts'],files,sql,max_bytes=5000,max_unpacked_bytes=12000,max_members=10)
  self.assertLess(len(raw),5000)
  self.assertEqual(len(validate_archive(raw,identity,['tw_posts'],max_bytes=5000,max_unpacked_bytes=12000,max_members=10)[1]),2)
  from taskweave.plugins.sdk import PluginError
  for kwargs in ({'max_unpacked_bytes':5000},{'max_bytes':3000},{'max_members':3}):
   with self.subTest(kwargs=kwargs),self.assertRaises(PluginError): make_archive(identity,['tw_posts'],files,sql,**{'max_bytes':5000,'max_unpacked_bytes':12000,'max_members':10,**kwargs})
   with self.subTest(restore=kwargs),self.assertRaises(PluginError): validate_archive(raw,identity,['tw_posts'],**{'max_bytes':5000,'max_unpacked_bytes':12000,'max_members':10,**kwargs})
  import random
  entropy=random.Random(421).randbytes(8192)
  incompressible={'a':(entropy[:4096],0o600),'b':(entropy[4096:],0o600)}
  with self.assertRaises(PluginError): make_archive(identity,['tw_posts'],incompressible,sql,max_bytes=5000,max_unpacked_bytes=12000,max_members=10)
  packed=make_archive(identity,['tw_posts'],incompressible,sql,max_bytes=16384,max_unpacked_bytes=12000,max_members=10)
  self.assertGreater(len(packed),5000)
  with self.assertRaises(PluginError): validate_archive(packed,identity,['tw_posts'],max_bytes=5000,max_unpacked_bytes=12000,max_members=10)

class WorkerEvidenceTests(unittest.TestCase):
 def test_actual_worker_keeps_concurrent_writes_after_later_read_failure(self):
  from taskweave.application.service import Application
  from taskweave.infrastructure.storage import uid
  from taskweave.plugins.registry import Registry
  from taskweave_wordpress import WordPressPlugin
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);wp=root/'wp-fixture'
   wp.write_text('#!'+sys.executable+'\nimport sys,json\nfrom pathlib import Path\na=[x for x in sys.argv[1:] if not x.startswith("--path=") and x!="--no-color"]\nif a[:2]==["core","is-installed"]: sys.exit(0)\nif a[:2]==["config","set"]: Path(a[2]).write_text(a[3]); print("Success")\nelif a[:2]==["config","get"]: print(Path(a[2]).read_text())\nelse: print("deliberate read failure",file=sys.stderr);sys.exit(7)\n')
   wp.chmod(0o700)
   with Application(root/'host',registry_factory='tests.fixtures.wordpress_site:concurrent_worker_registry') as app:
    env=app.repo.save_environment('WP protocol fixture',{'wordpress_mode':'local','wordpress_site_path':str(root),'wordpress_local_root':str(root),'wordpress_wp_path':str(wp)},{})['environment_id']
    task=app.repo.create_task('WP cumulative effects')['task_id']
    content='async def run(ctx, inputs):\n    await ctx.call("wordpress.config_set", {"name":"FIELD_A","value":"a","role":"a"})\n    await ctx.call("wordpress.option_get", {"key":"failure","role":"a"})'
    step=app.repo.save_step(task,{'name':'write then fail','capabilities':['wordpress.config_set','wordpress.option_get'],'step_content':content})
    app.confirm_step_manual(step['step_id'],step['content_hash'],environment_id=env)
    created=app.create_run(task,environment_id=env);app.coordinator.start(created['run_id'],uid())
    finished=app.coordinator.wait(created['run_id'],12)
    self.assertEqual(finished['status'],'FAILED',finished)
    attempt=finished['attempts'][0];self.assertEqual(attempt['effect_state'],'UNKNOWN')
    refs=app.repo.repositories.results.refs_for_attempt(attempt['attempt_id']);self.assertEqual(len(refs),1)
    stored=app.repo.read_result(refs[0]['result_id'],Registry([WordPressPlugin()]))['data']
    self.assertEqual({row['role'] for row in stored['requests']},{'a','b'})
    self.assertEqual([row['completion'] for row in stored['requests']],['completed','completed'])
    self.assertLess(len(json.dumps(stored).encode()),65536)

class BoundaryTests(unittest.TestCase):
 def test_boolean_false_does_not_enable_force_or_network(self):
  from taskweave_wordpress.commands import build_command
  self.assertEqual(build_command('delete_post',{'id':1,'post_type':'post','force':False}),['post','delete','1'])
  self.assertEqual(build_command('activate_plugin',{'slug':'hello-dolly','network':False}),['plugin','activate','hello-dolly'])
  self.assertIn('--hide_empty=0',build_command('list_terms',{'taxonomy':'category','hide_empty':False}))
 def test_positional_flags_do_not_expand_capability(self):
  from taskweave_wordpress.commands import build_command
  from taskweave.plugins.sdk import PluginError
  for name,values in [('create_menu',{'name':'--debug'}),('create_term',{'taxonomy':'category','name':'--format=json'}),('config_set',{'name':'WP_DEBUG','value':'--raw'}),('search_replace',{'old':'--all-tables','new':'x','tables':['tw_posts']})]:
   with self.subTest(name=name),self.assertRaises(PluginError): build_command(name,values)

class InstallSourceTests(unittest.TestCase):
 def test_archive_or_url_source_keeps_explicit_expected_slug(self):
  from taskweave_wordpress.actions import DEFINITIONS
  self.assertIn('source',DEFINITIONS['install_plugin'][0]['properties'],'archive installation input missing')
  from taskweave_wordpress.commands import build_command
  self.assertEqual(build_command('install_plugin',{'slug':'hello-dolly','source':'/site/hello-dolly.zip'}),['plugin','install','/site/hello-dolly.zip'])
  self.assertEqual(build_command('install_theme',{'slug':'twentytwentyfive','source':'https://downloads.wordpress.org/theme/twentytwentyfive.1.4.zip','version':'1.4'}),['theme','install','https://downloads.wordpress.org/theme/twentytwentyfive.1.4.zip','--version=1.4'])

class UserPreflightTests(unittest.IsolatedAsyncioTestCase):
 async def test_user_creation_checks_exact_login_email_with_supported_search(self):
  from taskweave_wordpress.actions import perform
  class Site:
   def __init__(self): self.commands=[]
   async def execute(self,ctx,command,**options):
    self.commands.append(command)
    if command[:2]==['core','is-installed']: return {'exit_code':0,'stdout':'','stderr':'','stdout_truncated':False,'stderr_truncated':False}
    if command[:2]==['user','list']:
     rows=[] if '--search=bob' in command or '--search=bob@example.test' in command else [{'ID':1,'user_login':'owner','user_email':'owner@example.test'}]
     return {'exit_code':0,'data':rows,'stdout':json.dumps(rows),'stderr':''}
    if command[:2]==['user','create']: return {'stdout':'2\n','stderr':'','exit_code':0}
    if command[:2]==['user','get']: return {'data':{'ID':2,'user_login':'bob','user_email':'bob@example.test','roles':['editor']},'stdout':'','stderr':'','exit_code':0}
    raise AssertionError(command)
  site=Site();ctx=TestContext();ctx.secrets['bob']='secret-user-password'
  try: result=await perform(ctx,site,'create_user',CASES['create_user'][0])
  except Exception as exc: self.fail('unique username/email were rejected: '+str(exc))
  self.assertEqual(result['result']['id'],2)
  self.assertTrue(any('--search=bob@example.test' in command for command in site.commands))

class DeadlineTests(unittest.IsolatedAsyncioTestCase):
 async def test_timeout_includes_owned_resource_connection(self):
  from taskweave_wordpress import WordPressPlugin
  ctx=TestContext()
  class Resources:
   async def acquire(self,*args):
    await asyncio.sleep(2)
    raise RuntimeError('resource deadline did not include open')
  ctx.resources=Resources()
  failure=None
  try: await WordPressPlugin().actions()['wordpress.check_environment'].execute(ctx,{'timeout_seconds':1})
  except Exception as exc: failure=exc
  self.assertIsInstance(failure,asyncio.TimeoutError)

class DumpGrammarTests(unittest.TestCase):
 def test_real_mariadb_dump_charset_assignments_are_accepted(self):
  from taskweave_wordpress.backup import validate_sql
  try: validate_sql(b'SET character_set_client = utf8mb4; CREATE TABLE `tw_posts` (`id` int); SET character_set_client = @saved_cs_client;',['tw_posts'])
  except Exception as exc: self.fail('pinned real dump grammar refused: '+str(exc))

class PathClassificationTests(unittest.IsolatedAsyncioTestCase):
 async def test_missing_path_is_distinct_from_escape(self):
  from taskweave_wordpress.transport import SiteTransport
  from taskweave.plugins.sdk import PluginError
  with tempfile.TemporaryDirectory() as root,tempfile.TemporaryDirectory() as other:
   site=await SiteTransport({'site_path':root,'local_root':root}).open(TestContext())
   with self.assertRaises(PluginError) as missing: await site.path('not-present')
   self.assertEqual(missing.exception.code,'WORDPRESS_PATH_NOT_FOUND')
   Path(root,'escape').symlink_to(other,target_is_directory=True)
   with self.assertRaises(PluginError) as escape: await site.path('escape')
   self.assertEqual(escape.exception.code,'WORDPRESS_PATH_INVALID')

class SqlScopeTests(unittest.TestCase):
 def test_dump_cannot_hide_another_table_or_execute_value_expressions(self):
  from taskweave_wordpress.backup import validate_sql
  from taskweave.plugins.sdk import PluginError
  for sql in (b'DROP TABLE `tw_posts`, `unrelated`;',b'CREATE TABLE `tw_posts` LIKE `unrelated`;',b'INSERT INTO `tw_posts` VALUES (LOAD_FILE(\'/etc/passwd\'));'):
   with self.subTest(sql=sql),self.assertRaises(PluginError): validate_sql(sql,['tw_posts'])
 def test_owned_table_name_does_not_authorize_external_engine_or_storage(self):
  from taskweave_wordpress.backup import validate_sql
  from taskweave.plugins.sdk import PluginError
  for sql in [b"CREATE TABLE `tw_posts` (`id` int) ENGINE=FEDERATED CONNECTION='mysql://remote/db';",b"CREATE TABLE `tw_posts` (`id` int) ENGINE=InnoDB DATA DIRECTORY='/other';"]:
   with self.subTest(sql=sql),self.assertRaises(PluginError): validate_sql(sql,['tw_posts'])

class DirectorySnapshotTests(unittest.TestCase):
 def test_empty_directories_and_modes_are_in_complete_envelope(self):
  from taskweave_wordpress.backup import make_archive,validate_archive
  import inspect
  self.assertIn('directories',inspect.signature(make_archive).parameters,'directory snapshot is missing')
  raw=make_archive({'site_path':'/site'},['tw_posts'],{'index.php':(b'x',0o644)},b'CREATE TABLE `tw_posts` (`id` int);',directories={'wp-content/empty':0o700},max_bytes=16384,max_members=10)
  manifest,_,_=validate_archive(raw,{'site_path':'/site'},['tw_posts'],max_bytes=16384,max_members=10)
  self.assertEqual(manifest['directories'],{'wp-content/empty':0o700})

class TruncationTests(unittest.TestCase):
 def test_restore_rejects_truncated_gzip_footer(self):
  from taskweave_wordpress.backup import make_archive,validate_archive
  from taskweave.plugins.sdk import PluginError
  raw=make_archive({'site_path':'/site'},['tw_posts'],{'index.php':(b'x',0o644)},b'CREATE TABLE `tw_posts` (`id` int);',max_bytes=16384,max_members=10)
  with self.assertRaises(PluginError): validate_archive(raw[:-4],{'site_path':'/site'},['tw_posts'],max_bytes=16384,max_members=10)

class AcquisitionTests(unittest.IsolatedAsyncioTestCase):
 async def test_concurrent_same_role_open_refuses_second_before_creating_handle(self):
  from unittest.mock import patch
  from taskweave_wordpress import SiteProvider
  from taskweave_wordpress.transport import WriteEvidence
  gate=asyncio.Event();calls=[]
  async def opening(site,ctx): calls.append(site);await gate.wait();return site
  provider=SiteProvider(WriteEvidence());ctx=TestContext();ctx.environment={'wordpress_site_path':'/site'}
  with patch('taskweave_wordpress.transport.SiteTransport.open',opening):
   first=asyncio.create_task(provider.open(ctx,'same'));await asyncio.sleep(.01)
   second=asyncio.create_task(provider.open(ctx,'same'));await asyncio.sleep(.01)
   try:
    self.assertTrue(second.done(),'same-role open created another pending resource')
    self.assertEqual(len(calls),1)
   finally:
    gate.set();outcomes=await asyncio.gather(first,second,return_exceptions=True)
    for result in outcomes:
     if not isinstance(result,BaseException): await provider.close(result)

class SqlFixRoundTests(unittest.TestCase):
 def test_executable_comments_and_all_client_commands_are_rejected_outside_literals(self):
  from taskweave_wordpress.backup import validate_sql
  from taskweave.plugins.sdk import PluginError
  for payload in ['/*! DROP TABLE unrelated */','/*!100100 DROP TABLE unrelated */','/*M!100100 DROP TABLE unrelated */',r'/*+ \C utf8 */',r'/* \! validator-only */',r'\! printf validator-only',r'\q',r'\C utf8','source other.sql','delimiter $$']:
   sql=('CREATE TABLE tw_posts (id int '+payload+');').encode()
   with self.subTest(payload=payload),self.assertRaises(PluginError):validate_sql(sql,['tw_posts'])
 def test_create_grammar_consumes_all_columns_and_options(self):
  from taskweave_wordpress.backup import validate_sql
  from taskweave.plugins.sdk import PluginError
  for suffix in ['(id int CHECK (SLEEP(30)=0))','(id int) ENGINE=InnoDB ENGINE=MRG_MyISAM UNION=(unrelated)','(id int GENERATED ALWAYS AS (1+1))','(id int) COMMENT=CONCAT(1,2)','(id int) ENGINE=InnoDB trailing','(id int, KEY x (other(10)) USING evil)']:
   with self.subTest(suffix=suffix),self.assertRaises(PluginError):validate_sql(('CREATE TABLE tw_posts '+suffix+';').encode(),['tw_posts'])
 def test_literals_preserve_comment_and_client_markers(self):
  from taskweave_wordpress.backup import validate_sql,sql_statements
  sql=b"CREATE TABLE tw_posts (id int, value varchar(255) DEFAULT '/*!50000 x */'); INSERT INTO tw_posts VALUES (1,'/*M!100100 x */ \\\\! source delimiter');"
  validate_sql(sql,['tw_posts']);self.assertIn('/*!50000 x */',sql_statements(sql)[0])

class ScratchFixRoundTests(unittest.IsolatedAsyncioTestCase):
 async def test_export_cleanup_failure_stops_scan_and_preserves_prior_evidence(self):
  from unittest.mock import AsyncMock,patch
  from taskweave_wordpress.transport import SiteTransport,WriteEvidence
  from taskweave_wordpress.backup import backup_site
  ctx=TestContext();evidence=WriteEvidence()
  with tempfile.TemporaryDirectory() as directory:
   site=SiteTransport({'site_path':directory},evidence);await site.open(ctx);site.start(ctx,'backup','default',{})
   async def execute(ctx,command,**kw):
    evidence.dispatch(ctx,'backup','default','database_export')['completion']='completed'
    Path(command[2]).write_bytes(b'CREATE TABLE tw_posts (id int);')
   site.execute=execute;site.delete=AsyncMock(side_effect=OSError('cleanup denied'));site.files=AsyncMock()
   with patch('taskweave_wordpress.backup.verified_tables',return_value=['tw_posts']),patch('taskweave_wordpress.backup.site_identity',return_value={}):
    with self.assertRaises(Exception):await backup_site(ctx,site,{'tables':['tw_posts']})
   site.files.assert_not_awaited();requests=(await evidence.results(ctx,RuntimeError()))[0].payload['requests']
   self.assertEqual(next(r for r in requests if r['stage']=='database_export')['completion'],'completed');self.assertEqual(next(r for r in requests if r['stage']=='scratch_cleanup')['completion'],'unknown')
 async def test_restore_cleanup_failure_preserves_overlay_and_import_evidence(self):
  from unittest.mock import AsyncMock,patch
  from taskweave_wordpress.transport import SiteTransport,WriteEvidence
  from taskweave_wordpress.backup import restore_site,make_archive,digest
  ctx=TestContext();evidence=WriteEvidence()
  with tempfile.TemporaryDirectory() as directory:
   site=SiteTransport({'site_path':directory},evidence);await site.open(ctx);site.start(ctx,'restore','default',{})
   raw=make_archive({},['tw_posts'],{'a':(b'a',0o600)},b'CREATE TABLE tw_posts (id int);',max_bytes=16384,max_members=10)
   Path(directory,'package').write_bytes(raw)
   async def execute(ctx,command,**kw):evidence.dispatch(ctx,'restore','default','database_import')['completion']='completed';return {}
   site.execute=execute;site.delete=AsyncMock(side_effect=OSError('cleanup denied'))
   with patch('taskweave_wordpress.backup.verified_tables',return_value=['tw_posts']),patch('taskweave_wordpress.backup.site_identity',return_value={}):
    with self.assertRaises(Exception):await restore_site(ctx,site,{'path':str(Path(directory,'package')),'checksum':digest(raw),'tables':['tw_posts'],'max_bytes':16384})
   requests=(await evidence.results(ctx,RuntimeError()))[0].payload['requests']
   self.assertEqual([r['completion'] for r in requests if r['stage']!='scratch_cleanup'],['completed','completed']);self.assertEqual(next(r for r in requests if r['stage']=='scratch_cleanup')['completion'],'unknown')

class NativeDumpFixTests(unittest.TestCase):
 def test_native_mariadb_dump_metadata_and_export_only_sandbox_normalization(self):
  from taskweave_wordpress.backup import validate_sql,normalize_export
  from taskweave.plugins.sdk import PluginError
  header=b'/*M!999999\\- enable the sandbox mode */ \n'
  body=b'/*M!100616 SET @OLD_NOTE_VERBOSITY=@@NOTE_VERBOSITY, NOTE_VERBOSITY=0 */;\nCREATE TABLE tw_posts (id bigint unsigned NOT NULL AUTO_INCREMENT, body longtext, PRIMARY KEY (id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;'
  with self.assertRaises(PluginError):validate_sql(header+body,['tw_posts'])
  self.assertEqual(normalize_export(header+body),body);validate_sql(body,['tw_posts'])
 def test_session_mode_cannot_change_literal_semantics(self):
  from taskweave_wordpress.backup import validate_sql
  from taskweave.plugins.sdk import PluginError
  with self.assertRaises(PluginError):validate_sql(b"SET SQL_MODE='NO_BACKSLASH_ESCAPES'; CREATE TABLE tw_posts (id int);",['tw_posts'])

class ImportRouteFixTests(unittest.IsolatedAsyncioTestCase):
 async def test_guarded_native_stdin_receives_exact_validated_bytes(self):
  from taskweave_wordpress.backup import import_sql
  from unittest.mock import AsyncMock
  from types import SimpleNamespace
  sql=b"CREATE TABLE tw_posts (id int); INSERT INTO tw_posts VALUES (1);"
  site=SimpleNamespace(execute=AsyncMock(return_value={}))
  await import_sql(TestContext(),site,sql,['tw_posts'])
  call=site.execute.await_args
  self.assertEqual(call.args[1],['db','import','-','--binary-mode','--skip-optimization',"--init-command=SET SESSION sql_mode='NO_AUTO_VALUE_ON_ZERO'"])
  self.assertIs(call.kwargs['stdin'],sql);self.assertTrue(call.kwargs['write'])
  site.execute.reset_mock()
  with self.assertRaises(Exception):await import_sql(TestContext(),site,b'CREATE TABLE tw_posts (id int);\\! validator-only',['tw_posts'])
  site.execute.assert_not_awaited()

class ScratchProtectionTests(unittest.IsolatedAsyncioTestCase):
 async def test_native_export_uses_private_directory_outside_complete_site(self):
  from taskweave_wordpress.transport import SiteTransport
  from taskweave_wordpress.backup import export_sql
  import stat
  with tempfile.TemporaryDirectory() as directory:
   site=SiteTransport({'site_path':directory});await site.open(TestContext())
   async def execute(ctx,command,**kw):
    path=Path(command[2]);self.assertFalse(path.is_relative_to(directory));self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode),0o700);self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o600)
    path.write_bytes(b'CREATE TABLE tw_posts (id int);')
   site.execute=execute
   self.assertEqual(await export_sql(TestContext(),site,['tw_posts'],1024),b'CREATE TABLE tw_posts (id int);')
   self.assertFalse(site.scratch_files);self.assertEqual(await site.files(1024,10),{})

class ClientCommandWordFixTests(unittest.TestCase):
 def test_binary_mode_remaining_delimiter_command_cannot_be_a_bare_column(self):
  from taskweave_wordpress.backup import validate_sql
  from taskweave.plugins.sdk import PluginError
  with self.assertRaises(PluginError):validate_sql(b'CREATE TABLE tw_posts (\ndelimiter int\n);',['tw_posts'])
  validate_sql(b'CREATE TABLE tw_posts (`delimiter` int);',['tw_posts'])
  validate_sql(b"CREATE TABLE tw_posts (id int); INSERT INTO tw_posts VALUES ('line\ndelimiter $$\nline');",['tw_posts'])

class CleanupWorkerEvidenceTests(unittest.TestCase):
 def test_actual_worker_persists_prior_action_export_and_unknown_cleanup(self):
  self._assert_worker_cleanup(1)
 def test_actual_worker_full_96_journal_preserves_unknown_cleanup(self):
  self._assert_worker_cleanup(94)
 def _assert_worker_cleanup(self,count):
  from taskweave.application.service import Application
  from taskweave.infrastructure.storage import uid
  from taskweave.plugins.registry import Registry
  from taskweave_wordpress import WordPressPlugin
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);wp=root/'wp-fixture'
   wp.write_text('#!'+sys.executable+'\nimport sys\nfrom pathlib import Path\na=[x for x in sys.argv[1:] if not x.startswith("--path=") and x!="--no-color"]\nif a[:2]==["core","is-installed"]: sys.exit(0)\nif a[:2]==["config","set"]: Path(a[2]).write_text(a[3]);print("Success")\nelif a[:2]==["config","get"]: print("tw_" if a[2]=="table_prefix" else Path(a[2]).read_text())\nelif a[:2]==["db","tables"]: print("tw_posts")\nelif a[:2]==["db","export"]: Path(a[2]).write_bytes(b"CREATE TABLE tw_posts (id int);");print(a[2])\nelse:sys.exit(7)\n')
   wp.chmod(0o700)
   with Application(root/'host',registry_factory='tests.fixtures.wordpress_site:cleanup_failure_worker_registry') as app:
    env=app.repo.save_environment('WP cleanup protocol fixture',{'wordpress_mode':'local','wordpress_site_path':str(root),'wordpress_local_root':str(root),'wordpress_wp_path':str(wp),'wordpress_owned_tables':['tw_posts']},{})['environment_id']
    task=app.repo.create_task('WP cumulative cleanup failure')['task_id']
    content='async def run(ctx, inputs):\n    for i in range('+str(count)+'):\n        await ctx.call("wordpress.config_set", {"name":"FIELD_A","value":str(i)})\n    await ctx.call("wordpress.db_export", '+repr({'path':str(root/'result.sql'),'tables':['tw_posts']})+')'
    step=app.repo.save_step(task,{'name':'write then cleanup fail','capabilities':['wordpress.config_set','wordpress.db_export'],'step_content':content})
    app.confirm_step_manual(step['step_id'],step['content_hash'],environment_id=env)
    created=app.create_run(task,environment_id=env);app.coordinator.start(created['run_id'],uid())
    finished=app.coordinator.wait(created['run_id'],30)
    self.assertEqual(finished['status'],'FAILED',finished);attempt=finished['attempts'][0];self.assertEqual(attempt['effect_state'],'UNKNOWN')
    refs=app.repo.repositories.results.refs_for_attempt(attempt['attempt_id']);self.assertEqual(len(refs),1)
    payload=app.repo.read_result(refs[0]['result_id'],Registry([WordPressPlugin()]))['data']
    self.assertEqual([r['completion'] for r in payload['requests']],['completed']*count+['unknown','completed'])
    self.assertEqual([r['stage'] for r in payload['requests']],['config set']*count+['scratch_cleanup','db export'])
    self.assertEqual(len(payload['requests']),count+2)
    self.assertEqual(payload['error_code'],'WORDPRESS_SCRATCH_CLEANUP_FAILED');self.assertFalse((root/'result.sql').exists())

class ConditionalCommentRound2Tests(unittest.TestCase):
 def test_conditional_tokens_cannot_change_owned_target_in_native_skipped_branch(self):
  from taskweave_wordpress.backup import validate_sql
  from taskweave.plugins.sdk import PluginError
  for sql in [b'DROP TABLE /*M!999999 tw_*/posts;',b'CREATE TABLE /*!99999 tw_*/posts (id int);',b'CREATE TABLE /*M!999999 tw_*/posts (id int);',b'CREATE TABLE tw_posts (id /*!99999 int */);',b'/*!99999 CREATE TABLE tw_posts (id int) */;',b'/*!50000 SET SQL_MODE= */\'NO_AUTO_VALUE_ON_ZERO\';']:
   with self.subTest(sql=sql),self.assertRaises(PluginError):validate_sql(sql,['tw_posts'])
 def test_native_dump_conditional_metadata_and_keys_are_complete_owned_statements(self):
  from taskweave_wordpress.backup import validate_sql
  for marker in ['/*!40101','/*!99999','/*!100100','/*M!100616','/*M!999999','/*!','/*M!']:
   sql=(marker+" SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */; CREATE TABLE tw_posts (id int); "+marker+' ALTER TABLE tw_posts DISABLE KEYS */; INSERT INTO tw_posts VALUES (1); '+marker+' ALTER TABLE tw_posts ENABLE KEYS */; '+marker+' SET SQL_MODE=@OLD_SQL_MODE */;').encode()
   validate_sql(sql,['tw_posts'])

class ScratchCapacityRound2Tests(unittest.IsolatedAsyncioTestCase):
 async def test_full_journal_at_cleanup_does_not_prevent_actual_owned_deletion(self):
  from taskweave_wordpress.transport import SiteTransport,WriteEvidence
  ctx=TestContext();evidence=WriteEvidence()
  with tempfile.TemporaryDirectory() as directory:
   site=SiteTransport({'site_path':directory},evidence);await site.open(ctx);site.start(ctx,'backup','default',{})
   path=await site.scratch(ctx)
   await site.write(path,b'private sql');parent=Path(path).parent
   while len(evidence.journals[ctx.scope.attempt_id]['requests'])<96:evidence.dispatch(ctx,'backup','default','prior_business')['completion']='completed'
   try:
    await site.cleanup_scratch(ctx,path)
    self.assertFalse(parent.exists())
   finally:
    # Clean only this test's own directory after the RED diagnostic failure.
    if Path(path).exists():Path(path).unlink()
    if parent.exists():parent.rmdir()
   self.assertFalse(parent.exists());requests=evidence.journals[ctx.scope.attempt_id]['requests']
   self.assertEqual(len(requests),96);self.assertEqual(next(r for r in requests if r['stage']=='scratch_cleanup')['completion'],'completed')
 async def test_capacity_rejection_precedes_scratch_creation(self):
  from taskweave_wordpress.transport import SiteTransport,WriteEvidence
  from unittest.mock import patch
  from taskweave.plugins.sdk import PluginError
  ctx=TestContext();evidence=WriteEvidence()
  with tempfile.TemporaryDirectory() as directory:
   site=SiteTransport({'site_path':directory},evidence);await site.open(ctx);site.start(ctx,'backup','default',{})
   for _ in range(96):evidence.dispatch(ctx,'backup','default','prior_business')['completion']='completed'
   with patch('taskweave_wordpress.transport.tempfile.mkdtemp') as mkdir:
    with self.assertRaises(PluginError):
     await site.scratch(ctx)
    mkdir.assert_not_called()
 async def test_cancellation_before_finally_still_removes_reserved_scratch(self):
  from taskweave_wordpress.transport import SiteTransport,WriteEvidence
  import asyncio
  ctx=TestContext();evidence=WriteEvidence()
  with tempfile.TemporaryDirectory() as directory:
   site=SiteTransport({'site_path':directory},evidence);await site.open(ctx);site.start(ctx,'backup','default',{})
   path=await site.scratch(ctx)
   await site.write(path,b'private sql');parent=Path(path).parent;ready=asyncio.Event()
   while len(evidence.journals[ctx.scope.attempt_id]['requests'])<96:evidence.dispatch(ctx,'backup','default','prior_business')['completion']='completed'
   async def action():
    try:ready.set();await asyncio.Future()
    finally:await site.cleanup_scratch(ctx,path)
   task=asyncio.create_task(action());await ready.wait();task.cancel()
   with self.assertRaises(asyncio.CancelledError):await task
   self.assertFalse(parent.exists());self.assertEqual(next(r for r in evidence.journals[ctx.scope.attempt_id]['requests'] if r['stage']=='scratch_cleanup')['completion'],'completed')

class CapacityDispatchRound2Tests(unittest.IsolatedAsyncioTestCase):
 async def test_native_dispatch_refusal_still_deletes_precreated_scratch(self):
  from taskweave_wordpress.transport import SiteTransport,WriteEvidence
  from taskweave_wordpress.backup import export_sql
  from taskweave.plugins.sdk import PluginError
  from unittest.mock import patch,AsyncMock
  ctx=TestContext();evidence=WriteEvidence()
  with tempfile.TemporaryDirectory() as directory:
   site=SiteTransport({'site_path':directory},evidence);await site.open(ctx);site.start(ctx,'backup','default',{})
   for _ in range(95):evidence.dispatch(ctx,'backup','default','prior_business')['completion']='completed'
   with patch('taskweave_wordpress.transport.run_command',new_callable=AsyncMock) as run:
    with self.assertRaises(PluginError) as error:await export_sql(ctx,site,['tw_posts'],1024)
    self.assertEqual(error.exception.code,'WORDPRESS_DIAGNOSTIC_CAPACITY');run.assert_not_awaited()
   self.assertFalse(site.scratch_files);requests=evidence.journals[ctx.scope.attempt_id]['requests']
   self.assertEqual(len(requests),96);self.assertEqual(requests[-1]['stage'],'scratch_cleanup');self.assertEqual(requests[-1]['completion'],'completed')


class FinalCanonicalSourceTests(unittest.IsolatedAsyncioTestCase):
 async def test_local_and_ssh_source_canonical_bytes_and_inputs_unchanged(self):
  import tempfile,json,sys,os
  from pathlib import Path
  from unittest.mock import patch
  from taskweave_wordpress.actions import perform
  from taskweave_wordpress.transport import SiteTransport
  from taskweave_process import run_command
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory).resolve();site_root=root/'site';site_root.mkdir();(root/'imports').mkdir();(site_root/'imports').mkdir()
   source=root/'imports/archive.zip';source.write_bytes(b'CHECKED_ROOT_BYTES')
   outside=root/'outside';outside.write_bytes(b'UNCHECKED_SITE_BYTES');(site_root/'imports/archive.zip').symlink_to(outside)
   flagged=root/'-archive.zip';flagged.write_bytes(b'CHECKED_FLAG_BYTES')
   receipt=root/'native.json';cli=root/'wp-cli'
   cli.write_text('#!'+sys.executable+'\nimport json,sys,os\nfrom pathlib import Path\ns=sys.argv[5]\nPath('+repr(str(receipt))+').write_text(json.dumps({"cwd":os.getcwd(),"source":s,"bytes":None if s.startswith("https://") else Path(s).read_text()}))\nprint("7" if sys.argv[3]=="media" else "installed")\n');cli.chmod(0o700)
   ctx=TestContext()
   class SSH:
    async def resolve_path(self,path,**kwargs):
     result=(root/path).resolve(strict=True);result.relative_to(root);return str(result)
    async def run(self,ctx,argv,**kwargs):return await run_command(ctx,argv[0],argv[1:],**kwargs)
   for mode in ('local','ssh'):
    site=SiteTransport({'site_path':str(site_root),'local_root':str(root),'wp_path':str(cli)});await site.open(ctx)
    if mode=='ssh':site.session=SSH()
    for name,raw in [('install_theme','imports/archive.zip'),('install_plugin','imports/archive.zip'),('import_media','imports/archive.zip'),('import_media',str(source)),('install_plugin','-archive.zip'),('import_media','https://example.test/photo.jpg')]:
     inputs={'source':raw,**({'slug':'fixture'} if name!='import_media' else {})};before=dict(inputs)
     site.start(ctx,name,'default',inputs)
     with patch('taskweave_wordpress.actions.installed',return_value=True),patch('taskweave_wordpress.actions.inventory',side_effect=[[],[{'name':'fixture','status':'inactive','version':'1'}]]),patch('taskweave_wordpress.actions.entity',return_value={'ID':7}):
      await perform(ctx,site,name,inputs)
     actual=json.loads(receipt.read_text());self.assertEqual(inputs,before)
     expected=raw if raw.startswith('https://') else str((root/raw).resolve())
     self.assertEqual(actual['source'],expected,(mode,name));self.assertEqual(actual['cwd'],str(site_root))
     if not raw.startswith('https://'):self.assertEqual(actual['bytes'],Path(expected).read_text());self.assertNotEqual(actual['bytes'],'UNCHECKED_SITE_BYTES')
