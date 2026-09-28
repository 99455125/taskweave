"""Context inspection stays independent of executable draft content."""

import tempfile
import unittest

from taskweave.application.service import Application
from taskweave.core.ports import AuthoringContribution, ContextCollection, ContextItem
from taskweave.core.validation import TaskError
from taskweave.infrastructure.storage import uid
from taskweave.plugins.demo import DemoPlugin
from taskweave.plugins.registry import Registry


class Resource:
    async def open(self, ctx, role): return role
    async def close(self, resource): pass


class TargetPlugin(DemoPlugin):
    def authoring(self, selected_ids):
        return AuthoringContribution("", context_provider_ids=("demo.page",))

    def resource_providers(self): return {"demo.resource": Resource()}

    async def collect_context(self, provider_id, ctx, request, *, include_view=True):
        role = await ctx.resources.acquire("demo.resource", request.get("role", "main"))
        return ContextCollection((ContextItem("text", "text/plain", role, "demo.page"),))

    async def list_context_targets(self, provider_id, ctx, request):
        return [{"target_id": role, "label": role, "request": {"role": role}}
                for role, _ in ctx.resources.active("demo.resource")]


def build_registry(): return Registry([TargetPlugin()])


class ContextTargetRuntimeTests(unittest.TestCase):
    def test_retained_worker_targets_accept_empty_draft_and_reject_old_session(self):
        with tempfile.TemporaryDirectory() as home, Application(home, registry_factory=f"{__name__}:build_registry") as app:
            task_id = app.repo.create_task("Context targets")["task_id"]
            step = app.repo.save_step(task_id, {"name": "Step", "step_content": "async def run(ctx, inputs):\n    return ctx.result(data={})\n", "capabilities": ["demo.echo"]})
            params = {"step_id": step["step_id"], "provider_id": "demo.page"}
            self.assertEqual(app.dispatch("context.targets", params), {"session_id": None, "targets": []})
            run = app.trial_step(step["step_id"], {}, uid())
            done = app.coordinator.wait(run["run_id"])
            self.assertEqual(done["status"], "SUCCEEDED", done)
            params["run_id"] = run["run_id"]
            app.dispatch("context.read", {**params, "request": {"role": "chosen"}})
            app.repo.save_step(task_id, {"name": "Draft", "step_content": "", "capabilities": ["demo.echo"]}, step_id=step["step_id"], expected_hash=step["content_hash"])
            result = app.dispatch("context.targets", params)
            self.assertEqual(result["targets"], [{"target_id": "chosen", "label": "chosen", "request": {"role": "chosen"}}])
            self.assertTrue(result["session_id"])
            items = app.dispatch("context.read", {**params, "request": result["targets"][0]["request"], "expected_session_id": result["session_id"]})
            self.assertEqual(items["items"][0]["content"], "chosen")
            with self.assertRaises(TaskError) as stale:
                app.dispatch("context.read", {**params, "expected_session_id": "outdated"})
            self.assertEqual(stale.exception.code, "CONTEXT_SESSION_CHANGED")
