"""Horizontal task-flow navigation over the unchanged version-2 flow contract."""

from nicegui import ui

from taskweave.desktop.components.flow_branches import split_branches


class FlowTree:
    def __init__(self, steps, selected_step_id, on_action, on_control, on_move, on_delete_control,
                 *, read_only=False, render_action=None, paths=None, on_insert=None, on_drop=None, on_delete_step=None, on_derive=None, action_label="步骤", delete_label="删除步骤"):
        self.action_label, self.delete_label = action_label, delete_label
        self.node_paths = {}
        self.steps = {step["step_id"]: step for step in steps}
        self.nodes = {}
        self.step_paths = {}
        self.names = {step["step_id"]: step["name"] for step in steps}
        self.validated = {step["step_id"] for step in steps
                          if step.get("validation_state") == "VALIDATED"}
        self.validation_icons = {}
        self.selected_step_id = selected_step_id
        self.selected_control = None
        self.on_action, self.on_control, self.on_move = on_action, on_control, on_move
        self.on_delete_control = on_delete_control
        self.read_only, self.render_action = read_only, render_action
        self.on_derive = on_derive
        self.paths = paths
        self.on_insert, self.on_drop, self.on_delete_step = on_insert, on_drop, on_delete_step

    def render(self, flow):
        self.flow = flow
        with ui.element('div').classes('tw-flow-canvas') as self.canvas:
            with ui.row().classes('tw-flow-sequence tw-flow-root') as self.root:
                ui.label('开始').classes('tw-flow-terminal')
                self._connector(self.paths.entries[flow['root']['id']] if self.paths else None)
                self._node(flow['root'], ('主流程',))
                self._connector(self.paths.nodes[flow['root']['id']] if self.paths else None, exit=True)
                ui.label('结束').classes('tw-flow-terminal')

    def select(self, node_id):
        for key, element in self.nodes.items():
            element.classes(add='is-selected' if key == node_id else '',
                            remove='' if key == node_id else 'is-selected')

    def set_validation(self, step_id, validation_state):
        self.steps[step_id]['validation_state'] = validation_state
        if validation_state == 'VALIDATED':
            self.validated.add(step_id)
        else:
            self.validated.discard(step_id)
        icon = self.validation_icons.get(step_id)
        if icon is not None and not icon.is_deleted:
            icon.set_visibility(step_id in self.validated)

    @staticmethod
    def _connector(mark=None, *, exit=False):
        edge = ui.element('span').classes('tw-flow-connector').props('aria-hidden=true')
        if mark is not None:
            state = 'taken' if mark.completed else 'pending' if mark.reached else mark.state
            state = state if exit else mark.state
            edge.classes('is-path-' + state)
            edge.props['data-path-state'] = state

    def _menu(self, node, *, control=False):
        with ui.button(icon='more_horiz').props('flat round dense aria-label="节点操作"').classes('tw-flow-menu'):
            with ui.menu():
                ui.menu_item('移动到其他分组', lambda nid=node['id']: self.on_move(nid))
                if self.on_insert:
                    from taskweave.presentation.flow_editor import find_node
                    _, parent = find_node(self.flow, node['id'])
                    index = next(i for i, child in enumerate(parent['children']) if child['id'] == node['id'])
                    ui.menu_item('在前面插入', lambda: self.on_insert(parent['id'], index))
                    ui.menu_item('在后面插入', lambda: self.on_insert(parent['id'], index + 1))
                if not control and self.on_derive:
                    ui.menu_item('复制步骤', lambda: self.on_derive(node['step_id'], 'copy'))
                    ui.menu_item('拆分步骤', lambda: self.on_derive(node['step_id'], 'split'))
                if not control and self.on_delete_step:
                    ui.menu_item(self.delete_label, lambda: self.on_delete_step(node['step_id']))
                if control:
                    ui.menu_item('删除空控制块', lambda nid=node['id']: self.on_delete_control(nid))

    def _draggable(self, element, node):
        element.props['data-node-id'] = node['id']
        if self.read_only or not self.on_drop:
            return
        element.props['draggable'] = True
        element.on('dragstart', js_handler="""event => {
            event.stopPropagation();
            event.dataTransfer.setData('application/taskweave-node', event.currentTarget.dataset.nodeId);
            event.dataTransfer.effectAllowed = 'move';
            event.currentTarget.classList.add('is-dragging');
            event.currentTarget.closest('.tw-flow-canvas')?.classList.add('is-drag-active');
        }""")
        element.on('dragend', js_handler="""event => {
            event.currentTarget.classList.remove('is-dragging');
            const canvas = event.currentTarget.closest('.tw-flow-canvas');
            canvas?.classList.remove('is-drag-active');
            canvas?.querySelectorAll('.is-drop-target').forEach(el => el.classList.remove('is-drop-target'));
        }""")

    def _gap(self, parent_id, index):
        gap = ui.element('div').classes('tw-flow-insert').props('aria-hidden=true')
        gap.props['data-parent-id'] = parent_id
        gap.props['data-index'] = index
        if self.on_drop:
            async def drop(event):
                await self.on_drop(event.args.get('node_id'), parent_id, index)
            gap.on('dragover', js_handler="""event => {
                if (!event.dataTransfer.types.includes('application/taskweave-node')) return;
                event.preventDefault(); event.stopPropagation();
                event.dataTransfer.dropEffect = 'move'; event.currentTarget.classList.add('is-drop-target');
            }""")
            gap.on('dragleave', js_handler="event => event.currentTarget.classList.remove('is-drop-target')")
            gap.on('drop', drop, js_handler="""event => {
                event.preventDefault(); event.stopPropagation(); event.currentTarget.classList.remove('is-drop-target');
                const node_id = event.dataTransfer.getData('application/taskweave-node');
                if (node_id) emit({node_id});
            }""")

    @staticmethod
    def _route_overlay(group):
        """Follow actual branch card geometry, including nested and unequal-height paths."""
        ui.element('svg').classes('tw-flow-path-overlay').props('aria-hidden=true')
        script = '''(() => {
            const group = getHtmlElement(GROUP_ID);
            if (!group) return;
            const svg = group.querySelector(':scope > .tw-flow-path-overlay');
            const rows = [...group.querySelectorAll(':scope > .tw-flow-branch')];
            let observer;
            const draw = () => {
                if (!group.isConnected) { observer.disconnect(); return; }
                const box = group.getBoundingClientRect();
                if (!box.width || !box.height) return;
                const scale = box.width / group.offsetWidth;
                const margin = 8 * scale;
                const width = box.width + 2 * margin;
                svg.setAttribute('viewBox', `0 0 ${width} ${box.height}`);
                const routes = [];
                for (const row of rows) {
                    const rect = row.querySelector(':scope > .tw-flow-sequence').getBoundingClientRect();
                    const y = rect.top + rect.height / 2 - box.top;
                    const state = row.dataset.pathState || 'neutral';
                    const exit = row.classList.contains('is-path-exited') ? 'taken'
                        : state === 'taken' ? 'pending' : state;
                    routes.push({state, d: `M0 ${box.height / 2} V${y} H${rect.left - box.left + margin}`});
                    routes.push({state: exit, d: `M${rect.right - box.left + margin} ${y} H${width} V${box.height / 2}`});
                }
                // Draw traversed shared stems last so neutral alternatives cannot cover them.
                routes.sort((a, b) => (a.state === 'taken') - (b.state === 'taken'));
                svg.replaceChildren(...routes.map(route => {
                    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                    path.setAttribute('d', route.d);
                    path.setAttribute('class', 'is-path-' + route.state);
                    return path;
                }));
            };
            observer = new ResizeObserver(draw);
            observer.observe(group);
            rows.forEach(row => observer.observe(row));
            requestAnimationFrame(draw);
        })();'''.replace('GROUP_ID', str(group.id))
        def install_routes():
            if not group.is_deleted:
                ui.run_javascript(script)
        ui.timer(0, install_routes, once=True)

    def _node(self, node, path):
        kind = node['kind']
        self.node_paths[node['id']] = ' › '.join(path)
        if kind == 'sequence':
            with ui.row().classes('tw-flow-sequence'):
                if self.on_insert and not self.read_only:
                    self._gap(node['id'], 0)
                if not node['children']:
                    if self.on_insert and not self.read_only:
                        ui.button('空路径 · 添加节点', on_click=lambda: self.on_insert(node['id'], 0)).props('flat no-caps').classes('tw-flow-empty')
                    else:
                        ui.label('空路径').classes('tw-flow-empty')
                for index, child in enumerate(node['children']):
                    if index and not (self.on_insert and not self.read_only):
                        mark = self.paths.edges[(node['children'][index - 1]['id'], child['id'])] if self.paths else None
                        self._connector(mark)
                    self._node(child, path)
                    if self.on_insert and not self.read_only:
                        self._gap(node['id'], index + 1)
            return
        if kind == 'action':
            name = self.names.get(node['step_id'], self.action_label)
            self.step_paths[node['step_id']] = ' › '.join(path)
            with ui.column().classes('tw-flow-node' + (' is-selected' if node['step_id'] == self.selected_step_id else '')) as card:
                self._draggable(card, node)
                self.nodes[node['id']] = card
                if self.paths:
                    card.classes('is-path-' + self.paths.nodes[node['id']].state)
                    card.props['data-node-id'] = node['id']
                with ui.row().classes('tw-flow-node-heading w-full'):
                    button = ui.button(name, icon='code', on_click=lambda sid=node['step_id']: self.on_action(sid)).props(
                        'flat no-caps').classes('tw-flow-node-title')
                    button.props['aria-label'] = ('查看' if self.read_only else '选择') + self.action_label + '：' + name
                    if node['step_id'] == self.selected_step_id:
                        self.selected_control = button
                    if not self.read_only:
                        icon = ui.icon('check').classes('tw-flow-validated')
                        icon.set_visibility(node['step_id'] in self.validated)
                        self.validation_icons[node['step_id']] = icon
                    if not self.read_only:
                        self._menu(node)
                step = self.steps[node['step_id']]
                if self.render_action is not None:
                    self.render_action(step, card)
                else:
                    plugins = sorted({item.split('.')[0] for item in step.get('capabilities', [])})
                    ui.label(f"{step.get('position', 0) + 1:02d} · " + (' / '.join(plugins) or '步骤')).classes('tw-flow-node-meta')
            return
        label = {'if': '条件分支', 'foreach': '列表遍历', 'loop': '条件循环'}[kind]
        if kind == 'if' and node.get('parallel', False):
            label += ' · 并行'
        icon = {'if': 'alt_route', 'foreach': 'repeat', 'loop': 'autorenew'}[kind]
        with ui.column().classes('tw-flow-block tw-flow-' + kind):
            with ui.row().classes('tw-flow-block-heading') as heading:
                self._draggable(heading, node)
                self.nodes[node['id']] = heading
                if self.paths:
                    heading.classes('is-path-' + self.paths.nodes[node['id']].state)
                if self.read_only:
                    with ui.row().classes('tw-flow-control-title items-center gap-2 p-2'):
                        ui.icon(icon)
                        ui.label(label)
                    if self.paths and node['id'] in self.paths.errors:
                        ui.label('失败 · ' + self.paths.errors[node['id']]).classes('text-xs text-red-700')
                else:
                    button = ui.button(label, icon=icon, on_click=lambda nid=node['id']: self.on_control(nid)).props(
                        'flat no-caps').classes('tw-flow-control-title')
                    button.props['aria-label'] = '配置' + label
                    self._menu(node, control=True)
            if kind == 'if':
                cases, fallback = split_branches(node)
                with ui.column().classes('tw-flow-branches has-routed-paths') as branches:
                    if self.paths:
                        branches.classes('has-execution-paths')
                    paths = [(case['then'], f'分支 {index + 1}') for index, case in enumerate(cases)]
                    paths.append((fallback, '否则'))
                    for branch, caption in paths:
                        with ui.row().classes('tw-flow-branch') as row:
                            mark = self.paths.branches[branch['id']] if self.paths else None
                            if mark is not None:
                                row.classes('is-path-' + mark.state + (' is-path-exited' if mark.completed else ''))
                                row.props['data-branch-id'] = branch['id']
                                row.props['data-path-state'] = mark.state
                            if mark is None:
                                ui.label(caption).classes('tw-flow-path-label')
                            else:
                                with ui.row().classes('tw-flow-path-label gap-2'):
                                    ui.label(caption)
                                    ui.label(mark.label(branch=True)).classes('tw-flow-path-status')
                            self._node(branch, (*path, caption))
                    self._route_overlay(branches)
            else:
                self._node(node['body'], (*path, label))
                returned = ui.label('下一项' if kind == 'foreach' else '继续循环').classes('tw-flow-return')
                if self.paths:
                    returned.classes('is-path-' + self.paths.returns[node['id']].state)
