"""Acceptance is derived from frozen requirements and persisted observations."""

from tests._core_fixture import CoreFixture
from taskweave.core.validation import TaskError


class AgentReviewTests(CoreFixture):
    def test_report_pointer_cannot_extract_unredacted_sensitive_actual_value(self):
        task = self.task()
        step = self.step(task, source='async def run(ctx, inputs):\n    return ctx.result(data={"password": "private-value"})\n')
        self.app.steps.confirm_manual(step['step_id'], step['content_hash'])
        spec = self.reviews().prepare('task', task, self.app.tasks.definition_hash(task), '敏感结果核对', [{'id': 'sensitive', 'label': '存在', 'source': {'step_id': step['step_id'], 'pointer': '/password'}, 'op': 'exists'}])
        run = self.app.agent.execute('task.run', {'task_id': task, 'expected_hash': self.app.tasks.definition_hash(task)}, 'private-review', spec['review_spec_id'])
        self.app.agent.wait(run['run_id'], timeout=10)
        report = self.app.agent.review('read', {'kind': 'run', 'identity': run['run_id'], 'pointer': '/checks/0/actual'})
        self.assertNotIn('private-value', str(report))
    def test_sequence_requirements_do_not_follow_changed_member_definitions(self):
        task = self.task()
        step = self.step(task)
        self.app.steps.confirm_manual(step['step_id'], step['content_hash'])
        sequence = self.app.sequences.save('冻结成员', [{'node_id': 'one', 'task_id': task, 'environment_id': None, 'inputs': {}, 'step_inputs': {}}], {'type': 'object'})
        spec = self.reviews().prepare('sequence', sequence['sequence_id'], sequence['revision'], '原成员版本', [])
        refreshed = self.app.steps.save(task, {'name': '新成员动作', 'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data={"changed": True})\n'}, step_id=step['step_id'], expected_hash=step['content_hash'])
        self.app.steps.confirm_manual(step['step_id'], refreshed['content_hash'])
        with self.assertRaises(TaskError) as error:
            self.app.agent.execute('sequence.start', {'sequence_id': sequence['sequence_id'], 'inputs': {}}, 'stale-sequence-spec', spec['review_spec_id'])
        self.assertEqual(error.exception.code, 'REVIEW_VERSION_MISMATCH')
        run = self.app.agent.execute('sequence.start', {'sequence_id': sequence['sequence_id'], 'inputs': {}}, 'fresh-sequence-unconfigured')
        self.assertIsNone(self.reviews().read('sequence', run['sequence_run_id'])['review_spec_id'])
    def reviews(self):
        self.assertTrue(hasattr(self.app.agent, "reviews"), "Acceptance use cases are not implemented")
        return self.app.agent.reviews

    def prepare_run(self, value=7, expected=7, rule=None):
        task = self.task()
        step = self.step(task, source=f'async def run(ctx, inputs):\n    return ctx.result(data={{"value": {value!r}}})\n')
        self.app.steps.confirm_manual(step["step_id"], step["content_hash"])
        review = self.reviews().prepare("task", task, self.app.tasks.definition_hash(task), "核对业务值", [{
            "id": "value", "label": "业务值符合预期", "source": {"step_id": step["step_id"], "pointer": "/value"},
            **(rule or {"op": "eq", "expected": expected}),
        }])
        run = self.app.agent.execute("task.run", {"task_id": task, "expected_hash": self.app.tasks.definition_hash(task),
                                    "review_spec_id": review["review_spec_id"]}, "review-run-" + task)
        self.assertEqual(self.app.agent.wait(run["run_id"], timeout=10)["status"], "SUCCEEDED")
        return task, step, review, run

    def test_successful_run_has_distinct_automatic_and_human_states(self):
        _, _, spec, run = self.prepare_run()
        report = self.reviews().read("run", run["run_id"])
        self.assertEqual(report["review_spec_id"], spec["review_spec_id"])
        self.assertEqual(report["run_status"], "SUCCEEDED")
        self.assertEqual(report["automatic_status"], "PASS")
        self.assertEqual(report["human_status"], "UNREVIEWED")
        self.assertEqual(report["checks"][0]["actual"], 7)
        self.assertTrue(report["checks"][0]["evidence"])
        decision = self.reviews().decide("run", run["run_id"], report["fingerprint"], "ACCEPTED", "")
        self.assertEqual(decision["human_status"], "ACCEPTED")

    def test_runtime_success_does_not_hide_failed_business_check(self):
        _, _, _, run = self.prepare_run(value=3, expected=7)
        report = self.reviews().read("run", run["run_id"])
        self.assertEqual(report["run_status"], "SUCCEEDED")
        self.assertEqual(report["automatic_status"], "FAIL")
        self.assertEqual(report["human_status"], "UNREVIEWED")

    def test_boolean_and_number_are_not_equal(self):
        _, _, _, run = self.prepare_run(value=True, expected=1)
        self.assertEqual(self.reviews().read("run", run["run_id"])["automatic_status"], "FAIL")

    def test_no_requirements_are_not_automatic_acceptance(self):
        task = self.task()
        step = self.step(task)
        self.app.steps.confirm_manual(step["step_id"], step["content_hash"])
        run = self.app.agent.execute("task.run", {"task_id": task, "expected_hash": self.app.tasks.definition_hash(task)}, "unconfigured")
        self.app.agent.wait(run["run_id"], timeout=10)
        report = self.reviews().read("run", run["run_id"])
        self.assertEqual(report["automatic_status"], "UNCONFIGURED")
        self.assertEqual(report["human_status"], "UNREVIEWED")

    def test_frozen_requirements_are_reused_without_rewriting_on_each_launch(self):
        task, _, spec, run = self.prepare_run()
        self.app.agent.execute("instance.end", {"instance_type": "run", "owner_id": run["run_id"]}, "review-end")
        second = self.app.agent.execute("task.run", {"task_id": task, "expected_hash": self.app.tasks.definition_hash(task)}, "review-second")
        self.app.agent.wait(second["run_id"], timeout=10)
        self.assertEqual(self.reviews().read("run", second["run_id"])["review_spec_id"], spec["review_spec_id"])

    def test_tools_cannot_write_a_forged_human_decision(self):
        self.reviews()
        with self.assertRaises(TaskError) as error:
            self.app.agent.review("decide", {"kind": "run", "identity": "run", "actor": "human", "decision": "ACCEPTED"})
        self.assertEqual(error.exception.code, "AGENT_OPERATION_DENIED")

    def test_missing_and_real_null_are_distinguished(self):
        task, step, _, run = self.prepare_run(value=None, expected=None)
        report = self.reviews().read("run", run["run_id"])
        self.assertEqual(report["automatic_status"], "PASS")
        # New requirements belong to a future launch, not the existing run.
        self.reviews().prepare("task", task, self.app.tasks.definition_hash(task), "另一要求", [{
            "id": "missing", "label": "缺失值", "source": {"step_id": step["step_id"], "pointer": "/missing"},
            "op": "eq", "expected": None,
        }])
        self.assertEqual(self.reviews().read("run", run["run_id"])["checks"][0]["id"], "value")

    def test_sequence_checks_keep_repeated_task_nodes_separate(self):
        reviews = self.reviews()
        task = self.task()
        step = self.step(task, input_schema={"type": "object", "properties": {"value": {"type": "integer"}}})
        self.app.steps.confirm_manual(step["step_id"], step["content_hash"])
        nodes = [{"node_id": name, "task_id": task, "environment_id": None, "inputs": {},
                  "step_inputs": {step["step_id"]: {"value": {"kind": "literal", "value": value}}}}
                 for name, value in (("one", 1), ("two", 2))]
        sequence = self.app.sequences.save("逐项核对", nodes, {"type": "object"})
        checks = [{"id": name, "label": name, "source": {"node_id": name, "step_id": step["step_id"], "pointer": "/value"},
                   "op": "eq", "expected": value} for name, value in (("one", 1), ("two", 2))]
        spec = reviews.prepare("sequence", sequence["sequence_id"], sequence["revision"], "组合验收", checks)
        started = self.app.agent.execute("sequence.start", {"sequence_id": sequence["sequence_id"], "inputs": {}},
                                         "review-sequence", review_spec_id=spec["review_spec_id"])
        self.assertEqual(self.app.agent.wait(started["sequence_run_id"], kind="sequence", timeout=10)["status"], "SUCCEEDED")
        report = reviews.read("sequence", started["sequence_run_id"])
        self.assertEqual(report["automatic_status"], "PASS")
        self.assertEqual([check["actual"] for check in report["checks"]], [1, 2])
        self.assertNotEqual(report["checks"][0]["evidence"][0]["run_id"], report["checks"][1]["evidence"][0]["run_id"])

    def test_empty_all_is_true_and_empty_any_is_false(self):
        for operation, expected_status in (("all", "PASS"), ("any", "FAIL")):
            with self.subTest(operation=operation):
                _, _, _, run = self.prepare_run(value=[], rule={"op": operation, "check": {"op": "eq", "expected": 1}})
                self.assertEqual(self.reviews().read("run", run["run_id"])["automatic_status"], expected_status)

    def test_invalidated_result_makes_prior_human_decision_stale(self):
        _, _, _, run = self.prepare_run()
        reviews = self.reviews()
        report = reviews.read("run", run["run_id"])
        reviews.decide("run", run["run_id"], report["fingerprint"], "ACCEPTED", "")
        result_id = report["checks"][0]["evidence"][0]["result_ids"][0]
        self.app.agent.execute("instance.end", {"instance_type": "run", "owner_id": run["run_id"]}, "end-before-result-removal")
        self.app.runs.delete_result(result_id)
        changed = reviews.read("run", run["run_id"])
        self.assertEqual(changed["human_status"], "STALE")
        self.assertEqual(changed["automatic_status"], "MISSING")
        with self.assertRaises(TaskError) as error:
            reviews.decide("run", run["run_id"], report["fingerprint"], "ACCEPTED", "")
        self.assertEqual(error.exception.code, "REVIEW_STALE")

    def test_large_report_has_bounded_pages_and_a_stable_report_identity(self):
        task = self.task()
        text = "v" * 600
        step = self.step(task, source=f'async def run(ctx, inputs):\n    return ctx.result(data={{"value": {text!r}}})\n')
        self.app.steps.confirm_manual(step["step_id"], step["content_hash"])
        reviews = self.reviews()
        spec = reviews.prepare("task", task, self.app.tasks.definition_hash(task), "多项核对", [
            {"id": str(index), "label": f"第{index}项", "source": {"step_id": step["step_id"], "pointer": "/value"},
             "op": "eq", "expected": text} for index in range(40)])
        run = self.app.agent.execute("task.run", {"task_id": task, "expected_hash": self.app.tasks.definition_hash(task),
                                     "review_spec_id": spec["review_spec_id"]}, "large-review")
        self.app.agent.wait(run["run_id"], timeout=10)
        first = self.app.agent.review("read", {"kind": "run", "identity": run["run_id"]})
        self.assertEqual(first["check_count"], 40)
        self.assertLessEqual(len(first["checks"]), 10)
        following = self.app.agent.review("read", {"kind": "run", "identity": run["run_id"],
                    "cursor": first["checks_page"]["next_cursor"]})
        self.assertEqual(first["fingerprint"], following["fingerprint"])
        self.assertNotEqual(first["checks"][0]["id"], following["checks"][0]["id"])

    def test_report_page_compacts_many_evidence_references_before_applying_budget(self):
        from taskweave.application.agent.projection import review_view
        report = {"kind": "run", "identity": "run", "fingerprint": "fp", "path": [],
                  "checks": [{"id": "each", "status": "PASS", "evidence": [
                      {"attempt_id": "attempt-" + str(index), "execution_path": "/root/loop/" + str(index)} for index in range(1000)]}]}
        projected = review_view(report)
        self.assertEqual(projected["checks"][0]["evidence_total"], 1000)
        self.assertTrue(projected["checks"][0]["evidence_truncated"])

    def test_skipped_branch_is_not_confused_with_missing_business_value(self):
        reviews = self.reviews()
        task = self.task()
        first = self.step(task)
        second = self.step(task)
        for step in (first, second):
            self.app.steps.confirm_manual(step["step_id"], step["content_hash"])
        block = lambda node, step: {"id": node, "kind": "sequence", "children": [{"id": step["step_id"], "kind": "action", "step_id": step["step_id"]}]}
        flow = {"version": 2, "root": {"id": "root", "kind": "sequence", "children": [{"id": "choose", "kind": "if",
                "condition": {"op": "eq", "left": {"literal": 1}, "right": {"literal": 2}},
                "then": block("yes", first), "else": block("no", second)}]}}
        self.app.tasks.save_flow(task, flow, self.app.tasks.definition_hash(task))
        self.app.tasks.confirm_flow(task, self.app.tasks.definition_hash(task))
        spec = reviews.prepare("task", task, self.app.tasks.definition_hash(task), "分支适用性", [{
            "id": "first", "label": "仅在此分支执行时核对", "source": {"step_id": first["step_id"], "pointer": "/value"},
            "op": "eq", "expected": 7}])
        run = self.app.agent.execute("task.run", {"task_id": task, "expected_hash": self.app.tasks.definition_hash(task),
                                      "review_spec_id": spec["review_spec_id"]}, "skipped-check")
        self.app.agent.wait(run["run_id"], timeout=10)
        report = reviews.read("run", run["run_id"])
        self.assertEqual(report["checks"][0]["status"], "NOT_APPLICABLE")
        self.assertEqual(report["automatic_status"], "NOT_APPLICABLE")

    def test_every_loop_iteration_has_its_own_acceptance_evidence(self):
        reviews = self.reviews()
        task = self.task()
        step = self.step(task, bindings={"value": {"ref": {"source": "loop", "node_id": "each", "field": "item", "pointer": ""}}})
        flow = {"version": 2, "root": {"id": "root", "kind": "sequence", "children": [{"id": "each", "kind": "foreach",
                "items": {"literal": [2, 3]}, "body": {"id": "body", "kind": "sequence", "children": [
                    {"id": step["step_id"], "kind": "action", "step_id": step["step_id"]}]}}]}}
        self.app.tasks.save_flow(task, flow, self.app.tasks.definition_hash(task))
        self.app.steps.confirm_manual(step["step_id"], step["content_hash"])
        self.app.tasks.confirm_flow(task, self.app.tasks.definition_hash(task))
        spec = reviews.prepare("task", task, self.app.tasks.definition_hash(task), "每轮核对", [{
            "id": "each", "label": "每轮值至少为2", "source": {"step_id": step["step_id"], "item_pointer": "/value", "loop_node_id": "each"},
            "op": "all", "check": {"op": "gte", "expected": 2}}])
        run = self.app.agent.execute("task.run", {"task_id": task, "expected_hash": self.app.tasks.definition_hash(task),
                                      "review_spec_id": spec["review_spec_id"]}, "loop-check")
        self.app.agent.wait(run["run_id"], timeout=10)
        report = reviews.read("run", run["run_id"])
        self.assertEqual(report["automatic_status"], "PASS")
        check = report["checks"][0]
        self.assertEqual(check["actual"], [2, 3])
        self.assertEqual(len({item["execution_path"] for item in check["evidence"]}), 2)
