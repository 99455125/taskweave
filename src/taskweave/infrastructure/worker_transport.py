"""Spawn-worker lifecycle and JSON IPC, independent of run state transitions."""
import json
import multiprocessing
import os
import threading
from taskweave.core.validation import TaskError
from taskweave.infrastructure.worker import worker_main


class WorkerTransport:
    def __init__(self, home, factory):
        self.home, self.factory = home, factory
        self.process = self.pipe = None
        self.session_id = None
        self.operation_lock = threading.Lock()
        self.owner_run_id = None
        self.parents = ()
        self._claims = []
        self.cancel = multiprocessing.get_context('spawn').Event()

    def claim(self, run_id):
        claimed = []
        for transport in dict.fromkeys((*self.parents, self)):
            # Context observation delegates from the parent to its branch worker.
            if (transport is not self and run_id.startswith('context:')
                    and transport.owner_run_id == run_id):
                continue
            if not transport.operation_lock.acquire(blocking=False):
                for item in reversed(claimed):
                    item.owner_run_id = None
                    item.operation_lock.release()
                raise TaskError('RUN_BUSY', '该现场正在执行或采集，请完成后再试')
            transport.owner_run_id = run_id
            claimed.append(transport)
        self._claims = claimed

    def release(self):
        claimed, self._claims = self._claims, []
        for transport in reversed(claimed):
            transport.owner_run_id = None
            transport.operation_lock.release()

    def start(self):
        if self.process and self.process.is_alive():
            return False
        ctx = multiprocessing.get_context('spawn')
        self.pipe, child = ctx.Pipe()
        self.process = ctx.Process(target=worker_main,
            args=(child, self.cancel, str(self.home), self.factory, os.getpid()), daemon=True)
        self.process.start()
        child.close()
        return True

    def send(self, message):
        try:
            encoded = json.dumps(message, ensure_ascii=False, allow_nan=False)
        except (ValueError, TypeError) as exc:
            raise TaskError("NOT_JSON", "Result must contain JSON values") from exc
        self.pipe.send(encoded)

    def poll(self, timeout):
        return self.pipe.poll(timeout)

    def receive(self):
        return json.loads(self.pipe.recv())

    def terminate(self):
        self.process.terminate()

    def stop(self, force=False):
        if self.process:
            if self.process.is_alive() and not force:
                try:
                    self.send({'kind': 'close'})
                except (OSError, EOFError):
                    pass
                self.process.join(2)
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(3)
            if self.process.is_alive():
                self.process.kill()
                self.process.join()
            self.process.close()
            self.process = None
        if self.pipe:
            self.pipe.close()
            self.pipe = None
        self.session_id = None
