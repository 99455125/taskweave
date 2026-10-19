import unittest


class PluginSelectionTests(unittest.TestCase):
    def test_filter_selection_and_disappearing_plugin_use_one_state(self):
        from taskweave.presentation.plugins import PluginSelection
        state = PluginSelection()
        rows = [{'id': 'a', 'enabled': True}, {'id': 'b', 'enabled': False}]
        state.load(rows)
        self.assertEqual(state.selected_plugin_id, 'a')
        state.selected_plugin_id = 'b'
        self.assertEqual(state.visible(), rows)
        state.status_filter = 'enabled'
        self.assertEqual(state.visible(), [rows[0]])
        self.assertEqual(state.selected_plugin_id, 'a')
        state.search_query = 'missing'
        self.assertEqual(state.visible(), [])
        self.assertIsNone(state.selected_plugin_id)
