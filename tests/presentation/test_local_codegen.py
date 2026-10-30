import asyncio
from copy import deepcopy
import unittest
from taskweave.core.validation import TaskError, normalize_step
from taskweave.core.codegen_contracts import codegen_digest


class LocalGenerationFlowTests(unittest.TestCase):
    def test_stale_generation_and_draft_edits_never_apply(self):
        from taskweave.presentation.codegen import LocalGenerationFlow
        async def run():
            identity=['task','step',1];doc={'step_content':'async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n'}
            async def call(operation,**kw):
                if operation.endswith('sources'):
                    return [{'capture_id':'capture','context_id':'group','generator_id':'p.gen','source_digest':'d'}]
                return {'source':'async def run(ctx, inputs):\n    x = 1\n    return ctx.result(data=inputs)\n',
                        'body_fragment':'x = 1','applicable':True,'diagnostics':[],'input_slots':[],
                        'draft_digest':codegen_digest(normalize_step(doc)),'candidate_digest':'candidate'}
            flow=LocalGenerationFlow(call,lambda:tuple(identity))
            await flow.load('step',doc);await flow.generate('step',doc)
            changed={**doc,'step_content':doc['step_content']+'# changed\n'}
            with self.assertRaises(TaskError):await flow.apply('step',changed,'replace')
            identity[1]='other'
            with self.assertRaises(TaskError):await flow.apply('step',doc,'replace')
        asyncio.run(run())

    def test_changed_source_on_apply_preserves_candidate_and_original(self):
        from taskweave.presentation.codegen import LocalGenerationFlow
        async def run():
            calls=[];doc={'step_content':'async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n'}
            async def call(op,**kw):
                calls.append(op)
                if op.endswith('sources'):return [{'capture_id':'c','context_id':'g','generator_id':'p.gen','source_digest':'d'}]
                if calls.count('step.codegen.generate')>1:raise TaskError('CODEGEN_SOURCE_CHANGED')
                return {'source':doc['step_content'],'body_fragment':'x = 1','applicable':True,'diagnostics':[],
                        'draft_digest':codegen_digest(normalize_step(doc)),'candidate_digest':'same'}
            flow=LocalGenerationFlow(call,lambda:('step',));await flow.load('step',doc);await flow.generate('step',doc)
            with self.assertRaises(TaskError):await flow.apply('step',doc,'replace')
            self.assertTrue(flow.result['applicable'])
        asyncio.run(run())

    def test_multiline_insertion_uses_statement_boundary_and_preserves_return(self):
        from taskweave.presentation.codegen import insert_fragment
        source='async def run(ctx, inputs):\n    value = await ctx.call(\n        "demo.echo", {})\n    return ctx.result(data=value)\n'
        changed=insert_fragment(source,'first = 1\nsecond = 2',source.index('"demo.echo"'))
        self.assertIn('    first = 1\n    second = 2\n    value = await',changed)
        self.assertIn('return ctx.result(data=value)',changed)
        with self.assertRaises(TaskError):insert_fragment(source,'first=1',0)

    def test_late_source_reply_is_ignored(self):
        from taskweave.presentation.codegen import LocalGenerationFlow
        async def run():
            identity=['step']
            async def call(*args,**kwargs):identity[0]='other';return [{'capture_id':'c'}]
            flow=LocalGenerationFlow(call,lambda:tuple(identity))
            await flow.load('step',{});self.assertEqual(flow.sources,[])
        asyncio.run(run())

    def test_inserting_a_second_recording_does_not_overwrite_existing_target_variable(self):
        from taskweave.presentation.codegen import insert_fragment
        from types import SimpleNamespace
        source='''async def run(ctx, inputs):
    recording_target = "original-page"
    await ctx.call("playwright.page_click", {"selector": "#old", "target_id": recording_target})
    return ctx.result(data=inputs)
'''
        fragment='''recording_target = "new-page"
await ctx.call("playwright.page_click", {"selector": "#new", "target_id": recording_target})'''
        merged=insert_fragment(source,fragment,source.index('    await ctx.call'))
        calls=[]
        async def call(action,params):calls.append(params['target_id'])
        namespace={};exec(merged,namespace)
        asyncio.run(namespace['run'](SimpleNamespace(call=call,result=lambda **kw:kw),{}))
        self.assertEqual(calls,['new-page','original-page'])
