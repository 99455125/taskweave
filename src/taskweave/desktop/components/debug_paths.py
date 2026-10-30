"""Compact, read-only recorded execution paths for a selected DEBUG run."""
import json

from nicegui import ui

from taskweave.desktop.components.flow_tree import FlowTree
from taskweave.presentation.execution_paths import ExecutionPaths


_STATUS = {'SUCCEEDED': '成功', 'FAILED': '失败', 'UNKNOWN': '结果待核对',
           'RUNNING': '执行中', 'CANCELLED': '已取消'}


def _single_trial_flow(run):
    """Represent only valid attempted actions, preserving their recorded path IDs."""
    root = None
    for attempt in run.get('attempts', []):
        if not attempt.get('valid'):
            continue
        sid = attempt['step_id']
        path = attempt.get('execution_path') or '/main/' + sid.replace('~', '~0').replace('/', '~1')
        parts = [part.replace('~1', '/').replace('~0', '~') for part in path.split('/')[1:]]
        if root is None:
            root = {'id': parts[0], 'kind': 'sequence', 'children': []}
        parent = root
        for identity in parts[1:-1]:
            child = next((node for node in parent['children'] if node['id'] == identity), None)
            if child is None:
                child = {'id': identity, 'kind': 'sequence', 'children': []}
                parent['children'].append(child)
            parent = child
        if not any(node['id'] == parts[-1] for node in parent['children']):
            parent['children'].append({'id': parts[-1], 'kind': 'action', 'step_id': sid})
    return {'version': 2, 'root': root} if root is not None else None


def render_debug_paths(run, steps):
    """Render a collapsed path view from this run's frozen definition and records."""
    snapshot = json.loads(run['definition_json'])
    definition = snapshot.get('steps', steps)
    request = json.loads(run.get('request_json') or '{}')
    single_trial = run.get('mode') == 'TRIAL' and not request.get('flow_trial')
    if single_trial:
        flow = _single_trial_flow(run)
    else:
        flow = snapshot.get('flow') or {'version': 2, 'root': {
            'id': 'main', 'kind': 'sequence', 'children': [
                {'id': step['step_id'], 'kind': 'action', 'step_id': step['step_id']}
                for step in definition]}}

    with ui.expansion('实际执行路径', icon='route', value=False).classes('w-full') as panel:
        if flow is None:
            ui.label('尚无执行动作').classes('text-xs text-gray-500')
            return panel
        if single_trial:
            ui.label('本次仅显示单步试跑实际执行的动作').classes('text-xs text-gray-500')
        overview = ExecutionPaths(flow, run)
        with ui.row().classes('tw-flow-legend w-full items-center gap-3 flex-wrap'):
            ui.label('已走过').classes('tw-path-legend-taken')
            ui.label('未命中 / 未进入').classes('tw-path-legend-skipped')
            ui.label('尚未执行 / 尚未判定').classes('tw-path-legend-pending')
            if overview.scopes:
                selector = ui.select({'': '全部轮次（汇总）', **overview.scopes}, value='',
                                     label='路径轮次').props('dense outlined options-dense')
        host = ui.column().classes('w-full min-w-0')

        def paint(scope):
            if host.is_deleted:
                return
            paths = ExecutionPaths(flow, run, scope=scope) if scope else overview

            def render_action(step, card):
                attempts = paths.attempts(step['step_id'])
                status = attempts[-1]['status'] if attempts else None
                card.classes('tw-run-flow-node is-' + {
                    'SUCCEEDED': 'succeeded', 'FAILED': 'failed', 'UNKNOWN': 'unknown',
                    'RUNNING': 'running'}.get(status, 'pending'))
                mark = paths.step_marks[step['step_id']]
                label = _STATUS.get(status, {'skipped': '未命中', 'not-entered': '未进入循环'}.get(
                    mark.state, '尚未执行'))
                if attempts:
                    label += f' · 有效尝试 {len(attempts)} 次'
                ui.label(label).classes('tw-flow-node-meta')

            host.clear()
            with host:
                FlowTree(definition, None, lambda _sid: None, None, None, None,
                         read_only=True, render_action=render_action, paths=paths).render(flow)

        paint('')
        if overview.scopes:
            selector.on_value_change(lambda event: paint(event.value))
    return panel
