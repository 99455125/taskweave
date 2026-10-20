"""Offline regressions for bill ownership and resume guards; no browser or service calls."""
import asyncio
import copy
from pathlib import Path
import sqlite3
import unittest

ROOT = Path(__file__).parent / 'bill_steps'


def load(name):
    namespace = {}
    exec(compile((ROOT / name).read_text(), str(ROOT / name), 'exec'), namespace)
    return namespace['run']


def result(rows):
    return {'rows': rows, 'row_count': len(rows), 'truncated': False}


class CreationReached(Exception):
    pass


class DraftContext:
    def __init__(self, rows):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.db.execute('CREATE TABLE ri_statement (id INTEGER, record_no TEXT, statement_status INTEGER, comment TEXT, input_org_code TEXT, treaty_id INTEGER, bill_type INTEGER, statement_flag INTEGER, is_deleted TEXT)')
        self.db.executemany('INSERT INTO ri_statement VALUES(?,?,?,?,?,?,?,?,?)', rows)
        self.business_calls = []

    async def call(self, action, inputs):
        if action == 'tidb.query':
            cursor = self.db.execute(inputs['sql'].replace('%s', '?'), inputs.get('params', []))
            return result([dict(row) for row in cursor.fetchall()])
        if action == 'playwright.page_state':
            return {'match_count': 0, 'visible': False}
        self.business_calls.append(action)
        if action == 'playwright.page_click' and inputs['selector'].get('name') == '新增合约账单':
            raise CreationReached()
        raise AssertionError('Unexpected external action: ' + action)


class ResumeContext:
    def __init__(self, mutation):
        self.calls = []
        self.rows = [dict(id=257312, statement_id=544940, input_org_code='000050', enter_org_code='000053', parent_id=None, net_balance='70000.00'), dict(id=257313, statement_id=544940, input_org_code='000053', enter_org_code='000045', parent_id=257312, net_balance='70000.00')]
        self.items = [dict(object_id=normal, item_code=code, item_amount=amount) for normal in [257312, 257313] for code, amount in [('01', '100000.00'), ('02', '20000.00'), ('21', '10000.00'), ('60', '0.00')]]
        if mutation == 'amount': self.rows[1]['net_balance'] = '1.00'
        if mutation == 'parent': self.rows[1]['parent_id'] = 123
        if mutation == 'items': self.items[0]['item_amount'] = '0.00'

    async def call(self, action, inputs):
        self.calls.append(action)
        if action != 'tidb.query': raise AssertionError('Resume guard reached a non-read action: ' + action)
        if 'FROM ri_statement WHERE' in inputs['sql']:
            return result([dict(id=544940, record_no='000050-2026PT00011-SOAP0001', statement_status=3, comment='仅供本地自测 TEST')])
        if 'FROM ri_statement_normal WHERE' in inputs['sql']: return result(self.rows)
        if 'FROM ri_statement_section_item WHERE' in inputs['sql']: return result(self.items)
        raise AssertionError('Unexpected query')


class BillGuardTests(unittest.TestCase):
    def draft_inputs(self, explicit=None):
        return dict(treaty_master_id=1, bill_label='NEW', expected_unsaved_draft_id=explicit)

    def test_existing_other_round_is_not_taken_over(self):
        ctx = DraftContext([(10, 'T-SOAP1', 0, '仅供本地自测 OLD', '000050', 1, 1, 1, 'N')])
        try:
            with self.assertRaisesRegex(ValueError, '其他轮次草稿'):
                asyncio.run(load('02-create.py')(ctx, self.draft_inputs(10)))
            self.assertEqual(ctx.business_calls, [])
        finally: ctx.db.close()

    def test_unmarked_draft_stops_creation(self):
        ctx = DraftContext([(10, 'T-SOAP1', 0, None, '000050', 1, 1, 1, 'N')])
        try:
            with self.assertRaisesRegex(ValueError, '未标识草稿'):
                asyncio.run(load('02-create.py')(ctx, self.draft_inputs()))
            self.assertEqual(ctx.business_calls, [])
        finally: ctx.db.close()

    def test_completed_bills_allow_new_round_creation(self):
        ctx = DraftContext([(10, 'T-SOAP1', 8, '仅供本地自测 OLD1', '000050', 1, 1, 1, 'N'), (11, 'T-SOAP2', 6, '仅供本地自测 OLD2', '000050', 1, 1, 1, 'N')])
        try:
            with self.assertRaises(CreationReached):
                asyncio.run(load('02-create.py')(ctx, self.draft_inputs()))
            self.assertEqual(ctx.business_calls, ['playwright.page_click'])
        finally: ctx.db.close()

    def test_submitted_resume_rejects_changes_before_any_write(self):
        inputs = dict(statement_id=544940, bill_label='TEST', platform_treaty_no='000050-2026PT00011', expected_normals=[{'id':257310, 'net_balance':'70000.00'}, {'id':257311, 'net_balance':'70000.00'}], expected_items=[{'code':code,'amount':amount} for code, amount in [('01','100000.00'),('02','20000.00'),('21','10000.00'),('60','0.00')]], recover_this_fixture=True)
        for mutation, message in [('amount','金额变化'),('parent','父子关系'),('items','科目与本轮预期')]:
            with self.subTest(mutation=mutation):
                ctx = ResumeContext(mutation)
                with self.assertRaisesRegex(ValueError, message):
                    asyncio.run(load('04-submit.py')(ctx, copy.deepcopy(inputs)))
                self.assertTrue(all(action == 'tidb.query' for action in ctx.calls))


if __name__ == '__main__':
    unittest.main()
