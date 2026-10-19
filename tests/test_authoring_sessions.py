"""One application owns retained AI requests across multiple desktop adapters."""
import asyncio
import tempfile
import threading
import unittest

from taskweave.application.service import Application
from taskweave.core.validation import TaskError
from taskweave.desktop.controller import DesktopController


class AuthoringSessionTests(unittest.TestCase):
    def test_two_controllers_share_request_and_waiter_cancel_does_not_cancel_work(self):
        entered, release = threading.Event(), threading.Event()
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            self.assertTrue(hasattr(app, 'authoring_requests'), 'retained requests belong to application')
            first, second = DesktopController(app), DesktopController(app)
            self.assertIs(first.authoring_requests, app.authoring_requests)
            self.assertIs(second.authoring_requests, app.authoring_requests)
            calls = []
            def dispatch(operation, params):
                calls.append(operation)
                entered.set()
                if not release.wait(5):
                    raise TimeoutError('fixture release')
                return {'proposed_content': 'candidate'}
            app.dispatch = dispatch
            saved = {'step_id': 'step', 'content_hash': 'h'}
            async def scenario():
                pending = asyncio.create_task(first.author_step('step.generate', saved, step_id='step'))
                try:
                    self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                    with self.assertRaises(TaskError) as caught:
                        await second.author_step('step.generate', saved, step_id='step')
                    self.assertEqual(caught.exception.code, 'AUTHORING_BUSY')
                    pending.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await pending
                    retained = second.authoring_request('step')
                    self.assertFalse(retained['task'].done())
                    release.set()
                    self.assertEqual(await asyncio.shield(retained['task']), {'proposed_content': 'candidate'})
                    self.assertEqual(calls, ['step.generate'])
                finally:
                    release.set()
            asyncio.run(scenario())
