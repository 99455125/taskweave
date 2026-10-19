"""Planning workflows run against ordinary application data without a GUI."""
import asyncio
import importlib.util
import subprocess
import sys
import unittest


class PlanningInteractionTests(unittest.IsolatedAsyncioTestCase):
    def interaction(self, application):
        self.assertIsNotNone(importlib.util.find_spec('taskweave.presentation.planning'))
        from taskweave.presentation.planning import PlanningInteraction
        from taskweave.presentation.state import PlanningPageState
        state = PlanningPageState(plan_id='p1', generation=1)
        return PlanningInteraction(application, state), state

    async def test_late_generation_does_not_replace_new_plan_candidate(self):
        entered, release = asyncio.Event(), asyncio.Event()
        class App:
            async def call(self, operation, **params):
                entered.set()
                await release.wait()
                return {'generation_id': 'g1', 'status': 'READY', 'candidate': {'steps': []}}
        interaction, state = self.interaction(App())
        pending = asyncio.create_task(interaction.generate({'plan_id': 'p1', 'revision': 3}, 'api'))
        await entered.wait()
        state.plan_id, state.generation = 'p2', 2
        release.set()
        self.assertEqual((await pending)['generation_id'], 'g1')
        self.assertIsNone(interaction.candidate)

    async def test_save_conflict_keeps_draft_and_saved_revision(self):
        class App:
            async def call(self, operation, **params):
                raise ValueError('revision conflict')
        interaction, _ = self.interaction(App())
        editor = interaction.edit({'plan_id': 'p1', 'revision': 3, 'name': 'saved'})
        editor.change('name', 'draft')
        with self.assertRaisesRegex(ValueError, 'revision conflict'):
            await editor.save()
        self.assertEqual(editor.draft['name'], 'draft')
        self.assertEqual(editor.plan['revision'], 3)
        self.assertEqual(editor.plan['name'], 'saved')

    async def test_collection_failure_keeps_staged_evidence_then_retries(self):
        self.assertIsNotNone(importlib.util.find_spec('taskweave.presentation.context_collection'))
        from taskweave.presentation.context_collection import ContextCaptureDraft, RecordingDraft
        from taskweave.presentation.planning import PlanningCollection
        calls = []
        class App:
            async def call(self, operation, **params):
                calls.append((operation, params))
                if len(calls) == 1:
                    raise OSError('disk full')
                return {'plan': {'plan_id': 'p1', 'revision': 4}, 'group': {'context_id': 'ctx'}}
        interaction, _ = self.interaction(App())
        editor = interaction.edit({'plan_id': 'p1', 'revision': 3, 'name': 'saved'})
        draft = ContextCaptureDraft()
        draft.append({'items': [{'kind': 'text', 'content': 'evidence'}]}, {}, False)
        collection = PlanningCollection(interaction.application, editor.plan, draft)
        recording = RecordingDraft(draft, collection.record)
        with self.assertRaisesRegex(OSError, 'disk full'):
            await collection.save(recording, 'demo.page', 'context', 'notes')
        self.assertEqual(len(draft.entries), 1)
        self.assertFalse(recording.committed)
        self.assertEqual(editor.plan['revision'], 3)
        result = await collection.save(recording, 'demo.page', 'context', 'notes')
        self.assertEqual(result['group']['context_id'], 'ctx')
        self.assertEqual(editor.plan['revision'], 4)
        self.assertEqual(calls[1][1]['captures'][0]['capture']['items'][0]['content'], 'evidence')

    async def test_latest_summary_never_falls_back_to_older_ready_candidate(self):
        class App:
            async def call(self, operation, **params):
                if operation == 'plan.generation.list':
                    return [{'generation_id': 'latest'}, {'generation_id': 'older'}]
                return {'generation_id': params['generation_id'], 'status': 'BLOCKED', 'candidate': None}
        interaction, _ = self.interaction(App())
        current, candidate = await interaction.latest_generation('p1')
        self.assertTrue(current)
        self.assertEqual(candidate['generation_id'], 'latest')
        self.assertEqual(candidate['status'], 'BLOCKED')

    async def test_repeated_imports_create_independent_tasks(self):
        class App:
            count = 0
            async def call(self, operation, **params):
                self.count += 1
                return {'task_id': f't{self.count}'}
        interaction, _ = self.interaction(App())
        self.assertEqual(await interaction.import_generation('g1'), {'task_id': 't1'})
        self.assertEqual(await interaction.import_generation('g1'), {'task_id': 't2'})

    async def test_import_and_workflow_are_available_with_gui_imports_blocked(self):
        script = '''
import importlib.abc, sys, asyncio
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('nicegui', 'webview', 'taskweave.desktop', 'taskweave.infrastructure')):
            raise AssertionError(fullname)
sys.meta_path.insert(0, Block())
from taskweave.presentation.planning import PlanningInteraction
from taskweave.presentation.context_collection import ContextCaptureDraft, RecordingDraft
from taskweave.presentation.state import PlanningPageState
class App:
    async def call(self, operation, **params):
        return {'task_id': 't1'}
async def main():
    flow = PlanningInteraction(App(), PlanningPageState(plan_id='p1'))
    assert await flow.import_generation('g1') == {'task_id': 't1'}
asyncio.run(main())
import unittest
suite = unittest.defaultTestLoader.loadTestsFromName('tests.presentation.test_planning.CompletePlanningFlowTests')
result = unittest.TextTestRunner().run(suite)
sys.exit(not result.wasSuccessful())
'''
        result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

class CompletePlanningFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_save_open_copy_delete_and_create_use_current_revisions(self):
        from taskweave.presentation.planning import PlanningInteraction
        from taskweave.presentation.state import PlanningPageState
        class App:
            def __init__(self):
                self.calls = []
                self.plans = {'p1': {'plan_id': 'p1', 'name': 'one', 'revision': 1},
                              'p2': {'plan_id': 'p2', 'name': 'two', 'revision': 1}}
            async def call(self, operation, **params):
                self.calls.append((operation, params))
                if operation == 'plan.update':
                    plan = self.plans[params['plan_id']]
                    plan.update(params, revision=plan['revision'] + 1)
                    return dict(plan)
                if operation == 'plan.get': return dict(self.plans[params['plan_id']])
                if operation == 'plan.copy':
                    self.plans['copy'] = {'plan_id': 'copy', 'revision': 1, 'name': 'copy'}
                    return self.plans['copy']
                if operation == 'plan.delete':
                    del self.plans[params['plan_id']]
                    return True
                if operation == 'plan.create': return {'plan_id': 'new', 'name': params['name'], 'revision': 1}
                raise AssertionError(operation)
        app = App()
        flow = PlanningInteraction(app, PlanningPageState(plan_id='p1'))
        editor = flow.edit(dict(app.plans['p1']))
        editor.change('name', 'draft')
        self.assertTrue(await flow.open('p2'))
        self.assertEqual(app.plans['p1']['name'], 'draft')
        self.assertEqual(flow.state.plan_id, 'p2')
        flow.edit(dict(app.plans['p2']))
        copied = await flow.copy_plan(app.plans['p2'])
        self.assertEqual(flow.state.plan_id, 'copy')
        deletion = await flow.prepare_delete([app.plans['p1'], copied], copied)
        self.assertFalse(await flow.delete_plan(deletion, approved=False))
        self.assertIn('copy', app.plans)
        self.assertTrue(await flow.delete_plan(deletion, approved=True))
        self.assertEqual(flow.state.plan_id, 'p1')
        await flow.create()
        self.assertEqual(flow.state.plan_id, 'new')
        self.assertEqual(app.calls[0][0], 'plan.update')

    async def test_history_is_lazy_invalidated_and_late_load_is_rejected(self):
        from taskweave.presentation.planning import PlanningInteraction
        from taskweave.presentation.state import PlanningPageState
        calls = []
        entered, release = asyncio.Event(), asyncio.Event()
        class App:
            async def call(self, operation, **params):
                calls.append(operation)
                entered.set()
                await release.wait()
                return [{'generation_id': 'g1'}]
        flow = PlanningInteraction(App(), PlanningPageState(plan_id='p1'))
        view = flow.view_session()
        self.assertFalse(view.invalidate_history())
        self.assertEqual(calls, [])
        self.assertTrue(view.select_tab('生成记录'))
        pending = asyncio.create_task(view.load_history())
        await entered.wait()
        flow.state.plan_id = 'p2'
        release.set()
        self.assertEqual(await pending, (False, None))
        self.assertEqual(view.history_rows, [])
        self.assertFalse(flow.is_current(view.identity))

    async def test_collection_cancel_and_unchanged_save_decisions_preserve_recording(self):
        from taskweave.presentation.context_collection import CollectionSession, ContextCaptureDraft
        async def invoke(*args, **kwargs): raise AssertionError('no recording command expected')
        session = CollectionSession(ContextCaptureDraft([{'capture_id': 'cap', 'label': 'one'}]))
        session.bind(invoke, source_page='planning')
        session.fields.update(name='group', notes='notes')
        self.assertEqual(session.save_decision(True, 'group', 'notes'), 'unchanged')
        self.assertEqual(session.cancel_decision('group', 'notes'), 'close')
        session.fields['notes'] = 'draft'
        self.assertEqual(session.cancel_decision('group', 'notes'), 'confirm')
        self.assertFalse(await session.cancel('group', 'notes', approved=False))
        self.assertEqual(session.fields['notes'], 'draft')
        self.assertTrue(await session.cancel('group', 'notes', approved=True))
        session.recording.committed = True
        self.assertEqual(session.cancel_decision('group', 'notes'), 'committed')
        self.assertFalse(await session.cancel('group', 'notes', approved=True))

    async def test_candidate_actions_expose_refresh_effects_and_reject_old_parse(self):
        from taskweave.presentation.planning import PlanningInteraction
        from taskweave.presentation.state import PlanningPageState
        class App:
            async def call(self, operation, **params):
                if operation == 'plan.update': return {'plan_id': 'p1', 'revision': 2, **params}
                if operation == 'plan.generation.import': return {'task_id': 'created'}
                return {'generation_id': 'g1', 'status': 'READY', 'candidate': {'steps': []}}
        flow = PlanningInteraction(App(), PlanningPageState(plan_id='p1'))
        editor = flow.edit({'plan_id': 'p1', 'revision': 1, 'name': 'saved'})
        editor.change('name', 'draft')
        action = await flow.generate_action(editor.plan, 'api')
        self.assertEqual(editor.plan['name'], 'draft')
        self.assertEqual(flow.effects(action), ('history', 'summary', 'preview'))
        flow.state.plan_id = 'p2'
        self.assertEqual(flow.effects(action), ())
        parsed = await flow.parse_action('g1', '{}', action.identity)
        self.assertEqual(flow.effects(parsed), ())
        self.assertIsNone(flow.candidate)
        imported = await flow.import_action('g1', action.identity)
        self.assertEqual(imported.value, {'task_id': 'created'})
        self.assertEqual(flow.effects(imported), ())

    async def test_organization_updates_share_latest_fields_without_saving_draft(self):
        from taskweave.presentation.planning import PlanningInteraction
        from taskweave.presentation.state import PlanningPageState
        calls = []
        class App:
            async def call(self, operation, **params):
                calls.append((operation, params))
                return True
        flow = PlanningInteraction(App(), PlanningPageState(plan_id='p1'))
        plan = {'plan_id': 'p1', 'name': 'saved', 'revision': 3, 'category_id': None}
        editor = flow.edit(plan)
        editor.change('name', 'unsaved')
        await flow.set_organization(plan, favorite=True)
        await flow.set_organization(plan, category_id='work')
        self.assertEqual([(params['is_favorite'], params['category_id']) for _, params in calls], [(1, None), (1, 'work')])
        self.assertEqual(editor.draft['name'], 'unsaved')
        self.assertEqual(plan['name'], 'saved')

    async def test_save_failure_blocks_navigation_and_keeps_draft(self):
        from taskweave.presentation.planning import PlanningInteraction
        from taskweave.presentation.state import PlanningPageState
        class App:
            async def call(self, operation, **params): raise OSError('save failed')
        flow = PlanningInteraction(App(), PlanningPageState(plan_id='p1'))
        editor = flow.edit({'plan_id': 'p1', 'name': 'saved', 'revision': 1})
        editor.change('name', 'draft')
        with self.assertRaisesRegex(OSError, 'save failed'):
            await flow.open('p2')
        self.assertEqual(flow.state.plan_id, 'p1')
        self.assertEqual(editor.draft['name'], 'draft')

    async def test_capture_session_busy_guard_is_independent_of_controls(self):
        from taskweave.presentation.context_collection import CollectionSession, ContextCaptureDraft
        async def invoke(*args, **kwargs): return {}
        session = CollectionSession(ContextCaptureDraft())
        session.bind(invoke, source_page='planning')
        self.assertTrue(session.begin_operation(capture=True))
        self.assertFalse(session.begin_operation(capture=True))
        self.assertEqual(session.cancel_decision('', ''), 'busy')
        session.finish_operation()
        session.recording.committed = True
        self.assertFalse(session.begin_operation(capture=True))
        self.assertTrue(session.begin_operation())
        session.finish_operation()
