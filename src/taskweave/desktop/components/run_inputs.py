"""Pause-time required input collection dialog."""

import json
from nicegui import ui
from taskweave.core.validation import TaskError
from taskweave.desktop.controller import command_id


def raw_values(value_form):
    values = {}
    for name, (kind, control) in value_form.controls.items():
        value = control.value
        if value is None or value == "":
            continue
        if kind in {"object", "array"}:
            try:
                value = json.loads(value)
            except (ValueError, TypeError):
                pass
        values[name] = value
    return values


def missing_required(schema, values):
    if schema is None:
        return []
    return [key for key in schema.get("required", []) if key not in values or values[key] in (None, "")]


def input_validation(form, scope, required_schema, editable_schema=None):
    from taskweave.core.validation import validate
    try:
        values = form.task_values() if scope == "task" else form.step_values()
        validate(values, required_schema)
        if scope == "task" and editable_schema is not None:
            validate(form.step_values(), {**editable_schema, "additionalProperties": True})
        return []
    except (TaskError, ValueError, TypeError) as exc:
        value_form = form.task_form if scope == "task" else form.step_form
        missing = missing_required(required_schema, raw_values(value_form))
        if scope == "task" and editable_schema is not None:
            missing.extend(missing_required(editable_schema, raw_values(form.step_form)))
        return missing or [str(exc)]


class RunInputDialog:
    def __init__(self, controller, state, button, trial_variables, content, *, identity,
                 apply_inputs, invalidate_signatures):
        self.controller, self.state, self.button = controller, state, button
        self.trial_variables, self.content = trial_variables, content
        self.identity, self.apply_inputs = identity, apply_inputs
        self.invalidate_signatures = invalidate_signatures

    async def resume_inputs(self, run, values, step_inputs=None, *, expected_identity=None):
        """Validate and resume a paused run while its opening page identity remains current."""
        run_id = run["run_id"]
        identity = expected_identity if expected_identity is not None else self.identity(run_id)
        if self.identity(run_id) != identity:
            return False
        request = await self.controller.run_request(run_id)
        if self.identity(run_id) != identity:
            return False
        waiting = request.get("waiting_input")
        if not waiting:
            return False
        from taskweave.core.validation import validate
        validate(values, waiting["schema"])
        await self.controller.call(
            "run.inputs", run_id=run_id, command_id=command_id(), inputs=values,
            **({"step_inputs": step_inputs} if step_inputs is not None else {}),
        )
        if self.identity(run_id) == identity:
            applied = self.apply_inputs(waiting, values, identity)
            if hasattr(applied, "__await__"):
                await applied
        command = request.get("last_command", {})
        await self.controller.call(
            "run.start", run_id=run_id, command_id=command_id(),
            mode=command.get("mode", "ALL"), target_step_id=command.get("target"),
        )
        if self.identity(run_id) != identity:
            return False
        invalidated = self.invalidate_signatures(identity)
        if hasattr(invalidated, "__await__"):
            await invalidated
        return True

    async def show(self, run):
        if not run or run['status'] != 'PAUSED':
            return
        identity = self.identity(run['run_id'])
        request = await self.controller.run_request(run['run_id'])
        if self.identity(run['run_id']) != identity:
            return
        waiting = request.get('waiting_input')
        if not waiting:
            return
        token = (run['run_id'], waiting.get('id'), waiting['scope'], waiting.get('step_id'), identity)
        if self.state.dialog_token == token and self.state.dialog and not self.state.dialog.is_deleted:
            self.button('补充必录参数', self.state.dialog.open, primary=True)
            return
        previous_dialog = self.state.dialog
        if previous_dialog is not None and not previous_dialog.is_deleted:
            previous_dialog.delete()
        self.state.dialog_token = token
        with (self.content() or ui.column()):
            dialog = ui.dialog()
        with dialog, ui.card().classes('w-full max-w-xl'):
            self.state.dialog = dialog
            title = '任务运行输入' if waiting['scope'] == 'task' else '当前步骤输入'
            ui.label(title + ' · 补充必录参数').classes('font-medium')
            definition = json.loads(run['definition_json'])['steps']
            current = next(step for step in definition if step['step_id'] == waiting['step_id'])
            environment = type('FixedEnvironment', (), {'value': run['environment_id'], 'on_value_change': lambda *args: None})()
            form = await self.trial_variables(current, environment, run=run, focus=None if waiting['scope'] == 'task' else 'step', readonly_other=waiting['scope'] != 'task')
            if self.identity(run['run_id']) != identity:
                dialog.delete()
                return
            if waiting['scope'] == 'task':
                form.apply_task_values(waiting['values'])
            else:
                form.apply_step_values(waiting['values'])
            editable_schema = None
            if waiting['scope'] == 'task':
                editable_schema = {
                    **current['input_schema'],
                    'properties': {
                        key: spec for key, spec in current['input_schema'].get('properties', {}).items()
                        if key not in current['bindings']
                    },
                    'required': [key for key in current['input_schema'].get('required', []) if key not in current['bindings']],
                }

            async def resume():
                step_inputs = None
                if waiting['scope'] == 'task':
                    from taskweave.core.validation import validate
                    validate(form.step_values(), {**editable_schema, 'additionalProperties': True})
                    step_inputs = {current['step_id']: form.step_values()}
                completed = await self.resume_inputs(
                    run, form.task_values() if waiting['scope'] == 'task' else form.step_values(),
                    step_inputs=step_inputs, expected_identity=identity,
                )
                if completed and self.identity(run['run_id']) == identity:
                    dialog.close()
            with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                submit = ui.button('提交输入并继续', on_click=resume).props('outline')
                ui.button('稍后填写', on_click=dialog.close).props('outline')
            validation_hint = ui.label().classes('text-sm text-red-700')
            def update_submit(_=None):
                issues = input_validation(form, waiting['scope'], waiting['schema'], editable_schema)
                if not issues:
                    submit.enable()
                    validation_hint.text = ''
                else:
                    submit.disable()
                    missing = [issue for issue in issues if issue in (waiting['schema'].get('required', []) + (editable_schema or {}).get('required', []))]
                    validation_hint.text = ('请补充必填字段：' + '、'.join(missing)) if missing else ('输入格式不正确：' + '；'.join(issues))
            for value_form in (form.task_form, form.step_form):
                for _, control in value_form.controls.values():
                    if hasattr(control, 'on_value_change'):
                        control.on_value_change(update_submit)
            update_submit()
        self.button('补充必录参数', dialog.open, primary=True)
        dialog.open()
