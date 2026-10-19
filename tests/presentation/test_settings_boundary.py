"""Settings use cases run against ordinary ports without desktop or infrastructure."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest


class SettingsBoundaryTests(unittest.TestCase):
    def service(self, home, *, instances=()):
        self.assertIsNotNone(importlib.util.find_spec('taskweave.application.settings'))
        from taskweave.application.settings import ApplicationSettings
        privacy = SimpleNamespace(get=lambda: {'redact_for_ai': True}, update=lambda **values: values)
        authoring = SimpleNamespace(model=None)
        return ApplicationSettings(
            home, privacy=privacy, set_max_concurrency=lambda value: value,
            list_environments=lambda: [{'environment_id': 'known'}],
            list_instances=lambda: list(instances), authoring=authoring,
            model_factory=lambda url, model, key: SimpleNamespace(url=url, model=model, api_key=key),
            workspace_location=lambda: Path(home).parent / 'location.json',
        )

    def test_default_environment_validation_and_existing_settings_survive(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root)
            (home / 'workbench.json').write_text(json.dumps({'ai_request_limit_kib': 99}))
            settings = self.service(home)
            settings.set_default_environment('known')
            self.assertEqual(settings.workbench_settings()['default_environment_id'], 'known')
            self.assertEqual(settings.workbench_settings()['ai_request_limit_kib'], 99)
            from taskweave.core.validation import TaskError
            with self.assertRaises(TaskError) as caught:
                settings.set_default_environment('missing')
            self.assertEqual(caught.exception.code, 'FORM_INVALID')
            self.assertEqual(settings.workbench_settings()['default_environment_id'], 'known')

    def test_busy_workspace_rejects_copy_and_does_not_write_marker(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root) / 'old'; home.mkdir()
            (home / 'evidence.txt').write_text('retained')
            settings = self.service(home, instances=[{'run_id': 'running'}])
            from taskweave.core.validation import TaskError
            with self.assertRaises(TaskError) as caught:
                settings.migrate_workspace(Path(root) / 'new')
            self.assertEqual(caught.exception.code, 'WORKSPACE_BUSY')
            self.assertFalse((Path(root) / 'new').exists())
            self.assertFalse((Path(root) / 'location.json').exists())
            self.assertEqual((home / 'evidence.txt').read_text(), 'retained')

    def test_settings_import_has_no_desktop_or_concrete_infrastructure_dependency(self):
        self.assertIsNotNone(importlib.util.find_spec('taskweave.application.settings'))
        result = subprocess.run([sys.executable, '-c', '''
import importlib.abc
import sys
class Boundary(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('taskweave.desktop', 'taskweave.infrastructure', 'nicegui', 'webview')):
            raise AssertionError(fullname)
sys.meta_path.insert(0, Boundary())
from taskweave.application.settings import ApplicationSettings
'''], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_model_probe_requests_the_async_contract_it_accepts(self):
        import asyncio
        from unittest.mock import AsyncMock
        with tempfile.TemporaryDirectory() as root:
            service = self.service(root)
            complete = AsyncMock(return_value=SimpleNamespace(
                proposed_content='async def run(ctx, inputs):\n    return ctx.result(data={"connected": True})',
                explanation='connected',
            ))
            service.authoring.model = SimpleNamespace(complete=complete)
            self.assertTrue(asyncio.run(service.test_model())['connected'])
            messages = complete.call_args.args[0]
            self.assertIn('async def run(ctx, inputs)', messages[-1]['content'])
