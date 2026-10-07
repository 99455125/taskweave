"""Real loopback SSH/SFTP and durable host failures, no production host."""
import asyncio
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from taskweave.core.ports import Scope, ResultRequest, StepResult
from taskweave.core.validation import TaskError, validate
from taskweave.infrastructure.storage import Results, uid, connect
from taskweave.infrastructure.worker import PluginContext, Resources
from taskweave.plugins.registry import Registry
from taskweave_ssh import SshPlugin, connect_ssh, SshError
from tests.fixtures.ssh_server import SshServer


class SshTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.server = await SshServer(self.root).start()
        self.plugin = SshPlugin()
        self.registry = Registry([self.plugin])
        self.results = Results(self.root/'host', Scope(uid(),uid(),uid(),uid()), self.registry)
        self.resources = Resources(self.registry)
        self.cancel = threading.Event()
        self.ctx = PluginContext(self.results.scope,self.results,self.resources,
            {'ssh_'+k:v for k,v in self.server.config().items()} | {'ssh_local_root':str(self.root)},
            {'password':'env:TW_SSH_PASSWORD','passphrase':'env:TW_SSH_PASSPHRASE','secret':'env:TW_SSH_SECRET'},
            self.cancel,lambda *args: None)
        self.resources.context = self.ctx
        self.env = patch.dict(os.environ, {'TW_SSH_PASSWORD':'test-password','TW_SSH_PASSPHRASE':'key-password','TW_SSH_SECRET':'special-secret-value'})
        self.env.start()
        self.sessions = []

    async def asyncTearDown(self):
        await self.resources.release_all()
        for session in self.sessions:
            await session.close()
        await self.server.close()
        self.env.stop()
        self.temp.cleanup()

    async def connect(self, **overrides):
        session = await connect_ssh(self.ctx, self.server.config() | overrides)
        self.sessions.append(session)
        return session

    async def action(self, name, **inputs):
        action = self.plugin.actions()['ssh.'+name]
        validate(inputs, action.spec.input_schema)
        output = await action.execute(self.ctx,inputs)
        validate(output,action.spec.output_schema)
        return output

    async def test_password_key_agent_and_host_identity(self):
        session = await self.connect()
        self.assertEqual((await self.action('check_connection'))['server_version'].split('-')[0], 'SSH')
        key_session = await self.connect(password_ref=None,key_path=str(self.server.key_path),key_passphrase_ref='passphrase')
        self.assertEqual((await key_session.run(self.ctx,[sys.executable,'-c','print("key ok")'],cwd='.',env={},stdin=None))['stdout'],'key ok\n')
        wrong = self.root/'wrong_hosts'
        import asyncssh
        wrong.write_bytes(f'[127.0.0.1]:{self.server.port} '.encode()+asyncssh.generate_private_key('ssh-ed25519').export_public_key())
        before=len(self.server.commands)
        with self.assertRaises(SshError) as raised:
            await self.connect(known_hosts=str(wrong))
        self.assertEqual(raised.exception.code,'SSH_HOST_KEY_INVALID')
        self.assertEqual(len(self.server.commands),before)
        with self.assertRaises(SshError):
            await self.connect(known_hosts=None)
        with patch.dict(os.environ, {'TW_SSH_PASSWORD':'wrong'}), self.assertRaises(SshError) as raised:
            await self.connect()
        self.assertEqual(raised.exception.code,'SSH_AUTH_FAILED')
        # Real OpenSSH agent socket, no automatic key discovery or forwarding.
        agent_key = self.root/'agent-key'
        agent_key.write_bytes(self.server.client_key.export_private_key('openssh'))
        agent_key.chmod(0o600)
        socket=self.root/'agent.sock'
        agent=await asyncio.create_subprocess_exec('/usr/bin/ssh-agent','-D','-a',str(socket),stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
        try:
            for _ in range(100):
                if socket.exists(): break
                await asyncio.sleep(.01)
            add=await asyncio.create_subprocess_exec('/usr/bin/ssh-add',str(agent_key),env=os.environ | {'SSH_AUTH_SOCK':str(socket)},stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
            self.assertEqual(await add.wait(),0)
            agent_session=await self.connect(password_ref=None,use_agent=True,agent_path=str(socket))
            self.assertEqual((await agent_session.run(self.ctx,[sys.executable,'-c','print("agent ok")'],cwd='.',env={},stdin=None))['stdout'],'agent ok\n')
        finally:
            agent.terminate(); await agent.wait()

    async def test_exec_quotes_argv_cwd_env(self):
        sub=self.root/'dir spaces; quote\''; sub.mkdir()
        args=['a b',"x'y",';touch injection','$(touch injection)','line\nnext']
        result=await self.action('exec',argv=[sys.executable,'-c','import os,sys,json; print(json.dumps([sys.argv[1:],os.getcwd(),os.getenv("VALUE")])); print(sys.stdin.read())',*args],cwd=sub.name,env={'VALUE':"v';touch injection"},stdin='input value')
        self.assertEqual(json.loads(result['stdout'].splitlines()[0]),[args,str(sub),"v';touch injection"])
        self.assertEqual(result['stdout'].splitlines()[1],'input value')
        self.assertFalse((sub/'injection').exists())
        result=await self.action('run_script',script='printf explicit; exit 7')
        self.assertEqual((result['exit_code'],result['stdout']),(7,'explicit'))

    async def test_bounded_streams_and_secret_refs(self):
        result=await self.action('exec',argv=[sys.executable,'-c','import os,sys; print(os.getenv("TOKEN")); print(sys.stdin.read()); print("界"*2000); print("x"*9000,file=sys.stderr)'],env_secret_refs={'TOKEN':'secret'},stdin_secret_ref='secret',max_output_bytes=1024)
        self.assertNotIn('special-secret-value',json.dumps(result))
        self.assertIn('[REDACTED]',result['stdout'])
        for stream in ('stdout','stderr'):
            self.assertLessEqual(len(result[stream].encode()),1024)
            self.assertTrue(result[stream+'_truncated'])
        before=len(self.server.commands)
        with self.assertRaises(TaskError):
            await self.action('exec',argv=['echo','bad'],env_secret_refs={'TOKEN':'missing'})
        self.assertEqual(len(self.server.commands),before)

    async def test_command_cancel_timeout_and_durable_failure(self):
        for cancel in (False,True):
            self.cancel.clear()
            task=asyncio.create_task(self.action('exec',argv=[sys.executable,'-u','-c','import time; print("partial success"); time.sleep(5)'],timeout_seconds=1))
            if cancel:
                await asyncio.sleep(.15); self.cancel.set()
            with self.assertRaises(SshError) as raised:
                await task
            self.assertEqual(raised.exception.code,'CANCELLED' if cancel else 'SSH_COMMAND_TIMEOUT')
            self.assertEqual(raised.exception.effect_state,'UNKNOWN')
            self.assertIn('partial success',raised.exception.result['stdout'])
            requests=await self.plugin.failure_results(self.ctx,raised.exception)
            self.assertEqual(len(requests),1)
            self.assertEqual(requests[0].handler_id,'ssh.command_failure')
            saved=self.results.persist_diagnostics(requests)
            with connect(self.results.path) as db:
                stored=json.loads(db.execute('SELECT payload_json FROM step_outputs WHERE attempt_id=? AND name=?',(self.results.scope.attempt_id,requests[0].name)).fetchone()[0])
            self.assertIn('partial success',stored['result']['stdout'])
            await self.resources.release_all()
            self.ctx.scope=replace(self.ctx.scope,attempt_id=uid())
            self.results.scope=self.ctx.scope
        self.ctx.scope=replace(self.ctx.scope,attempt_id=uid())
        self.assertEqual(await self.plugin.failure_results(self.ctx,raised.exception),[])

    async def test_cancel_before_start_and_external_cancel(self):
        self.cancel.set()
        with self.assertRaises(TaskError): await self.action('exec',argv=['touch','probe'])
        self.assertFalse(self.server.commands)
        self.cancel.clear()
        task=asyncio.create_task(self.action('exec',argv=[sys.executable,'-u','-c','import time; print("safe partial"); time.sleep(5)']))
        await asyncio.sleep(.15); task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        request=(await self.plugin.failure_results(self.ctx,None))[0]
        self.assertIn('safe partial',request.payload['result']['stdout'])

    async def test_read_stat_list_logs_checksum_download(self):
        (self.root/'data.txt').write_bytes(b'alpha\nbeta\n')
        self.assertEqual((await self.action('read_file',path='data.txt'))['content'],'alpha\nbeta\n')
        self.assertEqual((await self.action('stat',path='data.txt'))['size_bytes'],11)
        listing=await self.action('list_directory',path='.',max_entries=1)
        self.assertEqual(len(listing['entries']),1); self.assertTrue(listing['truncated'])
        logs=await self.action('read_logs',path='data.txt',max_bytes=6)
        self.assertEqual((logs['content'],logs['cursor'],logs['truncated']),('alpha\n',6,True))
        self.assertEqual((await self.action('read_logs',path='data.txt',cursor=6,max_bytes=6))['content'],'beta\n')
        self.assertEqual((await self.action('checksum',path='data.txt'))['checksum'],hashlib.sha256(b'alpha\nbeta\n').hexdigest())
        download=await self.action('download',remote_path='data.txt')
        ref=self.results.persist(StepResult(outputs=[ResultRequest('ssh.file','download',download['artifact'])]))[0]
        self.assertEqual((self.results.root/ref['locator']).read_bytes(),b'alpha\nbeta\n')
        with self.assertRaises(SshError): await self.action('read_file',path='data.txt',max_bytes=2)

    async def test_upload_mkdir_move_remove_and_checksum(self):
        (self.root/'local.txt').write_bytes(b'upload bytes')
        await self.action('mkdir',path='dest')
        upload=await self.action('upload',local_path='local.txt',remote_path='dest/file.txt')
        self.assertEqual(upload['checksum'],hashlib.sha256(b'upload bytes').hexdigest())
        self.assertEqual((self.root/'dest/file.txt').read_bytes(),b'upload bytes')
        with self.assertRaises(SshError): await self.action('upload',local_path='local.txt',remote_path='dest/file.txt')
        (self.root/'dest/existing').write_bytes(b'keep')
        with self.assertRaises(SshError): await self.action('move',source='dest/file.txt',destination='dest/existing')
        self.assertEqual((self.root/'dest/existing').read_bytes(),b'keep')
        await self.action('move',source='dest/file.txt',destination='dest/moved')
        await self.action('remove',path='dest/moved')
        with self.assertRaises(SshError): await self.action('remove',path='dest')
        await self.action('remove',path='dest',recursive=True)
        self.assertFalse((self.root/'dest').exists())
        with self.assertRaises(SshError): await self.action('upload',local_path='local.txt',remote_path='wrong',checksum='0'*64)
        self.assertFalse((self.root/'wrong').exists())
        self.assertFalse(list(self.root.glob('.taskweave-*')))

    async def test_path_symlink_escape_and_root_remove(self):
        with tempfile.TemporaryDirectory() as outside:
            (Path(outside)/'private').write_text('secret')
            (self.root/'escape').symlink_to(outside,target_is_directory=True)
            for action,inputs in [('read_file',{'path':'escape/private'}),('mkdir',{'path':'escape/new'}),('stat',{'path':outside}),('remove',{'path':'.','recursive':True})]:
                with self.subTest(action=action), self.assertRaises(SshError): await self.action(action,**inputs)
        with self.assertRaises(SshError): await self.action('exec',argv=['echo','bad'],env={'BAD=NAME':'value'})

    async def test_target_appearing_after_precheck_is_not_overwritten(self):
        (self.root/'local').write_bytes(b'ours')
        self.server.race_destination='race'
        with self.assertRaises(SshError): await self.action('upload',local_path='local',remote_path='race')
        self.assertEqual((self.root/'race').read_bytes(),b'concurrent target')
        self.assertFalse(list(self.root.glob('.taskweave-*')))

    async def test_transfer_cancel_preserves_progress_and_context_budget(self):
        (self.root/'large').write_bytes(b'x'*200000)
        self.server.delay_write=.2
        task=asyncio.create_task(self.action('upload',local_path='large',remote_path='cancelled'))
        await asyncio.sleep(.25); self.cancel.set()
        with self.assertRaises(SshError) as raised: await task
        self.assertEqual(raised.exception.effect_state,'UNKNOWN')
        requests=await self.plugin.failure_results(self.ctx,raised.exception)
        self.assertEqual(requests[0].handler_id,'ssh.transfer_failure')
        self.assertGreater(requests[0].payload['result']['bytes_transferred'],0)
        self.results.persist_diagnostics(requests)
        self.assertFalse((self.root/'cancelled').exists())
        self.assertFalse(list(self.root.glob('.taskweave-*')))
        self.cancel.clear()
        for index in range(10): (self.root/('界'*60+str(index))).write_text('')
        capture=await self.plugin.collect_context('ssh.server',self.ctx,{'max_output_bytes':1024})
        self.assertLessEqual(len(capture.items[0].content.encode()),1024)
        self.assertNotIn('test-password',capture.items[0].content)
        self.assertEqual(len(self.server.commands),0)

    async def test_recursive_removal_unlinks_in_root_symlink_without_deleting_target(self):
        (self.root/'kept').write_text('kept data')
        (self.root/'tree').mkdir()
        (self.root/'tree/link').symlink_to(self.root/'kept')
        await self.action('remove',path='tree',recursive=True)
        self.assertEqual((self.root/'kept').read_text(),'kept data')
        self.assertFalse((self.root/'tree').exists())

    async def test_transfer_timeout_and_external_cancel_preserve_evidence(self):
        (self.root/'big').write_bytes(b'x'*100000)
        self.server.delay_write=.2
        for external in (False,True):
            await self.resources.release_all()
            task=asyncio.create_task(self.action('upload',local_path='big',remote_path='partial',timeout_seconds=1))
            if external:
                await asyncio.sleep(.25); task.cancel()
                with self.assertRaises(asyncio.CancelledError): await task
            else:
                self.server.delay_write=.4
                with self.assertRaises(SshError) as raised: await task
                self.assertEqual(raised.exception.code,'SSH_OPERATION_TIMEOUT')
            requests=await self.plugin.failure_results(self.ctx,None)
            self.assertEqual(len(requests),1)
            self.assertEqual(requests[0].payload['effect_state'],'UNKNOWN')
            self.assertFalse((self.root/'partial').exists())
            self.assertFalse(list(self.root.glob('.taskweave-*')))

    async def test_unknown_fields_limits_and_no_overwrite_business_input(self):
        for action,inputs in [('exec',{'argv':['echo'],'unexpected':1}),('exec',{'argv':['echo'],'max_output_bytes':0}),('read_file',{'path':'x','max_bytes':0}),('remove',{'path':'.','recursive':'yes'})]:
            with self.subTest(action=action),self.assertRaises(TaskError): await self.action(action,**inputs)
        self.assertFalse(self.server.commands)
        (self.root/'source').write_bytes(b'new')
        (self.root/'target').write_bytes(b'old')
        await self.action('upload',local_path='source',remote_path='target',overwrite=True)
        self.assertEqual((self.root/'target').read_bytes(),b'new')
        (self.root/'source2').write_bytes(b'moved')
        await self.action('move',source='source2',destination='target',overwrite=True)
        self.assertEqual((self.root/'target').read_bytes(),b'moved')
        (self.root/'binary').write_bytes(b'\xff\x00')
        self.assertEqual((await self.action('read_file',path='binary',encoding='base64'))['content'],'/wA=')
        with self.assertRaises(SshError): await self.action('read_file',path='binary')
        self.assertTrue((await self.action('read_logs',path='binary',cursor=100))['rotated'])

    async def test_real_worker_timeout_saves_redacted_partial_diagnostics(self):
        await self._worker_failure(cancel=False)

    async def test_real_worker_cancel_saves_redacted_partial_diagnostics(self):
        await self._worker_failure(cancel=True)

    async def _worker_failure(self,*,cancel):
        from taskweave.application.service import Application
        def run():
            with tempfile.TemporaryDirectory() as home, Application(home) as app:
                app.configure_plugin('ssh',True)
                env=app.repo.save_environment('SSH evidence',dict(self.ctx.environment),dict(self.ctx.secret_refs))['environment_id']
                task=app.repo.create_task('SSH evidence')['task_id']
                code='import os,sys,time; from pathlib import Path; print("partial success "+os.getenv("TOKEN"),flush=True); print("partial stderr",file=sys.stderr,flush=True); print("x"*9000,flush=True); Path("started").touch(); time.sleep(20)'
                inputs={'argv':[sys.executable,'-c',code], 'env_secret_refs':{'TOKEN':'secret'}, 'timeout_seconds':60 if cancel else 1,'max_output_bytes':1024}
                step=app.repo.save_step(task,{'name':'partial SSH command','capabilities':['ssh.exec'],
                    'step_content':'async def run(ctx, inputs):\n'+f'    command = await ctx.call("ssh.exec", {inputs!r})\n'+'    return ctx.result(data=command)'})
                app.confirm_step_manual(step['step_id'],step['content_hash'],environment_id=env)
                run=app.create_run(task,environment_id=env)
                app.coordinator.start(run['run_id'],uid())
                if cancel:
                    import time
                    deadline=time.monotonic()+5
                    while not (self.root/'started').exists() and time.monotonic()<deadline: time.sleep(.01)
                    self.assertTrue((self.root/'started').exists())
                    app.coordinator.control(run['run_id'],uid(),'cancel')
                finished=app.coordinator.wait(run['run_id'],8)
                self.assertEqual(finished['status'],'FAILED',finished)
                attempt=finished['attempts'][0]
                self.assertEqual(attempt['effect_state'],'UNKNOWN')
                self.assertEqual(attempt['error_code'],'CANCELLED' if cancel else 'SSH_COMMAND_TIMEOUT')
                refs=app.repo.repositories.results.refs_for_attempt(attempt['attempt_id'])
                self.assertEqual(len(refs),1)
                self.assertEqual(refs[0]['handler_id'],'ssh.command_failure')
                stored=app.repo.read_result(refs[0]['result_id'],Registry([SshPlugin()]))['data']
                self.assertIn('partial success',stored['result']['stdout'])
                self.assertIn('partial stderr',stored['result']['stderr'])
                self.assertIn('[REDACTED]',stored['result']['stdout'])
                self.assertNotIn('special-secret-value',json.dumps(stored))
                self.assertTrue(stored['result']['stdout_truncated'])
                with self.assertRaisesRegex(TaskError,'OUTPUT_NOT_AVAILABLE'): app.repo.read_output(run['run_id'],step['step_id'])
        await asyncio.to_thread(run)

    async def test_connect_timeout_and_agent_disabled_fail_closed(self):
        writers=[]
        async def stall(reader,writer): writers.append(writer); await reader.read()
        listener=await asyncio.start_server(stall,'127.0.0.1',0)
        port=listener.sockets[0].getsockname()[1]
        try:
            with self.assertRaises(SshError) as raised: await self.connect(port=port,timeout_seconds=1)
            self.assertEqual(raised.exception.code,'SSH_CONNECT_TIMEOUT')
        finally:
            listener.close()
            for writer in writers: writer.close(); await writer.wait_closed()
            await listener.wait_closed()
        with self.assertRaises(SshError) as raised: await self.connect(password_ref=None)
        self.assertEqual(raised.exception.code,'SSH_AUTH_FAILED')
        self.assertFalse(self.server.commands)

    async def test_real_worker_transfer_cancel_saves_partial_diagnostics(self):
        from taskweave.application.service import Application
        (self.root/'worker_source').write_bytes(b'x'*300000)
        self.server.delay_write=.15
        def run():
            import time
            with tempfile.TemporaryDirectory() as home, Application(home) as app:
                app.configure_plugin('ssh',True)
                env=app.repo.save_environment('SSH upload evidence',dict(self.ctx.environment),dict(self.ctx.secret_refs))['environment_id']
                task=app.repo.create_task('SSH upload evidence')['task_id']
                step=app.repo.save_step(task,{'name':'partial upload','capabilities':['ssh.upload'],
                    'step_content':'async def run(ctx, inputs):\n    transfer = await ctx.call("ssh.upload", {"local_path":"worker_source", "remote_path":"worker_dest"})\n    return ctx.result(data=transfer)'})
                app.confirm_step_manual(step['step_id'],step['content_hash'],environment_id=env)
                run=app.create_run(task,environment_id=env)
                app.coordinator.start(run['run_id'],uid())
                deadline=time.monotonic()+5
                started=False
                while time.monotonic()<deadline:
                    files=list(self.root.glob('.taskweave-*'))
                    if files and files[0].stat().st_size>32768: started=True; break
                    time.sleep(.01)
                self.assertTrue(started)
                app.coordinator.control(run['run_id'],uid(),'cancel')
                finished=app.coordinator.wait(run['run_id'],8)
                self.assertEqual(finished['status'],'FAILED',finished)
                attempt=finished['attempts'][0]
                self.assertEqual(attempt['effect_state'],'UNKNOWN')
                self.assertEqual(attempt['error_code'],'CANCELLED')
                refs=app.repo.repositories.results.refs_for_attempt(attempt['attempt_id'])
                self.assertEqual(len(refs),1)
                self.assertEqual(refs[0]['handler_id'],'ssh.transfer_failure')
                stored=app.repo.read_result(refs[0]['result_id'],Registry([SshPlugin()]))['data']
                self.assertGreater(stored['result']['bytes_transferred'],0)
                self.assertLess(stored['result']['bytes_transferred'],300000)
                with self.assertRaisesRegex(TaskError,'OUTPUT_NOT_AVAILABLE'): app.repo.read_output(run['run_id'],step['step_id'])
        await asyncio.to_thread(run)
        self.assertFalse((self.root/'worker_dest').exists())
        self.assertFalse(list(self.root.glob('.taskweave-*')))

    async def test_cancel_during_first_write_keeps_acknowledged_progress(self):
        (self.root/'one_chunk').write_bytes(b'x'*32768)
        await self.action('check_connection')
        self.server.delay_write=.2
        task=asyncio.create_task(self.action('upload',local_path='one_chunk',remote_path='first_cancel'))
        for _ in range(100):
            if list(self.root.glob('.taskweave-*')): break
            await asyncio.sleep(.005)
        await asyncio.sleep(.05)
        self.cancel.set()
        with self.assertRaises(SshError): await task
        requests=await self.plugin.failure_results(self.ctx,None)
        self.assertEqual(requests[0].payload['result']['bytes_transferred'],32768)
        self.assertFalse((self.root/'first_cancel').exists())

    async def test_option_like_executable_is_not_interpreted_as_env_flags(self):
        result=await self.action('exec',argv=['-i','/bin/sh','-c','touch env_flag_probe'])
        self.assertNotEqual(result['exit_code'],0)
        self.assertFalse((self.root/'env_flag_probe').exists())

    async def test_destination_symlink_is_existing_and_overwrite_replaces_link(self):
        (self.root/'source_bytes').write_bytes(b'ours')
        (self.root/'referent').write_bytes(b'keep referent')
        (self.root/'target_link').symlink_to(self.root/'referent')
        await self.action('upload',local_path='source_bytes',remote_path='target_link',overwrite=True)
        self.assertEqual((self.root/'referent').read_bytes(),b'keep referent')
        self.assertFalse((self.root/'target_link').is_symlink())
        (self.root/'dangling').symlink_to(self.root/'missing_referent')
        with self.assertRaises(SshError): await self.action('upload',local_path='source_bytes',remote_path='dangling')
        self.assertFalse((self.root/'missing_referent').exists())
        (self.root/'move_link').symlink_to(self.root/'referent')
        await self.action('move',source='target_link',destination='move_link',overwrite=True)
        self.assertEqual((self.root/'referent').read_bytes(),b'keep referent')
        self.assertFalse((self.root/'move_link').is_symlink())

    async def test_cancel_during_connection_root_check_is_prompt(self):
        self.server.delay_realpath=2
        task=asyncio.create_task(self.connect())
        await asyncio.sleep(.1)
        self.cancel.set()
        with self.assertRaises(SshError) as raised:
            await asyncio.wait_for(task,.5)
        self.assertEqual(raised.exception.code,'CANCELLED')
        self.assertFalse(self.server.commands)

    async def test_command_deadline_covers_cwd_realpath_and_stat_before_spawn(self):
        import time
        for realpath_delay,stat_delay in ((1.4,0),(.6,.6)):
            session=await self.connect()
            self.server.delay_realpath=realpath_delay
            self.server.delay_stat=stat_delay
            before=len(self.server.commands)
            started=time.monotonic()
            with self.assertRaises(SshError) as raised:
                await session.run(self.ctx,['/bin/echo','must not start'],cwd='.',env={},stdin=None,timeout_seconds=1)
            self.assertEqual(raised.exception.code,'SSH_COMMAND_TIMEOUT')
            self.assertEqual(raised.exception.effect_state,'NOT_STARTED')
            self.assertIsNone(raised.exception.result)
            self.assertLess(time.monotonic()-started,1.3)
            self.assertEqual(len(self.server.commands),before)
            self.server.delay_realpath=0; self.server.delay_stat=0

    async def test_command_cancel_during_cwd_validation_is_prompt_and_not_started(self):
        session=await self.connect()
        self.server.delay_realpath=1.4
        task=asyncio.create_task(session.run(self.ctx,['/bin/echo','must not start'],cwd='.',env={},stdin=None))
        await asyncio.sleep(.1); self.cancel.set()
        with self.assertRaises(SshError) as raised:
            await asyncio.wait_for(task,.5)
        self.assertEqual(raised.exception.code,'CANCELLED')
        self.assertEqual(raised.exception.effect_state,'NOT_STARTED')
        self.assertIsNone(raised.exception.result)
        self.assertFalse(self.server.commands)
        self.assertEqual(await self.plugin.failure_results(self.ctx,raised.exception),[])

    async def test_external_cancel_during_handshake_is_prompt(self):
        import time
        writers=[]
        async def stall(reader,writer): writers.append(writer); await reader.read()
        listener=await asyncio.start_server(stall,'127.0.0.1',0)
        port=listener.sockets[0].getsockname()[1]
        try:
            task=asyncio.create_task(self.connect(port=port,timeout_seconds=2))
            await asyncio.sleep(.1)
            started=time.monotonic(); task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task
            self.assertLess(time.monotonic()-started,.5)
            self.assertFalse(self.server.commands)
        finally:
            listener.close()
            for writer in writers: writer.close(); await writer.wait_closed()
            await listener.wait_closed()

    async def test_download_cancel_after_first_ack_saves_progress_without_artifact(self):
        import asyncssh
        (self.root/'download_source').write_bytes(b'x'*131072)
        original=asyncssh.SFTPClientFile.read
        received=[]
        async def read_then_cancel(stream,*args,**kwargs):
            data=await original(stream,*args,**kwargs)
            if data:
                received.append(len(data)); self.cancel.set()
            return data
        with patch.object(asyncssh.SFTPClientFile,'read',read_then_cancel):
            with self.assertRaises(SshError) as raised:
                await self.action('download',remote_path='download_source')
        self.assertEqual(received,[65536])
        self.assertEqual(raised.exception.code,'CANCELLED')
        requests=await self.plugin.failure_results(self.ctx,raised.exception)
        self.assertEqual(len(requests),1)
        self.assertEqual(requests[0].handler_id,'ssh.transfer_failure')
        self.assertEqual(requests[0].payload['result']['bytes_transferred'],65536)
        refs=self.results.persist_diagnostics(requests)
        with connect(self.results.path) as db:
            stored=json.loads(db.execute('SELECT payload_json FROM step_outputs WHERE attempt_id=? AND name=?',
                (self.ctx.scope.attempt_id,requests[0].name)).fetchone()[0])
            self.assertEqual(stored['result']['bytes_transferred'],65536)
            self.assertEqual(db.execute('SELECT count(*) FROM result_receipts').fetchone()[0],0)
        self.assertFalse(self.results.tokens)
        self.assertFalse((self.results.root/'artifacts').exists())

    async def test_external_cancel_during_cwd_validation_has_no_command_evidence(self):
        session=await self.connect()
        self.server.delay_realpath=1.4
        task=asyncio.create_task(session.run(self.ctx,['/bin/echo','must not start'],cwd='.',env={},stdin=None))
        await asyncio.sleep(.1); task.cancel()
        with self.assertRaises(asyncio.CancelledError) as raised:
            await asyncio.wait_for(task,.5)
        self.assertEqual(raised.exception.effect_state,'NOT_STARTED')
        self.assertIsNone(raised.exception.result)
        self.assertFalse(self.server.commands)

    async def test_real_worker_download_cancel_saves_acknowledged_bytes_without_artifact(self):
        from taskweave.application.service import Application
        (self.root/'worker_download_source').write_bytes(b'x'*131072)
        self.server.delay_later_read=.4
        def run():
            import time
            with tempfile.TemporaryDirectory() as home, Application(home) as app:
                app.configure_plugin('ssh',True)
                env=app.repo.save_environment('SSH download evidence',dict(self.ctx.environment),dict(self.ctx.secret_refs))['environment_id']
                task=app.repo.create_task('SSH download evidence')['task_id']
                step=app.repo.save_step(task,{'name':'partial download','capabilities':['ssh.download','ssh.file'],
                    'step_content':'async def run(ctx, inputs):\n    transfer = await ctx.call("ssh.download", {"remote_path":"worker_download_source"})\n    return ctx.result(data=transfer, outputs=[ctx.output("ssh.file", "download", transfer["artifact"])])'})
                app.confirm_step_manual(step['step_id'],step['content_hash'],environment_id=env)
                run=app.create_run(task,environment_id=env)
                app.coordinator.start(run['run_id'],uid())
                deadline=time.monotonic()+5
                while 65536 not in self.server.read_requests and time.monotonic()<deadline: time.sleep(.01)
                self.assertIn(65536,self.server.read_requests,'second chunk request proves first chunk was acknowledged')
                app.coordinator.control(run['run_id'],uid(),'cancel')
                finished=app.coordinator.wait(run['run_id'],8)
                self.assertEqual(finished['status'],'CANCELLED',finished)
                attempt=finished['attempts'][0]
                self.assertEqual(attempt['status'],'CANCELLED')
                self.assertEqual(attempt['effect_state'],'NOT_STARTED')
                refs=app.repo.repositories.results.refs_for_attempt(attempt['attempt_id'])
                self.assertEqual(len(refs),1)
                self.assertEqual(refs[0]['handler_id'],'ssh.transfer_failure')
                stored=app.repo.read_result(refs[0]['result_id'],Registry([SshPlugin()]))['data']
                self.assertEqual(stored['result']['bytes_transferred'],65536)
                self.assertEqual(stored['effect_state'],'UNKNOWN')
                self.assertEqual(stored['error_code'],'CANCELLED')
                self.assertNotIn('staged',stored['result']['completed'])
                self.assertFalse((Path(home)/'tasks'/task/'artifacts').exists())
                with self.assertRaisesRegex(TaskError,'OUTPUT_NOT_AVAILABLE'): app.repo.read_output(run['run_id'],step['step_id'])
        await asyncio.to_thread(run)
