import asyncio
from io import BytesIO
import json
import tempfile
import unittest
from unittest.mock import patch

from taskweave.application.ai_requests import AISettings
from taskweave.core.validation import TaskError
from taskweave.infrastructure.model import HttpModel


class AIRequestLimitTests(unittest.TestCase):
    def test_settings_default_validation_and_restart(self):
        with tempfile.TemporaryDirectory() as home:
            settings = AISettings(home)
            self.assertEqual(settings.get()["ai_request_limit_kib"], 2048)
            settings.update(1024)
            self.assertEqual(AISettings(home).get()["request_limit_bytes"], 1024 * 1024)
            settings.update(512)
            self.assertEqual(AISettings(home).get()["ai_request_limit_kib"], 512)
            for value in (0, -1, 4097, 1.5, True):
                with self.assertRaises(TaskError): settings.update(value)

    def test_final_utf8_body_boundary_is_exact(self):
        model = HttpModel("https://example.com/v1/chat/completions", "m")
        contract = {"type": "object", "properties": {"step_content": {"type": "string"}}, "required": ["step_content"]}
        messages = [{"role": "user", "content": "中文\\n"}]
        payload = {"model": "m", "messages": messages, "response_format": {"type": "json_object"}}
        size = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        response = BytesIO(json.dumps({"choices": [{"message": {"content": json.dumps({"step_content": "ok"})}, "finish_reason": "stop"}]}).encode())
        with patch("taskweave.infrastructure.model.urlopen", return_value=response) as send:
            asyncio.run(model.complete(messages, [], contract, request_limit_bytes=size))
            self.assertEqual(len(send.call_args.args[0].data), size)
        with patch("taskweave.infrastructure.model.urlopen") as send:
            with self.assertRaises(TaskError) as error:
                asyncio.run(model.complete(messages, [], contract, request_limit_bytes=size - 1))
            self.assertEqual(error.exception.code, "CONTEXT_TOO_LARGE")
            send.assert_not_called()


class PreviewTransportTests(unittest.TestCase):
    def test_opt_in_preserves_image_bytes_and_web_exports_real_attachment(self):
        import os
        from taskweave.core.context_collection import capture_ai_payload
        from taskweave.infrastructure.privacy import redact_ai_payload
        from taskweave.application.ai_requests import web_chat_export
        capture = {"label": "登录截图", "operation_notes": "确认验证码", "items": [],
                   "views": [{"renderer": "shot", "title": "页面", "data": {"image_base64": "aW1hZ2U=", "mime_type": "image/png"}}]}
        self.assertEqual(capture_ai_payload(capture, 0, {})["preview_items"], [])
        capture["send_preview"] = True
        payload = capture_ai_payload(capture, 0, {})
        with patch.dict(os.environ, {"TEST_SECRET": "aW1h"}):
            safe = redact_ai_payload(payload)
        self.assertEqual(safe["preview_items"][0]["content"], "aW1hZ2U=")
        prompt, images = web_chat_export([{"role": "user", "content": json.dumps(safe)}])
        self.assertNotIn("aW1hZ2U=", prompt)
        self.assertIn("确认验证码", prompt)
        self.assertEqual(images[0]["data"], "aW1hZ2U=")

    def test_http_sends_image_message_and_keeps_structured_table(self):
        from taskweave.core.context_collection import capture_ai_payload
        capture = {"label": "采集", "operation_notes": "核对", "send_preview": True, "items": [], "views": [
            {"renderer": "shot", "data": {"image_base64": "aW1hZ2U=", "mime_type": "image/png"}},
            {"renderer": "table", "data": {"rows": [["中文", 12]]}}]}
        messages = [{"role": "user", "content": json.dumps(capture_ai_payload(capture, 0, {}))}]
        response = BytesIO(json.dumps({"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]}).encode())
        with patch("taskweave.infrastructure.model.urlopen", return_value=response) as send:
            asyncio.run(HttpModel("https://example.com/api", "vision").complete(messages, [], {"type": "object"}))
        wire = json.loads(send.call_args.args[0].data)["messages"][0]["content"]
        self.assertEqual(wire[-1]["image_url"]["url"], "data:image/png;base64,aW1hZ2U=")
        self.assertIn("中文", wire[0]["text"])
        self.assertNotIn("aW1hZ2U=", wire[0]["text"])
