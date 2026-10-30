"""Complete web-chat files and ZIP packaging, without UI or model calls."""
import base64
import binascii
from dataclasses import dataclass
import io
import json
from pathlib import PurePosixPath, PureWindowsPath
from zipfile import ZIP_DEFLATED, ZipFile

from taskweave.core.validation import TaskError


@dataclass(frozen=True)
class ChatExportFile:
    name: str
    content: bytes
    mime_type: str
    title: str


def chat_export_files(exported):
    files = [ChatExportFile('conversation.txt', exported['prompt'].encode('utf-8'),
                            'text/plain', '完整对话')]
    if 'messages' in exported:
        files.append(ChatExportFile('messages.json', json.dumps(exported['messages'], ensure_ascii=False,
            indent=2, allow_nan=False).encode('utf-8'), 'application/json', '对话消息记录'))
    names = {item.name for item in files}
    for item in exported.get('attachments', []):
        name = item['name']
        if (not isinstance(name, str) or not name or name in {'.', '..'} or '\x00' in name
                or PurePosixPath(name).name != name or PureWindowsPath(name).name != name or name in names):
            raise TaskError('FORM_INVALID', '导出附件文件名无效或重复：' + str(name))
        try:
            content = base64.b64decode(item['data'], validate=True)
        except (ValueError, TypeError, binascii.Error) as exc:
            raise TaskError('FORM_INVALID', '导出附件数据无效：' + name) from exc
        files.append(ChatExportFile(name, content, item['mime_type'], item.get('title') or name))
        names.add(name)
    return files


def chat_export_zip(files):
    output = io.BytesIO()
    with ZipFile(output, 'w', compression=ZIP_DEFLATED) as archive:
        for item in files:
            archive.writestr(item.name, item.content)
    return output.getvalue()
