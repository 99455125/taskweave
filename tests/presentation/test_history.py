import unittest
from taskweave.presentation.history import HistoryLoadState


class HistoryLoadTests(unittest.TestCase):
    def test_duplicate_closed_and_replaced_requests_are_rejected(self):
        state = HistoryLoadState(('task', 1))
        token = state.begin(('task', 1), visible=True)
        self.assertIsNotNone(token)
        self.assertIsNone(state.begin(('task', 1), visible=True))
        self.assertFalse(state.accepts(token, ('task', 1), visible=False))
        self.assertFalse(state.accepts(token, ('other', 1), visible=True))
        state.finish(token)
        self.assertFalse(state.loading)
        self.assertIsNotNone(state.begin(('task', 1), visible=True))

    def test_stale_finish_cannot_clear_new_loading(self):
        state = HistoryLoadState(('task', 1))
        first = state.begin(('task', 1), visible=True)
        state.finish(first)
        second = state.begin(('task', 1), visible=True)
        state.finish(first)
        self.assertTrue(state.loading)
        self.assertTrue(state.accepts(second, ('task', 1), visible=True))
