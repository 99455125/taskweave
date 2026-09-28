"""Execution result detail and renderer component."""

import json
from pathlib import Path
from nicegui import ui
from taskweave.core.validation import TaskError
from taskweave.desktop.display import image_reference


def document_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


class ResultViewer:
    def __init__(self, controller, button):
        self.controller, self.button = controller, button

    async def step_result_dialog(self, run, step, attempt_id=None):
        current = await self.controller.call('run.get', run_id=run['run_id'])
        if attempt_id is None:
            attempt = next((a for a in reversed(current['attempts']) if a['step_id'] == step['step_id'] and a['valid'] and a['status'] == 'SUCCEEDED'), None)
            attempt_id = attempt['attempt_id'] if attempt else None
        refs = [r for r in current['results'] if r['attempt_id'] == attempt_id]
        stored = {}
        for ref in refs:
            value = await self.controller.call('result.read', result_id=ref['result_id'])
            ref['name'] = value.get('name', Path(ref['locator']).name)
            value['result_id'] = ref['result_id']
            stored[ref['name']] = value
        data = stored.get('data', {}).get('data')
        views = stored.get('data', {}).get('views', [])
        renderers = self.controller.result_renderers
        with ui.dialog() as dialog, ui.card().classes('w-full max-w-5xl'):
            ui.label(step['name'] + ' · 运行结果').classes('text-lg font-medium')
            if not refs:
                ui.label('本步骤已成功完成，没有保存结果。')
            else:
                with ui.tabs().classes('w-full') as tabs:
                    view_tabs = [ui.tab(v['title']) for v in views]
                    raw_tab = ui.tab('原始数据')
                with ui.tab_panels(tabs, value=(view_tabs + [raw_tab])[0]).classes('w-full'):
                    for view, tab in zip(views, view_tabs):
                        with ui.tab_panel(tab):
                            try:
                                from taskweave.core.validation import pointer
                                payload = pointer(data, view.get('pointer', ''))
                                kind = renderers.get(view['renderer'], {}).get('type', 'json')
                                await self.render_result_view(kind, payload, stored)
                            except (TaskError, ValueError, TypeError, KeyError) as exc:
                                ui.label('该展示暂不可用：' + str(exc)).classes('text-red-700')
                                ui.code(document_text(data), language='json').classes('w-full')
                    with ui.tab_panel(raw_tab):
                        ui.code(document_text(data), language='json').classes('w-full')
            ui.button('关闭', on_click=dialog.close).props('outline')
        dialog.open()
    async def render_result_view(self, kind, payload, stored):
        if kind == 'table':
            if not isinstance(payload, dict) or not isinstance(payload.get('rows'), list):
                raise ValueError('表格需要 columns 和 rows')
            columns = [{'name': c['key'], 'label': c.get('label', c['key']), 'field': c['key'], 'align': 'left', 'sortable': True} for c in payload.get('columns', [])]
            if not columns and payload['rows']:
                columns = [{'name': key, 'label': key, 'field': key, 'align': 'left', 'sortable': True} for key in payload['rows'][0]]
            rows = [dict(row, __row_index=i) for i, row in enumerate(payload['rows'])]
            ui.table(columns=columns, rows=rows, row_key='__row_index', pagination=20).classes('w-full').style('max-width: 100%; overflow-x: auto')
        elif kind == 'report':
            if not isinstance(payload, dict):
                raise ValueError('核对报告需要对象')
            with ui.row().classes('items-center'):
                ui.icon('check_circle' if payload.get('passed') else 'error', color='green' if payload.get('passed') else 'red')
                ui.label(payload.get('message') or ('核对通过' if payload.get('passed') else '核对未通过'))
            tables = payload.get('tables', [])
            if tables:
                with ui.tabs() as tabs:
                    labels = [ui.tab(table['title']) for table in tables]
                with ui.tab_panels(tabs, value=labels[0]).classes('w-full'):
                    for table, label in zip(tables, labels):
                        with ui.tab_panel(label):
                            await self.render_result_view('table', table, stored)
            if payload.get('query_info'):
                with ui.expansion('查询信息').classes('w-full'):
                    ui.code(document_text(payload['query_info']), language='json').classes('w-full')
        elif kind == 'image':
            import base64
            payload = image_reference(payload, stored)
            if payload.get('output'):
                image = stored[payload['output']]
                mime = image['media_type']
                path = Path(image['path'])
                if not mime.startswith('image/') or path.stat().st_size > 10 * 1024 * 1024:
                    raise ValueError('图片格式不支持或超过 10MB')
                encoded = base64.b64encode(path.read_bytes()).decode()
            else:
                encoded = payload['image_base64']
                mime = payload.get('mime_type', 'image/png')
                from taskweave.desktop.display import decode_inline_image
                decode_inline_image(encoded, mime)
            ui.image('data:' + mime + ';base64,' + encoded).classes('w-full')
        else:
            ui.code(document_text(payload), language='json').classes('w-full')
    async def result_dialog(self, result_id):
        result = await self.controller.call("result.read", result_id=result_id)
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-4xl"):
            ui.label("执行结果").classes("text-lg")
            if result.get("path"):
                ui.label(result["path"])
                if result.get("media_type", "").startswith("image/"):
                    # Send only this authorized image; no broad static task-data mount.
                    import base64

                    image = Path(result["path"])
                    if image.stat().st_size <= 10 * 1024 * 1024:
                        ui.image(
                            "data:"
                            + result["media_type"]
                            + ";base64,"
                            + base64.b64encode(image.read_bytes()).decode()
                        ).classes("w-full")
                with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                    self.button(
                        "打开文件", lambda: self.controller.open_path(result["path"])
                    )
                    self.button(
                        "打开所在位置",
                        lambda: self.controller.open_path(Path(result["path"]).parent),
                    )
            ui.code(
                document_text(result.get("preview", result.get("data", result))),
                language="json",
            ).classes("w-full")
            ui.button("关闭", on_click=dialog.close)
        dialog.open()
