"""Optional HTTP chat-completion adapter; configuration is local environment only."""

import asyncio
import json
import os
import ssl
import logging
import certifi
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlparse
from taskweave.core.ports import ModelReply, ToolCall
from taskweave.core.validation import TaskError, validate
from taskweave.infrastructure.privacy import redact
from taskweave.application.prompts import FORMAT_CORRECTION
from taskweave.application.ai_requests import ensure_limit

logger = logging.getLogger(__name__)


def model_ssl_context():
    """Supply public CA roots even when the managed Python has no CA file."""
    context = ssl.create_default_context(cafile=certifi.where())
    # Preserve explicit corporate/custom CA configuration without disabling TLS.
    cafile = os.getenv("SSL_CERT_FILE")
    capath = os.getenv("SSL_CERT_DIR")
    if cafile or capath:
        context.load_verify_locations(cafile=cafile, capath=capath)
    return context


class HttpModel:
    def __init__(self, url, model, api_key=None):
        parsed = urlparse(url)
        if parsed.scheme != "https" and not (
            parsed.scheme == "http"
            and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        ):
            raise TaskError(
                "MODEL_URL_INVALID", "Use HTTPS, or HTTP for a loopback model"
            )
        if parsed.username or parsed.password:
            raise TaskError("MODEL_URL_INVALID")
        self.url, self.model, self.api_key = url, model, api_key

    def capabilities(self):
        return {"tools": True, "images": False, "json_object": True, "json_schema": False}

    async def complete(self, messages, tool_specs, response_contract, *, request_limit_bytes=None, _repair=False):
        original_messages = messages
        invalid_response = {"content": None}
        # Provider function names may disallow dots: map stable IDs to wire aliases.
        aliases = {f"tool_{i}": s.id for i, s in enumerate(tool_specs)}
        reverse = {v: k for k, v in aliases.items()}
        messages = json.loads(json.dumps(messages))
        for m in messages:
            for call in m.get("tool_calls", []):
                call["function"]["name"] = reverse[call["function"]["name"]]
        payload = {
            "model": self.model,
            "messages": messages,
            "response_format": {"type": "json_object"},
        }
        if urlparse(self.url).hostname == "api.deepseek.com":
            payload["thinking"] = {"type": "disabled"}
            payload["max_tokens"] = 8192
        if tool_specs:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": reverse[s.id],
                        "description": s.description,
                        "parameters": s.input_schema,
                    },
                }
                for s in tool_specs
            ]
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if request_limit_bytes is not None:
            ensure_limit(len(body), request_limit_bytes)

        def request():
            logger.info("AI 请求开始：model=%s，工具数=%s", self.model, len(tool_specs))
            logger.info("AI 对话请求：%s", json.dumps(redact(messages), ensure_ascii=False))
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = "Bearer " + self.api_key
            try:
                with urlopen(
                    Request(
                        self.url, data=body, headers=headers
                    ),
                    timeout=45,
                    context=model_ssl_context(),
                ) as response:
                    raw = response.read(2 * 1024 * 1024 + 1)
                if len(raw) > 2 * 1024 * 1024:
                    raise TaskError("MODEL_RESPONSE_TOO_LARGE", "模型回复超过 2 MB")
                try:
                    envelope = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise TaskError("MODEL_ENVELOPE_INVALID", f"接口响应不是合法 JSON（行 {exc.lineno}，列 {exc.colno}，响应字节数 {len(raw)}）") from exc
                choice = envelope["choices"][0]
                if choice.get("finish_reason") == "length":
                    raise TaskError("MODEL_OUTPUT_TRUNCATED", "模型输出被截断，请缩短目标或增加输出额度")
                message = choice["message"]
                invalid_response["content"] = message.get("content")
                logger.info("AI 对话回复：%s", json.dumps(redact({"content": message.get("content"), "tool_calls": message.get("tool_calls")}), ensure_ascii=False))
                calls = tuple(
                    ToolCall(
                        c["id"],
                        aliases[c["function"]["name"]],
                        json.loads(c["function"]["arguments"]),
                    )
                    for c in (message.get("tool_calls") or [])
                )
                content = parse_content(message.get("content")) if not calls else {}
                if not calls:
                    try:
                        validate(content, response_contract)
                    except TaskError as exc:
                        raise TaskError(
                            "MODEL_RESPONSE_CONTRACT_INVALID",
                            "模型回复不符合当前响应格式：" + str(exc),
                        ) from exc
                logger.info("AI 响应解析成功：工具调用数=%s", len(calls))
                return ModelReply(
                    content.get("step_content"), content.get("explanation", ""), calls, content
                )
            except TaskError as exc:
                logger.warning("AI 响应错误：%s", exc)
                raise
            except HTTPError as exc:
                logger.warning("AI HTTP 请求失败：status=%s", exc.code)
                reasons = {
                    400: "请求参数不被接受，请检查模型名称及 JSON 输出支持",
                    401: "API Key 无效或未提供",
                    402: "账户余额不足",
                    403: "账号或模型访问权限不足",
                    404: "接口地址或模型不存在",
                    429: "请求过于频繁或配额不足",
                }
                reason = reasons.get(exc.code, "模型服务异常，请稍后重试")
                raise TaskError("MODEL_REQUEST_FAILED", f"AI 连接失败（HTTP {exc.code}）：{reason}") from exc
            except (TimeoutError, URLError) as exc:
                logger.warning("AI 网络请求失败：%s", type(exc).__name__)
                cause = exc.reason if isinstance(exc, URLError) else exc
                if isinstance(cause, ssl.SSLError):
                    reason = "TLS 证书验证失败，请检查本机证书或代理配置"
                elif isinstance(cause, TimeoutError):
                    reason = "请求超时，请检查网络或稍后重试"
                else:
                    reason = "无法连接服务，请检查网络、代理和接口地址"
                raise TaskError("MODEL_REQUEST_FAILED", reason) from exc
            except Exception as exc:
                logger.warning("AI 响应解析失败：%s", type(exc).__name__)
                # Provider response and request URLs may contain secrets.
                raise TaskError(
                    "MODEL_REQUEST_FAILED",
                    f"模型响应解析失败（{type(exc).__name__}），请查看服务日志",
                ) from exc

        try:
            return await asyncio.to_thread(request)
        except TaskError as exc:
            if exc.code not in {"MODEL_JSON_INVALID", "MODEL_CONTENT_EMPTY", "MODEL_RESPONSE_CONTRACT_INVALID"} or _repair:
                raise
            logger.warning("模型内容未满足 JSON 契约，自动修正重试一次")
            contract = json.dumps(response_contract, ensure_ascii=False)
            correction = FORMAT_CORRECTION.format(
                response_contract=contract,
                validation_error=str(exc),
            )
            prior = invalid_response["content"]
            repair_messages = list(original_messages)
            if isinstance(prior, str):
                repair_messages.append({"role": "assistant", "content": prior})
            repair_messages.append({"role": "user", "content": correction})
            return await self.complete(
                repair_messages, tool_specs, response_contract,
                request_limit_bytes=request_limit_bytes, _repair=True,
            )


def parse_content(value):
    if isinstance(value, list):
        value = "".join(part.get("text", "") for part in value if isinstance(part, dict))
    if not isinstance(value, str) or not value.strip():
        raise TaskError("MODEL_CONTENT_EMPTY", "模型返回空内容，请重新生成")
    value = value.strip()
    if value.startswith("```") and value.endswith("```"):
        value = value.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        result = json.loads(value)
    except json.JSONDecodeError as exc:
        raise TaskError("MODEL_JSON_INVALID", f"模型内容 JSON 无效（行 {exc.lineno}，列 {exc.colno}，字符数 {len(value)}）：{exc.msg}") from exc
    if not isinstance(result, dict):
        raise TaskError("MODEL_CONTENT_INVALID", "模型 JSON 必须是包含 step_content 的对象")
    return result


def configured_model():
    url, model = os.getenv("TASKWEAVE_MODEL_URL"), os.getenv("TASKWEAVE_MODEL_NAME")
    return (
        HttpModel(url, model, os.getenv("TASKWEAVE_MODEL_API_KEY"))
        if url and model
        else None
    )
