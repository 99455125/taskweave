"""Private loopback bridge to the one application that owns a workspace."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import threading
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlparse

from taskweave.core.validation import TaskError
from taskweave.infrastructure.http import make_server
from taskweave.infrastructure.sqlite_storage import default_home


def workspace_id(home):
    return hashlib.sha256(str(Path(home).resolve()).encode()).hexdigest()


class AgentHost:
    def __init__(self, app):
        self.app = app
        self.path = Path(app.home) / 'agent-connection.json'
        self.identity = {'instance_id': secrets.token_hex(24), 'pid': os.getpid(),
                         'workspace_id': workspace_id(app.home)}
        self.server, token = make_server(self)
        self.descriptor = {**self.identity, 'url': f'http://127.0.0.1:{self.server.server_port}/api', 'token': token}
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True, name='taskweave-agent-api')

    def dispatch(self, operation, params):
        if operation == 'agent.identity':
            return self.identity
        if operation not in {'agent.discover', 'agent.describe', 'agent.author', 'agent.context',
                             'agent.execute', 'agent.wait', 'agent.inspect', 'agent.review'}:
            raise TaskError('AGENT_OPERATION_DENIED')
        return self.app.dispatch(operation, params)

    def __enter__(self):
        temporary = self.path.with_name('.agent-connection-' + self.identity['instance_id'] + '.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(self.descriptor, stream)
            os.replace(temporary, self.path)
            self.thread.start()
        except BaseException:
            temporary.unlink(missing_ok=True)
            self.server.server_close()
            raise
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()
        try:
            if json.loads(self.path.read_text()).get('instance_id') == self.identity['instance_id']:
                self.path.unlink()
        except (OSError, ValueError):
            pass


class AgentClient:
    def __init__(self, home=None):
        self.home = Path(home or default_home()).expanduser().resolve()

    def _descriptor(self):
        path = self.home / 'agent-connection.json'
        try:
            stat = path.lstat()
            if path.is_symlink() or stat.st_size > 8192 or (os.name != 'nt' and
                    (stat.st_uid != os.getuid() or stat.st_mode & 0o077)):
                raise TaskError('AGENT_CONNECTION_INVALID')
            value = json.loads(path.read_text())
            parsed = urlparse(value['url'])
            if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.path != '/api'
                    or parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.port
                    or value['workspace_id'] != workspace_id(self.home)
                    or not isinstance(value['token'], str) or not value['token']):
                raise TaskError('AGENT_CONNECTION_INVALID')
            return value
        except FileNotFoundError as exc:
            raise TaskError('AGENT_OWNER_UNAVAILABLE', '请先启动此工作空间的 TaskWeave 工作台或 serve') from exc
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise TaskError('AGENT_CONNECTION_INVALID') from exc

    @staticmethod
    def _send(descriptor, operation, params):
        request = Request(descriptor['url'], data=json.dumps({'operation': operation, 'params': params}).encode(),
                          headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + descriptor['token']})
        try:
            with urlopen(request, timeout=40) as response:
                result = json.load(response)
        except HTTPError as exc:
            try:
                result = json.load(exc)
            except (ValueError, OSError):
                raise TaskError('AGENT_CONNECTION_STALE') from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise TaskError('AGENT_OWNER_UNAVAILABLE', 'TaskWeave 连接已关闭，请重新启动工作台') from exc
        if not result.get('ok'):
            error = result.get('error', {})
            raise TaskError(error.get('code', 'AGENT_CONNECTION_INVALID'), error.get('message', ''))
        return result['result']

    def call(self, operation, params):
        value = self._descriptor()
        identity = self._send(value, 'agent.identity', {})
        if any(identity.get(key) != value.get(key) for key in ('instance_id', 'pid', 'workspace_id')):
            raise TaskError('AGENT_CONNECTION_STALE')
        return self._send(value, operation, params)
