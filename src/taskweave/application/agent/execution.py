"""Compact persisted run facts and precisely scoped evidence reads."""

import json
import time

from taskweave.application.agent.projection import fields, page, snapshot_view, contract_projection, textual_evidence
from taskweave.core.validation import TaskError, pointer


def run_summary(run):
    result = fields(run, ("run_id", "task_id", "status", "mode", "environment_id", "definition_hash",
                          "started_at", "finished_at", "can_end"))
    attempts = run.get("attempts", [])
    result["attempt_count"] = len(attempts)
    result["failed_attempts"] = [fields(row, ("attempt_id", "step_id", "status", "execution_path", "error_code"))
                                 for row in attempts if row.get("valid") and row["status"] in {"FAILED", "UNKNOWN"}][-5:]
    request = json.loads(run.get("request_json") or "{}")
    if request.get("waiting_input"):
        result["waiting_input"] = request["waiting_input"]
        result["next_action"] = "provide_inputs"
    elif run["status"] == "UNKNOWN" or any(row.get("status") == "UNKNOWN" for row in result["failed_attempts"]):
        result["next_action"] = "reconcile_with_evidence"
    elif run["status"] == "FAILED":
        result["next_action"] = "inspect_failure"
    elif run["status"] == "SUCCEEDED":
        result["next_action"] = "review"
    else:
        result["next_action"] = "wait_or_control"
    return result


class AgentExecution:
    def __init__(self, app, records, discovery, sanitize):
        self.app, self.records, self.discovery = app, records, discovery
        self.sanitize = sanitize

    def safe_document(self, value, include_images=False):
        return contract_projection(value if include_images else textual_evidence(value), self.sanitize)

    def wait(self, identity, kind="run", timeout=30):
        if type(timeout) not in (int, float) or not 0 <= timeout <= 30:
            raise TaskError("AGENT_WAIT_INVALID", "等待范围为0–30秒")
        if kind == "run":
            return run_summary(self.app.runs.wait(identity, timeout))
        if kind != "sequence":
            raise TaskError("AGENT_KIND_INVALID")
        deadline = time.monotonic() + timeout
        while True:
            run = self.app.sequences.run_get(identity)
            if run["status"] not in {"READY", "RUNNING"} or time.monotonic() >= deadline:
                return self.sequence_summary(run)
            time.sleep(min(.2, max(0, deadline - time.monotonic())))

    @staticmethod
    def sequence_summary(run):
        return {**fields(run, ("sequence_run_id", "sequence_id", "status", "current_node_id", "created_at")),
                "nodes": [fields(node, ("node_id", "task_id", "run_id", "status", "position")) for node in run["nodes"]]}

    def inspect(self, kind, identity, sections=None, cursor=None, limit=20, include_images=False, **options):
        allowed = {'request': {'pointer', 'text_offset'}, 'package': {'pointer', 'text_offset'}, 'events': {'after'},
                   'operation_result': {'params', 'pointer', 'text_offset'}, 'bundle': {'pointer', 'text_offset'},
                   'result': {'pointer', 'text_offset'},
                   'output': {'step_id', 'output', 'execution_path', 'item_pointer', 'loop_node_id', 'pointer', 'text_offset'}}.get(kind, set())
        if set(options) - allowed:
            raise TaskError('AGENT_ARGUMENT_INVALID')
        if kind == 'operation_result':
            params = options.get('params', {})
            self.discovery.validate_operation('inspect', identity, params)
            if identity == 'run.output':
                return self.inspect('output', params['run_id'], cursor=cursor, limit=limit, include_images=include_images,
                                    **{key: value for key, value in params.items() if key != 'run_id'},
                                    **{key: value for key, value in options.items() if key != 'params'})
            if identity == 'result.read':
                return self.inspect('result', params['result_id'], cursor=cursor, limit=limit,
                                    include_images=include_images,
                                    **{key: value for key, value in options.items() if key != 'params'})
            if identity == 'run.get':
                value = run_summary(self.app.runs.get(params['run_id']))
            elif identity == 'run.list':
                value = [run_summary(run) for run in self.app.dispatch(identity, params)]
            else:
                value = self.app.dispatch(identity, params)
            if identity in {'plan.generation.get', 'plan.generation.list'}:
                def public_generation(row):
                    return {key: item for key, item in row.items() if key not in {'request_snapshot_path', 'response_path'}}
                value = [public_generation(row) for row in value] if isinstance(value, list) else public_generation(value)
            from taskweave.application.agent.projection import selected_view
            return selected_view(self.safe_document(value, include_images), {'operation': identity}, options.get('pointer', ''), cursor, limit, options.get('text_offset'))
        if kind == "request":
            row = self.records.request(identity)
            if row is None:
                raise TaskError("AGENT_REQUEST_NOT_FOUND")
            result = fields(row, ("request_id", "state", "created_at", "updated_at"))
            result["result_available"] = row["result"] is not None
            if "pointer" in options:
                from taskweave.application.agent.projection import selected_view
                selected = selected_view(self.safe_document(row['result'], include_images), {'request_id': identity}, options['pointer'], cursor, limit, options.get('text_offset'))
                result['result'] = selected
            return result
        if kind == "bundle":
            if 'pointer' in options:
                from taskweave.application.agent.projection import selected_view
                return selected_view(self.safe_document(self.records.get('bundle', identity), include_images), {'bundle_id': identity}, options['pointer'], cursor, limit, options.get('text_offset'))
            return snapshot_view(self.records.get("bundle", identity), identity, sections, cursor, limit)
        if kind == "package":
            if 'text_offset' in options:
                from taskweave.application.agent.projection import selected_view
                return selected_view(self.safe_document(self.app.tasks.export(identity), include_images), {'task_id': identity}, options.get('pointer', ''), cursor, limit, options['text_offset'])
            return pointer(self.safe_document(self.app.tasks.export(identity), include_images), options.get("pointer", ""))
        if kind == "run":
            sections = ["summary"] if sections is None else sections
            if not isinstance(sections, list) or set(sections) - {"summary", "attempts", "results", "flow", "definition"}:
                raise TaskError("AGENT_SECTION_INVALID")
            run = self.app.runs.get(identity)
            result = run_summary(run)
            for section, source in (("attempts", "attempts"), ("results", "results"), ("flow", "flow_instances")):
                if section in sections:
                    paging = page(run.get(source, []), {"run_id": identity, "section": section}, cursor, limit)
                    result[section] = paging.pop("items")
                    result[section + "_page"] = paging
            if "definition" in sections:
                result["definition"] = json.loads(run["definition_json"])
            return result
        if kind == "output":
            allowed = {"step_id", "output", "execution_path", "item_pointer", "loop_node_id", "pointer", 'text_offset'}
            if set(options) - allowed or "step_id" not in options:
                raise TaskError("AGENT_ARGUMENT_INVALID")
            args = dict(options)
            selected_pointer = args.pop("pointer", "")
            text_offset = args.pop('text_offset', None)
            output_name = args.get('output', 'data')
            def project(value):
                return self.safe_document({output_name: value}, include_images).get(output_name, {'image_omitted': True})
            value = self.app.runs.project_output(identity, **args, transform=project)
            if text_offset is not None:
                from taskweave.application.agent.projection import selected_view
                return selected_view(value, {'run_id': identity, **fields(args, ('step_id', 'output', 'execution_path'))}, selected_pointer, cursor, limit, text_offset)
            return {"run_id": identity, **fields(args, ("step_id", "execution_path", "output")),
                    "data": pointer(value, selected_pointer)}
        if kind == "result":
            value = self.app.runs.read_result(identity)
            if 'pointer' in options:
                from taskweave.application.agent.projection import selected_view
                selected = {**fields(value, ('name', 'media_type', 'size_bytes', 'data', 'preview', 'views')), 'file_available': 'path' in value}
                return selected_view(self.safe_document(selected, include_images), {'result_id': identity}, options['pointer'], cursor, limit, options.get('text_offset'))
            return {"result_id": identity, **fields(value, ("name", "media_type", "size_bytes", "data", "preview", "views")),
                    "file_available": "path" in value}
        if kind == "events":
            after = options.get("after", 0)
            return self.app.runs.event_page(identity, after=after, limit=limit)
        if kind == "sequence_run":
            return self.sequence_summary(self.app.sequences.run_get(identity))
        return self.discovery.describe(kind, identity, sections)
