"""Loopback SSH+SFTP fixture with real authentication, shell and filesystem."""
import asyncio
from pathlib import Path
import os
import signal
import warnings
import asyncssh


class Server(asyncssh.SSHServer):
    def __init__(self, fixture):
        self.fixture = fixture
    def begin_auth(self, username):
        return True
    def password_auth_supported(self):
        return True
    def public_key_auth_supported(self):
        return True
    def validate_password(self, username, password):
        return username == 'tester' and password == 'test-password'
    def validate_public_key(self, username, key):
        return username == 'tester' and key == self.fixture.client_key.convert_to_public()


class SshServer:
    def __init__(self, root):
        self.root = Path(root)
        self.host_key = asyncssh.generate_private_key('ssh-ed25519')
        self.client_key = asyncssh.generate_private_key('ssh-ed25519')
        self.commands = []
        self.children = set()
        self.race_destination = None
        self.delay_write = 0
        self.delay_realpath = 0
        self.delay_stat = 0
        self.delay_later_read = 0
        self.read_requests = []
        self.rename_gate = None

    async def start(self):
        fixture = self
        class Sftp(asyncssh.SFTPServer):
            def __init__(self, channel):
                super().__init__(channel)
            async def realpath(self,path):
                if fixture.delay_realpath: await asyncio.sleep(fixture.delay_realpath)
                return super().realpath(path)
            async def stat(self,path):
                if fixture.delay_stat: await asyncio.sleep(fixture.delay_stat)
                return super().stat(path)
            async def read(self,file_obj,offset,size):
                fixture.read_requests.append(offset)
                if offset and fixture.delay_later_read: await asyncio.sleep(fixture.delay_later_read)
                return super().read(file_obj,offset,size)
            async def write(self, file_obj, offset, data):
                if fixture.delay_write:
                    await asyncio.sleep(fixture.delay_write)
                return super().write(file_obj, offset, data)
            def rename(self, oldpath, newpath):
                if fixture.race_destination is not None:
                    Path(os.fsdecode(newpath)).write_bytes(b'concurrent target')
                    fixture.race_destination = None
                return super().rename(oldpath, newpath)
        self.listener = await asyncssh.listen('127.0.0.1', 0, server_factory=lambda: Server(self),
            server_host_keys=[self.host_key], process_factory=self.process, encoding=None,
            sftp_factory=Sftp)
        self.port = self.listener.get_port()
        self.known_hosts = self.root / 'known_hosts'
        self.known_hosts.write_bytes(f'[127.0.0.1]:{self.port} '.encode()+self.host_key.export_public_key())
        self.key_path = self.root / 'private-key'
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore', message='Warning: bcrypt.kdf')
            self.key_path.write_bytes(self.client_key.export_private_key('openssh', passphrase='key-password', rounds=1))
        self.key_path.chmod(0o600)
        return self

    async def process(self, process):
        self.commands.append(process.command)
        child = await asyncio.create_subprocess_shell(process.command, executable='/bin/sh',
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            start_new_session=True)
        self.children.add(child)
        async def feed():
            try:
                while chunk := await process.stdin.read(8192):
                    child.stdin.write(chunk)
                    await child.stdin.drain()
            except (asyncssh.Error, BrokenPipeError, ConnectionResetError):
                pass
            finally:
                child.stdin.close()
        async def copy(source, dest):
            try:
                while chunk := await source.read(8192):
                    dest.write(chunk)
                    await dest.drain()
            except (asyncssh.Error, BrokenPipeError, ConnectionResetError):
                pass
        tasks = [asyncio.create_task(feed()), asyncio.create_task(copy(child.stdout, process.stdout)),
                 asyncio.create_task(copy(child.stderr, process.stderr))]
        try:
            code = await child.wait()
            await asyncio.gather(*tasks, return_exceptions=True)
            process.exit(code)
        finally:
            for task in tasks:
                task.cancel()
            if child.returncode is None:
                os.killpg(child.pid, signal.SIGKILL)
                await child.wait()
            self.children.discard(child)

    def config(self):
        return {'host':'127.0.0.1', 'port':self.port, 'username':'tester',
                'known_hosts':str(self.known_hosts), 'password_ref':'password', 'remote_root':str(self.root)}

    async def close(self):
        for child in tuple(self.children):
            if child.returncode is None:
                os.killpg(child.pid, signal.SIGKILL)
                await child.wait()
        self.listener.close()
        await self.listener.wait_closed()
