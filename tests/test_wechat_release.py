"""Release SDK boundary: real Node/process/staging; cloud SDK is controlled."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from taskweave.core.ports import Scope, StepResult, ResultRequest
from taskweave.core.validation import TaskError
from taskweave.infrastructure.storage import Results, uid
from taskweave.infrastructure.worker import PluginContext, Resources
from taskweave.plugins.registry import Registry
from taskweave_wechat_dev import WechatDevPlugin
from tests.fixtures.uniapp_project import compatible_test_node

class WechatReleaseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.project=self.root/'project';self.project.mkdir()
        (self.project/'project.config.json').write_text(json.dumps({'appid':'wx0123456789abcdef','miniprogramRoot':'./'}))
        (self.project/'app.json').write_text('{"pages":["pages/index/index"]}')
        sdk=self.root/'sdk'/'node_modules'/'miniprogram-ci';sdk.mkdir(parents=True)
        (sdk/'package.json').write_text('{"name":"miniprogram-ci","version":"2.1.48","main":"index.js"}')
        (sdk/'index.js').write_text((Path(__file__).parent/'fixtures/wechat_ci.cjs').read_text())
        self.plugin=WechatDevPlugin();registry=Registry([self.plugin]);self.registry=registry
        results=Results(self.root/'host',Scope(uid(),uid(),uid(),uid()),registry)
        self.results=results
        self.config={'project_root':str(self.project),'node_path':compatible_test_node(),'module_root':str(self.root/'sdk'),'private_key_ref':'release-key'}
        self.events=[]
        self.ctx=PluginContext(results.scope,results,Resources(registry),{'wechat_release_config':self.config},{},threading.Event(),lambda k,p:self.events.append((k,p)))
        self.ctx.resolve_secret=lambda ref:'fixture-private-key'
    async def call(self,name,**inputs):
        return await self.registry.actions['wechat_dev.'+name].execute(self.ctx,inputs)
    async def test_preview_stages_real_qr_and_upload_reports_cloud_completion(self):
        preview=await self.call('preview',page_path='pages/index/index',search_query='a=1&b=2',scene=1011)
        self.assertEqual(preview['remote_state'],'completed');self.assertEqual(preview['artifact']['media_type'],'image/png')
        self.assertGreater(preview['artifact']['size_bytes'],40)
        refs=self.results.persist(StepResult(outputs=[ResultRequest('wechat_dev.image','preview_qr',preview['artifact'])]))
        self.assertTrue((self.results.root/refs[0]['locator']).read_bytes().startswith(b'\x89PNG'))
        upload=await self.call('upload',version='1.2.3')
        self.assertEqual(upload['version'],'1.2.3');self.assertEqual(upload['sub_packages'],[{'name':'__FULL__','size':42}])
        self.assertNotIn('fixture-private-key',json.dumps([preview,upload,self.events]))
    async def test_tourist_appid_and_wrong_build_directory_never_publish(self):
        (self.project/'project.config.json').write_text('{"appid":"touristappid"}')
        with self.assertRaises(TaskError):await self.call('upload',version='1.2.3')
        (self.project/'project.config.json').write_text('{"appid":"wx0123456789abcdef"}')
        with self.assertRaises(TaskError):await self.call('upload',version='1.2.3',project_path=str(self.root))
    async def test_sdk_error_is_masked_and_retains_unknown_effect(self):
        with self.assertRaises(TaskError) as error:await self.call('upload',version='1.2.3',desc='fail')
        failures=await self.plugin.failure_results(self.ctx,error.exception)
        self.assertTrue(failures);self.assertEqual(failures[-1].payload['effect_state'],'UNKNOWN')
        self.assertNotIn('fixture-private-key',json.dumps(failures[-1].payload))
    async def test_missing_qr_and_malformed_sdk_receipt_cannot_report_success(self):
        for desc in ('missing','malformed'):
            with self.subTest(desc=desc),self.assertRaises(TaskError):
                await self.call('preview',page_path='pages/index/index',search_query='a=1&b=2',scene=1011,desc=desc)
    async def test_release_actions_reject_unknown_inputs_and_automatic_retry(self):
        for name in ('preview','upload'):
            action=self.registry.actions['wechat_dev.'+name]
            self.assertEqual(action.spec.effect,'WRITE');self.assertFalse(action.spec.retry_safe)
            with self.assertRaises(TaskError):await action.execute(self.ctx,{'version':'1.2.3','shell':'bad'})

    async def test_changed_build_bytes_are_rejected_before_cloud_call(self):
        with self.assertRaises(TaskError) as failure:
            await self.call('upload',version='1.2.3',expected_artifacts={'app.json':{'sha256':'0'*64,'size':1}})
        self.assertEqual(failure.exception.code,'WECHAT_RELEASE_ARTIFACT_CHANGED')
        self.assertEqual(await self.plugin.failure_results(self.ctx,Exception()),[])

    async def test_official_jpeg_qr_is_saved_with_correct_media_type(self):
        import base64
        sdk=self.root/'sdk/node_modules/miniprogram-ci/index.js'
        code=sdk.read_text();old='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
        code=code.replace(old,base64.b64encode((Path(__file__).parent/'fixtures/wechat_ci.jpg').read_bytes()).decode());sdk.write_text(code)
        preview=await self.call('preview',page_path='pages/index/index',search_query='a=1&b=2',scene=1011)
        self.assertEqual(preview['artifact']['media_type'],'image/jpeg')
        refs=self.results.persist(StepResult(outputs=[ResultRequest('wechat_dev.image','jpeg_qr',preview['artifact'])]))
        self.assertTrue((self.results.root/refs[0]['locator']).read_bytes().startswith(b'\xff\xd8'))

    async def test_timeout_does_not_retry_or_claim_remote_completion(self):
        with self.assertRaises(TaskError):await self.call('upload',version='1.2.3',desc='hang',timeout_seconds=1)
        failures=await self.plugin.failure_results(self.ctx,Exception())
        self.assertEqual(failures[-1].payload['effect_state'],'UNKNOWN')
    async def test_truncated_jpeg_is_rejected(self):
        from taskweave_wechat_dev.qrcode import image_extension
        jpeg=(Path(__file__).parent/'fixtures/wechat_ci.jpg').read_bytes()
        with self.assertRaises(TaskError):image_extension(jpeg[:-2])
        with self.assertRaises(TaskError):image_extension(jpeg+b'extra')

    async def test_added_file_invalidates_checked_manifest(self):
        import hashlib
        expected={p.name:{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'size':p.stat().st_size} for p in self.project.iterdir()}
        (self.project/'unexpected.js').write_text('unexpected code')
        with self.assertRaises(TaskError) as failure:await self.call('upload',version='1.2.3',expected_artifacts=expected)
        self.assertEqual(failure.exception.code,'WECHAT_RELEASE_ARTIFACT_CHANGED')
    async def test_successful_preview_qr_survives_later_upload_failure(self):
        await self.call('preview',page_path='pages/index/index',search_query='a=1&b=2',scene=1011)
        with self.assertRaises(TaskError):await self.call('upload',version='1.2.3',desc='fail')
        failures=await self.plugin.failure_results(self.ctx,Exception())
        files=[r for r in failures if r.handler_id=='wechat_dev.image']
        self.assertEqual(len(files),1)
        refs=self.results.persist(StepResult(outputs=failures))
        file=next(r for r in refs if r['kind']=='file')
        self.assertTrue((self.results.root/file['locator']).read_bytes().startswith(b'\x89PNG'))
