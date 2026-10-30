"""Plugin package boundaries and compatibility, without external services."""
import ast
import importlib
import importlib.util
import pickle
from pathlib import Path
import subprocess
import sys
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PluginArchitectureTests(unittest.TestCase):
    def test_plugins_only_use_public_host_sdk(self):
        violations = []
        for path in (ROOT / 'plugins').glob('*/src/taskweave_*/*.py'):
            for node in ast.walk(ast.parse(path.read_text())):
                names = ([node.module or ''] if isinstance(node, ast.ImportFrom)
                         else [item.name for item in node.names] if isinstance(node, ast.Import) else [])
                for name in names:
                    if name == 'taskweave' or name.startswith('taskweave.') and name != 'taskweave.plugins.sdk':
                        violations.append(f'{path.relative_to(ROOT)}:{node.lineno}: {name}')
        self.assertEqual(violations, [])

    def test_playwright_responsibilities_have_independent_owners(self):
        import taskweave_playwright as public
        owners = {
            'session': ('BrowserSession', 'page_for', '_live_context_targets'),
            'locators': ('locate', 'target_state', 'snapshot'),
            'browser_actions': ('BrowserAction', 'ReadTool'),
            'results': ('FileResult',),
            'plugin': ('PlaywrightPlugin',),
        }
        for module_name, names in owners.items():
            with self.subTest(owner=module_name):
                canonical = 'taskweave_playwright.' + module_name
                self.assertIsNotNone(importlib.util.find_spec(canonical), canonical)
                module = importlib.import_module(canonical)
                for name in names:
                    self.assertIs(getattr(public, name), getattr(module, name))
                    self.assertEqual(getattr(module, name).__module__, canonical)

    def test_session_and_results_do_not_depend_on_action_assembly(self):
        for name in ('session', 'results', 'locators'):
            canonical = 'taskweave_playwright.' + name
            spec = importlib.util.find_spec(canonical)
            self.assertIsNotNone(spec, canonical)
            for node in ast.walk(ast.parse(Path(spec.origin).read_text())):
                if isinstance(node, ast.ImportFrom) and node.level:
                    self.assertNotIn(node.module, ('plugin', 'browser_actions', None))

    def test_tidb_execution_uses_shared_database_policy_without_package_back_edge(self):
        import taskweave_tidb as public
        from taskweave_tidb import execution
        spec = importlib.util.find_spec('taskweave_tidb.database')
        self.assertIsNotNone(spec, 'shared database policy must not live in plugin assembly')
        database = importlib.import_module('taskweave_tidb.database')
        self.assertIs(execution.configuration, database.configuration)
        self.assertIs(public.configuration, database.configuration)
        self.assertIs(public.wire_value, database.wire_value)
        for node in ast.walk(ast.parse(Path(execution.__file__).read_text())):
            if isinstance(node, ast.ImportFrom) and node.level:
                self.assertIsNotNone(node.module, 'execution must not import its package assembly')

    def test_old_pickle_class_paths_and_new_round_trips(self):
        import taskweave_playwright as public
        for name, args in (('BrowserSession', ()), ('BrowserAction', ('page_title', 'Title', {}, {})),
                           ('ReadTool', ('page_title', 'Title', {}, {})), ('FileResult', ('image/png',)),
                           ('PlaywrightPlugin', ())):
            cls = getattr(public, name)
            legacy_global = f'ctaskweave_playwright\n{name}\n.'.encode()
            self.assertIs(pickle.loads(legacy_global), cls)
            self.assertIs(type(pickle.loads(pickle.dumps(cls(*args)))), cls)

    def test_declared_entry_points_register_all_plugins_without_resources(self):
        from importlib.metadata import EntryPoint
        from taskweave.plugins.registry import Registry
        plugins = []
        for path in sorted((ROOT / 'plugins').glob('*/pyproject.toml')):
            project = tomllib.loads(path.read_text())['project']
            for name, value in project['entry-points']['taskweave.plugins'].items():
                plugin = EntryPoint(name=name, value=value, group='taskweave.plugins').load()()
                self.assertEqual(plugin.manifest()['id'], name)
                self.assertEqual(plugin.manifest()['api_version'], 1)
                plugins.append(plugin)
        registry = Registry(plugins)
        self.assertEqual(set(registry.versions), {
            'playwright', 'ocr', 'tidb', 'file', 'utility', 'process', 'ssh',
            'baota_dashboard', 'wordpress', 'uniapp', 'wechat_dev', 'pdf', 'dataset', 'excel', 'nacos',
        })

    def test_host_sdk_does_not_import_optional_plugin_dependencies(self):
        result = subprocess.run([sys.executable, '-c', '''
import importlib.abc
import sys
class BlockOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'playwright', 'pymysql', 'sqlglot', 'ddddocr', 'nicegui', 'webview', 'reportlab', 'pypdfium2', 'pypdfium2_raw', 'openpyxl', 'et_xmlfile', 'defusedxml'}:
            raise RuntimeError('Optional dependency leaked: ' + fullname)
sys.meta_path.insert(0, BlockOptional())
import taskweave.plugins.sdk
import taskweave.plugins.registry
'''], capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)
