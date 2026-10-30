"""Optional PDFium plugin for creating text-only PDFs."""
import asyncio
from taskweave.plugins.sdk import AuthoringContribution, CapabilitySpec, PluginError
from .creation import MAX_TEXT, _RENDER_LOCK, check_cancelled, create_pdf, destination, font_and_text


class CreatePdf:
    spec = CapabilitySpec('pdf.create', '在 pdf_root 内新建 PDF 并写入纯文本；中文、自动换行和分页；目标存在时报错',
        {'type': 'object', 'properties': {
            'path': {'type': 'string', 'minLength': 1},
            'text': {'type': 'string', 'maxLength': MAX_TEXT},
        }, 'required': ['path', 'text'], 'additionalProperties': False},
        {'type': 'object', 'properties': {
            'path': {'type': 'string'}, 'page_count': {'type': 'integer', 'minimum': 1},
            'size_bytes': {'type': 'integer', 'minimum': 1},
            'cleanup_warning': {'type': 'string'},
        }, 'required': ['path', 'page_count', 'size_bytes'], 'additionalProperties': False},
        'WRITE', retry_safe=False)

    async def preflight(self, ctx, inputs):
        destination(ctx, inputs)
        check_cancelled(ctx)
        def check_font():
            with _RENDER_LOCK:
                font_and_text(inputs['text'])
        await asyncio.to_thread(check_font)
        return []

    async def execute(self, ctx, inputs):
        return await asyncio.to_thread(create_pdf, ctx, inputs)

    async def verify(self, ctx, inputs, output):
        return []


class PdfPlugin:
    def manifest(self):
        return {'id': 'pdf', 'api_version': 1, 'package_version': '0.1.0', 'core_requires': '>=0.1,<1',
                'config_variables': [{'key': 'pdf_root', 'type': 'string', 'required': True,
                    'description': '允许创建 PDF 的已有本地目录；输出不得逃逸此目录，目标存在时报错'}]}

    def actions(self): return {'pdf.create': CreatePdf()}
    def tools(self): return {}
    def result_handlers(self): return {}
    def resource_providers(self): return {}
    def authoring(self, selected_ids):
        return AuthoringContribution(
            'pdf.create 在显式 pdf_root 目录内创建 PDF，参数仅 path 与 text。path 来自用户或已观察证据，后缀 .pdf，父目录须已存在。'
            'text 是纯文本，最多 100000 字符，空文本生成一页；默认 A4，随包中文字体，保留换行，自动折行和分页。'
            '不解析 HTML/Markdown，不读取或修改已有 PDF，不覆盖已有文件，不自动重试。'
            '字体不覆盖的字符（包括部分 emoji/罕见汉字）明确报错，不静默丢字。不把正文写入日志。'
            '返回 path、page_count、size_bytes；若存在 cleanup_warning，PDF 已创建但须处理残留临时文件；路径是相对 pdf_root 的本地文件路径，不是宿主结果附件引用。',
            examples=('''async def run(ctx, inputs):
    document = await ctx.call("pdf.create", {"path": inputs["pdf_path"], "text": inputs["text"]})
    return ctx.result(data=document)''',))

    async def collect_context(self, provider_id, ctx, request, *, include_view=True):
        raise PluginError('CONTEXT_PROVIDER_UNAVAILABLE')
    async def lint(self, document): return []
    async def diagnose(self, error, refs): return []
