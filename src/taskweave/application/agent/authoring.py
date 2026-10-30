"""Freeze selected external authoring materials without another model call."""

from copy import deepcopy
from dataclasses import asdict

from taskweave.application.agent.projection import contract_projection, snapshot_view
from taskweave.application.prompts import DOMAIN_RULES, EXECUTABLE_STEP_RULES
from taskweave.core.task_package import STEP_DOCUMENT_SCHEMA, TASK_PACKAGE_SCHEMA
from taskweave.core.task_flow import FLOW_VERSION, MAX_DEPTH, MAX_ITERATIONS
from taskweave.core.validation import SAFE_BUILTINS, TaskError, fingerprint, normalize_step


FLOW_GUIDE = {
    "version": FLOW_VERSION, "max_depth": MAX_DEPTH, "max_iterations": MAX_ITERATIONS,
    "nodes": {
        "sequence": {"id": "root", "kind": "sequence", "children": []},
        "action": {"id": "action-node", "kind": "action", "step_id": "existing-step-id-or-package-key"},
        "if": {"id": "branch", "kind": "if", "parallel": False,
               "cases": [{"id": "match", "condition": {"op": "eq", "left": {"literal": 1}, "right": {"literal": 1}},
                          "body": {"id": "yes", "kind": "sequence", "children": []}}],
               "default": {"id": "fallback", "body": {"id": "no", "kind": "sequence", "children": []}}},
        "foreach": {"id": "items", "kind": "foreach", "items": {"ref": {"source": "task", "pointer": "/items"}},
                    "max_items": 1000, "body": {"id": "body", "kind": "sequence", "children": []}},
        "loop": {"id": "repeat", "kind": "loop", "mode": "while", "max_iterations": 100,
                 "condition": {"op": "eq", "left": {"literal": 1}, "right": {"literal": 2}},
                 "state_initial": {}, "state_update": {},
                 "body": {"id": "body", "kind": "sequence", "children": []}},
    },
    "rules": [
        "flow 顶层为 version/root；root 为 sequence；节点 id 唯一，每个动作步骤只放置一次。",
        "if 使用 cases/default 分支；parallel=false 取首个匹配分支，parallel=true 执行全部匹配分支，没有匹配时执行 default；loop.mode 为 while 或 until，循环上限显式配置。",
        "操作数为 literal 或 ref；ref.source 为 task/environment/step/loop/branch，pointer 为 JSON Pointer。",
        "loop ref 必须给所属 node_id 与 field=item/index/state；只能引用当前作用域已完成的动作。",
        "条件 op 为 eq/ne/gt/gte/lt/lte/contains、exists/empty、all/any/not；缺失不是 null，true 不是数字。",
        "循环外读取体内动作得到按轮次排列的聚合，嵌套保留层级，跳过位置为 null 并保留跳过事实。",
        "分支外消费分支结果需声明公共输出或明确处理缺失；具体保存必须通过 task.flow.save 的现行校验。",
        "控制流改变需要整体确认；试跑一条分支不等于其他分支已验证。",
    ],
    'conditions': {
        'all': {'op': 'all', 'conditions': [{'op': 'exists', 'value': {'literal': 1}}]},
        'any': {'op': 'any', 'conditions': [{'op': 'empty', 'value': {'literal': []}}]},
        'not': {'op': 'not', 'condition': {'op': 'eq', 'left': {'literal': 1}, 'right': {'literal': 2}}},
        'exists': {'op': 'exists', 'value': {'literal': None}},
        'empty': {'op': 'empty', 'value': {'literal': []}},
        'binary': {'op': 'eq', 'left': {'literal': 1}, 'right': {'literal': 1}},
    },
    'operands': {
        'literal': {'literal': 'any JSON value'},
        'task': {'ref': {'source': 'task', 'pointer': '/field'}},
        'environment': {'ref': {'source': 'environment', 'pointer': '/field'}},
        'step': {'ref': {'source': 'step', 'step_id': 'completed-step', 'output': 'data', 'pointer': '/field'}},
        'loop': {'ref': {'source': 'loop', 'node_id': 'enclosing-loop', 'field': 'item', 'pointer': ''}},
        'branch': {'ref': {'source': 'branch', 'node_id': 'preceding-branch', 'output': 'value', 'pointer': ''}},
    },
    'branch_outputs': {'outputs': {'value': {'match': {'literal': 1}, 'fallback': {'literal': 2}}}},
    'notes': ['all/any 的 conditions 必须为非空列表；not 使用 condition；exists/empty 使用 value；二元比较使用 left/right。',
              '条件循环 state_initial/state_update 为变量名到操作数的映射；while 在循环体前判断，until 在体后判断。',
              'step ref 的 item_pointer 与 loop_node_id 可选择嵌套循环项；采用执行器现行作用域校验。'],
}


class ExternalAuthoring:
    def __init__(self, app, records, discovery, sanitize):
        self.app, self.records, self.discovery, self.sanitize = app, records, discovery, sanitize

    def baseline(self, kind, identity):
        if kind == "step":
            step = self.app.steps.get(identity)
            return {"kind": kind, "identity": identity, "hash": step["content_hash"],
                    "task_id": step["task_id"],
                    "definition_hash": self.app.tasks.definition_hash(step["task_id"])}
        if kind == "task":
            return {"kind": kind, "identity": identity,
                    "hash": self.app.tasks.definition_hash(identity)}
        if kind == "plan":
            return {"kind": kind, "identity": identity, "hash": self.app.planning.get(identity)["revision"]}
        raise TaskError("AGENT_KIND_INVALID")

    def materials(self, params):
        allowed = {"task_id", "step_id", "plan_id", "capability_ids", "context_ids", "environment_id"}
        if not isinstance(params, dict) or set(params) - allowed:
            raise TaskError("AGENT_ARGUMENT_INVALID")
        owners = [(kind, params[kind + "_id"]) for kind in ("task", "step", "plan") if params.get(kind + "_id")]
        if len(owners) != 1:
            raise TaskError("AGENT_ARGUMENT_INVALID", "材料必须指定一个任务、步骤或规划")
        kind, identity = owners[0]
        baseline = self.baseline(kind, identity)
        step = self.app.steps.get(identity) if kind == "step" else None
        selected = params.get("capability_ids", step["capabilities"] if step else [])
        if not isinstance(selected, list) or any(not isinstance(key, str) for key in selected) or len(selected) > 40:
            raise TaskError("AGENT_ARGUMENT_INVALID", "按需选择最多40项能力")
        contexts = params.get("context_ids", [])
        if not isinstance(contexts, list) or any(not isinstance(key, str) for key in contexts) or len(contexts) > 20:
            raise TaskError("AGENT_ARGUMENT_INVALID")
        if contexts and kind == "task":
            raise TaskError("AGENT_ARGUMENT_INVALID", "请在所属步骤或规划中选择材料")
        source = self.app.contexts.ai_records(identity) if kind == "step" and contexts else (
            self.app.planning.contexts.context_records(identity) if kind == "plan" and contexts else [])
        groups = [group for group in source if group["context_id"] in contexts]
        if {group["context_id"] for group in groups} != set(contexts):
            raise TaskError("AGENT_CONTEXT_SCOPE_INVALID")
        # Textual materials only; preview/image sending is a separate explicit choice.
        groups = deepcopy(groups)
        for group in groups:
            for capture in group.get("captures", []):
                capture.pop("views", None)
                capture.pop("preview_items", None)
        detail = self.discovery.describe(kind, identity, sections=["summary", "schemas", "flow"])
        material = {
            "baseline": baseline, "target": detail,
            "instructions": DOMAIN_RULES + "\n" + EXECUTABLE_STEP_RULES,
            "runtime": {"entrypoint": "async def run(ctx, inputs)", "content_format": "python-async-v1",
                        "api": ["await ctx.call(action_id, inputs)", "ctx.result(data=None, outputs=(), views=())",
                                "ctx.output(handler_id, name, payload)", "ctx.log(message)", "ctx.cancelled()"],
                        "builtins": sorted(SAFE_BUILTINS)},
            "step_schema": STEP_DOCUMENT_SCHEMA,
            "task_package_schema": TASK_PACKAGE_SCHEMA,
            "flow": FLOW_GUIDE,
            "capabilities": [self.discovery.describe("capability", key, sections=["schemas"]) for key in selected],
            "plugins": [{"id": plugin.manifest()["id"], **asdict(contribution),
                         'context_requests': plugin.manifest().get('context_requests', {}),
                         'config_variables': plugin.manifest().get('config_variables', [])}
                        for plugin, contribution in zip(self.app.registry.selected_plugins(selected), self.app.registry.contributions(selected))],
            "contexts": groups,
        }
        if step:
            material["current_document"] = normalize_step(step)
            material["variables"] = self.app.authoring._variable_catalog(step, params.get("environment_id"))
        material = contract_projection(material, self.sanitize)
        material["bundle_id"] = fingerprint(material)
        self.records.put("bundle", material["bundle_id"], material)
        return snapshot_view(material, material["bundle_id"])

    def check_bundle(self, bundle_id, params, operation):
        material = self.records.get("bundle", bundle_id)
        baseline = material["baseline"]
        if self.baseline(baseline["kind"], baseline["identity"]) != baseline:
            raise TaskError("AGENT_BUNDLE_STALE", "编写材料对应的定义已变化，请重新获取")
        target_key = baseline["kind"] + "_id"
        if target_key in params and params[target_key] != baseline["identity"]:
            raise TaskError("AGENT_BUNDLE_SCOPE_INVALID")
        if baseline["kind"] == "step":
            owner = params.get("task_id")
            if params.get("step_id"):
                owner = self.app.steps.get(params["step_id"])["task_id"]
            if owner != baseline["task_id"]:
                raise TaskError("AGENT_BUNDLE_SCOPE_INVALID")
        elif target_key not in params and not (baseline["kind"] == "plan" and operation == "task.import"):
            raise TaskError("AGENT_BUNDLE_SCOPE_INVALID")
