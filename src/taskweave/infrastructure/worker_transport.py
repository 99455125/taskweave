"""Spawn-worker lifecycle and JSON IPC, independent of run state transitions."""
import json
import multiprocessing
import os
from taskweave.core.validation import dumps
from taskweave.infrastructure.worker import worker_main


class WorkerTransport:
    def __init__(self, home, factory):
        self.home, self.factory = home, factory
        self.process = self.pipe = None
        self.cancel = multiprocessing.get_context('spawn').Event()

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
        self.pipe.send(dumps(message))

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
