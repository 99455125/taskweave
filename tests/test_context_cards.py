"""Context edits are flushed before actions; stale target refreshes cannot win."""

import asyncio
import unittest
from unittest.mock import AsyncMock

from nicegui import ui
from nicegui.client import Client
from nicegui.page import page

from taskweave.desktop.contexts import (
    ContextCards,
    ContextCaptureDraft,
    ContextTargetPicker,
    context_ai_items,
    context_hidden_parameters,
    context_target_options,
    context_surface_defaults,
)
from taskweave.desktop.forms import ValueForm


class ContextCardTests(unittest.TestCase):
    def setUp(self):
        self.client = Client(page('/context-test'))

    def tearDown(self):
        self.client.delete()

    def run_scenario(self, scenario):
        async def within_client():
            with self.client:
                await scenario()
        asyncio.run(within_client())

    def test_shared_preview_keeps_all_views_and_raw_items_and_discards_stale_render(self):
        from taskweave.desktop.contexts import show_context_preview

        async def scenario():
            calls = []
            async def render(kind, data, stored):
                calls.append((kind, data))
                ui.label(data['text'])
            capture = {'items': [{'content': '原始证据'}], 'views': [
                {'title': '预览一', 'renderer': 'text-view', 'data': {'text': '第一项'}},
                {'title': '预览二', 'renderer': 'text-view', 'data': {'text': '第二项'}},
            ]}
            dialog = await show_context_preview('采集标题', capture,
                {'text-view': {'type': 'text'}}, render, redact_on_display=False)
            self.assertTrue(dialog.value)
            self.assertEqual(len(calls), 2)
            texts = [getattr(e, 'text', '') for e in dialog.descendants()]
            self.assertIn('第一项', texts)
            self.assertIn('第二项', texts)
            self.assertTrue(any('原始证据' in str(getattr(e, 'content', '')) for e in dialog.descendants()))
            dialog.close()
            active = True
            async def stale_render(*args):
                nonlocal active
                active = False
            stale = await show_context_preview('过期采集', capture, {}, stale_render,
                redact_on_display=False, is_active=lambda: active)
            self.assertFalse(stale.value)
        self.run_scenario(scenario)

    def test_group_card_shows_summary_and_has_no_stacked_editors(self):
        async def scenario():
            entry = dict(context_id='one', provider_id='test.page', name='名称', context_notes='说明', captures=[{'capture_id':'capture-one','label': '项一'}])
            edit = AsyncMock()
            cards = ContextCards([entry], AsyncMock(), AsyncMock(), recollect=edit)
            self.assertIn('名称', cards.cards['one']._props['label'])
            self.assertFalse(cards.cards['one'].value)
            self.assertIn('项一', [item.text for item in cards.cards['one'].descendants() if getattr(item, 'text', None)])
            self.assertEqual(len(entry['captures']), 1)
            self.assertNotIn('editors', cards.__dict__)
            cards.panel.delete()
        self.run_scenario(scenario)

    def test_target_refresh_discards_out_of_order_response(self):
        async def scenario():
            slow, started = asyncio.Event(), asyncio.Event()
            count = 0
            async def load():
                nonlocal count
                count += 1
                if count == 1:
                    started.set()
                    await slow.wait()
                    return {'session_id': 'old', 'targets': []}
                return {'session_id': 'new', 'targets': [
                    {'target_id': 'second', 'label': '第二个窗口', 'request': {'target_id': 'second', 'opaque': 'value'}}
                ]}
            with ui.column() as panel:
                picker = ContextTargetPicker(load)
            first = asyncio.create_task(picker.refresh())
            await started.wait()
            await picker.refresh()
            slow.set()
            await first
            picker.select.value = 'second'
            self.assertEqual(picker.selection(), ({'target_id': 'second', 'opaque': 'value'}, 'new'))
            panel.delete()
        self.run_scenario(scenario)

    def test_plugin_target_options_auto_select_only_single_target(self):
        async def scenario():
            responses = [
                {'session_id': 'one', 'targets': [
                    {'target_id': 'first', 'label': '第一个页面', 'request': {'target_id': 'first'}}
                ]},
                {'session_id': 'many', 'targets': [
                    {'target_id': 'first', 'label': '第一个页面', 'request': {'target_id': 'first'}},
                    {'target_id': 'second', 'label': '第二个页面', 'request': {'target_id': 'second'}},
                ]},
            ]

            async def load():
                return responses.pop(0)

            options = context_target_options({
                'x-taskweave-context-targets': {
                    'selector_label': '浏览器页面',
                    'parameter_mode_label': '新建页面',
                    'auto_select_single': True,
                    'hide_parameters_when_selected': True,
                }
            })
            with ui.column() as panel:
                picker = ContextTargetPicker(load, options)
            await picker.refresh()
            self.assertEqual(picker.select.value, 'first')
            self.assertFalse(picker.uses_parameters)
            await picker.refresh()
            self.assertEqual(picker.select.value, '')
            self.assertTrue(picker.uses_parameters)
            self.assertEqual(picker.select.options[''], '新建页面')
            self.assertEqual(picker.select._props['label'], '浏览器页面')
            panel.delete()

        self.run_scenario(scenario)

    def test_context_cards_move_entries_and_keep_order_for_ai(self):
        async def scenario():
            entries = [
                dict(context_id='a', provider_id='test.page', name='A', item={'content': 'A'}),
                dict(context_id='b', provider_id='test.page', name='B', item={'content': 'B'}),
            ]
            moved = entries[1]
            move = AsyncMock()
            cards = ContextCards(entries, AsyncMock(), AsyncMock(), move=move)
            await cards.move_entry(moved, 'up')
            move.assert_awaited_once_with(moved, 'up')
            self.assertEqual([item['context_id'] for item in cards.entries], ['b', 'a'])
            self.assertEqual([item['content'] for item in context_ai_items(cards.entries)], ['B', 'A'])
            cards.panel.delete()
        self.run_scenario(scenario)

    def test_capture_draft_stages_new_items_and_reversible_existing_deletes(self):
        draft = ContextCaptureDraft([{'capture_id': 'old', 'label': '旧项'}])
        old = draft.entries[0]
        new = draft.append({'items': [{'content': 'new'}], 'views': [{'title': 'new'}]}, {'scope': 'viewport'}, True, label='新项')
        draft.move(new, 'up')
        draft.remove(old)
        self.assertEqual([entry.get('label') for entry in draft.entries], ['新项'])
        payload = draft.payload()[0]
        self.assertEqual(payload | {'captured_at': None}, {'capture': {'items': [{'content': 'new'}], 'views': [{'title': 'new'}]}, 'request': {'scope': 'viewport'}, 'include_view': True, 'source_session_id': None, 'source_page': 'planning', 'captured_at': None, 'label': '新项', 'operation_notes': '', 'send_preview': False})
        self.assertTrue(payload['captured_at'])
        draft.undo_delete(old)
        self.assertEqual([entry.get('capture_id') for entry in draft.entries], [None, 'old'])

    def test_capture_draft_restores_multiple_deleted_items_in_any_undo_order(self):
        draft = ContextCaptureDraft([{'capture_id': key, 'label': key} for key in 'ABC'])
        a, b, _ = draft.entries
        draft.remove(a); draft.remove(b)
        draft.undo_delete(a); draft.undo_delete(b)
        self.assertEqual([item['capture_id'] for item in draft.entries], list('ABC'))

    def test_context_provider_without_target_extension_has_no_target_picker_options(self):
        self.assertIsNone(context_target_options({
            'type': 'object',
            'properties': {'table': {'type': 'string'}},
        }))

    def test_existing_page_keeps_scope_editable_and_skips_new_page_url(self):
        async def scenario():
            schema = {
                'type': 'object',
                'properties': {
                    'url': {'type': 'string'},
                    'role': {'type': 'string', 'default': 'operator'},
                    'scope': {'type': 'string', 'enum': ['viewport', 'full_page'], 'default': 'full_page'},
                },
                'required': ['url'],
                'x-taskweave-context-targets': {
                    'hide_parameters_when_selected': True,
                    'keep_parameters_when_selected': ['scope'],
                },
            }
            hidden = context_hidden_parameters(schema, target_selected=True)
            with ui.column() as panel:
                form = ValueForm(schema)
            form.hide_fields(hidden)
            self.assertEqual(hidden, {'url', 'role'})
            self.assertTrue(form.fields['scope'].visible)
            self.assertFalse(form.fields['url'].visible)
            self.assertEqual(form.values(exclude=hidden), {'scope': 'full_page'})
            form.controls['scope'][1].value = 'viewport'
            self.assertEqual(form.values(exclude=hidden), {'scope': 'viewport'})
            form.hide_fields(set())
            self.assertTrue(form.fields['url'].visible)
            panel.delete()
        self.run_scenario(scenario)

    def test_plugin_declares_planning_only_form_default(self):
        schema = {
            'properties': {'scope': {'type': 'string', 'default': 'full_page'}},
            'x-taskweave-context-surface-defaults': {'planning': {'scope': 'viewport'}},
        }
        self.assertEqual(context_surface_defaults(schema, 'planning'), {'scope': 'viewport'})
        self.assertEqual(context_surface_defaults(schema, 'step'), {})
        self.assertEqual(schema['properties']['scope']['default'], 'full_page')
