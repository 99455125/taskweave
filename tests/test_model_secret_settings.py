"""Durable interval scheduling, task operations and desktop API evidence."""
import asyncio
import json
from pathlib import Path
from taskweave.desktop.controller import DesktopController
from tests._runtime_fixture import RuntimeFixture

class ModelSecretSettingsTests(RuntimeFixture):
    def test_model_secret_is_persisted_and_restored_for_same_url(self):
        controller = DesktopController(self.app)
        asyncio.run(
            controller.save_model(
                "https://model.example/v1/chat/completions",
                "fixture",
                "",
                "test-session-secret",
            )
        )
        stored = Path(self.temp.name, "model.json").read_text()
        self.assertEqual(json.loads(stored)["api_key"], "test-session-secret")
        self.assertEqual(self.app.authoring.model.api_key, "test-session-secret")
        self.app.authoring.model = None
        asyncio.run(
            controller.save_model(
                "https://model.example/v1/chat/completions", "fixture", ""
            )
        )
        self.assertEqual(self.app.authoring.model.api_key, "test-session-secret")
        asyncio.run(
            controller.save_model(
                "https://another-model.example/v1/chat/completions", "fixture", ""
            )
        )
        self.assertIsNone(self.app.authoring.model.api_key)
