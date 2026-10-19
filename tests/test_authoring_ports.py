"""Authoring owns policy, while injected sessions own plugin resources."""
import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from tests._core_fixture import CoreFixture, ScriptedModel
from taskweave.core.ports import ModelReply


class AuthoringSessionTests(CoreFixture):
    def test_generation_uses_injected_session_and_releases_on_model_failure(self):
        step = self.step(self.task(), capabilities=['demo.echo'])
        opened, closed = [], []
        class Session:
            context = SimpleNamespace()
            async def close(self): closed.append(True)
        def factory(**request):
            opened.append(request)
            return Session()
        self.app.authoring.resource_sessions = factory
        self.app.authoring.model = ScriptedModel([ModelReply()])
        with self.assertRaises(Exception):
            asyncio.run(self.app.authoring.generate(step['step_id'], step['content_hash']))
        self.assertEqual(len(opened), 1)
        self.assertEqual(opened[0]['scope'].task_id, step['task_id'])
        self.assertEqual(closed, [True])

    def test_export_does_not_open_a_resource_session(self):
        step = self.step(self.task())
        def forbidden(**request): raise AssertionError('export opened resources')
        self.app.authoring.resource_sessions = forbidden
        result = asyncio.run(self.app.authoring.generate(step['step_id'], step['content_hash'], export_only=True))
        self.assertIn('prompt', result)

    def test_public_contracts_describe_real_defaults_and_preserve_wire_records(self):
        from taskweave.application.operations import build_operation_contracts
        from taskweave.core.data_contracts import TaskRecord, StepRecord, RunSummary, CommandResult
        contracts = build_operation_contracts(self.app)
        self.assertEqual(contracts['run.start'].signature.parameters['mode'].default, 'ALL')
        self.assertIs(contracts['run.start'].signature.return_annotation, CommandResult)
        self.assertFalse(contracts['run.start'].lock_exempt)
        self.assertTrue(contracts['run.get'].lock_exempt)
        self.assertTrue(contracts['step.generate'].asynchronous)
        task = self.app.dispatch('task.create', {'name': 'contract'})
        step = self.step(task['task_id'])
        self.app.confirm_step_manual(step['step_id'], step['content_hash'])
        run = self.app.create_run(task['task_id'])
        for record, shape in ((task, TaskRecord), (step, StepRecord), (run, RunSummary)):
            self.assertTrue(shape.__required_keys__.issubset(record), (shape, record.keys()))

    def test_authoring_boundary_has_no_concrete_resource_construction(self):
        import ast
        from pathlib import Path
        path = Path(__file__).resolve().parents[1] / 'src/taskweave/application/authoring.py'
        tree = ast.parse(path.read_text())
        forbidden = {'Results', 'Resources', 'PluginContext'}
        self.assertEqual([node.func.id for node in ast.walk(tree)
                          if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                          and node.func.id in forbidden], [])
        self.assertFalse(any(isinstance(node, ast.ImportFrom) and
                             node.module == 'taskweave.infrastructure.worker' for node in ast.walk(tree)))

    def test_read_tool_receives_injected_context_and_closes_successful_session(self):
        from unittest.mock import AsyncMock
        from taskweave.core.ports import ToolCall
        step = self.step(self.task(), capabilities=['demo.echo'])
        context = SimpleNamespace(marker='injected context')
        session = SimpleNamespace(context=context, close=AsyncMock())
        self.app.authoring.resource_sessions = lambda **request: session
        tool = self.app.registry.tools['demo.echo']
        tool.execute = AsyncMock(return_value={'sample': 1})
        self.app.authoring.model = ScriptedModel([
            ModelReply(tool_calls=(ToolCall('one', 'demo.echo', {'sample': 1}),)),
            ModelReply('async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n'),
        ])
        asyncio.run(self.app.authoring.generate(step['step_id'], step['content_hash']))
        tool.execute.assert_awaited_once_with(context, {'sample': 1})
        session.close.assert_awaited_once()
