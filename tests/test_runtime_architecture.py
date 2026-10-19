"""Worker transport preserves JSON envelopes and lifecycle behavior."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock


class WorkerTransportTests(unittest.TestCase):
    def test_transport_serializes_messages_and_closes_gracefully(self):
        from taskweave.infrastructure.worker_transport import WorkerTransport
        transport = WorkerTransport('/tmp/unused', None)
        pipe = Mock()
        process = Mock()
        process.is_alive.side_effect = [True, False, False]
        transport.pipe, transport.process = pipe, process
        transport.send({'kind': 'probe', 'scope': {'run_id': 'r'}})
        self.assertEqual(json.loads(pipe.send.call_args.args[0])['scope'], {'run_id': 'r'})
        pipe.recv.return_value = '{"kind":"Heartbeat"}'
        self.assertEqual(transport.receive(), {'kind': 'Heartbeat'})
        transport.stop()
        self.assertEqual(json.loads(pipe.send.call_args.args[0]), {'kind': 'close'})
        process.join.assert_called_once_with(2)
        process.terminate.assert_not_called()
        process.close.assert_called_once()
        pipe.close.assert_called_once()
        self.assertIsNone(transport.process)
        self.assertIsNone(transport.pipe)

    def test_forced_stop_terminates_without_close_message(self):
        from taskweave.infrastructure.worker_transport import WorkerTransport
        transport = WorkerTransport('/tmp/unused', None)
        pipe, process = Mock(), Mock()
        process.is_alive.side_effect = [True, True, False]
        transport.pipe, transport.process = pipe, process
        transport.stop(force=True)
        pipe.send.assert_not_called()
        process.terminate.assert_called_once()
        process.join.assert_called_once_with(3)


class RuntimePortTests(unittest.TestCase):
    def test_coordinator_writes_and_receipts_use_independent_ports(self):
        from taskweave.infrastructure.run_coordinator import Coordinator
        writes = SimpleNamespace(finish_run=Mock())
        leases = SimpleNamespace(command_receipt=lambda command, run, body, action: action())
        coordinator = Coordinator(None, None, None, None, None, None, None, '/tmp/unused',
                                  recover=False, writes=writes, leases=leases)
        coordinator._done('run', 'PAUSED')
        writes.finish_run.assert_called_once_with('run', 'PAUSED', None, False)
        self.assertEqual(coordinator._receipt('cmd', 'run', {}, lambda: {'status': 'PAUSED'}),
                         {'status': 'PAUSED'})

    def test_pool_routes_trials_by_task_and_executions_by_run_using_query_only_store(self):
        from taskweave.infrastructure.coordinator_pool import CoordinatorPool
        rows = {'a': {'run_id': 'a', 'task_id': 't', 'mode': 'TRIAL'},
                'b': {'run_id': 'b', 'task_id': 't', 'mode': 'TRIAL'},
                'c': {'run_id': 'c', 'task_id': 't', 'mode': 'EXECUTION'}}
        queries = SimpleNamespace(recover=Mock(), run=rows.__getitem__)
        created = []
        def factory():
            child = SimpleNamespace(close=Mock())
            created.append(child)
            return child
        pool = CoordinatorPool(queries, None, None, None, None, None, None, '/tmp/unused',
                               coordinator_factory=factory)
        self.assertIs(pool._for_run('a'), pool._for_run('b'))
        self.assertIsNot(pool._for_run('a'), pool._for_run('c'))
        self.assertEqual(len(created), 2)
        queries.recover.assert_called_once()
        pool.close()
        for child in created: child.close.assert_called_once()
