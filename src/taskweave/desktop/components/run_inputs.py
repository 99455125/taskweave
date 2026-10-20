"""Pause-time required input collection dialog."""

import json
from nicegui import ui
from taskweave.core.validation import TaskError
from taskweave.presentation.inputs import RunInputs, InputSubmission, request_key, missing_required


def raw_values(value_form):
    """Legacy adapter; live input dialogs submit their event-owned draft."""
    from taskweave.presentation.inputs import decode_raw_values
    return decode_raw_values({name: control.value for name, (_, control) in value_form.controls.items()},
                             {name: kind for name, (kind, _) in value_form.controls.items()})


def input_validation(form, scope, required_schema, editable_schema=None):
    """Compatibility adapter for legacy form callers; live dialogs use their draft."""
    from taskweave.presentation.debug import TrialInputDraft
    draft = TrialInputDraft()
    for target, value_form, schema in ((draft.task, form.task_form, required_schema if scope == 'task' else {}),
                                      (draft.step, form.step_form, editable_schema or (required_schema if scope == 'step' else {}))):
        target.configure(schema, {})
        for name, (_, control) in value_form.controls.items():
            target.change(name, control.value)
    return InputSubmission({}, None, {'scope': scope, 'schema': required_schema, 'step_id': None}, draft, editable_schema).issues()


class RunInputDialog:
    def __init__(self, controller, state, button, trial_variables, content, *, identity,
                 apply_inputs, invalidate_signatures):
        self.controller, self.state, self.button = controller, state, button
        self.trial_variables, self.content = trial_variables, content
        self.identity, self.apply_inputs = identity, apply_inputs
        self.invalidate_signatures = invalidate_signatures
        if not hasattr(state, 'drafts'):
            state.drafts = {}
        self.interaction = RunInputs(controller, state.drafts, identity)

    async def resume_inputs(self, run, values, step_inputs=None, *, expected_identity=None, expected_request=None):
        run_id = run['run_id']
        identity = expected_identity if expected_identity is not None else self.identity(run_id)
        result = None
        async for result in self.interaction.resume_events(
                run_id, values, step_inputs, expected_identity=identity, expected_request=expected_request):
            if result.phase == 'accepted' and result.current:
                applied = self.apply_inputs(result.waiting, values, identity)
                if hasattr(applied, '__await__'):
                    await applied
        if result is None or not result.current or self.identity(run_id) != identity:
            return False
        invalidated = self.invalidate_signatures(identity)
        if hasattr(invalidated, '__await__'):
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
            if self.identity(run['run_id']) != identity or not self.interaction.begin_open():
                return
            try:
                # Re-read at the explicit action: the waiting request may have changed.
                latest = await self.controller.run_request(run['run_id'])
                if self.identity(run['run_id']) != identity or not latest.get('waiting_input'):
                    return
                await self._open(run, latest['waiting_input'], identity)
            finally:
                self.interaction.end_open()
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
            if waiting.get('execution_path'):
                from taskweave.desktop.components.execution_details import round_label
                ui.label(round_label(waiting['execution_path'])).classes('text-sm text-gray-500')
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

            submission = self.interaction.bind(run['run_id'], waiting, form.input_draft, editable_schema)
            def remember(_=None):
                submission.remember()

            async def resume():
                if self.identity(run['run_id']) != identity or not self.interaction.begin_submit(key):
                    return
                submit.disable()
                remember()
                failure = None
                try:
                    values, step_inputs = submission.submission()
                    completed = await self.resume_inputs(
                        run, values, step_inputs=step_inputs, expected_identity=identity, expected_request=key,
                    )
                    if completed and self.identity(run['run_id']) == identity:
                        dialog.close()
                    elif self.identity(run['run_id']) == identity:
                        failure = '补参请求已变化，请关闭后重新打开。输入草稿已保留。'
                except (TaskError, ValueError, TypeError) as exc:
                    failure = str(exc)
                finally:
                    self.interaction.end_submit(key)
                    if not submit.is_deleted:
                        update_submit()
                        if failure:
                            validation_hint.text = failure
            with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                submit = ui.button('提交输入并继续', on_click=resume).props('outline')
                ui.button('稍后填写', on_click=dialog.close).props('outline')
            validation_hint = ui.label().classes('text-sm text-red-700')
            def update_submit(_=None):
                issues = submission.issues()
                if not issues and key not in self.interaction.submitting:
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
