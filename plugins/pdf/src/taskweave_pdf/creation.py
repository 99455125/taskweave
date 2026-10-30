"""Plain-text layout and exclusive publication of a new local PDF."""
from contextlib import closing, contextmanager
import ctypes
import hashlib
import io
import json
import os
import sys
import zlib
from pathlib import Path
import tempfile
from threading import RLock

from taskweave.plugins.sdk import PluginError

MAX_TEXT = 100000
FONT_NAME = 'TaskWeavePDFSans-Regular'
FONT_FILE = Path(__file__).resolve().parent / 'fonts' / (FONT_NAME + '.ttf')
_RENDER_LOCK = RLock()  # All PDFium calls, including imports and cleanup, must be serialized.


def destination(ctx, inputs):
    if (not isinstance(inputs, dict) or set(inputs) != {'path', 'text'}
            or not isinstance(inputs['path'], str) or not inputs['path'].strip()
            or '\x00' in inputs['path']
            or not isinstance(inputs['text'], str) or len(inputs['text']) > MAX_TEXT):
        raise PluginError('PDF_INPUT_INVALID', '需要 path 与 text；文本最多 100000 字符')
    values = {**ctx.environment, **ctx.task_parameters}
    root_value = values.get('pdf_root')
    if not isinstance(root_value, str) or not root_value.strip():
        raise PluginError('PDF_ROOT_REQUIRED', '请在环境或任务变量 pdf_root 中设置允许创建 PDF 的目录')
    try:
        root = Path(root_value).expanduser().resolve(strict=True)
        candidate = root / inputs['path']
        if not root.is_dir() or candidate.suffix.lower() != '.pdf':
            raise ValueError()
        # Resolve parents but never follow the final symlink, including dangling links.
        parent = candidate.parent.resolve(strict=True)
        parent.relative_to(root)
        if not parent.is_dir():
            raise ValueError()
        path = parent / candidate.name
        if path.exists() or path.is_symlink():
            raise PluginError('PDF_TARGET_EXISTS', '目标已存在；PDF 创建不会覆盖已有文件')
    except (ValueError, OSError, RuntimeError) as exc:
        raise PluginError('PDF_PATH_INVALID', '目标必须是 pdf_root 内的 .pdf 路径，且父目录已存在') from exc
    return root, path


def check_cancelled(ctx):
    if ctx.cancelled():
        raise PluginError('CANCELLED')


def font_and_text(text):
    try:
        font_data = FONT_FILE.read_bytes()
        metrics = json.loads(zlib.decompress(FONT_FILE.with_suffix('.metrics.zlib').read_bytes()))
        if metrics['sha256'] != hashlib.sha256(font_data).hexdigest():
            raise ValueError('font and metrics do not match')
    except (OSError, ValueError, KeyError, zlib.error) as exc:
        raise PluginError('PDF_FONT_UNAVAILABLE', '随包中文字体或字符度量无法加载，请检查安装或打包资源') from exc
    text = text.replace('\r\n', '\n').replace('\r', '\n').expandtabs(4)
    characters = metrics['characters']
    for char in set(text) - {'\n'}:
        if ord(char) < 32 or 0x7f <= ord(char) < 0xa0 or str(ord(char)) not in characters:
            raise PluginError('PDF_TEXT_UNSUPPORTED', '文本含控制字符或随包字体未覆盖的字符')
    return (font_data, metrics), text


@contextmanager
def load_font(pdfium, document, font_data, metrics, text):
    # Assign one CID per Unicode character to preserve aliases and supplementary
    # characters on Windows as well as platforms with 32-bit wchar_t.
    chars = sorted(set(text) - {'\n'})
    if not chars:
        yield None, {}
        return
    codes = {char: index for index, char in enumerate(chars, 1)}
    glyphs = bytearray(b'\0\0')
    mapping = [
        '/CIDInit /ProcSet findresource begin 12 dict begin begincmap',
        '/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> def',
        '/CMapName /TaskWeaveUnicode def /CMapType 2 def',
        '1 begincodespacerange <0000> <FFFF> endcodespacerange',
    ]
    for start in range(0, len(chars), 100):
        chunk = chars[start:start + 100]
        mapping.append(f'{len(chunk)} beginbfchar')
        for char in chunk:
            glyphs.extend(metrics['characters'][str(ord(char))][0].to_bytes(2, 'big'))
            mapping.append(f'<{codes[char]:04X}> <{char.encode("utf-16-be").hex().upper()}>')
        mapping.append('endbfchar')
    mapping.append('endcmap CMapName currentdict /CMap defineresource pop end end')
    data_buffer = (ctypes.c_ubyte * len(font_data)).from_buffer_copy(font_data)
    glyph_buffer = (ctypes.c_ubyte * len(glyphs)).from_buffer_copy(glyphs)
    handle = pdfium.raw.FPDFText_LoadCidType2Font(
        document, data_buffer, len(font_data), '\n'.join(mapping).encode('ascii'),
        glyph_buffer, len(glyphs))
    if not handle:
        raise PluginError('PDF_FONT_UNAVAILABLE', 'PDFium 无法加载随包中文字体')
    try:
        yield handle, codes
    finally:
        pdfium.raw.FPDFFont_Close(handle)


def render(ctx, stream, font, text):
    import pypdfium2 as pdfium
    raw = pdfium.raw
    width, height = 595.2755905511812, 841.8897637795277  # A4 in points.
    margin, size, leading = 48, 12, 18
    font_data, metrics = font
    scale = size / metrics['units_per_em']
    available = width - 2 * margin
    top = height - margin - metrics['ascent'] * scale
    bottom = margin - metrics['descent'] * scale
    try:
        with pdfium.PdfDocument.new() as document:
            with load_font(pdfium, document, font_data, metrics, text) as (loaded, codes):
                page = document.new_page(width, height)
                y = top

                def draw(line):
                    nonlocal y, page
                    check_cancelled(ctx)
                    if y < bottom:
                        page.gen_content()
                        page.close()
                        page = document.new_page(width, height)
                        y = top
                    if line:
                        handle = raw.FPDFPageObj_CreateTextObj(document, loaded, size)
                        if not handle:
                            raise PluginError('PDF_RENDER_FAILED', '无法创建 PDF 文本对象')
                        with closing(pdfium.PdfObject(handle, pdf=document)) as obj:
                            values = (ctypes.c_uint32 * len(line))(*(codes[char] for char in line))
                            if not raw.FPDFText_SetCharcodes(obj, values, len(line)):
                                raise PluginError('PDF_RENDER_FAILED', '无法写入 PDF 文本')
                            obj.set_matrix(pdfium.PdfMatrix(1, 0, 0, 1, margin, y))
                            page.insert_obj(obj)
                    y -= leading

                for paragraph in text.split('\n'):
                    line, used = [], 0
                    for index, char in enumerate(paragraph):
                        if index % 256 == 0:
                            check_cancelled(ctx)
                        advance = metrics['characters'][str(ord(char))][1] * scale
                        if line and used + advance > available:
                            draw(''.join(line))
                            line, used = [], 0
                        line.append(char)
                        used += advance
                    draw(''.join(line))
                page.gen_content()
                page.close()
                check_cancelled(ctx)
                # Save into memory first: OS write errors must not be swallowed by
                # a ctypes callback. Only the Python file write below touches disk.
                buffer = io.BytesIO()
                # PDFium 8076's subsetter rewrites supplementary ToUnicode values
                # to U+0000. Preserve the full font for these characters until fixed.
                flags = 0 if any(ord(char) > 0xffff for char in text) else raw.FPDF_SUBSET_NEW_FONTS
                document.save(buffer, flags=flags)
                check_cancelled(ctx)
                stream.write(buffer.getbuffer())
                return len(document)
    except pdfium.PdfiumError as exc:
        raise PluginError('PDF_RENDER_FAILED', 'PDFium 创建或保存 PDF 失败') from exc


def create_pdf(ctx, inputs):
    root, path = destination(ctx, inputs)
    check_cancelled(ctx)
    temporary = None
    result = None
    try:
        with _RENDER_LOCK:
            check_cancelled(ctx)
            font, text = font_and_text(inputs['text'])
            with tempfile.NamedTemporaryFile(prefix='.taskweave-pdf-', suffix='.tmp', dir=path.parent,
                                             delete=False) as stream:
                temporary = Path(stream.name)
                pages = render(ctx, stream, font, text)
                stream.flush()
                os.fsync(stream.fileno())
                size = stream.tell()
            check_cancelled(ctx)
            # Unlike replace/rename on POSIX, link fails if another writer created the target.
            os.link(temporary, path)
        result = {'path': path.relative_to(root).as_posix(), 'page_count': pages, 'size_bytes': size}
        return result
    except FileExistsError as exc:
        raise PluginError('PDF_TARGET_EXISTS', '目标已存在；PDF 创建不会覆盖已有文件') from exc
    except OSError as exc:
        raise PluginError('PDF_WRITE_FAILED', 'PDF 写入或发布失败，请检查目录权限及文件系统是否支持硬链接') from exc
    finally:
        if temporary is not None:
            primary_error = sys.exc_info()[1]
            try:
                temporary.unlink(missing_ok=True)
            except OSError as cleanup_error:
                warning = ('PDF_TEMP_CLEANUP_FAILED: 临时文件清理失败，请检查 '
                           + temporary.relative_to(root).as_posix()
                           + f'（{type(cleanup_error).__name__}）')
                if result is not None:
                    # Publication is complete; make cleanup visible without turning
                    # a successfully created document into an apparent write failure.
                    result['cleanup_warning'] = warning
                else:
                    raise PluginError(getattr(primary_error, 'code', 'PDF_WRITE_FAILED'),
                                      f'{primary_error}; {warning}') from primary_error
