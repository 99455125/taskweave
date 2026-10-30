"""Local browser fixture for actual shared flow-canvas geometry."""
import sys

from nicegui import ui

from taskweave.desktop.components.flow_tree import FlowTree
from taskweave.desktop.theme import STYLE


def sequence(identity, children):
    return {'id': identity, 'kind': 'sequence', 'children': children}


def action(index):
    return {'id': str(index), 'kind': 'action', 'step_id': str(index)}


@ui.page('/')
def canvas_page():
    ui.add_css(STYLE)
    steps = [{'step_id': str(index), 'name': '核对参与方并提交记录 · ' + str(index), 'position': index}
             for index in range(6)]
    linear = sequence('root', [action(index) for index in range(6)])
    nested = sequence('root', [
        {'id': 'choose', 'kind': 'if', 'parallel': True,
         'cases': [{'id': 'first', 'condition': {'op': 'eq', 'left': {'literal': True}, 'right': {'literal': True}},
                    'body': sequence('case-body', [action(index) for index in range(4)])}],
         'default': {'id': 'otherwise', 'body': sequence('default-body', [action(4)])}}, action(5)])
    looped = sequence('root', [{'id': 'each', 'kind': 'foreach', 'items': {'literal': [1]},
                               'body': sequence('loop-body', [action(index) for index in range(6)])}])
    from copy import deepcopy
    empty_nested = deepcopy(nested)
    outer = empty_nested['children'][0]
    inner = deepcopy(outer)
    inner['id'] = 'inner'
    inner['cases'][0]['body'] = sequence('inner-case', [action(4)])
    inner['default']['body'] = sequence('inner-empty', [])
    outer['cases'][0]['body']['children'].append(inner)
    outer['default']['body'] = sequence('outer-empty', [])
    for identity, root in [('linear', linear), ('nested', nested), ('loop', looped), ('empty-nested', empty_nested)]:
        with ui.row().classes('tw-editor-layout w-full items-start'):
            with ui.column().classes('tw-panel tw-flow-panel w-full').props('data-layout=' + identity):
                with ui.column().classes('w-full gap-0'):
                    FlowTree(steps, None, lambda _: None, lambda _: None, lambda _: None, lambda _: None).render(
                        {'version': 2, 'root': root})


if __name__ == '__main__':
    ui.run(host='127.0.0.1', port=int(sys.argv[1]), show=False, reload=False)
