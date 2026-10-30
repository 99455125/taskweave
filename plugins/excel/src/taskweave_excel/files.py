"""Bounded workbook loading and atomic publication within excel_root."""
import hashlib
from contextlib import contextmanager
import io
import os
from pathlib import Path
import tempfile
import warnings
from zipfile import ZipFile, BadZipFile
from taskweave.plugins.sdk import PluginError

MAX_FILE = 20 * 1024 * 1024
MAX_EXPANDED = 100 * 1024 * 1024
COMPLEX = ('xl/drawings/', 'xl/charts/', 'xl/pivot', 'xl/activeX/', 'xl/embeddings/',
           'xl/externalLinks/', 'xl/vba', 'xl/slicer', 'xl/queryTables/', 'xl/connections',
           'xl/threadedComments/', 'customXml/', '_xmlsignatures/')


def check(ctx):
    if ctx.cancelled():
        raise PluginError('CANCELLED')


@contextmanager
def write_guard(path):
    """Serialize TaskWeave writers across workers, including snapshot loading."""
    lock = path.parent / ('.taskweave-excel-' + hashlib.sha256(os.fsencode(path)).hexdigest()[:24] + '.lock')
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise PluginError('EXCEL_FILE_BUSY', '目标文件正在写入；若上次进程异常退出，请核对后处理残留锁') from exc
    except OSError as exc:
        raise PluginError('EXCEL_WRITE_FAILED', '无法锁定目标文件') from exc
    owned = os.fstat(fd)
    try:
        os.write(fd, str(os.getpid()).encode('ascii'))
        yield
    finally:
        os.close(fd)
        try:
            current = lock.lstat()
        except FileNotFoundError:
            current = None
        if current and (current.st_dev, current.st_ino) == (owned.st_dev, owned.st_ino):
            lock.unlink()


def path_for(ctx, value, *, existing=False, writing=False):
    root_value = {**ctx.environment, **ctx.task_parameters}.get('excel_root')
    if not isinstance(root_value, str) or not root_value.strip():
        raise PluginError('EXCEL_ROOT_REQUIRED', '请配置 excel_root 本地目录')
    try:
        root = Path(root_value).expanduser().resolve(strict=True)
        if not root.is_dir() or not isinstance(value, str) or not value:
            raise ValueError()
        candidate = root / value
        if writing and candidate.is_symlink():
            raise ValueError()
        path = candidate.resolve(strict=existing)
        path.relative_to(root)
        if path.suffix.lower() != '.xlsx' or not path.parent.is_dir() or (path.exists() and not path.is_file()):
            raise ValueError()
        return root, path
    except (ValueError, OSError, RuntimeError) as exc:
        raise PluginError('EXCEL_PATH_INVALID', '需要 excel_root 内的 .xlsx 普通文件，且父目录存在') from exc


def file_bytes(path):
    try:
        with path.open('rb') as stream:
            data = stream.read(MAX_FILE + 1)
        if len(data) > MAX_FILE:
            raise PluginError('EXCEL_LIMIT', '文件超过 20 MiB')
        return data
    except OSError as exc:
        raise PluginError('EXCEL_READ_FAILED') from exc


def checked_archive(data, writing=False):
    try:
        with ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > 10000 or sum(e.file_size for e in entries) > MAX_EXPANDED:
                raise PluginError('EXCEL_LIMIT', '工作簿解压后超过上限')
            if writing and any(e.filename.startswith(COMPLEX) or e.filename.endswith('.vml') for e in entries):
                raise PluginError('EXCEL_COMPLEX_WORKBOOK', '工作簿含复杂对象，当前写入不保证保留，已保留原文件')
    except (BadZipFile, OSError) as exc:
        raise PluginError('EXCEL_FORMAT_INVALID') from exc


def load(data, *, values=False, writing=False):
    from openpyxl import load_workbook
    checked_archive(data, writing)
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            book = load_workbook(io.BytesIO(data), read_only=not writing, data_only=values,
                                 keep_links=True, rich_text=writing)
        if writing and caught:
            book.close()
            raise PluginError('EXCEL_COMPLEX_WORKBOOK', '解析器报告可能丢失内容，已保留原文件')
        return book
    except PluginError:
        raise
    except Exception as exc:
        raise PluginError('EXCEL_FORMAT_INVALID', '工作簿无法读取') from exc


def publish(ctx, book, target, *, expected=None):
    check(ctx)
    if target.is_symlink() or (expected is None and target.exists()):
        raise PluginError('EXCEL_TARGET_EXISTS', '目标已存在，未覆盖')
    temporary = None
    try:
        fd, name = tempfile.mkstemp(prefix='.taskweave-excel-', suffix='.xlsx', dir=target.parent)
        temporary = Path(name)
        with os.fdopen(fd, 'w+b') as stream:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter('always')
                book.save(stream)
            if caught:
                raise PluginError('EXCEL_WRITE_FAILED', '保存时出现内容兼容警告，未发布')
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.stat().st_size > MAX_FILE:
            raise PluginError('EXCEL_LIMIT', '输出超过文件上限')
        check(ctx)
        if expected is None:
            os.link(temporary, target)
        else:
            if target.is_symlink() or not target.is_file() or hashlib.sha256(file_bytes(target)).digest() != expected:
                raise PluginError('EXCEL_FILE_CHANGED', '文件已被其他操作修改，未覆盖')
            os.replace(temporary, target)
        return target.stat().st_size
    except FileExistsError as exc:
        raise PluginError('EXCEL_TARGET_EXISTS') from exc
    except PluginError:
        raise
    except Exception as exc:
        raise PluginError('EXCEL_WRITE_FAILED', '写入失败，未发布不完整文件') from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
