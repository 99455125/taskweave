"""Live logs are opt-in, incremental, bounded and tied to their original view."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from nicegui.client import Client
from nicegui.page import page


class RunLogTests(unittest.TestCase):
    def test_stopped_or_failed_log_read_can_still_be_closed(self):
        from taskweave.desktop.components.run_logs import LiveRunLogs
        client = Client(page('/live-log-stop'))
        async def scenario():
            with client:
                for response in ({'events': [], 'cursor': 7, 'has_more': False, 'reset': False,
                                  'status': 'SUCCEEDED'}, RuntimeError('read failed')):
                    controller = SimpleNamespace(call=AsyncMock(side_effect=[response, response]))
                    viewer = LiveRunLogs(controller, 'r', lambda: True)
                    await viewer.toggle()
                    self.assertTrue(viewer.area.visible)
                    self.assertFalse(viewer.timer.active)
                    await viewer.toggle()
                    self.assertFalse(viewer.area.visible)
                    self.assertEqual(controller.call.await_count, 1)
                    await viewer.toggle()
                    self.assertTrue(viewer.area.visible)
                    self.assertEqual(controller.call.await_count, 2)
                    viewer.dispose()
        try:
            asyncio.run(scenario())
        finally:
            client.delete()

    def test_live_logs_only_read_when_open_visible_and_current(self):
        from taskweave.desktop.components.run_logs import LiveRunLogs
        client = Client(page('/live-log-test'))
        async def scenario():
            visible, current = [True], [True]
            controller = SimpleNamespace(call=AsyncMock(return_value={
                'events': [{'kind': 'Test', 'payload_json': '{"message":"中文日志"}'}],
                'cursor': 17, 'has_more': False, 'reset': False, 'status': 'RUNNING'}))
            with client:
                viewer = LiveRunLogs(controller, 'r', lambda: current[0], allowed=lambda: visible[0])
                await viewer.poll()
                controller.call.assert_not_awaited()
                await viewer.toggle()
                self.assertIn('中文日志', viewer.output.value)
                self.assertEqual(viewer.cursor, 17)
                visible[0] = False
                await viewer.poll()
                self.assertEqual(controller.call.await_count, 1)
                visible[0] = True
                await viewer.poll()
                self.assertEqual(controller.call.await_args.kwargs['after'], 17)
                await viewer.toggle()
                await viewer.poll()
                self.assertEqual(controller.call.await_count, 2)
                current[0] = False
                await viewer.toggle()
                self.assertEqual(controller.call.await_count, 2)
                viewer.dispose()
        try:
            asyncio.run(scenario())
        finally:
            client.delete()

    def test_late_and_overlapping_log_queries_do_not_write_to_new_view(self):
        from taskweave.desktop.components.run_logs import LiveRunLogs
        client = Client(page('/live-log-late'))
        async def scenario():
            entered, release = asyncio.Event(), asyncio.Event()
            current = [True]
            async def call(*args, **kwargs):
                entered.set()
                await release.wait()
                return {'events': [{'kind': 'late'}], 'cursor': 4, 'reset': False,
                        'has_more': False, 'status': 'RUNNING'}
            controller = SimpleNamespace(call=AsyncMock(side_effect=call))
            with client:
                viewer = LiveRunLogs(controller, 'r', lambda: current[0])
                pending = asyncio.create_task(viewer.toggle())
                await entered.wait()
                await viewer.poll()
                self.assertEqual(controller.call.await_count, 1)
                current[0] = False
                release.set()
                await pending
                self.assertEqual(viewer.output.value, '')
                self.assertEqual(viewer.cursor, 0)
                viewer.dispose()
        try:
            asyncio.run(scenario())
        finally:
            client.delete()
