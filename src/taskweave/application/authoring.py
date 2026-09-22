"""AI is an optional authoring service; proposals never execute or overwrite drafts."""

import asyncio
from dataclasses import asdict, replace
import json
import logging
from taskweave.core.validation import TaskError, content_tree, normalize_step
from taskweave.core.ports import Scope
from taskweave.infrastructure.privacy import redact
from taskweave.infrastructure.storage import uid, Results
from taskweave.infrastructure.worker import PluginContext, Resources
from taskweave.application.prompts import (
    STEP_CODE_RULES, STEP_DESCRIPTION_RULES, WEB_CHAT_JSON_RULES,
    WEB_CHAT_DESCRIPTION_RULES, REPAIR_RULES,
    CAPABILITY_CORRECTION,
)

# This is a transport guard, not the model's context window. The former 64 KiB
# limit rejected ordinary capability catalogs plus a fresh browser snapshot
# before the provider could evaluate them.
AUTHORING_REQUEST_LIMIT = 128 * 1024


def last_dialogue_rounds(history, count=2):
    if count == 0:
        return []
    starts = [index for index, message in enumerate(history) if message.get('role') == 'user']
    return history[starts[-count]:] if len(starts) > count else history


def dialogue_history(messages):
    """Remove static fields already supplied by the current request.

    Feedback and collected contexts remain byte-for-byte equivalent JSON data;
    only repeated task/step definitions are omitted from older turns.
    """
    result = json.loads(json.dumps(messages))
    repeated = {
        "goal", "ai_authoring_notes", "step_content", "input_schema", "output_schema",
        "available_variables",
    }
    for message in result:
        if message.get("role") != "user":
            continue
        try:
            payload = json.loads(message.get("content", ""))
        except (ValueError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        for key in repeated:
            payload.pop(key, None)
        message["content"] = json.dumps(payload, ensure_ascii=False)
    return result


def parameter_schema(schema):
    """Expose variable names/types to AI without local default values."""
    if isinstance(schema, list):
        return [parameter_schema(item) for item in schema]
    if isinstance(schema, dict):
        return {key: parameter_schema(value) for key, value in schema.items() if key != 'default'}
    return schema


class Authoring:
    def __init__(self, repo, registry, model=None):
        self.repo, self.registry, self.model = repo, registry, model
        self.conversations = {}

    def reset_conversation(self, step_id):
        self.conversations.pop(step_id, None)

    async def validate_step(self, step):
        self.registry.check(step)
        content_tree(step["step_content"], step["capabilities"])
        diagnostics = []
        self.registry.contributions(step["capabilities"])
        for plugin in self.registry.selected_plugins(step["capabilities"]):
            diagnostics.extend(asdict(d) for d in await plugin.lint(step))
        return diagnostics

    async def generate_goal(self, step_id, expected_hash, supplement="", contexts=None, export_only=False):
        """Generate only a concise human goal; never generate or execute code."""
        step = self.repo.step(step_id)
        if step["content_hash"] != expected_hash:
            raise TaskError("EDIT_CONFLICT")
        contributions = [asdict(item) for item in self.registry.contributions(step["capabilities"])]
        task_schema = json.loads(self.repo.task(step['task_id'])['input_schema_json'])
        request = {
            "current_goal": step["goal"],
            "user_requirement": supplement or "",
            "ai_authoring_notes": step.get("ai_authoring_notes", ""),
            "input_schema": parameter_schema(step["input_schema"]),
            "output_schema": parameter_schema(step["output_schema"]),
            "bindings": step["bindings"],
            "available_variables": [
                {"name": name, "source": source, "type": spec.get("type", "string")}
                for source, schema in (("task", task_schema), ("step", step["input_schema"]))
                for name, spec in schema.get("properties", {}).items()
            ],
            "capabilities": [
                asdict(self.registry.actions[action].spec)
                for action in step["capabilities"] if action in self.registry.actions
            ],
            "plugin_guidance": contributions,
            "plugin_contexts": contexts or [],
        }
        system = STEP_DESCRIPTION_RULES + ("\n" + WEB_CHAT_DESCRIPTION_RULES if export_only else "\n严格返回 JSON 对象：step_content 为步骤描述纯文本，explanation 为简短整理说明。")
        messages = [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(redact(request), ensure_ascii=False)}]
        if export_only:
            prompt = "\n\n".join(item["role"] + ":\n" + item["content"] for item in messages)
            return {"prompt": prompt, "expected_hash": expected_hash}
        if self.model is None:
            raise TaskError("MODEL_NOT_CONFIGURED")
        reply = await self.model.complete(messages, [], {"type": "object"})
        text = (reply.proposed_content or "").strip()
        if not text or "async def" in text:
            raise TaskError("MODEL_CONTENT_INVALID", "AI 未返回有效步骤描述")
        return {"goal": text, "explanation": reply.explanation, "expected_hash": expected_hash}

    async def generate(
        self,
        step_id,
        expected_hash,
        goal=None,
        feedback=None,
        contexts=None,
        environment_id=None,
        supplement=None,
        use_history=False,
        history_rounds=None,
        deduplicate_history=True,
        export_only=False,
    ):
        if self.model is None and not export_only:
            raise TaskError(
                "MODEL_NOT_CONFIGURED",
                "Manual authoring and execution remain available",
            )
        step = self.repo.step(step_id)
        if expected_hash != step["content_hash"]:
            raise TaskError("EDIT_CONFLICT")
        self.registry.check(step)
        selected = step["capabilities"]
        tools = {}
        contributions = []
        for c in self.registry.contributions(selected):
            contribution = asdict(c)
            channel = "web_chat" if export_only else "api"
            overrides = contribution.pop("channel_overrides", {}).get(channel, {})
            if not isinstance(overrides, dict) or set(overrides) - {"instructions", "examples"}:
                raise TaskError("AUTHORING_CHANNEL_INVALID", "插件对话适配仅支持 instructions 和 examples")
            contribution.update(overrides)
            if export_only:
                contribution["tool_ids"] = []  # Web chat cannot invoke local tools.
            contributions.append(contribution)
            for tid in c.tool_ids:
                if tid in selected and tid in self.registry.tools:
                    tools[tid] = self.registry.tools[tid]
        contexts = contexts or []
        if any(
            c.get("kind") == "image" for c in contexts
        ) and not export_only and not self.model.capabilities().get("images", False):
            raise TaskError("MODEL_IMAGE_UNSUPPORTED")
        task_schema = json.loads(self.repo.task(step['task_id'])['input_schema_json'])
        environment, secret_refs = self.repo.environment(environment_id)
        available_variables = [{"name": key, "source": "environment", "type": type(value).__name__} for key, value in environment.items()]
        available_variables.extend({"name": key, "source": "task", "type": spec.get('type', 'string')} for key, spec in task_schema.get('properties', {}).items())
        messages = [
            {"role": "system", "content": STEP_CODE_RULES + ("\n" + REPAIR_RULES if feedback else "")},
            {
                "role": "system",
                "content": json.dumps(
                    {
                        "plugins": contributions,
                        "result_views": {key: value for key, value in self.registry.views.items() if key.startswith("core.") or any(key.startswith(plugin.manifest()["id"] + ".") for plugin in self.registry.selected_plugins(selected))},
                        "capabilities": [
                            asdict(self.registry.actions[c].spec)
                            for c in selected
                            if c in self.registry.actions
                        ],
                    },
                    ensure_ascii=False,
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    redact(
                        {
                            "goal": goal or step["goal"],
                            "ai_authoring_notes": step.get("ai_authoring_notes", ""),
                            "step_content": step["step_content"],
                            "input_schema": step["input_schema"],
                            "output_schema": step["output_schema"],
                            "feedback": feedback or {},
                            "contexts": contexts,
                            "user_supplement": supplement or "",
                        }
                    ),
                    ensure_ascii=False,
                ),
            },
        ]
        payload = json.loads(messages[-1]['content'])
        payload['input_schema'] = parameter_schema(step['input_schema'])
        payload['output_schema'] = parameter_schema(step['output_schema'])
        payload['available_variables'] = available_variables
        messages[-1]['content'] = json.dumps(payload, ensure_ascii=False)
        if history_rounds is None:
            history_rounds = -1 if use_history else 0
        if not isinstance(history_rounds, int) or history_rounds < -1 or history_rounds > 10:
            raise TaskError("FORM_INVALID", "历史对话轮次只能是 -1、0 或 1–10")
        use_history = use_history or history_rounds != 0
        stored_history = json.loads(json.dumps(self.conversations.get(step_id, []))) if use_history else []
        history = stored_history if history_rounds == -1 else last_dialogue_rounds(stored_history, history_rounds)
        if use_history:
            messages[2:2] = dialogue_history(history) if deduplicate_history else history
        history_trimmed = len(history) < len(stored_history)
        if len(json.dumps(messages, ensure_ascii=False).encode()) > AUTHORING_REQUEST_LIMIT:
            raise TaskError("CONTEXT_TOO_LARGE", "本次完整请求超过 128 KiB，请选择更少的历史轮次（0 表示不带历史）或删除不需要的已采集上下文")
        if export_only:
            instruction = "请按以下项目规范生成或修订当前步骤。你无法调用本机插件工具，请使用提供的能力目录、页面上下文和日志，不要假设工具已执行。\n" + WEB_CHAT_JSON_RULES
            text = instruction + "\n\n" + "\n\n".join(message['role'] + ":\n" + message.get('content', '') for message in messages)
            logging.getLogger(__name__).info("网页 AI 对话内容：%s", redact(text))
            return {"prompt": text, "messages": messages, "expected_hash": expected_hash, "history_trimmed": history_trimmed}
        import threading

        scope = Scope(step["task_id"], uid(), step_id, uid())
        resources = Resources(self.registry)
        environment, secret_refs = self.repo.environment(environment_id)
        pc = PluginContext(
            scope,
            Results(self.repo.home, scope, self.registry),
            resources,
            environment,
            secret_refs,
            threading.Event(),
            lambda *args: None,
        )
        pc.task_parameters = {key: spec["default"] for key, spec in json.loads(self.repo.task(step["task_id"])["input_schema_json"]).get("properties", {}).items() if "default" in spec}
        resources.context = pc
        contract = {
            "type": "object",
            "properties": {
                "step_content": {"type": "string"},
                "explanation": {"type": "string"},
            },
            "required": ["step_content"],
        }

        async def session():
            corrected = False
            for _ in range(8):
                specs = [replace(t.spec, id=k) for k, t in tools.items()]
                reply = await self.model.complete(messages, specs, contract)
                if reply.tool_calls:
                    messages.append(
                        {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": c.call_id,
                                    "type": "function",
                                    "function": {
                                        "name": c.tool_id,
                                        "arguments": json.dumps(c.arguments),
                                    },
                                }
                                for c in reply.tool_calls
                            ],
                        }
                    )
                    for call in reply.tool_calls:
                        tool = tools.get(call.tool_id)
                        if tool is None:
                            raise TaskError("CAPABILITY_DENIED")
                        if tool.spec.effect != "READ":
                            raise TaskError("AUTHORING_WRITE_REQUIRES_TRIAL")
                        from taskweave.core.validation import validate

                        validate(call.arguments, tool.spec.input_schema)

                        async def invoke():
                            if any(
                                d.severity == "error"
                                for d in await tool.preflight(pc, call.arguments)
                            ):
                                raise TaskError("PREFLIGHT_FAILED")
                            value = await tool.execute(pc, call.arguments)
                            validate(value, tool.spec.output_schema)
                            if any(
                                d.severity == "error"
                                for d in await tool.verify(pc, call.arguments, value)
                            ):
                                raise TaskError("VERIFY_FAILED")
                            return value

                        value = await asyncio.wait_for(invoke(), 30)
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call.call_id,
                                "content": json.dumps(redact(value)),
                            }
                        )
                    if len(json.dumps(messages, ensure_ascii=False).encode()) > AUTHORING_REQUEST_LIMIT:
                        raise TaskError("CONTEXT_TOO_LARGE")
                    continue
                proposal = normalize_step(
                    {**step, "step_content": reply.proposed_content or ""}
                )
                messages.append({"role": "assistant", "content": json.dumps({"step_content": reply.proposed_content, "explanation": reply.explanation}, ensure_ascii=False)})
                try:
                    diagnostics = await self.validate_step(proposal)
                except TaskError as exc:
                    if exc.code != "CAPABILITY_DENIED" or corrected:
                        if exc.code == "CAPABILITY_DENIED":
                            raise TaskError(exc.code, f"AI 使用了未授权动作：{exc}。允许动作：{', '.join(selected)}") from exc
                        raise
                    corrected = True
                    messages.append({"role": "user", "content": CAPABILITY_CORRECTION + "\nError: " + str(exc) + "\nAllowed action IDs: " + json.dumps(selected)})
                    continue
                return {
                    "proposed_content": proposal["step_content"],
                    "explanation": redact(reply.explanation),
                    "diagnostics": diagnostics,
                    "expected_hash": expected_hash,
                    "stale": self.repo.step(step_id)["content_hash"] != expected_hash,
                    "history_trimmed": history_trimmed,
                    "authoring_session_id": uid(),
                }
            raise TaskError("MODEL_TOOL_LIMIT")

        try:
            return await asyncio.wait_for(session(), 180)
        finally:
            if use_history:
                self.conversations[step_id] = stored_history + [message for message in messages[2+len(history):] if message['role'] != 'system']
            await resources.release_all()

    async def collect_context(
        self, step_id, provider_id, request=None, environment_id=None
    ):
        step = self.repo.step(step_id)
        selected = self.registry.selected_plugins(step["capabilities"])
        plugin = next(
            (
                p
                for p in selected
                if provider_id in p.authoring(step["capabilities"]).context_provider_ids
            ),
            None,
        )
        if plugin is None:
            raise TaskError("CONTEXT_PROVIDER_UNAVAILABLE")
        import threading

        scope = Scope(step["task_id"], uid(), step_id, uid())
        resources = Resources(self.registry)
        environment, secret_refs = self.repo.environment(environment_id)
        pc = PluginContext(
            scope,
            Results(self.repo.home, scope, self.registry),
            resources,
            environment,
            secret_refs,
            threading.Event(),
            lambda *args: None,
        )
        pc.task_parameters = {key: spec["default"] for key, spec in json.loads(self.repo.task(step["task_id"])["input_schema_json"]).get("properties", {}).items() if "default" in spec}
        resources.context = pc
        try:
            context = await asyncio.wait_for(
                plugin.collect_context(provider_id, pc, request or {}), 30
            )
            # Return for user inspection; generation is a separate explicit operation.
            return redact([asdict(c) for c in context])
        finally:
            await resources.release_all()

    async def diagnose(self, attempt_id):
        from taskweave.core.ports import ErrorInfo

        evidence = self.repo.feedback(attempt_id)
        step = self.repo.step(evidence["step_id"])
        error = evidence["error"]
        info = ErrorInfo(
            error["error_code"] or "",
            error["error_summary"] or "",
            error["error_phase"] or "",
            evidence["effect_state"],
        )
        from taskweave.core.ports import ResultRef

        rows = self.repo.query(
            "SELECT * FROM result_refs WHERE attempt_id=?", (attempt_id,)
        )
        refs = [
            ResultRef(
                **{
                    k: r[k]
                    for k in (
                        "result_id",
                        "handler_id",
                        "kind",
                        "locator",
                        "media_type",
                        "checksum",
                        "size_bytes",
                    )
                }
            )
            for r in rows
        ]
        diagnostics = []
        for plugin in self.registry.selected_plugins(step["capabilities"]):
            diagnostics.extend(
                asdict(d)
                for d in await asyncio.wait_for(plugin.diagnose(info, refs), 30)
            )
        return redact(diagnostics)
