"""Literal argv execution with bounded drains and ownership of one process tree."""
import asyncio
import os
from pathlib import Path
import signal
import time

from taskweave.plugins.sdk import PluginError


class ProcessError(PluginError):
    """Partial results are available to library callers, not host failure JSON."""
    def __init__(self, code, message=None, *, result=None, effect_state='NOT_STARTED'):
        super().__init__(code, message)
        self.result = result
        self.effect_state = effect_state


class CommandFailureEvidence:
    """One bounded last command failure, scoped to a single host attempt.

    Business plugins own an instance and register CommandFailureResultHandler
    under their own namespace. Delegate their failure_results hook here;
    transport reuse never requires enabling/calling process plugin actions.
    """
    def __init__(self, handler_id, result_name):
        self.handler_id, self.result_name = handler_id, result_name
        self._attempt_id, self._failure = None, None

    async def run_command(self, ctx, action_id, executable, args, **options):
        self._attempt_id, self._failure = ctx.scope.attempt_id, None
        try:
            return await run_command(ctx, executable, args, **options)
        except (ProcessError, asyncio.CancelledError) as exc:
            partial = getattr(exc, 'result', None)
            if partial is not None:
                self._failure = {'action_id': action_id,
                    'error_code': getattr(exc, 'code', 'CANCELLED'),
                    'effect_state': 'UNKNOWN', 'result': dict(partial)}
            raise

    async def failure_results(self, ctx, error):
        from taskweave.plugins.sdk import ResultRequest
        if self._attempt_id != ctx.scope.attempt_id or self._failure is None:
            return []
        return [ResultRequest(self.handler_id, self.result_name, self._failure)]


def redact_text(text, values):
    for value in sorted(set(values), key=len, reverse=True):
        if value:
            text = text.replace(value, '[REDACTED]')
    return text


def validate_limits(timeout_seconds, max_output_bytes):
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 1800:
        raise ProcessError('PROCESS_LIMIT_INVALID', 'timeout_seconds must be 1–1800')
    if type(max_output_bytes) is not int or not 1024 <= max_output_bytes <= 1048576:
        raise ProcessError('PROCESS_LIMIT_INVALID', 'max_output_bytes must be 1024–1048576 per stream')


class _WindowsJob:
    """Assign a suspended child to a kill-on-close job before resuming threads.

    Standard Win32 Job/Toolhelp APIs prevent the spawn-before-assignment race.
    A restrictive enclosing job may reject assignment: fail closed, kill child.
    """
    def __init__(self):
        import ctypes
        from ctypes import wintypes as w
        self.ctypes, self.w = ctypes, w
        self.api = ctypes.WinDLL('kernel32', use_last_error=True)
        signatures = {
            'CreateJobObjectW': ([w.LPVOID, w.LPCWSTR], w.HANDLE),
            'SetInformationJobObject': ([w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD], w.BOOL),
            'OpenProcess': ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            'AssignProcessToJobObject': ([w.HANDLE, w.HANDLE], w.BOOL),
            'CreateToolhelp32Snapshot': ([w.DWORD, w.DWORD], w.HANDLE),
            'Thread32First': ([w.HANDLE, w.LPVOID], w.BOOL),
            'Thread32Next': ([w.HANDLE, w.LPVOID], w.BOOL),
            'OpenThread': ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            'ResumeThread': ([w.HANDLE], w.DWORD),
            'CloseHandle': ([w.HANDLE], w.BOOL),
        }
        for name, (args, result) in signatures.items():
            method = getattr(self.api, name)
            method.argtypes, method.restype = args, result

        class Basic(ctypes.Structure):
            _fields_ = [('PerProcessUserTimeLimit', ctypes.c_longlong), ('PerJobUserTimeLimit', ctypes.c_longlong),
                ('LimitFlags', w.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t), ('MaximumWorkingSetSize', ctypes.c_size_t),
                ('ActiveProcessLimit', w.DWORD), ('Affinity', ctypes.c_size_t), ('PriorityClass', w.DWORD), ('SchedulingClass', w.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in ('ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount', 'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]
        class Extended(ctypes.Structure):
            _fields_ = [('BasicLimitInformation', Basic), ('IoInfo', IO), ('ProcessMemoryLimit', ctypes.c_size_t),
                ('JobMemoryLimit', ctypes.c_size_t), ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), 'CreateJobObjectW failed')
        limits = Extended()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise OSError(ctypes.get_last_error(), 'SetInformationJobObject failed')

    def attach_and_resume(self, pid):
        c, w, api = self.ctypes, self.w, self.api
        process = api.OpenProcess(0x0100 | 0x0001, False, pid)  # SET_QUOTA | TERMINATE
        if not process:
            raise OSError(c.get_last_error(), 'OpenProcess failed')
        try:
            if not api.AssignProcessToJobObject(self.handle, process):
                raise OSError(c.get_last_error(), 'AssignProcessToJobObject failed')
        finally:
            api.CloseHandle(process)
        class Thread(c.Structure):
            _fields_ = [('dwSize', w.DWORD), ('cntUsage', w.DWORD), ('th32ThreadID', w.DWORD),
                        ('th32OwnerProcessID', w.DWORD), ('tpBasePri', w.LONG), ('tpDeltaPri', w.LONG), ('dwFlags', w.DWORD)]
        snapshot = api.CreateToolhelp32Snapshot(0x00000004, 0)  # SNAPTHREAD
        if snapshot == w.HANDLE(-1).value:
            raise OSError(c.get_last_error(), 'thread snapshot failed')
        resumed = False
        try:
            entry = Thread()
            entry.dwSize = c.sizeof(entry)
            present = api.Thread32First(snapshot, c.byref(entry))
            while present:
                if entry.th32OwnerProcessID == pid:
                    thread = api.OpenThread(0x0002, False, entry.th32ThreadID)
                    if not thread:
                        raise OSError(c.get_last_error(), 'OpenThread failed')
                    try:
                        if api.ResumeThread(thread) == 0xFFFFFFFF:
                            raise OSError(c.get_last_error(), 'ResumeThread failed')
                        resumed = True
                    finally:
                        api.CloseHandle(thread)
                present = api.Thread32Next(snapshot, c.byref(entry))
            if not resumed:
                raise OSError('suspended child thread unavailable')
        finally:
            api.CloseHandle(snapshot)

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


async def _terminate_tree(process, job):
    if job is not None:
        job.close()
        # Cancellation during spawn can leave an unassigned suspended parent.
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
    elif os.name == 'posix':
        # The parent may already have exited while descendants hold its pipes.
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        await asyncio.sleep(.2)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    elif process.returncode is None:
        process.kill()
    await process.wait()


async def run_command(ctx, executable: str, args: list[str], *, cwd: str, env: dict,
                      stdin: bytes | None, timeout_seconds: int = 60,
                      max_output_bytes: int = 65536) -> dict:
    """No shell. Explicit env overlays the inherited environment, never logged.

    Wrap ctx in RedactingContext for resolved secret values. Escaped POSIX
    descendants which deliberately create a new session cannot be reclaimed by
    process-group ownership; commands must not daemonize.
    """
    validate_limits(timeout_seconds, max_output_bytes)
    if ctx.cancelled():
        raise ProcessError('CANCELLED')
    if not isinstance(executable, str) or not executable or '\x00' in executable or not isinstance(args, list) or any(not isinstance(x, str) or '\x00' in x for x in args):
        raise ProcessError('PROCESS_ARGUMENT_INVALID')
    if not isinstance(env, dict) or any(not isinstance(k, str) or not k or '=' in k or '\x00' in k or not isinstance(v, str) or '\x00' in v for k, v in env.items()):
        raise ProcessError('PROCESS_ENVIRONMENT_INVALID')
    if stdin is not None and not isinstance(stdin, bytes):
        raise ProcessError('PROCESS_STDIN_INVALID')
    try:
        directory = Path(cwd).expanduser().resolve(strict=True)
        if not directory.is_dir():
            raise ValueError()
    except (TypeError, OSError, ValueError, RuntimeError) as exc:
        raise ProcessError('PROCESS_DIRECTORY_INVALID') from exc
    values = tuple(getattr(ctx, 'redaction_values', ()))
    # Retain one longest-secret lookahead so a secret crossing the byte budget
    # is redacted before truncation. Memory remains bounded by explicit inputs.
    secret_bytes = max((len(x.encode('utf-8')) for x in values), default=0)
    capture_limit = max_output_bytes + secret_bytes
    buffers = {'stdout': bytearray(), 'stderr': bytearray()}
    totals = {'stdout': 0, 'stderr': 0}
    started = time.monotonic()
    process, job, spawn = None, None, None
    tasks = []

    async def drain(stream, name):
        while True:
            block = await stream.read(8192)
            if not block:
                return
            totals[name] += len(block)
            available = capture_limit - len(buffers[name])
            if available > 0:
                buffers[name].extend(block[:available])

    async def feed():
        try:
            if stdin:
                process.stdin.write(stdin)
                await process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            process.stdin.close()

    def result():
        output = {'exit_code': process.returncode,
                  'duration_ms': round((time.monotonic() - started) * 1000)}
        for name in buffers:
            text = redact_text(bytes(buffers[name]).decode('utf-8', errors='replace'), values)
            encoded = text.encode('utf-8')
            output[name] = encoded[:max_output_bytes].decode('utf-8', errors='ignore')
            output[name + '_truncated'] = totals[name] > max_output_bytes or len(encoded) > max_output_bytes
        return output

    try:
        options = {'start_new_session': True} if os.name == 'posix' else {}
        if os.name == 'nt':
            job = _WindowsJob()
            options['creationflags'] = 0x00000004 | 0x00000200  # SUSPENDED | NEW_PROCESS_GROUP
        if ctx.cancelled():
            raise ProcessError('CANCELLED')
        spawn = asyncio.create_task(asyncio.create_subprocess_exec(executable, *args, cwd=str(directory),
            env={**os.environ, **env}, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, **options))
        # Keep the eventual process handle if cancellation lands during spawn.
        process = await asyncio.shield(spawn)
        if job is not None:
            try:
                job.attach_and_resume(process.pid)
            except OSError as exc:
                job.close()
                if process.returncode is None:
                    process.kill()
                await process.communicate()
                raise ProcessError('PROCESS_TREE_SETUP_FAILED') from exc
        tasks = [asyncio.create_task(drain(process.stdout, 'stdout')),
                 asyncio.create_task(drain(process.stderr, 'stderr')),
                 asyncio.create_task(feed()), asyncio.create_task(process.wait())]
        complete = asyncio.gather(*tasks)
        deadline = started + timeout_seconds
        error = None
        while not complete.done():
            if ctx.cancelled():
                error = 'CANCELLED'
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                error = 'PROCESS_TIMEOUT'
                break
            await asyncio.wait({complete}, timeout=min(.05, remaining))
        if error:
            await _terminate_tree(process, job)
        await complete
        output = result()
        ctx.log('INFO', f'process exit_code={output["exit_code"]} stdout_truncated={output["stdout_truncated"]} stderr_truncated={output["stderr_truncated"]}'
                + (f' code={error}' if error else ''))
        if error:
            raise ProcessError(error, result=output, effect_state='UNKNOWN')
        return output
    except asyncio.CancelledError as exc:
        if process is None and spawn is not None:
            while not spawn.done():
                try:
                    await asyncio.shield(spawn)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if not spawn.cancelled() and spawn.exception() is None:
                process = spawn.result()
        if process is not None:
            if not tasks:
                tasks = [asyncio.create_task(drain(process.stdout, 'stdout')),
                         asyncio.create_task(drain(process.stderr, 'stderr'))]
                process.stdin.close()
            # Host timeout cancels the action task; finish ownership cleanup.
            cleanup = asyncio.create_task(_terminate_tree(process, job))
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    continue
            await cleanup
            await asyncio.gather(*tasks, return_exceptions=True)
            # Compatible with cancellation semantics: rethrow the same error,
            # while reusable diagnostic wrappers can retain final safe output.
            exc.result = result()
            exc.effect_state = 'UNKNOWN'
            exc.code = 'CANCELLED'
        raise
    except FileNotFoundError as exc:
        raise ProcessError('PROCESS_EXECUTABLE_NOT_FOUND') from exc
    except PermissionError as exc:
        raise ProcessError('PROCESS_PERMISSION_DENIED') from exc
    except OSError as exc:
        raise ProcessError('PROCESS_START_FAILED') from exc
    finally:
        if job is not None:
            job.close()
        # Normal exit also releases any remaining owned children; no background
        # commands are retained after the action returns.
        if process is not None and os.name == 'posix':
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
