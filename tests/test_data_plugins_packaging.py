"""Build recipes retain dataset/excel entry points and their optional libraries."""
from pathlib import Path
import runpy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class DataPluginPackagingTests(unittest.TestCase):
    def test_platform_recipes_collect_plugins_and_excel_dependencies(self):
        for platform in ('windows', 'macos'):
            packages, distributions = [], []
            def collect(package):
                packages.append(package)
                return [], [], []
            def metadata(distribution):
                distributions.append(distribution)
                return []
            fake = lambda *a, **kw: SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[])
            with self.subTest(platform=platform), patch('PyInstaller.utils.hooks.collect_all', side_effect=collect), patch('PyInstaller.utils.hooks.copy_metadata', side_effect=metadata):
                runpy.run_path(str(ROOT / f'packaging/{platform}/taskweave.spec'), init_globals={
                    'SPECPATH': str(ROOT / f'packaging/{platform}'), 'Analysis': fake, 'PYZ': fake,
                    'EXE': fake, 'COLLECT': fake, 'BUNDLE': fake})
                self.assertTrue({'taskweave_dataset', 'taskweave_excel', 'openpyxl', 'et_xmlfile', 'defusedxml'} <= set(packages), packages)
                self.assertTrue({'taskweave-dataset', 'taskweave-excel', 'openpyxl', 'et-xmlfile', 'defusedxml'} <= set(distributions), distributions)

    def test_discovery_does_not_import_excel_runtime(self):
        import subprocess
        import sys
        code = '''import importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'openpyxl', 'et_xmlfile', 'defusedxml'}:
            raise RuntimeError(fullname)
sys.meta_path.insert(0, Block())
from taskweave_dataset import DatasetPlugin
from taskweave_excel import ExcelPlugin
from taskweave.plugins.registry import Registry
registry = Registry([DatasetPlugin(), ExcelPlugin()])
assert 'excel.write' in registry.actions
'''
        result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
