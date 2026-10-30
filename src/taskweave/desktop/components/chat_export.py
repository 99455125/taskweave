"""A compact preview and single download for the frozen web-chat request."""
import asyncio
import base64
from nicegui import ui

from taskweave.presentation.chat_export import chat_export_files, chat_export_zip


def render_chat_export(exported, controller=None, *, filename='taskweave-chat.zip'):
    files = chat_export_files(exported)

    async def download():
        content = await asyncio.to_thread(chat_export_zip, files)
        if controller is not None and controller.native:
            path = await controller.save_chat_bundle(content)
            ui.notify('文件包已保存：' + str(path), timeout=8000)
        else:
            ui.download.content(content, filename=filename, media_type='application/zip')

    def preview():
        with ui.dialog() as dialog, ui.card().classes('tw-chat-files-preview w-full max-w-4xl'):
            with ui.row().classes('w-full items-center justify-between'):
                ui.label('导出文件预览').classes('text-lg font-semibold')
                ui.button(icon='close', on_click=dialog.close).props('flat round dense aria-label=关闭文件预览')
            selected = ui.select({item.name: item.name + ' · ' + item.title for item in files},
                                 value=files[0].name, label='预览文件').props('outlined dense').classes('w-full')
            area = ui.column().classes('tw-chat-file-content w-full min-w-0')

            def paint():
                item = next(item for item in files if item.name == selected.value)
                area.clear()
                with area:
                    ui.label(f'{len(item.content):,} 字节').classes('text-xs text-gray-500')
                    if item.mime_type.startswith('image/'):
                        ui.image('data:' + item.mime_type + ';base64,' + base64.b64encode(item.content).decode()).classes('w-full')
                    else:
                        ui.code(item.content.decode('utf-8'), language='json' if item.mime_type == 'application/json'
                                else '').classes('w-full tw-chat-file-text')
            selected.on_value_change(lambda _: paint())
            paint()
            with ui.row().classes('w-full justify-end gap-2'):
                ui.button('关闭', on_click=dialog.close).props('outline')
        dialog.open()

    with ui.row().classes('tw-chat-export w-full items-center justify-between gap-3 flex-wrap'):
        ui.label(f'文件包 · {len(files)} 个文件 · 对话与所选附件').classes('text-sm text-gray-500')
        with ui.row().classes('gap-2 flex-wrap'):
            ui.button('预览文件', icon='visibility', on_click=preview).props('flat dense')
            ui.button('下载全部（ZIP）', icon='download', on_click=download).props('outline dense')
