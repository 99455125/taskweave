"""Authenticated connections reuse the existing application owner."""
import json
import unittest
import asyncio
import importlib.util
import sys
from tests._core_fixture import CoreFixture
from taskweave.core.validation import TaskError


class AgentTransportTests(CoreFixture):
    @unittest.skipUnless(importlib.util.find_spec('mcp'), 'optional mcp extra')
    def test_official_sdk_stdio_handshake_and_live_owner_call(self):
        from mcp import Client
        from mcp.client.stdio import StdioServerParameters
        from taskweave.infrastructure.agent_connection import AgentHost
        async def exercise():
            process = StdioServerParameters(command=sys.executable, args=['-m', 'taskweave', '--home', str(self.home), 'mcp'])
            async with Client(process) as client:
                listing = await client.list_tools()
                self.assertEqual(len(listing.tools), 8)
                called = await client.call_tool('taskweave_discover', {'kind': 'task'})
                self.assertFalse(called.is_error)
                self.assertEqual(json.loads(called.content[0].text)['total'], 0)
                error = await client.call_tool('taskweave_execute', {'operation': 'ai.settings.get', 'params': {}, 'request_id': 'denied'})
                self.assertTrue(error.is_error)
                self.assertIn('AGENT_OPERATION_DENIED', error.content[0].text)
                async def call(purpose, arguments):
                    response = await client.call_tool('taskweave_' + purpose, arguments)
                    self.assertFalse(response.is_error, response.content)
                    return json.loads(response.content[0].text)
                task = await call('author', {'operation': 'task.create', 'params': {'name': 'SDK 编写验证'}, 'request_id': 'sdk-task'})
                await call('describe', {'kind': 'operation', 'identity': 'step.save'})
                await call('author', {'operation': 'materials', 'params': {'task_id': task['task_id']}})
                step = await call('author', {'operation': 'step.save', 'params': {'task_id': task['task_id'], 'document': {
                    'name': '返回业务值', 'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data={"value": 7})\n'}}, 'request_id': 'sdk-step'})
                trial = await call('execute', {'operation': 'step.trial', 'params': {'step_id': step['step_id'], 'inputs': {}}, 'request_id': 'sdk-trial'})
                self.assertEqual((await call('wait', {'identity': trial['run_id'], 'timeout': 10}))['status'], 'SUCCEEDED')
                evidence = await call('inspect', {'kind': 'run', 'identity': trial['run_id'], 'sections': ['attempts']})
                await call('execute', {'operation': 'step.confirm', 'params': {'step_id': step['step_id'], 'expected_hash': step['content_hash'], 'attempt_id': evidence['attempts'][0]['attempt_id']}, 'request_id': 'sdk-confirm'})
                await call('execute', {'operation': 'instance.end', 'params': {'instance_type': 'run', 'owner_id': trial['run_id']}, 'request_id': 'sdk-end'})
                current = await call('describe', {'kind': 'task', 'identity': task['task_id']})
                spec = await call('review', {'action': 'prepare', 'params': {'target_kind': 'task', 'target_id': task['task_id'], 'expected_version': current['definition_hash'],
                    'title': '业务值为7', 'checks': [{'id': 'value', 'label': '值等于7', 'source': {'step_id': step['step_id'], 'pointer': '/value'}, 'op': 'eq', 'expected': 7}]}})
                run = await call('execute', {'operation': 'task.run', 'params': {'task_id': task['task_id'], 'expected_hash': current['definition_hash']}, 'review_spec_id': spec['review_spec_id'], 'request_id': 'sdk-launch'})
                self.assertEqual((await call('wait', {'identity': run['run_id'], 'timeout': 10}))['status'], 'SUCCEEDED')
                report = await call('review', {'action': 'read', 'params': {'kind': 'run', 'identity': run['run_id']}})
                self.assertEqual(report['automatic_status'], 'PASS')
                self.assertEqual(report['human_status'], 'UNREVIEWED')
        with AgentHost(self.app):
            asyncio.run(exercise())
    def test_owner_discovery_handshake_tools_and_cleanup(self):
        from taskweave.infrastructure.agent_connection import AgentHost, AgentClient
        from taskweave.integration.tools import tool_definitions, invoke
        with AgentHost(self.app):
            client = AgentClient(self.home)
            tools = tool_definitions()
            self.assertEqual(len(tools), 8)
            self.assertEqual(invoke(client, 'taskweave_discover', {'kind': 'task'})['total'], 0)
            descriptor = json.loads((self.home / 'agent-connection.json').read_text())
            self.assertNotIn(descriptor['token'], json.dumps(tools))
            descriptor['instance_id'] = 'stale'
            (self.home / 'agent-connection.json').write_text(json.dumps(descriptor))
            with self.assertRaises(TaskError) as error:
                client.call('agent.discover', {'kind': 'task'})
            self.assertEqual(error.exception.code, 'AGENT_CONNECTION_STALE')
            descriptor['instance_id'] = client._send(descriptor, 'agent.identity', {})['instance_id']
            (self.home / 'agent-connection.json').write_text(json.dumps(descriptor))
        self.assertFalse((self.home / 'agent-connection.json').exists())

    def test_missing_owner_does_not_create_application(self):
        from taskweave.infrastructure.agent_connection import AgentClient
        with self.assertRaises(TaskError) as error:
            AgentClient(self.home).call('agent.discover', {'kind': 'task'})
        self.assertEqual(error.exception.code, 'AGENT_OWNER_UNAVAILABLE')

    def test_tool_boundary_rejects_unknown_parameters_and_operations(self):
        from taskweave.integration.tools import invoke
        for name, args in [('taskweave_discover', {'kind': 'task', 'typo': True}),
                           ('config.set', {}), ('taskweave_context', {'operation': 'x', 'params': {}, 'include_images': 'false'})]:
            with self.subTest(name=name), self.assertRaises(TaskError):
                invoke(None, name, args)
