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


def request_key(run_id, waiting):
    """Business request identity, independent of page renders and selection."""
    return (run_id, waiting.get('id'), waiting['scope'], waiting.get('step_id'))


class RunInputDialog:
    def __init__(self, controller, state, button, trial_variables, content, *, identity,
                 apply_inputs, invalidate_signatures):
        self.controller, self.state, self.button = controller, state, button
        self.trial_variables, self.content = trial_variables, content
        self.identity, self.apply_inputs = identity, apply_inputs
        self.invalidate_signatures = invalidate_signatures
        self._opening = False
        self._submitting = set()
        if not hasattr(state, 'drafts'):
            state.drafts = {}

    async def resume_inputs(self, run, values, step_inputs=None, *, expected_identity=None, expected_request=None):
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
        if expected_request is not None and request_key(run_id, waiting) != expected_request:
            return False
        from taskweave.core.validation import validate
        validate(values, waiting["schema"])
        await self.controller.call(
            "run.inputs", run_id=run_id, command_id=command_id(), inputs=values,
            **({"step_inputs": step_inputs} if step_inputs is not None else {}),
            **({"expected_input_id": waiting['id']} if expected_request is not None and waiting.get('id') else {}),
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
        self.state.drafts.pop(request_key(run_id, waiting), None)
        if self.identity(run_id) != identity:
            return False
        invalidated = self.invalidate_signatures(identity)
        if hasattr(invalidated, "__await__"):
            await invalidated
        return True

    async def show(self, run):
        """Offer a manual entry; viewing/polling a paused run never opens a modal."""
        if self.state.dialog_token and self.state.dialog_token[-1] != self.identity((run or {}).get('run_id')):
            self.dismiss()
        if not run or run['status'] != 'PAUSED':
            self.dismiss()
            return
        identity = self.identity(run['run_id'])
        request = await self.controller.run_request(run['run_id'])
        if self.identity(run['run_id']) != identity:
            return
        waiting = request.get('waiting_input')
        if not waiting:
            self.dismiss()
            return
        key = request_key(run['run_id'], waiting)
        if self.state.dialog_token and self.state.dialog_token[:-1] != key:
            self.dismiss()
        async def open_requested():
            if self._opening or self.identity(run['run_id']) != identity:
                return
            self._opening = True
            try:
                # Re-read at the explicit action: the waiting request may have changed.
                latest = await self.controller.run_request(run['run_id'])
                if self.identity(run['run_id']) != identity or not latest.get('waiting_input'):
                    return
                await self._open(run, latest['waiting_input'], identity)
            finally:
                self._opening = False
        self.button('补充必录参数', open_requested, primary=True)

    def dismiss(self):
        """Close on navigation, retaining event-captured drafts for this request."""
        if self.state.dialog is not None and not self.state.dialog.is_deleted:
            self.state.dialog.close()

    async def _open(self, run, waiting, identity):
        key = request_key(run['run_id'], waiting)
        token = (*key, identity)
        if self.state.dialog_token == token and self.state.dialog and not self.state.dialog.is_deleted:
            self.state.dialog.open()
            return
        previous_dialog = self.state.dialog
        if previous_dialog is not None and not previous_dialog.is_deleted:
            previous_dialog.delete()
        # The content/detail area is periodically cleared. Own the dialog on the
        # stable client layout, so refresh cannot delete it while editing.
        with ui.context.client.layout:
            dialog = ui.dialog()
        with dialog, ui.card().classes('w-full max-w-xl'):
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
            draft = self.state.drafts.get(key, {})
            form.apply_task_values(draft.get('task', {}))
            form.apply_step_values(draft.get('step', {}))

            def remember(_=None):
                self.state.drafts[key] = {
                    'task': {name: control.value for name, (_, control) in form.task_form.controls.items()},
                    'step': {name: control.value for name, (_, control) in form.step_form.controls.items()},
                }
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
                if key in self._submitting or self.identity(run['run_id']) != identity:
                    return
                self._submitting.add(key)
                submit.disable()
                remember()
                failure = None
                try:
                    step_inputs = None
                    if waiting['scope'] == 'task':
                        from taskweave.core.validation import validate
                        validate(form.step_values(), {**editable_schema, 'additionalProperties': True})
                        step_inputs = {current['step_id']: form.step_values()}
                    completed = await self.resume_inputs(
                        run, form.task_values() if waiting['scope'] == 'task' else form.step_values(),
                        step_inputs=step_inputs, expected_identity=identity, expected_request=key,
                    )
                    if completed and self.identity(run['run_id']) == identity:
                        dialog.close()
                    elif self.identity(run['run_id']) == identity:
                        failure = '补参请求已变化，请关闭后重新打开。输入草稿已保留。'
                except (TaskError, ValueError, TypeError) as exc:
                    failure = str(exc)
                finally:
                    self._submitting.discard(key)
                    if not submit.is_deleted:
                        update_submit()
                        if failure:
                            validation_hint.text = failure
            with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                submit = ui.button('提交输入并继续', on_click=resume).props('outline')
                ui.button('稍后填写', on_click=dialog.close).props('outline')
            validation_hint = ui.label().classes('text-sm text-red-700')
            def update_submit(_=None):
                issues = input_validation(form, waiting['scope'], waiting['schema'], editable_schema)
                if not issues and key not in self._submitting:
                    submit.enable()
                    validation_hint.text = ''
                else:
                    submit.disable()
                    missing = [issue for issue in issues if issue in (waiting['schema'].get('required', []) + (editable_schema or {}).get('required', []))]
                    validation_hint.text = ('请补充必填字段：' + '、'.join(missing)) if missing else ('输入格式不正确：' + '；'.join(issues))
            for value_form in (form.task_form, form.step_form):
                for _, control in value_form.controls.values():
                    if hasattr(control, 'on_value_change'):
                        control.on_value_change(remember)
                        control.on_value_change(update_submit)
            update_submit()
        if self.identity(run['run_id']) != identity:
            dialog.delete()
            return
        self.state.dialog_token, self.state.dialog = token, dialog
        dialog.open()
