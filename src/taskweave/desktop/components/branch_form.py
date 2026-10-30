"""First-match branch cards over the existing nested-if flow contract."""

from copy import deepcopy

from nicegui import ui

from taskweave.core.validation import TaskError
from taskweave.desktop.components.flow_branches import (
    branch_output_values, build_branches, new_branch, split_branches,
)
from taskweave.desktop.components.flow_controls import ConditionForm, OperandForm

_FALLBACK = object()


class BranchForm:
    def __init__(self, node, steps, controls, *, on_change=None, sequence_nodes=None):
        self.node, self.steps, self.controls = deepcopy(node), steps, controls
        self.on_change = None
        self.sequence_nodes = sequence_nodes
        self.cases, self.mappings = [], []
        cases, self.fallback = split_branches(node)
        self.slot_ids = [case['id'] for case in cases]
        names, fallback_values = branch_output_values(node)
        with ui.row().classes('w-full items-center gap-3'):
            ui.label('执行方式').classes('text-sm text-gray-500')
            self.parallel = ui.checkbox('允许并行', value=node.get('parallel', False))
            self.parallel.on_value_change(lambda _: self._changed())
            self.mode_label = ui.label('所有命中分支执行，全部完成后继续' if self.parallel.value else '按顺序执行首个匹配分支').classes('tw-branch-mode')
            self.parallel.on_value_change(lambda e: self.mode_label.set_text('所有命中分支执行，全部完成后继续' if e.value else '按顺序执行首个匹配分支'))
            ui.space()
            ui.button('添加分支', icon='add', on_click=self.add_case).props('outline dense')
        self.case_area = ui.column().classes('tw-branch-cases w-full gap-3')
        for case in cases:
            self._append(case)
        with ui.row().classes('tw-branch-fallback w-full items-center gap-3'):
            ui.label('否则').classes('font-medium')
            ui.label('所有条件均不满足').classes('text-sm text-gray-500')
            ui.space()
            ui.label(f"{len(self.fallback['children'])} 个节点").classes('text-xs text-gray-500')
        with ui.expansion('分支公共输出', value=bool(names)).classes('w-full'):
            self.mapping_area = ui.column().classes('w-full gap-3')
            for name in names:
                self.add_mapping(name, {case['id']: case['values'][name] for case in cases},
                                 fallback_values[name])
            ui.button('添加映射', icon='add', on_click=lambda: self.add_mapping()).props('flat dense')
        self._order()
        self.on_change = on_change

    def _changed(self):
        if self.on_change:
            self.on_change()

    def _append(self, node):
        case = {'key': node['id'], 'node': node}
        with self.case_area:
            with ui.column().classes('tw-branch-case w-full gap-2') as case['host']:
                with ui.row().classes('w-full items-center gap-2'):
                    case['title'] = ui.label('').classes('font-semibold')
                    ui.label(f"{len(node['then']['children'])} 个节点").classes('text-xs text-gray-500')
                    ui.space()
                    case['up'] = ui.button(icon='arrow_upward', on_click=lambda: self.move_case(case, -1)).props('flat round dense')
                    case['down'] = ui.button(icon='arrow_downward', on_click=lambda: self.move_case(case, 1)).props('flat round dense')
                    case['remove'] = ui.button(icon='close', on_click=lambda: self.remove_case(case)).props('flat round dense')
                with ui.expansion('匹配条件', value=not self.cases,
                                  group='branch-' + str(id(self))).classes('w-full tw-branch-condition') as case['expansion']:
                    case['condition'] = ConditionForm(node['condition'], self.steps, self.controls, on_change=self._changed, sequence_nodes=self.sequence_nodes)
        self.cases.append(case)
        for mapping in self.mappings:
            self._output_field(mapping, case['key'], None)
        return case

    def add_case(self):
        node = new_branch()
        self.slot_ids.append(node['id'])
        for case in self.cases:
            case['expansion'].close()
        self._append(node)['expansion'].open()
        self._order()
        self._changed()

    def move_case(self, case, offset):
        index = self.cases.index(case)
        target = index + offset
        if not 0 <= target < len(self.cases):
            return
        self.cases.insert(target, self.cases.pop(index))
        self._order()
        self._changed()

    def remove_case(self, case):
        if len(self.cases) < 2:
            raise TaskError('FORM_INVALID', '至少保留一条条件分支')
        if case['node']['then']['children']:
            raise TaskError('FORM_INVALID', '请先移走此分支中的步骤或控制块')
        self.cases.remove(case)
        self.slot_ids.pop()
        case['host'].delete()
        for mapping in self.mappings:
            mapping['values'].pop(case['key']).root.delete()
        self._order()
        self._changed()

    def _order(self):
        for index, case in enumerate(self.cases):
            case['host'].move(target_index=index)
            case['title'].set_text(f'分支 {index + 1}')
            for key, text in [('up', '上移'), ('down', '下移'), ('remove', '移除')]:
                case[key].props['aria-label'] = f'{text}分支 {index + 1}'
            case['up'].set_enabled(index > 0)
            case['down'].set_enabled(index < len(self.cases) - 1)
            case['remove'].set_enabled(len(self.cases) > 1 and not case['node']['then']['children'])
            for mapping in self.mappings:
                field = mapping['values'][case['key']]
                field.label.set_text(f'分支 {index + 1}')
                field.root.move(target_index=index)
        for mapping in self.mappings:
            mapping['values'][_FALLBACK].root.move(target_index=len(self.cases))

    def _output_field(self, mapping, key, value):
        with mapping['area']:
            mapping['values'][key] = OperandForm(value or {}, self.steps, self.controls,
                                                '否则' if key is _FALLBACK else '',
                                                on_change=self._changed, required=True, sequence_nodes=self.sequence_nodes)

    def add_mapping(self, name='', values=None, fallback=None):
        mapping = {'values': {}}
        with self.mapping_area:
            with ui.column().classes('tw-branch-output w-full gap-3') as mapping['host']:
                with ui.row().classes('w-full items-center gap-2'):
                    mapping['name'] = ui.input('输出名称', value=name).classes('grow')
                    mapping['name'].on_value_change(lambda _: self._changed())
                    ui.button('移除此映射', on_click=lambda: self.remove_mapping(mapping)).props('flat dense')
                mapping['area'] = ui.element('div').classes('tw-branch-output-values w-full')
                for case in self.cases:
                    self._output_field(mapping, case['key'], (values or {}).get(case['key']))
                self._output_field(mapping, _FALLBACK, fallback)
        self.mappings.append(mapping)
        self._order()
        self._changed()

    def remove_mapping(self, mapping):
        self.mappings.remove(mapping)
        mapping['host'].delete()
        self._changed()

    def value(self):
        names = [(row['name'].value or '').strip() for row in self.mappings]
        if any(not name for name in names) or len(set(names)) != len(names):
            raise TaskError('FORM_INVALID', '映射名称不能为空或重复')
        cases = [{**deepcopy(case['node']), 'id': case['key'] if 'cases' in self.node or self.parallel.value else self.slot_ids[index], 'condition': case['condition'].value(),
                  'values': {name: row['values'][case['key']].value()
                             for name, row in zip(names, self.mappings)}} for index, case in enumerate(self.cases)]
        fallback = {name: row['values'][_FALLBACK].value() for name, row in zip(names, self.mappings)}
        original = deepcopy(self.node)
        if 'cases' in original or self.parallel.value:
            original['parallel'] = self.parallel.value
        return build_branches(original, cases, self.fallback, names, fallback_values=fallback)


def branch_sequence_targets(flow, moving_node_id=None):
    """Visible destination paths, excluding internal else-if wrapper sequences."""
    result = [(flow['root']['id'], '主流程')]

    def walk(node):
        if node['id'] == moving_node_id:
            return
        kind = node['kind']
        if kind == 'sequence':
            for child in node['children']:
                walk(child)
        elif kind == 'if':
            cases, fallback = split_branches(node)
            short = node['id'].replace('control-', '')[:6]
            for index, case in enumerate(cases, 1):
                result.append((case['then']['id'], f'条件 {short} · 分支 {index}'))
                walk(case['then'])
            result.append((fallback['id'], f'条件 {short} · 否则'))
            walk(fallback)
        elif kind in {'loop', 'foreach'}:
            title = '条件循环' if kind == 'loop' else '列表遍历'
            short = node['id'].replace('control-', '')[:6]
            result.append((node['body']['id'], f'{title} {short} · 循环体'))
            walk(node['body'])
    walk(flow['root'])
    return result
