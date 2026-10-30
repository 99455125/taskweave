"""Plugin contracts and real Chromium tests against the local business fixture."""

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from taskweave.core.ports import (
    AuthoringContribution,
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

    def test_table_schema_changes_require_explicit_maintenance(self):
        class Handler:
            columns = {"value": "TEXT"}

            def schema(self):
                return {"tables": {"p_demo_items": self.columns},
                        "indexes": {"p_demo_items": [["run_id", "step_id"]]}}

            def prepare(self, request):
                return PreparedResult("table", table_name="p_demo_items", rows=request.payload)

        registry = Registry([DemoPlugin()])
        handler = Handler()
        registry.handlers["demo.items"] = handler
        with tempfile.TemporaryDirectory() as home:
            task = uid()

            def persist(row):
                scoped = Results(home, Scope(task, uid(), uid(), uid()), registry)
                scoped.persist(StepResult(outputs=[ResultRequest("demo.items", "items", [row])]))
                return scoped.path

            path = persist({"value": "before"})
            handler.columns = {"value": "TEXT", "extra": "TEXT"}
            with self.assertRaises(TaskError) as error:
                persist({"value": "after", "extra": "new"})
            self.assertEqual(error.exception.code, "TABLE_SCHEMA_MISMATCH")
            with connect(path) as db:
                self.assertEqual([tuple(r) for r in db.execute("SELECT value FROM p_demo_items")], [("before",)])
                self.assertNotIn("extra", [r[1] for r in db.execute("PRAGMA table_info(p_demo_items)")])
                self.assertEqual(db.execute("SELECT table_name FROM plugin_table_schemas").fetchone()[0], "p_demo_items")
            handler.columns = {"value": "TEXT"}
            persist({"value": "after"})
            with connect(path) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM p_demo_items").fetchone()[0], 2)

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
