"""External authoring and execution reuse real application and worker behavior."""

from tests._core_fixture import CoreFixture, SOURCE
from taskweave.core.validation import TaskError


class AgentWorkflowTests(CoreFixture):
    def agent(self):
        self.assertTrue(hasattr(self.app, "agent"), "Application has no external AI use cases")
        return self.app.agent

    def test_external_ai_writes_trials_confirms_and_launches_without_model(self):
        api = self.agent()
        created = api.author("task.create", {"name": "核对输入", "description": "输入值原样保留"}, "new-task")
        repeated = api.author("task.create", {"name": "核对输入", "description": "输入值原样保留"}, "new-task")
        self.assertEqual(created["task_id"], repeated["task_id"])
        step = api.author("step.save", {"task_id": created["task_id"], "document": {
            "name": "保存核对值", "step_content": SOURCE}}, "new-step")
        trial = api.execute("step.trial", {"step_id": step["step_id"], "inputs": {"value": 7}}, "trial")
        self.assertEqual(api.wait(trial["run_id"], timeout=10)["status"], "SUCCEEDED")
        evidence = api.inspect("run", trial["run_id"], sections=["attempts"])
        api.execute("step.confirm", {"step_id": step["step_id"], "expected_hash": step["content_hash"],
                    "attempt_id": evidence["attempts"][0]["attempt_id"]}, "confirm")
        api.execute("instance.end", {"instance_type": "run", "owner_id": trial["run_id"]}, "end-trial")
        launched = api.execute("task.run", {"task_id": created["task_id"], "inputs": {"value": 7},
                    "expected_hash": self.app.tasks.describe_flow(created["task_id"])["definition_hash"]}, "launch")
        self.assertEqual(api.wait(launched["run_id"], timeout=10)["status"], "SUCCEEDED")
        self.assertEqual(api.inspect("output", launched["run_id"], step_id=step["step_id"])["data"], {"value": 7})
        self.assertEqual(api.execute("task.run", {"task_id": created["task_id"], "inputs": {"value": 7},
                    "expected_hash": self.app.tasks.describe_flow(created["task_id"])["definition_hash"]}, "launch")["run_id"], launched["run_id"])

    def test_frozen_materials_have_selected_runtime_contract_and_reject_stale_use(self):
        api = self.agent()
        task = self.task()
        step = self.step(task, capabilities=["demo.echo"])
        material = api.author("materials", {"step_id": step["step_id"], "capability_ids": ["demo.echo"]})
        self.assertIn("bundle_id", material)
        self.assertEqual(material["runtime"]["entrypoint"], "async def run(ctx, inputs)")
        self.assertIn("taskweave-task-3", material["task_package_schemas"])
        self.assertEqual(material["capabilities"][0]["id"], "demo.echo")
        saved = api.author("step.save", {"task_id": task, "step_id": step["step_id"],
                    "expected_hash": step["content_hash"], "document": {
                        "name": "Changed", "step_content": SOURCE}}, "edit", bundle_id=material["bundle_id"])
        with self.assertRaises(TaskError) as caught:
            api.author("step.save", {"task_id": task, "step_id": step["step_id"],
                       "expected_hash": saved["content_hash"], "document": {
                           "name": "Cannot overwrite", "step_content": SOURCE}}, "stale", bundle_id=material["bundle_id"])
        self.assertEqual(caught.exception.code, "AGENT_BUNDLE_STALE")

    def test_existing_step_requires_baseline_and_unknown_requests_do_not_execute(self):
        api = self.agent()
        task = self.task()
        step = self.step(task)
        with self.assertRaises(TaskError) as caught:
            api.author("step.save", {"task_id": task, "step_id": step["step_id"],
                       "document": {"name": "Wrong", "step_content": SOURCE}}, "edit")
        self.assertEqual(caught.exception.code, "AGENT_BASELINE_REQUIRED")
        with self.assertRaises(TaskError):
            api.execute("plugin.configure", {"plugin_id": "demo", "enabled": False}, "denied")
        self.assertEqual(self.app.steps.get(step["step_id"])["name"], "Step")

    def test_task_run_checks_version_before_start_and_exposes_request_state(self):
        api = self.agent()
        task = self.task()
        step = self.step(task)
        self.app.steps.confirm_manual(step["step_id"], step["content_hash"])
        with self.assertRaises(TaskError) as caught:
            api.execute("task.run", {"task_id": task, "expected_hash": "obsolete"}, "wrong-version")
        self.assertEqual(caught.exception.code, "EDIT_CONFLICT")
        self.assertEqual(self.app.runs.list(task), [])

    def test_public_dispatch_exposes_the_same_bounded_use_cases(self):
        result = self.app.dispatch("agent.author", {"operation": "task.create", "params": {"name": "通过接口创建"}, "request_id": "dispatch"})
        details = self.app.dispatch("agent.describe", {"kind": "task", "identity": result["task_id"]})
        self.assertEqual(details["name"], "通过接口创建")
        self.assertNotIn("graph_json", details)

    def test_two_branches_are_separately_trialled_before_confirmed_flow_execution(self):
        api = self.agent()
        task = api.author("task.create", {"name": "两分支验收", "input_schema": {
            "type": "object", "properties": {"left": {"type": "boolean"}}, "required": ["left"]}}, "branch-task")["task_id"]
        steps = []
        for name in ("left", "right"):
            step = api.author("step.save", {"task_id": task, "document": {"name": name,
                "step_content": 'async def run(ctx, inputs):\n    return ctx.result(data={"branch": "' + name + '"})\n'}}, "branch-" + name)
            trial = api.execute("step.trial", {"step_id": step["step_id"], "inputs": {"left": name == "left"}}, "try-" + name)
            self.assertEqual(api.wait(trial["run_id"], timeout=10)["status"], "SUCCEEDED")
            attempt = api.inspect("run", trial["run_id"], sections=["attempts"])["attempts"][0]
            api.execute("step.confirm", {"step_id": step["step_id"], "attempt_id": attempt["attempt_id"],
                        "expected_hash": step["content_hash"]}, "confirm-" + name)
            steps.append(step)
        api.execute("instance.end", {"instance_type": "run", "owner_id": trial["run_id"]}, "end-branches")
        body = lambda name, step: {"id": name, "kind": "sequence", "children": [{"id": step["step_id"], "kind": "action", "step_id": step["step_id"]}]}
        flow = {"version": 2, "root": {"id": "root", "kind": "sequence", "children": [{
            "id": "choice", "kind": "if", "condition": {"op": "eq", "left": {"ref": {"source": "task", "pointer": "/left"}}, "right": {"literal": True}},
            "then": body("yes", steps[0]), "else": body("no", steps[1])}]}}
        current = api.describe("task", task)["definition_hash"]
        api.author("task.flow.save", {"task_id": task, "flow": flow, "expected_hash": current}, "save-branches")
        current = api.describe("task", task)["definition_hash"]
        api.execute("task.flow.confirm", {"task_id": task, "expected_hash": current}, "confirm-branches")
        for name in ("left", "right"):
            run = api.execute("task.run", {"task_id": task, "inputs": {"left": name == "left"},
                              "expected_hash": current}, "run-" + name)
            self.assertEqual(api.wait(run["run_id"], timeout=10)["status"], "SUCCEEDED")
            attempts = api.inspect("run", run["run_id"], sections=["attempts"])["attempts"]
            self.assertEqual([row["step_id"] for row in attempts], [steps[name == "right"]["step_id"]])

    def test_loop_aggregate_instance_output_and_task3_package_are_available(self):
        api = self.agent()
        task = self.task()
        step = self.step(task, bindings={"value": {"ref": {"source": "loop", "node_id": "each", "field": "item", "pointer": ""}}})
        api.execute("step.confirm.manual", {"step_id": step["step_id"], "expected_hash": step["content_hash"]}, "loop-manual-confirm")
        flow = {"version": 2, "root": {"id": "root", "kind": "sequence", "children": [{
            "id": "each", "kind": "foreach", "items": {"literal": [2, 3]}, "max_items": 2,
            "body": {"id": "body", "kind": "sequence", "children": [{"id": step["step_id"], "kind": "action", "step_id": step["step_id"]}]}}]}}
        api.author("task.flow.save", {"task_id": task, "flow": flow,
                   "expected_hash": api.describe("task", task)["definition_hash"]}, "loop-flow")
        current = api.describe("task", task)["definition_hash"]
        api.execute("task.flow.confirm", {"task_id": task, "expected_hash": current}, "loop-confirm")
        run = api.execute("task.run", {"task_id": task, "expected_hash": current}, "loop-run")
        self.assertEqual(api.wait(run["run_id"], timeout=10)["status"], "SUCCEEDED")
        values = api.inspect("output", run["run_id"], step_id=step["step_id"], item_pointer="/value", loop_node_id="each")
        self.assertEqual(values["data"], [2, 3])
        attempts = api.inspect("run", run["run_id"], sections=["attempts"])["attempts"]
        one = api.inspect("output", run["run_id"], step_id=step["step_id"], execution_path=attempts[0]["execution_path"])
        self.assertEqual(one["data"], {"value": 2})
        package = api.inspect("package", task)
        self.assertEqual(package["format"], "taskweave-task-3")
        package["origin"] = "ai_generated"
        package["flow_validation_state"] = "DRAFT"
        for entry in package["steps"]:
            entry["validation_state"] = "DRAFT"
        imported = api.author("task.import", {"package": package}, "import-loop-package")
        self.assertNotEqual(imported["task_id"], task)
        self.assertEqual(api.describe("task", imported["task_id"], sections=["flow"])["flow"]["root"]["children"][0]["kind"], "foreach")

    def test_sequence_repeats_task_with_distinct_nodes_and_replays_start(self):
        api = self.agent()
        task = self.task()
        step = self.step(task, input_schema={"type": "object", "properties": {"value": {"type": "integer"}}})
        api.execute("step.confirm.manual", {"step_id": step["step_id"], "expected_hash": step["content_hash"]}, "sequence-confirm")
        nodes = [{"node_id": name, "task_id": task, "environment_id": None, "inputs": {},
                  "step_inputs": {step["step_id"]: {"value": {"kind": "literal", "value": index}}}}
                 for index, name in enumerate(("first", "second"))]
        sequence = api.author("sequence.save", {"name": "重复任务", "nodes": nodes, "input_schema": {"type": "object"}}, "new-sequence")
        launched = api.execute("sequence.start", {"sequence_id": sequence["sequence_id"], "inputs": {}}, "start-sequence")
        result = api.wait(launched["sequence_run_id"], kind="sequence", timeout=10)
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual([node["node_id"] for node in result["nodes"]], ["first", "second"])
        self.assertEqual(len({node["run_id"] for node in result["nodes"]}), 2)
        self.assertEqual(api.execute("sequence.start", {"sequence_id": sequence["sequence_id"], "inputs": {}}, "start-sequence")["sequence_run_id"], launched["sequence_run_id"])

    def test_missing_inputs_return_stable_request_and_continue_original_run(self):
        api = self.agent()
        task = self.app.tasks.create("补参", {"type": "object", "properties": {"value": {"type": "integer"}}, "required": ["value"]})["task_id"]
        step = self.step(task)
        api.execute("step.confirm.manual", {"step_id": step["step_id"], "expected_hash": step["content_hash"]}, "inputs-confirm")
        run = api.execute("task.run", {"task_id": task, "expected_hash": api.describe("task", task)["definition_hash"], "defer_inputs": True}, "missing-inputs")
        paused = api.wait(run["run_id"], timeout=10)
        self.assertEqual(paused["next_action"], "provide_inputs")
        api.execute("run.inputs", {"run_id": run["run_id"], "inputs": {"value": 0}, "expected_input_id": paused["waiting_input"]["id"]}, "provide-zero")
        self.assertEqual(api.wait(run["run_id"], timeout=10)["status"], "SUCCEEDED")
        self.assertEqual(api.inspect("output", run["run_id"], step_id=step["step_id"])["data"], {"value": 0})

    def test_missing_inputs_preserve_next_and_until_execution_boundaries(self):
        api = self.agent()
        for mode in ('NEXT', 'UNTIL'):
            with self.subTest(mode=mode):
                task = self.app.tasks.create('补参边界' + mode, {'type': 'object', 'properties': {'value': {'type': 'integer'}}, 'required': ['value']})['task_id']
                first, second = self.step(task), self.step(task)
                for index, step in enumerate((first, second)):
                    api.execute('step.confirm.manual', {'step_id': step['step_id'], 'expected_hash': step['content_hash']}, mode + '-confirm-' + str(index))
                run = api.execute('run.create', {'task_id': task, 'defer_inputs': True}, mode + '-create')
                api.execute('run.start', {'run_id': run['run_id'], 'mode': mode, 'target_step_id': first['step_id'] if mode == 'UNTIL' else None}, mode + '-start')
                paused = api.wait(run['run_id'], timeout=10)
                api.execute('run.inputs', {'run_id': run['run_id'], 'inputs': {'value': 0}, 'expected_input_id': paused['waiting_input']['id']}, mode + '-provide')
                api.wait(run['run_id'], timeout=10)
                attempts = self.app.runs.get(run['run_id'])['attempts']
                self.assertEqual([attempt['step_id'] for attempt in attempts if attempt['valid'] and attempt['status'] == 'SUCCEEDED'], [first['step_id']])

    def test_discovered_read_operations_can_retrieve_definitions_and_lists(self):
        api = self.agent()
        task = self.task()
        step = self.step(task)
        draft = api.inspect('operation_result', 'draft.export', params={'step_id': step['step_id']})
        self.assertIn('step_content', str(draft))
        tasks = api.inspect('operation_result', 'task.list', params={}, limit=1)
        self.assertEqual(tasks['data']['items'][0]['task_id'], task)
        with self.assertRaises(TaskError):
            api.inspect('operation_result', 'task.delete', params={'task_id': task})
        plan = self.app.planning.create('读取规划')
        generation = self.app.planning.generations.create_generation(plan['plan_id'], plan['revision'], 'web_chat', 'private/request.json')
        public = api.inspect('operation_result', 'plan.generation.get', params={'generation_id': generation['generation_id']})
        self.assertNotIn('request_snapshot_path', str(public))
        self.assertNotIn('private/request.json', str(public))

    def test_large_frozen_step_code_has_lossless_chunked_read_path(self):
        api = self.agent()
        task = self.task()
        code = 'async def run(ctx, inputs):\n    # ' + ('长文本' * 14000) + '\n    return ctx.result(data={})\n'
        step = self.step(task, source=code)
        material = api.author('materials', {'step_id': step['step_id']})
        self.assertTrue(material['truncated'])
        offset, chunks = 0, []
        while offset is not None:
            chunk = api.inspect('bundle', material['bundle_id'], pointer='/current_document/step_content', text_offset=offset)['data']
            chunks.append(chunk['text'])
            offset = chunk['next_offset']
        self.assertEqual(''.join(chunks), code)

    def test_context_provider_contract_and_full_conditions_are_available(self):
        from taskweave_playwright import PlaywrightPlugin
        from taskweave.plugins.registry import Registry
        api = self.agent()
        self.app.registry = self.app.authoring.registry = Registry([PlaywrightPlugin()])
        provider = api.describe('context_provider', 'playwright.page')
        self.assertIn('url', str(provider['request_contract']))
        material = api.author('materials', {'task_id': self.task(), 'capability_ids': [sorted(self.app.registry.actions)[0]]})
        full = api.inspect('bundle', material['bundle_id'], sections=['plugins'])
        self.assertIn('context_requests', full['plugins'][0])
        from taskweave.application.agent.authoring import FLOW_GUIDE
        self.assertEqual(FLOW_GUIDE['conditions']['all']['conditions'][0]['op'], 'exists')
        from copy import deepcopy
        from taskweave.core.task_flow import validate_flow
        for shape in FLOW_GUIDE['conditions'].values():
            node = deepcopy(FLOW_GUIDE['nodes']['if'])
            node['condition'] = shape
            node.update(FLOW_GUIDE['branch_outputs'])
            validate_flow({'version': 2, 'root': {'id': 'root', 'kind': 'sequence', 'children': [node]}}, [])

    def test_large_saved_result_has_pointer_and_chunk_access(self):
        api = self.agent()
        task = self.task()
        step = self.step(task, source="async def run(ctx, inputs):\n    return ctx.result(data={'text': 'x' * 50000})\n")
        self.app.steps.confirm_manual(step['step_id'], step['content_hash'])
        run = self.run_task(task)
        result_id = run['results'][0]['result_id']
        first = api.inspect('result', result_id, pointer='/data/text', text_offset=0)['data']
        self.assertEqual(first['characters'], 50000)
        self.assertEqual(first['next_offset'], 6000)
        self.assertNotIn('path', str(first))

    def test_pointer_reads_keep_parent_secret_redaction_before_projection(self):
        api = self.agent()
        task = self.task()
        step = self.step(task, source='async def run(ctx, inputs):\n    return ctx.result(data={"password": "must-not-leak", "plain": "ok"})\n')
        self.app.steps.confirm_manual(step['step_id'], step['content_hash'])
        run = self.run_task(task)
        output = api.inspect('output', run['run_id'], step_id=step['step_id'], pointer='/password')
        saved = api.inspect('result', run['results'][0]['result_id'], pointer='/data/password')
        self.assertNotIn('must-not-leak', str(output) + str(saved))

    def test_loop_item_projection_does_not_remove_secret_field_context(self):
        api = self.agent()
        task = self.task()
        step = self.step(task, source='async def run(ctx, inputs):\n    return ctx.result(data={"password": "loop-secret", "image_base64": "aW1hZ2U="})\n')
        self.app.steps.confirm_manual(step['step_id'], step['content_hash'])
        flow = {'version': 2, 'root': {'id': 'root', 'kind': 'sequence', 'children': [{'id': 'each', 'kind': 'foreach', 'items': {'literal': [1]}, 'body': {'id': 'body', 'kind': 'sequence', 'children': [{'id': 'action', 'kind': 'action', 'step_id': step['step_id']}]}}]}}
        self.app.tasks.save_flow(task, flow, self.app.tasks.definition_hash(task))
        self.app.tasks.confirm_flow(task, self.app.tasks.definition_hash(task))
        run = self.run_task(task)
        selected = api.inspect('output', run['run_id'], step_id=step['step_id'], item_pointer='/password', loop_node_id='each')
        self.assertNotIn('loop-secret', str(selected))
        with self.assertRaises(TaskError):
            api.inspect('output', run['run_id'], step_id=step['step_id'], item_pointer='/image_base64', loop_node_id='each')
        explicit = api.inspect('output', run['run_id'], step_id=step['step_id'], item_pointer='/image_base64', loop_node_id='each', include_images=True)
        self.assertEqual(explicit['data'], ['aW1hZ2U='])

    def test_schema_metadata_survives_redaction_while_secret_defaults_are_omitted(self):
        api = self.agent()
        task = self.task()
        step = self.step(task, input_schema={"type": "object", "properties": {
            "password": {"type": "string", "default": "must-not-leak"},
            "env_secret_refs": {"type": "object", "additionalProperties": {"type": "string"}},
            "image_base64": {"type": "string"}}})
        detail = api.describe("step", step["step_id"], sections=["schemas"])
        schema = detail["input_schema"]["properties"]
        self.assertEqual(schema["password"]["type"], "string")
        self.assertNotIn("default", schema["password"])
        self.assertEqual(schema["env_secret_refs"]["type"], "object")
        self.assertEqual(schema["image_base64"]["type"], "string")

    def test_common_browser_materials_deduplicate_plugin_contributions(self):
        from taskweave_playwright import PlaywrightPlugin
        from taskweave.plugins.registry import Registry
        api = self.agent()
        self.app.registry = self.app.authoring.registry = Registry([PlaywrightPlugin()])
        task = self.task()
        capabilities = sorted(self.app.registry.actions)[:5]
        material = api.author("materials", {"task_id": task, "capability_ids": capabilities})
        full = api.inspect("bundle", material["bundle_id"], sections=["plugins"])
        self.assertEqual(len(full["plugins"]), 1)
        actions = api.inspect("bundle", material["bundle_id"], sections=["capabilities"], limit=2)
        self.assertEqual(len(actions["capabilities"]), 2)
        self.assertIsNotNone(actions["capabilities_page"]["next_cursor"])

    def use_evidence_plugin(self):
        from taskweave.application.service import Application
        self.app.close()
        self.app = Application(self.home, registry_factory="tests._agent_fixture:build_registry")
        return self.agent()

    def test_context_default_has_no_preview_and_explicit_image_choice_is_separate(self):
        api = self.use_evidence_plugin()
        task = self.task()
        step = self.step(task, capabilities=["demo.echo"])
        params = {"step_id": step["step_id"], "provider_id": "demo.page"}
        default = api.context("context.read", params, "collect-default")
        self.assertEqual(default["items"][0]["content"], "text-only")
        hidden = api.context("context.read", {**params, "include_view": True}, "collect-hidden-preview")
        self.assertNotIn("aW1hZ2U=", str(hidden))
        explicit = api.context("context.read", params, "collect-explicit-preview", include_images=True)
        self.assertEqual(explicit["views"][0]["data"]["image_base64"], "aW1hZ2U=")

    def test_candidate_validation_reports_error_level_plugin_diagnostics(self):
        api = self.use_evidence_plugin()
        task = self.task()
        self.step(task, name="lint-error", capabilities=["demo.echo"])
        package = self.app.tasks.export(task)
        package["origin"] = "ai_generated"
        result = api.author("candidate.validate", {"package": package})
        self.assertFalse(result["valid"])
        self.assertEqual(result["diagnostics"][0]["code"], "REQUIRED_ACTION_ARGUMENT")

    def test_step_materials_cannot_be_applied_to_another_task(self):
        api = self.agent()
        original = self.task()
        step = self.step(original)
        bundle = api.author("materials", {"step_id": step["step_id"]})
        other = self.task()
        with self.assertRaises(TaskError) as error:
            api.author("step.save", {"task_id": other, "document": {"name": "Not owned", "step_content": SOURCE}},
                       "wrong-scope", bundle_id=bundle["bundle_id"])
        self.assertEqual(error.exception.code, "AGENT_BUNDLE_SCOPE_INVALID")

    def test_interrupted_sequence_pause_is_not_sent_again(self):
        import time
        from unittest.mock import patch
        api = self.agent()
        task = self.task()
        step = self.step(task, source='async def run(ctx, inputs):\n    await ctx.call("demo.wait", {"seconds": 2})\n    return ctx.result(data={})\n', capabilities=["demo.wait"])
        api.execute("step.confirm.manual", {"step_id": step["step_id"], "expected_hash": step["content_hash"]}, "pause-confirm")
        sequence = api.author("sequence.save", {"name": "Pause", "nodes": [{"node_id": "one", "task_id": task,
            "environment_id": None, "inputs": {}, "step_inputs": {}}], "input_schema": {"type": "object"}}, "pause-definition")
        launched = api.execute("sequence.start", {"sequence_id": sequence["sequence_id"], "inputs": {}}, "pause-start")
        identity = launched["sequence_run_id"]
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            nodes = self.app.sequences.run_get(identity)["nodes"]
            if nodes[0].get("run_id"):
                break
            time.sleep(.01)
        with patch.object(api.records, "finish", side_effect=RuntimeError("simulated response/receipt crash")):
            with self.assertRaises(RuntimeError):
                api.execute("sequence.pause", {"sequence_run_id": identity}, "pause-once")
        with self.assertRaises(TaskError) as error:
            api.execute("sequence.pause", {"sequence_run_id": identity}, "pause-once")
        self.assertEqual(error.exception.code, "AGENT_REQUEST_UNCERTAIN")

    def test_lost_worker_reports_unknown_and_queries_do_not_repeat_actions(self):
        import time
        api = self.agent()
        task = self.task()
        step = self.step(task, source='async def run(ctx, inputs):\n    await ctx.call("demo.wait", {"seconds": 10})\n    return ctx.result(data={})\n', capabilities=["demo.wait"])
        api.execute("step.confirm.manual", {"step_id": step["step_id"], "expected_hash": step["content_hash"]}, "unknown-confirm")
        run = api.execute("task.run", {"task_id": task, "expected_hash": api.describe("task", task)["definition_hash"]}, "unknown-run")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            current = self.app.runs.get(run["run_id"])
            process = self.app.coordinator.process
            if process is not None and current["attempts"]:
                break
            time.sleep(.02)
        self.assertIsNotNone(process)
        process.terminate()
        result = api.wait(run["run_id"], timeout=10)
        self.assertEqual(result["next_action"], "reconcile_with_evidence")
        for _ in range(2):
            evidence = api.inspect("run", run["run_id"], sections=["attempts"])
            self.assertEqual(len(evidence["attempts"]), 1)
            self.assertEqual(evidence["attempts"][0]["status"], "UNKNOWN")
        with self.assertRaises(TaskError) as error:
            api.execute("run.start", {"run_id": run["run_id"]}, "not-a-reconciliation")
        self.assertEqual(error.exception.code, "RECONCILIATION_REQUIRED")
