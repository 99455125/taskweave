"""Real browser flow for serial task sequences in a temporary workspace."""

import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest

from taskweave.application.service import Application


@unittest.skipUnless(importlib.util.find_spec("playwright"), "Playwright is not installed")
class SequencesBrowserTests(unittest.TestCase):
    def test_create_map_start_and_revisit_three_tasks(self):
        from playwright.sync_api import sync_playwright, expect
        with tempfile.TemporaryDirectory(prefix="taskweave-sequence-browser-") as temporary:
            with Application(temporary) as app:
                for name in ("First", "Second", "Third"):
                    task = app.repo.create_task(name, {"type": "object", "properties": {
                        "value": {"type": "integer"}}, "required": ["value"]})
                    step = app.repo.save_step(task["task_id"], {
                        "name": "Step", "step_content": "async def run(ctx, inputs):\n    return ctx.result(data={'value': inputs['value']})\n",
                        "input_schema": {"type": "object", "properties": {"value": {"type": "integer"}}, "required": ["value"]},
                        "bindings": {"value": {"ref": {"source": "task", "pointer": "/value"}}},
                    })
                    app.confirm_step_manual(step["step_id"], step["content_hash"])
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            log_path = Path(temporary) / "browser.log"
            with log_path.open("w") as log:
                process = subprocess.Popen([sys.executable, "-m", "taskweave", "--home", temporary,
                    "workbench", "--browser", "--port", str(port)], stdout=log, stderr=log)
                try:
                    url = None
                    deadline = time.monotonic() + 45
                    while time.monotonic() < deadline and not url:
                        for line in log_path.read_text().splitlines():
                            if line.startswith('{"url":'):
                                url = json.loads(line)["url"]
                        if process.poll() is not None:
                            self.fail(log_path.read_text())
                        time.sleep(0.1)
                    self.assertIsNotNone(url, log_path.read_text())
                    with sync_playwright() as playwright:
                        browser = playwright.chromium.launch(headless=True, channel="chromium")
                        try:
                            page = browser.new_page(viewport={"width": 1440, "height": 1000})
                            page.set_default_timeout(12000)
                            errors = []
                            page.on("pageerror", lambda error: errors.append(str(error)))
                            page.goto(url)
                            page.get_by_role("button", name="任务组合", exact=True).click()
                            page.get_by_label("组合名称").fill("Browser sequence")
                            for name in ("First", "Second", "Third"):
                                page.get_by_label("添加任务").click()
                                page.locator(".q-menu .q-item", has_text=name).click()
                                page.get_by_role("button", name="添加到末尾").click()
                            page.get_by_label("取值方式").nth(0).click()
                            page.locator(".q-menu .q-item", has_text="固定值").click()
                            page.get_by_label("JSON 值").fill("4")
                            page.get_by_label("取值方式").nth(1).click()
                            page.locator(".q-menu .q-item", has_text="前序任务输出").click()
                            page.get_by_label("来源任务和步骤").click()
                            page.locator(".q-menu .q-item", has_text="First · Step").click()
                            page.get_by_label("JSON 路径（留空表示整体）").fill("/value")
                            page.get_by_label("取值方式").nth(2).click()
                            page.locator(".q-menu .q-item", has_text="固定值").click()
                            page.get_by_label("JSON 值").nth(1).fill("5")
                            page.get_by_role("button", name="保存组合").click()
                            expect(page.get_by_text("组合已保存", exact=True)).to_be_visible()
                            page.get_by_label("JSON 值").nth(0).fill("6")
                            page.get_by_role("button", name="执行整个组合").click()
                            page.get_by_role("button", name="工作台", exact=True).click()
                            page.get_by_role("button", name="任务组合", exact=True).click()
                            expect(page.get_by_text("状态：成功", exact=True)).to_be_visible(timeout=20000)
                            import sqlite3
                            with sqlite3.connect(Path(temporary) / "taskweave.db") as db:
                                saved = json.loads(db.execute("SELECT nodes_json FROM task_sequences").fetchone()[0])
                            self.assertEqual(saved[0]["inputs"]["value"]["value"], 6)
                            self.assertFalse(errors, errors)
                        finally:
                            browser.close()
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=10)
