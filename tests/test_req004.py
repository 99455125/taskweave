"""Plugin contracts and real Chromium tests against the local business fixture."""

import asyncio
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

from taskweave.application.service import Application
from taskweave.core.ports import (
    AuthoringContribution,
    ModelReply,
    Scope,
    StepResult,
    ResultRequest,
    PreparedResult,
)
from taskweave.core.validation import TaskError
from taskweave.infrastructure.storage import Results, uid, connect
from taskweave.plugins.demo import DemoPlugin, TextPlugin
from taskweave.plugins.manager import PluginManager
from taskweave.plugins.registry import Registry

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples/req004"))
from mock_site import make_site


class Entry:
    dist = None

    def __init__(self, name, factory):
        self.name, self.factory, self.value = name, factory, "fixture:factory"

    def load(self):
        return self.factory


class ContractTests(unittest.TestCase):
    def test_dependency_versions_cycle_core_api_and_duplicate(self):
        demo = DemoPlugin()
        text = TextPlugin()
        text.manifest = lambda: {
            "id": "text",
            "api_version": 1,
            "package_version": "1.0.0",
            "dependencies": {"demo": ">=1,<2"},
        }
        self.assertEqual(set(Registry([text, demo]).versions), {"text", "demo"})
        with self.assertRaises(TaskError):
            Registry([text])
        with self.assertRaises(TaskError):
            Registry([demo, demo])
        demo.manifest = lambda: {
            "id": "demo",
            "api_version": 1,
            "package_version": "1.0.0",
            "dependencies": {"text": ">=1"},
        }
        with self.assertRaisesRegex(TaskError, "text|demo"):
            Registry([demo, text])
        for overrides in [
            {"api_version": 2},
            {"core_requires": ">=99"},
            {"package_version": "bad"},
        ]:
            demo = DemoPlugin()
            demo.manifest = lambda: {
                "id": "demo",
                "api_version": 1,
                "package_version": "1.0.0",
                **overrides,
            }
            with self.assertRaises(TaskError):
                Registry([demo])

    def test_discovery_disabled_load_failure_and_atomic_enable(self):
        with tempfile.TemporaryDirectory() as home:
            entries = [
                Entry("demo", DemoPlugin),
                Entry("text", TextPlugin),
                Entry("broken", lambda: (_ for _ in ()).throw(RuntimeError())),
            ]
            manager = PluginManager(home, entries)
            self.assertEqual(
                manager.registry(["demo", "text"]).versions, {"demo": "1.0.0", "text": "1.0.0"}
            )
            with self.assertRaises(TaskError):
                manager.configure("broken", True)
            self.assertFalse(manager.path.exists())
            manager.configure("demo", True)
            manager.configure("demo", False)
            self.assertEqual(manager.enabled(), [])
            with self.assertRaises(TaskError):
                PluginManager(home, [entries[1], entries[1]]).registry(["text"])
            with self.assertRaises(TaskError):
                manager.configure("absent", True)

    def test_action_schema_and_authoring_conflict(self):
        demo = DemoPlugin()
        action = demo.actions()["demo.echo"]
        action.spec = replace(action.spec, id="other.echo")
        demo.actions = lambda: {"demo.echo": action}
        with self.assertRaises(TaskError):
            Registry([demo])
        demo = DemoPlugin()
        text = TextPlugin()
        demo.authoring = lambda ids: AuthoringContribution(
            "a", constraints={"locator_style": "a"}
        )
        text.authoring = lambda ids: AuthoringContribution(
            "b", constraints={"locator_style": "b"}
        )
        with self.assertRaisesRegex(TaskError, "locator_style"):
            Registry([demo, text]).contributions(["demo.echo", "text.upper"])
        demo.authoring = lambda ids: AuthoringContribution(
            "override", constraints={"content_format": "sql"}
        )
        with self.assertRaisesRegex(TaskError, "content_format"):
            Registry([demo]).contributions(["demo.echo"])

    def test_declarative_table_migration_and_rollback(self):
        class Handler:
            version = 1

            def schema(self):
                cols = (
                    {"value": "TEXT"}
                    if self.version == 1
                    else {"value": "TEXT", "extra": "TEXT"}
                )
                return {
                    "version": self.version,
                    "tables": {"p_demo_migrated": cols},
                    "migrations": {
                        "2": {"add_columns": {"p_demo_migrated": {"extra": "TEXT"}}}
                    },
                    "indexes": {"p_demo_migrated": [["run_id", "step_id"]]},
                }

            def prepare(self, request):
                return PreparedResult(
                    "table", table_name="p_demo_migrated", rows=request.payload
                )

        registry = Registry([DemoPlugin()])
        handler = Handler()
        registry.handlers["demo.migrated"] = handler
        with tempfile.TemporaryDirectory() as home:
            task = uid()

            def persist(row):
                scoped = Results(home, Scope(task, uid(), uid(), uid()), registry)
                scoped.persist(
                    StepResult(outputs=[ResultRequest("demo.migrated", "items", [row])])
                )
                return scoped.path

            path = persist({"value": "before"})
            handler.version = 2
            persist({"value": "after", "extra": "new"})
            with connect(path) as db:
                self.assertEqual(
                    [
                        tuple(x)
                        for x in db.execute("SELECT value,extra FROM p_demo_migrated")
                    ],
                    [("before", None), ("after", "new")],
                )
                self.assertEqual(
                    db.execute("SELECT version FROM plugin_table_schemas").fetchone()[
                        0
                    ],
                    2,
                )
            handler.version = 3
            original = handler.schema
            handler.schema = lambda: {
                **original(),
                "tables": {
                    "p_demo_migrated": {
                        "value": "TEXT",
                        "extra": "TEXT",
                        "later": "TEXT",
                    }
                },
                "migrations": {
                    "3": {"add_columns": {"p_demo_migrated": {"later": "TEXT"}}}
                },
            }
            with self.assertRaises(TaskError):
                persist({"value": "invalid"})
            with connect(path) as db:
                self.assertNotIn(
                    "later",
                    [r[1] for r in db.execute("PRAGMA table_info(p_demo_migrated)")],
                )
                self.assertEqual(
                    db.execute("SELECT version FROM plugin_table_schemas").fetchone()[
                        0
                    ],
                    2,
                )

    def test_missing_enabled_package_does_not_block_unrelated_plugins(self):
        with tempfile.TemporaryDirectory() as home:
            manager = PluginManager(
                home, [Entry("demo", DemoPlugin), Entry("text", TextPlugin)]
            )
            manager.path.write_text(
                json.dumps({"format": 1, "enabled": ["demo", "text", "missing"]})
            )
            registry = manager.registry(strict=False)
            self.assertEqual(set(registry.versions), {"demo", "text"})
            self.assertEqual(registry.load_errors, {"missing": "PLUGIN_NOT_INSTALLED"})
            self.assertTrue(
                any(r["id"] == "missing" and r.get("error") for r in manager.catalog())
            )
            with self.assertRaises(TaskError):
                registry.check(
                    {"capabilities": ["missing.action"], "plugin_requirements": {}}
                )


@unittest.skipUnless(
    importlib.util.find_spec("taskweave_playwright"),
    "Install browser extra to run Chromium integration tests",
)
class BrowserTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="taskweave-browser-")
        self.app = Application(self.tmp.name)
        self.app.configure_plugin("playwright", True)
        self.env = self.app.repo.save_environment(
            "Browser", {"browser": {"headless": True, "timeout_ms": 5000}}
        )["environment_id"]
        self.server, self.state = make_site()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.app.close()
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()
        self.tmp.cleanup()

    def step(self, source, caps):
        task = self.app.repo.create_task("Browser test")
        return self.app.repo.save_step(
            task["task_id"], {"step_content": source, "capabilities": caps}
        )

    def trial(self, step, inputs=None):
        run = self.app.trial_step(step["step_id"], inputs or {}, uid(), self.env)
        return self.app.coordinator.wait(run["run_id"])

    def test_failed_trial_controller_can_close_browser_and_export_logs(self):
        from taskweave.desktop.controller import DesktopController
        step = self.step('async def run(ctx, inputs):\n    await ctx.call("playwright.page_open", {"url": "'+self.url+'"})\n    await ctx.call("playwright.page_click", {"selector": "#absent"})\n    return ctx.result(data={})', ['playwright.page_open','playwright.page_click'])
        run = self.trial(step)
        self.assertEqual(run['status'],'FAILED',run)
        self.assertTrue(self.app.coordinator.process.is_alive())
        controller = DesktopController(self.app)
        feedback = asyncio.run(controller.trial_feedback(run['run_id'],step['step_id']))
        self.assertEqual(feedback['status'],'FAILED')
        self.assertTrue(feedback['trial_logs'])
        pid = self.app.coordinator.process.pid
        revised = asyncio.run(controller.save_draft(step['task_id'], {**step, 'step_content': 'async def run(ctx, inputs):\n    return ctx.result(data=await ctx.call("playwright.page_title", {}))', 'capabilities': ['playwright.page_title']}, step))
        repeated = asyncio.run(controller.repeat_trial(revised, run['run_id']))
        finished = self.app.coordinator.wait(repeated['run_id'])
        self.assertEqual(finished['status'], 'SUCCEEDED')
        self.assertEqual(self.app.coordinator.process.pid, pid)
        self.assertEqual(self.app.repo.run_details(run['run_id'])['status'], 'FAILED')
        run = finished
        asyncio.run(controller.call('run.control',run_id=run['run_id'],command_id=uid(),operation='abandon'))
        self.assertIsNone(self.app.coordinator.process)

    def test_trial_and_formal_sessions_retained_until_explicit_end(self):
        task = self.app.repo.create_task("Retained browser")["task_id"]
        sources = [
            'async def run(ctx, inputs):\n    return ctx.result(data=await ctx.call("playwright.page_open", {"url": "'+self.url+'"}))',
            'async def run(ctx, inputs):\n    return ctx.result(data=await ctx.call("playwright.page_title", {}))',
        ]
        steps = []
        worker_pid = None
        for index in range(5):
            step = self.app.repo.save_step(task, {"name":str(index), "step_content":sources[0 if index == 0 else 1], "capabilities":["playwright.page_open", "playwright.page_title"]})
            trial = self.trial(step)
            self.assertEqual(trial["status"], "SUCCEEDED", trial)
            self.assertTrue(self.app.coordinator.process.is_alive())
            if worker_pid is None: worker_pid = self.app.coordinator.process.pid
            self.assertEqual(self.app.coordinator.process.pid, worker_pid)
            if index > 0:
                self.assertIn('TaskWeave Order', str(self.app.repo.read_output(trial['run_id'],step['step_id'],'data',self.app.registry)))
            step = self.app.confirm_step(step["step_id"], trial["attempts"][0]["attempt_id"], step["content_hash"])
            steps.append(step)
        run = self.app.create_run(task, {}, self.env)
        self.app.coordinator.start(run['run_id'],uid(),mode='UNTIL',target_step_id=steps[2]['step_id'])
        paused = self.app.coordinator.wait(run['run_id'])
        self.assertEqual(paused['status'],'PAUSED')
        self.assertEqual(len(paused['attempts']),3)
        pid = self.app.coordinator.process.pid
        self.app.coordinator.start(run['run_id'],uid(),mode='UNTIL',target_step_id=steps[4]['step_id'])
        completed = self.app.coordinator.wait(run['run_id'])
        self.assertEqual(completed['status'],'SUCCEEDED')
        self.assertEqual(len(completed['attempts']),5)
        self.assertEqual(self.app.coordinator.process.pid,pid)
        self.assertTrue(self.app.coordinator.process.is_alive())
        self.app.coordinator.control(run['run_id'],uid(),'abandon')
        self.assertIsNone(self.app.coordinator.process)
        self.assertEqual(self.app.repo.run(run['run_id'])['status'],'SUCCEEDED')

    def test_real_browser_workflow_saved_files_and_no_duplicate_submit(self):
        from browser_demo import run

        result = run(self.app, self.url)
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(result["output"], {"received_order_id": "ORDER-001"})
        self.assertEqual(self.state["count"], 1)
        image, download = result["files"]
        self.assertEqual(Path(image["path"]).read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        self.assertIn("ORDER-001", Path(download["path"]).read_text())

    def test_role_isolation_and_session_reused_between_steps(self):
        source = """async def run(ctx, inputs):
    await ctx.call("playwright.page_open", {"url": inputs["url"], "role": "a"})
    await ctx.call("playwright.page_fill", {"selector": "#name", "value": "Role A", "role": "a"})
    await ctx.call("playwright.page_open", {"url": inputs["url"], "role": "b"})
    return ctx.result()
"""
        step = self.step(source, ["playwright.page_open", "playwright.page_fill"])
        done = self.trial(step, {"url": self.url})
        self.assertEqual(done["status"], "SUCCEEDED", done)
        sessions = self.app.coordinator.context_sessions(step['task_id'])
        self.assertEqual([r['run_id'] for r in sessions], [done['run_id']])
        self.app.confirm_step(step['step_id'], done['attempts'][0]['attempt_id'], step['content_hash'])
        following = self.app.repo.save_step(step['task_id'], {'step_content': 'async def run(ctx, inputs):\n    return ctx.result()', 'capabilities': ['playwright.page_open']})
        observed = self.app.coordinator.collect_context(done['run_id'], following['step_id'], 'playwright.page', {'role': 'a'})
        self.assertTrue(observed)
        # Direct resource test on the public resource provider validates DOM isolation.
        from taskweave.infrastructure.worker import Resources, PluginContext
        from taskweave.core.ports import Scope

        async def inspect():
            scope = Scope(step["task_id"], uid(), step["step_id"], uid())
            resources = Resources(self.app.registry)
            results = Results(self.tmp.name, scope, self.app.registry)
            pc = PluginContext(
                scope,
                results,
                resources,
                {"browser": {"headless": True}},
                {},
                threading.Event(),
                lambda *a: None,
            )
            resources.context = pc
            try:
                a = await resources.acquire("playwright.session", "a")
                b = await resources.acquire("playwright.session", "b")
                await a["page"].goto(self.url)
                await b["page"].goto(self.url)
                await a["page"].fill("#name", "private A")
                await a["context"].add_cookies(
                    [{"name": "role", "value": "A", "url": self.url}]
                )
                self.assertEqual(await b["page"].input_value("#name"), "")
                self.assertEqual(await b["context"].cookies(), [])
                self.assertIs(await resources.acquire("playwright.session", "a"), a)
            finally:
                await resources.release_all()

        asyncio.run(inspect())

    def test_failure_screenshot_does_not_create_success_receipt(self):
        # Keep short timeout only for this intentionally absent-element scenario.
        self.app.repo.save_environment(
            "Browser",
            {"browser": {"headless": True, "timeout_ms": 700}},
            environment_id=self.env,
        )
        source = """async def run(ctx, inputs):
    await ctx.call("playwright.page_open", {"url": inputs["url"]})
    await ctx.call("playwright.page_click", {"selector": "#absent"})
    return ctx.result()
"""
        step = self.step(source, ["playwright.page_open", "playwright.page_click"])
        done = self.trial(step, {"url": self.url})
        self.assertEqual(done["status"], "FAILED", done)
        attempt = done["attempts"][0]
        self.assertEqual(attempt["effect_state"], "UNKNOWN")
        self.assertIsNone(self.app.repo.receipt(attempt))
        self.assertTrue(done["results"], self.app.repo.events(done["run_id"]))
        file = self.app.repo.read_result(
            done["results"][0]["result_id"], self.app.registry
        )
        self.assertTrue(Path(file["path"]).is_file())
        advice = asyncio.run(self.app.authoring.diagnose(attempt["attempt_id"]))
        self.assertEqual(advice[0]["code"], "CHECK_BROWSER_STATE")
        with self.assertRaises(TaskError):
            self.app.coordinator.start(
                done["run_id"], uid(), retry_step_id=step["step_id"]
            )

    def test_search_snapshot_failure_repair_and_retained_page(self):
        from taskweave.desktop.controller import DesktopController
        controller = DesktopController(self.app)
        caps = [cap for cap in self.app.registry.actions if cap.startswith('playwright.')]
        first = self.step('async def run(ctx, inputs):\n    await ctx.call("playwright.page_open", {"url": inputs["url"]})\n    return ctx.result()', caps)
        opened = self.trial(first, {'url': self.url + '/search-demo'})
        self.assertEqual(opened['status'], 'SUCCEEDED', opened)
        self.app.confirm_step(first['step_id'], opened['attempts'][0]['attempt_id'], first['content_hash'])
        second = self.app.repo.save_step(first['task_id'], {'capabilities': caps, 'step_content': 'async def run(ctx, inputs):\n    await ctx.call("playwright.page_input_value", {"selector": "#old-query"})\n    return ctx.result()'})
        failed = self.trial(second)
        self.assertEqual(failed['attempts'][0]['error_code'], 'LOCATOR_HIDDEN')
        pid = self.app.coordinator.process.pid
        feedback = asyncio.run(controller.trial_feedback(failed['run_id'], second['step_id']))
        self.assertEqual(feedback['failed_action']['action_id'], 'playwright.page_input_value')
        self.assertEqual(feedback['failed_action']['selector'], '#old-query')
        self.assertTrue(feedback['failure_snapshots'])
        contexts, status = asyncio.run(controller.repair_contexts(second, failed['run_id'], feedback))
        self.assertTrue(status['available'], status)
        data = json.loads(contexts[0]['content'])
        self.assertNotIn('old-query', [item['id'] for item in data['elements']])
        query = next(item for item in data['elements'] if item['id'] == 'search-editor')
        self.assertTrue(query['editable'])
        self.assertEqual(query['match_count'], 1)
        self.assertTrue(data['captured_at'])
        self.assertEqual(data['frames'][1]['frame_selector'], '#embedded')
        source = """async def run(ctx, inputs):
    query = {"kind": "role", "value": "textbox", "name": "Search query"}
    await ctx.call("playwright.page_fill", {"selector": query, "value": "ai最新资讯"})
    actual = await ctx.call("playwright.page_input_value", {"selector": query})
    assert actual["value"] == "ai最新资讯"
    await ctx.call("playwright.page_assert_value", {"selector": query, "value": "ai最新资讯"})
    await ctx.call("playwright.page_click", {"selector": {"kind": "role", "value": "button", "name": "Search"}})
    await ctx.call("playwright.page_assert_title", {"text": "ai最新资讯"})
    await ctx.call("playwright.page_assert_url", {"url": "**/search-results?query=**"})
    await ctx.call("playwright.page_assert_text", {"selector": "#results", "text": "ai最新资讯"})
    return ctx.result(data={"query": actual["value"]})
"""
        class Model:
            requests = []
            def capabilities(self): return {}
            async def complete(model, messages, tools, contract):
                model.requests.append(json.loads(json.dumps(messages)))
                return ModelReply(source, 'Use observed visible controls')
        model = Model()
        self.app.authoring.model = model
        proposal = asyncio.run(self.app.authoring.generate(second['step_id'], second['content_hash'], feedback=feedback, contexts=contexts, use_history=True))
        prompt = json.loads(model.requests[-1][-1]['content'])
        self.assertEqual(json.loads(prompt['contexts'][0]['content'])['captured_at'], data['captured_at'])
        self.assertIn('never guess', json.dumps(model.requests[-1]).lower())
        revised = asyncio.run(controller.save_draft(first['task_id'], {**second, 'step_content': proposal['proposed_content']}, second))
        repeated = asyncio.run(controller.repeat_trial(revised, failed['run_id']))
        done = self.app.coordinator.wait(repeated['run_id'])
        self.assertEqual(done['status'], 'SUCCEEDED', done)
        self.assertEqual(self.app.coordinator.process.pid, pid)
        self.assertEqual(self.app.repo.run_details(failed['run_id'])['status'], 'FAILED')
        new_contexts, _ = asyncio.run(controller.repair_contexts(revised, repeated['run_id'], feedback))
        self.assertIn('Results', json.loads(new_contexts[0]['content'])['title'])
        self.assertNotEqual(json.loads(new_contexts[0]['content'])['captured_at'], data['captured_at'])

    def test_disable_plugin_leaves_core_usable(self):
        step = self.step(
            'async def run(ctx, inputs):\n    return ctx.result(data=await ctx.call("playwright.page_title", {}))\n',
            ["playwright.page_title"],
        )
        self.app.configure_plugin("playwright", False)
        with self.assertRaisesRegex(TaskError, "playwright.page_title"):
            self.app.validate_step(step["step_id"])
        from taskweave.application.demo import run_demo

        self.assertEqual(run_demo(self.app)["status"], "SUCCEEDED")
        self.assertNotIn("playwright", self.app.registry.versions)

    def test_page_context_ai_read_tool_and_manual_proposal(self):
        source = 'async def run(ctx, inputs):\n    return ctx.result(data=await ctx.call("playwright.page_inspect", {}))\n'
        step = self.step(source, ["playwright.page_inspect"])
        contexts = asyncio.run(
            self.app.authoring.collect_context(
                step["step_id"], "playwright.page", {"url": self.url}, self.env
            )
        )
        observed = json.loads(contexts[0]["content"])
        self.assertEqual(observed["title"], "TaskWeave Order")
        self.assertTrue(observed["elements"])
        self.assertTrue(all("value" not in element for element in observed["elements"]))
        from taskweave.core.ports import ToolCall

        class Model:
            calls = 0

            def capabilities(self):
                return {"tools": True, "images": False}

            async def complete(model, messages, tools, contract):
                model.calls += 1
                if model.calls == 1:
                    self.assertIn("playwright.page_inspect", [t.id for t in tools])
                    return ModelReply(
                        tool_calls=(
                            ToolCall(
                                "observe", "playwright.page_inspect", {"url": self.url}
                            ),
                        )
                    )
                self.assertIn("TaskWeave Order", messages[-1]["content"])
                return ModelReply(source, "Observed title")

        model = Model()
        self.app.authoring.model = model
        proposal = asyncio.run(
            self.app.authoring.generate(
                step["step_id"],
                step["content_hash"],
                contexts=contexts,
                environment_id=self.env,
            )
        )
        self.assertEqual(proposal["proposed_content"], source)
        self.assertEqual(model.calls, 2)
        self.assertEqual(
            self.app.repo.step(step["step_id"])["validation_state"], "DRAFT"
        )
        self.assertEqual(self.trial(step)["status"], "SUCCEEDED")
        self.assertEqual(model.calls, 2)

    def test_third_party_plugin_contributes_without_core_changes(self):
        registry = Registry([TextPlugin()])
        contributions = registry.contributions(["text.upper"])
        self.assertEqual(len(contributions), 1)
        self.assertTrue(any("text.upper" in c.instructions for c in contributions))

    def test_paused_worker_context_observes_existing_page(self):
        source = 'async def run(ctx, inputs):\n    await ctx.call("playwright.page_open", {"url": inputs["url"]})\n    return ctx.result()\n'
        step = self.step(source, ["playwright.page_open"])
        done = self.trial(step, {"url": self.url})
        self.assertEqual(done["status"], "SUCCEEDED")
        self.app.confirm_step(
            step["step_id"], done["attempts"][0]["attempt_id"], step["content_hash"]
        )
        second = self.app.repo.save_step(
            step["task_id"],
            {"step_content": "async def run(ctx, inputs):\n    return ctx.result()\n"},
        )
        done = self.trial(second)
        self.app.confirm_step(
            second["step_id"], done["attempts"][0]["attempt_id"], second["content_hash"]
        )
        # Save bindings for the first step and re-confirm current source.
        current = self.app.repo.step(step["step_id"])
        current = self.app.repo.save_step(
            step["task_id"],
            {**current, "bindings": {"url": {"literal": self.url}}},
            step["step_id"],
            current["content_hash"],
        )
        done = self.trial(current, {"url": self.url})
        self.app.confirm_step(
            current["step_id"],
            done["attempts"][0]["attempt_id"],
            current["content_hash"],
        )
        run = self.app.create_run(step["task_id"], environment_id=self.env)
        self.app.coordinator.start(run["run_id"], uid(), mode="NEXT")
        self.assertEqual(self.app.coordinator.wait(run["run_id"])["status"], "PAUSED")
        items = self.app.dispatch(
            "context.read",
            {
                "step_id": step["step_id"],
                "provider_id": "playwright.page",
                "run_id": run["run_id"],
            },
        )
        self.assertEqual(json.loads(items[0]["content"])["title"], "TaskWeave Order")
        with self.assertRaises(TaskError):
            self.app.configure_plugin("playwright", False)
        self.app.coordinator.start(run["run_id"], uid())
        self.assertEqual(
            self.app.coordinator.wait(run["run_id"])["status"], "SUCCEEDED"
        )

    def test_manual_submission_checked_before_automated_submit(self):
        # Actual browser interaction outside the task represents manual takeover.
        from taskweave.infrastructure.worker import PluginContext, Resources

        async def human_interaction():
            resources = Resources(self.app.registry)
            scope = Scope(uid(), uid(), uid(), uid())
            pc = PluginContext(
                scope,
                Results(self.tmp.name, scope, self.app.registry),
                resources,
                {"browser": {"headless": False}},
                {},
                threading.Event(),
                lambda *a: None,
            )
            resources.context = pc
            try:
                session = await resources.acquire("playwright.session", "operator")
                page = session["page"]
                await page.goto(self.url)
                await self.app.registry.actions["playwright.page_handoff"].execute(
                    pc, {}
                )
                await page.click("#submit")
                await page.wait_for_selector("#order-id:not(:empty)")
            finally:
                await resources.release_all()

        asyncio.run(human_interaction())
        from browser_demo import run

        self.assertEqual(run(self.app, self.url)["status"], "SUCCEEDED")
        self.assertEqual(self.state["count"], 1)

    def test_post_submit_worker_loss_requires_external_query(self):
        source = """async def run(ctx, inputs):
    await ctx.call("playwright.page_open", {"url": inputs["url"]})
    await ctx.call("playwright.page_click", {"selector": "#submit"})
    await ctx.call("playwright.page_wait", {"selector": "#order-id:not(:empty)"})
    await ctx.call("playwright.page_wait", {"selector": "#never", "timeout_ms": 10000})
    return ctx.result()
"""
        step = self.step(
            source,
            [
                "playwright.page_open",
                "playwright.page_click",
                "playwright.page_wait",
                "playwright.page_wait",
            ],
        )
        run = self.app.trial_step(step["step_id"], {"url": self.url}, uid(), self.env)
        deadline = time.monotonic() + 45
        while self.state["count"] == 0 and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(
            self.state["count"], 1, self.app.repo.run_details(run["run_id"])
        )
        self.app.coordinator.process.terminate()
        done = self.app.coordinator.wait(run["run_id"])
        self.assertEqual(done["status"], "INTERRUPTED")
        self.assertEqual(done["attempts"][0]["status"], "UNKNOWN")
        with self.assertRaises(TaskError):
            self.app.coordinator.start(run["run_id"], uid())
        from urllib.request import urlopen

        with urlopen(self.url + "/state") as response:
            state = json.load(response)
        self.assertEqual(state["order_id"], "ORDER-001")
        self.app.coordinator.reconcile(
            done["attempts"][0]["attempt_id"],
            "completed",
            "Confirmed ORDER-001 from /state",
            uid(),
        )
        self.app.coordinator.start(run["run_id"], uid())
        self.assertEqual(
            self.app.coordinator.wait(run["run_id"])["status"], "SUCCEEDED"
        )
        self.assertEqual(self.state["count"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
