"""The utility plugin supplies time, identifiers, and exact decimal arithmetic."""

import asyncio
from datetime import datetime
import tempfile
import unittest
from uuid import UUID

from taskweave.application.service import Application
from taskweave.core.validation import TaskError, validate
from taskweave.infrastructure.storage import uid
from taskweave.plugins.registry import Registry
from taskweave_utility import UtilityPlugin


class UtilityTests(unittest.TestCase):
    def test_actions_are_discoverable_and_time_is_timezone_aware(self):
        actions = Registry([UtilityPlugin()]).actions
        self.assertEqual(set(actions), {'utility.now', 'utility.uuid', 'utility.decimal'})
        result = asyncio.run(actions['utility.now'].execute(None, {'timezone': 'Asia/Shanghai'}))
        self.assertEqual(result['timezone'], 'Asia/Shanghai')
        self.assertEqual(result['compact'], datetime.fromisoformat(result['iso']).strftime('%Y%m%d%H%M%S'))
        self.assertEqual(result['iso'][-6:], '+08:00')
        with self.assertRaises(TaskError):
            asyncio.run(actions['utility.now'].execute(None, {'timezone': 'Not/AZone'}))

    def test_uuid_is_valid_and_changes_between_calls(self):
        action = UtilityPlugin().actions()['utility.uuid']
        first = asyncio.run(action.execute(None, {}))['value']
        second = asyncio.run(action.execute(None, {}))['value']
        self.assertEqual(UUID(first).version, 4)
        self.assertNotEqual(first, second)

    def test_decimal_is_exact_and_rejects_invalid_inputs(self):
        action = UtilityPlugin().actions()['utility.decimal']
        def calculate(operation, left, right, scale=2):
            return asyncio.run(action.execute(None, {
                'operation': operation, 'left': left, 'right': right, 'scale': scale,
            }))['value']
        self.assertEqual(calculate('add', '0.1', '0.2'), '0.30')
        self.assertEqual(calculate('multiply', '2.005', '1'), '2.01')
        self.assertEqual(calculate('divide', '10', '3'), '3.33')
        with self.assertRaises(TaskError):
            calculate('divide', '1', '0')
        with self.assertRaises(TaskError):
            calculate('add', 'NaN', '1')

    def test_decimal_result_schema_accepts_full_supported_operand_range(self):
        action = UtilityPlugin().actions()['utility.decimal']
        result = asyncio.run(action.execute(None, {
            'operation': 'multiply', 'left': '9' * 30, 'right': '9' * 30,
            'scale': 0,
        }))
        validate(result, action.spec.output_schema)

    def test_step_can_use_utility_actions_and_return_values(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            app.configure_plugin('utility', True)
            task_id = app.repo.create_task('编号与金额')['task_id']
            source = '''async def run(ctx, inputs):
    clock = await ctx.call("utility.now", {"timezone": "Asia/Shanghai"})
    amount = await ctx.call("utility.decimal", {"operation": "multiply", "left": "2.005", "right": "1", "scale": 2})
    return ctx.result(data={"contract_no": "hxy_auto_" + clock["compact"], "amount": amount["value"]})
'''
            step = app.repo.save_step(task_id, {
                'step_content': source,
                'capabilities': ['utility.now', 'utility.decimal'],
                'plugin_requirements': {'utility': '0.1.0'},
                'output_schema': {'type': 'object', 'properties': {
                    'contract_no': {'type': 'string'}, 'amount': {'type': 'string'},
                }, 'required': ['contract_no', 'amount']},
            })
            run = app.trial_step(step['step_id'], {}, uid())
            finished = app.coordinator.wait(run['run_id'], timeout=10)
            self.assertEqual(finished['status'], 'SUCCEEDED', finished['attempts'])
            data = app.repo.read_output(run['run_id'], step['step_id'])
            self.assertRegex(data['contract_no'], r'^hxy_auto_\d{14}$')
            self.assertEqual(data['amount'], '2.01')
