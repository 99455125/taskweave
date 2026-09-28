"""Plan authoring use cases: freeze evidence, generate, validate and import."""

from dataclasses import asdict
from copy import deepcopy
import json
from pathlib import Path
import re

from taskweave.application.ai_requests import ensure_limit, utf8_size, web_chat_export
from taskweave.core.context_collection import capture_ai_payload
from taskweave.application.prompts import DOMAIN_RULES, EXECUTABLE_STEP_RULES, PLAN_RULES, WEB_CHAT_RULES, WEB_CHAT_CODE_RULES
from taskweave.application.tasks import TaskUseCases
from taskweave.core.task_package import TASK_PACKAGE_SCHEMA
from taskweave.core.repositories import PlanContextRepository, PlanGenerationRepository, PlanRepositoryPort, StepContextRepository, StepRepository, UnitOfWork
from taskweave.core.validation import TaskError
from taskweave.infrastructure.privacy import redact, redact_ai_payload


PLAN_CANDIDATE_SCHEMA = deepcopy(TASK_PACKAGE_SCHEMA)
PLAN_CANDIDATE_SCHEMA["properties"]["plan_context_refs"] = {
    "type": "object", "additionalProperties": {
        "type": "array", "items": {"type": "string"}, "uniqueItems": True,
    },
}

PLAN_CANDIDATE_SCHEMA["required"].append("plan_context_refs")

PLAN_RESPONSE_SCHEMA = {
    "oneOf": [PLAN_CANDIDATE_SCHEMA, {
        "type": "object", "properties": {"error": {
            "type": "object", "properties": {
                "code": {"const": "PLAN_INFORMATION_MISSING"},
                "message": {"type": "string"}, "items": {"type": "array", "items": {"type": "string"}},
            }, "required": ["code", "message", "items"], "additionalProperties": False,
        }}, "required": ["error"], "additionalProperties": False,
    }]
}


_STEP_CONTENT_STRING = re.compile(
    r'("step_content"\s*:\s*")(.*?)("\s*,\s*"input_schema"\s*:)', re.DOTALL,
)


def _recover_step_content_quotes(response_text):
    """Repair only unescaped quotes in the known step_content JSON string slot."""
    matches = list(_STEP_CONTENT_STRING.finditer(response_text))
    if not matches or len(matches) != response_text.count('"step_content"'):
        return response_text

    def repair(match):
        escaped = []
        backslashes = 0
        for char in match.group(2):
            if char == '"' and backslashes % 2 == 0:
                escaped.append('\\')
            if char == '\n':
                escaped.append('\\n')
            elif char == '\r':
                escaped.append('\\r')
            elif char == '\t':
                escaped.append('\\t')
            else:
                escaped.append(char)
            backslashes = backslashes + 1 if char == '\\' else 0
        return match.group(1) + ''.join(escaped) + match.group(3)

    return _STEP_CONTENT_STRING.sub(repair, response_text)


class PlanningService:
    def __init__(
        self,
        plans: PlanRepositoryPort,
        contexts: PlanContextRepository,
        generations: PlanGenerationRepository,
        sessions,
        settings,
        registry,
        authoring,
        privacy_settings,
        tasks: TaskUseCases,
        steps: StepRepository,
        step_contexts: StepContextRepository,
        uow: UnitOfWork,
        plan_files_root: Path,
    ):
        self.plans, self.contexts, self.generations = plans, contexts, generations
        self.sessions, self.settings, self.registry = sessions, settings, registry
        self.authoring, self.privacy_settings, self.tasks = authoring, privacy_settings, tasks
        self.steps, self.step_contexts = steps, step_contexts
        self.uow = uow
        self.plan_files_root = Path(plan_files_root)

    def create(self, name="新计划"): return self.plans.create(name)
    def copy(self, plan_id, expected_revision): return self.plans.copy(plan_id, expected_revision)
    def list(self): return self.plans.list()
    def generation_list(self, plan_id):
        self.plans.get(plan_id)
        return self.generations.generations(plan_id)
    def generation_get(self, generation_id):
        generation = self.generations.generation(generation_id)
        generation["context_labels"] = {key: item["name"] for key, item in self._frozen_contexts(generation).items()}
        return generation
    def generation_imports(self, generation_id):
        self.generations.generation(generation_id)
        return self.generations.imports(generation_id)
    def get(self, plan_id):
        return {**self.plans.get(plan_id), "contexts": self.contexts.contexts(plan_id)}
    def update(self, plan_id, expected_revision, name, plan_description="", plan_notes="", environment_id=None, plugin_ids=None):
        old = self.plans.get(plan_id)
        signature = (environment_id, plugin_ids or [])
        if (old.get("environment_id"), old.get("plugin_ids")) != signature:
            return self.sessions.change_configuration(old["plan_id"], lambda: self.plans.update(plan_id, expected_revision, name, plan_description, plan_notes, environment_id, plugin_ids))
        return self.plans.update(plan_id, expected_revision, name, plan_description, plan_notes, environment_id, plugin_ids)
    def delete(self, plan_id, expected_revision):
        return self.sessions.change_configuration(plan_id, lambda: self.plans.delete(plan_id, expected_revision))
    def context_collect(self, plan_id, expected_revision=None, provider_id=None, request=None, expected_session_id=None, include_view=True):
        return self.sessions.collect(plan_id, expected_revision, provider_id, request, expected_session_id, include_view)
    def context_save_batch(self, plan_id, expected_revision, context_id, provider_id, name, context_notes, captures):
        plan = self.plans.get(plan_id)
        available = {provider for plugin in self.registry.plugins if plugin.manifest()['id'] in plan.get('plugin_ids', []) for provider in plugin.authoring([]).context_provider_ids}
        if provider_id not in available:
            raise TaskError('CONTEXT_PROVIDER_UNAVAILABLE', provider_id)
        return self.contexts.save_context_batch(plan_id, expected_revision, context_id, provider_id, name, context_notes, captures)
    def context_targets(self, plan_id, provider_id, request=None): return self.sessions.targets(plan_id, provider_id, request)
    def context_list(self, plan_id): return self.contexts.contexts(plan_id)
    def context_capture_get(self, plan_id, context_id, capture_id): return self.contexts.get_capture(context_id, capture_id, plan_id)
    def context_capture_append(self, plan_id, expected_revision, context_id, capture, *, request=None, include_view=True, session_id=None, label=""):
        return self.contexts.append_capture(plan_id, expected_revision, context_id, capture, request=request, include_view=include_view, session_id=session_id, label=label)
    def context_capture_replace(self, plan_id, expected_revision, context_id, capture_id, capture, *, request=None, include_view=True, session_id=None):
        return self.contexts.replace_capture(plan_id, expected_revision, context_id, capture_id, capture, request=request, include_view=include_view, session_id=session_id)
    def context_capture_delete(self, plan_id, expected_revision, context_id, capture_id):
        return self.contexts.delete_capture(plan_id, expected_revision, context_id, capture_id)
    def context_capture_reorder(self, plan_id, expected_revision, context_id, capture_id, direction):
        return self.contexts.reorder_capture(plan_id, expected_revision, context_id, capture_id, direction)
    def context_capture_label(self, plan_id, expected_revision, context_id, capture_id, label, operation_notes=None, send_preview=None):
        return self.contexts.update_capture_label(plan_id, expected_revision, context_id, capture_id, label, operation_notes, send_preview)
    def context_update(self, plan_id, expected_revision, context_id, name, context_notes=""):
        return self.contexts.update_context(plan_id, expected_revision, context_id, name, context_notes)
    def context_delete(self, plan_id, expected_revision, context_id):
        return self.contexts.delete_context(plan_id, expected_revision, context_id)
    def context_reorder(self, plan_id, expected_revision, context_id, direction):
        return self.contexts.reorder_context(plan_id, expected_revision, context_id, direction)

    def _materials(self, plan, source_contexts=None):
        plugin_ids = set(plan.get("plugin_ids", ()))
        capabilities = sorted(
            key for group in (self.registry.actions, self.registry.tools, self.registry.handlers)
            for key in group if key.split(".", 1)[0] in plugin_ids
        )
        contributions = []
        for plugin in self.registry.plugins:
            if plugin.manifest()["id"] in plugin_ids:
                contributions.append(asdict(plugin.authoring(capabilities)))
        contexts = [{
            "context_id": item["context_id"],
            "provider_id": item["provider_id"],
            "name": item["name"],
            "context_notes": item.get("context_notes", ""),
            "order_index": item["order_index"],
            "captures": [capture_ai_payload(capture, index, self.registry.views)
                         for index, capture in enumerate(item.get("captures", []))
                         if capture.get("items") or (capture.get("send_preview") and capture.get("views"))],
        } for item in (source_contexts if source_contexts is not None else self.contexts.context_records(plan["plan_id"]))
            if any(c.get("items") or (c.get("send_preview") and c.get("views")) for c in item.get("captures", []))]

        return {
            "plan": {
                "name": plan["name"],
                "plan_description": plan["plan_description"],
                "plan_notes": plan.get("plan_notes", ""),
            },
            "contexts": contexts,
            "plugins": contributions,
            "capability_catalog": self.registry.catalog(),
            "task_package_schema": PLAN_CANDIDATE_SCHEMA,
        }

    def _messages(self, plan, source_contexts=None):
        system = "\n".join((DOMAIN_RULES, EXECUTABLE_STEP_RULES, PLAN_RULES))
        materials = self._materials(plan, source_contexts)
        if self.privacy_settings.get()["redact_for_ai"]:
            materials = redact_ai_payload(materials)
        return [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(materials, ensure_ascii=False)}]

    def _snapshot(self, plan, channel):
        source_contexts = self.contexts.context_records(plan["plan_id"])
        messages = self._messages(plan, source_contexts)
        if channel == "web_chat":
            messages[0]["content"] += "\n" + WEB_CHAT_RULES + "\n" + WEB_CHAT_CODE_RULES
        prompt, _ = web_chat_export(messages)
        limit = self.settings.get()["request_limit_bytes"]
        ensure_limit(utf8_size(messages), limit)
        root = self.plan_files_root / plan["plan_id"] / "generations"
        root.mkdir(parents=True, exist_ok=True)
        return messages, prompt, root, source_contexts

    async def generate(self, plan_id, expected_revision, channel):
        if channel not in {"api", "web_chat"}: raise TaskError("FORM_INVALID", channel)
        plan = self.plans.get(plan_id)
        if plan["revision"] != expected_revision: raise TaskError("EDIT_CONFLICT")
        messages, prompt, root, source_contexts = self._snapshot(plan, channel)
        temp = root / f"request-{plan['revision']}-{channel}.txt"
        temp.write_text(prompt, encoding="utf-8")
        generation = self.generations.create_generation(plan_id, plan["revision"], channel, str(temp.relative_to(self.plan_files_root)))
        self._context_snapshot_path(generation).write_text(json.dumps(source_contexts, ensure_ascii=False), encoding="utf-8")
        if channel == "web_chat":
            return {**generation, "prompt": prompt, "attachments": web_chat_export(messages)[1], "request_size_bytes": utf8_size(messages), "request_limit_bytes": self.settings.get()["request_limit_bytes"]}
        if self.authoring.model is None:
            self.generations.finish_generation(generation["generation_id"], "FAILED", diagnostics=[{"code": "MODEL_NOT_CONFIGURED"}])
            raise TaskError("MODEL_NOT_CONFIGURED")
        try:
            reply = await self.authoring._complete(messages, [], PLAN_RESPONSE_SCHEMA)
            return self._accept(generation["generation_id"], reply.structured_content)
        except Exception as exc:
            self.generations.finish_generation(generation["generation_id"], "FAILED", diagnostics=[{"message": str(exc)}])
            raise

    def _context_snapshot_path(self, generation):
        return self.plan_files_root / generation["plan_id"] / "generations" / f'{generation["generation_id"]}-contexts.json'

    def _frozen_contexts(self, generation):
        path = self._context_snapshot_path(generation)
        return {item["context_id"]: item for item in json.loads(path.read_text(encoding="utf-8"))} if path.exists() else {}

    def _validated_refs(self, generation, package, refs):
        if not isinstance(refs, dict):
            raise TaskError("TASK_PACKAGE_INVALID", "plan_context_refs 必须按步骤列出上下文 ID")
        keys = {entry["key"] for entry in package["steps"]}
        frozen = self._frozen_contexts(generation)
        for key, context_ids in refs.items():
            if (key not in keys or not isinstance(context_ids, list)
                    or any(not isinstance(item, str) for item in context_ids)
                    or len(context_ids) != len(set(context_ids))):
                raise TaskError("TASK_PACKAGE_INVALID", f"{key} 的上下文引用无效")
            for context_id in context_ids:
                if not isinstance(context_id, str) or context_id not in frozen or not any(capture.get('items') or (capture.get('send_preview') and capture.get('views')) for capture in frozen[context_id].get('captures', [])):
                    raise TaskError("TASK_PACKAGE_INVALID", f"{key} 引用了不存在的上下文：{context_id}")
        # Old replies without evidence remain importable. With frozen material,
        # omission must not silently turn a generated task into an evidence-free one.
        has_material = any(
            (capture.get("items") or (capture.get("send_preview") and capture.get("views")))
            for context in frozen.values() for capture in context.get("captures", [])
        )
        missing = keys - refs.keys()
        if missing and (has_material or refs):
            raise TaskError(
                "TASK_PACKAGE_INVALID",
                "缺少步骤上下文对应关系：" + "、".join(sorted(missing))
                + "；请在 plan_context_refs 中逐步填写相关上下文 ID，无相关材料时明确填写 []",
            )
        return refs

    def _accept(self, generation_id, content, response_text=None):
        generation = self.generations.generation(generation_id)
        response_path = self.plan_files_root / generation["plan_id"] / "generations" / f"{generation_id}-response.json"
        response_path.write_text(response_text if response_text is not None else json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
        if isinstance(content.get("error"), dict):
            error = content["error"]
            if error.get("code") != "PLAN_INFORMATION_MISSING": raise TaskError("TASK_PACKAGE_INVALID")
            return self.generations.finish_generation(generation_id, "BLOCKED", str(response_path.relative_to(self.plan_files_root)), diagnostics=[error])
        refs = content.get("plan_context_refs", {})
        package = {key: value for key, value in content.items() if key != "plan_context_refs"}
        checked = self.tasks.validate_package(package, expected_origin="ai_generated")
        refs = self._validated_refs(generation, checked, refs)
        diagnostics = checked.pop("diagnostics", [])
        if refs:
            checked["plan_context_refs"] = refs
        result = self.generations.finish_generation(generation_id, "READY", str(response_path.relative_to(self.plan_files_root)), checked, diagnostics)
        result["context_labels"] = {key: item["name"] for key, item in self._frozen_contexts(generation).items()}
        return result

    def parse(self, generation_id, response_text):
        try:
            content = json.loads(response_text)
        except json.JSONDecodeError as exc:
            repaired_text = _recover_step_content_quotes(response_text)
            try:
                content = json.loads(repaired_text)
                response_text = repaired_text
            except json.JSONDecodeError:
                self.generations.finish_generation(generation_id, "FAILED", diagnostics=[{"code": "MODEL_JSON_INVALID", "message": str(exc)}])
                raise TaskError("MODEL_JSON_INVALID", str(exc)) from exc
        if not isinstance(content, dict): raise TaskError("TASK_PACKAGE_INVALID")
        try:
            return self._accept(generation_id, content, response_text)
        except Exception as exc:
            self.generations.finish_generation(generation_id, "FAILED", diagnostics=[{"message": str(exc)}])
            raise

    def import_generation(self, generation_id):
        generation = self.generations.generation(generation_id)
        if generation["status"] not in {"READY", "IMPORTED"} or not generation.get("candidate"):
            raise TaskError("TASK_PACKAGE_INVALID", "只有校验通过的候选可以导入")
        package = dict(generation["candidate"])
        refs = package.pop("plan_context_refs", {})
        self._validated_refs(generation, package, refs)
        frozen = self._frozen_contexts(generation)
        task_id = None
        try:
            with self.uow.transaction():
                result = self.tasks.import_package(package)
                task_id = result.get("task_id") if isinstance(result, dict) else result
                if not task_id:
                    raise TaskError("SAVE_FAILED", "任务导入未返回 task_id")
                task_steps = self.steps.steps(task_id)
                if len(task_steps) != len(package["steps"]):
                    raise TaskError("SAVE_FAILED", "导入步骤数量与候选不一致")
                for entry, step in zip(package["steps"], task_steps):
                    for context_id in refs.get(entry["key"], []):
                        context = frozen[context_id]
                        group = self.step_contexts.create_step_context_group(
                            step["step_id"], context["provider_id"], context["name"], context.get("context_notes", ""),
                        )
                        for capture in context.get("captures", []):
                            self.step_contexts.append_step_context_capture(
                                group["context_id"], capture, request=capture.get("request", {}),
                                include_view=capture.get("include_view", True), source_page="planning_import",
                                source_session_id=capture.get("source_session_id"), label=capture.get("label", ""),
                                captured_at=capture.get("captured_at"),
                            )
                self.generations.mark_imported(generation_id, task_id)
        except Exception:
            raise
        return {"task_id": task_id, "already_imported": False}
