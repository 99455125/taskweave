"""Loopback authorization removes only its token, retaining the requested route."""

import asyncio
import unittest
from urllib.parse import parse_qs, urlsplit

from taskweave.desktop.security import LocalAccess


class LocalAccessTests(unittest.TestCase):
    def response(self, query, *, path='/', host='127.0.0.1:1234', origin=None, cookie=None, kind='http'):
        messages, forwarded = [], []
        async def application(scope, receive, send):
            forwarded.append(scope)
            await send({'type': 'http.response.start', 'status': 200, 'headers': []})
            await send({'type': 'http.response.body', 'body': b'ok'})
        async def receive(): return {'type': 'http.request', 'body': b''}
        async def send(message): messages.append(message)
        headers = [(b'host', host.encode())]
        if origin:
            headers.append((b'origin', origin.encode()))
        if cookie:
            headers.append((b'cookie', cookie.encode()))
        scope = {'type': kind, 'path': path, 'headers': headers, 'query_string': query.encode()}
        asyncio.run(LocalAccess(application, 'temporary-token', 1234)(scope, receive, send))
        return messages, forwarded

    def test_authorization_redirect_preserves_route_and_removes_all_access_parameters(self):
        response, forwarded = self.response('view=editor&task_id=task&step_id=step&debug=true&access=temporary-token&access=discard&empty=')
        self.assertFalse(forwarded)
        self.assertEqual(response[0]['status'], 303)
        headers = dict(response[0]['headers'])
        location = urlsplit(headers[b'location'].decode())
        self.assertEqual(location.path, '/')
        self.assertEqual(parse_qs(location.query, keep_blank_values=True), {
            'view': ['editor'], 'task_id': ['task'], 'step_id': ['step'], 'debug': ['true'], 'empty': [''],
        })
        self.assertIn(b'HttpOnly', headers[b'set-cookie'])
        self.assertIn(b'SameSite=strict', headers[b'set-cookie'])

    def test_logs_redirect_keeps_query_as_data_on_the_same_path(self):
        response, _ = self.response('access=temporary-token&filter=%E4%B8%AD%E6%96%87&target=https%3A%2F%2Fexample.com', path='/logs')
        location = urlsplit(dict(response[0]['headers'])[b'location'].decode())
        self.assertEqual(location.path, '/logs')
        self.assertFalse(location.netloc)
        self.assertEqual(parse_qs(location.query).get('filter'), ['中文'])

    def test_wrong_token_host_origin_and_missing_socket_cookie_remain_denied(self):
        for query, parameters in (
            ('access=wrong', {}),
            ('access=temporary-token', {'host': 'example.com'}),
            ('access=temporary-token', {'origin': 'https://example.com'}),
            ('access=temporary-token', {'path': '/probe'}),
        ):
            with self.subTest(parameters=parameters):
                response, forwarded = self.response(query, **parameters)
                self.assertFalse(forwarded)
                self.assertEqual(response[0]['status'], 403)
        response, forwarded = self.response('', kind='websocket')
        self.assertFalse(forwarded)
        self.assertEqual(response, [{'type': 'websocket.close', 'code': 1008}])

    def test_existing_local_cookie_still_forwards_the_original_route(self):
        response, forwarded = self.response('view=editor&step_id=step', cookie='taskweave_1234=temporary-token')
        self.assertEqual(response[0]['status'], 200)
        self.assertEqual(forwarded[0]['query_string'], b'view=editor&step_id=step')
