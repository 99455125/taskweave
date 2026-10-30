"""Nacos configuration operations and JSON update semantics."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugins/nacos/src'))


class NacosJsonTests(unittest.TestCase):
    def test_merge_preserves_unspecified_fields_and_replaces_arrays(self):
        from taskweave_nacos.json_update import merge_json
        original = {'db': {'host': 'prod', 'port': 3306}, 'list': [1, 2], 'unchanged': True}
        self.assertEqual(merge_json(original, {'db': {'port': 3307}, 'list': [3], 'new': None}),
                         {'db': {'host': 'prod', 'port': 3307}, 'list': [3], 'unchanged': True, 'new': None})
        self.assertEqual(original['db']['port'], 3306)

    def test_merge_requires_object_at_root(self):
        from taskweave_nacos.json_update import merge_json
        from taskweave.plugins.sdk import PluginError
        with self.assertRaises(PluginError):
            merge_json([1], {'key': 2})

    def test_patch_json_returns_merged_json_and_preserves_null(self):
        import json
        from taskweave_nacos.json_update import patch_json
        updated = patch_json('{"a": {"left": 1, "right": 2}, "x": 3}', {'a': {'left': None}})
        self.assertEqual(json.loads(updated), {'a': {'left': None, 'right': 2}, 'x': 3})

    def test_patch_rejects_invalid_or_ambiguous_json(self):
        from taskweave_nacos.json_update import patch_json
        from taskweave.plugins.sdk import PluginError
        for content in ('{"x": 1, "x": 2}', '{"x": NaN}', '[1]', 'not json'):
            with self.subTest(content=content), self.assertRaises(PluginError):
                patch_json(content, {'x': 3})

class NacosActionTests(unittest.IsolatedAsyncioTestCase):
    async def test_patch_reads_merges_and_publishes_with_server_cas(self):
        import hashlib
        import json
        from types import SimpleNamespace
        from unittest.mock import patch
        from taskweave_nacos import NacosPlugin
        from taskweave_nacos.client import NacosClient
        requests = []
        async def request(client, method, path, params=None, data=None, headers=None, **kwargs):
            requests.append((method, path, params, data, headers))
            if method == 'GET': return '{"keep":1,"db":{"port":3306}}'
            return 'true'
        ctx = SimpleNamespace(environment={'nacos_profiles': {'prod': {'url': 'http://localhost:8848', 'allow_http': True}}}, task_parameters={}, cancelled=lambda: False, resolve_secret=lambda ref: 'secret')
        with patch.object(NacosClient, 'request', request):
            result = await NacosPlugin().actions()['nacos.patch_json'].execute(ctx, {'profile': 'prod', 'data_id': 'app.json', 'patch': {'db': {'port': 3307}}})
        self.assertTrue(result['published'])
        self.assertEqual(json.loads(requests[-1][3]['content']), {'keep': 1, 'db': {'port': 3307}})
        self.assertEqual(requests[-1][4]['casMd5'], hashlib.md5(b'{"keep":1,"db":{"port":3306}}').hexdigest())

    async def test_patch_conflict_fails_without_retry(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from taskweave_nacos import NacosPlugin
        from taskweave_nacos.client import NacosClient
        from taskweave.plugins.sdk import PluginError
        calls = []
        async def request(client, method, path, params=None, data=None, headers=None, **kwargs):
            calls.append(method)
            return '{"a": 1}' if method == 'GET' else 'false'
        ctx = SimpleNamespace(environment={'nacos_profiles': {'prod': {'url': 'http://localhost:8848', 'allow_http': True}}}, task_parameters={}, cancelled=lambda: False, resolve_secret=lambda ref: 'secret')
        with patch.object(NacosClient, 'request', request):
            with self.assertRaises(PluginError):
                await NacosPlugin().actions()['nacos.patch_json'].execute(ctx, {'profile': 'prod', 'data_id': 'app.json', 'patch': {'a': 2}})
        self.assertEqual(calls, ['GET', 'POST'])

class NacosHttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_login_read_and_patch_use_real_http_and_secret_reference(self):
        import hashlib
        import json
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from types import SimpleNamespace
        from urllib.parse import parse_qs, urlsplit
        from taskweave_nacos import NacosPlugin
        original = '{"environment":"prod","service":{"limit":1}}'
        calls = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def reply(self, text):
                data = text.encode('utf-8'); self.send_response(200); self.end_headers(); self.wfile.write(data)
            def do_GET(self):
                calls.append(('GET', self.path, {})); self.reply(original)
            def do_POST(self):
                data = parse_qs(self.rfile.read(int(self.headers['Content-Length'])).decode())
                calls.append(('POST', self.path, {'data': data, 'cas': self.headers.get('casMd5')}))
                if self.path == '/nacos/v1/auth/login': self.reply('{"accessToken":"test-token"}')
                else: self.reply('true')
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        ctx = SimpleNamespace(environment={'nacos_profiles': {'prod': {'url': f'http://127.0.0.1:{server.server_port}', 'allow_http': True, 'username': 'tester', 'password_ref': 'nacos-password', 'namespace': 'uat'}}}, task_parameters={}, cancelled=lambda: False, resolve_secret=lambda ref: 'test-password' if ref == 'nacos-password' else None)
        try:
            result = await NacosPlugin().actions()['nacos.patch_json'].execute(ctx, {'profile': 'prod', 'data_id': 'app.json', 'patch': {'service': {'limit': 2}}})
        finally:
            server.shutdown(); server.server_close(); thread.join()
        self.assertTrue(result['published'])
        self.assertEqual([c[0] for c in calls], ['POST', 'GET', 'POST'])
        self.assertEqual(calls[0][2]['data'], {'username': ['tester'], 'password': ['test-password']})
        self.assertEqual(parse_qs(urlsplit(calls[1][1]).query)['accessToken'], ['test-token'])
        self.assertEqual(calls[2][2]['cas'], hashlib.md5(original.encode()).hexdigest())
        self.assertEqual(json.loads(calls[2][2]['data']['content'][0]), {'environment':'prod','service':{'limit':2}})
        self.assertNotIn('test-password', str(result))

    async def test_actions_cover_configuration_lifecycle_and_deletion(self):
        from taskweave_nacos import NacosPlugin
        actions = NacosPlugin().actions()
        self.assertEqual(set(actions), {'nacos.list', 'nacos.namespaces', 'nacos.select_fields', 'nacos.get', 'nacos.get_json', 'nacos.publish', 'nacos.patch_json', 'nacos.update_fields', 'nacos.update_many', 'nacos.update_batch', 'nacos.delete'})
        self.assertEqual(actions['nacos.delete'].spec.effect, 'WRITE')
        self.assertFalse(actions['nacos.delete'].spec.retry_safe)

    async def test_get_json_exposes_fields_for_step_selection(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from taskweave_nacos import NacosPlugin
        from taskweave_nacos.client import NacosClient
        async def request(client, method, path, params=None, data=None, headers=None):
            return '{"service":{"limit":5},"other":"source-only"}'
        ctx = SimpleNamespace(environment={'nacos_profiles': {'dev': {'url': 'http://localhost:8848', 'allow_http': True}}}, task_parameters={}, cancelled=lambda: False, resolve_secret=lambda ref: '')
        with patch.object(NacosClient, 'request', request):
            result = await NacosPlugin().actions()['nacos.get_json'].execute(ctx, {'profile': 'dev', 'data_id': 'app.json'})
        self.assertEqual(result['value']['service']['limit'], 5)

    async def test_list_publish_and_delete_parameters_and_schema(self):
        import json
        from types import SimpleNamespace
        from unittest.mock import patch
        from taskweave.core.validation import validate
        from taskweave_nacos import NacosPlugin
        from taskweave_nacos.client import NacosClient
        calls = []
        async def request(client, method, path, params=None, data=None, headers=None):
            calls.append((method, path, params, data))
            return json.dumps({'pageItems': [{'dataId': 'a.yml'}], 'totalCount': 1}) if method == 'GET' else 'true'
        ctx = SimpleNamespace(environment={'nacos_profiles': {'test': {'url': 'http://localhost:8848', 'allow_http': True, 'namespace': 'ns'}}}, task_parameters={}, cancelled=lambda: False, resolve_secret=lambda ref: '')
        actions = NacosPlugin().actions()
        with patch.object(NacosClient, 'request', request):
            for name, inputs in [('list', {'profile': 'test', 'group': 'team', 'page': 2, 'page_size': 5}), ('publish', {'profile': 'test', 'data_id': 'a.yml', 'content': 'a: 1', 'type': 'yaml'}), ('delete', {'profile': 'test', 'data_id': 'a.yml'})]:
                output = await actions['nacos.' + name].execute(ctx, inputs)
                validate(output, actions['nacos.' + name].spec.output_schema)
        self.assertEqual(calls[0][2], {'dataId': '', 'group': 'team', 'tenant': 'ns', 'search': 'blur', 'pageNo': 2, 'pageSize': 5})
        self.assertEqual(calls[1][3]['type'], 'yaml')
        self.assertEqual(calls[2][0], 'DELETE')

    async def test_http_server_error_after_write_is_unknown(self):
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from types import SimpleNamespace
        from taskweave.plugins.sdk import PluginError
        from taskweave_nacos import NacosPlugin
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(500); self.end_headers(); self.wfile.write(b'error')
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        ctx = SimpleNamespace(environment={'nacos_profiles': {'x': {'url': f'http://127.0.0.1:{server.server_port}', 'allow_http': True}}}, task_parameters={}, cancelled=lambda: False, resolve_secret=lambda ref: '')
        try:
            with self.assertRaises(PluginError) as exc:
                await NacosPlugin().actions()['nacos.publish'].execute(ctx, {'profile': 'x', 'data_id': 'a', 'content': 'text', 'type': 'text'})
            self.assertEqual(exc.exception.code, 'NACOS_WRITE_UNKNOWN')
        finally:
            server.shutdown(); server.server_close(); thread.join()

    async def test_cancel_after_login_prevents_publish(self):
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from types import SimpleNamespace
        from taskweave.plugins.sdk import PluginError
        from taskweave_nacos import NacosPlugin
        calls = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                calls.append(self.path); self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(200); self.end_headers(); self.wfile.write(b'{"accessToken":"t"}')
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        ctx = SimpleNamespace(environment={'nacos_profiles': {'x': {'url': f'http://127.0.0.1:{server.server_port}', 'allow_http': True, 'username': 'u', 'password_ref': 'p'}}}, task_parameters={}, cancelled=lambda: len(calls) > 0, resolve_secret=lambda ref: 'secret')
        try:
            with self.assertRaises(PluginError) as exc:
                await NacosPlugin().actions()['nacos.publish'].execute(ctx, {'profile': 'x', 'data_id': 'a', 'content': 'text', 'type': 'text'})
            self.assertEqual(exc.exception.code, 'CANCELLED')
            self.assertEqual(calls, ['/nacos/v1/auth/login'])
        finally:
            server.shutdown(); server.server_close(); thread.join()

    async def test_oversized_write_response_has_unknown_outcome(self):
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from types import SimpleNamespace
        from taskweave.plugins.sdk import PluginError
        from taskweave_nacos import NacosPlugin
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(200); self.end_headers(); self.wfile.write(b'x' * (2 * 1024 * 1024 + 1))
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        ctx = SimpleNamespace(environment={'nacos_profiles': {'x': {'url': f'http://127.0.0.1:{server.server_port}', 'allow_http': True}}}, task_parameters={}, cancelled=lambda: False, resolve_secret=lambda ref: '')
        try:
            with self.assertRaises(PluginError) as exc:
                await NacosPlugin().actions()['nacos.publish'].execute(ctx, {'profile': 'x', 'data_id': 'a', 'content': 'text', 'type': 'text'})
            self.assertEqual(exc.exception.code, 'NACOS_WRITE_UNKNOWN')
        finally:
            server.shutdown(); server.server_close(); thread.join()

    async def test_publish_requires_type_and_unknown_response_is_not_rejection(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from taskweave.plugins.sdk import PluginError
        from taskweave_nacos import NacosPlugin
        from taskweave_nacos.client import NacosClient
        ctx = SimpleNamespace(environment={'nacos_profiles': {'x': {'url': 'http://localhost:8848', 'allow_http': True}}}, task_parameters={}, cancelled=lambda: False, resolve_secret=lambda ref: '')
        action = NacosPlugin().actions()['nacos.publish']
        async def request(client, method, path, params=None, data=None, headers=None):
            self.assertEqual(data['type'], 'yaml')
            return '<html>unknown</html>'
        with self.assertRaises(PluginError) as exc:
            await action.execute(ctx, {'profile': 'x', 'data_id': 'app', 'content': 'a: 1'})
        self.assertEqual(exc.exception.code, 'NACOS_TYPE_REQUIRED')
        with patch.object(NacosClient, 'request', request):
            with self.assertRaises(PluginError) as exc:
                await action.execute(ctx, {'profile': 'x', 'data_id': 'app', 'content': 'a: 1', 'type': 'yaml'})
            self.assertEqual(exc.exception.code, 'NACOS_WRITE_UNKNOWN')

    async def test_nacos_243_cas_conflict_http_500_is_not_retried(self):
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from types import SimpleNamespace
        from taskweave.plugins.sdk import PluginError
        from taskweave_nacos import NacosPlugin
        calls = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                calls.append('GET'); self.send_response(200); self.end_headers(); self.wfile.write(b'{"x":1}')
            def do_POST(self):
                calls.append('POST'); self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(500); self.end_headers(); self.wfile.write(b'Cas publish fail')
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        ctx = SimpleNamespace(environment={'nacos_profiles': {'x': {'url': f'http://127.0.0.1:{server.server_port}', 'allow_http': True}}}, task_parameters={}, cancelled=lambda: False, resolve_secret=lambda ref: '')
        try:
            with self.assertRaises(PluginError) as exc:
                await NacosPlugin().actions()['nacos.patch_json'].execute(ctx, {'profile': 'x', 'data_id': 'a', 'patch': {'x': 2}})
            self.assertEqual(exc.exception.code, 'NACOS_WRITE_UNKNOWN')
            self.assertEqual(calls, ['GET', 'POST'])
        finally:
            server.shutdown(); server.server_close(); thread.join()

class NacosFieldOperationTests(unittest.TestCase):
    def test_nested_delete_and_set_preserve_other_fields(self):
        from taskweave_nacos.structured_update import apply_operations
        value = {'SmartCount': {'AA': 'keep', 'BBB': 'old'}}
        self.assertEqual(apply_operations(value, [{'op': 'set', 'path': ['SmartCount', 'BBB'], 'value': 'new'}]), {'SmartCount': {'AA': 'keep', 'BBB': 'new'}})
        self.assertEqual(apply_operations(value, [{'op': 'remove', 'path': ['SmartCount', 'BBB']}]), {'SmartCount': {'AA': 'keep'}})
        self.assertEqual(value['SmartCount']['BBB'], 'old')

    def test_list_and_comma_separated_items_can_be_added_and_removed(self):
        from taskweave_nacos.structured_update import apply_operations
        value = {'list': ['a', 'b'], 'csv': 'a,b'}
        result = apply_operations(value, [
            {'op': 'list_add', 'path': ['list'], 'value': 'c'},
            {'op': 'list_remove', 'path': ['list'], 'value': 'b'},
            {'op': 'csv_add', 'path': ['csv'], 'value': 'c'},
            {'op': 'csv_remove', 'path': ['csv'], 'value': 'b'},
        ])
        self.assertEqual(result, {'list': ['a', 'c'], 'csv': 'a,c'})

    def test_ambiguous_list_removal_and_missing_field_fail(self):
        from taskweave_nacos.structured_update import apply_operations
        from taskweave.plugins.sdk import PluginError
        for value, operation in [({'a': [1, 1]}, {'op': 'list_remove', 'path': ['a'], 'value': 1}), ({'a': 1}, {'op': 'remove', 'path': ['missing']})]:
            with self.subTest(value=value), self.assertRaises(PluginError):
                apply_operations(value, [operation])

    def test_yaml_patch_preserves_other_values_comments_and_string_style(self):
        from taskweave_nacos.structured_update import update_document
        original = '# Keep this comment\nSmartCount:\n  AA: "a,b" # inline\n  BBB: old\n  choices:\n    - one\n    - two\n'
        result = update_document(original, 'yaml', [
            {'op': 'csv_add', 'path': ['SmartCount', 'AA'], 'value': 'c'},
            {'op': 'remove', 'path': ['SmartCount', 'BBB']},
            {'op': 'list_remove', 'path': ['SmartCount', 'choices'], 'value': 'one'},
        ])
        self.assertIn('# Keep this comment', result)
        self.assertIn('# inline', result)
        self.assertIn('a,b,c', result)
        self.assertNotIn('BBB:', result)
        self.assertIn('- two', result)

    def test_yaml_duplicate_keys_and_aliases_fail_before_update(self):
        from taskweave_nacos.structured_update import update_document
        from taskweave.plugins.sdk import PluginError
        for original in ('a: 1\na: 2\n', 'a: &defaults {x: 1}\nb: *defaults\n'):
            with self.subTest(original=original), self.assertRaises(PluginError):
                update_document(original, 'yaml', [{'op': 'set', 'path': ['a'], 'value': 3}])

class NacosUpdateActionTests(unittest.IsolatedAsyncioTestCase):
    async def test_yaml_field_update_uses_namespace_and_cas(self):
        import hashlib
        from types import SimpleNamespace
        from unittest.mock import patch
        from taskweave_nacos import NacosPlugin
        from taskweave_nacos.client import NacosClient
        original = 'AA: keep\nBBB: old\n'
        calls = []
        async def request(client, method, path, params=None, data=None, headers=None):
            calls.append((method, params, data, headers))
            return __import__('json').dumps({'content': original, 'type': 'yaml'}) if method == 'GET' else 'true'
        ctx = SimpleNamespace(environment={'nacos_profiles': {'cluster': {'url': 'http://localhost:8848', 'allow_http': True}}}, task_parameters={}, cancelled=lambda: False, resolve_secret=lambda ref: '')
        with patch.object(NacosClient, 'request', request):
            result = await NacosPlugin().actions()['nacos.update_fields'].execute(ctx, {'profile': 'cluster', 'namespace': 'test1', 'data_id': 'app.yml', 'format': 'yaml', 'operations': [{'op': 'remove', 'path': ['BBB']}]})
        self.assertTrue(result['published'])
        self.assertEqual(calls[0][1]['tenant'], 'test1')
        self.assertEqual(calls[1][2]['tenant'], 'test1')
        self.assertEqual(calls[1][2]['type'], 'yaml')
        self.assertIn('AA: keep', calls[1][2]['content'])
        self.assertNotIn('BBB:', calls[1][2]['content'])
        self.assertEqual(calls[1][3]['casMd5'], hashlib.md5(original.encode()).hexdigest())

    async def test_list_namespaces_uses_nacos_ids_and_names(self):
        import json
        from types import SimpleNamespace
        from unittest.mock import patch
        from taskweave_nacos import NacosPlugin
        from taskweave_nacos.client import NacosClient
        async def request(client, method, path, params=None, data=None, headers=None):
            self.assertEqual((method, path), ('GET', '/v2/console/namespace/list'))
            return json.dumps({'code': 0, 'data': [{'namespace': '', 'namespaceShowName': 'public'}, {'namespace': 'dev1-id', 'namespaceShowName': 'dev1'}]})
        ctx = SimpleNamespace(environment={'nacos_profiles': {'cluster': {'url': 'http://localhost:8848', 'allow_http': True}}}, task_parameters={}, cancelled=lambda: False, resolve_secret=lambda ref: '')
        with patch.object(NacosClient, 'request', request):
            result = await NacosPlugin().actions()['nacos.namespaces'].execute(ctx, {'profile': 'cluster'})
        self.assertEqual(result['namespaces'], [{'id': '', 'name': 'public'}, {'id': 'dev1-id', 'name': 'dev1'}])

class NacosSourceSelectionTests(unittest.IsolatedAsyncioTestCase):
    def test_selects_yaml_fields_to_apply_to_a_different_namespace(self):
        from taskweave_nacos.structured_update import selected_fields
        source = 'spring:\n  cloud:\n    aaa: from-test\n    bbb: only-here\n'
        self.assertEqual(selected_fields(source, 'yaml', [['spring', 'cloud', 'aaa']]), [{'op': 'set', 'path': ['spring', 'cloud', 'aaa'], 'value': 'from-test'}])

    async def test_select_fields_returns_operations_for_sync(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from taskweave_nacos import NacosPlugin
        from taskweave_nacos.client import NacosClient
        async def request(client, method, path, params=None, data=None, headers=None):
            return 'spring:\n  cloud:\n    aaa: 9\n    bbb: keep\n'
        ctx = SimpleNamespace(environment={'nacos_profiles': {'x': {'url': 'http://localhost:8848', 'allow_http': True}}}, task_parameters={}, cancelled=lambda: False, resolve_secret=lambda ref: '')
        with patch.object(NacosClient, 'request', request):
            result = await NacosPlugin().actions()['nacos.select_fields'].execute(ctx, {'profile': 'x', 'data_id': 'app.yml', 'format': 'yaml', 'paths': [['spring', 'cloud', 'aaa']]})
        self.assertEqual(result['operations'], [{'op': 'set', 'path': ['spring', 'cloud', 'aaa'], 'value': 9}])

class NacosBatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_multi_namespace_publication_tracks_each_result(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from taskweave_nacos import NacosPlugin
        from taskweave_nacos.client import NacosClient
        writes = []
        async def request(client, method, path, params=None, data=None, headers=None):
            if method == 'GET':
                return '{"content": "{\\"spring\\":{\\"cloud\\":{\\"aaa\\":\\"old\\",\\"bbb\\":\\"keep\\"}}}", "type":"json"}'
            writes.append(data['tenant']); return 'true'
        logs = []
        ctx = SimpleNamespace(environment={'nacos_profiles': {'cluster': {'url': 'http://localhost:8848', 'allow_http': True}}}, task_parameters={}, cancelled=lambda: False, resolve_secret=lambda ref: '', log=lambda level, message: logs.append(message))
        inputs = {'profile': 'cluster', 'namespaces': ['dev1', 'dev2'], 'data_id': 'app.json', 'format': 'json', 'operations': [{'op': 'set', 'path': ['spring', 'cloud', 'aaa'], 'value': 'new'}]}
        with patch.object(NacosClient, 'request', request):
            output = await NacosPlugin().actions()['nacos.update_many'].execute(ctx, inputs)
        self.assertEqual(writes, ['dev1', 'dev2'])
        self.assertEqual([x['namespace'] for x in output['published']], ['dev1', 'dev2'])
        self.assertEqual(len(logs), 4)

    async def test_multi_namespace_stops_and_reports_completed_targets(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from taskweave.plugins.sdk import PluginError
        from taskweave_nacos import NacosPlugin
        from taskweave_nacos.client import NacosClient
        writes = []
        async def request(client, method, path, params=None, data=None, headers=None):
            if method == 'GET': return '{"content":"{\\"x\\":1}","type":"json"}'
            writes.append(data['tenant'])
            if data['tenant'] == 'dev2': raise PluginError('NACOS_WRITE_UNKNOWN')
            return 'true'
        logs = []
        ctx = SimpleNamespace(environment={'nacos_profiles': {'cluster': {'url': 'http://localhost:8848', 'allow_http': True}}}, task_parameters={}, cancelled=lambda: False, resolve_secret=lambda ref: '', log=lambda level, message: logs.append(message))
        inputs = {'profile': 'cluster', 'namespaces': ['dev1', 'dev2', 'dev3'], 'data_id': 'a', 'format': 'json', 'operations': [{'op': 'set', 'path': ['x'], 'value': 2}]}
        with patch.object(NacosClient, 'request', request):
            with self.assertRaises(PluginError) as exc:
                await NacosPlugin().actions()['nacos.update_many'].execute(ctx, inputs)
        self.assertEqual(exc.exception.code, 'NACOS_BATCH_INCOMPLETE')
        self.assertEqual(writes, ['dev1', 'dev2'])
        self.assertIn('dev1', str(exc.exception))
        self.assertIn('dev2', str(exc.exception))

    def test_unselected_yaml_ambiguous_scalar_retains_lexical_form(self):
        from taskweave_nacos.structured_update import update_document
        result = update_document('a: on\nb: old\n', 'yaml', [{'op': 'set', 'path': ['b'], 'value': 'new'}])
        self.assertIn('a: on', result)
        self.assertNotIn('%YAML 1.1', result)

    def test_deleting_a_key_preserves_comment_for_next_key(self):
        from taskweave_nacos.structured_update import update_document
        result = update_document('a: 1\n# important comment for b\nb: 2\n', 'yaml', [{'op': 'remove', 'path': ['a']}])
        self.assertIn('# important comment for b', result)
        self.assertIn('b: 2', result)

    def test_remove_quoted_yaml_list_value(self):
        from taskweave_nacos.structured_update import update_document
        result = update_document('a: ["one", "two"]\n', 'yaml', [{'op': 'list_remove', 'path': ['a'], 'value': 'one'}])
        self.assertNotIn('one', result)
        self.assertIn('two', result)

    async def test_update_preserves_existing_type_and_metadata(self):
        import json
        from types import SimpleNamespace
        from unittest.mock import patch
        from taskweave_nacos import NacosPlugin
        from taskweave_nacos.client import NacosClient
        details = {'content':'a: old\n', 'type':'text', 'appName':'app', 'desc':'notes', 'configTags':'team'}
        calls = []
        async def request(client, method, path, params=None, data=None, headers=None):
            if method == 'GET':
                self.assertEqual(params['show'], 'all'); return json.dumps(details)
            calls.append(data); return 'true'
        ctx = SimpleNamespace(environment={'nacos_profiles': {'x': {'url': 'http://localhost:8848', 'allow_http': True}}}, task_parameters={}, cancelled=lambda: False, resolve_secret=lambda ref: '')
        with patch.object(NacosClient, 'request', request):
            await NacosPlugin().actions()['nacos.update_fields'].execute(ctx, {'profile': 'x', 'data_id': 'a', 'format': 'yaml', 'operations': [{'op': 'set', 'path': ['a'], 'value': 'new'}]})
        self.assertEqual(calls[0]['type'], 'text')
        self.assertNotIn('appName', calls[0])
        self.assertEqual(calls[0]['desc'], 'notes')
        self.assertNotIn('config_tags', calls[0])

    async def test_batch_multiple_configs_and_namespaces(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from taskweave_nacos import NacosPlugin
        from taskweave_nacos.client import NacosClient
        import json
        calls = []
        async def request(client, method, path, params=None, data=None, headers=None):
            if method == 'GET':
                return json.dumps({'content': '{"a":1,"b":2}', 'type': 'json'})
            calls.append((data['tenant'], data['dataId'])); return 'true'
        ctx = SimpleNamespace(environment={'nacos_profiles': {'x': {'url': 'http://localhost:8848', 'allow_http': True}}}, task_parameters={}, cancelled=lambda: False, resolve_secret=lambda ref: '', log=lambda *args: None)
        inputs = {'profile':'x', 'namespaces':['dev1','dev2'], 'configs':[{'data_id':'a.json','format':'json','operations':[{'op':'set','path':['a'],'value':4}]}, {'data_id':'b.json','format':'json','operations':[{'op':'remove','path':['b']}]}]}
        with patch.object(NacosClient, 'request', request):
            result = await NacosPlugin().actions()['nacos.update_batch'].execute(ctx, inputs)
        self.assertEqual(calls, [('dev1','a.json'), ('dev1','b.json'), ('dev2','a.json'), ('dev2','b.json')])
        self.assertEqual(len(result['published']), 4)

    def test_yaml_inserted_string_is_string_for_yaml_11_consumer(self):
        from ruamel.yaml import YAML
        from taskweave_nacos.structured_update import update_document
        updated = update_document('a: old\n', 'yaml', [{'op': 'set', 'path': ['a'], 'value': 'on'}])
        parser = YAML(typ='safe'); parser.version = (1, 1)
        self.assertEqual(parser.load(updated)['a'], 'on')

    def test_yaml_list_delete_preserves_next_item_comment(self):
        from taskweave_nacos.structured_update import update_document
        updated = update_document('a:\n  - x\n  # note for y\n  - y\nb: keep\n', 'yaml', [{'op': 'list_remove', 'path': ['a'], 'value': 'x'}])
        self.assertIn('# note for y', updated)
        self.assertIn('- y', updated)

    def test_yaml_does_not_silently_drop_comment_on_deleted_final_item(self):
        from taskweave_nacos.structured_update import update_document
        from taskweave.plugins.sdk import PluginError
        original = 'a: 1\n# keep\nb: 2 # trailing\n'
        with self.assertRaises(PluginError):
            update_document(original, 'yaml', [{'op': 'remove', 'path': ['b']}])

    def test_yaml_source_ambiguous_boolean_not_silently_copied(self):
        from taskweave_nacos.structured_update import selected_fields
        from taskweave.plugins.sdk import PluginError
        with self.assertRaises(PluginError):
            selected_fields('a: on\n', 'yaml', [['a']])
