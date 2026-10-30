"""Resolve combination values within an exact branch and loop occurrence."""

from taskweave.core.flow_values import aggregate_branch_output, aggregate_output
from taskweave.core.sequence_flow import machine_flow, source_operand
from taskweave.core.validation import TaskError, pointer


class SequenceValues:
    def __init__(self, use_cases, run, cursor, pending=()):
        self.app, self.run, self.cursor = use_cases, run, cursor
        self.flow = machine_flow(run["snapshot"]["flow"])
        by_path = {item["execution_path"]: item for item in run["flow_instances"]}
        by_path.update({item["execution_path"]: item for item in pending})
        self.visits = list(by_path.values())

    def _child_output(self, run_id, name, **projection):
        try:
            step_id, output = name.split("/", 1)
        except ValueError as exc:
            raise TaskError("SEQUENCE_SOURCE_INVALID") from exc
        if output != 'data':
            attempts = [attempt for attempt in self.app.runs.runs.run_details(run_id)['attempts']
                        if attempt['step_id'] == step_id and attempt['valid'] and attempt['status'] == 'SUCCEEDED']
            if not attempts:
                raise TaskError('SEQUENCE_OUTPUT_NOT_JSON')
            for attempt in attempts:
                ref = next((ref for ref in self.app.runs.results.receipt(attempt) or [] if ref.get('name') == output), None)
                if ref is None or ref.get('kind') != 'json':
                    raise TaskError('SEQUENCE_OUTPUT_NOT_JSON')
        return self.app.runs.output(run_id, step_id, output, **projection)

    def read(self, binding, cursor=None):
        cursor = self.cursor if cursor is None else cursor
        if "literal" in binding:
            return binding["literal"]
        # Conditions may use public task-call references, whereas machine
        # callbacks and bindings already use the translated representation.
        binding = machine_flow(binding)
        ref = binding["ref"]
        source = ref["source"]
        frames = cursor.get("frames", [])
        if source == "task":
            value = self.run["inputs"]
        elif source == "loop":
            frame = next((frame for frame in reversed(frames) if frame["node_id"] == ref["node_id"]), None)
            if frame is None:
                raise TaskError("FLOW_REFERENCE_INVALID")
            field = ref["field"]
            value = frame["items"][frame["index"]] if field == "item" else frame["index"] if field == "index" else frame["state"]
        elif source == "step":
            value = aggregate_output(self.flow, self.visits, ref["step_id"], ref["output"], self._child_output,
                                     item_pointer=ref.get("item_pointer"), loop_node_id=ref.get("loop_node_id"), active_frames=frames)
        elif source == "branch":
            def mapped(operand, path, selected):
                historical = []
                for visit in self.visits:
                    if visit["kind"] not in {"foreach", "loop"} or not path.startswith(visit["execution_path"] + "/"):
                        continue
                    index = path[len(visit["execution_path"]) + 1:].split("/", 1)[0]
                    if not index.isdigit():
                        continue
                    frame = {"node_id": visit["node_id"], "kind": visit["kind"], "path": visit["execution_path"], "index": int(index)}
                    if visit["kind"] == "foreach":
                        frame["items"] = visit["payload"]["items"]
                    else:
                        iteration = next((v for v in self.visits if v["execution_path"] == visit["execution_path"] + "/" + index), None)
                        current = next((f for f in frames if f["path"] == visit["execution_path"] and f["index"] == int(index)), None)
                        if iteration is None and current is None:
                            raise TaskError("FLOW_REFERENCE_INVALID")
                        frame["state"] = iteration["payload"]["state_before"] if iteration else current["state"]
                    historical.append(frame)
                return self.read(operand, {**cursor, "frames": [*frames, *historical]})
            value = aggregate_branch_output(self.flow, self.visits, ref["node_id"], ref["output"], mapped, active_frames=frames)
        else:
            raise TaskError("SEQUENCE_SOURCE_INVALID")
        return pointer(value, ref.get("pointer", ""))

    def source(self, source):
        # A child task's own loop projection is distinct from combination
        # aggregation. Preserve existing child output projection when the
        # named loop is inside the referenced child rather than this flow.
        if source.get("kind") == "output" and source.get("item_pointer") is not None:
            known = {item["node_id"] for item in self.visits if item["kind"] in {"foreach", "loop"}}
            known |= {f["node_id"] for f in self.cursor.get("frames", []) if f["kind"] in {"foreach", "loop"}}
            scope = source.get('projection_scope') or ('combination' if source.get('loop_node_id') in known else 'task')
            if scope == 'task':
                value = aggregate_output(self.flow, self.visits, source['node_id'], source['step_id'] + '/' + source['output'],
                    lambda run_id, name: self._child_output(run_id, name, item_pointer=source['item_pointer'], loop_node_id=source['loop_node_id']),
                    active_frames=self.cursor.get('frames', []))
                return pointer(value, source["pointer"])
        return self.read(source_operand(source))
