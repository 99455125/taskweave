"""One confirmation action chooses trial evidence or explicit manual approval."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from taskweave.core.validation import TaskError
from taskweave.desktop.workbench import Workbench


class ConfirmationUi(unittest.TestCase):
    def test_success_missing_stale_evidence_and_cancel(self):
        async def scenario():
            for evidence, approval in [('success', True), ('missing', True), ('stale', True), ('missing', False)]:
                with self.subTest(evidence=evidence, approval=approval):
                    saved = {'step_id': 'step', 'content_hash': 'current'}
                    bench = object.__new__(Workbench)
                    bench.save_editor = AsyncMock(return_value=saved)
                    bench.trials = {} if evidence == 'missing' else {'step': 'trial'}
                    bench.environment_id = 'uat'
                    bench.edit_controls = {'code': 'current'}
                    bench.paint = AsyncMock()
                    bench.controller = SimpleNamespace(confirm=AsyncMock(return_value=saved), call=AsyncMock(return_value=saved))
                    if evidence == 'stale':
                        bench.controller.confirm.side_effect = TaskError('VALIDATION_EVIDENCE_INVALID')
                    class Dialog:
                        def __enter__(self): return self
                        def __exit__(self, *args): pass
                        def __await__(self):
                            async def answer(): return approval
                            return answer().__await__()
                    with patch('taskweave.desktop.workbench.ui', MagicMock()) as ui:
                        ui.dialog.return_value = Dialog()
                        await bench.confirm()
                        self.assertEqual(ui.dialog.call_count, 0 if evidence == 'success' else 1)
                    if evidence != 'success' and approval:
                        bench.controller.call.assert_awaited_once_with('step.confirm.manual', step_id='step', expected_hash='current', environment_id='uat')
                    else:
                        bench.controller.call.assert_not_awaited()
                    self.assertEqual(bench.paint.await_count, 1 if evidence == 'success' or approval else 0)
        asyncio.run(scenario())

    def test_ai_repair_selects_transport_or_cancels(self):
        async def scenario():
            for choice in ['api', 'chat', None]:
                bench = object.__new__(Workbench)
                bench.generate = AsyncMock()
                class Dialog:
                    def __enter__(self): return self
                    def __exit__(self, *args): pass
                    def __await__(self):
                        async def answer(): return choice
                        return answer().__await__()
                with patch('taskweave.desktop.workbench.ui', MagicMock()) as ui:
                    ui.dialog.return_value = Dialog()
                    await bench.choose_trial_ai()
                if choice is None:
                    bench.generate.assert_not_awaited()
                else:
                    bench.generate.assert_awaited_once_with(fix_logs=True, web_chat=choice == 'chat', supplement_override='', history_rounds=-1, deduplicate_history=True)
        asyncio.run(scenario())
