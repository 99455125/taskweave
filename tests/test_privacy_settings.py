import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import asyncio

from taskweave.application.service import Application
from taskweave.infrastructure.privacy import PrivacySettings, redact_collected_context


class PrivacySettingsTests(unittest.TestCase):
    def test_independent_defaults_and_persistence(self):
        with tempfile.TemporaryDirectory() as home:
            settings = PrivacySettings(home)
            self.assertEqual(settings.get(), {"redact_on_display": True, "redact_for_ai": True})
            Path(home, "workbench.json").write_text(json.dumps({"executor_max_threads": 4}))
            settings.update(redact_on_display=False, redact_for_ai=True)
            self.assertEqual(settings.get(), {"redact_on_display": False, "redact_for_ai": True})
            settings.update(redact_on_display=True, redact_for_ai=False)
            self.assertEqual(settings.get(), {"redact_on_display": True, "redact_for_ai": False})
            self.assertEqual(json.loads(Path(home, "workbench.json").read_text())["executor_max_threads"], 4)

    def test_display_redaction_does_not_modify_original_or_image(self):
        source = {"items": [{"content": "password=abcd1234"}], "views": [{
            "renderer": "fake.image", "data": {"image_base64": "abc" * 30000, "password": "abcd1234"},
        }]}
        displayed = redact_collected_context(source, {"fake.image": {"type": "image"}})
        self.assertEqual(displayed["items"][0]["content"], "password=[REDACTED]")
        self.assertEqual(displayed["views"][0]["data"]["password"], "[REDACTED]")
        self.assertEqual(displayed["views"][0]["data"]["image_base64"], source["views"][0]["data"]["image_base64"])
        self.assertEqual(source["items"][0]["content"], "password=abcd1234")

    def test_serialized_json_evidence_redacts_sensitive_fields(self):
        source = {"items": [{"content": '{"password":"abcd1234","title":"page"}'}]}
        displayed = redact_collected_context(source, {})
        self.assertEqual(json.loads(displayed["items"][0]["content"]),
                         {"password": "[REDACTED]", "title": "page"})
        self.assertIn("abcd1234", source["items"][0]["content"])

    def test_authoring_ai_toggle(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            data = {"content": "password=abcd1234"}
            app.privacy_settings.update(redact_on_display=True, redact_for_ai=False)
            self.assertEqual(app.authoring._outbound(data), data)
            app.privacy_settings.update(redact_on_display=True, redact_for_ai=True)
            self.assertEqual(app.authoring._outbound(data), {"content": "password=[REDACTED]"})
            self.assertEqual(data["content"], "password=abcd1234")

    def test_planning_ai_toggle_keeps_stored_context_raw(self):
        with tempfile.TemporaryDirectory() as home, Application(home) as app:
            plan = app.planning.create("规划")
            saved = app.planning.contexts.save_context_batch(
                plan["plan_id"], plan["revision"], None, "fake.page", "页面", "",
                [{"label": "页面", "capture": {"items": [{"content": "password=abcd1234"}], "views": []}, "request": {}}],
            )
            capture_id = saved["group"]["captures"][0]["capture_id"]
            current_plan = app.planning.get(plan["plan_id"])

            from taskweave.desktop.planning import PlanningPage
            from taskweave.desktop.state import PlanningPageState

            controller = MagicMock()
            controller.privacy_settings.side_effect = app.privacy_settings.get
            controller.result_renderers = {}
            page = PlanningPage(controller, PlanningPageState(plan_id=plan["plan_id"]), None, None, None, None)

            class UIContext:
                def __enter__(self):
                    return self

                def __exit__(self, *_):
                    return False

                def classes(self, *_):
                    return self

                def props(self, *_):
                    return self

                def open(self):
                    return None

                def close(self):
                    return None

            dialog, card = UIContext(), UIContext()
            fake_ui = MagicMock()
            fake_ui.dialog.return_value = dialog
            fake_ui.card.return_value = card

            async def visible_capture_text():
                with patch("taskweave.desktop.planning.ui", fake_ui):
                    await page.show_context_preview(
                        "页面", {"items": [{"content": "password=abcd1234"}], "views": []}
                    )
                return fake_ui.code.call_args.args[0]

            # Holding AI redaction off while toggling display proves the settings
            # are independent on the real planning preview path.
            app.privacy_settings.update(redact_on_display=True, redact_for_ai=False)
            self.assertIn("password=[REDACTED]", asyncio.run(visible_capture_text()))
            self.assertIn("password=abcd1234", app.planning._messages(current_plan)[1]["content"])
            app.privacy_settings.update(redact_on_display=False, redact_for_ai=False)
            self.assertIn("password=abcd1234", asyncio.run(visible_capture_text()))
            self.assertIn("password=abcd1234", app.planning._messages(current_plan)[1]["content"])

            # Holding display redaction off while toggling AI proves the reverse.
            app.privacy_settings.update(redact_on_display=False, redact_for_ai=True)
            self.assertIn("password=abcd1234", asyncio.run(visible_capture_text()))
            self.assertIn("password=[REDACTED]", app.planning._messages(current_plan)[1]["content"])
            stored = app.planning.contexts.get_capture(saved["group"]["context_id"], capture_id, plan["plan_id"])
            self.assertEqual(stored["items"][0]["content"], "password=abcd1234")
