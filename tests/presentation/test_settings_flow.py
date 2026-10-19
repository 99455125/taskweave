"""Settings draft and command sequencing without UI controls."""
import unittest
from unittest.mock import AsyncMock
from types import SimpleNamespace


class SettingsFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_probe_saves_plain_draft_first_and_preserves_blank_secret(self):
        from taskweave.presentation.settings import SettingsSession
        events = []
        async def save(*args): events.append(('save', args))
        async def probe(): events.append(('probe',)); return {'connected': True}
        port = SimpleNamespace(save_model=save, test_model=probe)
        session = SettingsSession(port)
        session.load({'url': ' x ', 'model': ' m ', 'key_env': ' KEY '}, {}, {'ai_request_limit_kib': 20})
        outputs = [value async for value in session.test_model()]
        self.assertEqual(events, [('save', ('x', 'm', 'KEY', None)), ('probe',)])
        self.assertEqual(outputs, [None, {'connected': True}])
        self.assertEqual(session.draft['url'], ' x ')

    async def test_invalid_number_or_failed_save_retains_draft(self):
        from taskweave.presentation.settings import SettingsSession
        from taskweave.core.validation import TaskError
        port = SimpleNamespace(call=AsyncMock(side_effect=RuntimeError('offline')))
        session = SettingsSession(port)
        session.draft['request_limit'] = 1.5
        with self.assertRaises(TaskError): await session.save_limit()
        port.call.assert_not_awaited()
        session.draft['request_limit'] = 20
        with self.assertRaises(RuntimeError): await session.save_limit()
        self.assertEqual(session.draft['request_limit'], 20)
