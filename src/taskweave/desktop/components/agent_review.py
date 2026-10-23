"""Human acceptance on immutable execution facts with existing result renderers."""
import json
from nicegui import ui
from taskweave.desktop.components.result_viewer import ResultViewer
from taskweave.application.agent.projection import compact_record


LABELS = {'PASS': '通过', 'FAIL': '未通过', 'MISSING': '缺少证据', 'ERROR': '核对错误',
          'UNCONFIGURED': '未配置核对项', 'INCOMPLETE': '尚未完成', 'NOT_APPLICABLE': '不适用',
          'UNREVIEWED': '待人工验收', 'ACCEPTED': '人工验收通过', 'REJECTED': '人工验收未通过', 'STALE': '事实已变化，需重新验收'}
RUN_LABELS = {'READY': '就绪', 'RUNNING': '执行中', 'PAUSED': '已暂停', 'SUCCEEDED': '成功',
              'FAILED': '失败', 'INTERRUPTED': '中断', 'CANCELLED': '已结束', 'UNKNOWN': '待核对'}


class ReviewDialog:
    def __init__(self, controller, button):
        self.controller, self.button = controller, button
        self.viewer = ResultViewer(controller, button)

    async def open(self, kind, identity):
        self.kind, self.identity = kind, identity
        self.dialog = ui.dialog()
        with self.dialog, ui.card().classes('w-full max-w-6xl gap-3'):
            self.body = ui.column().classes('w-full gap-3')
        await self.refresh()
        self.dialog.open()

    async def refresh(self):
        report = await self.controller.review_report(self.kind, self.identity)
        self.report = report
        self.body.clear()
        with self.body:
            ui.label(report['title']).classes('text-xl font-semibold')
            if report['goal']:
                ui.label(report['goal']).classes('whitespace-pre-wrap')
            ui.label('版本 ' + report['definition_hash'][:16] + ' · ' + report['identity']).classes('text-xs text-gray-500')
            with ui.row().classes('gap-4'):
                ui.badge('执行：' + RUN_LABELS.get(report['run_status'], report['run_status']))
                ui.badge('自动核对：' + LABELS.get(report['automatic_status'], report['automatic_status']))
                ui.badge(LABELS[report['human_status']])
            ui.label('核对依据为本次持久化结果；步骤返回的数据仍需结合原始证据判断。').classes('text-gray-500')
            if not report['checks']:
                ui.label('尚未配置自动核对项，请查看执行路径与原始结果后填写验收依据。')
            for check in report['checks']:
                with ui.expansion(LABELS.get(check['status'], check['status']) + ' · ' + check['label']).classes('w-full border rounded'):
                    if 'actual' in check:
                        ui.label('实际：' + json.dumps(check['actual'], ensure_ascii=False))
                    if check.get('op') not in {'exists', 'all', 'any'}:
                        ui.label('要求：' + check.get('op', '') + ' ' + json.dumps(check.get('expected'), ensure_ascii=False))
                    ui.code(json.dumps(compact_record(check), ensure_ascii=False, indent=2), language='json').classes('w-full')
                    for evidence in check.get('evidence', [])[:20]:
                        self.button('查看证据', lambda e=evidence: self.evidence(e), flat=True)
                    if len(check.get('evidence', [])) > 20:
                        ui.label('其余证据可在下方执行路径中逐页查看。')
            ui.label('实际执行路径（含历史尝试和循环轮次）').classes('font-medium')
            attempts = report['path'] if self.kind == 'run' else [dict(attempt, run_id=node.get('run_id'), node_id=node['node_id'],
                name=f"{node['position'] + 1}. {node['task_name']} · {attempt.get('name', '步骤')}") for node in report['path'] for attempt in node['attempts']]
            for attempt in attempts:
                attempt.setdefault('run_id', self.identity)
            self.path_area = ui.column().classes('w-full')
            self._attempts = attempts
            self.render_path(0)
            self._flows = report.get('flow', []) if self.kind == 'run' else [dict(item, node_id=node['node_id'],
                task_label=f"{node['position'] + 1}. {node['task_name']}") for node in report['path'] for item in node.get('flow', [])]
            ui.label('控制节点与选路事实').classes('font-medium')
            self.flow_area = ui.column().classes('w-full')
            self.render_flows(0)
            with ui.expansion('输入摘要与流程事实').classes('w-full'):
                ui.code(json.dumps(compact_record({'inputs': report['inputs'], 'flow': report.get('flow', [])}), ensure_ascii=False, indent=2), language='json').classes('w-full')
            if report.get('human_decision'):
                ui.label('上次决定：' + report['human_decision']['note']).classes('whitespace-pre-wrap')
            self.note = ui.textarea('人工验收依据 / 未通过原因').props('outlined').classes('w-full')
            with ui.row().classes('gap-2'):
                self.button('刷新证据', self.refresh)
                if report['run_status'] in {'SUCCEEDED', 'FAILED', 'INTERRUPTED', 'CANCELLED'}:
                    self.button('验收通过', lambda: self.decide('ACCEPTED'), primary=True)
                    self.button('验收未通过', lambda: self.decide('REJECTED'))
                self.button('关闭', self.dialog.close)

    def render_path(self, offset):
        self.path_area.clear()
        with self.path_area:
            for attempt in self._attempts[offset:offset + 20]:
                with ui.row().classes('w-full items-center border-b py-1'):
                    ui.label(attempt.get('name', attempt['step_id']))
                    from taskweave.desktop.components.execution_details import round_label
                    ui.label(round_label(attempt.get('execution_path'))).classes('text-xs').tooltip(attempt.get('execution_path') or '主流程')
                    ui.label(RUN_LABELS.get(attempt['status'], attempt['status']) + (' · 当前有效' if attempt['valid'] else ' · 历史尝试'))
                    self.button('查看原始结果', lambda e=attempt: self.evidence(e), flat=True)
            with ui.row():
                ui.label(f'{offset + 1 if self._attempts else 0}–{min(offset + 20, len(self._attempts))} / {len(self._attempts)}')
                if offset:
                    self.button('上一页', lambda: self.render_path(max(0, offset - 20)))
                if offset + 20 < len(self._attempts):
                    self.button('下一页', lambda: self.render_path(offset + 20))

    async def evidence(self, evidence):
        run = await self.controller.call('run.get', run_id=evidence['run_id'])
        definition = json.loads(run['definition_json'])
        step = next(step for step in definition['steps'] if step['step_id'] == evidence['step_id'])
        await self.viewer.step_result_dialog(run, step, evidence['attempt_id'])

    def render_flows(self, offset):
        self.flow_area.clear()
        with self.flow_area:
            if not self._flows:
                ui.label('本次无控制节点记录。').classes('text-gray-500')
            kinds = {'if': '条件分支', 'foreach': '遍历循环', 'loop': '条件循环', 'action': '动作', 'sequence': '顺序'}
            for visit in self._flows[offset:offset + 20]:
                label = kinds.get(visit.get('kind'), visit.get('kind', '流程')) + ' · ' + RUN_LABELS.get(visit.get('status'), visit.get('status', ''))
                if visit.get('task_label'):
                    label = visit['task_label'] + ' · ' + label
                with ui.expansion(label).classes('w-full'):
                    # Full local facts, one node at a time; no silent ten-node clipping.
                    ui.code(json.dumps(visit, ensure_ascii=False, indent=2), language='json').classes('w-full')
            with ui.row():
                ui.label(f'{offset + 1 if self._flows else 0}–{min(offset + 20, len(self._flows))} / {len(self._flows)}')
                if offset:
                    self.button('上一页控制记录', lambda: self.render_flows(max(0, offset - 20)))
                if offset + 20 < len(self._flows):
                    self.button('下一页控制记录', lambda: self.render_flows(offset + 20))

    async def decide(self, decision):
        await self.controller.review_decide(self.kind, self.identity, self.report['fingerprint'], decision, self.note.value or '')
        await self.refresh()
