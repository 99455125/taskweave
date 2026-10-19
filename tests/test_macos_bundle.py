"""Frozen desktop bootstrap must preserve local state and work without a shell."""

import json
import os
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from taskweave.desktop.bundle import (
    BUNDLED_PLUGINS, bundled_browser_path, initialize_bundled_plugins,
)
from taskweave.core.validation import TaskError


class BundleTests(unittest.TestCase):
    def test_bundle_resource_lookup_without_cwd(self):
        with tempfile.TemporaryDirectory() as root:
            browsers = Path(root) / 'browsers'
            browsers.mkdir()
            with patch('sys.frozen', True, create=True), patch('sys._MEIPASS', root, create=True):
                self.assertEqual(bundled_browser_path(), browsers)
            with patch('sys.frozen', False, create=True):
                self.assertIsNone(bundled_browser_path())

    def test_existing_plugin_config_is_unchanged(self):
        with tempfile.TemporaryDirectory() as home:
            p = Path(home) / 'plugins.json'
            original = b'{"format": 1, "enabled": ["utility"]}\n'
            p.write_bytes(original)
            self.assertFalse(initialize_bundled_plugins(Path(home), BUNDLED_PLUGINS))
            self.assertEqual(p.read_bytes(), original)

    def test_macos_resources_browser_is_found_with_frameworks_meipass(self):
        with tempfile.TemporaryDirectory() as root:
            contents = Path(root) / 'TaskWeave.app/Contents'
            browsers = contents / 'Resources/browsers'
            browsers.mkdir(parents=True)
            with patch('sys.frozen', True, create=True), patch('sys.platform', 'darwin'), \
                 patch('sys.executable', str(contents / 'MacOS/TaskWeave')), \
                 patch('sys._MEIPASS', str(contents / 'Frameworks'), create=True):
                self.assertEqual(bundled_browser_path(), browsers.resolve())

    def test_new_workspace_enables_all_eleven(self):
        with tempfile.TemporaryDirectory() as home:
            self.assertTrue(initialize_bundled_plugins(Path(home), BUNDLED_PLUGINS))
            p = Path(home) / 'plugins.json'
            self.assertEqual(set(json.loads(p.read_text())['enabled']), {
                'playwright', 'ocr', 'tidb', 'utility', 'file', 'process', 'ssh',
                'baota_dashboard', 'wordpress', 'uniapp', 'wechat_dev',
            })
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)

    def test_invalid_existing_plugin_config_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as home:
            p = Path(home) / 'plugins.json'
            p.write_text('{"format": 2, "enabled": []}')
            before = p.read_bytes()
            with self.assertRaises(TaskError):
                initialize_bundled_plugins(Path(home), BUNDLED_PLUGINS)
            self.assertEqual(p.read_bytes(), before)

    def test_child_dispatch_precedes_gui_import(self):
        launcher = Path(__file__).resolve().parents[1] / 'packaging/macos/taskweave_launcher.py'
        class ChildDispatched(Exception):
            pass
        with patch('multiprocessing.freeze_support', side_effect=ChildDispatched), patch.dict(os.environ, {}):
            with self.assertRaises(ChildDispatched):
                runpy.run_path(str(launcher), run_name='__main__')

    def test_existing_workspace_lock_is_respected(self):
        from taskweave.infrastructure.locking import InstanceLock
        with tempfile.TemporaryDirectory() as home:
            path = Path(home) / 'coordinator.lock'
            owner = InstanceLock(path)
            try:
                with self.assertRaisesRegex(TaskError, 'Another coordinator'):
                    InstanceLock(path)
            finally:
                owner.close()

    def test_initialization_never_writes_plugin_config_while_locked(self):
        from taskweave.infrastructure.locking import InstanceLock
        with tempfile.TemporaryDirectory() as home:
            root = Path(home)
            owner = InstanceLock(root / 'coordinator.lock')
            try:
                with self.assertRaises(TaskError):
                    initialize_bundled_plugins(root, BUNDLED_PLUGINS)
                self.assertFalse((root / 'plugins.json').exists())
            finally:
                owner.close()

    def test_frozen_application_failure_is_synchronous_and_releases_log_handler(self):
        import logging
        from nicegui import ui
        from taskweave.desktop.launcher import launch
        handlers = list(logging.getLogger().handlers)
        with tempfile.TemporaryDirectory() as home, patch('sys.frozen', True, create=True), \
             patch('taskweave.application.service.Application', side_effect=TaskError('INSTANCE_RUNNING')), \
             patch.object(ui, 'run') as run:
            with self.assertRaises(TaskError):
                launch(home)
            run.assert_not_called()
        self.assertEqual(logging.getLogger().handlers, handlers)

    def test_preflight_error_writes_redacted_startup_log_before_native_alert(self):
        from taskweave.desktop.bundle import main
        with tempfile.TemporaryDirectory() as home:
            (Path(home) / 'plugins.json').write_text('{"format":99,"enabled":[]}')
            alert = MagicMock()
            with patch.dict('sys.modules', {'AppKit': MagicMock(NSAlert=alert)}):
                self.assertEqual(main(['--home', home]), 1)
            log = Path(home) / 'logs/server.log'
            self.assertTrue(log.is_file())
            text = log.read_text()
            self.assertIn('PLUGIN_CONFIG_INVALID', text)
            self.assertIn('startup', text)
            self.assertIn(str(log), alert.alloc.return_value.init.return_value.setInformativeText_.call_args.args[0])
