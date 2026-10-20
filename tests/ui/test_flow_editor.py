"""Flow tree editing keeps action identity and rejects destructive moves."""

import unittest

from taskweave.core.task_flow import validate_flow
from taskweave.core.validation import TaskError
from taskweave.presentation.flow_editor import insert_control, move_node, remove_control, update_control


class FlowEditorTests(unittest.TestCase):
    def setUp(self):
        self.flow = {"version": 2, "root": {"id": "root", "kind": "sequence", "children": [
            {"id": "step-a", "kind": "action", "step_id": "step-a"},
            {"id": "step-b", "kind": "action", "step_id": "step-b"},
        ]}}

    def test_insert_move_update_and_remove_control(self):
        flow, control_id = insert_control(self.flow, "foreach", index=1)
        flow = move_node(flow, "step-b", control_id + "-body")
        flow = update_control(flow, control_id, {"items": {"literal": [1, 2]}, "max_items": 2})
        validate_flow(flow, [{"step_id": "step-a"}, {"step_id": "step-b"}])
        self.assertEqual(flow["root"]["children"][1]["body"]["children"][0]["step_id"], "step-b")
        with self.assertRaises(TaskError):
            remove_control(flow, control_id)
        flow = move_node(flow, "step-b", "root")
        flow = remove_control(flow, control_id)
        self.assertEqual([node["step_id"] for node in flow["root"]["children"]], ["step-a", "step-b"])

    def test_reject_move_into_own_body(self):
        flow, control_id = insert_control(self.flow, "loop")
        with self.assertRaises(TaskError):
            move_node(flow, control_id, control_id + "-body")

    def test_run_history_recognizes_iteration_paths(self):
        from taskweave.desktop.components.execution_details import controlled_run, round_label
        import json
        self.assertEqual(round_label('/root/each/0/body/inner/2/body/action'), '第 1 轮 / 第 3 轮')
        flow, _ = insert_control(self.flow, 'foreach')
        self.assertTrue(controlled_run({'definition_json': json.dumps({'flow': flow})}))
        self.assertFalse(controlled_run({'definition_json': json.dumps({'flow': self.flow})}))


if __name__ == "__main__":
    unittest.main()
