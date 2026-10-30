"""PDF font/resources and platform specs retain the optional plugin when frozen."""
from pathlib import Path
import runpy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class PdfPackagingTests(unittest.TestCase):
    def test_both_platform_specs_collect_pdf_font_engine_and_licenses(self):
        from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs
        for platform in ('windows', 'macos'):
            packages, distributions, data, binaries = [], [], [], []
            def collect(package):
                packages.append(package)
                files = collect_data_files(package) if package in ('taskweave_pdf', 'pypdfium2_raw') else []
                native = collect_dynamic_libs(package) if package == 'pypdfium2_raw' else []
                binaries.extend(native)
                data.extend(files)
                return files, native, []
            def metadata(distribution):
                distributions.append(distribution)
                return []
            fake = lambda *args, **kwargs: SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[])
            with self.subTest(platform=platform), patch('PyInstaller.utils.hooks.collect_all', side_effect=collect), \
                 patch('PyInstaller.utils.hooks.copy_metadata', side_effect=metadata):
                runpy.run_path(str(ROOT / f'packaging/{platform}/taskweave.spec'), init_globals={
                    'SPECPATH': str(ROOT / f'packaging/{platform}'),
                    'Analysis': fake, 'PYZ': fake, 'EXE': fake, 'COLLECT': fake, 'BUNDLE': fake})
                self.assertIn('taskweave_pdf', packages)
                self.assertIn('pypdfium2', packages)
                self.assertIn('pypdfium2_raw', packages)
                self.assertNotIn('reportlab', packages)
                self.assertIn('taskweave-pdf', distributions)
                self.assertIn('pypdfium2', distributions)
                self.assertNotIn('reportlab', distributions)
                names = {Path(source).name for source, destination in data}
                self.assertIn('TaskWeavePDFSans-Regular.ttf', names)
                self.assertIn('OFL.txt', names)
                self.assertIn('TaskWeavePDFSans-Regular.metrics.zlib', names)
                self.assertIn('version.json', names)
                self.assertTrue(any('pdfium' in Path(source).name for source, dest in binaries))

    def test_host_can_import_without_pdf_engine(self):
        import subprocess
        import sys
        result = subprocess.run([sys.executable, '-c', '''
import importlib.abc
import sys
class BlockPdf(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'reportlab', 'pypdfium2', 'pypdfium2_raw'}:
            raise RuntimeError('PDF engine leaked into host or discovery')
sys.meta_path.insert(0, BlockPdf())
import taskweave.plugins.sdk
from taskweave.plugins.registry import Registry
from taskweave_pdf import PdfPlugin
assert Registry([PdfPlugin()]).versions['pdf'] == '0.1.0'
'''], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
