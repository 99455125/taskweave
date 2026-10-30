"""Web-chat export has one ZIP download and a shared, read-only file preview."""
import asyncio
import base64
import io
import unittest
import tempfile
from unittest.mock import AsyncMock, patch
from zipfile import ZipFile
from nicegui import ui
from nicegui.client import Client
from nicegui.page import page
from taskweave.desktop.components.chat_export import render_chat_export


class ChatExportUITests(unittest.TestCase):
    def test_native_action_saves_one_zip_through_workspace_exports(self):
        from taskweave.application.service import Application
        from taskweave.desktop.controller import DesktopController
        async def scenario(app,client):
            controller=DesktopController(app)
            controller.native=True
            controller.open_path=AsyncMock()
            callbacks={};original_button=ui.button
            def button(*args,**kwargs):
                element=original_button(*args,**kwargs)
                if args:callbacks[args[0]]=kwargs.get('on_click')
                return element
            with client,patch('nicegui.ui.button',side_effect=button):
                render_chat_export({'prompt':'本机导出对话'},controller)
                await callbacks['下载全部（ZIP）']()
                paths=list((app.home/'exports').glob('*.zip'))
                self.assertEqual(len(paths),1)
                with ZipFile(paths[0]) as archive:
                    self.assertEqual(archive.read('conversation.txt').decode(),'本机导出对话')
                controller.open_path.assert_awaited_once_with(app.home/'exports')
        with tempfile.TemporaryDirectory() as home,Application(home) as app:
            client=Client(page('/chat-native-bundle'))
            try:asyncio.run(scenario(app,client))
            finally:client.delete()

    def test_compact_actions_export_frozen_dialogue_and_all_images_and_preview_switches(self):
        client=Client(page('/chat-bundle'))
        async def scenario():
            exported={'prompt':'完整对话📄','attachments':[
                {'name':f'context-preview-{i}.png','title':f'预览{i}','mime_type':'image/png',
                 'data':base64.b64encode(f'image-{i}'.encode()).decode()} for i in (1,2)]}
            buttons={};original_button=ui.button
            def button(*args,**kwargs):
                element=original_button(*args,**kwargs)
                if args:buttons[args[0]]=kwargs.get('on_click')
                return element
            with client,patch('nicegui.ui.button',side_effect=button):
                render_chat_export(exported)
                self.assertEqual([name for name in buttons if name.startswith('下载')],['下载全部（ZIP）'])
                exported['prompt']='changed after rendering'
                with patch('nicegui.ui.download.content') as download:
                    await buttons['下载全部（ZIP）']()
                self.assertEqual(download.call_args.kwargs['media_type'],'application/zip')
                with ZipFile(io.BytesIO(download.call_args.args[0])) as archive:
                    self.assertEqual(archive.read('conversation.txt').decode(),'完整对话📄')
                    self.assertEqual(archive.read('context-preview-2.png'),b'image-2')
                buttons['预览文件']()
                self.assertTrue(any(isinstance(e,ui.code) and '完整对话📄' in e.content for e in client.elements.values()))
                selection=next(e for e in client.elements.values() if isinstance(e,ui.select) and e._props.get('label')=='预览文件')
                selection.set_value('context-preview-2.png')
                self.assertTrue(any(isinstance(e,ui.image) and e._props.get('src','').startswith('data:image/png;base64,') for e in client.elements.values()))
        try:asyncio.run(scenario())
        finally:client.delete()

    def test_no_images_still_has_download_action(self):
        client=Client(page('/chat-text-only'))
        try:
            with client:
                render_chat_export({'prompt':'text only'})
            self.assertEqual(sum(getattr(e,'text','')=='下载全部（ZIP）' for e in client.elements.values()),1)
        finally:client.delete()
