"""External AI entry points share existing use cases and command semantics."""

import json
from copy import deepcopy

from taskweave.application.agent.authoring import ExternalAuthoring
from taskweave.application.agent.discovery import AgentDiscovery
from taskweave.application.agent.execution import AgentExecution
from taskweave.application.agent.review import AgentReview, review_contract
from taskweave.application.agent.projection import bounded, fields, contract_projection, textual_evidence, review_view, page, compact_record
from taskweave.application.agent.projection import contextual_value
from taskweave.core.agent_ports import AgentRecords
from taskweave.core.validation import TaskError, fingerprint, validate


LOCAL_EXECUTION = frozenset({"run.create", "step.confirm", "step.confirm.manual", "task.flow.confirm", "sequence.start"})
REPLAYABLE = frozenset({"step.trial", "step.trial.flow", "run.start", "run.inputs", "run.restart",
                        "run.control", "run.reconcile", "sequence.start"})
COMMAND_OPERATIONS = (REPLAYABLE - {"sequence.start"}) | {
    "instance.end", "sequence.run.inputs", "sequence.run.retry", "sequence.run.reconcile",
    "sequence.pause", "sequence.cancel", "sequence.continue",
}


def mutation_summary(result):
    if not isinstance(result, dict):
        return result
    names = ("task_id", "step_id", "run_id", "sequence_id", "sequence_run_id", "plan_id", "generation_id",
             "context_id", "attempt_id", "content_hash", "definition_hash", "revision", "name", "status",
             "validation_state", "validation_source", "flow_validation_state", "valid", "diagnostics",
             "deleted", "command_id", "requested", "decision")
    selected = fields(result, names)
    return selected or result


class AgentService:
    def __init__(self, app, records: AgentRecords, sanitize):
        self.app, self.records, self.sanitize = app, records, sanitize
        self.discovery = AgentDiscovery(app)
        self.authoring = ExternalAuthoring(app, records, self.discovery, sanitize)
        self.execution = AgentExecution(app, records, self.discovery, sanitize)
        self.reviews = AgentReview(app, records)

    def _public(self, result, *, contracts=False, include_images=False):
        if not include_images:
            result = textual_evidence(result)
        return bounded(contract_projection(result, self.sanitize) if contracts else self.sanitize(result))

    def discover(self, kind, query="", cursor=None, limit=20):
        return self._public(self.discovery.discover(kind, query, cursor, limit))

    def describe(self, kind, identity, sections=None):
        return self._public(self.discovery.describe(kind, identity, sections), contracts=True)

    def _baseline(self, operation, params, expected_hash):
        if operation in {"task.update", "step.reorder"}:
            if not expected_hash:
                raise TaskError("AGENT_BASELINE_REQUIRED")
            if self.app.tasks.describe_flow(params["task_id"])["definition_hash"] != expected_hash:
                raise TaskError("EDIT_CONFLICT")
        if operation in {"step.save", "step.delete"} and params.get("step_id"):
            baseline = params.get("expected_hash", expected_hash)
            if not baseline:
                raise TaskError("AGENT_BASELINE_REQUIRED")
            if self.app.steps.get(params["step_id"])["content_hash"] != baseline:
                raise TaskError("EDIT_CONFLICT")

    def author(self, operation, params, request_id=None, bundle_id=None, expected_hash=None):
        if operation == "materials":
            self.discovery.validate_operation("author", operation, params)
            return self._public(self.authoring.materials(params), contracts=True)
        if operation == "candidate.validate":
            if not isinstance(params, dict) or set(params) != {"package"}:
                raise TaskError("AGENT_ARGUMENT_INVALID")
            normalized = self.app.tasks.validate_package(params["package"], expected_origin="ai_generated")
            diagnostics = normalized.get("diagnostics", [])
            return self._public({"valid": not any(item.get("severity", "error") == "error" for item in diagnostics),
                                 "executable": all(item["document"]["step_content"] for item in normalized["steps"]),
                                 "diagnostics": diagnostics})
        self.discovery.validate_operation("author", operation, params)
        digest = fingerprint({"purpose": "author", "operation": operation, "params": params,
                              "bundle_id": bundle_id, "expected_hash": expected_hash})
        def apply():
            self._baseline(operation, params, expected_hash)
            if bundle_id:
                self.authoring.check_bundle(bundle_id, params, operation)
            if operation == "task.import":
                self.app.tasks.validate_package(params["package"], expected_origin="ai_generated")
            return self.app.dispatch(operation, params)
        with self.app.coordinator.lock:
            result = self.records.atomic(request_id, digest, apply)
        return self._public(mutation_summary(result))

    def _external(self, request_id, digest, operation, replayable=False):
        try:
            previous = self.records.claim(request_id, digest)
        except TaskError as exc:
            if exc.code != "AGENT_REQUEST_UNCERTAIN" or not replayable:
                raise
            previous = None
        if previous is not None:
            if not previous["ok"]:
                raise TaskError(previous["error"]["code"], previous["error"].get("message", ""))
            return previous["value"]
        try:
            result = operation()
        except TaskError as exc:
            self.records.finish(request_id, digest, {"ok": False, "error": exc.document()})
            raise
        self.records.finish(request_id, digest, {"ok": True, "value": result})
        return result

    def context(self, operation, params, request_id=None, include_images=False):
        if type(include_images) is not bool:
            raise TaskError('AGENT_ARGUMENT_INVALID')
        params = dict(params)
        if operation in {"context.read", "context.record", "plan.context.collect", "plan.context.read", "plan.context.record"}:
            params.setdefault("include_view", include_images)
        self.discovery.validate_operation("context", operation, params)
        digest = fingerprint({"purpose": "context", "operation": operation, "params": params})
        result = self._external(request_id, digest, lambda: self.app.dispatch(operation, params))
        try:
            return self._public(result, include_images=include_images)
        except TaskError as exc:
            if exc.code != "AGENT_RESULT_TOO_LARGE":
                raise
            return {"request_id": request_id, "state": "COMPLETED", "truncated": True,
                    "next_action": "inspect_request_pointer"}

    def execute(self, operation, params, request_id, review_spec_id=None):
        if operation == "task.run":
            if review_spec_id is not None:
                params = {**params, "review_spec_id": review_spec_id}
            return self._launch(params, request_id)
        if review_spec_id is not None and operation not in {"run.create", "sequence.start"}:
            raise TaskError("AGENT_ARGUMENT_INVALID", "验收要求只在创建运行时绑定")
        params = dict(params)
        command_id = "agent-" + fingerprint({"request_id": request_id, "operation": operation})
        if operation in COMMAND_OPERATIONS:
            params.setdefault("command_id", command_id)
        if operation == "sequence.start":
            params.setdefault("request_id", command_id)
        self.discovery.validate_operation("execute", operation, params)
        digest = fingerprint({"purpose": "execute", "operation": operation, "params": params, "review_spec_id": review_spec_id})
        def action():
            if operation == "sequence.start":
                result = self.app.sequences.prepare_start(**params)
                self.reviews.bind_sequence_run(result["sequence_run_id"], review_spec_id)
                return result
            if operation == "run.create":
                result = self.app.dispatch(operation, params)
                self.reviews.bind_run(result["run_id"], review_spec_id)
                return result
            if operation == "run.inputs":
                request = self.app.runs.request(params["run_id"])
                command = request.get('last_command', {})
                self.app.dispatch(operation, params)
                return self.app.runs.start(params["run_id"], "continue-" + command_id,
                                           mode=command.get("mode", "ALL"), target_step_id=command.get("target"))
            return self.app.dispatch(operation, params)
        if operation in LOCAL_EXECUTION:
            with self.app.coordinator.lock:
                result = self.records.atomic(request_id, digest, action)
            if operation == "sequence.start":
                self.app.sequences.driver.wake(result["sequence_run_id"])
        else:
            result = self._external(request_id, digest, action, operation in REPLAYABLE)
        return self._public(mutation_summary(result))

    def _launch(self, params, request_id):
        self.discovery.validate_operation("execute", "task.run", params)
        digest = fingerprint({"purpose": "launch", "params": params})
        def create():
            if self.app.tasks.describe_flow(params["task_id"])["definition_hash"] != params["expected_hash"]:
                raise TaskError("EDIT_CONFLICT")
            arguments = {key: value for key, value in params.items() if key not in {"expected_hash", "review_spec_id"}}
            run = self.app.runs.create(**arguments)
            self.reviews.bind_run(run["run_id"], params.get("review_spec_id"))
            return run
        def launch():
            with self.app.coordinator.lock:
                run = self.records.atomic("create-" + fingerprint(request_id), digest, create)
            return self.app.runs.start(run["run_id"], "launch-" + fingerprint(request_id))
        return self._public(mutation_summary(self._external(request_id, digest, launch, replayable=True)))

    def wait(self, identity, kind="run", timeout=30):
        return self._public(self.execution.wait(identity, kind, timeout))

    def inspect(self, kind, identity, sections=None, cursor=None, limit=20, **options):
        include_images = options.pop("include_images", False)
        if type(include_images) is not bool:
            raise TaskError('AGENT_ARGUMENT_INVALID')
        return self._public(self.execution.inspect(kind, identity, sections, cursor, limit, include_images=include_images, **options),
                            contracts=kind in {"bundle", "package", "operation", "operation_result", "task", "step", "capability", "environment", "plan", "sequence"},
                            include_images=include_images)

    def review(self, action, params):
        validate(params, review_contract(action))
        if not isinstance(params, dict):
            raise TaskError('AGENT_ARGUMENT_INVALID')
        if action == 'open':
            if set(params) != {'kind', 'identity'} or params['kind'] not in {'run', 'sequence'}:
                raise TaskError('AGENT_ARGUMENT_INVALID')
            # Resolve existence before opening, and never send a session URL to a model.
            report = self.reviews.read(params['kind'], params['identity'])
            opener = getattr(self, 'review_opener', None)
            if opener is None:
                raise TaskError('REVIEW_UI_UNAVAILABLE', '请在工作台打开相同工作空间，再查看验收')
            opener(params['kind'], params['identity'])
            return {'opened': True, 'review_ref': report['fingerprint']}
        if action == "prepare":
            spec = self.reviews.prepare(**params)
            return self._public({**fields(spec, ("review_spec_id", "target_kind", "target_id", "expected_version", "title")),
                                 "check_count": len(spec["checks"])})
        if action == "read":
            allowed = {"kind", "identity", "sections", "cursor", "limit", "pointer"}
            if not isinstance(params, dict) or set(params) - allowed or not {"kind", "identity"} <= set(params):
                raise TaskError("AGENT_ARGUMENT_INVALID")
            report = self.public_review(self.reviews.read(params["kind"], params["identity"]))
            return self._public(review_view(report, params.get("sections"), params.get("cursor"),
                                            params.get("limit", 10), params.get("pointer")))
        if action == "read_spec":
            if not isinstance(params, dict) or set(params) - {"review_spec_id", "cursor", "limit"} or "review_spec_id" not in params:
                raise TaskError("AGENT_ARGUMENT_INVALID")
            spec = self.records.get("review_spec", params["review_spec_id"])
            spec['checks'] = self.public_checks(spec['checks'])
            paging = page([compact_record(item) for item in spec["checks"]], {"review_spec_id": spec["review_spec_id"]}, params.get("cursor"), params.get("limit", 10))
            return self._public({**fields(spec, ("review_spec_id", "target_kind", "target_id", "expected_version", "title")),
                                 "checks": [compact_record(item) for item in paging.pop("items")], "checks_page": paging})
        raise TaskError("AGENT_OPERATION_DENIED", "工具仅能准备或读取验收，人工决定由桌面交互记录")

    def public_checks(self, checks):
        checks = deepcopy(checks)
        def project_rule(rule, source):
            for key in ('actual', 'expected'):
                if key in rule:
                    rule[key] = contextual_value(rule[key], source, self.execution.safe_document)
            if isinstance(rule.get('check'), dict):
                project_rule(rule['check'], source)
        for check in checks:
            project_rule(check, check['source'])
        return checks

    def public_review(self, report):
        return {**report, 'checks': self.public_checks(report['checks'])}
