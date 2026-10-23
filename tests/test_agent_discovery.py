"""External AI discovery stays small and exposes real, selected contracts."""

import json
import unittest

from tests._core_fixture import CoreFixture
from taskweave.core.validation import TaskError


def discovery(app):
    try:
        from taskweave.application.agent.discovery import AgentDiscovery
    except ModuleNotFoundError as exc:
        raise AssertionError("AI discovery is not implemented") from exc
    return AgentDiscovery(app)


class AgentDiscoveryTests(CoreFixture):
    def test_operation_names_and_acceptance_schema_are_discoverable(self):
        api = discovery(self.app)
        result = api.discover('operation', query='review.prepare')
        self.assertEqual(result['items'][0]['id'], 'review.prepare')
        contract = api.describe('operation', 'review.prepare')['parameters']
        import jsonschema
        jsonschema.Draft202012Validator.check_schema(contract)
        self.assertIn('checks', contract['properties'])
    def test_search_pages_stably_without_returning_step_code(self):
        ids = [self.app.tasks.create(f"通用示例检查 {i}")["task_id"] for i in range(3)]
        self.step(ids[0])
        api = discovery(self.app)
        page = api.discover("task", query="通用示例", limit=2)
        following = api.discover("task", query="通用示例", cursor=page["next_cursor"], limit=2)
        self.assertEqual(len(page["items"]), 2)
        self.assertEqual(len(following["items"]), 1)
        self.assertEqual({r["id"] for r in page["items"] + following["items"]}, set(ids))
        self.assertNotIn("step_content", json.dumps(page))
        self.assertIsNone(following["next_cursor"])

    def test_cursor_is_bound_to_query_and_detects_changed_collection(self):
        self.app.tasks.create("通用示例甲")
        self.app.tasks.create("通用示例乙")
        api = discovery(self.app)
        page = api.discover("task", query="通用示例", limit=1)
        with self.assertRaises(TaskError) as caught:
            api.discover("task", query="另一查询", cursor=page["next_cursor"])
        self.assertEqual(caught.exception.code, "AGENT_CURSOR_INVALID")
        self.app.tasks.create("通用示例丙")
        with self.assertRaises(TaskError) as caught:
            api.discover("task", query="通用示例", cursor=page["next_cursor"])
        self.assertEqual(caught.exception.code, "AGENT_CURSOR_STALE")

    def test_action_details_are_selected_and_catalog_search_has_no_schema(self):
        api = discovery(self.app)
        compact = api.discover("capability", query="echo")
        self.assertEqual(compact["items"][0]["id"], "demo.echo")
        self.assertNotIn("input_schema", json.dumps(compact))
        detail = api.describe("capability", "demo.echo")
        self.assertEqual(detail["action"]["input_schema"], {"type": "object"})
        self.assertEqual(detail["action"]["id"], "demo.echo")
        self.assertLess(len(json.dumps(compact)), len(json.dumps(self.app.registry.catalog())))

    def test_environment_discovery_exposes_names_without_values_or_secret_refs(self):
        env = self.app.environments.save("验收环境", {"base_url": "https://private.example"},
                                         {"password": "env:PRIVATE_PASSWORD"})
        api = discovery(self.app)
        page = api.discover("environment")
        self.assertEqual(page["items"][0]["id"], env["environment_id"])
        text = json.dumps(page)
        self.assertNotIn("private.example", text)
        self.assertNotIn("PRIVATE_PASSWORD", text)
        detail = api.describe("environment", env["environment_id"])
        self.assertEqual({r["name"] for r in detail["variables"]}, {"base_url", "password"})
        self.assertNotIn("PRIVATE_PASSWORD", json.dumps(detail))

    def test_task_detail_is_sectioned_and_retains_control_flow(self):
        task = self.task()
        step = self.step(task)
        api = discovery(self.app)
        brief = api.describe("task", task)
        self.assertEqual(brief["steps"][0]["step_id"], step["step_id"])
        self.assertNotIn("step_content", json.dumps(brief))
        code = api.describe("step", step["step_id"], sections=["code", "schemas"])
        self.assertEqual(code["step_content"], step["step_content"])
        flow = api.describe("task", task, sections=["flow"])
        self.assertEqual(flow["flow"]["version"], 2)

    def test_operation_detail_and_validation_use_real_defaults(self):
        api = discovery(self.app)
        spec = api.describe("operation", "run.start")
        self.assertIn("retry_execution_path", spec["parameters"]["properties"])
        self.assertEqual(spec["parameters"]["properties"]["mode"]["default"], "ALL")
        self.assertEqual(set(spec["parameters"]["required"]), {"run_id", "command_id"})
        for params in ({"run_id": "a"}, {"run_id": 2, "command_id": "b"},
                       {"run_id": "a", "command_id": "b", "surprise": True}):
            with self.subTest(params=params), self.assertRaises(TaskError) as caught:
                api.validate_operation("execute", "run.start", params)
            self.assertEqual(caught.exception.code, "AGENT_ARGUMENT_INVALID")
        api.validate_operation("execute", "run.start", {"run_id": "a", "command_id": "b"})

    def test_one_call_launch_and_materials_contracts_are_discoverable(self):
        api = discovery(self.app)
        launch = api.describe("operation", "task.run")
        self.assertEqual(set(launch["parameters"]["required"]), {"task_id", "expected_hash"})
        material = api.describe("operation", "materials")
        self.assertEqual(material["parameters"]["properties"]["capability_ids"]["type"], "array")

    def test_configuration_and_wrong_purpose_operations_are_not_callable(self):
        api = discovery(self.app)
        for purpose, op in (("execute", "ai.settings.get"), ("author", "run.start"),
                            ("execute", "environment.delete"), ("author", "does.not.exist")):
            with self.subTest(op=op), self.assertRaises(TaskError) as caught:
                api.validate_operation(purpose, op, {})
            self.assertEqual(caught.exception.code, "AGENT_OPERATION_DENIED")

    def test_every_exposed_parameter_has_an_explicit_json_type(self):
        from taskweave.application.agent.contracts import PURPOSE_OPERATIONS
        api = discovery(self.app)
        for operation in sorted(set().union(*PURPOSE_OPERATIONS.values())):
            contract = api.describe("operation", operation)
            for name, schema in contract["parameters"]["properties"].items():
                with self.subTest(operation=operation, parameter=name):
                    self.assertIn("type", schema)

    def test_recording_options_are_explicit_and_preserve_through_ack(self):
        api = discovery(self.app)
        params = {"step_id": "s", "provider_id": "p", "operation": "ack",
                  "recording_id": "r", "expected_session_id": "session", "through": 4}
        api.validate_operation("context", "context.record", params)
        with self.assertRaises(TaskError):
            api.validate_operation("context", "context.record", {**params, "arbitrary": "value"})

    def test_recording_rejects_options_unsupported_by_the_selected_owner(self):
        api = discovery(self.app)
        base = {"provider_id": "p", "operation": "start"}
        for operation, params in (
            ("context.record", {**base, "step_id": "s", "session_id": "wrong"}),
            ("context.record", {**base, "step_id": "s", "expected_revision": 2}),
            ("context.record", {**base, "step_id": "s", "run_id": "run", "environment_id": "env"}),
            ("plan.context.record", {**base, "plan_id": "p", "environment_id": "env"}),
        ):
            with self.subTest(params=params), self.assertRaises(TaskError):
                api.validate_operation("context", operation, params)

    def test_invalid_limits_and_unknown_sections_are_explicit_errors(self):
        api = discovery(self.app)
        for limit in (0, 101, True, "5"):
            with self.subTest(limit=limit), self.assertRaises(TaskError):
                api.discover("task", limit=limit)
        with self.assertRaises(TaskError):
            api.describe("task", self.task(), sections=["everything"])


if __name__ == "__main__":
    unittest.main()
