"""Owned persistent, bounded newline streams for ordinary library consumers.

No application protocol semantics live here. Callers must not daemonize or
transfer process ownership. Close reuses the finite runner's tree primitives.
"""
import asyncio
import math
import os
from pathlib import Path
import time

from .runner import ProcessError, _WindowsJob, _terminate_tree, redact_text, validate_limits


class OwnedProcessSession:
    def __init__(self, ctx, process, job, max_line_bytes, max_stderr_bytes):
        self.ctx, self.process, self.job = ctx, process, job
        self.max_line_bytes, self.max_stderr_bytes = max_line_bytes, max_stderr_bytes
        self.frames = asyncio.Queue(maxsize=8)
        self.stderr_buffer = bytearray()
        self.stderr_total = 0
        self.values = tuple(getattr(ctx, 'redaction_values', ()))
        self.lookahead = max((len(v.encode()) for v in self.values), default=0)
        self.failure = None
        self.closed = False
        self.close_task = None
        self.read_lock, self.write_lock = asyncio.Lock(), asyncio.Lock()
        self.tasks = [asyncio.create_task(self._stdout()), asyncio.create_task(self._stderr())]

    @classmethod
    async def start(cls, ctx, executable, args, *, cwd, env, max_line_bytes=1048576,
                    max_stderr_bytes=65536):
        validate_limits(60, max_stderr_bytes)
        if type(max_line_bytes) is not int or not 1024 <= max_line_bytes <= 1048576:
            raise ProcessError('PROCESS_LIMIT_INVALID')
        if ctx.cancelled():
            raise ProcessError('CANCELLED')
        if not isinstance(executable, str) or not executable or '\0' in executable or not isinstance(args, list) or any(not isinstance(a, str) or '\0' in a for a in args):
            raise ProcessError('PROCESS_ARGUMENT_INVALID')
        if not isinstance(env, dict) or any(not isinstance(k, str) or not k or '=' in k or '\0' in k or not isinstance(v, str) or '\0' in v for k,v in env.items()):
            raise ProcessError('PROCESS_ENVIRONMENT_INVALID')
        try:
            directory = Path(cwd).expanduser().resolve(strict=True)
            if not directory.is_dir():
                raise ValueError()
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            raise ProcessError('PROCESS_DIRECTORY_INVALID') from exc
        job, process = None, None
        options = {'start_new_session': True} if os.name == 'posix' else {}
        if os.name == 'nt':
            job = _WindowsJob()
            options['creationflags'] = 0x00000004 | 0x00000200
        spawn = asyncio.create_task(asyncio.create_subprocess_exec(executable, *args,
            cwd=str(directory), env={**os.environ, **env}, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, **options))
        try:
            process = await asyncio.shield(spawn)
            if job is not None:
                job.attach_and_resume(process.pid)
            if ctx.cancelled():
                raise ProcessError('CANCELLED', effect_state='UNKNOWN')
            return cls(ctx, process, job, max_line_bytes, max_stderr_bytes)
        except BaseException as exc:
            # Retain the eventual spawn handle even if the caller is cancelled.
            while not spawn.done():
                try:
                    await asyncio.shield(spawn)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if process is None and not spawn.cancelled() and spawn.exception() is None:
                process = spawn.result()
            if process is not None:
                cleanup = asyncio.create_task(_terminate_tree(process, job))
                while not cleanup.done():
                    try:
                        await asyncio.shield(cleanup)
                    except asyncio.CancelledError:
                        continue
                cleanup.result()
            elif job is not None:
                job.close()
            if isinstance(exc, FileNotFoundError):
                raise ProcessError('PROCESS_EXECUTABLE_NOT_FOUND') from exc
            if isinstance(exc, PermissionError):
                raise ProcessError('PROCESS_PERMISSION_DENIED') from exc
            raise

    async def _stdout(self):
        buffer = bytearray()
        try:
            while True:
                block = await self.process.stdout.read(8192)
                if not block:
                    if buffer:
                        raise ProcessError('PROCESS_FRAME_INCOMPLETE', effect_state='UNKNOWN')
                    return
                buffer.extend(block)
                while b'\n' in buffer:
                    offset = buffer.index(b'\n')
                    if offset > self.max_line_bytes:
                        raise ProcessError('PROCESS_FRAME_TOO_LARGE', effect_state='UNKNOWN')
                    frame = bytes(buffer[:offset]);del buffer[:offset+1]
                    try:
                        self.frames.put_nowait(frame)
                    except asyncio.QueueFull as exc:
                        raise ProcessError('PROCESS_FRAME_QUEUE_LIMIT', effect_state='UNKNOWN') from exc
                if len(buffer) > self.max_line_bytes:
                    raise ProcessError('PROCESS_FRAME_TOO_LARGE', effect_state='UNKNOWN')
        except ProcessError as exc:
            self.failure = exc
            # A protocol producer failure must reap even with an idle caller.
            # Schedule the sole close owner; do not await it from its reader.
            if self.close_task is None:
                self.close_task = asyncio.create_task(self._close())

    async def _stderr(self):
        while True:
            block = await self.process.stderr.read(8192)
            if not block:
                return
            self.stderr_total += len(block)
            remaining = self.max_stderr_bytes + self.lookahead - len(self.stderr_buffer)
            if remaining > 0:
                self.stderr_buffer.extend(block[:remaining])

    def stderr_result(self):
        text = redact_text(self.stderr_buffer.decode('utf-8', errors='replace'), self.values)
        encoded = text.encode()
        return {'stderr': encoded[:self.max_stderr_bytes].decode('utf-8', errors='ignore'),
                'stderr_truncated': self.stderr_total > self.max_stderr_bytes or len(encoded) > self.max_stderr_bytes}

    async def _bounded(self, operation, timeout_seconds):
        if type(timeout_seconds) not in (int,float) or not math.isfinite(timeout_seconds) or not 0<timeout_seconds<=1800:
            operation.close()
            raise ProcessError('PROCESS_LIMIT_INVALID')
        validate_limits(math.ceil(timeout_seconds), self.max_stderr_bytes)
        task = asyncio.create_task(operation)
        deadline = time.monotonic() + timeout_seconds
        try:
            while not task.done():
                if self.ctx.cancelled():
                    raise ProcessError('CANCELLED', effect_state='UNKNOWN')
                if self.failure:
                    raise self.failure
                if self.closed:
                    raise ProcessError('PROCESS_SESSION_CLOSED', effect_state='UNKNOWN')
                if time.monotonic() >= deadline:
                    raise ProcessError('PROCESS_TIMEOUT', effect_state='UNKNOWN')
                await asyncio.wait([task], timeout=.02)
            if self.failure:
                raise self.failure
            return task.result()
        except BaseException:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await self.close()
            raise

    async def write_line(self, data, *, timeout_seconds=60):
        if not isinstance(data, bytes) or len(data) > self.max_line_bytes or b'\n' in data:
            raise ProcessError('PROCESS_FRAME_INVALID')
        async def write():
            async with self.write_lock:
                if self.closed or self.process.returncode is not None:
                    raise ProcessError('PROCESS_SESSION_CLOSED', effect_state='UNKNOWN')
                self.process.stdin.write(data + b'\n')
                await self.process.stdin.drain()
        return await self._bounded(write(), timeout_seconds)

    async def read_line(self, *, timeout_seconds=60):
        async def read():
            async with self.read_lock:
                while self.frames.empty():
                    if self.tasks[0].done():
                        if self.failure:
                            raise self.failure
                        self.tasks[0].result()
                        raise ProcessError('PROCESS_SESSION_EXITED', effect_state='UNKNOWN')
                    await asyncio.sleep(.01)
                return self.frames.get_nowait()
        return await self._bounded(read(), timeout_seconds)

    async def _close(self):
        self.closed = True
        self.process.stdin.close()
        await _terminate_tree(self.process, self.job)
        for task in self.tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

    async def close(self):
        if self.close_task is None:
            self.close_task = asyncio.create_task(self._close())
        while not self.close_task.done():
            try:
                await asyncio.shield(self.close_task)
            except asyncio.CancelledError:
                continue
        self.close_task.result()
