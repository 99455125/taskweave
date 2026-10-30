"""Choose an existing step and explicitly resolve its target dependencies."""
from copy import deepcopy
import inspect
import json
from uuid import uuid4
from nicegui import ui
from taskweave.core.validation import TaskError
from taskweave.core.task_flow import validate_flow, conditional_branches
from taskweave.presentation.flow_editor import find_node


def _bindings(control):
    try:
        value = json.loads(control.value or '')
    except (ValueError, TypeError) as exc:
        raise TaskError('FORM_INVALID', f'输入绑定 JSON 格式无效：{exc}') from exc
    if not isinstance(value, dict):
        raise TaskError('FORM_INVALID', '输入绑定必须是 JSON 对象')
    for key, binding in value.items():
        if not isinstance(binding, dict) or ('ref' in binding and not isinstance(binding['ref'], dict)):
            raise TaskError('FORM_INVALID', f'输入 {key} 的绑定及 ref 必须是 JSON 对象')
    return value


def _destination(flow, parent_id, index, names):
    parent, _ = find_node(flow, parent_id)
    if parent is None or parent['kind'] != 'sequence' or type(index) is not int or not 0 <= index <= len(parent['children']):
        raise TaskError('FLOW_EDITOR_TARGET_INVALID')
    def locate(node, path):
        if node['id'] == parent_id:
            return path
        if node['kind'] == 'sequence':
            children = [(child, path) for child in node['children']]
        elif node['kind'] == 'if':
            children = [(body, [*path, f'分支 {number + 1}' if number < len(node['cases']) else '默认分支'])
                        for number, (_, body) in enumerate(conditional_branches(node))]
        elif node['kind'] in {'loop', 'foreach'}:
            children = [(node['body'], [*path, '条件循环' if node['kind'] == 'loop' else '列表遍历'])]
        else:
            children = []
        for child, labels in children:
            found = locate(child, labels)
            if found:
                return found
        return None
    def label(node):
        return names.get(node.get('step_id'), {'if': '条件分支', 'foreach': '列表遍历',
                         'loop': '条件循环', 'sequence': '步骤分组'}.get(node['kind'], '步骤'))
    children = parent['children']
    previous = label(children[index - 1]) if index else '分组开始'
    following = label(children[index]) if index < len(children) else '分组结束'
    return ' › '.join(locate(flow['root'], ['主流程'])), f'{previous} → 新步骤 → {following}'


def _binding_scope(flow, steps, parent_id, index):
    """Use the actual flow validator to filter references at this insertion slot."""
    probe = deepcopy(flow)
    identity = 'reuse-preview-' + uuid4().hex
    parent, _ = find_node(probe, parent_id)
    parent['children'].insert(index, {'id': identity, 'kind': 'action', 'step_id': identity})
    candidate = {'step_id': identity, 'bindings': {}}
    definitions = [*steps, candidate]
    def accepts(binding):
        candidate['bindings'] = {'value': binding}
        try:
            validate_flow(probe, definitions)
        except TaskError as exc:
            if exc.code == 'FLOW_REFERENCE_INVALID':
                return False
            raise
        return True
    return accepts


async def show_step_reuse(controller, *, task_id, parent_id, index, expected_flow, is_current, on_created):
    """Return the dialog; on_created receives the saved new step after success."""
    if not is_current(): return None
    expected_flow = deepcopy(expected_flow)
    tasks = await controller.call('task.list')
    if not is_current(): return None
    target_snapshot = await controller.call('task.flow.describe', task_id=task_id)
    if not is_current(): return None
    if target_snapshot['flow'] != expected_flow:
        raise TaskError('EDIT_CONFLICT', '流程位置已变化，请刷新画布后重新选择插入点')
    target_steps = await controller.call('step.list', task_id=task_id)
    if not is_current(): return None
    target_names = {step['step_id']: step.get('name') or step['step_id'] for step in target_steps}
    destination_path, destination_slot = _destination(expected_flow, parent_id, index, target_names)
    accepts = _binding_scope(expected_flow, target_steps, parent_id, index)
    target_options = {identity: f'{number + 1} · {name}' for number, (identity, name) in enumerate(target_names.items())
                      if accepts({'ref': {'source': 'step', 'step_id': identity, 'pointer': ''}})}
    target_name = next((task['name'] for task in tasks if task['task_id'] == task_id), '当前任务')
    state = {'generation': 0, 'source': None, 'snapshot': None, 'revisions': {},
             'bindings': None, 'source_names': {}, 'loading': False, 'busy': False, 'setting': False}
    with ui.dialog() as dialog, ui.card().classes('tw-step-reuse-dialog w-full max-w-5xl'):
        with ui.column().classes('tw-step-operation-header w-full gap-1'):
            ui.label('从已有步骤复制复用').classes('text-xl font-semibold')
            ui.label(f'复制到：{target_name} · {destination_path}').classes('text-sm font-medium')
            ui.label(destination_slot).classes('text-sm text-gray-600')
        with ui.column().classes('tw-step-operation-body gap-3'):
            ui.label('选择已有步骤，检查依赖后复制代码、输入输出、插件配置及上下文材料。').classes('text-sm')
            task_select = ui.select({task['task_id']: f"{number + 1} · {task['name']}" for number, task in enumerate(tasks)}, value=task_id,
                                    label='来源任务', with_input=True).classes('w-full')
            step_select = ui.select({}, label='来源步骤', with_input=True).classes('w-full')
            preview = ui.column().classes('tw-step-reuse-preview w-full')
        footer = ui.column().classes('tw-step-operation-footer gap-2')
        with footer:
            error = ui.label('').classes('text-negative whitespace-pre-wrap w-full')
            error.set_visibility(False)

        def sync_confirm():
            confirm.set_enabled(state['source'] is not None and not state['loading'] and not state['busy'])

        def empty_preview(message):
            preview.clear()
            with preview:
                ui.label(message).classes('text-gray-600 py-4')

        def show_error(exc):
            error.set_text(str(exc))
            error.set_visibility(True)

        def active(generation):
            return is_current() and not dialog.is_deleted and generation == state['generation']

        async def load_source():
            if state['setting'] or state['busy']: return
            state['generation'] += 1
            generation = state['generation']
            state['source'] = None
            state['loading'] = True
            empty_preview('正在加载来源步骤…')
            sync_confirm()
            error.set_visibility(False)
            selected = step_select.value
            if not selected:
                state['loading'] = False
                empty_preview('请选择来源步骤，查看依赖后再复制。' if step_select.options else '该任务暂无可复用步骤，请选择其他来源任务。')
                sync_confirm()
                return
            try:
                source = await controller.call('step.get', step_id=selected)
                if not active(generation): return
                snapshot = await controller.call('task.flow.describe', task_id=source['task_id'])
                if not active(generation): return
                groups = await controller.call('context.list', step_id=selected)
                if not active(generation): return
                state.update(source=source, snapshot=snapshot,
                             revisions={group['context_id']: group['revision'] for group in groups})
                preview.clear()
                with preview:
                    ui.label(source['name']).classes('text-lg font-semibold')
                    ui.label(f"上下文：{len(groups)} 组 · {sum(len(g['captures']) for g in groups)} 项").classes('text-sm')
                    ui.label('检查目标位置的依赖').classes('font-semibold')
                    ui.label('候选仅显示此位置可引用的前序步骤；完整输入绑定 JSON 是最终提交内容，保存时再次校验。').classes('text-sm text-gray-600')
                    mappings = ui.column().classes('w-full gap-2')
                    with ui.expansion('步骤代码预览', icon='code', value=False).classes('w-full'):
                        ui.code(source['step_content'], language='python').classes('w-full')
                    with ui.expansion('输入输出定义', icon='schema', value=False).classes('w-full'):
                        ui.code(json.dumps({'input_schema': source['input_schema'], 'output_schema': source['output_schema']}, ensure_ascii=False, indent=2), language='json').classes('w-full')
                    with ui.expansion('高级编辑：完整输入绑定 JSON', icon='data_object', value=False).classes('w-full'):
                        ui.label('删除绑定仅移除输入来源，保留输入字段及代码；运行时按既有补录规则供值。').classes('text-sm text-gray-600')
                        binding_control = ui.textarea('目标输入绑定（JSON）', value=json.dumps(source['bindings'], ensure_ascii=False, indent=2)).classes('w-full').props('autogrow')
                    state['bindings'] = binding_control
                    cross_task = source['task_id'] != task_id
                    with mappings:
                        if not source['bindings']:
                            ui.label('此步骤没有依赖绑定，可直接复制。').classes('text-sm text-gray-600')
                        for key, binding in source['bindings'].items():
                            ref = binding.get('ref', {}) if isinstance(binding, dict) else {}
                            source_kind = ref.get('source')
                            if source_kind not in {'step', 'loop', 'branch'}:
                                ui.label(f'输入 {key} · 保留现有绑定（可在 JSON 中修改）').classes('text-sm')
                                continue
                            choices = {'': '尚未解决，请映射或删除依赖', '$delete': '删除依赖绑定'}
                            if source_kind == 'step': choices.update(target_options)
                            elif not cross_task and accepts(binding): choices['$keep'] = '保留当前作用域引用（需在目标位置有效）'
                            selected_value = '' if cross_task else (ref.get('step_id', '') if source_kind == 'step' else '$keep')
                            if selected_value not in choices: selected_value = ''
                            source_label = state['source_names'].get(ref.get('step_id'), '来源步骤') if source_kind == 'step' else {'loop': '循环作用域', 'branch': '分支公共输出'}[source_kind]
                            ui.label(f'输入 {key} · {source_label} {ref.get("pointer", "")}').classes('text-xs text-gray-600')
                            def change(event, key=key, original=deepcopy(binding)):
                                if state['busy']: return
                                try:
                                    values = _bindings(binding_control)
                                    if event.value == '$delete':
                                        values.pop(key, None)
                                    elif event.value:
                                        current = deepcopy(values.get(key, original))
                                        if event.value != '$keep':
                                            if current.get('ref', {}).get('source') != 'step':
                                                current = deepcopy(original)
                                            current['ref']['step_id'] = event.value
                                        values[key] = current
                                    else:
                                        values[key] = deepcopy(original)
                                    binding_control.value = json.dumps(values, ensure_ascii=False, indent=2)
                                    error.set_visibility(False)
                                except TaskError as exc:
                                    show_error(exc)
                            ui.select(choices, value=selected_value, label=f'输入 {key} 的依赖处理', with_input=True, on_change=change).classes('w-full')
            except TaskError as exc:
                if active(generation): show_error(exc)
            finally:
                if generation == state['generation']:
                    state['loading'] = False
                    sync_confirm()

        async def load_task():
            if state['busy']: return
            state['generation'] += 1
            generation = state['generation']
            state.update(source=None, loading=True)
            empty_preview('正在加载来源任务…')
            sync_confirm()
            step_select.disable()
            try:
                steps = await controller.call('step.list', task_id=task_select.value)
                if not active(generation): return
                state['source_names'] = {step['step_id']: step['name'] for step in steps}
                state['setting'] = True
                step_select.set_options({step['step_id']: f"{number + 1} · {step['name']}" for number, step in enumerate(steps)}, value=steps[0]['step_id'] if steps else None)
                state['setting'] = False
                step_select.enable()
                await load_source()
            except TaskError as exc:
                if active(generation): show_error(exc)
            finally:
                if generation == state['generation']:
                    state['loading'] = False
                    step_select.enable()
                    sync_confirm()

        async def submit():
            if state['busy'] or state['loading'] or not dialog.value or dialog.is_deleted: return
            if not is_current():
                show_error('目标编辑位置已变化，请关闭弹窗后重新打开。')
                return
            source = state['source']
            if source is None:
                show_error('请选择可复用的来源步骤。')
                return
            state['busy'] = True
            dialog.props('no-backdrop-dismiss')
            spinner.set_visibility(True)
            saving.set_visibility(True)
            confirm.disable()
            task_select.disable()
            step_select.disable()
            cancel.disable()
            frozen = [(element, element.enabled) for element in preview.descendants()
                      if hasattr(element, 'disable') and hasattr(element, 'enabled')]
            for element, _ in frozen: element.disable()
            try:
                values = _bindings(state['bindings'])
                cross_task = source['task_id'] != task_id
                for key, binding in values.items():
                    ref = binding.get('ref', {}) if isinstance(binding, dict) else {}
                    if ref.get('source') == 'step' and ref.get('step_id') not in target_options:
                        raise TaskError('BINDING_INVALID', f'输入 {key} 的步骤依赖尚未解决，请映射到目标位置可用的前序步骤或删除绑定')
                    if cross_task and ref.get('source') in {'loop', 'branch'} and binding == source['bindings'].get(key):
                        raise TaskError('BINDING_INVALID', f'输入 {key} 的作用域依赖尚未解决，请删除绑定或在 JSON 中配置目标引用')
                created = await controller.call('step.reuse', step_id=source['step_id'], target_task_id=task_id,
                    parent_id=parent_id, index=index, expected_hash=state['snapshot']['definition_hash'],
                    expected_step_hash=source['content_hash'], context_revisions=state['revisions'],
                    target_expected_hash=target_snapshot['definition_hash'], bindings=values)
                dialog.close()
                if is_current():
                    result = on_created(created)
                    if inspect.isawaitable(result): await result
            except TaskError as exc:
                if not dialog.is_deleted: show_error(exc)
            finally:
                state['busy'] = False
                if not dialog.is_deleted:
                    dialog.props(remove='no-backdrop-dismiss')
                    spinner.set_visibility(False)
                    saving.set_visibility(False)
                for element in (confirm, cancel, task_select, step_select):
                    if not element.is_deleted: element.enable()
                for element, enabled in frozen:
                    if not element.is_deleted: element.set_enabled(enabled)
                if not confirm.is_deleted: sync_confirm()

        def source_changed():
            if not state['setting'] and not state['busy']:
                state.update(source=None, loading=True, generation=state['generation'] + 1)
                return load_source()
        def task_changed():
            if not state['busy']:
                state.update(source=None, loading=True, generation=state['generation'] + 1)
                return load_task()
        task_select.on_value_change(task_changed)
        step_select.on_value_change(source_changed)
        def cancel_dialog():
            if not state['busy']:
                dialog.close()

        with footer, ui.row().classes('w-full justify-end gap-2'):
            spinner = ui.spinner(size='sm')
            spinner.set_visibility(False)
            saving = ui.label('正在保存，关闭窗口不会取消已提交的操作').classes('text-sm text-gray-600')
            saving.set_visibility(False)
            cancel = ui.button('取消', on_click=cancel_dialog).props('outline')
            confirm = ui.button('确认复用', on_click=submit).props('unelevated color=primary')
        await load_task()
    if not is_current(): return None
    dialog.open()
    return dialog
