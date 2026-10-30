"""Local conversion consumes saved evidence without a browser or model."""
import ast
from copy import deepcopy
import json
import unittest
from taskweave.core.validation import TaskError, content_tree
from taskweave.plugins.registry import Registry
from taskweave.plugins.demo import DemoPlugin
from taskweave_playwright import PlaywrightPlugin


def recorded_capture(**changes):
    document = {'document_id': 'doc', 'sent': 2, 'acknowledged': 2, 'sealed': True}
    evidence = {'schema_version': 1, 'recording_id': 'record', 'state': 'STOPPED',
                'complete': True, 'role': 'operator', 'primary': True,
                'start_url': 'https://example.test/orders', 'issues': [], 'documents': [document],
                'actions': [
                    {'sequence': 1, 'operation': 'fill', 'selector': {'kind': 'css', 'value': '#order'},
                     'verified': True, 'document_id': 'doc', 'value': 'O-100', 'value_state': 'complete'},
                    {'sequence': 2, 'operation': 'click', 'selector': {'kind': 'role', 'value': 'button', 'name': '查询', 'exact': True},
                     'verified': True, 'document_id': 'doc'}]}
    evidence.update(changes)
    return {'request': {'role': 'operator'}, 'items': [
        {'kind': 'text', 'mime_type': 'application/json', 'source': 'playwright.recording',
         'content': json.dumps({'recording_id': 'record', 'events': [], 'codegen': evidence}), 'truncated': False}]}


class LocalCodegenTests(unittest.TestCase):
    def generate(self, capture=None, bindings=None, options=None):
        return PlaywrightPlugin().generate_code('playwright.recording', capture or recorded_capture(),
                                               bindings or {}, options or {})

    def test_optional_discovery_leaves_old_plugins_compatible(self):
        self.assertEqual(Registry([DemoPlugin()]).catalog()['code_generators'], [])
        registry = Registry([PlaywrightPlugin()])
        self.assertEqual(registry.catalog()['code_generators'][0]['id'], 'playwright.recording')
        plugin = DemoPlugin()
        plugin.code_generators = lambda: [{'id': 'demo.bad'}]
        with self.assertRaises(TaskError):
            Registry([plugin])

    def test_values_require_explicit_choice_and_bound_candidate_runs_through_step_parser(self):
        pending = self.generate()
        self.assertFalse(pending['applicable'])
        self.assertEqual(pending['input_slots'][0]['id'], 'action:1:value')
        self.assertNotIn('O-100', json.dumps(pending, ensure_ascii=False))
        result = self.generate(bindings={'action:1:value': {'input': 'order_no'}})
        self.assertTrue(result['applicable'], result['diagnostics'])
        self.assertIn('inputs[\'order_no\']', result['source'])
        self.assertIn('playwright.page_assert_url', result['source'])
        self.assertNotIn('target_id', result['source'])
        self.assertNotIn('page_open', result['source'])
        content_tree(result['source'], result['required_capabilities'])
        self.assertEqual(self.generate(bindings={'action:1:value': {'input': 'order_no'}}), result)

    def test_nonconstant_values_can_only_bind_input(self):
        for state in ['redacted', 'truncated', 'missing']:
            capture = recorded_capture()
            item = json.loads(capture['items'][0]['content'])
            item['codegen']['actions'][0]['value_state'] = state
            capture['items'][0]['content'] = json.dumps(item)
            self.assertFalse(self.generate(capture, {'action:1:value': {'constant': True}})['applicable'])
            self.assertTrue(self.generate(capture, {'action:1:value': {'input': 'order_no'}})['applicable'])

    def test_broken_incomplete_or_unsupported_recordings_never_emit_partial_source(self):
        variants = [recorded_capture(complete=False), recorded_capture(primary=False),
                    recorded_capture(issues=['PAUSED']), recorded_capture(issues=[{}]), recorded_capture(state='RECORDING'),
                    recorded_capture(documents=[{'document_id':'doc','sent':3,'acknowledged':2,'sealed':True}])]
        for change in [{'operation':'press'}, {'verified':False}, {'sequence':9}]:
            c = recorded_capture();v=json.loads(c['items'][0]['content']);v['codegen']['actions'][0].update(change)
            c['items'][0]['content']=json.dumps(v);variants.append(c)
        for capture in variants:
            with self.subTest(capture=capture):
                result = self.generate(capture, {'action:1:value': {'constant': True}})
                self.assertFalse(result['applicable'])
                self.assertFalse(result['source'])
                self.assertTrue(result['diagnostics'])

    def test_empty_string_select_check_and_invalid_binding(self):
        c=recorded_capture();v=json.loads(c['items'][0]['content']);a=v['codegen']['actions']
        a[0]['value']='';a.append({'sequence':3,'operation':'check','checked':False,'selector':'#check','verified':True,'document_id':'doc'})
        a.append({'sequence':4,'operation':'select','value':'A','value_state':'complete','selector':'#select','verified':True,'document_id':'doc'})
        c['items'][0]['content']=json.dumps(v)
        r=self.generate(c, {'action:1:value':{'constant':True}, 'action:4:value':{'constant':True}})
        self.assertTrue(r['applicable'], r['diagnostics']);ast.parse(r['source'])
        self.assertIn("'value': ''",r['source']);self.assertIn("'checked': False",r['source'])
        self.assertFalse(self.generate(bindings={'not-a-slot':{'constant':True}})['applicable'])

    def test_legacy_and_truncated_records_stay_available_but_not_applicable(self):
        legacy=recorded_capture();legacy['items'][0]['content']=json.dumps({'events':[]})
        self.assertFalse(self.generate(legacy)['applicable'])
        truncated=recorded_capture();truncated['items'][0]['truncated']=True
        self.assertFalse(self.generate(truncated)['applicable'])

    def test_configured_role_and_navigation_are_explicit(self):
        result=self.generate(bindings={'action:1:value':{'constant':True}}, options={'role':'reviewer','start':'open','url_input':'url'})
        self.assertTrue(result['applicable'], result['diagnostics'])
        self.assertIn("'role': 'reviewer'",result['source']);self.assertIn('page_open',result['source'])
        self.assertIn("inputs['url']",result['source'])


def build_registry():
    return Registry([PlaywrightPlugin()])


class CodegenApplicationTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from taskweave.application.service import Application
        self.directory=tempfile.TemporaryDirectory()
        self.app=Application(self.directory.name,registry_factory=f'{__name__}:build_registry')
        self.addCleanup(self.directory.cleanup);self.addCleanup(self.app.close)
        self.task=self.app.repo.create_task('local generation')
        self.step=self.app.repo.save_step(self.task['task_id'],{'name':'search',
            'step_content':'async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n',
            'input_schema':{'type':'object','properties':{'order_no':{'type':'string'}}},
            'capabilities':list(self.app.registry.actions)})
        self.saved=self.app.contexts.save(self.step['step_id'],'playwright.page','Search','draft',recorded_capture()['items'])

    def test_persisted_capture_generates_without_consuming_or_changing_step(self):
        params={'step_id':self.step['step_id'],'document':self.step}
        sources=self.app.dispatch('step.codegen.sources',params)
        source=sources[0]
        result=self.app.dispatch('step.codegen.generate',{**params,'generator_id':source['generator_id'],
            'context_id':source['context_id'],'capture_id':source['capture_id'],
            'expected_source_digest':source['source_digest'],'bindings':{'action:1:value':{'input':'order_no'}}})
        self.assertTrue(result['applicable'],result['diagnostics'])
        self.assertTrue(result['candidate_digest'])
        self.assertEqual(self.app.repo.step(self.step['step_id'])['step_content'],self.step['step_content'])
        self.assertTrue(self.app.contexts.get_capture(source['context_id'],source['capture_id'])['items'])
        self.assertFalse(self.app.dispatch('instance.list',{}))

    def test_material_drift_invalid_input_and_unselected_plugin_are_rejected(self):
        source=self.app.dispatch('step.codegen.sources',{'step_id':self.step['step_id'],'document':self.step})[0]
        params={'step_id':self.step['step_id'],'document':self.step,'generator_id':source['generator_id'],
                'context_id':source['context_id'],'capture_id':source['capture_id'],'expected_source_digest':source['source_digest']}
        for binding in [{'action:1:value':{'input':'missing'}},{'action:1:value':{'input':'order_no'}}]:
            doc=deepcopy(self.step)
            if binding['action:1:value']['input']=='order_no': doc['input_schema']['properties']['order_no']={'type':'integer'}
            with self.assertRaises(TaskError):
                self.app.dispatch('step.codegen.generate',{**params,'document':doc,'bindings':binding})
        with self.assertRaises(TaskError):
            self.app.dispatch('step.codegen.generate',{**params,'expected_source_digest':'stale'})
        with self.assertRaises(TaskError):
            self.app.dispatch('step.codegen.generate',{**params,'document':{**self.step,'capabilities':[]}})
        other=self.app.repo.save_step(self.task['task_id'],{'name':'other'})
        with self.assertRaises(TaskError):
            self.app.dispatch('step.codegen.generate',{**params,'step_id':other['step_id']})

    def test_plugin_fragment_must_match_validated_function_body(self):
        source=self.app.dispatch('step.codegen.sources',{'step_id':self.step['step_id'],'document':self.step})[0]
        plugin=self.app.registry.plugins[0];original=plugin.generate_code
        def bad(*args):
            result=original(*args)
            if result['applicable']:result['body_fragment']='return ctx.result(data={"silently_skipped": True})'
            return result
        plugin.generate_code=bad
        with self.assertRaises(TaskError):
            self.app.dispatch('step.codegen.generate',{'step_id':self.step['step_id'],'document':self.step,
                'generator_id':source['generator_id'],'context_id':source['context_id'],'capture_id':source['capture_id'],
                'expected_source_digest':source['source_digest'],'bindings':{'action:1:value':{'input':'order_no'}}})

    def test_selected_page_candidate_passes_host_with_runtime_target_binding(self):
        evidence=recorded_capture(primary=False,target_mode='selected')
        saved=self.app.contexts.save(self.step['step_id'],'playwright.page','Selected page','draft',evidence['items'])
        sources=self.app.dispatch('step.codegen.sources',{'step_id':self.step['step_id'],'document':self.step})
        source=next(s for s in sources if s['context_id']==saved['context_id'])
        result=self.app.dispatch('step.codegen.generate',{'step_id':self.step['step_id'],'document':self.step,
            'generator_id':source['generator_id'],'context_id':source['context_id'],'capture_id':source['capture_id'],
            'expected_source_digest':source['source_digest'],'bindings':{'action:1:value':{'input':'order_no'}}})
        self.assertTrue(result['applicable'],result['diagnostics'])
        self.assertIn('playwright.page_targets',result['required_capabilities'])
        self.assertIn('recording_target',result['source'])
