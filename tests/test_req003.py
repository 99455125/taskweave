"""Real application integration tests: spawn workers, SQLite and loopback HTTP."""

from contextlib import closing
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from unittest.mock import patch

from taskweave.application.service import Application
from taskweave.application.demo import run_demo
from taskweave.core.ports import ModelReply, ToolCall, Scope, StepResult, ResultRequest
from taskweave.core.validation import TaskError, pointer, validate, content_tree
from taskweave.infrastructure.storage import uid, Results, migrate
from taskweave.infrastructure.http import make_server
from taskweave.infrastructure.model import HttpModel

SOURCE = "async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n"


class ScriptedModel:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.messages = []

    def capabilities(self):
        return {"tools": True, "images": False}

    async def complete(self, messages, tool_specs, response_contract):
        self.messages.append(json.loads(json.dumps(messages)))
        return next(self.replies)


class AppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="taskweave-test-")
        self.home = Path(self.tmp.name)
        self.app = Application(self.home)

    def tearDown(self):
        self.app.close()
        self.tmp.cleanup()

    def task(self):
        return self.app.repo.create_task("Test")["task_id"]

    def step(self, task, source=SOURCE, bindings=None, capabilities=None, **extra):
        return self.app.repo.save_step(
            task,
            {
                "name": "Step",
                "step_content": source,
                "bindings": bindings or {},
                "capabilities": capabilities or [],
                **extra,
            },
        )

    def confirm(self, step, sample=None):
        run = self.app.trial_step(step["step_id"], sample or {}, uid())
        done = self.app.coordinator.wait(run["run_id"])
        self.assertEqual(done["status"], "SUCCEEDED", done)
        return self.app.confirm_step(
            step["step_id"], done["attempts"][0]["attempt_id"], step["content_hash"]
        )

    def run_task(self, task, **kwargs):
        run = self.app.create_run(task, **kwargs)
        self.app.coordinator.start(run["run_id"], uid())
        return self.app.coordinator.wait(run["run_id"])

    def test_five_steps_use_persisted_output_after_worker_replacement(self):
        result = run_demo(self.app)
        self.assertEqual(result["step_5_output"], {"received_order_id": "ORD-1001"})
        with closing(sqlite3.connect(result["task_db"])) as db:
            count = db.execute(
                "SELECT count(*) FROM step_outputs WHERE run_id=?", (result["run_id"],)
            ).fetchone()[0]
            self.assertEqual(count, 5)
        with closing(sqlite3.connect(result["control_db"])) as db:
            self.assertNotIn(
                "step_versions",
                [
                    x[0]
                    for x in db.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                ],
            )

    def test_pause_restart_continue_and_edit_lock(self):
        task = self.task()
        one = self.confirm(self.step(task, bindings={"v": {"literal": 42}}), {"v": 42})
        two = self.confirm(
            self.step(
                task,
                bindings={
                    "v": {
                        "ref": {
                            "source": "step",
                            "step_id": one["step_id"],
                            "pointer": "/v",
                        }
                    }
                },
            ),
            {"v": 42},
        )
        run = self.app.create_run(task)
        self.app.coordinator.start(run["run_id"], uid(), mode="NEXT")
        self.assertEqual(self.app.coordinator.wait(run["run_id"])["status"], "PAUSED")
        with self.assertRaisesRegex(TaskError, "End the active"):
            self.app.repo.save_step(task, one, one["step_id"], one["content_hash"])
        self.app.close()
        self.app = Application(self.home)
        self.app.coordinator.start(run["run_id"], uid())
        self.assertEqual(
            self.app.coordinator.wait(run["run_id"])["status"], "SUCCEEDED"
        )
        self.assertEqual(
            self.app.repo.read_output(run["run_id"], two["step_id"]), {"v": 42}
        )

    def test_draft_confirmation_and_edits_invalidate(self):
        task = self.task()
        step = self.step(task)
        with self.assertRaises(TaskError):
            self.app.create_run(task)
        old = self.confirm(step)
        new = self.app.repo.save_step(
            task, {**old, "goal": "new goal"}, old["step_id"], old["content_hash"]
        )
        self.assertEqual(new["validation_state"], "DRAFT")
        with self.assertRaisesRegex(TaskError, "EDIT_CONFLICT"):
            self.app.repo.save_step(task, old, old["step_id"], old["content_hash"])
        attempt = self.app.repo.query("SELECT attempt_id FROM step_attempts", one=True)[
            "attempt_id"
        ]
        with self.assertRaises(TaskError):
            self.app.confirm_step(new["step_id"], attempt, new["content_hash"])

    def test_failure_stops_then_explicit_retry_records_attempt(self):
        task = self.task()
        one = self.confirm(self.step(task))
        source = 'async def run(ctx, inputs):\n    assert inputs["good"], "business assertion failed"\n    return ctx.result(data={"ok": True})\n'
        two = self.confirm(
            self.step(
                task,
                source,
                bindings={"good": {"ref": {"source": "task", "pointer": "/good"}}},
            ),
            {"good": True},
        )
        self.confirm(self.step(task))
        run = self.run_task(task, inputs={"good": False})
        self.assertEqual(run["status"], "FAILED")
        self.assertEqual(
            [x["step_id"] for x in run["attempts"]], [one["step_id"], two["step_id"]]
        )
        self.app.coordinator.start(run["run_id"], uid(), retry_step_id=two["step_id"])
        again = self.app.coordinator.wait(run["run_id"])
        self.assertEqual(len(again["attempts"]), 3)
        self.assertEqual(
            [
                a["attempt_no"]
                for a in again["attempts"]
                if a["step_id"] == two["step_id"]
            ],
            [1, 2],
        )

    def test_missing_reference_fails_before_worker(self):
        task = self.task()
        self.confirm(
            self.step(
                task, bindings={"x": {"ref": {"source": "task", "pointer": "/missing"}}}
            ),
            {"x": 1},
        )
        run = self.run_task(task)
        self.assertEqual(run["attempts"][0]["error_code"], "INPUT_MISSING")
        self.assertEqual(run["attempts"][0]["effect_state"], "NOT_STARTED")
        self.assertIsNone(self.app.coordinator.process)

    def test_repeated_command_and_trial_are_idempotent(self):
        task = self.task()
        step = self.step(task)
        cmd = uid()
        a = self.app.trial_step(step["step_id"], {}, cmd)
        self.app.coordinator.wait(a["run_id"])
        b = self.app.trial_step(step["step_id"], {}, cmd)
        self.assertEqual(a, b)
        with self.assertRaises(TaskError):
            self.app.trial_step(step["step_id"], {"x": 1}, cmd)
        self.app.confirm_step(
            step["step_id"],
            self.app.repo.run_details(a["run_id"])["attempts"][0]["attempt_id"],
            step["content_hash"],
        )
        run = self.app.create_run(task)
        command = uid()
        responses = []

        def start():
            responses.append(self.app.coordinator.start(run["run_id"], command))

        threads = [threading.Thread(target=start) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        done = self.app.coordinator.wait(run["run_id"])
        self.assertEqual(len(done["attempts"]), 1)
        self.assertEqual(len(responses), 4)
        self.assertTrue(all(r == responses[0] for r in responses))
        with self.assertRaises(TaskError):
            self.app.coordinator.start(run["run_id"], command, mode="NEXT")

    def test_single_instance_and_single_active_run(self):
        with self.assertRaises(TaskError):
            Application(self.home)
        task = self.task()
        self.confirm(self.step(task))
        self.confirm(self.step(task))
        r1 = self.app.create_run(task)
        r2 = self.app.create_run(task)
        self.app.coordinator.start(r1["run_id"], uid(), mode="NEXT")
        self.app.coordinator.wait(r1["run_id"])
        with self.assertRaises(TaskError):
            self.app.coordinator.start(r2["run_id"], uid())
        self.app.coordinator.control(r1["run_id"], uid(), "abandon")
        self.app.coordinator.start(r2["run_id"], uid())
        self.assertEqual(self.app.coordinator.wait(r2["run_id"])["status"], "SUCCEEDED")

    def test_worker_kill_unknown_requires_reconciliation(self):
        task = self.task()
        source = 'async def run(ctx, inputs):\n    await ctx.call("demo.wait", inputs)\n    return ctx.result()\n'
        self.confirm(
            self.step(
                task,
                source,
                capabilities=["demo.wait"],
                bindings={
                    "seconds": {"ref": {"source": "task", "pointer": "/seconds"}}
                },
            ),
            {"seconds": 0},
        )
        run = self.app.create_run(task, {"seconds": 10})
        self.app.coordinator.start(run["run_id"], uid())
        deadline = time.monotonic() + 5
        while not self.app.coordinator.process and time.monotonic() < deadline:
            time.sleep(0.02)
        time.sleep(0.3)
        self.app.coordinator.process.terminate()
        done = self.app.coordinator.wait(run["run_id"])
        self.assertEqual(done["status"], "INTERRUPTED", done)
        self.assertEqual(done["attempts"][0]["status"], "UNKNOWN")
        with self.assertRaisesRegex(TaskError, "RECONCILIATION_REQUIRED"):
            self.app.coordinator.start(run["run_id"], uid())
        self.app.coordinator.reconcile(
            done["attempts"][0]["attempt_id"],
            "not_completed",
            {},
            uid(),
        )
        self.app.coordinator.control(run["run_id"], uid(), "abandon")

    def test_pause_cancel_and_timeout(self):
        task = self.task()
        source = 'async def run(ctx, inputs):\n    await ctx.call("demo.wait", {"seconds": inputs["seconds"]})\n    return ctx.result()\n'
        self.confirm(
            self.step(
                task,
                source,
                capabilities=["demo.wait"],
                bindings={"seconds": {"literal": 1}},
            ),
            {"seconds": 0},
        )
        self.confirm(self.step(task))
        run = self.app.create_run(task)
        self.app.coordinator.start(run["run_id"], uid())
        self.app.coordinator.control(run["run_id"], uid(), "pause")
        done = self.app.coordinator.wait(run["run_id"])
        self.assertEqual(done["status"], "PAUSED")
        self.assertEqual(len(done["attempts"]), 1)
        self.app.coordinator.control(run["run_id"], uid(), "abandon")
        run = self.app.create_run(task)
        self.app.coordinator.start(run["run_id"], uid())
        time.sleep(0.2)
        self.app.coordinator.control(run["run_id"], uid(), "cancel")
        self.assertEqual(
            self.app.coordinator.wait(run["run_id"])["status"], "CANCELLED"
        )
        task2 = self.task()
        stuck = self.step(
            task2,
            "async def run(ctx, inputs):\n    while True:\n        pass\n",
            timeout_ms=200,
        )
        trial = self.app.trial_step(stuck["step_id"], {}, uid())
        done = self.app.coordinator.wait(trial["run_id"], 5)
        self.assertEqual(done["status"], "INTERRUPTED")
        self.assertEqual(done["attempts"][0]["error_code"], "WORKER_TIMEOUT")

    def test_upstream_rerun_invalidates_downstream(self):
        task = self.task()
        one = self.confirm(self.step(task, bindings={"v": {"literal": 1}}), {"v": 1})
        two = self.confirm(
            self.step(
                task,
                bindings={
                    "v": {
                        "ref": {
                            "source": "step",
                            "step_id": one["step_id"],
                            "pointer": "/v",
                        }
                    }
                },
            ),
            {"v": 1},
        )
        self.confirm(self.step(task))
        run = self.app.create_run(task)
        self.app.coordinator.start(
            run["run_id"], uid(), mode="UNTIL", target_step_id=two["step_id"]
        )
        self.app.coordinator.wait(run["run_id"])
        self.app.coordinator.start(
            run["run_id"], uid(), mode="NEXT", retry_step_id=one["step_id"]
        )
        done = self.app.coordinator.wait(run["run_id"])
        with self.assertRaises(TaskError):
            self.app.repo.read_output(run["run_id"], two["step_id"])
        self.assertEqual(len(done["attempts"]), 3)
        self.assertEqual(sum(a["valid"] for a in done["attempts"]), 1)

    def test_state_only_does_not_create_task_db(self):
        task = self.task()
        self.confirm(
            self.step(task, "async def run(ctx, inputs):\n    return ctx.result()\n")
        )
        self.assertEqual(self.run_task(task)["status"], "SUCCEEDED")
        self.assertFalse(self.app.repo.task_path(task).exists())

    def test_recovery_after_result_commit_before_control_ack(self):
        task = self.task()
        self.confirm(self.step(task))
        run = self.app.create_run(task)

        def lost_ack(*args):
            raise RuntimeError("Simulated coordinator ACK failure")

        with patch.object(self.app.repo, "finish_attempt", side_effect=lost_ack):
            self.app.coordinator.start(run["run_id"], uid())
            done = self.app.coordinator.wait(run["run_id"])
        self.assertEqual(done["status"], "INTERRUPTED")
        # The application retains RUNNING when a receipt exists but ACK cannot commit.
        self.assertEqual(done["attempts"][0]["status"], "RUNNING")
        self.app.close()
        self.app = Application(self.home)
        self.assertEqual(
            self.app.repo.run_details(run["run_id"])["attempts"][0]["status"],
            "SUCCEEDED",
        )
        self.app.coordinator.start(run["run_id"], uid())
        done = self.app.coordinator.wait(run["run_id"])
        self.assertEqual(done["status"], "SUCCEEDED")
        self.assertEqual(len(done["attempts"]), 1)

    def test_custom_table_isolation_parsing_cleanup(self):
        source = 'async def run(ctx, inputs):\n    return ctx.result(outputs=[ctx.output("demo.table", "items", [{"value": inputs["v"]}])])\n'
        tasks = []
        for v in ("first", "second"):
            task = self.task()
            tasks.append(task)
            self.confirm(
                self.step(
                    task,
                    source,
                    bindings={"v": {"literal": v}},
                    capabilities=["demo.table"],
                ),
                {"v": v},
            )
            run = self.run_task(task)
            ref = run["results"][0]
            self.assertEqual(
                self.app.repo.read_result(ref["result_id"], self.app.registry)["data"],
                [v],
            )
            self.app.repo.delete_result(ref["result_id"])
            with self.assertRaises(TaskError):
                self.app.repo.read_result(ref["result_id"], self.app.registry)
        self.app.repo.delete_task(tasks[0])
        self.assertFalse(self.app.repo.task_path(tasks[0]).exists())
        self.assertTrue(self.app.repo.task_path(tasks[1]).exists())

    def test_ai_tool_generation_editing_and_manual_execution(self):
        task = self.task()
        bad = 'async def run(ctx, inputs):\n    raise ValueError("fix me")\n'
        step = self.step(
            task,
            bad,
            capabilities=["demo.echo", "text.upper"],
            goal="Return the inputs",
        )
        trial = self.app.trial_step(step["step_id"], {}, uid())
        done = self.app.coordinator.wait(trial["run_id"])
        self.assertEqual(done["status"], "FAILED")
        feedback = self.app.export_feedback(done["attempts"][0]["attempt_id"])
        model = ScriptedModel(
            [
                ModelReply(tool_calls=(ToolCall("call1", "demo.echo", {"sample": 1}),)),
                ModelReply(SOURCE, "Use the input"),
            ]
        )
        self.app.authoring.model = model
        proposal = asyncio.run(
            self.app.authoring.generate(
                step["step_id"], step["content_hash"], feedback=feedback
            )
        )
        self.assertEqual(self.app.repo.step(step["step_id"])["step_content"], bad)
        prompt = json.dumps(model.messages)
        self.assertIn("text.upper", prompt)
        self.assertIn("demo.echo", prompt)
        edited = self.app.repo.save_step(
            task,
            {**step, "step_content": proposal["proposed_content"]},
            step["step_id"],
            step["content_hash"],
        )
        self.confirm(edited)
        self.app.authoring.model = None
        self.assertEqual(self.run_task(task)["status"], "SUCCEEDED")
        self.assertEqual(len(model.messages), 2)

    def test_privacy_draft_roundtrip_and_no_model(self):
        task = self.task()
        step = self.step(task)
        with self.assertRaisesRegex(TaskError, "Manual authoring"):
            asyncio.run(
                self.app.authoring.generate(step["step_id"], step["content_hash"])
            )
        package = self.app.export_draft(step["step_id"])
        imported = self.app.import_draft(self.task(), package)
        self.assertEqual(imported["validation_state"], "DRAFT")
        self.app.confirm_step_manual(step['step_id'], step['content_hash'])
        run = self.app.create_run(task, {"password": "local-test-value"})
        self.assertEqual(json.loads(self.app.repo.run(run['run_id'])['input_summary_json'])['password'], '[REDACTED]')
        environment = self.app.repo.save_environment("local", {"token": "local-test-token"})
        self.assertEqual(self.app.repo.environment(environment['environment_id'])[0]['token'], 'local-test-token')
        from taskweave.infrastructure.privacy import redact

        self.assertEqual(
            redact({"username": "alice", "password": "p"}),
            {"username": "[REDACTED]", "password": "[REDACTED]"},
        )

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

    def test_http_api_auth_and_task_create(self):
        server, token = make_server(self.app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}/api"
        try:
            body = json.dumps(
                {"operation": "task.create", "params": {"name": "API test"}}
            ).encode()
            with self.assertRaises(HTTPError):
                urlopen(
                    Request(
                        url, data=body, headers={"Content-Type": "application/json"}
                    )
                )
            with urlopen(
                Request(
                    url,
                    data=body,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": "Bearer " + token,
                    },
                )
            ) as response:
                result = json.load(response)
            self.assertTrue(result["ok"])
            self.assertEqual(result["result"]["name"], "API test")
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_migration_failure_rolls_back_and_unknown_version_rejected(self):
        path = self.home / "migration-test.db"
        with closing(sqlite3.connect(path)) as db:
            db.executescript(
                'CREATE TABLE original(value TEXT); INSERT INTO original VALUES("kept"); PRAGMA user_version=1;'
            )
            with self.assertRaises(sqlite3.Error):
                migrate(
                    db,
                    path,
                    2,
                    {2: "ALTER TABLE original ADD COLUMN added TEXT; BAD SQL;"},
                )
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(
                [r[1] for r in db.execute("PRAGMA table_info(original)")], ["value"]
            )
            self.assertTrue(Path(str(path) + ".v1.bak").exists())
            db.execute("PRAGMA user_version=99")
            with self.assertRaises(TaskError):
                migrate(db, path, 2, {2: ""})

    def test_named_plugin_result_can_feed_next_step(self):
        task = self.task()
        source = 'async def run(ctx, inputs):\n    return ctx.result(outputs=[ctx.output("demo.table", "items", [{"value": "stored"}])])\n'
        one = self.confirm(self.step(task, source, capabilities=["demo.table"]))
        two = self.confirm(
            self.step(
                task,
                bindings={
                    "value": {
                        "ref": {
                            "source": "step",
                            "step_id": one["step_id"],
                            "output": "items",
                            "pointer": "/0",
                        }
                    }
                },
            ),
            {"value": "stored"},
        )
        done = self.run_task(task)
        self.assertEqual(done["status"], "SUCCEEDED", done)
        self.assertEqual(
            self.app.repo.read_output(done["run_id"], two["step_id"]),
            {"value": "stored"},
        )

    def test_output_run_isolation_and_stale_definition(self):
        task = self.task()
        step = self.confirm(
            self.step(
                task, bindings={"v": {"ref": {"source": "task", "pointer": "/v"}}}
            ),
            {"v": "sample"},
        )
        first = self.run_task(task, inputs={"v": "first"})
        second = self.run_task(task, inputs={"v": "second"})
        self.assertEqual(
            self.app.repo.read_output(first["run_id"], step["step_id"]), {"v": "first"}
        )
        self.assertEqual(
            self.app.repo.read_output(second["run_id"], step["step_id"]),
            {"v": "second"},
        )
        pending = self.app.create_run(task, {"v": "later"})
        self.app.repo.save_step(
            task, {**step, "goal": "changed"}, step["step_id"], step["content_hash"]
        )
        with self.assertRaisesRegex(TaskError, "RUN_CONFIG_CHANGED"):
            self.app.coordinator.start(pending["run_id"], uid())

    def test_result_save_failure_does_not_retry_business(self):
        task = self.task()
        source = 'async def run(ctx, inputs):\n    return ctx.result(outputs=[ctx.output("demo.table", "items", [{"value": inputs["v"]}])])\n'
        self.confirm(
            self.step(
                task,
                source,
                bindings={"v": {"ref": {"source": "task", "pointer": "/v"}}},
                capabilities=["demo.table"],
            ),
            {"v": "valid"},
        )
        # JSON object cannot be bound as a SQLite TEXT scalar: persistence fails after execution.
        done = self.run_task(task, inputs={"v": {"invalid": "row value"}})
        self.assertEqual(done["status"], "FAILED")
        self.assertEqual(done["attempts"][0]["error_code"], "RESULT_SAVE_FAILED")
        self.assertEqual(done["attempts"][0]["effect_state"], "SUCCEEDED")
        with self.assertRaisesRegex(TaskError, "RECONCILIATION_REQUIRED"):
            self.app.coordinator.start(
                done["run_id"], uid(), retry_step_id=done["attempts"][0]["step_id"]
            )

    def test_ai_write_tool_and_undeclared_capability_rejected(self):
        task = self.task()
        step = self.step(task, capabilities=["demo.echo"])
        self.app.registry.tools["demo.echo"].spec = replace(
            self.app.registry.tools["demo.echo"].spec, effect="WRITE"
        )
        self.app.authoring.model = ScriptedModel(
            [ModelReply(tool_calls=(ToolCall("c", "demo.echo", {}),))]
        )
        with self.assertRaisesRegex(TaskError, "AUTHORING_WRITE_REQUIRES_TRIAL"):
            asyncio.run(
                self.app.authoring.generate(step["step_id"], step["content_hash"])
            )
        self.app.authoring.model = ScriptedModel(
            [
                ModelReply(
                    'async def run(ctx, inputs):\n    return ctx.result(data=await ctx.call("text.upper", inputs))\n'
                ),
                ModelReply(
                    'async def run(ctx, inputs):\n    return ctx.result(data=await ctx.call("text.upper", inputs))\n'
                )
            ]
        )
        with self.assertRaises(TaskError):
            asyncio.run(
                self.app.authoring.generate(step["step_id"], step["content_hash"])
            )
        self.assertEqual(self.app.repo.step(step["step_id"])["step_content"], SOURCE)

    def test_file_storage_and_invalid_staged_token(self):
        from taskweave.core.ports import PreparedResult

        class FileHandler:
            def prepare(self, request):
                return PreparedResult(
                    "file", staged_token=request.payload, media_type="text/plain"
                )

        self.app.registry.handlers["file.text"] = FileHandler()
        task = self.task()
        scope = Scope(task, uid(), uid(), uid())
        result_store = Results(self.home, scope, self.app.registry)
        staged = asyncio.run(result_store.allocate_file("report"))
        Path(staged.local_path).write_text("business output")
        refs = result_store.persist(
            StepResult(outputs=[ResultRequest("file.text", "report", staged.token)])
        )
        self.assertEqual(
            (result_store.root / refs[0]["locator"]).read_text(), "business output"
        )
        self.assertEqual(len(refs[0]["checksum"]), 64)
        second = Results(self.home, Scope(task, uid(), uid(), uid()), self.app.registry)
        with self.assertRaises(TaskError):
            second.persist(
                StepResult(outputs=[ResultRequest("file.text", "bad", staged.token)])
            )

    def test_model_http_adapter_uses_local_gateway(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        received = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                received.append(
                    json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                )
                response = {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "step_content": SOURCE,
                                        "explanation": "local fixture",
                                    }
                                )
                            }
                        }
                    ]
                }
                data = json.dumps(response).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            model = HttpModel(
                f"http://127.0.0.1:{server.server_port}/chat/completions",
                "local-fixture",
            )
            reply = asyncio.run(
                model.complete([{"role": "user", "content": "Generate JSON"}], [], {})
            )
            self.assertEqual(reply.proposed_content, SOURCE)
            self.assertEqual(received[0]["model"], "local-fixture")
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

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

    def test_context_preview_and_plugin_diagnostics(self):
        from unittest.mock import AsyncMock
        from taskweave.core.ports import AuthoringContribution, ContextItem, Diagnostic

        task = self.task()
        step = self.step(
            task,
            'async def run(ctx, inputs):\n    raise ValueError("expected failure")\n',
            capabilities=["demo.echo"],
        )
        plugin = self.app.registry.plugins[0]
        plugin.authoring = lambda selected: AuthoringContribution(
            "demo", context_provider_ids=("demo.page",)
        )
        plugin.collect_context = AsyncMock(
            return_value=[ContextItem("text", "text/plain", "page title", "demo.page")]
        )
        items = asyncio.run(
            self.app.authoring.collect_context(step["step_id"], "demo.page")
        )
        self.assertEqual(items[0]["content"], "page title")
        with self.assertRaises(TaskError):
            asyncio.run(
                self.app.authoring.collect_context(step["step_id"], "unselected.page")
            )
        trial = self.app.trial_step(step["step_id"], {}, uid())
        done = self.app.coordinator.wait(trial["run_id"])
        plugin.diagnose = AsyncMock(
            return_value=[Diagnostic("CHECK_INPUT", "Inspect the supplied input")]
        )
        advice = asyncio.run(
            self.app.authoring.diagnose(done["attempts"][0]["attempt_id"])
        )
        self.assertEqual(advice[0]["code"], "CHECK_INPUT")


if __name__ == "__main__":
    unittest.main(verbosity=2)
