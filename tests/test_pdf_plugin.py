"""PDF creation preserves text and never overwrites existing user files."""
import asyncio
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from taskweave.core.validation import TaskError, validate


class PdfPluginTests(unittest.TestCase):
    def test_pdf_plugin_available(self):
        self.assertIsNotNone(importlib.util.find_spec('taskweave_pdf'), 'PDF plugin is not implemented')

    def action(self):
        from taskweave_pdf import PdfPlugin
        return PdfPlugin().actions()['pdf.create']

    def ctx(self, root, **kwargs):
        return SimpleNamespace(environment={'pdf_root': str(root)}, task_parameters={},
                               cancelled=kwargs.get('cancelled', lambda: False))

    def create(self, root, text, path='output.pdf', **kwargs):
        return asyncio.run(self.action().execute(self.ctx(root, **kwargs), {'path': path, 'text': text}))

    def reader(self, path):
        from pypdf import PdfReader
        return PdfReader(path)

    def test_creates_pdf_with_reportlab_import_blocked(self):
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as root:
            result = subprocess.run([sys.executable, '-c', """
import asyncio, importlib.abc, sys
from types import SimpleNamespace
class BlockReportLab(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] == 'reportlab':
            raise RuntimeError('ReportLab must not be used by the PDF plugin')
sys.meta_path.insert(0, BlockReportLab())
from taskweave_pdf import PdfPlugin
ctx = SimpleNamespace(environment={'pdf_root': sys.argv[1]}, task_parameters={}, cancelled=lambda: False)
asyncio.run(PdfPlugin().actions()['pdf.create'].execute(ctx, {'path': 'native.pdf', 'text': '中文 PDFium'}))
""", root], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('中文 PDFium', self.reader(Path(root, 'native.pdf')).pages[0].extract_text())

    def test_chinese_literal_text_newlines_and_embedded_font(self):
        with tempfile.TemporaryDirectory() as root:
            text = '中文报告：创建成功。\n\n<tag> & literal\n第二段\t测试'
            result = self.create(root, text)
            reader = self.reader(Path(root, 'output.pdf'))
            extracted = reader.pages[0].extract_text()
            self.assertIn('中文报告：创建成功。', extracted)
            self.assertIn('<tag> & literal', extracted)
            self.assertIn('第二段 测试', extracted)
            self.assertEqual(result['page_count'], 1)
            self.assertLess(result['size_bytes'], 200000, 'A short PDF should embed only the used glyphs')
            self.assertEqual(result['path'], 'output.pdf')
            self.assertEqual(result['size_bytes'], Path(root, 'output.pdf').stat().st_size)
            validate(result, self.action().spec.output_schema)
            fonts = reader.pages[0]['/Resources']['/Font'].get_object().values()
            font_objects = [f.get_object() for f in fonts]
            font_objects += [child.get_object() for f in list(font_objects) for child in f.get('/DescendantFonts', [])]
            descriptors = [f['/FontDescriptor'].get_object() for f in font_objects if '/FontDescriptor' in f]
            self.assertTrue(any('/FontFile2' in descriptor for descriptor in descriptors))
            positions = []
            reader.pages[0].extract_text(visitor_text=lambda txt, cm, tm, font, size: positions.append((txt, tm[4] * cm[1] + tm[5] * cm[3] + cm[5])))
            chinese_y = next(y for txt, y in positions if '中文报告' in txt)
            literal_y = next(y for txt, y in positions if '<tag>' in txt)
            self.assertAlmostEqual(chinese_y - literal_y, 36)

    def test_long_cjk_and_unbroken_english_wrap_and_paginate(self):
        with tempfile.TemporaryDirectory() as root:
            text = '中' * 4000 + '\n' + 'W' * 4000 + '\n结束'
            result = self.create(root, text)
            reader = self.reader(Path(root, 'output.pdf'))
            self.assertGreaterEqual(result['page_count'], 3)
            self.assertEqual(result['page_count'], len(reader.pages))
            all_text = ''.join(p.extract_text() for p in reader.pages)
            self.assertEqual(all_text.count('中'), 4000)
            self.assertEqual(all_text.count('W'), 4000)
            self.assertIn('结束', all_text)
            for page in reader.pages:
                for line in page.extract_text().splitlines():
                    if line.startswith('中'):
                        self.assertLessEqual(len(line), 41)
                    if line.startswith('W'):
                        self.assertLessEqual(len(line), 47)  # W is 10.536pt; printable width is 499.276pt.

    def test_unicode_aliases_and_supplementary_characters_round_trip(self):
        with tempfile.TemporaryDirectory() as root:
            text = 'A B\u00a0C  中文\U0001f100'
            self.create(root, text)
            self.assertEqual(self.reader(Path(root, 'output.pdf')).pages[0].extract_text().strip(), text)

    def test_native_save_failure_cleans_output_and_next_call_succeeds(self):
        import pypdfium2 as pdfium
        with tempfile.TemporaryDirectory() as root:
            with patch.object(pdfium.raw, 'FPDF_SaveAsCopy', return_value=0):
                with self.assertRaises(TaskError) as raised:
                    self.create(root, '中文')
                self.assertEqual(raised.exception.code, 'PDF_RENDER_FAILED')
            self.assertEqual(list(Path(root).iterdir()), [])
            self.assertEqual(self.create(root, '恢复创建')['page_count'], 1)

    def test_concurrent_calls_produce_independent_pdfs(self):
        with tempfile.TemporaryDirectory() as root:
            async def run():
                return await asyncio.gather(*(self.action().execute(self.ctx(root), {
                    'path': f'{i}.pdf', 'text': f'并发文档 {i}'}) for i in range(4)))
            results = asyncio.run(run())
            self.assertEqual(len(results), 4)
            for i in range(4):
                self.assertIn(f'并发文档 {i}', self.reader(Path(root, f'{i}.pdf')).pages[0].extract_text())

    def test_empty_text_creates_one_blank_page(self):
        with tempfile.TemporaryDirectory() as root:
            result = self.create(root, '')
            self.assertLess(result['size_bytes'], 10000, 'A blank PDF must not embed an unused font')
            self.assertEqual(result['page_count'], 1)
            self.assertEqual(len(self.reader(Path(root, 'output.pdf')).pages), 1)

    def test_existing_target_and_symlink_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            target = Path(root, 'output.pdf')
            target.write_bytes(b'keep-original')
            for path in ('output.pdf',):
                with self.assertRaises(TaskError) as raised:
                    self.create(root, 'new', path)
                self.assertEqual(raised.exception.code, 'PDF_TARGET_EXISTS')
            self.assertEqual(target.read_bytes(), b'keep-original')
            Path(outside, 'private.pdf').write_bytes(b'outside')
            Path(root, 'link.pdf').symlink_to(Path(outside, 'private.pdf'))
            Path(root, 'dangling.pdf').symlink_to(Path(root, 'missing.pdf'))
            for path in ('link.pdf', 'dangling.pdf'):
                with self.assertRaises(TaskError):
                    self.create(root, 'new', path)
            self.assertFalse(Path(root, 'missing.pdf').exists())
            self.assertEqual(Path(outside, 'private.pdf').read_bytes(), b'outside')

    def test_root_required_task_override_and_path_boundaries(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            action = self.action()
            ctx = self.ctx(root)
            ctx.environment = {}
            with self.assertRaises(TaskError) as raised:
                asyncio.run(action.execute(ctx, {'path': 'out.pdf', 'text': 'x'}))
            self.assertEqual(raised.exception.code, 'PDF_ROOT_REQUIRED')
            ctx.task_parameters = {'pdf_root': root}
            ctx.environment = {'pdf_root': outside}
            result = asyncio.run(action.execute(ctx, {'path': 'override.pdf', 'text': '中文'}))
            self.assertEqual(result['path'], 'override.pdf')
            self.assertTrue(Path(root, 'override.pdf').exists())
            Path(root, 'escape').symlink_to(outside, target_is_directory=True)
            for path in ('../bad.pdf', str(Path(outside, 'bad.pdf')), 'escape/bad.pdf',
                         'missing/bad.pdf', 'bad.txt', 'a\x00.pdf'):
                with self.subTest(path=path), self.assertRaises(TaskError):
                    self.create(root, 'x', path)
            self.assertEqual(list(Path(outside).iterdir()), [])

    def test_invalid_input_missing_glyph_and_controls_leave_no_output(self):
        with tempfile.TemporaryDirectory() as root:
            for text in ('x' * 100001, '\x00', '\x01', '\U0010ffff', '\ud800', 123):
                with self.subTest(text=repr(text)[:40]), self.assertRaises(TaskError):
                    self.create(root, text)
                self.assertEqual(list(Path(root).iterdir()), [])
            with self.assertRaises(TaskError):
                asyncio.run(self.action().execute(self.ctx(root), {'path': 'x.pdf', 'text': 'x', 'overwrite': True}))

    def test_cancelled_before_publish_leaves_no_output(self):
        with tempfile.TemporaryDirectory() as root:
            for cancelled in (lambda: True, lambda: Path(root).exists() and any(Path(root).iterdir())):
                with self.assertRaises(TaskError) as raised:
                    self.create(root, '中文文本' * 100, cancelled=cancelled)
                self.assertEqual(raised.exception.code, 'CANCELLED')
                self.assertEqual(list(Path(root).iterdir()), [])

    def test_publish_failure_and_concurrent_target_preserve_files(self):
        with tempfile.TemporaryDirectory() as root:
            with patch('taskweave_pdf.creation.os.link', side_effect=OSError('test failure')):
                with self.assertRaises(TaskError) as raised:
                    self.create(root, '中文')
                self.assertEqual(raised.exception.code, 'PDF_WRITE_FAILED')
            self.assertEqual(list(Path(root).iterdir()), [])
            def competing_writer(source, target):
                Path(target).write_bytes(b'other writer')
                raise FileExistsError()
            with patch('taskweave_pdf.creation.os.link', side_effect=competing_writer):
                with self.assertRaises(TaskError) as raised:
                    self.create(root, '中文')
                self.assertEqual(raised.exception.code, 'PDF_TARGET_EXISTS')
            self.assertEqual(Path(root, 'output.pdf').read_bytes(), b'other writer')
            self.assertEqual(len(list(Path(root).iterdir())), 1)

    def test_cleanup_failure_reports_published_result_or_preserves_primary_error(self):
        from taskweave.plugins.sdk import PluginError
        with tempfile.TemporaryDirectory() as root:
            with patch('taskweave_pdf.creation.Path.unlink', side_effect=PermissionError('busy')):
                result = self.create(root, '已创建')
            self.assertIn('PDF_TEMP_CLEANUP_FAILED', result['cleanup_warning'])
            self.assertTrue(Path(root, 'output.pdf').is_file())
            validate(result, self.action().spec.output_schema)
        with tempfile.TemporaryDirectory() as root:
            with patch('taskweave_pdf.creation.Path.unlink', side_effect=PermissionError('busy')), \
                 patch('taskweave_pdf.creation.render', side_effect=PluginError('CANCELLED')):
                with self.assertRaises(TaskError) as raised:
                    self.create(root, '取消')
            self.assertEqual(raised.exception.code, 'CANCELLED')
            self.assertIn('PDF_TEMP_CLEANUP_FAILED', str(raised.exception))
            self.assertEqual(raised.exception.__cause__.code, 'CANCELLED')
            self.assertFalse(Path(root, 'output.pdf').exists())

    def test_preflight_does_not_write_and_action_has_write_semantics(self):
        with tempfile.TemporaryDirectory() as root:
            action = self.action()
            self.assertEqual(action.spec.effect, 'WRITE')
            self.assertFalse(action.spec.retry_safe)
            self.assertEqual(asyncio.run(action.preflight(self.ctx(root), {'path': 'ok.pdf', 'text': '中文'})), [])
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_real_worker_creates_pdf_and_returns_metadata(self):
        from taskweave.application.service import Application
        from taskweave.infrastructure.storage import uid
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as root, Application(home) as app:
            app.configure_plugin('pdf', True)
            task = app.repo.create_task('创建 PDF')['task_id']
            app.repo.update_task(task, name='创建 PDF', input_schema={'type': 'object', 'properties': {
                'pdf_root': {'type': 'string', 'default': root}}})
            step = app.repo.save_step(task, {'name': '创建', 'capabilities': ['pdf.create'],
                'step_content': 'async def run(ctx, inputs):\n    document = await ctx.call("pdf.create", {"path": "worker.pdf", "text": "工作进程中文 PDF"})\n    return ctx.result(data=document)'})
            app.confirm_step_manual(step['step_id'], step['content_hash'])
            run = app.create_run(task)
            app.coordinator.start(run['run_id'], uid())
            finished = app.coordinator.wait(run['run_id'])
            self.assertEqual(finished['status'], 'SUCCEEDED', finished['attempts'])
            self.assertEqual(app.repo.read_output(run['run_id'], step['step_id'])['path'], 'worker.pdf')
            self.assertIn('工作进程中文 PDF', self.reader(Path(root, 'worker.pdf')).pages[0].extract_text())
