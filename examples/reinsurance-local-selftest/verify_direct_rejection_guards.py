"""Offline direct-treaty guards. No browser, network or business database calls."""
import asyncio
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).parent/'rejection_direct_steps'

def rows(*items):
    return dict(rows=list(items),row_count=len(items),truncated=False)

def execute(number,ctx,overrides=None):
    definition=next(d for d in json.loads((ROOT/'definitions.json').read_text()) if d['step_number']==number)
    values={k:v['default'] for k,v in definition['input_schema']['properties'].items() if 'default' in v}
    values.update(overrides or {})
    scope={};path=ROOT/definition['source'];exec(compile(path.read_text(),str(path),'exec'),scope)
    return asyncio.run(scope['run'](ctx,values))

class Context:
    def __init__(self,replies):self.replies=iter(replies);self.actions=[]
    async def call(self,action,args):
        self.actions.append(action)
        if action not in ['tidb.query','playwright.page_inspect']:raise AssertionError('Guard reached action: '+action)
        return next(self.replies)

class DirectGuards(unittest.TestCase):
    def parties(self,status='0',parent=10):
        return rows(dict(id=10,org_code='000050',reinsurance_role='01',from_id=None,status=status,biz_id=None),
                    dict(id=11,org_code='000045',reinsurance_role='02',from_id=parent,status=status,biz_id=None))
    def test_multiple_rows_stop_direct_party_write(self):
        ctx=Context([{'elements':[dict(id='0_amount',visible=True),dict(id='1_amount',visible=True)]}])
        with self.assertRaisesRegex(ValueError,'只有一条再保参与方'):execute(3,ctx)
        self.assertEqual(ctx.actions,['playwright.page_inspect'])
    def test_broker_chain_stops_direct_submit(self):
        value=self.parties();value['rows'].append(dict(id=12,org_code='000053'));value['row_count']=3
        ctx=Context([value])
        with self.assertRaisesRegex(ValueError,'恰好两个参与方'):execute(5,ctx,dict(platform_contract_number='OWN',contract_suffix='OWN'))
        self.assertEqual(ctx.actions,['tidb.query'])
    def test_wrong_parent_stops_submit(self):
        ctx=Context([self.parties(parent=99)])
        with self.assertRaisesRegex(ValueError,'上下游关系'):execute(5,ctx,dict(platform_contract_number='OWN',contract_suffix='OWN'))
        self.assertEqual(ctx.actions,['tidb.query'])
    def test_existing_job_stops_duplicate_submit(self):
        ctx=Context([self.parties(),rows(dict(id=123,status=4))])
        with self.assertRaisesRegex(ValueError,'核心任务已存在'):execute(5,ctx,dict(platform_contract_number='OWN',contract_suffix='OWN'))
        self.assertEqual(ctx.actions,['tidb.query','tidb.query'])

    def master(self):
        definitions=json.loads((ROOT/'definitions.json').read_text())
        props=next(d for d in definitions if d['step_number']==6)['input_schema']['properties']
        return rows(dict(id=325096,treaty_name=props['expected_treaty_name']['default']))

    def pending(self):
        value=self.parties(status='3')
        for row in value['rows']:row['reviewer']=None
        value['rows'][1]['biz_id']='owned-local-treaty-direct-20261016052451'
        return value

    def test_other_master_stops_before_login(self):
        ctx=Context([rows(dict(id=325096,treaty_name='OTHER'))])
        with self.assertRaisesRegex(ValueError,'主表归属'):execute(6,ctx)
        self.assertEqual(ctx.actions,['tidb.query'])

    def test_wrong_phase_stops_before_login(self):
        value=self.pending();value['rows'][1]['status']='4'
        ctx=Context([self.master(),value])
        with self.assertRaisesRegex(ValueError,'首次直连再保人待确认'):execute(6,ctx)
        self.assertEqual(ctx.actions,['tidb.query','tidb.query'])

    def test_other_biz_stops_before_login(self):
        value=self.pending();value['rows'][1]['biz_id']='OTHER'
        ctx=Context([self.master(),value])
        with self.assertRaisesRegex(ValueError,'业务ID'):execute(6,ctx)
        self.assertEqual(ctx.actions,['tidb.query','tidb.query'])

    def test_snapshot_stops_duplicate_first_rejection(self):
        ctx=Context([self.master(),self.pending(),rows(dict(id=60003))])
        with self.assertRaisesRegex(ValueError,'已有退回快照'):execute(7,ctx,dict(cedant_id=10,source_id=11))
        self.assertEqual(ctx.actions,['tidb.query']*3)

    def props(self,number):
        return next(d for d in json.loads((ROOT/'definitions.json').read_text()) if d['step_number']==number)['input_schema']['properties']

    def returned(self):
        value=self.pending();value['rows'][0]['status']='13';value['rows'][1]['status']='4'
        return value

    def test_changed_live_version_stops_modify_before_login(self):
        ctx=Context([self.returned(),rows(dict(treaty_name='OTHER'))])
        with self.assertRaisesRegex(ValueError,'预期版本'):execute(9,ctx,dict(cedant_id=10,source_id=11))
        self.assertEqual(ctx.actions,['tidb.query']*2)

    def test_changed_snapshot_stops_modify_before_login(self):
        ctx=Context([self.returned(),self.master(),rows(dict(id=60003,snapshot_sha256='OTHER'))])
        with self.assertRaisesRegex(ValueError,'快照已变化'):execute(9,ctx,dict(cedant_id=10,source_id=11))
        self.assertEqual(ctx.actions,['tidb.query']*3)

    def test_existing_new_job_stops_resubmit_before_ui(self):
        props=self.props(11)
        ctx=Context([rows(dict(treaty_name=props['v2_treaty_name']['default'])),self.returned(),
                     rows(dict(id=60003,snapshot_sha256=props['snapshot_sha256']['default'])),
                     rows(dict(id=props['before_job_id']['default'],status=8),dict(id=props['before_job_id']['default']+1,status=4))])
        with self.assertRaisesRegex(ValueError,'不再提交'):execute(11,ctx,dict(cedant_id=10,source_id=11))
        self.assertEqual(ctx.actions,['tidb.query']*4)

    def test_wrong_second_snapshot_stops_view_before_navigation(self):
        ctx=Context([rows(dict(id=60004,snapshot_sha256='OTHER'))])
        with self.assertRaisesRegex(ValueError,'V2快照归属或内容'):execute(14,ctx)
        self.assertEqual(ctx.actions,['tidb.query'])

if __name__=='__main__':unittest.main()
