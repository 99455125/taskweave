"""Bounded reads from an explicitly configured local file root."""
import asyncio
import base64
import csv
import io
import json
from pathlib import Path
from taskweave.plugins.sdk import AuthoringContribution, CapabilitySpec, PluginError


MAX_BYTES = 1024 * 1024


def source_path(ctx, inputs):
    values = {**ctx.environment, **ctx.task_parameters}
    root = values.get('file_root')
    if not isinstance(root, str) or not root.strip():
        raise PluginError('FILE_ROOT_REQUIRED', '请在环境或任务变量 file_root 中设置允许读取的目录')
    try:
        root = Path(root).expanduser().resolve(strict=True)
        path = (root / inputs['path']).resolve(strict=True)
        path.relative_to(root)
        if not root.is_dir() or not path.is_file():
            raise ValueError()
    except (ValueError, OSError, RuntimeError) as exc:
        raise PluginError('FILE_PATH_INVALID', '文件不存在、不是普通文件或超出 file_root') from exc
    return root, path


def read_file(ctx, inputs):
    root, path = source_path(ctx, inputs)
    limit = inputs.get('max_bytes', MAX_BYTES)
    if type(limit) is not int or not 1 <= limit <= MAX_BYTES:
        raise PluginError('FILE_LIMIT_INVALID', 'max_bytes 必须在 1 到 1048576 之间')
    if ctx.cancelled():
        raise PluginError('CANCELLED')
    try:
        with path.open('rb') as stream:
            data = stream.read(limit + 1)
    except OSError as exc:
        raise PluginError('FILE_READ_FAILED', '文件无法读取') from exc
    if len(data) > limit:
        raise PluginError('FILE_TOO_LARGE', '文件超过读取上限；未返回部分文件，避免执行残缺 SQL')
    if ctx.cancelled():
        raise PluginError('CANCELLED')
    format = inputs.get('format', 'text')
    encoding = inputs.get('encoding', 'utf-8-sig')
    try:
        if format == 'base64':
            content, encoding = base64.b64encode(data).decode('ascii'), None
        else:
            text = data.decode(encoding)
            if format == 'text':
                content = text
            elif format == 'json':
                content = json.loads(text)
                json.dumps(content, allow_nan=False)
            elif format == 'csv':
                reader = csv.DictReader(io.StringIO(text), delimiter=inputs.get('delimiter', ','))
                headers = reader.fieldnames or []
                if not headers or any(not header.strip() for header in headers) or len(set(headers)) != len(headers):
                    raise ValueError('missing or duplicate CSV header')
                content = list(reader)
                if any(None in row or any(value is None for value in row.values()) for row in content):
                    raise ValueError('CSV row width differs from header')
            else:
                raise ValueError('format')
    except (UnicodeError, LookupError, ValueError, csv.Error) as exc:
        raise PluginError('FILE_FORMAT_INVALID', '编码或文件内容与指定格式不符；未返回部分内容') from exc
    return {'path': path.relative_to(root).as_posix(), 'format': format, 'content': content,
            'encoding': encoding, 'size_bytes': len(data)}


class ReadFile:
    spec = CapabilitySpec('file.read', '完整读取 file_root 内的本地文件，返回文本、JSON、CSV 或 Base64；超限不截断',
        {'type': 'object', 'properties': {
            'path': {'type': 'string', 'minLength': 1},
            'format': {'enum': ['text', 'json', 'csv', 'base64']},
            'encoding': {'enum': ['utf-8', 'utf-8-sig', 'gb18030', 'utf-16', 'latin-1']},
            'max_bytes': {'type': 'integer', 'minimum': 1, 'maximum': MAX_BYTES},
            'delimiter': {'type': 'string', 'minLength': 1, 'maxLength': 1},
        }, 'required': ['path'], 'additionalProperties': False},
        {'type': 'object', 'properties': {'path': {'type': 'string'}, 'format': {'type': 'string'},
            'content': {}, 'encoding': {'type': ['string', 'null']}, 'size_bytes': {'type': 'integer'}},
            'required': ['path', 'format', 'content', 'encoding', 'size_bytes'], 'additionalProperties': False},
        'READ', retry_safe=True)
    async def preflight(self, ctx, inputs):
        source_path(ctx, inputs)
        return []
    async def execute(self, ctx, inputs):
        return await asyncio.to_thread(read_file, ctx, inputs)
    async def verify(self, ctx, inputs, output): return []


class FilePlugin:
    def manifest(self):
        return {'id': 'file', 'api_version': 1, 'package_version': '0.1.0', 'core_requires': '>=0.1,<1',
                'config_variables': [{'key': 'file_root', 'type': 'string', 'required': True,
                                     'description': '明确允许读取的本地目录；相对文件路径与符号链接不得逃逸此目录'}]}
    def actions(self): return {'file.read': ReadFile()}
    def tools(self): return {}
    def result_handlers(self): return {}
    def resource_providers(self): return {}
    def authoring(self, selected_ids):
        return AuthoringContribution(
            'file.read 读取显式 file_root 目录内文件，path 为观察或用户提供的路径。默认 text/utf-8-sig，最多 1MB，超过上限报错而非截断。content 是完整文本或所选 JSON/CSV/Base64 数据；不得猜测路径或把 Base64 当 SQL。SQL 文本经 data 返回和输入绑定交给 tidb.execute_sql，插件不直接互相调用。读取不等于执行；不把用户文件内容写进日志。',
            examples=('''async def run(ctx, inputs):
    document = await ctx.call("file.read", {"path": inputs["sql_file"], "format": "text"})
    return ctx.result(data=document)''',))
    async def collect_context(self, provider_id, ctx, request, *, include_view=True):
        raise PluginError('CONTEXT_PROVIDER_UNAVAILABLE')
    async def lint(self, document): return []
    async def diagnose(self, error, refs): return []
