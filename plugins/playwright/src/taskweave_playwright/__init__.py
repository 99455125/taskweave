"""Browser plugin: resources, actions, authoring tools and result interpretation."""

import ast
import json
import asyncio
import re
from datetime import datetime, timezone
from playwright.async_api import expect
from urllib.parse import urlparse
from playwright.async_api import async_playwright, Error, TimeoutError
from taskweave.plugins.sdk import (
    CapabilitySpec,
    AuthoringContribution,
    ContextItem,
    Diagnostic,
    PreparedResult,
    PluginError,
)


def schema(properties=None, required=()):
    return {
        "type": "object",
        "properties": {
            "role": {"type": "string", "minLength": 1},
            **(properties or {}),
        },
        "required": list(required),
        "additionalProperties": False,
    }


STRING = {"type": "string"}
NULL = {"type": "null"}
LOCATOR = {"oneOf": [
    {"type": "string", "minLength": 1},
    {"type": "object", "properties": {
        "kind": {"enum": ["css", "role", "label", "placeholder"]},
        "value": {"type": "string", "minLength": 1},
        "name": {"type": "string"}, "frame": {"type": "string", "minLength": 1},
        "exact": {"type": "boolean"}}, "required": ["kind", "value"], "additionalProperties": False}
]}


def locate(page, selector):
    if isinstance(selector, str):
        return page.locator(selector)
    root = page.frame_locator(selector['frame']) if selector.get('frame') else page
    kind, value = selector['kind'], selector['value']
    if kind == 'css':
        return root.locator(value)
    if kind == 'role':
        return root.get_by_role(value, name=selector.get('name'), exact=selector.get('exact', True))
    if kind == 'label':
        return root.get_by_label(value, exact=selector.get('exact', True))
    return root.get_by_placeholder(value, exact=selector.get('exact', True))


async def target_state(page, selector):
    locator = locate(page, selector)
    count = await locator.count()
    state = {'selector': selector, 'match_count': count}
    if count == 1:
        supports_edit = await locator.evaluate("e => e.matches('input,textarea,select') || e.isContentEditable")
        state.update(visible=await locator.is_visible(), enabled=await locator.is_enabled(), editable=await locator.is_editable() if supports_edit else False)
    return state


async def snapshot(page):
    frames = []
    remaining = 80
    truncated = len(page.frames) > 8
    for frame in page.frames[:8]:
        elements = await frame.locator('input,textarea,select,button,a,img,canvas,[role="button"],[role="textbox"]').evaluate_all(r"""els => {
          const visible = e => {const s=getComputedStyle(e); return s.visibility!=='hidden' && s.display!=='none' && Array.from(e.getClientRects()).some(r=>r.width>0 && r.height>0)};
          const domPath = e => {
            const parts=[];
            for(let node=e;node&&node.nodeType===1;node=node.parentElement){
              if(node.id && node.ownerDocument.querySelectorAll('#'+CSS.escape(node.id)).length===1){parts.unshift('#'+CSS.escape(node.id));break;}
              const tag=node.localName;
              const siblings=node.parentElement?Array.from(node.parentElement.children).filter(s=>s.localName===tag):[node];
              parts.unshift(tag+':nth-of-type('+(siblings.indexOf(node)+1)+')');
            }
            return parts.join(' > ');
          };
          return els.filter(e=>visible(e)).sort((a,b)=>(a.tagName==='A')-(b.tagName==='A')).slice(0,80).map(e=>{
            const tag=e.tagName.toLowerCase(); const role=e.getAttribute('role')||({button:'button',textarea:'textbox',select:'combobox',a:'link',img:'img'}[tag])||(e.type==='submit'?'button':e.type==='text'||e.type==='search'?'textbox':'');
            const label=Array.from(e.labels||[]).map(l=>l.innerText).join(' ').trim();
            const name=(e.getAttribute('aria-label')||(e.getAttribute('aria-labelledby')||'').split(/\s+/).map(id=>e.ownerDocument.getElementById(id)?.innerText||'').join(' ').trim()||label||e.getAttribute('alt')||(role==='button' && tag==='input'?e.value:e.innerText)||'').replace(/\s+/g,' ').trim().slice(0,120);
            const placeholder=e.getAttribute('placeholder')||'';
            const css=e.id?'#'+CSS.escape(e.id):(tag==='img'||tag==='canvas'?domPath(e):null);
            const selector=css?{kind:'css',value:css}:placeholder?{kind:'placeholder',value:placeholder,exact:true}:label?{kind:'label',value:label,exact:true}:role&&name?{kind:'role',value:role,name:name,exact:true}:null;
            return {tag,width:Math.round(e.getBoundingClientRect().width),height:Math.round(e.getBoundingClientRect().height),id:e.id,type:e.type||'',role,name,label,placeholder,visible:true,enabled:!e.matches(':disabled') && e.getAttribute('aria-disabled')!=='true',editable:(tag==='textarea'||tag==='input'||e.isContentEditable)&&!e.readOnly&&!e.disabled,selector};
          });
        }""")
        selected = elements[:min(remaining, 40)]
        truncated = truncated or len(selected) < len(elements)
        for item in selected:
            if item['selector']:
                # Evaluate uniqueness using the same locator implementation as execution.
                item['match_count'] = await locate(frame, item['selector']).count()
            else:
                item['match_count'] = None
        frame_selector = None
        if frame != page.main_frame:
            handle = await frame.frame_element()
            frame_selector = await handle.evaluate("e => e.id ? '#'+CSS.escape(e.id) : e.name ? 'iframe[name='+JSON.stringify(e.name)+']' : null")
            if frame.parent_frame != page.main_frame:
                frame_selector = None
            for item in selected:
                if item['selector'] and frame_selector:
                    item['selector']['frame'] = frame_selector
                elif item['selector']:
                    item['selector'] = None
        frames.append({'url': frame.url.split('?')[0].split('#')[0], 'frame_selector': frame_selector, 'elements': selected})
        remaining -= len(selected)
        if remaining <= 0:
            break
    return {'title': await page.title(), 'url': page.url.split('?')[0].split('#')[0], 'captured_at': datetime.now(timezone.utc).isoformat(), 'elements': frames[0]['elements'] if frames else [], 'frames': [{key: value for key, value in frame.items() if key != 'elements'} if index == 0 else frame for index, frame in enumerate(frames)], 'truncated': truncated or remaining <= 0}



class BrowserSession:
    async def open(self, ctx, role):
        runtime = await async_playwright().start()
        options = ctx.environment.get("browser", {})
        options = dict(options)
        parameters = {**ctx.environment, **getattr(ctx, 'task_parameters', {})}
        for name in ('headless', 'timeout_ms', 'executable_path'):
            if 'playwright_' + name in parameters:
                options[name] = parameters['playwright_' + name]
        try:
            browser = await runtime.chromium.launch(
                headless=options.get("headless", False),
                channel="chromium",
                **(
                    {"executable_path": options["executable_path"]}
                    if options.get("executable_path")
                    else {}
                ),
            )
            context = await browser.new_context(accept_downloads=True)
            page = await context.new_page()
            page.set_default_timeout(options.get("timeout_ms", 10000))
            return {
                "runtime": runtime,
                "browser": browser,
                "context": context,
                "page": page,
                "role": role,
            }
        except Exception:
            await runtime.stop()
            raise PluginError(
                "BROWSER_START_FAILED",
                "Matching Chromium is unavailable or could not start",
            )

    async def close(self, resource):
        try:
            await resource["browser"].close()
        finally:
            await resource["runtime"].stop()


async def page_for(ctx, role):
    resource = await ctx.resources.acquire("playwright.session", role)
    if resource["page"].is_closed():
        raise PluginError(
            "BROWSER_PAGE_CLOSED",
            "The role page was closed; end the run and re-establish the session",
        )
    return resource["page"]


class BrowserAction:
    def __init__(self, name, description, inputs, output, effect="READ"):
        self.name = name
        self.spec = CapabilitySpec(
            "playwright." + name,
            description,
            inputs,
            output,
            effect,
            resource_ids=("playwright.session",),
        )

    async def preflight(self, ctx, inputs):
        if self.name in {"page_open", "page_inspect"} and "url" in inputs and urlparse(inputs["url"]).scheme not in {"http", "https"}:
            return [
                Diagnostic("URL_INVALID", "Only HTTP/HTTPS pages are supported", "/url")
            ]
        return []

    async def execute(self, ctx, inputs):
        role = inputs.get("role", getattr(ctx, 'task_parameters', {}).get('playwright_role', ctx.environment.get('playwright_role', 'operator')))
        page = await page_for(ctx, role)
        try:
            if inputs.get('selector') is not None:
                state = await asyncio.wait_for(target_state(page, inputs['selector']), 2)
                ctx.emit('BrowserTargetObserved', state)
                if self.name in {'page_fill', 'page_click', 'page_input_value', 'page_element_image'}:
                    if state['match_count'] == 0:
                        raise PluginError('LOCATOR_NOT_FOUND', 'No control matches the requested locator')
                    if state['match_count'] > 1:
                        raise PluginError('LOCATOR_AMBIGUOUS', 'Locator matches multiple controls')
                    if not state.get('visible'):
                        raise PluginError('LOCATOR_HIDDEN', 'Target control is hidden')
                    if not state.get('enabled'):
                        raise PluginError('LOCATOR_DISABLED', 'Target control is disabled')
                    if self.name == 'page_fill' and not state.get('editable'):
                        raise PluginError('LOCATOR_NOT_EDITABLE', 'Target control is not editable')
            return await self.perform(ctx, page, inputs)
        except (Error, PluginError, asyncio.TimeoutError) as exc:
            if isinstance(exc, PluginError):
                raise
            if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
                raise PluginError(
                    "BROWSER_TIMEOUT",
                    "Browser action timed out; inspect locator and page state",
                ) from exc
            raise PluginError(
                "BROWSER_ACTION_FAILED",
                "Browser action failed; inspect diagnostic screenshot",
            ) from exc

    async def perform(self, ctx, page, inputs):
        op = self.name
        if op == "page_open":
            await page.goto(inputs["url"], wait_until="domcontentloaded")
            return None
        if op == "page_title":
            return {"title": await page.title()}
        if op == "page_text":
            return {
                "text": (
                    await locate(page, inputs.get("selector", "body")).inner_text()
                )[:65536]
            }
        if op == "page_fill":
            await locate(page, inputs["selector"]).fill(inputs["value"])
            return None
        if op == "page_click":
            await locate(page, inputs["selector"]).click()
            return None
        if op == "page_wait":
            await locate(page, inputs["selector"]).wait_for(
                state=inputs.get("state", "visible")
            )
            return None
        if op == "page_assert_text":
            try:
                await expect(locate(page, inputs["selector"])).to_contain_text(inputs["text"], timeout=10000)
            except AssertionError as exc:
                raise PluginError("BUSINESS_ASSERTION_FAILED", "Expected page text was not observed; use page_assert_value for input values") from exc
            return {"matched": True}
        if op == 'page_input_value':
            return {'value': await locate(page, inputs['selector']).input_value()}
        if op == 'page_assert_value':
            try:
                await expect(locate(page, inputs['selector'])).to_have_value(inputs['value'], timeout=10000)
            except AssertionError as exc:
                raise PluginError('BUSINESS_ASSERTION_FAILED', 'Expected control value was not observed') from exc
            return {'matched': True}
        if op == 'page_assert_title':
            try:
                await expect(page).to_have_title(re.compile(re.escape(inputs['text'])), timeout=10000)
            except AssertionError as exc:
                raise PluginError('BUSINESS_ASSERTION_FAILED', 'Expected title was not observed') from exc
            return {'matched': True}
        if op == 'page_assert_url':
            try:
                await page.wait_for_url(inputs['url'], timeout=10000)
            except TimeoutError as exc:
                raise PluginError('BUSINESS_ASSERTION_FAILED', 'Expected URL was not observed') from exc
            return {'matched': True}
        if op == "page_screenshot":
            staged = await ctx.allocate_file("screenshot")
            await page.screenshot(path=staged.local_path, type="png", full_page=True)
            return {"staged_file": staged.token}
        if op == 'page_element_image':
            import base64
            image = await locate(page, inputs['selector']).screenshot(type='png')
            if len(image) > 1024 * 1024:
                raise PluginError('IMAGE_TOO_LARGE', 'Element image exceeds 1MB; choose the CAPTCHA image only')
            return {'image_base64':base64.b64encode(image).decode('ascii'),'mime_type':'image/png'}
        if op == "page_download":
            staged = await ctx.allocate_file("download")
            async with page.expect_download() as info:
                await locate(page, inputs["selector"]).click()
            download = await info.value
            await download.save_as(staged.local_path)
            return {
                "staged_file": staged.token,
                "suggested_filename": download.suggested_filename,
            }
        if op == "page_inspect":
            data = await snapshot(page)
            data['role'] = inputs.get('role', getattr(ctx, 'task_parameters', {}).get('playwright_role', ctx.environment.get('playwright_role', 'operator')))
            data['task_id'] = ctx.scope.task_id
            data['run_id'] = ctx.scope.run_id
            return data
        if op == "page_handoff":
            if ctx.environment.get("browser", {}).get("headless", False):
                raise PluginError(
                    "HANDOFF_REQUIRES_WINDOW",
                    "Use headless=false for manual browser interaction",
                )
            await page.bring_to_front()
            return {"role": inputs.get("role", "operator"), "ready": True}
        raise PluginError("CAPABILITY_UNAVAILABLE")

    async def verify(self, ctx, inputs, output):
        return []


class ReadTool(BrowserAction):
    """Observe an explicitly chosen URL in an isolated authoring browser."""

    async def perform(self, ctx, page, inputs):
        if inputs.get("url"):
            await page.goto(inputs["url"], wait_until="domcontentloaded")
        return await super().perform(
            ctx, page, {k: v for k, v in inputs.items() if k != "url"}
        )


class FileResult:
    def __init__(self, media_type):
        self.media_type = media_type

    def schema(self):
        return {"version": 1, "kind": "file"}

    def prepare(self, request):
        return PreparedResult(
            "file",
            staged_token=request.payload["staged_file"],
            media_type=self.media_type,
        )

    def parse(self, stored):
        return stored

    def preview(self, parsed):
        return {"file": parsed}


class PlaywrightPlugin:
    def manifest(self):
        return {
            "id": "playwright",
            "api_version": 1,
            "package_version": "0.3.0",
            "core_requires": ">=0.1,<1",
            "dependencies": {},
            "resource_descriptions": {"playwright.session": "浏览器、页面及浏览器上下文"},
            "config_variables": [
                {"key": "playwright_headless", "type": "boolean", "default": False, "required": False, "description": "是否无头执行；任务参数优先，环境变量备选。"},
                {"key": "playwright_timeout_ms", "type": "number", "default": 10000, "required": False, "description": "页面动作超时，毫秒。"},
                {"key": "playwright_role", "type": "string", "default": "operator", "required": False, "description": "默认浏览器角色；动作显式 role 优先。"},
                {"key": "playwright_executable_path", "type": "string", "required": False, "description": "自定义匹配 Chromium 路径，通常无需设置。"},
            ],
        }

    def actions(self):
        entries = [
            (
                "page_open",
                "Navigate to URL",
                schema({"url": STRING}, ["url"]),
                NULL,
                "READ",
            ),
            (
                "page_title",
                "Read current page title",
                schema(),
                {
                    "type": "object",
                    "properties": {"title": STRING},
                    "required": ["title"],
                },
                "READ",
            ),
            (
                "page_text",
                "Read locator text",
                schema({"selector": LOCATOR}),
                {
                    "type": "object",
                    "properties": {"text": STRING},
                    "required": ["text"],
                },
                "READ",
            ),
            (
                "page_fill",
                "Fill an input",
                schema({"selector": LOCATOR, "value": STRING}, ["selector", "value"]),
                NULL,
                "WRITE",
            ),
            (
                "page_click",
                "Click an element; may submit business",
                schema({"selector": LOCATOR}, ["selector"]),
                NULL,
                "WRITE",
            ),
            (
                "page_wait",
                "Wait for locator state",
                schema(
                    {
                        "selector": LOCATOR,
                        "state": {
                            "enum": ["attached", "detached", "visible", "hidden"]
                        },
                    },
                    ["selector"],
                ),
                NULL,
                "READ",
            ),
            (
                "page_assert_text",
                "Assert business text",
                schema({"selector": LOCATOR, "text": STRING}, ["selector", "text"]),
                {
                    "type": "object",
                    "properties": {"matched": {"const": True}},
                    "required": ["matched"],
                },
                "READ",
            ),
            (
                "page_screenshot",
                "Capture PNG into task artifact",
                schema(),
                {
                    "type": "object",
                    "properties": {"staged_file": STRING},
                    "required": ["staged_file"],
                },
                "READ",
            ),
            (
                "page_download",
                "Download by clicking",
                schema({"selector": LOCATOR}, ["selector"]),
                {
                    "type": "object",
                    "properties": {"staged_file": STRING, "suggested_filename": STRING},
                    "required": ["staged_file", "suggested_filename"],
                },
                "WRITE",
            ),
            (
                "page_inspect",
                "Observe title and interactive element descriptions",
                schema(),
                {"type": "object"},
                "READ",
            ),
            (
                "page_handoff",
                "Bring browser forward for manual interaction; pause task separately",
                schema(),
                {"type": "object"},
                "READ",
            ),
        ]
        entries.extend([
            ('page_element_image', 'Read a visible uniquely located element as PNG Base64, for local image-processing plugins', schema({'selector':LOCATOR}, ['selector']), {'type':'object','properties':{'image_base64':STRING,'mime_type':{'const':'image/png'}},'required':['image_base64','mime_type']}, 'READ'),
            ('page_input_value', 'Read the actual value of an input, textarea or select; never use page_text for values', schema({'selector': LOCATOR}, ['selector']), {'type':'object','properties':{'value':STRING},'required':['value']}, 'READ'),
            ('page_assert_value', 'Wait until the control value equals the expected value', schema({'selector':LOCATOR,'value':STRING}, ['selector','value']), {'type':'object','properties':{'matched':{'const':True}},'required':['matched']}, 'READ'),
            ('page_assert_title', 'Wait until page title contains expected text', schema({'text':STRING}, ['text']), {'type':'object','properties':{'matched':{'const':True}},'required':['matched']}, 'READ'),
            ('page_assert_url', 'Wait for a URL glob such as **/search?**; credentials must not be in URL', schema({'url':STRING}, ['url']), {'type':'object','properties':{'matched':{'const':True}},'required':['matched']}, 'READ'),
        ])
        return {
            "playwright." + n: BrowserAction(n, d, i, o, e) for n, d, i, o, e in entries
        }

    def tools(self):
        return {
            "playwright.page_inspect": ReadTool(
                "page_inspect",
                "Inspect selected URL without clicking",
                schema({"url": STRING}, ["url"]),
                {"type": "object"},
            )
        }

    def result_views(self):
        return {"playwright.screenshot": {"type": "image", "description": "展示本次保存的页面截图：字段使用 {output: 文件结果名称} 或 {image_base64: 图片Base64, mime_type: image/png}"}}

    def result_handlers(self):
        return {
            "playwright.image": FileResult("image/png"),
            "playwright.download": FileResult("application/octet-stream"),
        }

    def resource_providers(self):
        return {"playwright.session": BrowserSession()}

    def authoring(self, selected_ids):
        return AuthoringContribution(
            "Use ctx.call with explicit role; roles have separate browser contexts. Continue the current retained page unless the user explicitly requests navigation; never insert page_open just to read. "
            "Prefer visible, enabled controls from the latest timestamped snapshot; never guess familiar website selectors or reuse hidden controls. Use the supplied selector object and frame scope; avoid ambiguous locators. "
            "Unnamed images and canvases include an observed DOM-path selector. Use that exact unique selector for page_element_image; do not infer parent classes, image src or document-wide nth-of-type from snapshot ordering. DOM paths may change after rendering; collect a fresh snapshot when they stop matching. "
            "page_text/page_assert_text read rendered page text, NOT input values; use page_input_value/page_assert_value for input/textarea/select values. "
            "A successful click is not business success. Wait for and assert an actual URL, title, result text or state via page_assert_url/page_assert_title/page_assert_text. Never assert a constant or a flag you just assigned (submitted=True). "
            "Repair the exact ActionFailed locator using failure evidence and the fresh current snapshot. Do not repeat the same failed selector without new evidence. "
            "This browser plugin does not recognize CAPTCHA. With a selected OCR plugin, use page_element_image on the actual CAPTCHA image and pass image_base64 to its recognition action; then fill returned text and assert login success. If no selected capability can recognize it, explicitly explain that the user must fill CAPTCHA manually via page_handoff and then continue; never invent OCR or claim login success before checking the authenticated page. "
            "Use specific locators and page_wait; never use sleep. Click/fill/download may affect business. "
            "Check existing business status before a submit; assert resulting ID/status afterwards. "
            "The runtime action playwright.page_inspect reads the retained current page without navigation. The authoring tool with the same ID observes an explicitly supplied URL in an isolated browser, not the current runtime page. "
            'Save PNG with output = ctx.output("playwright.image", "capture", screenshot), passing the ENTIRE page_screenshot response object, not screenshot["staged_file"]. Return ctx.result(data={"capture": {"output": "capture"}}, outputs=[output], views=[{"title": "Screenshot", "renderer": "playwright.screenshot", "pointer": "/capture"}]). ctx.output only creates a request; dropping its return value or returning outputs=[] does NOT save an image. A staged_file UUID alone cannot display an image. '
            "Pause after page_handoff with NEXT/UNTIL for manual interaction; continuing must re-check status.",
            examples=(
                """async def run(ctx, inputs):
    await ctx.call("playwright.page_open", {"url": inputs["url"], "role": "operator"})
    title = await ctx.call("playwright.page_title", {"role": "operator"})
    assert title["title"]
    return ctx.result(data=title)
""",
            ),
            context_provider_ids=("playwright.page",),
            tool_ids=("playwright.page_inspect",),
            channel_overrides={"web_chat": {"instructions":
                "你在网页对话中辅助编写 TaskWeave 的 Playwright 步骤，不能访问用户本机、运行浏览器或调用本机工具。"
                "只使用能力目录中的 ctx.call 动作和输入 schema，不生成独立 Playwright 脚本或 MCP 工具调用。"
                "根据最新带时间的页面快照和失败动作选择可见、启用且唯一的定位器；缺少定位证据时用中文指出需要采集什么，不编造已观察页面。"
                "无名称图片和 canvas 已提供实际 DOM 路径，截图直接使用该 selector，不从图片排列猜测 nth-of-type、父节点类名或 src；结构改变时重新采集。"
                "继续前一步保留的页面，除非用户要求打开地址，不添加 page_open；保留 role 和 frame 范围。"
                "任务和环境变量自动进入 inputs，使用 inputs[变量名]，不要填写账号密钥常量。"
                "浏览器插件不识别验证码。选择 OCR 插件时，用 page_element_image 获取实际验证码图片，把 image_base64 传给该插件识别，再填写返回文字；无其他识别能力时，明确说明需用户通过 page_handoff 人工输入后继续，不编造 OCR，不把填写完成当作登录成功。"
                "输入值用 page_input_value/page_assert_value，不用页面文字读取；点击后用 URL、标题或结果文字等待并验证真实结果。"
                "返回完整 async def run(ctx, inputs) 内容，用 ctx.result 返回 JSON 数据，无 import、全局代码和 diff。"
                "代码返回 JSON 对象的 step_content 字段，中文 explanation 说明修改原因和尚未验证的假设。"}},
            constraints={"content_format": "python-async-v1"},
        )

    async def lint(self, step_document):
        tree = ast.parse(step_document["step_content"])
        diagnostics = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "call"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and str(node.args[0].value).startswith("playwright.")
            ):
                if len(node.args) < 2 or not isinstance(
                    node.args[1], (ast.Dict, ast.Name)
                ):
                    diagnostics.append(
                        Diagnostic(
                            "BROWSER_INPUT_REQUIRED",
                            "Pass an input object to browser actions",
                        )
                    )
        return diagnostics

    async def collect_context(self, provider_id, ctx, request):
        if provider_id != "playwright.page":
            raise PluginError("CONTEXT_PROVIDER_UNAVAILABLE")
        url = request.get("url")
        if url and urlparse(url).scheme not in {"http", "https"}:
            raise PluginError("URL_INVALID")
        role = request.get("role", "operator")
        if not url and not any(
            r == role for r, _ in ctx.resources.active("playwright.session")
        ):
            raise PluginError("SESSION_NOT_AVAILABLE")
        page = await page_for(ctx, role)
        if url:
            await page.goto(url, wait_until="domcontentloaded")
        action = self.actions()["playwright.page_inspect"]
        data = await action.perform(ctx, page, {})
        return [
            ContextItem(
                "text",
                "application/json",
                json.dumps(data, ensure_ascii=False),
                "playwright.page",
                truncated=data.get('truncated', False),
            )
        ]

    async def diagnose(self, error, refs):
        if error.code.startswith(("BROWSER", "LOCATOR")) or error.code in {
            "TimeoutError",
            "BUSINESS_ASSERTION_FAILED",
        }:
            return [
                Diagnostic(
                    "CHECK_BROWSER_STATE",
                    "Inspect screenshot, URL, role and locator; verify external business status before retry",
                    severity="warning",
                )
            ]
        return []

    async def failure_results(self, ctx, error):
        from taskweave.plugins.sdk import ResultRequest

        requests = []
        for role, resource in ctx.resources.active("playwright.session"):
            if not resource["page"].is_closed():
                try:
                    data = await asyncio.wait_for(snapshot(resource['page']), 2)
                    ctx.emit('BrowserFailureSnapshot', {'role': role, 'snapshot': data})
                except Exception:
                    ctx.emit('BrowserFailureSnapshotUnavailable', {'role': role})
                staged = await ctx.allocate_file("failure")
                # A short business action timeout must not suppress its diagnostic evidence.
                await resource["page"].screenshot(
                    path=staged.local_path,
                    type="png",
                    timeout=3000,
                    animations="disabled",
                )
                requests.append(
                    ResultRequest(
                        "playwright.image",
                        "failure_" + str(len(requests)),
                        {"staged_file": staged.token},
                    )
                )
        return requests
