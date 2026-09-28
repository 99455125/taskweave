"""Real application integration tests: spawn workers, SQLite and loopback HTTP."""
import json
from pathlib import Path
import tempfile
import unittest
from taskweave.application.service import Application
from taskweave.infrastructure.storage import uid

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


class CoreFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="taskweave-test-")
        self.home = Path(self.tmp.name)
        self.app = Application(self.home, registry_factory="taskweave.plugins.demo:build_registry")

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
