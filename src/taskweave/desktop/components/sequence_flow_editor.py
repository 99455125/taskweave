"""Structured combination canvas and control configuration bindings."""

from copy import deepcopy

from nicegui import ui

from taskweave.core.validation import TaskError
from taskweave.core.task_flow import conditional_branches
from taskweave.presentation.flow_editor import find_node
from taskweave.desktop.components.flow_tree import FlowTree
from taskweave.desktop.components.branch_form import BranchForm, branch_sequence_targets
from taskweave.desktop.components.flow_controls import ControlForm


class SequenceFlowEditor:
    def __init__(self, page):
        self.page = page
        self.selected = None
        self.form = None
        self.views = {}
        self.error = None

    def reset(self):
        self.selected = self.form = None

    def flush(self):
        if self.form is None or self.selected is None:
            return
        values = self.form.value()
        node, _ = find_node(self.page.draft.flow, self.selected)
        if node is not None:
            if node['kind'] == 'if':
                node.clear()
                node.update(deepcopy(values))
            else:
                node.update(deepcopy(values))

    def controls(self):
        result = {}
        def walk(node):
            kind = node['kind']
            if kind in {'if', 'foreach', 'loop'}:
                result[node['id']] = ('分支 ' if kind == 'if' else '循环 ') + node['id'][-8:]
            children = (node['children'] if kind == 'sequence' else
                        [body for _, body in conditional_branches(node)] if kind == 'if' else
                        [node['body']] if kind in {'foreach', 'loop'} else [])
            for child in children:
                walk(child)
        walk(self.page.draft.flow['root'])
        return result

    async def select(self, node_id):
        self.flush()
        self.selected, self.form = node_id, None
        await self.page.repaint()

    async def add(self, kind, parent_id="root", index=None):
        try:
            self.flush()
            identity = self.page.draft.add_control(kind, parent_id, index)
        except TaskError as exc:
            self.feedback('插入失败：' + str(exc))
            return
        self.selected = identity
        self.form = None
        await self.page.repaint()

    def feedback(self, text):
        if self.error is not None and not self.error.is_deleted:
            self.error.set_text(text)
        else:
            ui.notify(text, type='negative')

    async def insert(self, parent_id, index):
        try:
            self.flush()
        except TaskError as exc:
            self.feedback('插入失败：' + str(exc))
            return
        with ui.dialog() as dialog, ui.card().classes('tw-confirm-dialog'):
            ui.label('在此插入节点').classes('tw-confirm-title')
            for kind, label in [('action', '任务'), ('if', '条件分支'), ('foreach', '列表遍历'), ('loop', '条件循环')]:
                ui.button(label, on_click=lambda _, k=kind: dialog.submit(k)).props('flat')
            ui.button('取消', on_click=lambda: dialog.submit(None)).props('outline')
        kind = await dialog
        if not kind:
            return
        if kind == 'action':
            await self.page.add_dialog(parent_id, index)
        else:
            try:
                await self.add(kind, parent_id, index)
            except TaskError as exc:
                self.feedback('插入失败：' + str(exc))

    def select_moved(self, node_id):
        self.form = None
        if node_id in self.controls():
            self.selected = node_id
        else:
            self.selected = None
            self.page.selected_node_id = node_id

    async def move(self, node_id):
        try:
            self.flush()
        except TaskError as exc:
            self.feedback('无法移动：' + str(exc))
            return
        targets = dict(branch_sequence_targets(self.page.draft.flow, moving_node_id=node_id))
        with ui.dialog() as dialog, ui.card().classes('tw-confirm-dialog'):
            ui.label('移动到流程分组').classes('tw-confirm-title')
            target = ui.select(targets, value=next(iter(targets), None), label='目标分组').classes('w-full')
            error = ui.label('').classes('text-negative whitespace-pre-wrap')
            async def apply():
                try:
                    self.page.draft.move_to(node_id, target.value)
                except TaskError as exc:
                    error.set_text('无法移动：' + str(exc))
                    return
                self.select_moved(node_id)
                dialog.close()
                await self.page.repaint()
            with ui.row().classes('tw-confirm-actions'):
                ui.button('取消', on_click=dialog.close).props('outline')
                ui.button('移动', on_click=apply)
        dialog.open()

    async def drop(self, node_id, parent_id, index):
        try:
            self.flush()
            node, parent = find_node(self.page.draft.flow, node_id)
            if parent is not None and parent['id'] == parent_id and parent['children'].index(node) < index:
                index -= 1
            self.page.draft.move_to(node_id, parent_id, index)
        except TaskError as exc:
            self.feedback('无法移动：' + str(exc))
            return
        self.select_moved(node_id)
        await self.page.repaint()

    async def remove(self, node_id):
        try:
            self.flush()
            self.page.draft.remove_control(node_id)
        except TaskError as exc:
            self.feedback('无法删除：' + str(exc))
            return
        if self.selected == node_id:
            self.reset()
        await self.page.repaint()

    async def remove_task(self, node_id):
        index = next(i for i, node in enumerate(self.page.draft.nodes) if node['node_id'] == node_id)
        await self.page.remove_node(index)

    def render(self):
        page = self.page
        nodes = {node['node_id']: node for node in page.draft.nodes}
        steps = [{'step_id': key, 'name': page._task_name(node['task_id']), 'position': index,
                  'validation_state': 'VALIDATED' if page._task_status(node['task_id']) == '任务已确认' else 'DRAFT'}
                 for index, (key, node) in enumerate(nodes.items())]
        with ui.column().classes('tw-panel tw-flow-panel w-full'):
            with ui.row().classes('tw-step-list-heading w-full items-center gap-2'):
                ui.icon('account_tree').classes('text-blue-500')
                ui.label('组合流程').classes('font-semibold')
                ui.label(f'{len(nodes)} 个任务 · {len(self.controls())} 个控制节点').classes('tw-badge')
                ui.space()
                with ui.row().classes('tw-flow-toolbar items-center gap-2 flex-wrap'):
                    with ui.button('添加节点', icon='add').props('flat no-caps'):
                        with ui.menu():
                            ui.menu_item('任务', page.add_dialog)
                            for kind, caption in [('if', '条件分支'), ('foreach', '列表遍历'), ('loop', '条件循环')]:
                                ui.menu_item(caption, lambda k=kind: self.add(k))
                    view = self.views.setdefault(page.draft.sequence_id or 'new', {'zoom': 1.0, 'expanded': True})
                    def zoom_changed(event):
                        view['zoom'] = event.value
                        tree.root.style(f"zoom:{view['zoom']}")
                    ui.select({0.75: '75%', 1.0: '100%', 1.25: '125%'}, value=view['zoom'], on_change=zoom_changed).props(
                        'borderless dense aria-label=流程缩放').classes('tw-flow-zoom')
                    def toggle():
                        view['expanded'] = not view['expanded']
                        tree.canvas.set_visibility(view['expanded'])
                    ui.button(icon='unfold_less', on_click=toggle).props('flat round dense aria-label=展开或收起流程')
            ui.label('在节点“更多”中选择前后插入；拖动时显示落点，放下后校验依赖并自动排版。').classes('text-xs text-gray-600 w-full')
            self.error = ui.label('').classes('text-negative whitespace-pre-wrap')
            def metadata(step, card):
                node = nodes[step['step_id']]
                card.classes('tw-sequence-node')
                environment = next((env['name'] for env in page.environments if env['environment_id'] == node['environment_id']), '默认环境')
                ui.label(f"{step['position'] + 1:02d} · {environment}").classes('tw-flow-node-meta')
                ui.label(f"{len(page.steps.get(node['task_id'], []))} 个步骤 · {page._task_status(node['task_id'])}").classes('tw-flow-node-meta')
            tree = FlowTree(steps, None if self.selected else page.selected_node_id, page.select_node,
                            self.select, self.move, self.remove, render_action=metadata,
                            on_insert=self.insert, on_drop=self.drop, on_delete_step=self.remove_task,
                            action_label="任务", delete_label="移除任务")
            tree.render(page.draft.flow)
            self.tree = tree
            tree.canvas.classes('tw-sequence-canvas')
            tree.root.style(f"zoom:{view['zoom']}")
            tree.canvas.set_visibility(view['expanded'])
            selected = self.selected or page.selected_node_id
            ui.label(tree.node_paths.get(selected, '主流程')).classes('tw-flow-location text-xs text-gray-500')
            status = ui.label().classes('text-xs text-gray-500')
            def update_status():
                if status.is_deleted:
                    timer.deactivate()
                    return
                try:
                    dirty = page.draft.needs_save() or bool(page.invalid_literals)
                    if self.form is not None and self.selected:
                        node, _ = find_node(page.draft.flow, self.selected)
                        values = self.form.value()
                        dirty = dirty or any(node.get(key) != value for key, value in values.items())
                except (TaskError, ValueError, TypeError):
                    dirty = True
                status.set_text('未保存修改 · 保存组合后生效' if dirty else '组合已保存')
            timer = ui.timer(.3, update_status)
            update_status()
            if self.selected:
                tree.select(self.selected)
            for index, node in enumerate(page.draft.nodes, 1):
                card = tree.nodes.get(node['node_id'])
                if card:
                    for element in card.descendants():
                        if isinstance(element, ui.button) and element.text == page._task_name(node['task_id']):
                            element.props['aria-label'] = f"选择任务节点 {index}：{element.text}"
                            element.props['icon'] = 'task_alt'

    def render_configuration(self):
        node, _ = find_node(self.page.draft.flow, self.selected)
        if node is None:
            self.reset()
            return
        ui.label({'if': '条件分支', 'foreach': '列表遍历', 'loop': '条件循环'}[node['kind']]).classes('text-lg font-semibold')
        sources = {item['node_id']: {'name': self.page._task_name(item['task_id']),
                                    'steps': {step['step_id']: step['name'] for step in self.page.steps.get(item['task_id'], [])}}
                   for item in self.page.draft.nodes}
        self.form = (BranchForm if node['kind'] == 'if' else ControlForm)(node, {}, self.controls(), sequence_nodes=sources)
        ui.label('修改保留在组合草稿中，保存组合后生效。').classes('text-xs text-gray-500')
