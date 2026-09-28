"""Run/debug variable forms and their non-validating environment refresh."""

import json

from nicegui import ui

from taskweave.core.validation import TaskError
from taskweave.desktop.forms import ValueForm


def _draft_edits(form, current=None):
    """Read changed control values without applying submit-time validation."""
    edits = dict(current or {})
    required = set(form.schema.get("required", []))
    for name, (kind, control) in form.controls.items():
        value = control.value
        required_blank = name in required and value in (None, "")
        if name in edits:
            if value == edits[name]:
                continue
            if required_blank:
                edits[name] = value
            elif value == form.defaults.get(name):
                edits.pop(name)
            else:
                edits[name] = value
        elif required_blank or value != form.defaults.get(name):
            edits[name] = value
    return edits


def _apply_draft(form, edits):
    """Restore raw draft values, including incomplete JSON text and blanks."""
    for name, value in edits.items():
        if name not in form.controls:
            continue
        kind, control = form.controls[name]
        if kind in {"object", "array"} and not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False)
        control.value = value


def _capture_draft(form, edits):
    latest = _draft_edits(form, edits)
    edits.clear()
    edits.update(latest)


def _watch_draft(form, edits):
    required = set(form.schema.get("required", []))
    for name, (kind, control) in form.controls.items():
        if not hasattr(control, "on_value_change"):
            continue

        def remember(event, field=name, value_form=form, target=edits):
            value = event.value
            if field in required and value in (None, ""):
                target[field] = value
            elif value == value_form.defaults.get(field):
                target.pop(field, None)
            else:
                target[field] = value

        control.on_value_change(remember)


def _validated_partial_values(form):
    """Allow deferred required values while still validating supplied values."""
    from taskweave.core.validation import validate
    from taskweave.desktop.components.run_inputs import raw_values

    values = raw_values(form)
    validate({**values}, {**form.schema, "required": []})
    for name, (kind, _control) in form.controls.items():
        if kind == "integer" and name in values:
            values[name] = int(values[name])
    return values


class TrialInputPanel:
    def __init__(self, controller, task_id, format_value):
        self.controller, self.task_id, self.format_value = controller, task_id, format_value

    async def render(self, step, environment, values=None, *, run=None, focus=None, readonly_other=False, task_id=None):
        task_id = task_id or (run or {}).get("task_id") or self.task_id()
        current_step = step
        definition = json.loads(run["definition_json"]) if run and run.get("definition_json") else None
        if definition and definition.get("task", {}).get("task_id") == task_id:
            task_schema = json.loads(definition["task"]["input_schema_json"])
        else:
            task = await self.controller.call("task.get", task_id=task_id)
            task_schema = json.loads(task["input_schema_json"])
        area = ui.column().classes("w-full gap-2")
        form = step_form = None
        task_edits, step_edits = {}, {}
        render_sequence = 0

        async def render_environment(selected, sequence):
            nonlocal form, step_form
            environments = await self.controller.call("environment.list")
            if sequence != render_sequence:
                return form
            selected_environment = next((e for e in environments if e["environment_id"] == selected), None)
            env = json.loads(selected_environment["public_config_json"]) if selected_environment else {}
            env_descriptions = json.loads(selected_environment.get("descriptions_json") or "{}") if selected_environment else {}
            defaults = {k: v["default"] for k, v in task_schema.get("properties", {}).items() if "default" in v}
            task_defaults = {**env, **defaults}
            task_values = {**task_defaults, **task_edits}
            area.clear()
            with area:
                with ui.expansion("环境变量 · 只读", icon="public").classes("w-full border rounded"):
                    if not env:
                        ui.label("当前环境未配置变量").classes("text-gray-500")
                    for key, value in env.items():
                        suffix = "（被任务变量覆盖）" if key in defaults or key in task_edits else ""
                        if env_descriptions.get(key):
                            ui.label(env_descriptions[key]).classes("text-xs text-gray-500")
                        ui.label(f"{key} = {self.format_value(value)} · 环境{suffix}").classes("tw-code w-full")
                with ui.expansion("任务变量 · 本次运行输入", icon="edit", value=bool(task_schema.get("required")) and focus in {None, "task"}).classes("w-full border rounded"):
                    form = ValueForm(task_schema, task_defaults)
                    form.defaults = {key: control.value for key, (_, control) in form.controls.items()}
                    _apply_draft(form, task_edits)
                    _watch_draft(form, task_edits)
                    if readonly_other and focus != "task":
                        for _, control in form.controls.values():
                            control.disable()
                with ui.expansion("步骤变量与依赖 · 本次步骤输入", icon="account_tree", value=bool([key for key in current_step["input_schema"].get("required", []) if key not in current_step["bindings"]]) and focus in {None, "step"}).classes("w-full border rounded"):
                    properties = current_step["input_schema"].get("properties", {})
                    if not properties and not current_step["bindings"]:
                        ui.label("此步骤无专用输入或依赖").classes("text-gray-500")
                    editable = {key: spec for key, spec in properties.items() if key not in current_step["bindings"]}
                    step_schema = {**current_step["input_schema"], "properties": editable, "required": [key for key in current_step["input_schema"].get("required", []) if key in editable]}
                    step_defaults = {key: spec["default"] for key, spec in editable.items() if "default" in spec}
                    step_base = {**task_values, **step_defaults}
                    step_form = ValueForm(step_schema, step_base)
                    step_form.defaults = {key: control.value for key, (_, control) in step_form.controls.items()}
                    _apply_draft(step_form, step_edits)
                    _watch_draft(step_form, step_edits)
                    if readonly_other and focus != "step":
                        for _, control in step_form.controls.values():
                            control.disable()

                    def update_step_defaults(_):
                        try:
                            step_form.apply_defaults({**env, **defaults, **form.values()})
                        except TaskError:
                            return  # Incomplete JSON is a draft until submit.

                    for _, control in form.controls.values():
                        if hasattr(control, "on_value_change"):
                            control.on_value_change(update_step_defaults)
                    for key, _spec in properties.items():
                        if key not in current_step["bindings"]:
                            continue
                        binding = current_step["bindings"][key]
                        if "literal" in binding:
                            value, source = binding["literal"], "步骤固定值"
                        else:
                            ref = binding["ref"]
                            source = {"task": "任务引用", "environment": "环境引用", "step": "前序步骤结果"}.get(ref["source"], "步骤引用")
                            if ref["source"] in {"task", "environment"}:
                                from taskweave.core.validation import pointer
                                try:
                                    value = pointer(task_values if ref["source"] == "task" else env, ref["pointer"])
                                except TaskError:
                                    value = "未配置"
                            else:
                                previous_steps = definition["steps"] if definition else await self.controller.call("step.list", task_id=task_id)
                                previous = next((f"{i+1}. {s['name']}" for i, s in enumerate(previous_steps) if s["step_id"] == ref["step_id"]), "未知步骤")
                                value = f"{previous} · {ref.get('output', 'data')}{ref['pointer']}（执行时读取）"
                                try:
                                    from taskweave.core.validation import pointer
                                    result = await self.controller.call("run.output", run_id=run["run_id"], step_id=ref["step_id"], output=ref.get("output", "data")) if run else await self.controller.previous_result(task_id, ref["step_id"], selected, output=ref.get("output", "data"))
                                    value = pointer(result, ref["pointer"])
                                    source = f"前序结果 · {previous}（最近成功结果示例）"
                                except TaskError:
                                    source = f"前序结果 · {previous}（暂无可用结果）"
                        ui.label(f"{key} = {self.format_value(value)} · {source}").classes("tw-code w-full").style("max-height: 10rem; overflow: auto")
            return form

        stored_inputs = await self.controller.execution_inputs(run["run_id"]) if run else None
        supplied_task = stored_inputs["task"] if run else values
        supplied_step = stored_inputs["steps"].get(current_step["step_id"], {}) if run else values
        await render_environment(environment.value or None, render_sequence)
        if supplied_task:
            _apply_draft(form, supplied_task)
        if supplied_step:
            _apply_draft(step_form, supplied_step)

        class TrialInputs:
            async def replace(_, selected, task_values, step_values):
                nonlocal render_sequence
                task_edits.clear()
                task_edits.update(task_values or {})
                step_edits.clear()
                step_edits.update(step_values or {})
                render_sequence += 1
                await render_environment(selected, render_sequence)

            async def refresh(_, new_step, selected, task_values=None, step_values=None):
                nonlocal current_step, render_sequence
                current_step = new_step
                task_edits.clear()
                task_edits.update(task_values or {})
                step_edits.clear()
                step_edits.update(step_values or {})
                render_sequence += 1
                await render_environment(selected, render_sequence)

            def values(_):
                return {**form.values(), **step_form.values()}

            def task_values(_):
                return form.values()

            def step_values(_):
                return step_form.values()

            def task_draft_values(_):
                return _validated_partial_values(form)

            def step_draft_values(_):
                return _validated_partial_values(step_form)

            def task_edits(_):
                return _draft_edits(form, task_edits)

            def step_edits(_):
                return _draft_edits(step_form, step_edits)

            def apply_task_values(_, values):
                _apply_draft(form, values)

            def apply_step_values(_, values):
                _apply_draft(step_form, values)

            @property
            def task_form(_):
                return form

            @property
            def step_form(_):
                return step_form

        proxy = TrialInputs()

        async def change(event):
            nonlocal render_sequence
            if getattr(environment, "_tw_skip_change", False):
                environment._tw_skip_change = False
                return
            _capture_draft(form, task_edits)
            _capture_draft(step_form, step_edits)
            render_sequence += 1
            await render_environment(event.value or None, render_sequence)

        environment.on_value_change(change)
        return proxy
