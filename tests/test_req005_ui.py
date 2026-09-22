"""Real NiceGUI browser acceptance against a separate application process."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from urllib.request import urlopen, Request
from urllib.error import HTTPError

GUI_AVAILABLE = all(
    importlib.util.find_spec(name) for name in ["nicegui", "playwright"]
)


class FixtureModel(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        source = 'async def run(ctx, inputs):\n    return ctx.result(data={"ai": True})\n'
        payload = json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": None,
                            "content": json.dumps(
                                {
                                    "step_content": source,
                                    "explanation": "测试模型建议，不访问外部服务",
                                }
                            )
                        }
                    }
                ]
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
        self.server.requests.append(body)

    def log_message(self, *args):
        pass


@unittest.skipUnless(GUI_AVAILABLE, "Install gui and browser extras for UI acceptance")
class WorkbenchAcceptance(unittest.TestCase):
    def test_real_task_authoring_ai_trial_run_history_and_configuration(self):
        from playwright.sync_api import sync_playwright, expect
        import sqlite3
        from contextlib import closing

        with tempfile.TemporaryDirectory(prefix="taskweave-ui-") as temporary:
            provider = ThreadingHTTPServer(("127.0.0.1", 0), FixtureModel)
            provider.requests = []
            thread = threading.Thread(target=provider.serve_forever, daemon=True)
            thread.start()
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            environment = dict(
                os.environ,
                TASKWEAVE_MODEL_URL=f"http://127.0.0.1:{provider.server_port}/chat",
                TASKWEAVE_MODEL_NAME="fixture",
            )
            log_path = Path(temporary) / "server.log"
            log = log_path.open("w")
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "taskweave",
                    "--home",
                    temporary,
                    "workbench",
                    "--browser",
                    "--port",
                    str(port),
                ],
                stdout=log,
                stderr=log,
                env=environment,
            )
            try:
                url = None
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    for line in log_path.read_text().splitlines():
                        if line.startswith('{"url":'):
                            url = json.loads(line)["url"]
                    if url:
                        try:
                            with urlopen(url, timeout=1):
                                break
                        except (OSError, HTTPError):
                            pass
                    if process.poll() is not None:
                        self.fail(log_path.read_text())
                    time.sleep(0.1)
                self.assertIsNotNone(url)
                bare = f"http://127.0.0.1:{port}/"
                with self.assertRaises(HTTPError) as denied:
                    urlopen(bare)
                self.assertEqual(denied.exception.code, 403)
                with self.assertRaises(HTTPError) as origin_denied:
                    urlopen(
                        Request(url, headers={"Origin": "https://unrelated.example"})
                    )
                self.assertEqual(origin_denied.exception.code, 403)
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(
                        headless=True, channel="chromium"
                    )
                    evidence = (
                        Path(__file__).resolve().parents[1]
                        / ".runtime/req005-ui-evidence"
                    )
                    evidence.mkdir(parents=True, exist_ok=True)
                    page = browser.new_page(viewport={"width": 1280, "height": 950})
                    errors, external = [], []
                    page.on("pageerror", lambda e: errors.append(str(e)))
                    page.on(
                        "request",
                        lambda r: (
                            external.append(r.url)
                            if not r.url.startswith(f"http://127.0.0.1:{port}/")
                            else None
                        ),
                    )
                    page.goto(url)
                    expect(
                        page.get_by_role("button", name="新建任务", exact=True)
                    ).to_be_visible()
                    self.assertEqual(
                        page.get_by_role("button", name="步骤编写", exact=True).count(),
                        0,
                    )
                    page.get_by_role("button", name="新建任务", exact=True).click()
                    page.get_by_label("任务名称", exact=True).fill("UI 验收任务")
                    page.get_by_role("button", name="保存", exact=True).click()
                    page.get_by_role("button", name="添加步骤", exact=True).click()
                    expect(
                    page.get_by_role("button", name="调试历史", exact=True)
                    ).to_be_visible()
                    page.get_by_label("步骤名称", exact=True).fill("AI 编写等待步骤")
                    page.get_by_role(
                        "button", name="AI 生成内容", exact=True
                    ).click()
                    page.get_by_role("button", name="使用 API", exact=True).click()
                    expect(
                        page.get_by_role("button", name="采纳到编辑器", exact=True)
                    ).to_be_visible(timeout=15000)
                    page.get_by_role("button", name="采纳到编辑器", exact=True).click()
                    editor = page.locator(".cm-content")
                    editor.click()
                    editor.press("ControlOrMeta+A")
                    page.keyboard.insert_text(
                        'async def run(ctx, inputs):\n    return ctx.result(data={"manual_adjustment": True})\n'
                    )
                    page.get_by_role("button", name="调试当前步骤", exact=True).click()
                    expect(
                        page.get_by_text("调试状态：成功", exact=True)
                    ).to_be_visible(timeout=15000)
                    page.get_by_role("tab", name="步骤详情", exact=True).click()
                    page.get_by_role(
                        "button", name="确认验证并保存", exact=True
                    ).click()
                    expect(
                        page.get_by_role(
                            "button", name="1. AI 编写等待步骤", exact=True
                        )
                    ).to_be_visible()
                    page.get_by_role("button", name="+", exact=True).click()
                    expect(page.get_by_role("button", name="2. 新步骤", exact=True)).to_be_visible()
                    page.get_by_label("步骤名称", exact=True).fill("手写文本步骤")
                    expect(page.get_by_label("步骤名称", exact=True)).to_have_value("手写文本步骤")
                    page.get_by_role("tab", name="时间设置", exact=True).click()
                    page.get_by_label("上一步成功后等待（秒）", exact=True).fill("2")
                    page.get_by_role("button", name="保存步骤设置", exact=True).click()
                    page.get_by_role("tab", name="步骤详情", exact=True).click()
                    page.get_by_role("button", name="调试当前步骤", exact=True).click()
                    expect(
                        page.get_by_text("调试状态：成功", exact=True)
                    ).to_be_visible(timeout=15000)
                    page.get_by_role("tab", name="步骤详情", exact=True).click()
                    page.get_by_role(
                        "button", name="确认验证并保存", exact=True
                    ).click()
                    expect(
                        page.get_by_text("2. 手写文本步骤", exact=True)
                    ).to_be_visible()
                    with closing(sqlite3.connect(Path(temporary) / "taskweave.db")) as db:
                        second_saved = db.execute("SELECT name,validation_state FROM steps ORDER BY position").fetchall()[1]
                    self.assertEqual(second_saved, ("手写文本步骤", "VALIDATED"))
                    page.screenshot(
                        path=str(evidence / "step-editor.png"), full_page=True
                    )
                    page.get_by_role("button", name="执行", exact=True).click()
                    page.get_by_role(
                        "button", name="新建执行", exact=True
                    ).click()
                    page.get_by_role("button", name="创建并执行", exact=True).click()
                    expect(
                        page.get_by_text("运行状态：成功", exact=True)
                    ).to_be_visible(timeout=20000)
                    page.screenshot(
                        path=str(evidence / "execution.png"), full_page=True
                    )
                    self.assertEqual(
                        len(provider.requests), 1
                    )  # fixed execution never invokes the model
                    page.get_by_role("button", name="任务", exact=True).click()
                    page.get_by_role("button", name="打开", exact=True).click()
                    page.get_by_role("button", name="1. AI 编写等待步骤", exact=True).click()
                    page.get_by_role("button", name="AI 生成内容", exact=True).click()
                    page.get_by_role("button", name="使用 Chat 网页", exact=True).click()
                    expect(page.get_by_label("复制到网页 AI 的内容", exact=True)).to_be_visible()
                    self.assertIn('async def run', page.get_by_label("复制到网页 AI 的内容", exact=True).input_value())
                    with closing(sqlite3.connect(Path(temporary) / "taskweave.db")) as db:
                        web_source = db.execute("SELECT step_content FROM steps WHERE name=?", ("AI 编写等待步骤",)).fetchone()[0]
                    page.get_by_label("粘贴网页 AI 回复", exact=True).fill(json.dumps({'step_content': web_source, 'explanation':'网页回复'}))
                    page.get_by_role("button", name="解析并预览", exact=True).click()
                    expect(page.get_by_role("dialog").filter(has_text="网页 AI 回复预览").last).to_be_visible()
                    expect(page.get_by_text("网页回复", exact=True)).to_be_visible()
                    page.get_by_role("button", name="采纳到编辑器", exact=True).click()
                    expect(page.get_by_text("网页 AI 回复已保存为草稿，下一次调试使用此内容。", exact=True)).to_be_visible()
                    self.assertEqual(len(provider.requests), 1)
                    repair_note = page.get_by_label("AI 补充说明（可选）", exact=True)
                    if not repair_note.is_visible():
                        page.get_by_role("button", name="调试", exact=True).click()
                    repair_note.fill("网页保留页面")
                    page.get_by_role("button", name="AI 修复", exact=True).click()
                    page.get_by_role("button", name="Chat 网页修复", exact=True).click()
                    expect(page.get_by_label("复制到网页 AI 的内容", exact=True)).to_be_visible()
                    self.assertIn('网页保留页面', page.get_by_label("复制到网页 AI 的内容", exact=True).input_value())
                    page.get_by_role("button", name="关闭", exact=True).click()
                    supplement = page.get_by_label("AI 补充说明（可选）", exact=True)
                    supplement.click()
                    supplement.press("ControlOrMeta+A")
                    supplement.press_sequentially("继续当前页面，不重新打开")
                    supplement.press("Tab")
                    expect(supplement).to_have_value("继续当前页面，不重新打开")
                    page.get_by_role("button", name="AI 修复", exact=True).click()
                    page.get_by_role("button", name="API 修复", exact=True).click()
                    expect(page.get_by_role("button", name="采纳到编辑器", exact=True)).to_be_visible(timeout=15000)
                    self.assertIn("继续当前页面", json.dumps(provider.requests[-1], ensure_ascii=False))
                    page.get_by_role("button", name="采纳到编辑器", exact=True).click()
                    expect(page.get_by_text("AI 建议已保存为草稿，下一次调试使用此内容。", exact=True)).to_be_visible()
                    with closing(sqlite3.connect(Path(temporary) / "taskweave.db")) as db:
                        saved_content = db.execute("SELECT step_content,validation_state FROM steps WHERE name=?", ("AI 编写等待步骤",)).fetchone()
                        self.assertIn('"ai": True', saved_content[0])
                        self.assertEqual(saved_content[1], 'DRAFT')
                    page.get_by_role("button", name="插件", exact=True).click()
                    page.get_by_text("未启用 · ocr", exact=True).click()
                    expect(page.get_by_text("ocr · 未加载", exact=True)).to_be_visible()
                    page.get_by_role("button", name="环境", exact=True).click()
                    page.get_by_role("button", name="新建环境", exact=True).click()
                    page.get_by_label("环境名称", exact=True).fill("本地 UI 环境")
                    page.get_by_role("button", name="添加变量", exact=True).click()
                    page.get_by_label("Key", exact=True).fill("base_url")
                    page.get_by_label("Value", exact=True).fill("http://127.0.0.1")
                    page.get_by_role(
                        "button", name="保存环境", exact=True
                    ).click()
                    expect(page.get_by_text("本地 UI 环境", exact=True)).to_be_visible()
                    page.get_by_role("button", name="设置", exact=True).click()
                    expect(
                        page.get_by_label("完整 Chat Completions 接口地址", exact=True)
                    ).to_be_visible()
                    page.get_by_label(
                        "API Key（本地保存，留空保留当前密钥）", exact=True
                    ).fill("fixture-session-key")
                    page.get_by_role("button", name="保存连接", exact=True).click()
                    expect(
                        page.get_by_text("AI 连接配置已保存", exact=True)
                    ).to_be_visible()
                    self.assertIn(
                        "fixture-session-key",
                        (Path(temporary) / "model.json").read_text(),
                    )
                    with page.expect_popup() as popup:
                        page.get_by_role("button", name="服务日志", exact=True).click()
                    logs_page = popup.value
                    expect(logs_page.get_by_text("服务实时日志", exact=True)).to_be_visible()
                    expect(logs_page.get_by_text("AI 响应解析成功", exact=False).first).to_be_visible()
                    page.get_by_role("button", name="测试连接（实际调用一次模型）", exact=True).click()
                    expect(logs_page.get_by_text("AI 响应解析成功", exact=False)).to_have_count(3, timeout=15000)
                    logs_page.close()
                    self.assertFalse(errors, errors)
                    self.assertFalse(external, external)
                    browser.close()
                self.assertNotIn(
                    "Traceback", log_path.read_text(), log_path.read_text()
                )
            finally:
                if process.poll() is None:
                    process.send_signal(
                        signal.SIGINT if os.name != "nt" else signal.SIGTERM
                    )
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                log.close()
                provider.shutdown()
                provider.server_close()


if __name__ == "__main__":
    unittest.main()
