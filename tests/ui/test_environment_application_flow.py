"""Environment draft transitions against the real application and NiceGUI client."""

import asyncio
import json
import tempfile
import unittest
from unittest.mock import patch

from nicegui import ui
from nicegui.client import Client
from nicegui.page import page

from taskweave.application.service import Application
from taskweave.core.validation import TaskError
from taskweave.desktop.controller import DesktopController
from taskweave.desktop.workbench import Workbench


class Choice:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def __await__(self):
        async def result():
            return self.value
        return result().__await__()


class EnvironmentApplicationFlowTests(unittest.TestCase):
    def test_dirty_values_protect_switch_and_save_preserves_secret_references(self):
        async def scenario(app, client):
            with client:
                env_a = app.dispatch("environment.save", {
                    "name": "A", "public_config": {"keep": "yes"},
                    "secret_refs": {"token": "env:TOKEN"},
                    "descriptions": {"keep": "keep me"},
                })
                env_b = app.dispatch("environment.save", {"name": "B", "public_config": {}, "secret_refs": {}})
                workbench = Workbench(DesktopController(app))
                callbacks = {}

                def track_button(title, callback, **_kwargs):
                    callbacks[title] = callback
                    return ui.button(title)

                workbench.environment_page.button = track_button
                workbench.environment_page.selected_environment_id = env_a["environment_id"]
                button_callbacks = {"添加变量": [], "移除": []}
                original_button = ui.button

                def capture_button(text="", *args, **kwargs):
                    if text in button_callbacks and kwargs.get("on_click"):
                        button_callbacks[text].append(kwargs["on_click"])
                    return original_button(text, *args, **kwargs)

                with patch("taskweave.desktop.pages.environments.ui.button", side_effect=capture_button):
                    await workbench.navigate("environment")

                def field(label):
                    return next(element for element in client.elements.values()
                                if getattr(element, "_props", {}).get("label") == label and not element.is_deleted)

                with patch("taskweave.desktop.pages.environments.ui.button", side_effect=capture_button):
                    button_callbacks["添加变量"][-1]()
                    fields = [element for element in client.elements.values()
                              if getattr(element, "_props", {}).get("label") == "Key" and not element.is_deleted]
                    fields[-1].value = "temporary"
                    button_callbacks["移除"][-1]()
                    button_callbacks["添加变量"][-1]()
                live_keys = [element for element in client.elements.values()
                             if getattr(element, "_props", {}).get("label") == "Key" and not element.is_deleted]
                live_values = [element for element in client.elements.values()
                               if getattr(element, "_props", {}).get("label") == "Value" and not element.is_deleted]
                live_descriptions = [element for element in client.elements.values()
                                     if getattr(element, "_props", {}).get("label") == "说明（可选）" and not element.is_deleted]
                live_keys[-1].value = "added"
                live_values[-1].value = "42"
                live_descriptions[-1].value = "persist this row"
                field("Value").value = "unsaved"
                with patch("taskweave.desktop.pages.environments.ui.dialog", return_value=Choice("stay")) as dialog:
                    await callbacks["B"]()
                self.assertTrue(dialog.called, "a value-only edit must trigger the unsaved-changes prompt")
                self.assertEqual(workbench.environment_page.selected_environment_id, env_a["environment_id"])

                with patch("taskweave.desktop.pages.environments.ui.dialog", return_value=Choice("save")):
                    await callbacks["B"]()
                saved_a = next(item for item in app.dispatch("environment.list", {})
                               if item["environment_id"] == env_a["environment_id"])
                self.assertEqual(json.loads(saved_a["public_config_json"]), {"keep": "unsaved", "added": 42})
                self.assertEqual(json.loads(saved_a["secret_refs_json"]), {"token": "env:TOKEN"})
                self.assertEqual(json.loads(saved_a["descriptions_json"]), {"keep": "keep me", "added": "persist this row"})
                self.assertEqual(workbench.environment_page.selected_environment_id, env_b["environment_id"])

                field("环境名称").value = "discard this name"
                with patch("taskweave.desktop.pages.environments.ui.dialog", return_value=Choice("discard")):
                    await callbacks["A"]()
                saved_b = next(item for item in app.dispatch("environment.list", {})
                               if item["environment_id"] == env_b["environment_id"])
                self.assertEqual(saved_b["name"], "B")
                self.assertEqual(workbench.environment_page.selected_environment_id, env_a["environment_id"])
                await callbacks["B"]()

                field("环境名称").value = ""
                with patch("taskweave.desktop.pages.environments.ui.dialog", return_value=Choice("save")):
                    with self.assertRaises(TaskError):
                        await workbench.navigate("home")
                self.assertEqual(workbench.page, "environment", "a failed save must block navigation")
                field("环境名称").value = "B edited"
                with patch("taskweave.desktop.pages.environments.ui.dialog", return_value=Choice("stay")) as dialog:
                    self.assertFalse(await workbench.navigate("home"))
                self.assertTrue(dialog.called, "leaving the environment page must protect its draft")
                self.assertEqual(workbench.page, "environment")
                with patch("taskweave.desktop.pages.environments.ui.dialog", return_value=Choice("save")):
                    self.assertTrue(await workbench.navigate("home"))
                saved_b = next(item for item in app.dispatch("environment.list", {})
                               if item["environment_id"] == env_b["environment_id"])
                self.assertEqual(saved_b["name"], "B edited")
                workbench._dispose_page(workbench.page)

        with tempfile.TemporaryDirectory(prefix="taskweave-env-flow-") as home, Application(home) as app:
            client = Client(page("/environment-application-flow"))
            try:
                asyncio.run(scenario(app, client))
            finally:
                client.delete()

    def test_secret_rows_delete_and_rename_without_touching_public_variables(self):
        async def scenario(app, client):
            with client:
                removed = app.dispatch("environment.save", {
                    "name": "Remove", "public_config": {"keep": "ordinary"},
                    "secret_refs": {"token": "env:TOKEN"},
                })
                renamed = app.dispatch("environment.save", {
                    "name": "Rename", "public_config": {"keep": "ordinary"},
                    "secret_refs": {"token": "env:TOKEN"},
                })
                workbench = Workbench(DesktopController(app))
                callbacks, remove_callbacks = {}, []

                def track_button(title, callback, **_kwargs):
                    callbacks[title] = callback
                    return ui.button(title)

                original_button = ui.button

                def capture_button(text="", *args, **kwargs):
                    if text == "移除" and kwargs.get("on_click"):
                        remove_callbacks.append(kwargs["on_click"])
                    return original_button(text, *args, **kwargs)

                workbench.environment_page.button = track_button
                workbench.environment_page.selected_environment_id = removed["environment_id"]
                with patch("taskweave.desktop.pages.environments.ui.button", side_effect=capture_button):
                    await workbench.navigate("environment")
                remove_callbacks[-1]()
                await callbacks["保存环境"]()
                saved = {item["environment_id"]: item for item in app.dispatch("environment.list", {})}
                self.assertEqual(json.loads(saved[removed["environment_id"]]["public_config_json"]), {"keep": "ordinary"})
                self.assertEqual(json.loads(saved[removed["environment_id"]]["secret_refs_json"]), {})

                await workbench.environment_page.open_environment(renamed["environment_id"])
                keys = [element for element in client.elements.values()
                        if getattr(element, "_props", {}).get("label") == "Key" and not element.is_deleted]
                keys[-1].value = "renamed_token"
                await callbacks["保存环境"]()
                saved = {item["environment_id"]: item for item in app.dispatch("environment.list", {})}
                self.assertEqual(json.loads(saved[renamed["environment_id"]]["public_config_json"]), {"keep": "ordinary"})
                self.assertEqual(json.loads(saved[renamed["environment_id"]]["secret_refs_json"]), {"renamed_token": "env:TOKEN"})
                self.assertNotIn("token", json.loads(saved[renamed["environment_id"]]["secret_refs_json"]))
                values = [element for element in client.elements.values()
                          if getattr(element, "_props", {}).get("label") == "Value" and not element.is_deleted]
                values[-1].value = "secret text must not become public"
                with self.assertRaises(TaskError):
                    await callbacks["保存环境"]()
                saved = {item["environment_id"]: item for item in app.dispatch("environment.list", {})}
                self.assertEqual(json.loads(saved[renamed["environment_id"]]["public_config_json"]), {"keep": "ordinary"})
                self.assertEqual(json.loads(saved[renamed["environment_id"]]["secret_refs_json"]), {"renamed_token": "env:TOKEN"})
                workbench._dispose_page(workbench.page)

        with tempfile.TemporaryDirectory(prefix="taskweave-env-secret-rows-") as home, Application(home) as app:
            client = Client(page("/environment-secret-rows"))
            try:
                asyncio.run(scenario(app, client))
            finally:
                client.delete()

    def test_late_save_does_not_reselect_or_repaint_a_new_environment_draft(self):
        async def scenario(app, client):
            with client:
                env_a = app.dispatch("environment.save", {"name": "A", "public_config": {"keep": "yes"}})
                env_b = app.dispatch("environment.save", {"name": "B", "public_config": {}})
                workbench = Workbench(DesktopController(app))
                workbench.environment_page.selected_environment_id = env_a["environment_id"]
                await workbench.navigate("environment")
                entered, release = asyncio.Event(), asyncio.Event()
                original_call = workbench.controller.call

                async def delayed_call(operation, **kwargs):
                    if operation == "environment.save":
                        entered.set()
                        await release.wait()
                    return await original_call(operation, **kwargs)

                workbench.controller.call = delayed_call
                pending = asyncio.create_task(workbench.environment_page.save_environment(
                    "A renamed", [("keep", "yes", "")], environment_id=env_a["environment_id"], refresh=True,
                ))
                await entered.wait()
                await workbench.environment_page.open_environment(env_b["environment_id"])
                name = next(element for element in client.elements.values()
                            if getattr(element, "_props", {}).get("label") == "环境名称" and not element.is_deleted)
                name.value = "B draft"
                b_identity = workbench.environment_page.view_identity()
                release.set()
                await pending
                current_name = next(element for element in client.elements.values()
                                    if getattr(element, "_props", {}).get("label") == "环境名称" and not element.is_deleted)
                self.assertEqual(workbench.environment_page.selected_environment_id, env_b["environment_id"])
                self.assertEqual(current_name.value, "B draft")
                self.assertEqual(workbench.environment_page.view_identity(), b_identity)
                stored = {item["environment_id"]: item for item in app.dispatch("environment.list", {})}
                self.assertEqual(stored[env_a["environment_id"]]["name"], "A renamed")
                workbench._dispose_page(workbench.page)

        with tempfile.TemporaryDirectory(prefix="taskweave-env-late-save-") as home, Application(home) as app:
            client = Client(page("/environment-late-save"))
            try:
                asyncio.run(scenario(app, client))
            finally:
                client.delete()

    def test_new_environment_saves_once_and_reuses_its_persisted_id(self):
        async def scenario(app, client):
            with client:
                env_b = app.dispatch("environment.save", {"name": "B", "public_config": {}})
                workbench = Workbench(DesktopController(app))
                callbacks = {}

                def track_button(title, callback, **_kwargs):
                    callbacks[title] = callback
                    return ui.button(title)

                workbench.environment_page.button = track_button
                await workbench.navigate("environment")

                def field(label):
                    return next(element for element in client.elements.values()
                                if getattr(element, "_props", {}).get("label") == label and not element.is_deleted)

                await callbacks["新建"]()
                field("环境名称").value = "save on leave"
                with patch("taskweave.desktop.pages.environments.ui.dialog", return_value=Choice("save")):
                    self.assertTrue(await workbench.navigate("home"))
                rows = app.dispatch("environment.list", {})
                created = [item for item in rows if item["name"] == "save on leave"]
                self.assertEqual(len(created), 1)
                self.assertEqual(workbench.page, "home")

                await workbench.navigate("environment")
                await callbacks["新建"]()
                field("环境名称").value = "manual create"
                await callbacks["保存环境"]()
                first = [item for item in app.dispatch("environment.list", {}) if item["name"] == "manual create"]
                self.assertEqual(len(first), 1)
                first_id = first[0]["environment_id"]
                field("环境名称").value = "manual create updated"
                await callbacks["保存环境"]()
                rows = app.dispatch("environment.list", {})
                self.assertEqual(sum(item["name"].startswith("manual create") for item in rows), 1)
                updated = next(item for item in rows if item["name"] == "manual create updated")
                self.assertEqual(updated["environment_id"], first_id)

                await callbacks["新建"]()
                field("环境名称").value = "save before switch"
                with patch("taskweave.desktop.pages.environments.ui.dialog", return_value=Choice("save")):
                    await callbacks["B"]()
                rows = app.dispatch("environment.list", {})
                created = [item for item in rows if item["name"] == "save before switch"]
                self.assertEqual(len(created), 1)
                self.assertEqual(workbench.environment_page.selected_environment_id, env_b["environment_id"])
                workbench._dispose_page(workbench.page)

        with tempfile.TemporaryDirectory(prefix="taskweave-env-new-id-") as home, Application(home) as app:
            client = Client(page("/environment-new-id"))
            try:
                asyncio.run(scenario(app, client))
            finally:
                client.delete()


if __name__ == "__main__":
    unittest.main()
