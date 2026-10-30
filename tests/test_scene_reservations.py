"""Hierarchical physical resource reservation excludes aliases atomically."""
import unittest
from taskweave.infrastructure.worker_transport import WorkerTransport
from taskweave.core.validation import TaskError


class SceneReservations(unittest.TestCase):
    def test_branch_reuse_reserves_parent_and_blocks_parent_execution(self):
        parent = WorkerTransport('.', None)
        branch = WorkerTransport('.', None)
        branch.parents = (parent,)
        branch.claim('B')
        try:
            with self.assertRaises(TaskError):
                parent.claim('A')
        finally:
            branch.release()
        parent.claim('A')
        try:
            with self.assertRaises(TaskError):
                branch.claim('B')
        finally:
            parent.release()

    def test_nested_context_reservation_does_not_release_parent(self):
        parent = WorkerTransport('.', None)
        branch = WorkerTransport('.', None)
        branch.parents = (parent,)
        parent.claim('context:A')
        branch.claim('context:A')
        branch.release()
        self.assertTrue(parent.operation_lock.locked())
        parent.release()


if __name__ == '__main__': unittest.main()
