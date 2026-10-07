"""Explicit real PHP/WP/database integration. Set TW_WORDPRESS_INTEGRATION_CONFIG.

Run inside owned tool-equipped container for local; host for trusted SSH.
No tools/containers/dependencies are installed by these tests.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import unittest
from tests.fixtures.wordpress_site import WordPressContext

@unittest.skipUnless(os.getenv('TW_WORDPRESS_INTEGRATION_CONFIG'),'explicit real WordPress configuration required')
class WordPressIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().set_debug(False)
        self.spec=json.loads(Path(os.environ['TW_WORDPRESS_INTEGRATION_CONFIG']).read_text())
        secrets=json.loads(Path(self.spec['secrets_file']).read_text())
        self.fixture=WordPressContext(self.spec['environment'],secrets)
        self.action=self.fixture.action
    async def asyncTearDown(self): await self.fixture.close()
    async def test_all_business_groups(self):
        report=[]
        prefix=self.spec.get('prefix','tw_')
        site_path=self.spec['environment']['wordpress_site_path']
        async def call(action_id,**inputs):
            try: value=await self.action(action_id,timeout_seconds=180,max_output_bytes=1048576,**inputs)
            except Exception:
                receipts=await self.fixture.plugin.failure_results(self.fixture.ctx,None)
                print(json.dumps({'failed_action':action_id,'bounded_safe_diagnostic':receipts[0].payload.get('last_command') if receipts else None}))
                raise
            report.append({'action':action_id,'completion':value['completion']});return value
        await call('check_environment')
        # Config/core installation are real; CLI handles pre-install DB checks.
        await call('config_create',dbname='wordpress_fixture',dbuser='tw_fixture',dbhost='tw-wp-db-01a0fc57',dbprefix=prefix,db_password_ref='db')
        await call('is_installed')
        await call('core_install',url='http://wordpress-fixture.test',title='TaskWeave fixture',admin_user='owner',admin_email='owner@fixture.test',admin_password_ref='admin')
        await call('core_install',url='http://wordpress-fixture.test',title='TaskWeave fixture',admin_user='owner',admin_email='owner@fixture.test',admin_password_ref='admin')
        await call('core_update',version='7.1.2')
        await call('verify_checksums')
        await call('config_set',name='TASKWEAVE_FIXTURE',value='literal;$(noexec)')
        self.assertEqual((await call('config_get',name='TASKWEAVE_FIXTURE'))['result'],'literal;$(noexec)')
        await call('config_set',name='DB_PASSWORD',value_ref='db')
        await call('option_set',key='taskweave_fixture',value={'kind':'real','value':1})
        self.assertEqual((await call('option_get',key='taskweave_fixture'))['result'],{'kind':'real','value':1})
        await call('set_permalink_structure',structure='/%postname%/')
        await call('list_themes')
        await call('install_theme',slug='twentytwentyfive')
        await call('activate_theme',slug='twentytwentyfive')
        await call('update_theme',slug='twentytwentyfive')
        await call('install_theme',slug='twentytwentyfour')
        await call('delete_theme',slug='twentytwentyfour')
        await call('list_plugins')
        await call('install_plugin',slug='hello-dolly',source=site_path+'/fixture-hello-dolly.zip')
        await call('activate_plugin',slug='hello-dolly')
        await call('update_plugin',slug='hello-dolly')
        await call('deactivate_plugin',slug='hello-dolly')
        await call('delete_plugin',slug='hello-dolly')
        await call('list_posts',post_type='page',limit=2)
        post=(await call('create_post',post_type='page',title='Fixture page',status='draft',content='old-fixture-marker'))['result']['id']
        await call('update_post',id=post,post_type='page',title='Updated page',content='old-fixture-marker new content')
        await call('list_terms',taxonomy='category')
        term=(await call('create_term',taxonomy='category',name='Fixture category'))['result']['term_id']
        await call('update_term',taxonomy='category',id=int(term),name='Updated category')
        await call('list_menus')
        menu=int((await call('create_menu',name='Fixture menu'))['result']['term_id'])
        custom=int((await call('add_menu_item',menu=menu,kind='custom',title='Fixture link',link='https://example.test'))['result']['db_id'])
        await call('add_menu_item',menu=menu,kind='post',post_id=post)
        await call('add_menu_item',menu=menu,kind='term',taxonomy='category',term_id=int(term))
        await call('update_menu_item',menu=menu,id=custom,title='Updated link',parent_id=0)
        await call('delete_menu_item',menu=menu,id=custom)
        await call('delete_menu',menu=menu)
        await call('list_media',limit=2)
        media=(await call('import_media',source=self.spec['media_path'],title='Fixture image',caption='caption',description='description',alt='alt'))['result']['id']
        await call('update_media',id=media,title='Updated image',caption='updated caption',description='updated description',alt='updated alt')
        await call('delete_media',id=media)
        await call('list_users',limit=2)
        user=(await call('create_user',login='fixture_user',email='fixture@site.test',user_role='subscriber',password_ref='user'))['result']['id']
        await call('set_user_role',id=user,user_role='editor')
        await call('set_user_password',id=user,password_ref='user',skip_email=True)
        await call('delete_user',id=user,reassign=1)
        await call('search_replace',old='old-fixture-marker',new='changed-fixture-marker',tables=[prefix+'posts'])
        preview=await call('search_replace',old='old-fixture-marker',new='changed-fixture-marker',tables=[prefix+'posts'])
        await call('search_replace',old='old-fixture-marker',new='changed-fixture-marker',tables=[prefix+'posts'],dry_run=False,preview_token=preview['result']['preview_token'])
        await call('cache_flush',exclusive_cache=True)
        await call('set_maintenance_mode',enabled=True)
        await call('set_maintenance_mode',enabled=False)
        await call('delete_term',taxonomy='category',id=int(term))
        await call('delete_post',id=post,post_type='page',force=True)
        # Complete archive acceptance runs separately with all owned tables.
        await self.fixture.plugin.collect_context('wordpress.site',self.fixture.ctx,{'limit':2})
        print(json.dumps({'mode':self.spec['environment'].get('wordpress_mode','local'),'business_actions':report}))

    async def test_complete_files_and_sql_backup_restore(self):
        from taskweave.core.ports import ResultRequest,StepResult
        from taskweave_wordpress.backup import validate_archive
        site=await self.fixture.ctx.resources.acquire('wordpress.site','default')
        tables=self.spec['environment']['wordpress_owned_tables']
        await self.action('option_set',key='taskweave_restore_probe',value='before')
        hidden=str(site.site)+'/.taskweave-hidden-proof'
        await site.write(hidden,b'complete hidden file',0o600)
        empty=str(site.site)+'/.taskweave-empty-proof'
        await site.mkdir(empty,0o700)
        source=str(site.site)+'/license.txt'
        original=await site.read(source,67108864)
        baseline={name:hashlib.sha256(pair[0]).hexdigest() for name,pair in (await site.files(268435456,10000)).items()}
        backup=await self.action('backup',tables=tables,max_bytes=67108864,max_unpacked_bytes=268435456,max_members=10000,timeout_seconds=600,max_output_bytes=1048576)
        staged=self.fixture.results.tokens[backup['artifact']['token']]
        raw=staged.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),backup['artifact']['checksum'])
        import tarfile,io
        with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as archive:
            manifest=json.load(archive.extractfile('manifest.json'))
        self.assertEqual({name:item['sha256'] for name,item in manifest['files'].items()},baseline)
        self.assertGreater(len(manifest['files']),3500)
        self.assertIn('.taskweave-hidden-proof',manifest['files'])
        validate_archive(raw,manifest['identity'],tables,max_bytes=67108864,max_unpacked_bytes=268435456,max_members=10000)
        self.fixture.results.persist(StepResult(outputs=[ResultRequest('wordpress.file','complete_backup',backup['artifact'])]))
        package=str(site.site)+'/taskweave-restore-package.tar.gz'
        await site.write(package,raw)
        await site.write(source,original+b'\nchanged fixture core file\n')
        await site.write(hidden,b'changed hidden file')
        await site.mkdir(empty,0o755)
        await self.action('option_set',key='taskweave_restore_probe',value='after')
        restored=await self.action('restore',path=package,checksum=hashlib.sha256(raw).hexdigest(),tables=tables,max_bytes=67108864,max_unpacked_bytes=268435456,max_members=10000,timeout_seconds=600,max_output_bytes=1048576)
        self.assertEqual(restored['completion'],'completed')
        self.assertEqual(await site.read(source,67108864),original)
        self.assertEqual(await site.read(hidden,67108864),b'complete hidden file')
        actual_mode=(await site.session.sftp.stat(empty)).permissions if site.session else Path(empty).stat().st_mode
        self.assertEqual(actual_mode&0o777,0o700)
        self.assertEqual((await self.action('option_get',key='taskweave_restore_probe'))['result'],'before')
        await site.delete(package)
        print(json.dumps({'mode':self.spec['environment'].get('wordpress_mode','local'),'complete_backup_files':len(manifest['files']),'expanded_file_bytes':sum(item['size'] for item in manifest['files'].values()),'archive_bytes':len(raw),'archive_sha256':hashlib.sha256(raw).hexdigest(),'sql_tables':tables,'file_and_database_restore_verified':True,'artifact_persisted':True}))

    async def test_core_download_without_config_or_database(self):
        download=self.spec.get('download_path','/download')
        environment=dict(self.spec['environment']);environment['wordpress_site_path']=download;environment['wordpress_local_root']=download
        if environment.get('wordpress_mode')=='ssh': environment['wordpress_ssh']={**environment['wordpress_ssh'],'remote_root':download}
        fixture=WordPressContext(environment,json.loads(Path(self.spec['secrets_file']).read_text()))
        try:
            result=await fixture.action('core_download',version='7.1.2',locale='en_US',timeout_seconds=180,max_output_bytes=1048576)
            self.assertEqual(result['result']['version'],'7.1.2')
            site=await fixture.ctx.resources.acquire('wordpress.site','default')
            files=await site.files(268435456,10000)
            self.assertGreater(len(files),3700)
            print(json.dumps({'mode':environment.get('wordpress_mode','local'),'core_download_files':len(files),'core_download_before_config':True}))
        finally: await fixture.close()

    async def test_database_export_and_import(self):
        import uuid
        tables=self.spec['environment']['wordpress_owned_tables']
        site=await self.fixture.ctx.resources.acquire('wordpress.site','default')
        path=str(site.site)+'/.taskweave-db-action-'+uuid.uuid4().hex+'.sql'
        await self.action('option_set',key='taskweave_db_action_probe',value='before')
        exported=await self.action('db_export',path=path,tables=tables,max_bytes=67108864,timeout_seconds=180)
        await self.action('option_set',key='taskweave_db_action_probe',value='after')
        imported=await self.action('db_import',path=path,tables=tables,checksum=exported['result']['sha256'],max_bytes=67108864,timeout_seconds=180)
        self.assertEqual(imported['completion'],'completed')
        self.assertEqual((await self.action('option_get',key='taskweave_db_action_probe'))['result'],'before')
        await site.delete(path)
        print(json.dumps({'mode':self.spec['environment'].get('wordpress_mode','local'),'db_export_import_restored_data':True,'sha256':exported['result']['sha256']}))

    async def test_actual_worker_partial_restore_is_durable(self):
        from taskweave.application.service import Application
        from taskweave.infrastructure.storage import uid
        from taskweave.plugins.registry import Registry
        from taskweave_wordpress import WordPressPlugin
        from tempfile import TemporaryDirectory
        import threading
        site=await self.fixture.ctx.resources.acquire('wordpress.site','default')
        # Capture complete real files+SQL, then provoke failure on the second
        # lexically sorted regular file without changing any user target.
        first=str(site.site)+'/000-taskweave-first-proof'
        second=str(site.site)+'/001-taskweave-denied-proof'
        await site.write(first,b'before-first',0o600);await site.write(second,b'before-second',0o600)
        tables=self.spec['environment']['wordpress_owned_tables']
        backup=await self.action('backup',tables=tables,max_bytes=67108864,timeout_seconds=600,max_output_bytes=1048576)
        raw=self.fixture.results.tokens[backup['artifact']['token']].read_bytes()
        import io,tarfile
        with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as archive:
            manifest=json.load(archive.extractfile('manifest.json'))
        expected_completed=sorted(manifest['files']).index('001-taskweave-denied-proof')
        package=str(site.site)+'/taskweave-worker-restore-package.tar.gz'
        await site.write(package,raw)
        await site.write(first,b'after-first');await site.write(second,b'after-second',0o444)
        def worker():
            with TemporaryDirectory(prefix='taskweave-wp-real-worker-') as home,Application(home,registry_factory='tests.fixtures.wordpress_site:worker_registry') as app:
                environment=app.repo.save_environment('owned real WordPress fixture',self.spec['environment'],dict(self.fixture.ctx.secret_refs))['environment_id']
                task=app.repo.create_task('real partial WordPress restoration')['task_id']
                inputs={'path':package,'checksum':hashlib.sha256(raw).hexdigest(),'tables':tables,'max_bytes':67108864,'timeout_seconds':180,'max_output_bytes':1048576}
                content='async def run(ctx, inputs):\n    await ctx.call("wordpress.restore", '+repr(inputs)+')\n    return ctx.result(data={"unexpected_success": True})'
                step=app.repo.save_step(task,{'name':'owned partial restore','capabilities':['wordpress.restore'],'step_content':content})
                app.confirm_step_manual(step['step_id'],step['content_hash'],environment_id=environment)
                created=app.create_run(task,environment_id=environment);app.coordinator.start(created['run_id'],uid())
                finished=app.coordinator.wait(created['run_id'],60)
                self.assertEqual(finished['status'],'FAILED',finished)
                attempt=finished['attempts'][0];self.assertEqual(attempt['effect_state'],'UNKNOWN')
                refs=app.repo.repositories.results.refs_for_attempt(attempt['attempt_id']);self.assertEqual(len(refs),1)
                payload=app.repo.read_result(refs[0]['result_id'],Registry([WordPressPlugin()]))['data']
                receipt=next(item for item in payload['requests'] if item['stage']=='files_overlay')
                self.assertEqual(receipt['completion'],'partial');self.assertEqual(receipt['completed_files'],expected_completed)
                self.assertIn('pending_file_sha256',receipt)
                self.assertNotIn('database_import',[item['stage'] for item in payload['requests']])
                return {'status':finished['status'],'effect_state':attempt['effect_state'],'completed_files':receipt['completed_files'],'completed_directories':receipt['completed_directories'],'durable_receipt':True}
        try:
            state=await asyncio.to_thread(worker)
            self.assertEqual(await site.read(first,1024),b'before-first')
            self.assertEqual(await site.read(second,1024),b'after-second')
            print(json.dumps({'mode':self.spec['environment'].get('wordpress_mode','local'),'actual_worker_partial_restore':state}))
        finally:
            if site.session: await site.session.sftp.chmod(second,0o600)
            else: Path(second).chmod(0o600)
            for path in (first,second,package): await site.delete(path)
