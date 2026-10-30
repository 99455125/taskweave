"""Desktop multi-branch editing preserves the version 2 flow contract."""

from copy import deepcopy
import unittest

from taskweave.core.flow_machine import advance_after_action, next_action
from taskweave.core.flow_values import aggregate_branch_output, aggregate_output
from taskweave.core.task_flow import validate_flow
from taskweave.core.validation import TaskError, pointer
from taskweave.desktop.components.flow_branches import (
    branch_output_values, build_branches, move_branch, new_branch,
    remove_branch, split_branches,
)


def seq(node_id, *children):
    return {"id": node_id, "kind": "sequence", "children": list(children)}


def action(step_id):
    return {"id": step_id, "kind": "action", "step_id": step_id}


def predicate(minimum):
    return {"op": "gte", "left": {"ref": {"source": "task", "pointer": "/amount"}},
            "right": {"literal": minimum}}


def branch_ref(node_id, *, path=None):
    ref = {"source": "branch", "node_id": node_id, "output": "chosen"}
    if path is not None:
        ref["pointer"] = path
    return {"ref": ref}


def chain():
    return {"id": "choose", "kind": "if", "parallel": False,
            "cases": [{"id": identity, "condition": predicate(limit), "body": seq(body, action(step))}
                      for identity, limit, body, step in [("choose", 100, "then-1", "large"),
                          ("case-2", 10, "then-2", "normal"), ("case-3", 1, "then-3", "small")]],
            "default": {"id": "default", "body": seq("fallback", action("invalid"))},
            "outputs": {"chosen": {key: {"literal": value} for key, value in
                        [("choose", "large"), ("case-2", "normal"), ("case-3", "small"), ("default", "invalid")]}}}


def step_definitions(node):
    result = []

    def visit(value):
        if isinstance(value, dict):
            if value.get("kind") == "action":
                result.append({"step_id": value["step_id"], "bindings": {}})
            else:
                for child in value.values():
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(node)
    return result


def drive(flow, amount=0):
    """Exercise real decisions and branch aggregation, without running plugins."""
    cursor = None
    visits, actions, results = [], [], {}

    def read(binding, current):
        if "literal" in binding:
            return binding["literal"]
        ref = binding["ref"]
        if ref["source"] == "task":
            value = {"amount": amount}
        elif ref["source"] == "loop":
            frame = next(frame for frame in current["frames"] if frame["node_id"] == ref["node_id"])
            value = frame["items"][frame["index"]] if ref["field"] == "item" else frame["index"]
        elif ref["source"] == "branch":
            value = aggregate_branch_output(flow, visits, ref["node_id"], ref["output"],
                                            lambda mapping, *_: read(mapping, current),
                                            active_frames=current["frames"])
        elif ref["source"] == "step":
            value = aggregate_output(flow, visits, ref["step_id"], ref.get("output", "data"),
                                     lambda attempt_id, _: results[attempt_id], active_frames=current["frames"])
        else:
            raise AssertionError(f"Unexpected source: {ref['source']}")
        return pointer(value, ref.get("pointer", ""))

    for _ in range(100):
        transition = next_action(flow, cursor, read)
        visits.extend(transition["instances"])
        cursor = transition["cursor"]
        if transition["done"]:
            return actions, visits, lambda binding: read(binding, cursor)
        if transition["action"]:
            actions.append(transition["action"]["step_id"])
            attempt_id = f"attempt-{len(actions)}"
            results[attempt_id] = {"category": actions[-1]}
            transition = advance_after_action(flow, cursor, attempt_id, execution_path=transition["action"]["execution_path"])
            visits.extend(transition["instances"])
            cursor = transition["cursor"]
    raise AssertionError("Flow failed to finish")


class FlowBranchesTests(unittest.TestCase):
    def test_cases_roundtrip_without_dirtying_or_aliasing_original(self):
        original = chain()
        before = deepcopy(original)
        cases, fallback = split_branches(original)
        names, defaults = branch_output_values(original)
        self.assertEqual([case["id"] for case in cases], ["choose", "case-2", "case-3"])
        self.assertEqual(fallback["id"], "fallback")
        self.assertEqual(names, ["chosen"])
        self.assertEqual(defaults, {"chosen": {"literal": "invalid"}})
        rebuilt = build_branches(original, cases, fallback, names)
        self.assertEqual(rebuilt, original)
        cases[0]["condition"]["right"]["literal"] = -1
        fallback["children"].clear()
        rebuilt["cases"][0]["body"]["children"].clear()
        defaults["chosen"]["literal"] = "changed"
        self.assertEqual(original, before)

    def test_nested_default_subtree_is_retained_without_flattening(self):
        original = chain()
        original["default"]["body"] = seq("nested-fallback", chain())
        cases, fallback = split_branches(original)
        self.assertEqual(len(cases), 3)
        self.assertEqual(fallback, original["default"]["body"])
        self.assertEqual(build_branches(original, cases, fallback, ["chosen"]), original)

    def test_first_middle_last_and_fallback_execute_with_public_output(self):
        original = chain()
        cases, fallback = split_branches(original)
        rebuilt = build_branches(original, cases, fallback, ["chosen"])
        flow = {"version": 2, "root": seq("root", rebuilt, action("joined"))}
        steps = step_definitions(flow)
        steps[-1]["bindings"] = {"value": branch_ref("choose")}
        validate_flow(flow, steps)
        for amount, chosen in [(100, "large"), (50, "normal"), (2, "small"), (0, "invalid")]:
            with self.subTest(amount=amount):
                actions, _, read = drive(flow, amount)
                self.assertEqual(actions, [chosen, "joined"])
                self.assertEqual(read(branch_ref("choose")), chosen)

    def test_reordering_moves_path_and_output_together_and_keeps_structural_ids(self):
        original = chain()
        cases, fallback = split_branches(original)
        moved = move_branch(cases, 1, 0)
        self.assertEqual([case["id"] for case in moved], ["choose", "case-2", "case-3"])
        self.assertEqual([case["then"]["id"] for case in moved], ["then-2", "then-1", "then-3"])
        rebuilt = build_branches(original, moved, fallback, ["chosen"])
        self.assertEqual(rebuilt["id"], "choose")
        self.assertEqual(rebuilt["default"]["id"], "default")
        self.assertEqual([case["id"] for case in rebuilt["cases"]], ["choose", "case-2", "case-3"])
        flow = {"version": 2, "root": seq("root", rebuilt)}
        validate_flow(flow, step_definitions(flow))
        actions, _, read = drive(flow, 100)
        self.assertEqual(actions, ["normal"])
        self.assertEqual(read(branch_ref("choose")), "normal")
        self.assertEqual(cases[0]["then"]["id"], "then-1")

    def test_append_preserves_default_path_output_and_stable_ids_across_reads(self):
        original = chain()
        cases, fallback = split_branches(original)
        added = new_branch(values={"chosen": {"literal": "new"}})
        cases.append(added)
        rebuilt = build_branches(original, cases, fallback, ["chosen"])
        self.assertEqual(build_branches(original, cases, fallback, ["chosen"]), rebuilt)
        loaded, loaded_fallback = split_branches(rebuilt)
        self.assertEqual(len(loaded), 4)
        self.assertEqual(loaded_fallback, original["default"]["body"])
        self.assertEqual(loaded[-1]["id"], added["id"])
        flow = {"version": 2, "root": seq("root", rebuilt)}
        validate_flow(flow, step_definitions(flow))
        actions, _, read = drive(flow, 0)
        self.assertEqual(actions, ["invalid"])
        self.assertEqual(read(branch_ref("choose")), "invalid")

    def test_new_branch_requires_explicit_existing_public_outputs(self):
        original = chain()
        cases, fallback = split_branches(original)
        cases.append(new_branch())
        with self.assertRaises(TaskError) as error:
            build_branches(original, cases, fallback, ["chosen"])
        self.assertEqual(error.exception.code, "FORM_INVALID")

    def test_new_output_requires_explicit_fallback_value(self):
        original = chain()
        cases, fallback = split_branches(original)
        for case in cases:
            case["values"]["amount"] = {"literal": 1}
        with self.assertRaises(TaskError):
            build_branches(original, cases, fallback, ["chosen", "amount"])
        updated = build_branches(original, cases, fallback, ["chosen", "amount"],
                                 fallback_values={"chosen": {"literal": "invalid"}, "amount": {"literal": 0}})
        flow = {"version": 2, "root": seq("root", updated)}
        validate_flow(flow, step_definitions(flow))
        _, _, read = drive(flow, 0)
        self.assertEqual(read({"ref": {"source": "branch", "node_id": "choose", "output": "amount"}}), 0)

    def test_remove_only_empty_branch_and_keep_default_and_remaining_paths(self):
        original = chain()
        original["cases"][1]["body"]["children"] = []
        cases, fallback = split_branches(original)
        removed = remove_branch(cases, 1)
        self.assertEqual([case["then"]["id"] for case in removed], ["then-1", "then-3"])
        rebuilt = build_branches(original, removed, fallback, ["chosen"])
        flow = {"version": 2, "root": seq("root", rebuilt)}
        validate_flow(flow, step_definitions(flow))
        for amount, expected in [(50, "small"), (0, "invalid")]:
            actions, _, read = drive(flow, amount)
            self.assertEqual(actions, [expected])
            self.assertEqual(read(branch_ref("choose")), expected)
        self.assertEqual(len(cases), 3)
        with self.assertRaises(TaskError):
            remove_branch(cases, 0)
        only = [new_branch()]
        with self.assertRaises(TaskError):
            remove_branch(only, 0)

    def test_empty_output_fields_are_not_added_when_absent_in_existing_tree(self):
        original = chain()
        original.pop("outputs")
        cases, fallback = split_branches(original)
        self.assertEqual(len(cases), 3)
        self.assertEqual(build_branches(original, cases, fallback, []), original)

    def test_depth_limit_and_loop_scope_are_still_enforced_by_existing_validator(self):
        original = {"id": "choose", "kind": "if", "cases": [{"id": "match", "condition": predicate(0), "body": seq("first")}], "default": {"id": "default", "body": seq("fallback")}}
        cases, fallback = split_branches(original)
        cases.extend(new_branch() for _ in range(6))
        cases[1]["condition"] = {"op": "eq", "left": {"ref": {
            "source": "loop", "node_id": "each", "field": "item"}}, "right": {"literal": "yes"}}
        built = build_branches(original, cases, fallback, [])
        flow = {"version": 2, "root": seq("root", {"id": "each", "kind": "foreach",
                "items": {"literal": ["yes"]}, "body": seq("body", built)})}
        validate_flow(flow, [])
        invalid_scope = {"version": 2, "root": seq("root", built)}
        with self.assertRaises(TaskError) as missing_loop:
            validate_flow(invalid_scope, [])
        self.assertEqual(missing_loop.exception.code, "FLOW_REFERENCE_INVALID")
        # Sibling cases do not increase nesting depth; nested control blocks do.
        nested = built
        for index in range(8):
            nested = {"id": f"loop-{index}", "kind": "foreach", "items": {"literal": []},
                      "body": seq(f"body-{index}", nested)}
        flow["root"]["children"][0]["body"]["children"][0] = nested
        with self.assertRaises(TaskError) as too_deep:
            validate_flow(flow, [])
        self.assertEqual(too_deep.exception.code, "FLOW_DEPTH_EXCEEDED")

    def test_multi_branch_decisions_execute_in_each_loop_iteration(self):
        original = chain()
        cases, fallback = split_branches(original)
        for index, case in enumerate(cases):
            case["condition"] = {"op": "eq", "left": {"ref": {
                "source": "loop", "node_id": "each", "field": "item"}}, "right": {"literal": index}}
        built = build_branches(original, cases, fallback, ["chosen"])
        flow = {"version": 2, "root": seq("root", {"id": "each", "kind": "foreach",
                "items": {"literal": [0, 1, 2, 3]}, "body": seq("body", built)})}
        validate_flow(flow, step_definitions(flow))
        actions, _, _ = drive(flow)
        self.assertEqual(actions, ["large", "normal", "small", "invalid"])

    def test_step_reference_outputs_survive_sorting_and_default_passthrough(self):
        original = chain()
        cases, fallback = split_branches(original)
        for case, step_id in zip(cases, ["large", "normal", "small"]):
            case["values"]["chosen"] = {"ref": {
                "source": "step", "step_id": step_id, "output": "data", "pointer": "/category"}}
        fallback_values = {"chosen": {"ref": {
            "source": "step", "step_id": "invalid", "output": "data", "pointer": "/category"}}}
        built = build_branches(original, move_branch(cases, 2, 0), fallback, ["chosen"],
                               fallback_values=fallback_values)
        flow = {"version": 2, "root": seq("root", built, action("joined"))}
        steps = step_definitions(flow)
        steps[-1]["bindings"] = {"picked": branch_ref("choose")}
        validate_flow(flow, steps)
        for amount, expected in [(100, "small"), (0, "invalid")]:
            with self.subTest(amount=amount):
                actions, _, read = drive(flow, amount)
                self.assertEqual(actions, [expected, "joined"])
                self.assertEqual(read(branch_ref("choose")), expected)

    def test_delete_empty_first_or_last_branch_preserves_every_other_step(self):
        for index, expected_steps, amount, selected in [
                (0, ["normal", "small", "invalid"], 100, "normal"),
                (2, ["large", "normal", "invalid"], 1, "invalid")]:
            with self.subTest(index=index):
                original = chain()
                cases, fallback = split_branches(original)
                cases[index]["then"]["children"] = []
                built = build_branches(original, remove_branch(cases, index), fallback, ["chosen"])
                flow = {"version": 2, "root": seq("root", built)}
                definitions = step_definitions(flow)
                self.assertEqual([step["step_id"] for step in definitions], expected_steps)
                validate_flow(flow, definitions)
                actions, _, read = drive(flow, amount)
                self.assertEqual(actions, [selected])
                self.assertEqual(read(branch_ref("choose")), selected)

    def test_invalid_branch_edits_do_not_mutate_existing_state(self):
        original = chain()
        before = deepcopy(original)
        cases, fallback = split_branches(original)
        before_cases = deepcopy(cases)
        for index, target in [(-1, 0), (0, 3), (True, 0)]:
            with self.subTest(index=index, target=target), self.assertRaises(TaskError):
                move_branch(cases, index, target)
        for index in [-1, 3, False]:
            with self.subTest(index=index), self.assertRaises(TaskError):
                remove_branch(cases, index)
        for names in [["chosen", "chosen"], [""], [None]]:
            with self.subTest(names=names), self.assertRaises(TaskError):
                build_branches(original, cases, fallback, names)
        with self.assertRaises(TaskError):
            build_branches(original, [], fallback, ["chosen"])
        self.assertEqual(original, before)
        self.assertEqual(cases, before_cases)


if __name__ == "__main__":
    unittest.main()
