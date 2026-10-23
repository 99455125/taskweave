"""Discover actual workspace capabilities without importing their full catalogs."""

from dataclasses import asdict
import json

from taskweave.application.agent.contracts import operation_detail, validate_operation, PURPOSE_OPERATIONS, VIRTUAL_OPERATIONS
from taskweave.application.agent.projection import bounded, fields, page
from taskweave.core.validation import TaskError


class AgentDiscovery:
    def __init__(self, app):
        self.app = app

    def validate_operation(self, purpose, operation, params):
        return validate_operation(self.app, purpose, operation, params)

    def discover(self, kind, query="", cursor=None, limit=20):
        if not isinstance(query, str) or len(query) > 500:
            raise TaskError("AGENT_QUERY_INVALID")
        app = self.app
        if kind == 'operation':
            rows = [{'id': operation, 'purpose': purpose} for purpose, operations in PURPOSE_OPERATIONS.items() for operation in operations]
            rows.extend({'id': operation, 'purpose': purpose} for operation, (purpose, _) in VIRTUAL_OPERATIONS.items())
            rows.extend({'id': 'review.' + action, 'purpose': 'review'} for action in ('prepare', 'read', 'read_spec', 'open'))
        elif kind == "task":
            rows = [{"id": row["task_id"], **fields(row, ("name", "description", "definition_hash"))}
                    for row in app.tasks.list()]
        elif kind == "sequence":
            rows = [{"id": row["sequence_id"], **fields(row, ("name", "description", "revision"))}
                    for row in app.sequences.list()]
        elif kind == "plan":
            rows = [{"id": row["plan_id"], **fields(row, ("name", "plan_description", "revision"))}
                    for row in app.planning.list()]
        elif kind == "environment":
            rows = [{"id": row["environment_id"], "name": row["name"]}
                    for row in app.environments.list()]
        elif kind == "plugin":
            installed = {row["id"]: {**fields(row, ("id", "enabled", "error", "distribution")), 'installed': True}
                         for row in app.installed_plugins()}
            for plugin_id, manifest in app.registry.manifests.items():
                installed.setdefault(plugin_id, {"id": plugin_id, 'installed': False})
                installed[plugin_id].update(loaded=True, version=manifest.get("package_version"))
            for plugin_id, row in installed.items():
                row.setdefault("loaded", False)
                if plugin_id in app.registry.load_errors:
                    row["error"] = app.registry.load_errors[plugin_id]
                row["external_environment"] = "not_checked"
            rows = list(installed.values())
        elif kind == 'context_provider':
            rows = [{'id': provider, 'plugin_id': plugin_id} for plugin_id, manifest in app.registry.manifests.items()
                    for provider in manifest.get('context_requests', {})]
        elif kind == "capability":
            actions = {key: value.spec for key, value in app.registry.actions.items()}
            actions.update({key: value.spec for key, value in app.registry.tools.items() if key not in actions})
            rows = [{"id": key, **fields(asdict(spec), ("description", "effect", "timeout_ms"))}
                    for key, spec in actions.items()]
            rows.extend({"id": key, "description": "持久化结果处理器", "kind": "result_handler"}
                        for key in app.registry.handlers if key not in actions)
        else:
            raise TaskError("AGENT_KIND_INVALID", "未知发现类型")
        rows = sorted((row for row in rows if query.casefold() in
                       json.dumps(row, ensure_ascii=False).casefold()), key=lambda row: row["id"])
        return page(rows, {"kind": kind, "query": query}, cursor, limit)

    def describe(self, kind, identity, sections=None):
        sections = ["summary"] if sections is None else sections
        if not isinstance(sections, list) or not sections or set(sections) - {
            "summary", "schemas", "code", "flow", "variables", "contexts",
        }:
            raise TaskError("AGENT_SECTION_INVALID")
        app = self.app
        if kind == 'plugin':
            manifest = app.registry.manifests.get(identity)
            if manifest is None:
                raise TaskError('PLUGIN_NOT_LOADED')
            return fields(manifest, ('id', 'api_version', 'package_version', 'core_requires', 'context_requests', 'config_variables', 'resource_descriptions'))
        if kind == 'context_provider':
            for plugin_id, manifest in app.registry.manifests.items():
                if identity in manifest.get('context_requests', {}):
                    return {'id': identity, 'plugin_id': plugin_id, 'request_contract': manifest['context_requests'][identity]}
            raise TaskError('CONTEXT_PROVIDER_UNAVAILABLE')
        if kind == "operation":
            if identity.startswith('review.'):
                from taskweave.application.agent.review import review_contract
                return {'operation': identity, 'purpose': 'review', 'parameters': review_contract(identity.removeprefix('review.'))}
            return bounded(operation_detail(app, identity))
        if kind == "capability":
            action = app.registry.actions.get(identity) or app.registry.tools.get(identity)
            if action is None:
                if identity in app.registry.handlers:
                    return {"id": identity, "kind": "result_handler", "schema": app.registry.handlers[identity].schema()}
                raise TaskError("CAPABILITY_UNKNOWN", identity)
            result = {"id": identity, "action": asdict(action.spec)}
            if "summary" in sections:
                result["authoring"] = [asdict(value) for value in app.registry.contributions([identity])]
            return bounded(result)
        if kind == "environment":
            config, secrets = app.environments.get(identity)
            return bounded({"id": identity, "variables": [
                {"name": key, "secret": key in secrets,
                 "type": "secret_reference" if key in secrets else type(config[key]).__name__}
                for key in sorted(set(config) | set(secrets))]})
        if kind == "task":
            task = app.tasks.get(identity)
            result = fields(task, ("task_id", "name", "description", "definition_hash", "flow_validation_state"))
            result["definition_hash"] = app.tasks.definition_hash(identity)
            try:
                flow_details = app.tasks.describe_flow(identity)
            except TaskError as exc:
                if not exc.code.startswith(("FLOW_", "LOOP_")):
                    raise
                # A draft may contain loop bindings before its control tree is saved.
                # Keep its baseline available so the author can repair that draft.
                flow_details = {"flow": json.loads(task["graph_json"]), "confirmed": False}
                result["flow_diagnostics"] = [exc.document()]
            result["flow_confirmed"] = flow_details["confirmed"]
            if "summary" in sections:
                result["steps"] = [fields(row, ("step_id", "name", "step_description", "validation_state", "content_hash"))
                                   for row in app.steps.list(identity)]
            if "schemas" in sections:
                result["input_schema"] = json.loads(task["input_schema_json"])
            if "flow" in sections:
                result["flow"] = flow_details["flow"]
            return bounded(result)
        if kind == "step":
            step = app.steps.get(identity)
            result = fields(step, ("step_id", "task_id", "name", "step_description", "step_notes", "content_hash", "validation_state", "capabilities"))
            if "code" in sections:
                result["step_content"] = step["step_content"]
            if "schemas" in sections:
                result.update(fields(step, ("input_schema", "output_schema", "bindings", "plugin_requirements", "timeout_ms", "delay_after_previous_seconds")))
            if "contexts" in sections:
                result["contexts"] = [{"context_id": row["context_id"], **fields(row, ("name", "provider_id", "revision"))}
                                      for row in app.contexts.list(identity)]
            return bounded(result)
        if kind == "sequence":
            return bounded(app.sequences.get(identity))
        if kind == "plan":
            return bounded(fields(app.planning.get(identity), (
                "plan_id", "name", "plan_description", "plan_notes", "revision", "plugin_ids", "environment_id")))
        raise TaskError("AGENT_KIND_INVALID", "未知详情类型")
