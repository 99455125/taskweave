"""The web-chat bundle contains complete dialogue and all selected attachments."""
import base64
import io
import json
import unittest
from zipfile import ZipFile
from taskweave.core.validation import TaskError
from taskweave.presentation.chat_export import chat_export_files, chat_export_zip


class ChatExportTests(unittest.TestCase):
    def test_dialogue_and_messages_and_exact_image_bytes_share_one_zip(self):
        exported={'prompt':'完整对话\ncontext-preview-1.png',
                  'messages':[{'role':'user','content':'原始对话'}],
                  'attachments':[{'name':'context-preview-1.png','title':'页面截图','mime_type':'image/png',
                                  'data':base64.b64encode(b'preview bytes').decode()}]}
        files=chat_export_files(exported)
        with ZipFile(io.BytesIO(chat_export_zip(files))) as archive:
            self.assertEqual(archive.namelist(),['conversation.txt','messages.json','context-preview-1.png'])
            self.assertEqual(archive.read('conversation.txt').decode(),exported['prompt'])
            self.assertEqual(json.loads(archive.read('messages.json')),exported['messages'])
            self.assertEqual(archive.read('context-preview-1.png'),b'preview bytes')
            self.assertIsNone(archive.testzip())

    def test_no_attachments_still_exports_downloadable_complete_conversation(self):
        with ZipFile(io.BytesIO(chat_export_zip(chat_export_files({'prompt':'只有对话📄'})))) as archive:
            self.assertEqual(archive.namelist(),['conversation.txt'])
            self.assertEqual(archive.read('conversation.txt').decode(),'只有对话📄')

    def test_duplicate_or_unsafe_attachment_names_and_invalid_data_are_rejected(self):
        for name,data in [('conversation.txt','YQ=='),('../outside.png','YQ=='),('folder/a.png','YQ=='),('C:\\a.png','YQ=='),('a.png','bad-base64!')]:
            with self.subTest(name=name,data=data),self.assertRaises(TaskError):
                chat_export_files({'prompt':'text','attachments':[{'name':name,'title':'image','mime_type':'image/png','data':data}]})
