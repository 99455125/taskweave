"""Durable interval scheduling, task operations and desktop API evidence."""
import socket
import unittest
from taskweave.desktop.launcher import select_local_port

class DesktopPortTests(unittest.TestCase):
    def test_selected_port_can_bind_exact_server_address(self):
        port = select_local_port()
        self.assertGreater(port, 0)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", port))

class DesktopConnectionTraceTests(unittest.TestCase):
    def test_client_lifecycle_records_route_and_duration_without_business_fields(self):
        import asyncio
        import json
        import logging
        import tempfile
        from types import SimpleNamespace
        from nicegui.client import Client
        from nicegui.page import page
        from taskweave.desktop import launcher
        from taskweave.desktop.server_logs import ServerLogs
        client = Client(page('/connection-trace'))
        wb = SimpleNamespace(page='editor', task_id='private-task', step_id='private-step',
                             _debug_visible=True, code='private-code', document={'password':'private-password'})
        with tempfile.TemporaryDirectory() as home:
            logs = ServerLogs(home)
            logger = logging.getLogger('taskweave.desktop.launcher')
            prior_level = logger.level
            logger.setLevel(logging.INFO)
            logger.addHandler(logs)
            async def scenario():
                trace = getattr(launcher, 'install_client_trace', None)
                self.assertTrue(callable(trace), 'Missing event-based client connection diagnostics')
                record = trace(client, wb, native=True, requested_view='editor')
                client.tab_id = '11111111-1111-4111-8111-111111111111'
                for handler in client.connect_handlers:
                    client.safe_invoke(handler)
                client.tab_id = None
                for handler in client.disconnect_handlers:
                    client.safe_invoke(handler)
                client.tab_id = '11111111-1111-4111-8111-111111111111'
                for handler in client.connect_handlers:
                    client.safe_invoke(handler)
                record('page_ready')
                client.delete()
            try:
                asyncio.run(scenario())
                lines, _ = logs.after()
                records = [json.loads(text.split('UI_LIFECYCLE ',1)[1]) for _,text in lines]
                self.assertEqual([r['event'] for r in records],
                                 ['page_created','connected','socket_disconnected','connected','page_ready','client_deleted'])
                self.assertEqual({r['client_id'] for r in records}, {client.id})
                self.assertTrue(all(r['view']=='editor' and r['native'] and r['debug'] for r in records))
                self.assertEqual(records[2]['tab_id'], records[1]['tab_id'])
                self.assertFalse(records[2]['has_socket'])
                self.assertGreaterEqual(records[3]['since_disconnect_ms'], 0)
                text=logs.path.read_text()
                for private in ('private-task','private-step','private-code','private-password',home):
                    self.assertNotIn(private,text)
            finally:
                if client.id in Client.instances:
                    client.delete()
                logger.removeHandler(logs)
                logger.setLevel(prior_level)
                logs.close()

    def test_restore_failure_logs_public_kind_and_drops_arbitrary_route_and_tab_text(self):
        import asyncio
        import json
        import logging
        import tempfile
        from types import SimpleNamespace
        from nicegui.client import Client
        from nicegui.page import page
        from taskweave.desktop import launcher
        from taskweave.desktop.server_logs import ServerLogs
        client=Client(page('/connection-trace-failure'))
        client.tab_id='private-tab-text'
        wb=SimpleNamespace(page='private-route',task_id=None,step_id=None,_debug_visible=False)
        with tempfile.TemporaryDirectory() as home:
            logs=ServerLogs(home)
            logger=logging.getLogger('taskweave.desktop.launcher')
            prior_level=logger.level
            logger.setLevel(logging.INFO)
            logger.addHandler(logs)
            async def scenario():
                trace=getattr(launcher,'install_client_trace',None)
                self.assertTrue(callable(trace), 'Missing event-based client connection diagnostics')
                record=trace(client,wb,native=False,requested_view='private-requested-route')
                record('route_restore_failed',error=ValueError('private-exception-body'))
                client.delete()
            try:
                asyncio.run(scenario())
                rows,_=logs.after()
                text=logs.path.read_text()
                failure=json.loads(next(row for _,row in rows if 'route_restore_failed' in row).split('UI_LIFECYCLE ',1)[1])
                self.assertEqual(failure['error_type'],'ValueError')
                self.assertEqual(failure['requested_view'],'unknown')
                self.assertEqual(failure['view'],'unknown')
                self.assertIsNone(failure['tab_id'])
                from taskweave.core.validation import TaskError
                record = launcher.install_client_trace
                # Capture a public failure code without its private explanation.
                with Client(page('/public-restore-code')) as other:
                    try:
                        emit = record(other, wb, native=False, requested_view='editor')
                        emit('route_restore_failed', error=TaskError('NOT_FOUND', 'private-public-error-body'))
                        new_rows, _ = logs.after()
                        coded=json.loads(next(row for _,row in reversed(new_rows)
                            if 'route_restore_failed' in row).split('UI_LIFECYCLE ',1)[1])
                        self.assertEqual(coded.get('error_code'), 'NOT_FOUND')
                        self.assertNotIn('private-public-error-body', logs.path.read_text())
                    finally:
                        other.delete()
                for private in ('private-route','private-requested-route','private-tab-text','private-exception-body'):
                    self.assertNotIn(private,text)
            finally:
                if client.id in Client.instances:
                    client.delete()
                logger.removeHandler(logs)
                logger.setLevel(prior_level)
                logs.close()
