"""Object array forms preserve raw edits and validate submitted typed rows."""
import asyncio
import json
from types import SimpleNamespace
import unittest

from nicegui import ui

from nicegui.client import Client
from nicegui.page import page
from taskweave.core.validation import TaskError
from taskweave.desktop.forms import ValueForm
from taskweave.presentation.debug import InputScopeDraft


ARRAY = {'type': 'array', 'items': {'type': 'object', 'properties': {
    'name': {'type': 'string', 'minLength': 2},
    'role': {'type': 'string', 'enum': ['lead', 'member']},
    'share': {'type': 'number', 'minimum': 0, 'maximum': 100},
    'count': {'type': 'integer'}, 'active': {'type': 'boolean'}},
    'required': ['name', 'role', 'share'], 'additionalProperties': False}}
SCHEMA = {'type': 'object', 'properties': {'parties': ARRAY}, 'required': ['parties']}


class ArrayInputsTests(unittest.TestCase):
    def setUp(self):
        self.client = Client(page('/array-inputs'))

    def tearDown(self):
        self.client.delete()

    def form(self, values=None, schema=SCHEMA, **kwargs):
        with self.client:
            return ValueForm(schema, values, **kwargs)

    def test_rows_add_remove_and_type_values_without_inventing_optional_fields(self):
        form = self.form()
        editor = form.controls['parties'][1]
        self.assertTrue(hasattr(editor, 'add_row'), 'object arrays need row editing')
        with self.assertRaises(TaskError): form.values()
        with self.client: editor.add_row()
        controls = editor.rows[0]['controls']
        controls['name'].set_value('Acme')
        controls['role'].set_value('lead')
        controls['share'].set_value('0')
        self.assertEqual(form.values(), {'parties': [{'name': 'Acme', 'role': 'lead', 'share': 0}]})
        controls['active'].set_value(False)
        controls['count'].set_value('3')
        self.assertEqual(form.values()['parties'][0]['active'], False)
        self.assertEqual(form.values()['parties'][0]['count'], 3)
        with self.client: editor.remove_row(editor.rows[0])
        self.assertEqual(form.values(), {'parties': []})

    def test_invalid_numeric_draft_survives_debug_snapshot_and_resume_rebuild(self):
        form = self.form({'parties': [{'name': 'Acme', 'role': 'lead', 'share': 10}]})
        editor = form.controls['parties'][1]
        self.assertTrue(hasattr(editor, 'rows'), 'object arrays need editable rows')
        scope = InputScopeDraft()
        scope.configure(SCHEMA, {})
        editor.on_value_change(lambda e: scope.change('parties', e.value))
        editor.rows[0]['controls']['share'].set_value('12x')
        self.assertEqual(json.loads(scope.raw['parties'])[0]['share'], '12x')
        with self.assertRaises(TaskError): scope.values()
        restored = self.form(scope.raw, compact=True)
        field = restored.controls['parties'][1].rows[0]['controls']['share']
        self.assertEqual(field.value, '12x')
        field.set_value('12.5')
        scope.change('parties', restored.controls['parties'][1].value)
        self.assertEqual(scope.values()['parties'][0]['share'], 12.5)
        self.assertEqual(restored.values()['parties'][0]['share'], 12.5)

    def test_invalid_boolean_json_draft_survives_structural_repair_and_rebuild(self):
        form = self.form({'parties': '[unfinished'})
        editor = form.controls['parties'][1]
        repaired = '[{"name":"Acme","role":"lead","share":10,"active":"yes"}]'
        raw_editor = next(control for control in editor.body.descendants() if isinstance(control, ui.textarea))
        raw_editor.set_value(repaired)
        scope = InputScopeDraft()
        scope.configure(SCHEMA, {})
        scope.change('parties', editor.value)
        try:
            restored = self.form(scope.raw)
        except ValueError as exc:
            self.fail(f'Boolean draft restoration must preserve invalid raw data: {exc}')
        field = restored.controls['parties'][1].rows[0]['controls']['active']
        self.assertEqual(field.value, 'yes')
        with self.assertRaisesRegex(TaskError, 'active'):
            restored.values()
        self.assertEqual(json.loads(restored.controls['parties'][1].value)[0]['active'], 'yes')
        field.set_value(False)
        self.assertIs(restored.values()['parties'][0]['active'], False)

    def test_missing_required_row_field_identifies_row_and_field(self):
        form = self.form({'parties': [{'name': 'Acme', 'role': 'lead'}]})
        with self.assertRaisesRegex(TaskError, 'parties.*1.*share'):
            form.values()

    def test_row_constraints_reject_required_enum_range_fraction_and_string_errors(self):
        for row in [ {'name': 'Acme', 'role': 'lead'},
                     {'name': 'Acme', 'role': 'other', 'share': 2},
                     {'name': 'Acme', 'role': 'lead', 'share': 101},
                     {'name': 'Acme', 'role': 'lead', 'share': 2, 'count': '1.5'},
                     {'name': 'A', 'role': 'lead', 'share': 2}]:
            with self.subTest(row=row):
                form = self.form({'parties': [row]})
                with self.assertRaises(TaskError): form.values()

    def test_absence_and_empty_array_differ_and_defaults_leave_edited_rows(self):
        optional = {'properties': {'parties': ARRAY}}
        form = self.form(schema=optional)
        self.assertEqual(form.values(), {})
        editor = form.controls['parties'][1]
        self.assertTrue(hasattr(editor, 'add_row'))
        with self.client: editor.add_row()
        editor.rows[0]['controls']['name'].set_value('draft')
        form.apply_defaults({'parties': []})
        self.assertEqual(editor.rows[0]['controls']['name'].value, 'draft')
        with self.client: editor.remove_row(editor.rows[0])
        self.assertEqual(form.values(), {'parties': []})

    def test_trial_panel_rebuild_and_paused_submission_share_typed_rows(self):
        from taskweave.desktop.components.trial_inputs import TrialInputPanel
        from taskweave.presentation.inputs import InputSubmission

        async def scenario():
            async def call(operation, **params):
                if operation == 'task.get':
                    return {'input_schema_json': json.dumps(SCHEMA)}
                if operation == 'environment.list':
                    return []
                raise AssertionError(operation)
            panel = TrialInputPanel(SimpleNamespace(call=call), lambda: 'task', str)
            environment = ui.select(['first', 'second'], value='first')
            step = {'step_id': 'step', 'input_schema': {'properties': {}}, 'bindings': {}}
            form = await panel.render(step, environment)
            editor = form.task_form.controls['parties'][1]
            editor.add_row()
            fields = editor.rows[0]['controls']
            fields['name'].set_value('Acme')
            fields['role'].set_value('lead')
            fields['share'].set_value('unfinished')
            edits = form.task_edits()
            await form.replace('second', edits, {})
            rebuilt = form.task_form.controls['parties'][1]
            self.assertEqual(rebuilt.rows[0]['controls']['share'].value, 'unfinished')
            waiting = {'scope': 'task', 'step_id': 'step', 'schema': SCHEMA}
            drafts = {}
            submission = InputSubmission(drafts, 'request', waiting, form.input_draft)
            submission.remember()
            self.assertEqual(json.loads(drafts['request']['task']['parties'])[0]['share'], 'unfinished')
            self.assertTrue(submission.issues())
            rebuilt.rows[0]['controls']['share'].set_value('42.5')
            self.assertEqual(submission.issues(), [])
            self.assertEqual(submission.submission(),
                             ({'parties': [{'name': 'Acme', 'role': 'lead', 'share': 42.5}]}, {'step': {}}))
            self.assertEqual(form.values()['parties'][0]['share'], 42.5)

        async def mounted():
            with self.client:
                await scenario()
        asyncio.run(mounted())

    def test_readonly_scope_disables_row_edits_and_buttons(self):
        form = self.form({'parties': [{'name': 'Acme', 'role': 'lead', 'share': 2}]})
        editor = form.controls['parties'][1]
        self.assertTrue(hasattr(editor, 'disable'), 'row editors must honor readonly scopes')
        editor.disable()
        self.assertFalse(editor.add_button.enabled)
        self.assertTrue(all(not control.enabled for control in editor.rows[0]['controls'].values()))

    def test_large_integer_is_converted_without_float_rounding(self):
        form = self.form({'parties': [{'name': 'Acme', 'role': 'lead', 'share': 2,
                                      'count': '9007199254740993'}]})
        self.assertEqual(form.values()['parties'][0]['count'], 9007199254740993)

    def test_complex_schemas_and_invalid_json_keep_json_editor(self):
        for array in [ {'type': 'array', 'items': {'type': 'string'}},
                       {'type': 'array', 'items': {'type': 'object', 'properties': {'x': {'type': 'object'}}}},
                       {**ARRAY, 'prefixItems': [{'type': 'string'}]} ]:
            form = self.form({'parties': []}, {'properties': {'parties': array}})
            control = form.controls['parties'][1]
            self.assertFalse(hasattr(control, 'add_row'))
            self.assertEqual(form.values(), {'parties': []})
        form = self.form({'parties': '[unfinished'})
        control = form.controls['parties'][1]
        self.assertEqual(control.value, '[unfinished')
        with self.assertRaises(TaskError): form.values()

    def insurance_schema(self, *, enum=False):
        item = {'type': 'string', 'minLength': 1}
        if enum:
            item['enum'] = ['类型A', '机动车', '责任']
        return {'properties': {'明细': {'type': 'array', 'items': {'type': 'object', 'properties': {
            '类别': {'type': 'array', 'items': item, 'minItems': 1, 'uniqueItems': True},
            '责任限额': {'type': 'number', 'default': 1000},
            '币种': {'type': 'string', 'default': 'CNY'},
            '数值比例': {'type': 'number', 'default': 0}}, 'required': ['类别'],
            'additionalProperties': True}}}}

    def test_insurance_string_list_is_editable_with_optional_defaults_and_extensions(self):
        schema = self.insurance_schema()
        form = self.form({'明细': [{'类别': ['类型A', '机动车'], '业务扩展': {'keep': True}}]}, schema)
        editor = form.controls['明细'][1]
        self.assertTrue(hasattr(editor, 'rows'), 'simple string-list fields must keep object row editing')
        classes = editor.rows[0]['controls']['类别']
        self.assertEqual(classes.value, ['类型A', '机动车'])
        with self.client:
            classes.add_entry('责任')
            classes.remove_entry(1)
        self.assertEqual(form.values(), {'明细': [{'类别': ['类型A', '责任'], '业务扩展': {'keep': True}}]})
        with self.client: editor.add_row()
        fields = editor.rows[1]['controls']
        self.assertIn('可选', fields['责任限额'].label)
        self.assertEqual(fields['责任限额'].value, '1000')
        self.assertEqual(fields['币种'].value, 'CNY')
        self.assertEqual(fields['数值比例'].value, '0')
        with self.client: fields['类别'].add_entry('类型A')
        fields['责任限额'].set_value('')
        self.assertEqual(form.values()['明细'][1], {'类别': ['类型A'], '币种': 'CNY', '数值比例': 0})

    def test_string_list_draft_restore_preserves_blank_entry_and_unknown_values(self):
        schema = self.insurance_schema()
        form = self.form({'明细': [{'类别': ['类型A'], '业务扩展': ['keep']}]}, schema)
        editor = form.controls['明细'][1]
        self.assertTrue(hasattr(editor, 'rows'))
        with self.client: editor.rows[0]['controls']['类别'].add_entry('')
        restored = self.form({'明细': editor.value}, schema)
        self.assertEqual(restored.controls['明细'][1].rows[0]['controls']['类别'].value, ['类型A', ''])
        with self.assertRaisesRegex(TaskError, '类别'):
            restored.values()
        with self.client:
            restored.controls['明细'][1].rows[0]['controls']['类别'].remove_entry(1)
        self.assertEqual(restored.values(), {'明细': [{'类别': ['类型A'], '业务扩展': ['keep']}]})

    def test_enum_string_list_is_multiple_select_and_retains_invalid_draft_choice(self):
        schema = self.insurance_schema(enum=True)
        form = self.form({'明细': [{'类别': ['类型A', 'unknown']}]}, schema)
        editor = form.controls['明细'][1]
        self.assertTrue(hasattr(editor, 'rows'))
        classes = editor.rows[0]['controls']['类别']
        self.assertIsInstance(classes, ui.select)
        self.assertTrue(classes.multiple)
        self.assertEqual(classes.value, ['类型A', 'unknown'])
        with self.assertRaises(TaskError): form.values()
        classes.set_value(['类型A', '机动车'])
        self.assertEqual(form.values(), {'明细': [{'类别': ['类型A', '机动车']}]})

    def test_malformed_string_list_item_and_unknown_extension_survive_sibling_edits(self):
        schema = self.insurance_schema()
        form = self.form({'明细': [{'类别': ['类型A', 7], '业务扩展': {'original': 1}}]}, schema)
        editor = form.controls['明细'][1]
        self.assertTrue(hasattr(editor, 'rows'))
        editor.rows[0]['controls']['币种'].set_value('USD')
        self.assertEqual(json.loads(editor.value)[0]['类别'], ['类型A', 7])
        restored = self.form({'明细': editor.value}, schema)
        self.assertEqual(json.loads(restored.controls['明细'][1].value)[0]['业务扩展'], {'original': 1})
        with self.assertRaisesRegex(TaskError, '类别'):
            restored.values()

    def test_nested_complex_array_fields_stay_in_json_editor(self):
        schema = self.insurance_schema()
        schema['properties']['明细']['items']['properties']['类别']['items'] = {'type': 'object'}
        form = self.form({'明细': []}, schema)
        self.assertFalse(hasattr(form.controls['明细'][1], 'rows'))
