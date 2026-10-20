"""Plain draft state for editing ordered task sequences."""

from copy import deepcopy
from uuid import uuid4

from taskweave.core.validation import TaskError


class SequenceDraft:
    def __init__(self):
        self.sequence_id = None
        self.revision = None
        self.name = ""
        self.description = ""
        self.input_schema_text = '{"type":"object","properties":{}}'
        self.launch_inputs_text = "{}"
        self.nodes = []
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
        self._saved = {"name": self.name, "description": self.description,
                       "nodes": deepcopy(self.nodes), "input_schema": deepcopy(definition["input_schema"])}

    def reset(self):
        self.__init__()

    def add(self, task_id):
        if not task_id:
            raise TaskError("SEQUENCE_NODE_INVALID", "请先选择任务")
        self.nodes.append({"node_id": str(uuid4()), "task_id": task_id,
                           "environment_id": None, "inputs": {}, "step_inputs": {}})

    def move(self, index, direction):
        target = index + direction
        if not 0 <= index < len(self.nodes) or not 0 <= target < len(self.nodes):
            return
        self.nodes[index], self.nodes[target] = self.nodes[target], self.nodes[index]

    def remove(self, index):
        del self.nodes[index]

    def payload(self):
        import json
        return {"name": self.name, "description": self.description,
                "nodes": deepcopy(self.nodes), "input_schema": json.loads(self.input_schema_text),
                "sequence_id": self.sequence_id, "expected_revision": self.revision}

    def needs_save(self):
        payload = self.payload()
        return self.sequence_id is None or self._saved != {
            "name": payload["name"], "description": payload["description"],
            "nodes": payload["nodes"], "input_schema": payload["input_schema"]}

    def launch_inputs(self):
        import json
        value = json.loads(self.launch_inputs_text)
        if not isinstance(value, dict):
            raise TaskError("INPUT_INVALID", "组合启动输入必须是 JSON 对象")
        return value
