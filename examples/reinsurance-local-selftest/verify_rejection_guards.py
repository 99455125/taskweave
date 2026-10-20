"""Offline ownership and duplicate-submit guards for the independent rejection case."""
import asyncio
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).parent / 'rejection_broker_steps'


def rows(*items):
    return dict(rows=list(items), row_count=len(items), truncated=False)


def execute(number, context, overrides=None):
    definition = next(d for d in json.loads((ROOT / 'definitions.json').read_text()) if d['step_number'] == number)
    values = {k: v['default'] for k, v in definition['input_schema']['properties'].items() if 'default' in v}
    values.update(overrides or {})
    namespace = {}
    path = ROOT / definition['source']
    exec(compile(path.read_text(), str(path), 'exec'), namespace)
    return asyncio.run(namespace['run'](context, values))


class Context:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.actions = []

    def log(self, message):
        pass

    async def call(self, action, arguments):
        self.actions.append(action)
        if action != 'tidb.query':
            raise AssertionError('Guard unexpectedly reached external action: ' + action)
        return next(self.replies)


class RejectionGuards(unittest.TestCase):
    def parties(self, status='3', biz='owned-local-treaty-cb-20261016045751-ab'):
        return rows(dict(id=100, org_code='000050', reinsurance_role='01', from_id=None, status='3', reviewer=None, biz_id=None),
                    dict(id=101, org_code='000053', reinsurance_role='03', from_id=100, status=status, reviewer=None, biz_id=biz),
                    dict(id=102, org_code='000045', reinsurance_role='02', from_id=101, status='0', reviewer=None, biz_id=None))

    def master(self):
        return rows(dict(id=900, treaty_name='2026-Allianz Jingdong General Insurance Company Ltd-Whole Account-PT-TW-LOCAL-CB-20261016045751'))

    def test_existing_job_stops_submit_before_page_write(self):
        parties = self.parties(status='0', biz=None)
        for row in parties['rows']:
            row['status'] = '0'
        ctx = Context([parties, rows(dict(id=999, status=4))])
        with self.assertRaisesRegex(ValueError, '核心任务已存在'):
            execute(5, ctx, dict(platform_contract_number='000050-2026PT00012', contract_suffix='TW-LOCAL-CB-20261016045751'))
        self.assertEqual(ctx.actions, ['tidb.query', 'tidb.query'])

    def test_changed_master_stops_before_login(self):
        ctx = Context([rows(dict(id=900, treaty_name='OTHER'))])
        with self.assertRaisesRegex(ValueError, '主表归属'):
            execute(6, ctx)
        self.assertEqual(ctx.actions, ['tidb.query'])

    def test_changed_phase_stops_before_login(self):
        ctx = Context([self.master(), self.parties(status='4')])
        with self.assertRaisesRegex(ValueError, '首次经纪待确认'):
            execute(6, ctx)
        self.assertEqual(ctx.actions, ['tidb.query', 'tidb.query'])

    def test_other_biz_stops_before_login(self):
        ctx = Context([self.master(), self.parties(biz='OTHER')])
        with self.assertRaisesRegex(ValueError, 'Mock业务ID'):
            execute(6, ctx)
        self.assertEqual(ctx.actions, ['tidb.query', 'tidb.query'])

    def test_changed_parent_stops_before_login(self):
        parties = self.parties()
        parties['rows'][2]['from_id'] = 999
        ctx = Context([self.master(), parties])
        with self.assertRaisesRegex(ValueError, '上下游'):
            execute(6, ctx)
        self.assertEqual(ctx.actions, ['tidb.query', 'tidb.query'])

    def test_stale_my_task_card_cannot_be_claimed(self):
        class StaleTabContext(Context):
            async def call(self, action, arguments):
                if action == 'tidb.query':
                    return await super().call(action, arguments)
                self.actions.append(action)
                if action == 'file.read':
                    return {'content': {'ui': dict(url='http://localhost:9877/login',
                        accounts={'broker': '000053'}, sharedPassword='test-only', captcha=1, emailCode=1)}}
                if action == 'playwright.page_attribute':
                    return {'value': '请输入用户名'}
                if action == 'playwright.page_inspect':
                    return {'url': 'http://localhost:9877/Home'}
                if action == 'playwright.page_text':
                    return {'text': '平台合约编号：000050-2026PT00012'}
                if action == 'playwright.page_list':
                    return {'items': [], 'truncated': False}
                if action == 'playwright.page_assert_state' and isinstance(arguments['selector'], str) and 'list-item_' in arguments['selector']:
                    raise ValueError('本轮卡片未出现在尚未刷新的我的任务页签')
                if action == 'playwright.page_click' and isinstance(arguments['selector'], dict) and arguments['selector'].get('name') == '处 理':
                    raise AssertionError('Stale unrelated task was claimed')
                return {}

        ctx = StaleTabContext([self.master(), self.parties()])
        with self.assertRaisesRegex(ValueError, '本轮卡片未出现'):
            execute(6, ctx)

    def test_existing_snapshot_stops_first_rejection(self):
        values = dict(cedant_id=100, source_id=101, reinsurer_id=102)
        ctx = Context([self.master(), self.parties(), rows(dict(id=60001))])
        with self.assertRaisesRegex(ValueError, '已有退回快照'):
            execute(7, ctx, values)
        self.assertEqual(ctx.actions, ['tidb.query'] * 3)

    def test_rejected_phase_stops_duplicate_rejection(self):
        ctx = Context([self.master(), self.parties(status='4')])
        with self.assertRaisesRegex(ValueError, '任务阶段'):
            execute(7, ctx, dict(cedant_id=100, source_id=101, reinsurer_id=102))
        self.assertEqual(ctx.actions, ['tidb.query'] * 2)

    def returned_parties(self):
        values = self.parties(status='4')
        values['rows'][0]['status'] = '13'
        return values

    def test_changed_live_version_stops_modify_before_login(self):
        ctx = Context([self.returned_parties(), rows(dict(treaty_name='OTHER'))])
        with self.assertRaisesRegex(ValueError, '预期版本'):
            execute(9, ctx, dict(cedant_id=100, source_id=101, reinsurer_id=102))
        self.assertEqual(ctx.actions, ['tidb.query'] * 2)

    def test_changed_snapshot_stops_modify_before_login(self):
        ctx = Context([self.returned_parties(), self.master(), rows(dict(id=60001, snapshot_sha256='OTHER'))])
        with self.assertRaisesRegex(ValueError, '快照已变化'):
            execute(9, ctx, dict(cedant_id=100, source_id=101, reinsurer_id=102))
        self.assertEqual(ctx.actions, ['tidb.query'] * 3)

    def test_existing_new_job_stops_resubmit_before_ui(self):
        definitions = json.loads((ROOT / 'definitions.json').read_text())
        props = next(d for d in definitions if d['step_number'] == 11)['input_schema']['properties']
        ctx = Context([rows(dict(treaty_name=props['v2_treaty_name']['default'])),
                       self.returned_parties(),
                       rows(dict(id=60001, snapshot_sha256=props['snapshot_sha256']['default'])),
                       rows(dict(id=props['before_job_id']['default'], status=8),
                            dict(id=props['before_job_id']['default'] + 1, status=4))])
        with self.assertRaisesRegex(ValueError, '不再提交'):
            execute(11, ctx, dict(cedant_id=100, source_id=101, reinsurer_id=102))
        self.assertEqual(ctx.actions, ['tidb.query'] * 4)

    def test_wrong_second_snapshot_stops_view_before_navigation(self):
        ctx = Context([rows(dict(id=60002, snapshot_sha256='OTHER'))])
        with self.assertRaisesRegex(ValueError, 'V2快照归属或内容'):
            execute(14, ctx)
        self.assertEqual(ctx.actions, ['tidb.query'])


if __name__ == '__main__':
    unittest.main()
