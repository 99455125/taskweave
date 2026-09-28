import base64
import unittest

from taskweave.core.ports import ContextCollection, ContextItem, ContextView
from taskweave.core.validation import TaskError


class ContextCollectionTests(unittest.TestCase):
    def test_redaction_preserves_complete_image_and_full_page_evidence(self):
        from taskweave.infrastructure.privacy import redact_collected_context

        encoded = base64.b64encode(b"image-payload" * 6000).decode("ascii")
        content = 'password=private-value ' + 'page content ' * 7000
        capture = {
            'items': [{'kind': 'text', 'content': content}],
            'views': [{'title': '完整页面截图', 'renderer': 'playwright.screenshot',
                       'data': {'image_base64': encoded, 'mime_type': 'image/png'}}],
        }
        result = redact_collected_context(capture, {'playwright.screenshot': {'type': 'image'}})
        self.assertEqual(result['views'][0]['data']['image_base64'], encoded)
        self.assertEqual(len(result['items'][0]['content']), len(content) - len('private-value') + len('[REDACTED]'))
        self.assertIn('password=[REDACTED]', result['items'][0]['content'])

    def test_serializes_items_and_plugin_views_separately(self):
        from taskweave.core.context_collection import serialize_context_collection

        result = serialize_context_collection(
            ContextCollection(
                (ContextItem('text', 'application/json', '{}', 'demo.page'),),
                (ContextView('预览', 'demo.table', {'columns': [], 'rows': []}),),
            ),
            {'demo.table': {'type': 'table'}},
        )
        self.assertEqual(result['items'][0]['source'], 'demo.page')
        self.assertEqual(result['views'][0]['renderer'], 'demo.table')

    def test_rejects_unregistered_renderer_and_duplicate_titles(self):
        from taskweave.core.context_collection import serialize_context_collection

        for views in (
            (ContextView('预览', 'missing.table', {}),),
            (ContextView('重复', 'demo.table', {}), ContextView('重复', 'demo.table', {})),
        ):
            with self.subTest(views=views), self.assertRaises(TaskError):
                serialize_context_collection(ContextCollection((), views), {'demo.table': {'type': 'table'}})


if __name__ == '__main__':
    unittest.main()
