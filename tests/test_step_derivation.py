"""Step copies/splits keep source history and isolate newly selected material."""
import unittest
from copy import deepcopy
from tests._core_fixture import CoreFixture, SOURCE
from taskweave.core.validation import TaskError


class StepDerivationTests(CoreFixture):
    def setUp(self):
        super().setUp()
        self.task_id = self.task()
        self.source = self.step(self.task_id, input_schema={'type': 'object', 'properties': {'value': {'type': 'string'}}},
                                bindings={'value': {'literal': 'shared'}})
        self.groups = self.app.contexts.contexts
        self.group = self.groups.create_step_context_group(self.source['step_id'], 'demo.context', 'original')
        self.capture = self.groups.append_step_context_capture(self.group['context_id'],
            {'items': [{'kind': 'text', 'content': 'source'}], 'views': [], 'operation_notes': 'notes', 'send_preview': False},
            request={'scope': 'selected'}, label='material', source_session_id='recording-session')
        self.group = self.groups.list_step_contexts(self.source['step_id'])[0]

    def params(self):
        return dict(step_id=self.source['step_id'], expected_step_hash=self.source['content_hash'], expected_hash=self.app.tasks.describe_flow(self.task_id)['definition_hash'],
                    context_revisions={self.group['context_id']: self.group['revision']})

    def test_copy_inherits_input_bindings_and_creates_independent_material(self):
        source_before = deepcopy(self.groups.get_step_context_capture(self.group['context_id'], self.capture['capture_id']))
        result = self.app.dispatch('step.copy', self.params())
        copied = self.app.steps.get(result['step_id'])
        self.assertNotEqual(copied['step_id'], self.source['step_id'])
        self.assertEqual(copied['bindings'], self.source['bindings'])
        self.assertEqual(copied['input_schema'], self.source['input_schema'])
        target = self.groups.list_step_contexts(copied['step_id'])[0]
        capture = self.groups.get_step_context_capture(target['context_id'], target['captures'][0]['capture_id'])
        self.assertNotEqual(capture['capture_id'], self.capture['capture_id'])
        for key in ('items', 'request', 'operation_notes', 'source_session_id'):
            self.assertEqual(capture[key], source_before[key])
        self.assertEqual(self.groups.get_step_context_capture(self.group['context_id'], self.capture['capture_id']), source_before)

    def test_split_keeps_source_identity_and_shared_material_in_both_steps(self):
        first, second = deepcopy(self.source), deepcopy(self.source)
        first['name'], second['name'] = 'first', 'second'
        result = self.app.dispatch('step.split', {**self.params(), 'first_document': first, 'second_document': second,
            'first_capture_ids': [self.capture['capture_id']], 'second_capture_ids': [self.capture['capture_id']]})
        self.assertEqual(self.app.steps.get(self.source['step_id'])['name'], 'first')
        self.assertEqual(self.app.steps.get(result['step_id'])['name'], 'second')
        self.assertEqual([s['step_id'] for s in self.app.steps.list(self.task_id)], [self.source['step_id'], result['step_id']])
        self.assertEqual(len(self.groups.list_step_contexts(self.source['step_id'])[0]['captures']), 1)
        self.assertEqual(len(self.groups.list_step_contexts(result['step_id'])[0]['captures']), 1)

    def test_invalid_second_code_rolls_back_first_and_new_step(self):
        before = self.app.tasks.describe_flow(self.task_id)
        with self.assertRaises(TaskError) as raised:
            self.app.dispatch('step.split', {**self.params(), 'first_document': {**self.source, 'name': 'changed'},
                'second_document': {**self.source, 'step_content': 'not valid python!'},
                'first_capture_ids': [], 'second_capture_ids': [self.capture['capture_id']]})
        self.assertEqual(raised.exception.code, "CONTENT_INVALID")
        self.assertEqual(self.app.tasks.describe_flow(self.task_id), before)
        self.assertEqual(self.app.steps.get(self.source['step_id'])['name'], self.source['name'])
        self.assertEqual(len(self.app.steps.list(self.task_id)), 1)

    def test_split_rejects_removing_output_still_referenced_by_successor(self):
        self.source = self.app.steps.save(self.task_id, {**self.source, 'output_schema': {
            'type': 'object', 'properties': {'value': {'type': 'string'}}}},
            self.source['step_id'], self.source['content_hash'])
        self.step(self.task_id, bindings={'value': {'ref': {'source': 'step', 'step_id': self.source['step_id'], 'pointer': '/value'}}})
        before = self.app.tasks.describe_flow(self.task_id)
        with self.assertRaises(TaskError) as raised:
            self.app.dispatch('step.split', {**self.params(), 'first_document': {**self.source, 'output_schema': {'type': 'object', 'properties': {}}},
                'second_document': self.source, 'first_capture_ids': [], 'second_capture_ids': []})
        self.assertEqual(raised.exception.code, 'STEP_OUTPUT_REFERENCED')
        self.assertEqual(self.app.tasks.describe_flow(self.task_id), before)

    def test_split_rejects_stale_step_with_newer_task_hash(self):
        self.app.steps.save(self.task_id, {**self.source, 'name': 'concurrent'}, self.source['step_id'], self.source['content_hash'])
        with self.assertRaises(TaskError) as raised:
            self.app.dispatch('step.split', {**self.params(), 'first_document': self.source,
                'second_document': self.source, 'first_capture_ids': [], 'second_capture_ids': []})
        self.assertEqual(raised.exception.code, 'EDIT_CONFLICT')
        self.assertEqual(self.app.steps.get(self.source['step_id'])['name'], 'concurrent')

    def test_nested_output_dependency_is_preserved(self):
        self.source = self.app.steps.save(self.task_id, {**self.source, 'output_schema': {
            'type': 'object', 'properties': {'obj': {'type': 'object', 'properties': {'value': {'type': 'string'}}}}}},
            self.source['step_id'], self.source['content_hash'])
        self.step(self.task_id, bindings={'value': {'ref': {'source': 'step', 'step_id': self.source['step_id'], 'pointer': '/obj/value'}}})
        before = self.app.tasks.describe_flow(self.task_id)
        first = {**self.source, 'output_schema': {'type': 'object', 'properties': {'obj': {'type': 'object', 'properties': {}}}}}
        with self.assertRaises(TaskError) as raised:
            self.app.dispatch('step.split', {**self.params(), 'first_document': first,
                'second_document': self.source, 'first_capture_ids': [], 'second_capture_ids': []})
        self.assertEqual(raised.exception.code, 'STEP_OUTPUT_REFERENCED')
        self.assertEqual(self.app.tasks.describe_flow(self.task_id), before)

    def test_copy_preserves_empty_context_group_notes(self):
        empty = self.groups.create_step_context_group(self.source['step_id'], 'demo.context', 'Notes', 'Still useful')
        params = self.params()
        params['context_revisions'][empty['context_id']] = empty['revision']
        copied = self.app.dispatch('step.copy', params)
        groups = self.groups.list_step_contexts(copied['step_id'])
        notes = next(group for group in groups if group['name'] == 'Notes')
        self.assertEqual(notes['context_notes'], 'Still useful')
        self.assertEqual(notes['captures'], [])

    def test_reuse_other_task_requires_mapping_or_explicit_binding_removal(self):
        upstream = self.source
        reusable = self.step(self.task_id, input_schema={'type': 'object', 'properties': {'value': {'type': 'string'}}, 'required': ['value']},
            bindings={'value': {'ref': {'source': 'step', 'step_id': upstream['step_id'], 'pointer': '/value'}}})
        target = self.task()
        target_upstream = self.step(target)
        arguments = dict(step_id=reusable['step_id'], target_task_id=target, parent_id='root', index=1,
            expected_hash=self.app.tasks.describe_flow(self.task_id)['definition_hash'], expected_step_hash=reusable['content_hash'],
            context_revisions={}, target_expected_hash=self.app.tasks.describe_flow(target)['definition_hash'])
        with self.assertRaises(TaskError):
            self.app.dispatch('step.reuse', {**arguments, 'bindings': reusable['bindings']})
        self.assertEqual(len(self.app.steps.list(target)), 1)
        mapped = self.app.dispatch('step.reuse', {**arguments, 'bindings': {'value': {'ref': {
            'source': 'step', 'step_id': target_upstream['step_id'], 'pointer': '/value'}}}})
        self.assertEqual(mapped['bindings']['value']['ref']['step_id'], target_upstream['step_id'])
        arguments.update(index=2, target_expected_hash=self.app.tasks.describe_flow(target)['definition_hash'])
        unbound = self.app.dispatch('step.reuse', {**arguments, 'bindings': {}})
        self.assertEqual(unbound['bindings'], {})
        self.assertEqual(unbound['input_schema'], reusable['input_schema'])
        self.assertEqual(unbound['step_content'], reusable['step_content'])
        self.assertEqual(self.app.steps.get(reusable['step_id'])['bindings'], reusable['bindings'])

    def test_reuse_copies_context_across_tasks_and_rejects_stale_destination(self):
        target = self.task()
        params = {**self.params(), 'target_task_id': target, 'parent_id': 'root', 'index': 0,
                  'target_expected_hash': self.app.tasks.describe_flow(target)['definition_hash'], 'bindings': self.source['bindings']}
        result = self.app.dispatch('step.reuse', params)
        copied_group = self.groups.list_step_contexts(result['step_id'])[0]
        copied = self.groups.get_step_context_capture(copied_group['context_id'], copied_group['captures'][0]['capture_id'])
        self.assertEqual(copied['items'], self.capture['items'])
        self.assertNotEqual(copied['capture_id'], self.capture['capture_id'])
        with self.assertRaises(TaskError) as raised:
            self.app.dispatch('step.reuse', params)
        self.assertEqual(raised.exception.code, 'EDIT_CONFLICT')
        self.assertEqual(len(self.app.steps.list(target)), 1)

    def test_split_keeps_actual_trial_history_on_original_step(self):
        from uuid import uuid4
        run = self.app.trial_step(self.source['step_id'], {'value': 'shared'}, str(uuid4()))
        done = self.app.coordinator.wait(run['run_id'])
        self.assertEqual(done['status'], 'SUCCEEDED', done)
        self.app.runs.end_instance('run', run['run_id'])
        attempts = self.app.storage.query('SELECT * FROM step_attempts WHERE step_id=?', (self.source['step_id'],))
        result = self.app.dispatch('step.split', {**self.params(), 'first_document': {**self.source, 'name': 'original part'},
            'second_document': {**self.source, 'name': 'new part'},
            'first_capture_ids': [self.capture['capture_id']], 'second_capture_ids': [self.capture['capture_id']]})
        self.assertEqual(self.app.storage.query('SELECT * FROM step_attempts WHERE step_id=?', (self.source['step_id'],)), attempts)
        self.assertEqual(self.app.storage.query('SELECT * FROM step_attempts WHERE step_id=?', (result['step_id'],)), [])
        self.assertEqual(self.app.runs.output(run['run_id'], self.source['step_id']), {'value': 'shared'})
