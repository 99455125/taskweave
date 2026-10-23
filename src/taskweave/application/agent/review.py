"""Frozen acceptance requirements and read-only projections of execution facts."""

import json
from datetime import datetime, timezone
from uuid import uuid4

from taskweave.application.agent.checks import evaluate, preview
from taskweave.application.agent.projection import fields
from taskweave.core.flow_values import aggregate_output
from taskweave.core.task_flow import is_linear_flow
from taskweave.core.validation import TaskError, fingerprint, pointer, validate


RULE = {"type": "object", "properties": {
    "op": {"enum": ["exists", "eq", "ne", "gt", "gte", "lt", "lte", "count", "contains", "all", "any"]},
    "expected": {}, "check": {"$ref": "#/$defs/rule"},
}, "required": ["op"], "additionalProperties": False}
CHECK_SCHEMA = {"type": "array", "maxItems": 100, "$defs": {"rule": RULE}, "items": {
    "type": "object", "properties": {
        "id": {"type": "string", "minLength": 1, "maxLength": 100},
        "label": {"type": "string", "minLength": 1, "maxLength": 500},
        "source": {"type": "object", "properties": {
            "step_id": {"type": "string"}, "node_id": {"type": "string"}, "output": {"type": "string"},
            "pointer": {"type": "string"}, "execution_path": {"type": "string"},
            "item_pointer": {"type": "string"}, "loop_node_id": {"type": "string"},
        }, "required": ["step_id"], "additionalProperties": False},
        "op": RULE["properties"]["op"], "expected": {}, "check": {"$ref": "#/$defs/rule"},
        "on_skip": {"enum": ["not_applicable", "missing"]},
    }, "required": ["id", "label", "source", "op"], "additionalProperties": False,
}}


def review_contract(action):
    from copy import deepcopy
    S = {'type': 'string'}
    def schema(properties, required):
        return {'type': 'object', 'properties': properties, 'required': required, 'additionalProperties': False}
    schemas = {
        'prepare': schema({'target_kind': {'enum': ['task', 'sequence']}, 'target_id': S,
                           'expected_version': {'type': ['string', 'integer']}, 'title': S,
                           'checks': {key: deepcopy(value) for key, value in CHECK_SCHEMA.items() if key != '$defs'}},
                          ['target_kind', 'target_id', 'expected_version', 'title', 'checks']),
        'read': schema({'kind': {'enum': ['run', 'sequence']}, 'identity': S, 'sections': {'type': 'array', 'items': S},
                        'cursor': {'type': ['string', 'null']}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100}, 'pointer': S}, ['kind', 'identity']),
        'open': schema({'kind': {'enum': ['run', 'sequence']}, 'identity': S}, ['kind', 'identity']),
        'read_spec': schema({'review_spec_id': S, 'cursor': {'type': ['string', 'null']},
                             'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100}}, ['review_spec_id']),
    }
    if action not in schemas:
        raise TaskError('AGENT_OPERATION_DENIED')
    result = schemas[action]
    if action == 'prepare':
        result['$defs'] = deepcopy(CHECK_SCHEMA['$defs'])
    return result


class AgentReview:
    def __init__(self, app, records):
        self.app, self.records = app, records

    def version(self, kind, identity):
        if kind == "task":
            return self.app.tasks.definition_hash(identity)
        if kind == "sequence":
            return self.app.sequences.get(identity)["revision"]
        raise TaskError("AGENT_KIND_INVALID")

    @staticmethod
    def _category(kind, identity, version):
        return "review_specs:" + fingerprint({"kind": kind, "identity": identity, "version": version})

    def prepare(self, target_kind, target_id, expected_version, title, checks):
        if isinstance(expected_version, bool) or not isinstance(expected_version, (str, int)):
            raise TaskError('REVIEW_REQUIREMENTS_INVALID')
        if self.version(target_kind, target_id) != expected_version:
            raise TaskError("EDIT_CONFLICT")
        if not isinstance(title, str) or not title.strip() or len(title) > 500:
            raise TaskError("REVIEW_REQUIREMENTS_INVALID")
        validate(checks, CHECK_SCHEMA)
        if len({check["id"] for check in checks}) != len(checks) or len(json.dumps(checks, ensure_ascii=False).encode()) > 65536:
            raise TaskError("REVIEW_REQUIREMENTS_INVALID")
        if target_kind == "task":
            owners = {None: target_id}
        else:
            owners = {node["node_id"]: node["task_id"] for node in self.app.sequences.get(target_id)["nodes"]}
        def check_rule(rule, depth=0):
            if depth > 8:
                raise TaskError("REVIEW_REQUIREMENTS_INVALID")
            if rule["op"] in {"all", "any"}:
                if "check" not in rule or "expected" in rule:
                    raise TaskError("REVIEW_REQUIREMENTS_INVALID")
                check_rule(rule["check"], depth + 1)
            elif rule["op"] != "exists" and "expected" not in rule:
                raise TaskError("REVIEW_REQUIREMENTS_INVALID")
        for check in checks:
            check_rule(check)
            source = check["source"]
            owner = owners.get(source.get("node_id"))
            if owner is None or source["step_id"] not in {step["step_id"] for step in self.app.steps.list(owner)}:
                raise TaskError("REVIEW_SOURCE_INVALID")
        spec = {"target_kind": target_kind, "target_id": target_id, "expected_version": expected_version,
                "title": title, "checks": checks}
        if target_kind == 'sequence':
            spec['task_hashes'] = {node['node_id']: self.app.tasks.definition_hash(node['task_id'])
                                   for node in self.app.sequences.get(target_id)['nodes']}
        spec["review_spec_id"] = fingerprint(spec)
        def save():
            if self.version(target_kind, target_id) != expected_version:
                raise TaskError("EDIT_CONFLICT")
            if target_kind == 'sequence' and spec['task_hashes'] != {node['node_id']: self.app.tasks.definition_hash(node['task_id']) for node in self.app.sequences.get(target_id)['nodes']}:
                raise TaskError('EDIT_CONFLICT')
            self.records.put("review_spec", spec["review_spec_id"], spec)
            self.records.put(self._category(target_kind, target_id, expected_version), spec["review_spec_id"], spec)
            return spec
        with self.app.coordinator.lock:
            return self.records.atomic("review-prepare-" + spec["review_spec_id"], fingerprint(spec), save)

    def select(self, target_kind, target_id, version, review_spec_id=None, task_hashes=None):
        if review_spec_id is None:
            records = self.records.find(self._category(target_kind, target_id, version), limit=100)
            return next((record for record in records if target_kind != 'sequence' or record.get('task_hashes') == task_hashes), None)
        spec = self.records.get("review_spec", review_spec_id)
        if (spec["target_kind"], spec["target_id"], spec["expected_version"]) != (target_kind, target_id, version):
            raise TaskError("REVIEW_VERSION_MISMATCH")
        if target_kind == 'sequence' and spec.get('task_hashes') != task_hashes:
            raise TaskError('REVIEW_VERSION_MISMATCH')
        return spec

    def bind_run(self, run_id, review_spec_id=None):
        run = self.app.runs.stored(run_id)
        spec = self.select("task", run["task_id"], run["definition_hash"], review_spec_id)
        self.records.put("review_binding", "run:" + run_id, {"review_spec_id": spec["review_spec_id"] if spec else None})

    def bind_sequence_run(self, sequence_run_id, review_spec_id=None):
        run = self.app.sequences.run_get(sequence_run_id)
        spec = self.select("sequence", run["sequence_id"], run["snapshot"]["revision"], review_spec_id, run['snapshot']['task_hashes'])
        self.records.put("review_binding", "sequence:" + sequence_run_id, {"review_spec_id": spec["review_spec_id"] if spec else None})

    def _binding(self, kind, identity):
        try:
            return self.records.get("review_binding", kind + ":" + identity)
        except TaskError as exc:
            if exc.code != "AGENT_RECORD_NOT_FOUND":
                raise
            return {"review_spec_id": None}

    @staticmethod
    def _witness_pointer(witness, path):
        for segment in path.split("/")[1:]:
            if isinstance(witness, list):
                try:
                    witness = witness[int(segment)]
                except (ValueError, IndexError):
                    return None
            else:
                break
        return witness

    def _check(self, check, run):
        source = check["source"]
        result = {"id": check["id"], "label": check["label"], "source": source,
                  "expected": preview(check.get("expected")), "op": check["op"], "evidence": []}
        definition = json.loads(run["definition_json"] or "{}")
        args = {key: value for key, value in source.items() if key not in {"node_id", "pointer"}}
        flow = definition.get("flow")
        try:
            witness = True
            if flow and not is_linear_flow(flow) and source.get("execution_path") is None:
                visits = self.app.runs.flow_runs.instances(run["run_id"])
                # A still-running control frame can expose a partial aggregate; it is not acceptance evidence.
                if run["status"] in {"READY", "RUNNING", "PAUSED"}:
                    raise TaskError("OUTPUT_NOT_AVAILABLE")
                witness = aggregate_output(flow, visits, source["step_id"], source.get("output", "data"),
                                           lambda aid, name: {"attempt_id": aid})
            if witness is None:
                result.update(evaluate(None, check, witness, check.get("on_skip", "not_applicable")))
                result.update(actual_available=False, message="该动作属于未执行分支")
                return result
            value = self.app.runs.output(run["run_id"], **args)
            selected_pointer = source.get("pointer", "")
            value = pointer(value, selected_pointer)
            witness = self._witness_pointer(witness, selected_pointer)
            result.update(evaluate(value, check, witness, check.get("on_skip", "not_applicable")))
            result["actual"] = preview(value)
            result["actual_fingerprint"] = fingerprint(value)
            attempts = [attempt for attempt in run["attempts"] if attempt["step_id"] == source["step_id"]
                        and attempt["valid"] and attempt["status"] == "SUCCEEDED"
                        and (source.get("execution_path") is None or attempt.get("execution_path") == source["execution_path"])]
            refs_by_attempt = {}
            for ref in run["results"]:
                refs_by_attempt.setdefault(ref["attempt_id"], []).append(ref["result_id"])
            result["evidence"] = [{"run_id": run["run_id"], **fields(attempt, ("attempt_id", "step_id", "execution_path")),
                                   "result_ids": sorted(refs_by_attempt.get(attempt["attempt_id"], [])),
                                   "source_kind": "persisted_step_result"} for attempt in attempts]
        except TaskError as exc:
            missing = exc.code in {"OUTPUT_NOT_AVAILABLE", "RESULT_NOT_FOUND", "INPUT_MISSING", "RESULT_UNAVAILABLE"}
            result.update(status="MISSING" if missing else "ERROR", error_code=exc.code)
        return result

    @staticmethod
    def _automatic(run_status, checks, configured):
        statuses = [check["status"] for check in checks]
        if not configured or not checks:
            return "UNCONFIGURED"
        if run_status != "SUCCEEDED":
            return "INCOMPLETE"
        if any(status in {"FAIL", "ERROR"} for status in statuses):
            return "FAIL"
        if "MISSING" in statuses:
            return "MISSING"
        return "PASS" if "PASS" in statuses else "NOT_APPLICABLE"

    def _sequence_report(self, identity):
        run = self.app.sequences.run_get(identity)
        binding = self._binding("sequence", identity)
        spec_id = binding.get("review_spec_id")
        spec = self.records.get("review_spec", spec_id) if spec_id else None
        children = {node["node_id"]: self.app.runs.get(node["run_id"]) for node in run["nodes"] if node.get("run_id")}
        definitions = {node_id: json.loads(child['definition_json']) for node_id, child in children.items()}
        step_names = {node_id: {step['step_id']: step['name'] for step in definition.get('steps', [])}
                      for node_id, definition in definitions.items()}
        checks = []
        for check in spec["checks"] if spec else []:
            node_id = check["source"]["node_id"]
            if node_id not in children:
                observed = {"id": check["id"], "label": check["label"], "source": check["source"],
                            "status": "MISSING", "message": "此组合节点尚未执行", "evidence": []}
            else:
                observed = self._check(check, children[node_id])
                for evidence in observed["evidence"]:
                    evidence.update(sequence_run_id=identity, node_id=node_id)
            checks.append(observed)
        report = {"kind": "sequence", "identity": identity, "sequence_run_id": identity,
                  "review_spec_id": spec_id, "title": spec["title"] if spec else run["snapshot"]["name"],
                  "goal": spec["title"] if spec else "", "definition_hash": fingerprint(run["snapshot"]),
                  "run_status": run["status"], "automatic_status": self._automatic(run["status"], checks, spec is not None),
                  "checks": checks, "inputs": run["inputs"],
                  "path": [{**fields(node, ("node_id", "task_id", "run_id", "status", "position")),
                            'task_name': definitions.get(node['node_id'], {}).get('task', {}).get('name', '尚未执行的任务'),
                            "attempts": [{**fields(attempt, ("attempt_id", "step_id", "execution_path", "status", "valid")),
                                          'name': step_names.get(node['node_id'], {}).get(attempt['step_id'], '步骤')}
                                         for attempt in children.get(node["node_id"], {}).get("attempts", [])],
                            "flow": children.get(node["node_id"], {}).get("flow_instances", [])} for node in run["nodes"]],
                  "result_state": [{"node_id": node_id, **fields(ref, ("result_id", "attempt_id", "state", "checksum"))}
                                   for node_id, child in children.items() for ref in child["results"]]}
        return self._finish_report(report)

    def read(self, kind, identity):
        if kind == "sequence":
            return self._sequence_report(identity)
        if kind != "run":
            raise TaskError("AGENT_KIND_INVALID")
        run = self.app.runs.get(identity)
        definition = json.loads(run["definition_json"] or "{}")
        binding = self._binding(kind, identity)
        spec_id = binding.get("review_spec_id")
        spec = self.records.get("review_spec", spec_id) if spec_id else None
        checks = [self._check(check, run) for check in spec["checks"]] if spec else []
        automatic = self._automatic(run["status"], checks, spec is not None)
        report = {"kind": kind, "identity": identity, "run_id": identity, "review_spec_id": spec_id,
                  "title": spec["title"] if spec else definition.get("task", {}).get("name", "执行验收"),
                  "goal": definition.get("task", {}).get("description", ""),
                  "definition_hash": run["definition_hash"], "run_status": run["status"],
                  "automatic_status": automatic, "checks": checks,
                  "inputs": json.loads(run.get("input_summary_json") or "{}"),
                  "path": [{**fields(attempt, ("step_id", "attempt_id", "execution_path", "status", "valid", "started_at", "finished_at")),
                            "name": next((step["name"] for step in definition.get("steps", []) if step["step_id"] == attempt["step_id"]), "步骤")}
                           for attempt in run["attempts"]],
                  "flow": run.get("flow_instances", []),
                  "result_state": [fields(ref, ("result_id", "attempt_id", "state", "checksum")) for ref in run["results"]]}
        return self._finish_report(report)

    def _finish_report(self, report):
        kind, identity = report["kind"], report["identity"]
        report["fingerprint"] = fingerprint(report)
        self.records.put("review_report", report["fingerprint"], report)
        decisions = self.records.find("review_decisions:" + kind + ":" + identity, limit=1)
        report = dict(report)
        report["human_status"] = "UNREVIEWED"
        if decisions:
            report["human_status"] = decisions[0]["decision"] if decisions[0]["report_fingerprint"] == report["fingerprint"] else "STALE"
            report["human_decision"] = decisions[0]
        return report

    def decide(self, kind, identity, expected_fingerprint, decision, note):
        if decision not in {"ACCEPTED", "REJECTED"} or not isinstance(note, str) or len(note) > 2000:
            raise TaskError("REVIEW_DECISION_INVALID")
        report = self.read(kind, identity)
        if report["fingerprint"] != expected_fingerprint:
            raise TaskError("REVIEW_STALE", "执行事实已变化，请重新核对")
        if report["run_status"] not in {"SUCCEEDED", "FAILED", "INTERRUPTED", "CANCELLED"}:
            raise TaskError("REVIEW_NOT_FINISHED")
        if decision == "ACCEPTED" and report["automatic_status"] != "PASS" and not note.strip():
            raise TaskError("REVIEW_NOTE_REQUIRED", "自动核对未通过时，请说明人工验收依据")
        record = {"report_fingerprint": expected_fingerprint, "decision": decision, "note": note,
                  "source": "desktop_user", 'decided_at': datetime.now(timezone.utc).isoformat()}
        self.records.put("review_decisions:" + kind + ":" + identity, str(uuid4()), record)
        return self.read(kind, identity)
