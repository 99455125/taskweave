"""Offline image-code recognition, independent of browser automation and AI APIs."""
import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from taskweave.plugins.sdk import AuthoringContribution, CapabilitySpec, PluginError


def image_bytes(encoded):
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise PluginError('CAPTCHA_IMAGE_INVALID', '验证码图片需要有效 Base64') from exc
    if not data or len(data) > 1024 * 1024:
        raise PluginError('CAPTCHA_IMAGE_INVALID', '验证码图片不能为空且不能超过 1MB')
    from PIL import Image
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format not in {'PNG', 'JPEG', 'WEBP', 'BMP'} or max(image.size) > 4096 or image.width * image.height > 4_000_000:
                raise PluginError('CAPTCHA_IMAGE_INVALID', '验证码图片格式或尺寸不支持')
            image.verify()
    except PluginError:
        raise
    except Exception as exc:
        raise PluginError('CAPTCHA_IMAGE_INVALID', '验证码图片无法解析') from exc
    return data


class LocalOcr:
    async def open(self, ctx, role):
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='captcha-ocr')
        def initialize():
            import ddddocr
            config = {**ctx.environment, **getattr(ctx, 'task_parameters', {})}
            return ddddocr.DdddOcr(show_ad=False, use_gpu=False, beta=bool(config.get('captcha_beta', False)))
        try:
            engine = await asyncio.get_running_loop().run_in_executor(executor, initialize)
            return {'executor': executor, 'engine': engine}
        except Exception as exc:
            executor.shutdown(wait=False, cancel_futures=True)
            raise PluginError('CAPTCHA_ENGINE_UNAVAILABLE', '本地 OCR 初始化失败，请检查随包模型及运行库') from exc

    async def close(self, resource):
        resource['engine'] = None
        resource['executor'].shutdown(wait=False, cancel_futures=True)


class Recognize:
    spec = CapabilitySpec('captcha.recognize', '本地识别普通图片文字验证码（无网络、无 API Key）',
        {'type':'object','properties':{'image_base64':{'type':'string','maxLength':1_400_000},'expected_length':{'type':'integer','minimum':1,'maximum':16}},'required':['image_base64'],'additionalProperties':False},
        {'type':'object','properties':{'text':{'type':'string'},'engine':{'const':'ddddocr'},'needs_verification':{'const':True}},'required':['text','engine','needs_verification']},
        'READ', resource_ids=('captcha.ocr',))

    async def preflight(self, ctx, inputs):
        image_bytes(inputs['image_base64'])
        return []

    async def execute(self, ctx, inputs):
        data = image_bytes(inputs['image_base64'])
        resource = await ctx.resources.acquire('captcha.ocr', 'local')
        try:
            text = await asyncio.get_running_loop().run_in_executor(resource['executor'], resource['engine'].classification, data)
        except Exception as exc:
            raise PluginError('CAPTCHA_RECOGNITION_FAILED', '本地验证码识别失败') from exc
        text = str(text).strip()
        if not text or len(text) > 16 or (inputs.get('expected_length') and len(text) != inputs['expected_length']):
            raise PluginError('CAPTCHA_RESULT_INVALID', '识别结果为空或长度不符，请检查图片或人工填写')
        return {'text':text, 'engine':'ddddocr', 'needs_verification':True}

    async def verify(self, ctx, inputs, output):
        return []


class CaptchaPlugin:
    def manifest(self):
        return {'id':'captcha','api_version':1,'package_version':'0.1.0','core_requires':'>=0.1,<1','dependencies':{},
                'resource_descriptions':{'captcha.ocr':'本地 OCR 模型及识别线程'},
                'config_variables':[{'key':'captcha_beta','type':'boolean','default':False,'required':False,'description':'使用备选本地模型；不影响其他任务。'}]}
    def actions(self):
        return {'captcha.recognize':Recognize()}
    def tools(self):
        return {}
    def resource_providers(self):
        return {'captcha.ocr':LocalOcr()}
    def result_handlers(self):
        return {}
    def authoring(self, selected_ids):
        common = 'captcha.recognize accepts image_base64 (raw PNG/JPEG/WebP/BMP bytes encoded as Base64), optional expected_length; returns text, engine, needs_verification. It is offline CPU OCR for simple image text, not sliders/click puzzles or arithmetic solving. Recognition is a candidate, never proof of successful login. Obtain the current image from a selected image-producing plugin, fill returned text and verify the actual authenticated page after submit. Do not invent image paths, bypass step APIs, retry indefinitely or silently refresh CAPTCHA. If image evidence or recognition is unavailable, explain and use a selected manual handoff capability.'
        return AuthoringContribution(common, channel_overrides={'web_chat':{'instructions':common+' You cannot run local OCR in this web chat. Generate ctx.call code using the available image action and captcha.recognize, not a guessed CAPTCHA string.'}}, constraints={'content_format':'python-async-v1'})
    async def lint(self, step_document):
        return []
    async def collect_context(self, provider_id, ctx, request):
        return []
    async def diagnose(self, error, refs):
        return []
