"""Context edits are flushed before actions; stale target refreshes cannot win."""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock

from nicegui import ui
from nicegui.client import Client
from nicegui.events import ValueChangeEventArguments
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

    def test_preview_is_read_only_and_card_owns_preview_selection(self):
        from taskweave.desktop.contexts import render_context_draft_rows, show_context_preview

        async def scenario():
            draft = ContextCaptureDraft()
            capture = {'items': [], 'views': [{'renderer': 'text', 'data': {'text': 'preview'}}]}
            entry = draft.append(capture, {}, True, label='页面')
            with ui.column() as rows:
                render_context_draft_rows(draft, AsyncMock(), lambda: None)
            carry = next(e for e in rows.descendants() if getattr(e, 'text', '') == '携带预览')
            dialog = await show_context_preview('页面', capture, {}, AsyncMock(),
                                               redact_on_display=False)
            self.assertFalse(any(getattr(e, 'text', '') == '携带预览' for e in dialog.descendants()))
            carry.value = True
            self.assertTrue(entry['send_preview'])
            self.assertTrue(draft.payload()[0]['send_preview'])
        self.run_scenario(scenario)

    def test_draft_card_edits_title_and_notes_inline_without_losing_preview_choice(self):
        from taskweave.desktop.contexts import render_context_draft_rows

        async def scenario():
            draft = ContextCaptureDraft()
            entry = draft.append({'items': [{'source': 'demo.page', 'content': 'data'}]}, {}, False, label='页面')
            with ui.column() as rows:
                render_context_draft_rows(draft, AsyncMock(), lambda: None)
            carry = next(e for e in rows.descendants() if getattr(e, 'text', '') == '携带预览')
            self.assertFalse(carry.enabled)
            self.assertFalse(any(getattr(e, 'text', '') == '添加操作说明' for e in rows.descendants()))
            self.assertFalse(any(e._props.get('label') == '采集项标题' for e in rows.descendants()))
            title = next(e for e in rows.descendants() if getattr(e, 'text', '') == '页面')
            next(e.handler for e in title._event_listeners.values() if e.type == 'click')(None)
            title_input = next(e for e in rows.descendants() if e._props.get('label') == '采集项标题')
            title_input.value = '查询页面'
            self.assertEqual(draft.payload()[0]['label'], '查询页面')
            next(e.handler for e in title_input._event_listeners.values() if e.type == 'keydown.enter')()
            edit = next(e for e in rows.descendants() if getattr(e, 'text', '') == '编辑说明')
            next(e.handler for e in edit._event_listeners.values() if e.type == 'click')(None)
            notes = next(e for e in rows.descendants() if e._props.get('label') == '操作说明')
            notes.value = '新说明'
            self.assertEqual(draft.payload()[0]['operation_notes'], '新说明')
            done = next(e for e in rows.descendants() if getattr(e, 'text', '') == '完成')
            next(e.handler for e in done._event_listeners.values() if e.type == 'click')(None)
            self.assertEqual(entry['label'], '查询页面')
            self.assertEqual(entry['operation_notes'], '新说明')
            self.assertFalse(entry['send_preview'])
        self.run_scenario(scenario)

    def test_page_card_uses_collected_title_and_removes_private_url_parts(self):
        from taskweave.desktop.contexts import render_context_draft_rows

        async def scenario():
            draft = ContextCaptureDraft()
            entry = draft.append({'items': [{'source': 'playwright.page', 'content':
                '{"title":"记录查询", "url":"https://user:secret@example.com/contracts?token=secret#private"}'}]},
                {}, False, label='playwright.page')
            with ui.column() as rows:
                render_context_draft_rows(draft, AsyncMock(), lambda: None)
            self.assertEqual(entry['label'], '记录查询')
            texts = [getattr(e, 'text', '') for e in rows.descendants()]
            self.assertIn('https://example.com/contracts', texts)
            self.assertFalse(any('secret' in text or 'private' in text for text in texts))
        self.run_scenario(scenario)

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

    def test_context_reader_exposes_elements_recorded_actions_and_field_details(self):
        from copy import deepcopy
        from types import SimpleNamespace
        from taskweave.desktop.contexts import show_context_preview

        async def scenario():
            element={'tag':'button','name':'提交记录','role':'button','visible':True,
                     'enabled':False,'selector':{'kind':'role','value':'button','name':'提交记录'},
                     'attributes':{'data-testid':'submit-order'}}
            capture={'items':[
                {'source':'playwright.page','content':json.dumps({'title':'记录页','elements':[element],
                    'frames':[{'url':'https://example.com/frame','elements':[dict(element,name='框架按钮')]}]})},
                {'source':'playwright.recording','content':json.dumps({'events':[{'sequence':1,'kind':'click','target':element}]})},
                {'source':'plugin_b.schema','content':json.dumps({'table':'orders','columns':[{'name':'order_no','type':'string'}]})}],
                'views':[]}
            original=deepcopy(capture)
            dialog=await show_context_preview('开发材料',capture,{},AsyncMock(),redact_on_display=False)
            labels=[getattr(e,'label','') for e in dialog.descendants()]
            self.assertIn('采集数据',labels)
            self.assertIn('原文',labels)
            tables=[e for e in dialog.descendants() if 'tw-context-data-table' in e.classes]
            self.assertTrue(any(row['name']=='提交记录' for table in tables for row in table.rows))
            self.assertTrue(any(row['name']=='框架按钮' for table in tables for row in table.rows))
            self.assertTrue(any(row.get('action')=='click' for table in tables for row in table.rows))
            table=next(t for t in tables if t.rows[0]['name']=='提交记录')
            next(v.handler for v in table._event_listeners.values() if v.type=='rowClick')(
                SimpleNamespace(args=[None,table.rows[0],0]))
            trees=[e for e in self.client.elements.values() if 'tw-context-field-tree' in e.classes]
            self.assertTrue(any('data-testid' in json.dumps(t._props['nodes'],ensure_ascii=False) for t in trees))
            self.assertTrue(any('order_no' in json.dumps(t._props['nodes'],ensure_ascii=False) for t in trees))
            self.assertEqual(capture,original)
        self.run_scenario(scenario)

    def test_structured_context_reader_keeps_display_redaction_and_plain_text(self):
        from taskweave.desktop.contexts import show_context_preview
        async def scenario():
            capture={'items':[
                {'source':'plugin_b.schema','content':json.dumps({'password':'fixture-sensitive-value','columns':['order_no']})},
                {'source':'plugin_b.notes','content':'手动核对记录状态'}],'views':[]}
            dialog=await show_context_preview('材料',capture,{},AsyncMock())
            rendered=' '.join(str(getattr(e,'content',''))+json.dumps(e._props,ensure_ascii=False) for e in dialog.descendants())
            self.assertNotIn('fixture-sensitive-value',rendered)
            self.assertIn('[REDACTED]',rendered)
            self.assertIn('手动核对记录状态',rendered)
            self.assertIn('order_no',rendered)
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

    def test_saved_capture_keeps_preview_choice_in_header_and_empty_notes_out_of_body(self):
        async def scenario():
            capture = dict(capture_id='capture-one', label='项一', has_preview=True,
                           source_page='planning', items=[{'content': '原始证据'}])
            group = dict(context_id='one', name='名称', captures=[capture])
            cards = ContextCards([group], AsyncMock(), AsyncMock(), recollect=AsyncMock(),
                                 update_capture=AsyncMock(), preview_capture=AsyncMock())
            elements = list(cards.cards['one'].descendants())
            carry = next(e for e in elements if getattr(e, 'text', '') == '携带预览')
            preview = next(e for e in elements if e._props.get('icon') == 'visibility')
            self.assertIs(carry.parent_slot.parent, preview.parent_slot.parent)
            actions = carry.parent_slot.parent.parent_slot.parent
            self.assertIn('tw-context-capture-actions', actions.classes)
            self.assertIn('tw-context-capture-header', actions.parent_slot.parent.classes)
            edit = next(e for e in elements if getattr(e, 'text', '') == '编辑说明')
            metadata = next(e for e in elements if getattr(e, 'text', '') == '规划采集')
            self.assertIs(metadata.parent_slot.parent, edit.parent_slot.parent.parent_slot.parent)
            self.assertFalse(any('tw-context-staged-note-text' in e.classes for e in elements))
            self.assertFalse(any('tw-context-capture-preview' in e.classes for e in elements))
            self.assertNotIn('暂无组说明', [getattr(e, 'text', '') for e in elements])
            group_edit = next(e for e in elements if getattr(e, 'text', '') == '编辑组说明')
            recollect = next(e for e in elements if getattr(e, 'text', '') == '继续采集')
            self.assertIs(group_edit.parent_slot.parent, recollect.parent_slot.parent)
            self.assertIn('justify-end', group_edit.parent_slot.parent.classes)
            cards.panel.delete()
        self.run_scenario(scenario)

    def test_saved_capture_shows_read_only_notes_and_summary_without_preview_action(self):
        async def scenario():
            group = dict(context_id='one', name='名称', context_notes='组说明', captures=[
                dict(capture_id='capture-one', label='项一', operation_notes='打开记录查询',
                     items=[{'content': '原始证据'}]),
            ])
            cards = ContextCards([group], AsyncMock(), AsyncMock())
            texts = [getattr(e, 'text', '') for e in cards.cards['one'].descendants()]
            self.assertIn('打开记录查询', texts)
            self.assertIn('原始证据', texts)
            self.assertIn('组说明', texts)
            self.assertNotIn('已采集', texts)
            self.assertNotIn('编辑说明', texts)
            cards.panel.delete()
        self.run_scenario(scenario)

    def test_saved_capture_actions_keep_the_selected_capture_identity(self):
        async def scenario():
            first = dict(capture_id='first', label='第一项', has_preview=True, send_preview=False)
            second = dict(capture_id='second', label='第二项', has_preview=True, send_preview=False)
            group = dict(context_id='group', name='名称', captures=[first, second])
            updated, previewed, moved = [], [], []

            async def update(selected_group, selected_capture, label, **metadata):
                updated.append((selected_group, selected_capture, label, metadata))

            def preview(selected_group, selected_capture):
                previewed.append((selected_group, selected_capture))

            def move(selected_group, selected_capture, direction):
                moved.append((selected_group, selected_capture, direction))

            cards = ContextCards([group], AsyncMock(), AsyncMock(), update_capture=update,
                                 preview_capture=preview, move_capture=move, delete_capture=AsyncMock())
            rows = [e for e in cards.cards['group'].descendants() if 'tw-context-capture-row' in e.classes]
            elements = list(rows[0].descendants())
            carry = next(e for e in elements if getattr(e, 'text', '') == '携带预览')
            await carry._change_handlers[-1](ValueChangeEventArguments(
                sender=carry, client=self.client, value=True, previous_value=False))
            self.assertEqual(updated, [(group, first, '第一项', {'send_preview': True})])
            self.assertTrue(first['send_preview'])
            self.assertFalse(second['send_preview'])
            self.assertTrue(carry.enabled)
            preview_button = next(e for e in elements if e._props.get('icon') == 'visibility')
            next(e.handler for e in preview_button._event_listeners.values() if e.type == 'click')(None)
            move_down = next(e for e in elements if getattr(e, 'text', '') == '下移')
            next(e.handler for e in move_down.parent_slot.parent._event_listeners.values() if e.type == 'click')(None)
            self.assertEqual(previewed, [(group, first)])
            self.assertEqual(moved, [(group, first, 'down')])
            self.assertIn('改名', [getattr(e, 'text', '') for e in elements])
            self.assertIn('删除采集项', [getattr(e, 'text', '') for e in elements])
            cards.panel.delete()
        self.run_scenario(scenario)

    def test_saved_preview_choice_ignores_success_after_owner_changes(self):
        async def scenario():
            started, finish = asyncio.Event(), asyncio.Event()
            active = True
            capture = dict(capture_id='one', label='项一', has_preview=True, send_preview=False)
            group = dict(context_id='group', name='名称', captures=[capture])

            async def update(*args, **kwargs):
                started.set()
                await finish.wait()

            cards = ContextCards([group], AsyncMock(), AsyncMock(), update_capture=update,
                                 is_active=lambda: active)
            carry = next(e for e in cards.cards['group'].descendants()
                         if getattr(e, 'text', '') == '携带预览')
            saving = asyncio.create_task(carry._change_handlers[-1](ValueChangeEventArguments(
                sender=carry, client=self.client, value=True, previous_value=False)))
            await started.wait()
            self.assertFalse(carry.enabled)
            active = False
            finish.set()
            await saving
            self.assertFalse(capture['send_preview'])
            self.assertFalse(carry.enabled)
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
