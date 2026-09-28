"""AI is an optional authoring service; proposals never execute or overwrite drafts."""

import asyncio
from dataclasses import asdict, replace
import json
import logging
from taskweave.core.validation import (
    SAFE_BUILTINS, TaskError, content_tree, merge_input_layers, normalize_step,
)
from taskweave.core.ports import Scope
from taskweave.infrastructure.privacy import redact, redact_ai_payload
from taskweave.infrastructure.storage import uid, Results
from taskweave.infrastructure.worker import PluginContext, Resources
from taskweave.application.prompts import (
    DOMAIN_RULES, EXECUTABLE_STEP_RULES, STEP_CONTENT_RULES,
    STEP_DESCRIPTION_RULES, STEP_RESPONSE_RULES, WEB_CHAT_RULES,
    WEB_CHAT_CODE_RULES, REPAIR_RULES, CAPABILITY_CORRECTION,
)
from taskweave.application.ai_requests import web_chat_export, ensure_limit, utf8_size
from taskweave.core.repositories import EnvironmentRepository, ResultRepository, RunRepository, StepRepository, TaskRepository

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
        "step_description", "step_notes", "step_content", "input_schema", "output_schema",
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


def _input_dependencies(bindings):
    return {
        name: value
        for name, value in (bindings or {}).items()
        if isinstance(value, dict)
        and isinstance(value.get("ref"), dict)
        and value["ref"].get("source") == "step"
    }


def _context_payload(contexts):
    """Keep both context body and user-authored metadata intact."""
    if isinstance(contexts, dict) and isinstance(contexts.get("items"), list):
        contexts = contexts["items"]
    return [json.loads(json.dumps(item)) for item in (contexts or [])]


def _context_items(contexts):
    """Return plugin items from either legacy flat evidence or grouped captures."""
    result=[]
    for value in contexts:
        if isinstance(value,dict) and isinstance(value.get('captures'),list):
            for capture in value['captures']:
                result.extend(capture.get('items',[]))
                result.extend(capture.get("preview_items", []))
        else:
            result.append(value)
    return result


class Authoring:
    def __init__(self, tasks: TaskRepository, steps: StepRepository, environments: EnvironmentRepository, runs: RunRepository, results: ResultRepository, home, registry, model=None, request_limit=None, redact_for_ai=None):
        self.tasks, self.steps, self.environments = tasks, steps, environments
        self.runs, self.results, self.home = runs, results, home
        self.registry, self.model = registry, model
        self.request_limit = request_limit or (lambda: 2048 * 1024)
        self.redact_for_ai = redact_for_ai or (lambda: True)
        self.conversations = {}

    def _outbound(self, value):
        return redact_ai_payload(value) if self.redact_for_ai() else value

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

    def _variable_catalog(self, step, environment_id):
        task_schema = json.loads(self.tasks.task(step['task_id'])['input_schema_json'])
        public, secrets = self.environments.environment(environment_id)
        descriptions = {}
        if environment_id:
            row = next((item for item in self.environments.list_environments() if item['environment_id'] == environment_id), None)
            descriptions = json.loads(row.get('descriptions_json') or '{}') if row else {}
        environment_variables = {
            name: {'schema': {'type': type(value).__name__, 'description': descriptions.get(name, '')}, 'required': False}
            for name, value in public.items()
        }
        environment_variables.update({
            name: {'schema': {'type': 'string', 'description': descriptions.get(name, '')}, 'required': False, 'secret': True}
            for name in secrets
        })
        declared = []
        for schema in (task_schema, step['input_schema']):
            required = set(schema.get('required', []))
            declared.append({name: {
                'schema': parameter_schema(spec), 'required': name in required,
            } for name, spec in schema.get('properties', {}).items()})
        merged = merge_input_layers(environment_variables, *declared)
        return [{'name': name, **details} for name, details in merged.items()]

    def _catalog(self, step, tools=None):
        selected = step["capabilities"]
        plugins = self.registry.selected_plugins(selected)
        plugin_ids = {plugin.manifest()["id"] for plugin in plugins}
        return {
            "runtime_api": [
                "await ctx.call(action_id, inputs)",
                "ctx.result(data=None, outputs=(), views=())",
                "ctx.output(handler_id, name, payload)",
                "ctx.log(message)",
                "ctx.cancelled()",
            ],
            "runtime_builtins": sorted(SAFE_BUILTINS),
            "actions": [
                asdict(self.registry.actions[c].spec)
                for c in selected if c in self.registry.actions
            ],
            "authoring_tools": [
                asdict((tools or {})[key].spec) for key in sorted(tools or {})
            ],
            "result_handlers": [
                key for key in selected if key in self.registry.handlers
            ],
            "result_views": {
                key: value for key, value in self.registry.views.items()
                if key.startswith("core.") or key.split(".", 1)[0] in plugin_ids
            },
            "plugin_versions": {
                key: self.registry.versions[key] for key in sorted(plugin_ids)
            },
        }

    async def generate_goal(self, step_id, expected_hash, supplement="", contexts=None, environment_id=None, export_only=False):
        """Generate the description and its durable authoring notes; never code."""
        step = self.steps.step(step_id)
        if step["content_hash"] != expected_hash:
            raise TaskError("EDIT_CONFLICT")
        contributions = [
            {'context_provider_ids': list(item.context_provider_ids)}
            for item in self.registry.contributions(step["capabilities"])
        ]
        request = {
            "step_description": step["step_description"],
            "user_requirement": supplement or "",
            "step_notes": step.get("step_notes", ""),
            "output_schema": parameter_schema(step["output_schema"]),
            "input_dependencies": _input_dependencies(step["bindings"]),
            "available_variables": self._variable_catalog(step, environment_id),
            "capabilities": [
                asdict(self.registry.actions[action].spec)
                for action in step["capabilities"] if action in self.registry.actions
            ],
            "plugin_guidance": contributions,
            "plugin_contexts": _context_payload(contexts),
        }
        system = DOMAIN_RULES + "\n" + STEP_DESCRIPTION_RULES
        if export_only:
            system += "\n" + WEB_CHAT_RULES
        messages = [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(self._outbound(request), ensure_ascii=False)}]
        if export_only:
            prompt, attachments = web_chat_export(messages)
            ensure_limit(utf8_size(messages), self.request_limit())
            return {"prompt": prompt, "attachments": attachments, "expected_hash": expected_hash}
        if self.model is None:
            raise TaskError("MODEL_NOT_CONFIGURED")
        contract = {'type':'object','properties':{'step_description':{'type':'string'},'step_notes':{'type':'string'}},'required':['step_description','step_notes'],'additionalProperties':False}
        reply = await self._complete(messages, [], contract)
        text = (reply.structured_content.get('step_description') or '').strip()
        notes = (reply.structured_content.get('step_notes') or '').strip()
        if not text or "async def" in text or "async def" in notes:
            raise TaskError("MODEL_CONTENT_INVALID", "AI 未返回有效步骤描述")
        return {"step_description": text, "step_notes": notes, "expected_hash": expected_hash}

    async def _complete(self, messages, tools, contract):
        """Pass the frozen workspace budget while accepting legacy model fixtures."""
        try:
            return await self.model.complete(messages, tools, contract, request_limit_bytes=self.request_limit())
        except TypeError as exc:
            if "request_limit_bytes" not in str(exc):
                raise
            return await self.model.complete(messages, tools, contract)

    async def generate(
        self,
        step_id,
        expected_hash,
        step_description=None,
        feedback=None,
        contexts=None,
        environment_id=None,
        repair_notes=None,
        purpose=None,
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
        step = self.steps.step(step_id)
        if expected_hash != step["content_hash"]:
            raise TaskError("EDIT_CONFLICT")
        self.registry.check(step)
        if purpose is None:
            purpose = "repair" if feedback is not None or repair_notes is not None or use_history or history_rounds not in (None, 0) else "content"
        if purpose not in {"content", "repair"}:
            raise TaskError("FORM_INVALID", "步骤生成 purpose 只能是 content 或 repair")
        selected = step["capabilities"]
        tools = {}
        contributions = []
        for c in self.registry.contributions(selected):
            contribution = asdict(c)
            channel = "web_chat" if export_only else "api"
            overrides = contribution.pop("channel_overrides", {}).get(channel, {})
            if not isinstance(overrides, dict) or set(overrides) - {"instructions", "examples"}:
                raise TaskError("AUTHORING_CHANNEL_INVALID", "插件对话适配仅支持 instructions 和 examples")
            if overrides.get('instructions'):
                contribution['instructions'] = (contribution.get('instructions', '') + '\n' + overrides['instructions']).strip()
            if overrides.get('examples'):
                contribution['examples'] = list(contribution.get('examples', ())) + list(overrides['examples'])
            if export_only:
                contribution["tool_ids"] = []  # Web chat cannot invoke local tools.
            contributions.append(contribution)
            for tid in c.tool_ids:
                if tid in selected and tid in self.registry.tools:
                    tools[tid] = self.registry.tools[tid]
        contexts = _context_payload(contexts)
        if any(c.get("kind") == "image" for c in _context_items(contexts)) and not export_only and not self.model.capabilities().get("images", False):
            raise TaskError("MODEL_IMAGE_UNSUPPORTED")
        available_variables = self._variable_catalog(step, environment_id)
        system = DOMAIN_RULES + "\n" + EXECUTABLE_STEP_RULES + "\n" + (REPAIR_RULES if purpose == "repair" else STEP_CONTENT_RULES) + "\n" + STEP_RESPONSE_RULES
        if export_only:
            system += "\n" + WEB_CHAT_RULES + "\n" + WEB_CHAT_CODE_RULES
        messages = [
            {"role": "system", "content": system},
            {
                "role": "system",
                "content": json.dumps(
                    {
                        "plugins": contributions,
                        **self._catalog(step, tools),
                    },
                    ensure_ascii=False,
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    self._outbound(
                        {
                            "step_description": step_description or step["step_description"],
                            "step_notes": step.get("step_notes", ""),
                            "step_content": step["step_content"],
                            "output_schema": step["output_schema"],
                            "contexts": contexts,
                            "input_dependencies": _input_dependencies(step["bindings"]),
                        }
                    ),
                    ensure_ascii=False,
                ),
            },
        ]
        payload = json.loads(messages[-1]['content'])
        payload['output_schema'] = parameter_schema(step['output_schema'])
        payload['available_variables'] = available_variables
        if purpose == "repair":
            payload['feedback'] = feedback or {}
            payload['repair_notes'] = repair_notes or ""
        messages[-1]['content'] = json.dumps(self._outbound(payload), ensure_ascii=False)
        if history_rounds is None:
            history_rounds = -1 if use_history else 0
        if not isinstance(history_rounds, int) or history_rounds < -1 or history_rounds > 10:
            raise TaskError("FORM_INVALID", "历史对话轮次只能是 -1、0 或 1–10")
        use_history = use_history or history_rounds != 0
        stored_history = json.loads(json.dumps(self.conversations.get(step_id, []))) if use_history else []
        history = stored_history if history_rounds == -1 else last_dialogue_rounds(stored_history, history_rounds)
        if use_history:
            history = dialogue_history(history) if deduplicate_history else history
            if self.redact_for_ai():
                history = [{**message, 'content': redact_ai_payload(message.get('content', ''))} for message in history]
            messages[2:2] = history
        history_trimmed = len(history) < len(stored_history)
        if export_only:
            text, attachments = web_chat_export(messages)
            ensure_limit(utf8_size(messages), self.request_limit())
            logging.getLogger(__name__).info("网页 AI 对话内容：%s", redact(text))
            return {"prompt": text, "attachments": attachments, "messages": messages, "expected_hash": expected_hash, "history_trimmed": history_trimmed}
        import threading

        scope = Scope(step["task_id"], uid(), step_id, uid())
        resources = Resources(self.registry)
        environment, secret_refs = self.environments.environment(environment_id)
        pc = PluginContext(
            scope,
            Results(self.home, scope, self.registry),
            resources,
            environment,
            secret_refs,
            threading.Event(),
            lambda *args: None,
        )
        pc.task_parameters = {key: spec["default"] for key, spec in json.loads(self.tasks.task(step["task_id"])["input_schema_json"]).get("properties", {}).items() if "default" in spec}
        resources.context = pc
        contract = {
            "type": "object",
            "properties": {
                "step_content": {"type": "string"},
                "explanation": {"type": "string"},
            },
            "required": ["step_content", "explanation"],
            "additionalProperties": False,
        }

        async def session():
            corrected = False
            for _ in range(8):
                specs = [replace(t.spec, id=k) for k, t in tools.items()]
                reply = await self._complete(messages, specs, contract)
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
                                "content": json.dumps(self._outbound(value)),
                            }
                        )
                    continue
                if not (reply.proposed_content or "").strip():
                    explanation = (reply.explanation or "").strip()
                    if explanation.startswith("缺少必要信息："):
                        raise TaskError("AUTHORING_INFORMATION_MISSING", explanation)
                    raise TaskError("MODEL_CONTENT_INVALID", "AI 未返回完整步骤内容")
                proposal = normalize_step({**step, "step_content": reply.proposed_content})
                messages.append({"role": "assistant", "content": json.dumps({"step_content": reply.proposed_content, "explanation": reply.explanation}, ensure_ascii=False)})
                try:
                    diagnostics = await self.validate_step(proposal)
                except TaskError as exc:
                    if exc.code != "CAPABILITY_DENIED" or corrected:
                        if exc.code == "CAPABILITY_DENIED":
                            raise TaskError(exc.code, f"AI 使用了未授权动作：{exc}。允许动作：{', '.join(selected)}") from exc
                        raise
                    corrected = True
                    messages.append({"role": "user", "content": CAPABILITY_CORRECTION.format(allowed_ids=json.dumps(selected, ensure_ascii=False), validation_error=str(exc))})
                    continue
                return {
                    "proposed_content": proposal["step_content"],
                    "explanation": redact(reply.explanation),
                    "diagnostics": diagnostics,
                    "expected_hash": expected_hash,
                    "stale": self.steps.step(step_id)["content_hash"] != expected_hash,
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

    def _context_plugin(self, step_id, provider_id):
        step = self.steps.step(step_id)
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
        return step, plugin

    async def context_targets(self, step_id, provider_id, request=None):
        # Independent authoring observations own no retained resources.
        self._context_plugin(step_id, provider_id)
        return {"session_id": None, "targets": []}

    async def collect_context(
        self, step_id, provider_id, request=None, environment_id=None, expected_session_id=None,
        include_view=True,
    ):
        if expected_session_id:
            raise TaskError("CONTEXT_SESSION_CHANGED", "采集实例已结束或变化，请刷新后重新选择")
        step, plugin = self._context_plugin(step_id, provider_id)
        import threading

        scope = Scope(step["task_id"], uid(), step_id, uid())
        resources = Resources(self.registry)
        environment, secret_refs = self.environments.environment(environment_id)
        pc = PluginContext(
            scope,
            Results(self.home, scope, self.registry),
            resources,
            environment,
            secret_refs,
            threading.Event(),
            lambda *args: None,
        )
        pc.task_parameters = {key: spec["default"] for key, spec in json.loads(self.tasks.task(step["task_id"])["input_schema_json"]).get("properties", {}).items() if "default" in spec}
        resources.context = pc
        try:
            context = await asyncio.wait_for(
                plugin.collect_context(provider_id, pc, request or {}, include_view=include_view), 60
            )
            # Return for user inspection; generation is a separate explicit operation.
            from taskweave.core.context_collection import serialize_context_collection
            return serialize_context_collection(context, self.registry.views)
        finally:
            await resources.release_all()

    async def diagnose(self, attempt_id):
        from taskweave.core.ports import ErrorInfo

        evidence = self.runs.feedback(attempt_id)
        step = self.steps.step(evidence["step_id"])
        error = evidence["error"]
        info = ErrorInfo(
            error["error_code"] or "",
            error["error_summary"] or "",
            error["error_phase"] or "",
            evidence["effect_state"],
        )
        from taskweave.core.ports import ResultRef

        rows = self.results.refs_for_attempt(attempt_id)
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
