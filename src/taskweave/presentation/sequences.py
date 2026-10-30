"""Plain draft state for editing ordered task sequences."""

from copy import deepcopy
from uuid import uuid4

from taskweave.core.validation import TaskError
from taskweave.core.sequence_flow import linear_flow, validate_sequence_flow
from taskweave.core.task_flow import conditional_branches
from taskweave.presentation.flow_editor import find_node, move_node, insert_control, update_control, remove_control, _walk


class SequenceDraft:
    def __init__(self):
        self.sequence_id = None
        self.revision = None
        self.name = ""
        self.description = ""
        self.input_schema_text = '{"type":"object","properties":{}}'
        self.launch_inputs_text = "{}"
        self.nodes = []
        self.flow = linear_flow([])
        self.selected_run_id = None
        self._saved = None

    def load(self, definition):
        import json
        self.sequence_id = definition["sequence_id"]
        self.revision = definition["revision"]
        self.name = definition["name"]
        self.description = definition["description"]
        self.input_schema_text = json.dumps(definition["input_schema"], ensure_ascii=False, indent=2)
        self.nodes = deepcopy(definition["nodes"])
        self.flow = deepcopy(definition.get("flow") or linear_flow(self.nodes))
        self._apply(self.flow)
        self._saved = {"name": self.name, "description": self.description,
                       "nodes": deepcopy(self.nodes), "flow": deepcopy(self.flow), "input_schema": deepcopy(definition["input_schema"])}

    def reset(self):
        self.__init__()

    def _apply(self, flow, nodes=None):
        nodes = self.nodes if nodes is None else nodes
        validate_sequence_flow(flow, nodes)
        by_id = {node['node_id']: node for node in nodes}
        ordered = [by_id[node['step_id']] for node, _ in _walk(flow['root']) if node['kind'] == 'action']
        self.flow, self.nodes = flow, ordered

    def add(self, task_id, parent_id="root", index=None):
        if not task_id:
            raise TaskError("SEQUENCE_NODE_INVALID", "请先选择任务")
        flow = deepcopy(self.flow)
        parent, _ = find_node(flow, parent_id)
        if parent is None or parent["kind"] != "sequence":
            raise TaskError("FLOW_EDITOR_TARGET_INVALID")
        index = len(parent['children']) if index is None else index
        if type(index) is not int or not 0 <= index <= len(parent['children']):
            raise TaskError("FLOW_EDITOR_TARGET_INVALID")
        node_id = str(uuid4())
        item = {"node_id": node_id, "task_id": task_id, "environment_id": None, "inputs": {}, "step_inputs": {}}
        parent['children'].insert(index, {'id': node_id, 'kind': 'action', 'step_id': node_id})
        self._apply(flow, [*self.nodes, item])
        return node_id

    def can_move(self, index, direction):
        if not 0 <= index < len(self.nodes):
            return False
        node, parent = find_node(self.flow, self.nodes[index]['node_id'])
        return parent is not None and 0 <= parent['children'].index(node) + direction < len(parent['children'])

    def move(self, index, direction):
        if not self.can_move(index, direction):
            return
        node, parent = find_node(self.flow, self.nodes[index]['node_id'])
        self.move_to(node['id'], parent['id'], parent['children'].index(node) + direction)

    def remove(self, index):
        identity = self.nodes[index]['node_id']
        flow = deepcopy(self.flow)
        node, parent = find_node(flow, identity)
        if parent is None:
            raise TaskError('FLOW_EDITOR_TARGET_INVALID')
        parent['children'].remove(node)
        self._apply(flow, [node for node in self.nodes if node['node_id'] != identity])

    def add_control(self, kind, parent_id="root", index=None):
        flow, identity = insert_control(self.flow, kind, parent_id, index)
        self._apply(flow)
        return identity

    def move_to(self, node_id, parent_id, index=None):
        self._apply(move_node(self.flow, node_id, parent_id, index))

    def update_control(self, node_id, changes):
        self._apply(update_control(self.flow, node_id, changes))

    def remove_control(self, node_id):
        self._apply(remove_control(self.flow, node_id))

    def scope(self, target):
        """Offer sources structurally available at this task/control node."""
        found = {'nodes': set(), 'loops': set(), 'branches': set(), 'aggregates': set()}
        def walk(node, available, loops, branches, aggregates):
            if node['id'] == target or node.get('step_id') == target:
                found.update(nodes=set(available), loops=set(loops), branches=set(branches), aggregates=set(aggregates))
            kind = node['kind']
            if kind == 'action':
                return available | {node['step_id']}, branches, aggregates
            if kind == 'sequence':
                for child in node['children']:
                    available, branches, aggregates = walk(child, available, loops, branches, aggregates)
                return available, branches, aggregates
            if kind == 'if':
                for _, body in conditional_branches(node):
                    walk(body, set(available), loops, set(branches), set(aggregates))
                return available, branches | {node['id']}, aggregates
            inside, inner_branches, inner_aggregates = walk(node['body'], available, loops | {node['id']}, branches, aggregates)
            return inside, inner_branches, inner_aggregates | {node['id']}
        walk(self.flow['root'], set(), set(), set(), set())
        return found

    def payload(self):
        import json
        return {"name": self.name, "description": self.description,
                "nodes": deepcopy(self.nodes), "flow": deepcopy(self.flow), "input_schema": json.loads(self.input_schema_text),
                "sequence_id": self.sequence_id, "expected_revision": self.revision}

    def needs_save(self):
        payload = self.payload()
        return self.sequence_id is None or self._saved != {
            "name": payload["name"], "description": payload["description"],
            "nodes": payload["nodes"], "flow": payload["flow"], "input_schema": payload["input_schema"]}

    def launch_inputs(self):
        import json
        value = json.loads(self.launch_inputs_text)
        if not isinstance(value, dict):
            raise TaskError("INPUT_INVALID", "组合启动输入必须是 JSON 对象")
        return value
