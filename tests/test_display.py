import json
import unittest
from taskweave.desktop.display import step_names, readable_metadata, execution_title, image_reference


class DisplayTests(unittest.TestCase):
    def test_history_uses_original_names_and_order(self):
        run = {'definition_json': json.dumps({'steps': [{'step_id': 'opaque', 'name': '打开百度'}]})}
        self.assertEqual(step_names(run, [{'step_id': 'opaque', 'name': '改名'}]), {'opaque': '1. 打开百度'})
        self.assertEqual(step_names({}, [{'step_id': 'old', 'name': '输入资讯'}]), {'old': '1. 输入资讯'})

    def test_records_hide_internal_ids_and_preserve_business_data(self):
        record = {'event_id': 'opaque-event', 'run_id': 'opaque-run', 'payload_json': json.dumps({'step_id': 'opaque-step', 'data': {'task_id': 'business-id', 'id': 'customer'}})}
        shown = readable_metadata(record, {'opaque-step': '2. 搜索资讯'})
        self.assertEqual(shown, {'内容': {'步骤': '2. 搜索资讯', 'data': {'task_id': 'business-id', 'id': 'customer'}}})
        self.assertEqual(record['run_id'], 'opaque-run')
        self.assertEqual(readable_metadata({'step_id': 'deleted'}, {}), {'步骤': '未知步骤'})

    def test_session_title_has_time_and_kind(self):
        self.assertEqual(execution_title({'mode': 'TRIAL', 'started_at': '2026-09-18 10:00', 'run_id': 'opaque'}), '试跑 · 2026-09-18 10:00')
        self.assertEqual(execution_title({}), '执行 · 未开始')


class ImageReferenceTests(unittest.TestCase):
    def test_named_id_and_legacy_capture(self):
        stored = {'capture': {'path': '/authorized/image', 'media_type': 'image/png', 'result_id': 'saved-id'}}
        for payload in [{'output': 'capture'}, 'saved-id', {'capture': 'a1abfe9d-75db-4f90-832d-e2439a1f18a9'}, 'a1abfe9d-75db-4f90-832d-e2439a1f18a9']:
            self.assertEqual(image_reference(payload, stored), {'output': 'capture'})
        self.assertEqual(image_reference({'image_base64': 'abc'}, stored), {'image_base64': 'abc'})

    def test_unrelated_paths_and_ambiguous_images_rejected(self):
        stored = {name: {'path': '/authorized/' + name, 'media_type': 'image/png'} for name in ['one', 'two']}
        for payload in ['/etc/passwd', 'a1abfe9d-75db-4f90-832d-e2439a1f18a9', {}]:
            with self.assertRaises(ValueError):
                image_reference(payload, stored)


class OutputPersistenceValidationTests(unittest.TestCase):
    def test_discarded_output_rejected(self):
        from taskweave.core.validation import content_tree, TaskError
        with self.assertRaises(TaskError) as error:
            content_tree('async def run(ctx, inputs):\n    ctx.output("playwright.image", "capture", {})\n    return ctx.result(data={})', ['playwright.image'])
        self.assertEqual(error.exception.code, 'CONTENT_OUTPUT_UNUSED')
        content_tree('async def run(ctx, inputs):\n    output = ctx.output("playwright.image", "capture", {})\n    return ctx.result(data={"capture":{"output":"capture"}}, outputs=[output])', ['playwright.image'])

