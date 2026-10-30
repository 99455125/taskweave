"""Per-call startup samples remain durable and defer manual required inputs."""
import time

from tests._core_fixture import CoreFixture
from taskweave.core.validation import TaskError


class SequenceStartupInputsTests(CoreFixture):
    def configured(self, *, bound=False):
        task = self.task()
        step = self.step(task, input_schema={'type': 'object', 'properties': {
            'value': {'type': 'integer'}, 'optional': {'type': 'string'}}, 'required': ['value']},
            bindings={'value': {'literal': 7}} if bound else {})
        self.app.confirm_step_manual(step['step_id'], step['content_hash'])
        nodes = [{'node_id': nid, 'task_id': task, 'environment_id': None,
                  'inputs': {}, 'step_inputs': {}} for nid in ['first', 'second']]
        saved = self.app.sequences.save('Repeated calls', nodes, {'type': 'object'})
        return saved, task, step['step_id']

    def wait(self, run_id):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            run = self.app.sequences.run_get(run_id)
            if run['status'] not in {'READY', 'RUNNING'}:
                return run
            time.sleep(.03)
        self.fail('sequence did not reach a stable state')

    def test_startup_samples_freeze_per_node_and_participate_in_replay_identity(self):
        saved, _, sid = self.configured()
        values = {'first': {sid: {'value': 11}}, 'second': {sid: {'value': 22}}}
        run = self.app.sequences.prepare_start(saved['sequence_id'], 'freeze', {}, node_step_inputs=values)
        values['first'][sid]['value'] = 999
        self.assertEqual(self.app.sequences.run_get(run['sequence_run_id'])['snapshot']['node_step_inputs'],
                         {'first': {sid: {'value': 11}}, 'second': {sid: {'value': 22}}})
        self.assertEqual(self.app.sequences.get(saved['sequence_id'])['nodes'], saved['nodes'])
        same = self.app.sequences.prepare_start(saved['sequence_id'], 'freeze', {}, node_step_inputs={
            'first': {sid: {'value': 11}}, 'second': {sid: {'value': 22}}})
        self.assertEqual(same['sequence_run_id'], run['sequence_run_id'])
        with self.assertRaises(TaskError) as error:
            self.app.sequences.prepare_start(saved['sequence_id'], 'freeze', {}, node_step_inputs=values)
        self.assertEqual(error.exception.code, 'COMMAND_CONFLICT')

    def test_repeated_task_calls_receive_distinct_step_samples_at_runtime(self):
        saved, _, sid = self.configured()
        run = self.app.sequences.start(saved['sequence_id'], 'distinct', {}, node_step_inputs={
            'first': {sid: {'value': 11}}, 'second': {sid: {'value': 22, 'optional': 'second'}}})
        done = self.wait(run['sequence_run_id'])
        self.assertEqual(done['status'], 'SUCCEEDED', done)
        self.assertEqual([self.app.runs.output(n['run_id'], sid) for n in done['nodes']],
                         [{'value': 11}, {'value': 22, 'optional': 'second'}])

    def test_missing_required_step_sample_uses_existing_waiting_input(self):
        saved, _, sid = self.configured()
        run = self.app.sequences.start(saved['sequence_id'], 'blank', {}, node_step_inputs={
            'first': {sid: {'optional': 'later'}}})
        done = self.wait(run['sequence_run_id'])
        self.assertEqual(done['status'], 'WAITING_INPUT', done)
        self.assertIsNotNone(done['nodes'][0]['run_id'])
        self.assertEqual(done['nodes'][1]['run_id'], None)

    def test_unknown_or_automatically_bound_fields_are_rejected_before_creation(self):
        saved, _, sid = self.configured(bound=True)
        for values in [{'missing-node': {sid: {}}}, {'first': {'missing-step': {}}},
                       {'first': {sid: {'value': 9}}}, {'first': {sid: {'unknown': 9}}},
                       {'first': {sid: {'optional': 123}}}]:
            with self.subTest(values=values), self.assertRaises(TaskError) as error:
                self.app.sequences.prepare_start(saved['sequence_id'], str(values), {}, node_step_inputs=values)
            self.assertIn(error.exception.code, {'INPUT_INVALID', 'SCHEMA_MISMATCH'})
        self.assertEqual(self.app.sequences.run_list(), [])

    def test_task_level_samples_remain_distinct_for_repeated_calls(self):
        task = self.app.repo.create_task('Task inputs', {'type': 'object', 'properties': {
            'value': {'type': 'integer'}}, 'required': ['value']})['task_id']
        step = self.step(task, input_schema={'type': 'object', 'properties': {'value': {'type': 'integer'}},
                                          'required': ['value']},
                         bindings={'value': {'ref': {'source': 'task', 'pointer': '/value'}}})
        self.app.confirm_step_manual(step['step_id'], step['content_hash'])
        nodes = [{'node_id': nid, 'task_id': task, 'environment_id': None,
                  'inputs': {}, 'step_inputs': {}} for nid in ['first', 'second']]
        saved = self.app.sequences.save('Task startup', nodes, {'type': 'object'})
        started = self.app.sequences.start(saved['sequence_id'], 'task-inputs', {},
                                          node_inputs={'first': {'value': 3}, 'second': {'value': 8}})
        done = self.wait(started['sequence_run_id'])
        self.assertEqual(done['status'], 'SUCCEEDED', done)
        self.assertEqual([self.app.runs.output(n['run_id'], step['step_id']) for n in done['nodes']],
                         [{'value': 3}, {'value': 8}])

    def test_samples_are_reused_when_a_call_occurs_in_multiple_loop_rounds(self):
        saved, task, sid = self.configured()
        flow = {'version': 2, 'root': {'id': 'root', 'kind': 'sequence', 'children': [
            {'id': 'each', 'kind': 'foreach', 'items': {'literal': [1, 2]},
             'body': {'id': 'body', 'kind': 'sequence', 'children': [
                 {'id': 'first', 'kind': 'action', 'step_id': 'first'}]}}]}}
        saved = self.app.sequences.save('Loop samples', saved['nodes'][:1], {'type': 'object'}, flow=flow)
        started = self.app.sequences.start(saved['sequence_id'], 'loop-inputs', {},
                                          node_step_inputs={'first': {sid: {'value': 6}}})
        done = self.wait(started['sequence_run_id'])
        self.assertEqual(done['status'], 'SUCCEEDED', done)
        self.assertEqual([self.app.runs.output(n['run_id'], sid) for n in done['nodes']],
                         [{'value': 6}, {'value': 6}])
