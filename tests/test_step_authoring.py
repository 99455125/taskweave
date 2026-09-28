"""Real application integration tests: spawn workers, SQLite and loopback HTTP."""
from taskweave.core.validation import TaskError, pointer, validate, content_tree
from taskweave.infrastructure.storage import uid
from tests._core_fixture import CoreFixture

class StepAuthoringTests(CoreFixture):
    def test_draft_confirmation_and_edits_invalidate(self):
        task = self.task()
        step = self.step(task)
        with self.assertRaises(TaskError):
            self.app.create_run(task)
        old = self.confirm(step)
        new = self.app.repo.save_step(
            task, {**old, "step_description": "new goal"}, old["step_id"], old["content_hash"]
        )
        self.assertEqual(new["validation_state"], "DRAFT")
        with self.assertRaisesRegex(TaskError, "EDIT_CONFLICT"):
            self.app.repo.save_step(task, old, old["step_id"], old["content_hash"])
        attempt = self.app.repo.query("SELECT attempt_id FROM step_attempts", one=True)[
            "attempt_id"
        ]
        with self.assertRaises(TaskError):
            self.app.confirm_step(new["step_id"], attempt, new["content_hash"])

    def test_binding_reorder_and_schema_validation(self):
        task = self.task()
        one = self.step(task)
        two = self.step(
            task,
            bindings={
                "x": {
                    "ref": {"source": "step", "step_id": one["step_id"], "pointer": ""}
                }
            },
        )
        with self.assertRaises(TaskError):
            self.app.repo.reorder(task, [two["step_id"], one["step_id"]])
        self.assertEqual(pointer({"a/b": {"~x": [42]}}, "/a~1b/~0x/0"), 42)
        for schema, value in [
            ({"type": "integer"}, True),
            ({"type": "object", "required": ["x"]}, {}),
            ({"type": "array", "items": {"type": "string"}}, [1]),
        ]:
            with self.assertRaises(TaskError):
                validate(value, schema)
        with self.assertRaises(TaskError):
            validate({}, {"$ref": "https://example.test/schema"})
        with self.assertRaises(TaskError):
            content_tree("import os\nasync def run(ctx, inputs): pass", [])

    def test_environment_change_invalidates_trial_evidence(self):
        task = self.task()
        step = self.step(task)
        environment = self.app.repo.save_environment("test", {"url": "first"})[
            "environment_id"
        ]
        trial = self.app.trial_step(step["step_id"], {}, uid(), environment)
        done = self.app.coordinator.wait(trial["run_id"])
        self.app.repo.save_environment(
            "test", {"url": "second"}, environment_id=environment
        )
        with self.assertRaisesRegex(TaskError, "ENVIRONMENT_CHANGED"):
            self.app.confirm_step(
                step["step_id"], done["attempts"][0]["attempt_id"], step["content_hash"]
            )
