"""Reviewed step copy/split dialogs over the atomic derivation operations."""
from copy import deepcopy
import ast
import inspect
import json

from nicegui import ui
from taskweave.core.validation import TaskError


def _json_object(control, label):
    try:
        value = json.loads(control.value or '')
    except (ValueError, TypeError) as exc:
        raise TaskError('FORM_INVALID', f'{label} JSON 格式无效：{exc}') from exc
    if not isinstance(value, dict):
        raise TaskError('FORM_INVALID', f'{label}必须是 JSON 对象')
    return value


def _code_selection(code, title):
    area = ui.column().classes('w-full gap-1')
    def refresh():
        area.clear()
        source = code.value or ''
        with area:
            try:
                tree = ast.parse(source)
                functions = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == 'run']
                if len(functions) != 1 or not functions[0].body:
                    raise ValueError('需要一个包含完整语句的 async def run 函数')
                function = functions[0]
                # One-line suites and semicolon statements cannot be separated by
                # line boundaries without destroying a complete Python statement.
                if function.body[0].lineno == function.lineno or any(
                        left.end_lineno >= right.lineno for left, right in zip(function.body, function.body[1:])):
                    raise ValueError('同行语句暂不支持独立勾选，请先在完整代码中将语句分行')
            except (SyntaxError, ValueError) as exc:
                ui.label(f'代码段暂不可选：{exc}。可继续编辑完整代码，再刷新代码段。').classes('text-warning')
                return
            lines = source.splitlines(keepends=True)
            first_node = function.body[0]
            start = min([first_node.lineno] + [node.lineno for node in getattr(first_node, 'decorator_list', [])]) - 1
            finish = function.body[-1].end_lineno
            prefix, suffix = ''.join(lines[:start]), ''.join(lines[finish:])
            segments, previous = [], start
            for node in function.body:
                # Keep comments/blank lines preceding a statement with that segment.
                segments.append(''.join(lines[previous:node.end_lineno]))
                previous = node.end_lineno
            selected = set(range(len(segments)))
            state = {'generated': source, 'restoring': False}
            def choose(event, index):
                if state['restoring']: return
                if code.value != state['generated']:
                    ui.notify('完整代码已有编辑，请先点击“按当前代码刷新代码段”，再选择代码段。', type='warning')
                    state['restoring'] = True
                    event.sender.value = index in selected
                    state['restoring'] = False
                    return
                if event.value: selected.add(index)
                else: selected.discard(index)
                body = ''.join(segment for index, segment in enumerate(segments) if index in selected)
                if not body:
                    indent = lines[start][:len(lines[start]) - len(lines[start].lstrip())]
                    body = indent + 'pass\n'
                state['generated'] = prefix + body + suffix
                code.value = state['generated']
            for index, node in enumerate(function.body):
                end = node.end_lineno
                location = str(node.lineno) if node.lineno == end else f'{node.lineno}–{end}'
                summary = lines[node.lineno - 1].strip()
                summary = summary[:100] + ('…' if len(summary) > 100 else '')
                ui.checkbox(f'{title}代码段 {index + 1} · 第 {location} 行 · {summary}', value=True,
                            on_change=lambda event, i=index: choose(event, i)).props('dense')
    ui.button('按当前代码刷新代码段', on_click=refresh).props('flat dense')
    refresh()


def _schema_selection(control, title, kind, *, bindings=None):
    area = ui.column().classes('w-full gap-1')
    def refresh():
        area.clear()
        with area:
            try:
                schema = _json_object(control, title + kind + ' Schema')
                original_bindings = _json_object(bindings, title + '输入绑定') if bindings else None
            except TaskError as exc:
                ui.label(str(exc) + '；修正 JSON 后可刷新字段选择。').classes('text-warning')
                return
            properties = schema.get('properties')
            if not isinstance(properties, dict) or not properties:
                ui.label(f'{kind} Schema 没有可逐项选择的 properties，请在 JSON 中编辑。').classes('text-sm text-gray-600')
                return
            selected = set(properties)
            state = {'schema': control.value, 'bindings': bindings.value if bindings else None, 'restoring': False}
            def choose(event, key):
                if state['restoring']: return
                if control.value != state['schema'] or (bindings and bindings.value != state['bindings']):
                    ui.notify('Schema 或绑定已有编辑，请先刷新字段选择。', type='warning')
                    state['restoring'] = True
                    event.sender.value = key in selected
                    state['restoring'] = False
                    return
                if event.value: selected.add(key)
                else: selected.discard(key)
                result = deepcopy(schema)
                result['properties'] = {key: value for key, value in properties.items() if key in selected}
                if isinstance(result.get('required'), list):
                    result['required'] = [key for key in result['required'] if key not in properties or key in selected]
                state['schema'] = json.dumps(result, ensure_ascii=False, indent=2)
                control.value = state['schema']
                if bindings:
                    values = {key: value for key, value in original_bindings.items() if key not in properties or key in selected}
                    state['bindings'] = json.dumps(values, ensure_ascii=False, indent=2)
                    bindings.value = state['bindings']
            for key in properties:
                ui.checkbox(f'{title}{kind}字段 · {key}', value=True,
                            on_change=lambda event, key=key: choose(event, key)).props('dense')
            ui.label('字段勾选保留其他 Schema 约束；复杂依赖可在 JSON 中核对和调整。').classes('text-xs text-gray-600')
    ui.button('刷新' + kind + '字段选择', on_click=refresh).props('flat dense')
    refresh()



def _part_header(title, second):
    with ui.row().classes('w-full items-center justify-between'):
        ui.label(title).classes('font-semibold')
        ui.badge('新建并紧随其后' if second else '保留身份与执行记录', color='primary' if second else 'grey-7').props('outline')


def _document(step, form, title):
    result = deepcopy(step)
    result.update(name=(form['name'].value or '').strip(), step_content=form['code'].value or '')
    if not result['name']:
        raise TaskError('FORM_INVALID', title + '名称不能为空')
    for key, control in form['controls'].items():
        result[key] = _json_object(control, control._props['label'])
    return result


async def show_step_derivation(controller, step, *, mode, is_current, on_created):
    """Open a persistent review draft; only submission writes the derivation."""
    if mode not in {'copy', 'split'}:
        raise TaskError('FORM_INVALID', '请选择复制或拆分步骤')
    if not is_current(): return None
    step = deepcopy(step)
    descriptor = await controller.call('task.flow.describe', task_id=step['task_id'])
    if not is_current(): return None
    groups = await controller.call('context.list', step_id=step['step_id'])
    if not is_current(): return None
    revisions = {group['context_id']: group['revision'] for group in groups}
    capture_options = {capture['capture_id']: group['name'] + ' · ' + (capture.get('label') or '采集项')
                       for group in groups for capture in group['captures']}
    action = '复制' if mode == 'copy' else '拆分'
    busy = False
    forms = [{}, {}]
    ui.add_css('''
        .q-card.tw-step-derivation-dialog {width:min(1100px,96vw); max-width:min(1100px,96vw)!important; height:min(900px,90dvh);
          max-height:90dvh!important; display:grid; grid-template-rows:auto minmax(0,1fr) auto;
          padding:0; gap:0; overflow:hidden;}
        .q-card.tw-step-derivation-dialog.tw-step-derivation-copy {height:auto;}
        .tw-step-derivation-header {border-bottom:1px solid #dbe3ed; gap:8px;}
        .tw-step-derivation-body {min-height:0; height:100%; max-height:100%; align-self:stretch; overflow:auto; width:100%;}
        .tw-step-derivation-body .q-tab-panel {padding:0; overflow:visible;}
        .tw-step-derivation-part {box-shadow:none; border:1px solid #dbe3ed; padding:12px 16px; gap:8px;}
        .tw-step-derivation-footer {gap:8px;}
        .tw-step-derivation-code .cm-editor {max-height:260px;}
        .tw-step-derivation-code .cm-scroller {overflow:auto;}
        .tw-step-derivation-summary {font-size:12px; color:#536275;}
        @media(max-width:600px) {
          .tw-step-derivation-part {padding:10px;}
        }
    ''')
    with ui.dialog() as dialog, ui.card().classes('tw-step-derivation-dialog' + (' tw-step-derivation-copy' if mode == 'copy' else '')):
        with ui.column().classes('tw-step-operation-header tw-step-derivation-header w-full'):
            ui.label(action + '步骤 · ' + step['name']).classes('text-xl font-semibold')
            if mode == 'split':
                ui.label('按类别分配给上下两份；切换分类会保留所有选择与手写内容。').classes('text-sm text-gray-600')
                with ui.row().classes('w-full gap-3 flex-nowrap'):
                    for index, form in enumerate(forms):
                        title = '第一份' if index == 0 else '第二份'
                        form['name'] = ui.input(title + '名称', value=step['name'] + (' · 第二份' if index else '')).props('dense outlined').classes('w-1/2')
                with ui.tabs().classes('w-full') as tabs:
                    ui.tab('code', label='代码', icon='code')
                    ui.tab('contexts', label='上下文', icon='snippet_folder')
                    ui.tab('io', label='输入输出', icon='schema')
            else:
                ui.label('在当前步骤之后创建完整副本，原步骤与执行记录保留。').classes('text-sm text-gray-600')
        with ui.column().classes('tw-step-operation-body tw-step-derivation-body'):
            if mode == 'copy':
                with ui.card().classes('tw-step-derivation-part w-full'):
                    ui.label('将复制的内容').classes('font-semibold')
                    ui.label(f'完整代码 · 输入输出与绑定 · 插件配置 · {len(groups)} 组上下文 / {len(capture_options)} 项材料')
                    ui.label('副本的上下文可独立编辑。').classes('text-sm text-gray-600')
                with ui.expansion('查看完整代码', icon='code').classes('w-full'):
                    ui.code(step['step_content'], language='python').classes('w-full')
            else:
                with ui.tab_panels(tabs, value='code').props('keep-alive').classes('w-full'):
                    with ui.tab_panel('code'):
                        ui.label('按完整语句选择；条件和循环作为整体。可展开完整代码继续编辑。').classes('text-sm text-gray-600 mb-3')
                        for index, form in enumerate(forms):
                            title = '第一份' if index == 0 else '第二份'
                            with ui.card().classes('tw-step-derivation-part w-full mb-3'):
                                _part_header(title, bool(index))
                                selection = ui.column().classes('w-full gap-1')
                                with ui.expansion('查看与编辑完整代码', icon='edit_note').classes('w-full'):
                                    form['code'] = ui.codemirror(step['step_content'], language='Python', line_wrapping=True).classes('tw-step-derivation-code w-full border rounded')
                                with selection: _code_selection(form['code'], title)
                    with ui.tab_panel('contexts'):
                        ui.label('同一项材料可同时保留在两份中；第二份获得独立副本。').classes('text-sm text-gray-600 mb-3')
                        for index, form in enumerate(forms):
                            title = '第一份' if index == 0 else '第二份'
                            with ui.card().classes('tw-step-derivation-part w-full mb-3'):
                                _part_header(title, bool(index))
                                form['captures'] = ui.select(capture_options, value=list(capture_options), multiple=True,
                                    label=title + '上下文材料（可多选）').classes('w-full').props('use-chips outlined')
                                if not capture_options: ui.label('原步骤暂无采集项。').classes('text-sm text-gray-600')
                    with ui.tab_panel('io'):
                        ui.label('选择字段会同步必填项；取消输入字段也会移除对应绑定。复杂约束与引用可在高级编辑中核对。').classes('text-sm text-gray-600 mb-3')
                        for index, form in enumerate(forms):
                            title = '第一份' if index == 0 else '第二份'
                            with ui.card().classes('tw-step-derivation-part w-full mb-3'):
                                _part_header(title, bool(index))
                                selection = ui.column().classes('w-full gap-2')
                                controls = form['controls'] = {}
                                with ui.expansion('高级编辑 · Schema 与输入绑定', icon='data_object').classes('w-full'):
                                    for key, label in [('input_schema', '输入 Schema'), ('bindings', '输入绑定'), ('output_schema', '输出 Schema')]:
                                        controls[key] = ui.textarea(title + label + '（JSON）', value=json.dumps(step.get(key, {}), ensure_ascii=False, indent=2)).classes('w-full').props('autogrow outlined')
                                with selection:
                                    _schema_selection(controls['input_schema'], title, '输入', bindings=controls['bindings'])
                                    _schema_selection(controls['output_schema'], title, '输出')
                                ui.label('插件能力：' + ('、'.join(step.get('capabilities', [])) or '无')).classes('text-xs text-gray-600')
        with ui.column().classes('tw-step-operation-footer tw-step-derivation-footer w-full'):
            if mode == 'split':
                summary = ui.label().classes('tw-step-derivation-summary w-full')
                def sync_summary():
                    parts = []
                    for index, form in enumerate(forms):
                        title = '第一份' if index == 0 else '第二份'
                        try:
                            inputs = len(_json_object(form['controls']['input_schema'], '').get('properties', {}))
                            outputs = len(_json_object(form['controls']['output_schema'], '').get('properties', {}))
                            fields = f'{inputs} 输入 / {outputs} 输出'
                        except (TaskError, TypeError): fields = 'JSON 待修正'
                        parts.append(f"{title}：{len((form['code'].value or '').splitlines())} 行代码 · {len(form['captures'].value or [])} 项材料 · {fields}")
                    summary.set_text('　｜　'.join(parts))
                for form in forms:
                    for control in (form['code'], form['captures'], *form['controls'].values()):
                        control.on_value_change(sync_summary)
                sync_summary()
                ui.label('确认后：第一份保留原记录，第二份紧随其后；已有下游引用仍指向第一份。').classes('text-sm')
            progress = ui.label('正在保存，关闭窗口不会取消已提交的操作').classes('text-sm text-gray-600')
            progress.props('role=status')
            progress.set_visibility(False)
            error = ui.label('').classes('text-negative whitespace-pre-wrap w-full')
            error.props('role=alert')
            error.set_visibility(False)

            async def submit():
                nonlocal busy
                if busy or dialog.is_deleted or not dialog.value: return
                if not is_current():
                    error.set_text('当前编辑对象已变化，请关闭弹窗后重新打开。')
                    error.set_visibility(True)
                    return
                busy = True
                enabled_states = [(element, element.enabled) for element in dialog.descendants()
                                  if hasattr(element, 'set_enabled')]
                blocked_backdrop = bool(dialog._props.get('no-backdrop-dismiss'))
                dialog.props('no-backdrop-dismiss')
                progress.set_visibility(True)
                confirm.props('loading')
                for element, _ in enabled_states:
                    element.disable()
                error.set_visibility(False)
                try:
                    arguments = dict(step_id=step['step_id'], expected_hash=descriptor['definition_hash'],
                        expected_step_hash=step['content_hash'], context_revisions=revisions)
                    if mode == 'split':
                        arguments.update(first_document=_document(step, forms[0], '第一份'), second_document=_document(step, forms[1], '第二份'),
                            first_capture_ids=list(forms[0]['captures'].value or []), second_capture_ids=list(forms[1]['captures'].value or []))
                    created = await controller.call('step.' + mode, **arguments)
                    dialog.close()
                    if is_current():
                        result = on_created(created)
                        if inspect.isawaitable(result): await result
                except TaskError as exc:
                    if not dialog.is_deleted:
                        error.set_text(str(exc))
                        error.set_visibility(True)
                finally:
                    busy = False
                    if not dialog.is_deleted and not blocked_backdrop:
                        dialog.props(remove='no-backdrop-dismiss')
                    if not progress.is_deleted:
                        progress.set_visibility(False)
                    if not confirm.is_deleted:
                        confirm.props(remove='loading')
                    for element, enabled in enabled_states:
                        if not element.is_deleted:
                            element.set_enabled(enabled)

            def cancel_review():
                if not busy:
                    dialog.close()

            with ui.row().classes('w-full justify-end gap-2'):
                cancel = ui.button('取消', on_click=cancel_review).props('outline')
                confirm = ui.button('确认' + action, on_click=submit).props('unelevated color=primary')
    dialog.open()
    return dialog
