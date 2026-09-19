import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from taskweave.desktop.workbench import Workbench


class TaskConfigRefresh(unittest.TestCase):
    def test_reopening_saved_config_reads_latest_and_preserves_step_editor(self):
        async def scenario():
            stored = {'task_id': 'task', 'name': '旧名称', 'description': '旧说明',
                      'input_schema_json': json.dumps({'type': 'object', 'properties': {}})}
            stale = dict(stored)

            async def call(operation, **values):
                self.assertEqual(values['task_id'], 'task')
                if operation == 'task.get':
                    return dict(stored)
                self.assertEqual(operation, 'task.update')
                stored.update(name=values['name'], description=values['description'],
                              input_schema_json=json.dumps(values['input_schema']))

            workbench = object.__new__(Workbench)
            workbench.controller = SimpleNamespace(call=AsyncMock(side_effect=call))
            editor = object()
            workbench.edit_controls = editor
            workbench.task_name_label = SimpleNamespace(text='旧名称')
            workbench.paint = AsyncMock()
            buttons = {}
            workbench.button = lambda label, callback, **kwargs: buttons.update({label: callback})
            fields = {}
            fake_ui = MagicMock()

            def field(label, value):
                control = MagicMock()
                control.value = value
                control.classes.return_value = control
                fields[label] = control
                return control

            fake_ui.input.side_effect = field
            fake_ui.textarea.side_effect = field
            with patch('taskweave.desktop.workbench.ui', fake_ui), \
                 patch('taskweave.desktop.workbench.SchemaEditor') as schema_editor:
                schema = {'type': 'object', 'properties': {'loginurl': {'type': 'string'}}}
                schema_editor.return_value.schema.return_value = schema
                await workbench.task_dialog(stale)
                fields['任务名称'].value = '新名称'
                fields['说明'].value = '新说明'
                await buttons['保存']()
                await workbench.task_dialog(stale)
                self.assertEqual(fields['任务名称'].value, '新名称')
                self.assertEqual(fields['说明'].value, '新说明')
                self.assertEqual(schema_editor.call_args.args[0], schema)
                self.assertIs(workbench.edit_controls, editor)
                workbench.paint.assert_not_awaited()
                self.assertEqual(stale['name'], '旧名称')

        asyncio.run(scenario())
