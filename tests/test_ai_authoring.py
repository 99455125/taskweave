"""Real application integration tests: spawn workers, SQLite and loopback HTTP."""
import asyncio
from dataclasses import replace
import json
import threading
from taskweave.core.ports import ModelReply, ToolCall
from taskweave.core.validation import TaskError
from taskweave.infrastructure.storage import uid
from taskweave.infrastructure.model import HttpModel

SOURCE = "async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n"
from tests._core_fixture import CoreFixture, ScriptedModel

class AiAuthoringTests(CoreFixture):
    def test_ai_tool_generation_editing_and_manual_execution(self):
        task = self.task()
        bad = 'async def run(ctx, inputs):\n    raise ValueError("fix me")\n'
        step = self.step(
            task,
            bad,
            capabilities=["demo.echo", "text.upper"],
            step_description="Return the inputs",
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
        from taskweave.core.ports import ContextCollection
        plugin.collect_context = AsyncMock(
            return_value=ContextCollection((ContextItem("text", "text/plain", "page title", "demo.page"),))
        )
        items = asyncio.run(
            self.app.authoring.collect_context(step["step_id"], "demo.page")
        )
        self.assertEqual(items["items"][0]["content"], "page title")
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
