"""Shared leaf execution capacity; control traversal never owns a slot."""
import threading


class ExecutionCapacity:
    def __init__(self, limit):
        self.limit = limit
        self.active = 0
        self.lock = threading.Lock()

    def try_acquire(self):
        with self.lock:
            if self.active >= self.limit:
                return False
            self.active += 1
            return True

    def release(self):
        with self.lock:
            self.active -= 1

    def resize(self, limit):
        with self.lock:
            self.limit = limit
