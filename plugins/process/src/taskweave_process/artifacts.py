"""Root-confined complete files staged through the existing host contract."""
import asyncio
import hashlib
import mimetypes
import os
from pathlib import Path
import stat

from taskweave.plugins.sdk import PluginError, PreparedResult

DEFAULT_TRANSFER_BYTES = 16 * 1024 * 1024
MAX_TRANSFER_BYTES = 64 * 1024 * 1024
ARTIFACT_SCHEMA = {'type': 'object', 'properties': {
    'token': {'type': 'string', 'minLength': 1}, 'name': {'type': 'string', 'minLength': 1},
    'media_type': {'type': 'string', 'minLength': 1}, 'size_bytes': {'type': 'integer', 'minimum': 0},
    'checksum': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}},
    'required': ['token', 'name', 'media_type', 'size_bytes', 'checksum'], 'additionalProperties': False}


def validate_transfer_limit(max_bytes):
    if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_TRANSFER_BYTES:
        raise PluginError('PROCESS_ARTIFACT_LIMIT_INVALID')


def confined_path(root, path, *, directory=False):
    try:
        base = Path(root).expanduser().resolve(strict=True)
        resolved = (base / path).resolve(strict=True)
        resolved.relative_to(base)
        if not base.is_dir() or not (resolved.is_dir() if directory else resolved.is_file()):
            raise ValueError()
    except (TypeError, ValueError, OSError, RuntimeError) as exc:
        raise PluginError('PROCESS_PATH_INVALID', 'Path missing, wrong type or outside configured root') from exc
    return base, resolved


def read_artifact(root, path, max_bytes):
    validate_transfer_limit(max_bytes)
    base, source = confined_path(root, path)
    # POSIX dir-fd traversal prevents parent symlink swaps after resolution.
    if os.name == 'posix':
        descriptor = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            parts = source.relative_to(base).parts
            for part in parts[:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            file_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        finally:
            os.close(descriptor)
        stream = os.fdopen(file_fd, 'rb')
    else:
        stream = source.open('rb')
    with stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode):
            raise PluginError('PROCESS_PATH_INVALID')
        if metadata.st_size > max_bytes:
            raise PluginError('PROCESS_ARTIFACT_TOO_LARGE')
        data = stream.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise PluginError('PROCESS_ARTIFACT_TOO_LARGE')
    return source.name, data


async def stage_artifact(ctx, root: str, path: str, *, max_bytes: int) -> dict:
    if ctx.cancelled():
        raise PluginError('CANCELLED')
    try:
        name, data = await asyncio.to_thread(read_artifact, root, path, max_bytes)
    except OSError as exc:
        raise PluginError('PROCESS_ARTIFACT_READ_FAILED') from exc
    return await _stage_bytes(ctx, name, data)


async def _stage_bytes(ctx, name, data):
    if ctx.cancelled():
        raise PluginError('CANCELLED')
    staged = await ctx.allocate_file(name)
    writer = asyncio.create_task(asyncio.to_thread(Path(staged.local_path).write_bytes, data))
    try:
        await asyncio.shield(writer)
        if ctx.cancelled():
            raise PluginError('CANCELLED')
    except BaseException:
        # A cancelled to_thread await does not stop the writer. Let it finish
        # before deleting the staged path so it cannot recreate a stray file.
        while not writer.done():
            try:
                await asyncio.shield(writer)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not writer.cancelled():
            writer.exception()
        Path(staged.local_path).unlink(missing_ok=True)
        raise
    return {'token': staged.token, 'name': name,
            'media_type': mimetypes.guess_type(name)[0] or 'application/octet-stream',
            'size_bytes': len(data), 'checksum': hashlib.sha256(data).hexdigest()}


class FileResultHandler:
    def schema(self):
        return {'tables': {}, 'indexes': {}}

    def prepare(self, request):
        from jsonschema import Draft202012Validator
        if not Draft202012Validator(ARTIFACT_SCHEMA).is_valid(request.payload):
            raise PluginError('PROCESS_ARTIFACT_RESULT_INVALID')
        return PreparedResult('file', staged_token=request.payload['token'], media_type=request.payload['media_type'])

    def parse(self, stored):
        return stored

    def preview(self, parsed):
        return {'renderer': 'json', 'data': parsed}


class CommandFailureResultHandler:
    """JSON diagnostic declaration reusable under any owning plugin namespace."""
    def schema(self):
        return {'tables': {}, 'indexes': {}}

    def prepare(self, request):
        from jsonschema import Draft202012Validator
        from .actions import COMMAND_SCHEMA
        schema = {'type': 'object', 'properties': {
            'action_id': {'type': 'string', 'minLength': 1},
            'error_code': {'type': 'string', 'minLength': 1},
            'effect_state': {'enum': ['UNKNOWN']}, 'result': COMMAND_SCHEMA},
            'required': ['action_id', 'error_code', 'effect_state', 'result'], 'additionalProperties': False}
        if not Draft202012Validator(schema).is_valid(request.payload):
            raise PluginError('PROCESS_COMMAND_FAILURE_RESULT_INVALID')
        return PreparedResult('json', payload=request.payload)

    def parse(self, stored):
        return stored

    def preview(self, parsed):
        return {'renderer': 'json', 'data': parsed}
