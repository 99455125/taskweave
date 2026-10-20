"""Offline checks for settlement authoring guards; no browser, HTTP or business DB."""
import asyncio
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent


class Context:
    def __init__(self, replies):
        self.replies = list(replies)
        self.actions = []

    async def call(self, capability, arguments):
        self.actions.append(capability)
        if capability != 'tidb.query':
            raise AssertionError('Unexpected non-query capability: ' + capability)
        return self.replies.pop(0)

    def result(self, **value):
        return value


def rows(*values):
    return {'rows': list(values), 'row_count': len(values), 'truncated': False}


def inputs(number):
    definition = json.loads((ROOT / 'settlement_steps/definitions.json').read_text())[number - 1]
    return {key: value['default'] for key, value in definition['input_schema']['properties'].items()}


def execute(number, context, values):
    definitions = json.loads((ROOT / 'settlement_steps/definitions.json').read_text())
    scope = {}
    exec((ROOT / 'settlement_steps' / definitions[number - 1]['source']).read_text(), scope)
    return asyncio.run(scope['run'](context, values))


class SettlementGuards(unittest.TestCase):
    def test_all_authored_sources_compile(self):
        for folder in ('settlement_steps', 'settlement_receiver_steps'):
            for path in (ROOT / folder).glob('*.py'):
                compile(path.read_text(), str(path), 'exec')

    def test_sender_wait_does_not_accept_changed_role_state(self):
        values = inputs(6)
        values['verify_audited_only'] = True
        sender = dict(task_id=175581, org_code='000050', status='3',
                      institution_settlement_no=values['run_label'],
                      comments='仅供本地自测 ' + values['run_label'],
                      currency='SETTLE-CNY', total_amount='70000.00')
        receiver = dict(sender, task_id=175582, org_code='000053')

        class WaitContext(Context):
            async def call(self, capability, arguments):
                if capability == 'process.run':
                    self.actions.append(capability)
                    return dict(exit_code=0, stdout='{"outcome":"complete"}',
                                stdout_truncated=False, stderr_truncated=False)
                return await super().call(capability, arguments)

            def log(self, message):
                pass

        after = rows(dict(id=175581, org_code='000050', status='3'),
                     dict(id=175582, org_code='000053', status='6'))
        ctx = WaitContext([rows(sender, receiver), after, rows()])
        with self.assertRaisesRegex(ValueError, '等待回调后双方任务状态不符'):
            execute(6, ctx, values)
        self.assertEqual(ctx.actions, ['tidb.query', 'process.run', 'tidb.query', 'tidb.query'])

    def master(self, label):
        return dict(id=174791, institution_settlement_no=label,
                    comments='仅供本地自测 ' + label, currency='SETTLE-CNY',
                    from_org_code='000050', to_org_code='000053', status='0')

    def test_other_round_label_stops_before_page_write(self):
        ctx = Context([rows(self.master('OTHER-ROUND'))])
        with self.assertRaisesRegex(ValueError, '归属'):
            execute(2, ctx, inputs(2))
        self.assertEqual(ctx.actions, ['tidb.query'])

    def test_existing_detail_stops_duplicate_add(self):
        values = inputs(2)
        ctx = Context([rows(self.master(values['run_label'])), rows({'id': 175317})])
        with self.assertRaisesRegex(ValueError, '重复保存'):
            execute(2, ctx, values)
        self.assertEqual(ctx.actions, ['tidb.query', 'tidb.query'])

    def test_readonly_resume_rejects_changed_normal_without_page_write(self):
        values = inputs(2)
        values['verify_saved_only'] = True
        wrong = dict(id=174791, institution_settlement_no=values['run_label'],
                     comments='仅供本地自测 ' + values['run_label'],
                     total_amount='70000.00', payer_org_code='000050', receiver_org_code='000053',
                     detail_id=175317, statement_id=999999, statement_normal_id=999999,
                     platform_statement_no=None, platform_statement_no_temp=values['platform_statement_no'],
                     statement_currency='CNY', statement_amount='70000.00', settlement_amount=None,
                     sign_chain_id='owned-local-mock-sign-bill-257312',
                     file_id='owned-local-pdf-ddfdea6f235bacf52923b856cda024c9e5b15fc8f5cb397135a109e522b3e662')
        ctx = Context([rows(self.master(values['run_label'])), rows({'id': 175317}), rows(wrong)])
        with self.assertRaisesRegex(ValueError, '保存关键字段'):
            execute(2, ctx, values)
        self.assertEqual(ctx.actions, ['tidb.query'] * 3)

    def test_changed_receiver_task_stops_save(self):
        values = inputs(3)
        sender = dict(task_id=175581, org_code='000050', status='0')
        receiver = dict(task_id=999999, org_code='000053', status='0')
        ctx = Context([rows(sender, receiver)])
        with self.assertRaisesRegex(ValueError, '任务状态变化'):
            execute(3, ctx, values)
        self.assertEqual(ctx.actions, ['tidb.query'])

    def test_existing_chain_job_stops_resubmission(self):
        values = inputs(3)
        sender = dict(self.master(values['run_label']), task_id=175581,
                      org_code='000050', total_amount='70000.00')
        receiver = dict(sender, task_id=175582, org_code='000053')
        detail = dict(id=175317, statement_normal_id=257312,
                      statement_amount='70000.00', settlement_amount='70000.00',
                      settlement_currency_exchange_rate='100.00',
                      statement_currency_exchange_rate='100.00')
        ctx = Context([rows(sender, receiver), rows(detail), rows({'id': 123, 'status': 8})])
        scope = {}
        exec((ROOT / 'settlement_steps/04-submit-to-review.py').read_text(), scope)
        with self.assertRaisesRegex(ValueError, '已有结算发起任务'):
            asyncio.run(scope['run'](ctx, values))
        self.assertEqual(ctx.actions, ['tidb.query'] * 3)


if __name__ == '__main__':
    unittest.main()
