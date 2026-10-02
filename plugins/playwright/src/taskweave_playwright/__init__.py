"""Browser plugin: resources, actions, authoring tools and result interpretation."""

import ast
import base64
import json
import asyncio
import re
from datetime import datetime, timezone
from uuid import uuid4
from playwright.async_api import expect
from urllib.parse import urlparse
from playwright.async_api import async_playwright, Error, TimeoutError
from .observation import ELEMENTS_JS, inspect_dom, verify_candidates, frame_path, attach_frame
from .actions import INTERACTIONS, READS, SINGULAR_READS, entries as common_entries, perform as common_perform
from .side_effects import SPECIAL_WRITES, entries as side_effect_entries, perform as side_effect_perform
from .protocol import reply
from taskweave.plugins.sdk import (
    CapabilitySpec,
    AuthoringContribution,
    ContextItem,
    ContextCollection,
    ContextView,
    Diagnostic,
    PreparedResult,
    PluginError,
)


def schema(properties=None, required=()):
    return {
        "type": "object",
        "properties": {
            "role": {"type": "string", "minLength": 1},
            "target_id": {"type": "string", "minLength": 1, "maxLength": 64},
            "timeout_ms": {"type": "integer", "minimum": 1, "maximum": 20000},
            **(properties or {}),
        },
        "required": list(required),
        "$defs": {"locator": LOCATOR},
        "additionalProperties": False,
    }


STRING = {"type": "string"}
NULL = {"type": "null"}
LOCATOR = {"oneOf": [
    {"type": "string", "minLength": 1},
    {"type": "object", "properties": {
        "kind": {"enum": ["css", "role", "label", "placeholder"]},
        "value": {"type": "string", "minLength": 1},
        "name": {"type": "string"}, "frame": {"oneOf": [
            {"type": "string", "minLength": 1},
            {"type": "array", "minItems": 1, "maxItems": 8, "items": {"type": "string", "minLength": 1}}]},
        "within": {"$ref": "#/$defs/locator"},
        "nth": {"type": "integer", "minimum": 0, "maximum": 9999},
        "exact": {"type": "boolean"}}, "required": ["kind", "value"], "additionalProperties": False}
]}


INSPECT_PARAMETERS = {
    'scope': {'enum': ['runtime', 'viewport', 'full_page']}, 'selector': LOCATOR,
    'include_ancestors': {'type': 'boolean'}, 'include_descendants': {'type': 'boolean'},
    'depth': {'type': 'integer', 'minimum': 0, 'maximum': 6},
    'max_nodes': {'type': 'integer', 'minimum': 1, 'maximum': 300},
    'interactive_only': {'type': 'boolean'},
}


def locate(page, selector, _depth=0):
    if _depth > 8:
        raise PluginError('LOCATOR_SCOPE_TOO_DEEP', 'Locator scope nesting exceeds eight levels')
    if isinstance(selector, str):
        return page.locator(selector)
    root = page
    frames = selector.get('frame', [])
    if isinstance(frames, str):
        frames = [frames]
    for frame in frames:
        root = root.frame_locator(frame)
    if selector.get('within') is not None:
        root = locate(root, selector['within'], _depth + 1)
    kind, value = selector['kind'], selector['value']
    if kind == 'css':
        locator = root.locator(value)
    elif kind == 'role':
        locator = root.get_by_role(value, name=selector.get('name'), exact=selector.get('exact', True))
    elif kind == 'label':
        locator = root.get_by_label(value, exact=selector.get('exact', True))
    else:
        locator = root.get_by_placeholder(value, exact=selector.get('exact', True))
    return locator.nth(selector['nth']) if 'nth' in selector else locator


async def target_state(page, selector):
    locator = locate(page, selector)
    count = await reply(locator.count())
    state = {'selector': selector, 'match_count': count}
    if isinstance(selector, dict) and 'nth' in selector:
        state['base_match_count'] = await reply(locate(page, {key: value for key, value in selector.items() if key != 'nth'}).count())
    if count == 1:
        supports_edit = await reply(locator.evaluate("e => e.matches('input,textarea,select') || e.isContentEditable"))
        state.update(visible=await reply(locator.is_visible()), enabled=await reply(locator.is_enabled()),
                     editable=await reply(locator.is_editable()) if supports_edit else False)
    return state


async def snapshot(page, scope='runtime'):
    frames = []
    full_page = scope == 'full_page'
    all_elements = scope != 'viewport'
    remaining = 2000 if full_page else (300 if scope == 'viewport' else 80)
    truncated = len(page.frames) > 8
    for frame in page.frames[:8]:
        elements = await reply(frame.locator('input,textarea,select,button,a,img,canvas,[role="button"],[role="textbox"],[role="option"],[role="radio"],[role="menuitem"],[role="gridcell"],[role="listbox"] li').evaluate_all(ELEMENTS_JS, {"allElements": all_elements, "limit": remaining + 1}))
        selected = elements[:remaining]
        truncated = truncated or len(selected) < len(elements)
        for offset in range(0, len(selected), 16):
            await asyncio.gather(*(verify_candidates(frame, item, locate) for item in selected[offset:offset+16]))
        frame_selector = None
        if frame != page.main_frame:
            frame_selector = await frame_path(page, frame)
            for item in selected:
                if frame_selector:
                    attach_frame(item, frame_selector)
                else:
                    item['selector'] = item['preferred_selector'] = None
                    item['match_count'] = None
                    item['candidate_selectors'] = []
        frames.append({'url': frame.url.split('?')[0].split('#')[0], 'frame_selector': frame_selector, 'elements': selected})
        remaining -= len(selected)
        if remaining <= 0:
            break
    return {'title': await reply(page.title()), 'url': page.url.split('?')[0].split('#')[0], 'captured_at': datetime.now(timezone.utc).isoformat(), 'elements': frames[0]['elements'] if frames else [], 'frames': [{key: value for key, value in frame.items() if key != 'elements'} if index == 0 else frame for index, frame in enumerate(frames)], 'truncated': truncated or remaining <= 0}



class BrowserSession:
    async def open(self, ctx, role):
        runtime = await async_playwright().start()
        options = ctx.environment.get("browser", {})
        options = dict(options)
        parameters = {**ctx.environment, **getattr(ctx, 'task_parameters', {})}
        for name in ('headless', 'timeout_ms', 'executable_path', 'locale'):
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
            context = await browser.new_context(
                accept_downloads=True,
                locale=options.get("locale", "zh-CN"),
            )
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
        if resource.get("context_recorder") is not None:
            await resource["context_recorder"].close()
        try:
            await resource["browser"].close()
        finally:
            await resource["runtime"].stop()


async def page_for(ctx, role, target_id=None):
    resource = await ctx.resources.acquire("playwright.session", role)
    if target_id is not None:
        page = next((page for key, page in _live_context_targets(resource) if key == target_id), None)
        if page is None:
            raise PluginError('BROWSER_TARGET_STALE', 'The selected page is no longer in this role session; enumerate live targets again')
        return page
    if resource["page"].is_closed():
        raise PluginError(
            "BROWSER_PAGE_CLOSED",
            "The role page was closed; end the run and re-establish the session",
        )
    return resource["page"]


def _live_context_targets(resource):
    """Keep opaque page identities inside the owning, live resource only."""
    pages = resource["context"].pages
    pages = [page for page in pages if not page.is_closed()]
    known = resource.setdefault("context_target_pages", {})
    for target_id, page in list(known.items()):
        if not any(page is current for current in pages):
            del known[target_id]
    targets = []
    for page in pages:
        target_id = next((key for key, value in known.items() if value is page), None)
        if target_id is None:
            target_id = uuid4().hex
            known[target_id] = page
        targets.append((target_id, page))
    return targets


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
        if self.name == 'page_targets':
            resource = await ctx.resources.acquire('playwright.session', role)
            live = _live_context_targets(resource)
            return {'targets': [{'target_id': key, 'title': (await page.title())[:200],
                'url': page.url.split('?')[0].split('#')[0], 'primary': page is resource['page']}
                for key, page in live[:32]], 'truncated': len(live) > 32}
        page = await page_for(ctx, role, inputs.get('target_id'))
        try:
            await self.prepare_page(page, inputs)
            if inputs.get('selector') is not None:
                if self.name in READS:
                    # Collection reads do not need actionability or layout.
                    # State reads/assertions inspect their own requested state.
                    state = {'selector': inputs['selector'], 'match_count': await asyncio.wait_for(reply(locate(page, inputs['selector']).count()), 2)}
                else:
                    state = await asyncio.wait_for(target_state(page, inputs['selector']), 2)
                ctx.emit('BrowserTargetObserved', state)
                if self.name in SINGULAR_READS:
                    if state['match_count'] == 0:
                        raise PluginError('LOCATOR_NOT_FOUND', 'No element matches the requested locator')
                    if state['match_count'] > 1:
                        raise PluginError('LOCATOR_AMBIGUOUS', 'Locator matches multiple elements')
                if self.name in INTERACTIONS | SPECIAL_WRITES | {'page_fill', 'page_click', 'page_press', 'page_select_option', 'page_input_value', 'page_element_image', 'page_check', 'page_checked', 'page_assert_checked'}:
                    if state['match_count'] == 0:
                        raise PluginError('LOCATOR_NOT_FOUND', 'No control matches the requested locator')
                    if state['match_count'] > 1:
                        raise PluginError('LOCATOR_AMBIGUOUS', 'Locator matches multiple controls')
                    if not state.get('visible') and not (self.name == 'page_upload' and inputs.get('mode', 'input') == 'input'):
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

    async def prepare_page(self, page, inputs):
        pass

    async def perform(self, ctx, page, inputs):
        op = self.name
        timeout = inputs.get('timeout_ms')
        if op in INTERACTIONS | READS:
            return await common_perform(op, page, inputs, locate, target_state)
        if op in SPECIAL_WRITES:
            return await side_effect_perform(op, page, inputs, locate)
        if op == "page_open":
            await page.goto(inputs["url"], wait_until="domcontentloaded", timeout=inputs.get("timeout_ms"))
            return None
        if op == "page_title":
            return {"title": await page.title()}
        if op == "page_text":
            return {
                "text": (
                    await locate(page, inputs.get("selector", "body")).inner_text(timeout=timeout)
                )[:65536]
            }
        if op in {'page_check', 'page_checked', 'page_assert_checked'}:
            locator = locate(page, inputs['selector'])
            state = await locator.evaluate("""e => {
                const native=e.matches('input[type=checkbox],input[type=radio]');
                const aria=e.getAttribute('aria-checked');
                const semantic=['checkbox','radio','switch','menuitemcheckbox','menuitemradio'].includes(e.getAttribute('role'));
                return {supported:native || semantic && ['true','false','mixed'].includes(aria),
                    native, radio:e.matches('input[type=radio]'),
                    checked:native?e.checked:aria==='mixed'?null:aria==='true',
                    mixed:native?e.indeterminate:aria==='mixed'};
            }""")
            if not state['supported']:
                raise PluginError('LOCATOR_NOT_CHECKABLE', 'Target is not a checkbox/radio with observable checked state')
            if op == 'page_checked':
                return {'checked': None if state['mixed'] else state['checked'], 'mixed': state['mixed']}
            expected = inputs['checked']
            if op == 'page_check':
                if state['radio'] and not expected:
                    raise PluginError('RADIO_UNCHECK_UNSUPPORTED', 'Choose another radio option to change the group selection')
                await locator.set_checked(expected, timeout=timeout)
                return None
            try:
                if state['native']:
                    deadline = asyncio.get_running_loop().time() + (timeout or 10000) / 1000
                    await expect(locator).to_have_js_property('indeterminate', False, timeout=timeout or 10000)
                    remaining = max(1, int((deadline - asyncio.get_running_loop().time()) * 1000))
                    await expect(locator).to_be_checked(checked=expected, timeout=remaining)
                else:
                    await expect(locator).to_have_attribute('aria-checked', 'true' if expected else 'false', timeout=timeout or 10000)
            except AssertionError as exc:
                raise PluginError('BUSINESS_ASSERTION_FAILED', 'Expected checked state was not observed') from exc
            return {'matched': True}
        if op == "page_fill":
            await locate(page, inputs["selector"]).fill(inputs["value"], timeout=timeout)
            return None
        if op == "page_click":
            await locate(page, inputs["selector"]).click(timeout=timeout)
            return None
        if op == "page_press":
            await locate(page, inputs["selector"]).press(inputs["key"], timeout=timeout)
            return None
        if op == "page_select_option":
            await locate(page, inputs["selector"]).select_option(**inputs["option"], timeout=timeout)
            return None
        if op == "page_wait":
            await locate(page, inputs["selector"]).wait_for(
                state=inputs.get("state", "visible"), timeout=timeout
            )
            return None
        if op == "page_assert_text":
            try:
                await expect(locate(page, inputs["selector"])).to_contain_text(inputs["text"], timeout=timeout or 10000)
            except AssertionError as exc:
                raise PluginError("BUSINESS_ASSERTION_FAILED", "Expected page text was not observed; use page_assert_value for input values") from exc
            return {"matched": True}
        if op == 'page_input_value':
            return {'value': await locate(page, inputs['selector']).input_value(timeout=timeout)}
        if op == 'page_assert_value':
            try:
                await expect(locate(page, inputs['selector'])).to_have_value(inputs['value'], timeout=timeout or 10000)
            except AssertionError as exc:
                raise PluginError('BUSINESS_ASSERTION_FAILED', 'Expected control value was not observed') from exc
            return {'matched': True}
        if op == 'page_assert_title':
            try:
                await expect(page).to_have_title(re.compile(re.escape(inputs['text'])), timeout=timeout or 10000)
            except AssertionError as exc:
                raise PluginError('BUSINESS_ASSERTION_FAILED', 'Expected title was not observed') from exc
            return {'matched': True}
        if op == 'page_assert_url':
            try:
                await page.wait_for_url(inputs['url'], timeout=timeout or 10000)
            except TimeoutError as exc:
                raise PluginError('BUSINESS_ASSERTION_FAILED', 'Expected URL was not observed') from exc
            return {'matched': True}
        if op == "page_screenshot":
            staged = await ctx.allocate_file("screenshot")
            await page.screenshot(path=staged.local_path, type="png", full_page=True, timeout=timeout)
            return {"staged_file": staged.token}
        if op == 'page_element_image':
            import base64
            image = await locate(page, inputs['selector']).screenshot(type='png', timeout=timeout)
            if len(image) > 1024 * 1024:
                raise PluginError('IMAGE_TOO_LARGE', 'Element image exceeds 1MB; choose the CAPTCHA image only')
            return {'image_base64':base64.b64encode(image).decode('ascii'),'mime_type':'image/png'}
        if op == "page_download":
            staged = await ctx.allocate_file("download")
            async with page.expect_download(timeout=timeout) as info:
                await locate(page, inputs["selector"]).click(timeout=timeout)
            download = await info.value
            await download.save_as(staged.local_path)
            return {
                "staged_file": staged.token,
                "suggested_filename": download.suggested_filename,
            }
        if op == "page_inspect":
            data = await snapshot(page, inputs.get('scope', 'runtime'))
            if inputs.get('selector') is not None or inputs.get('include_descendants'):
                data['dom'] = await inspect_dom(page, inputs, locate)
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

    async def prepare_page(self, page, inputs):
        if inputs.get("url"):
            await page.goto(inputs["url"], wait_until="domcontentloaded", timeout=inputs.get("timeout_ms"))

    async def perform(self, ctx, page, inputs):
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
            "package_version": "0.4.0",
            "core_requires": ">=0.1,<1",
            "dependencies": {},
            "resource_descriptions": {"playwright.session": "浏览器、页面及浏览器上下文"},
            "context_requests": {
                "playwright.page": {
                    "type": "object",
                    "x-taskweave-context-targets": {
                        "selector_label": "上下文实例 / 页面",
                        "parameter_mode_label": "新建页面",
                        "auto_select_single": True,
                        "hide_parameters_when_selected": True,
                        "keep_parameters_when_selected": ["scope"],
                    },
                    "properties": {
                        "url": {"type": "string", "description": "可选；首次采集时打开的 HTTP/HTTPS 地址，后续留空以采集当前页面"},
                        "role": {"type": "string", "default": "operator", "description": "需要持续复用的浏览器角色"},
                        "scope": {"type": "string", "enum": ["viewport", "full_page"], "default": "full_page", "description": "采集当前可见区域或整个页面"},
                    },
                    "required": ["url"],
                    "additionalProperties": False,
                    "x-taskweave-context-surface-defaults": {"planning": {"scope": "viewport"}},
                    "x-taskweave-context-view": {"default": True},
                    "x-taskweave-context-recording": True,
                }
            },
            "config_variables": [
                {"key": "playwright_headless", "type": "boolean", "default": False, "required": False, "description": "是否无头执行；任务参数优先，环境变量备选。"},
                {"key": "playwright_timeout_ms", "type": "number", "default": 10000, "required": False, "description": "页面动作超时，毫秒。"},
                {"key": "playwright_role", "type": "string", "default": "operator", "required": False, "description": "默认浏览器角色；动作显式 role 优先。"},
                {"key": "playwright_executable_path", "type": "string", "required": False, "description": "自定义匹配 Chromium 路径，通常无需设置。"},
                {"key": "playwright_locale", "type": "string", "default": "zh-CN", "required": False, "description": "BrowserContext 语言区域，新建浏览器上下文时应用；不通过页面操作切换语言。"},
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
                "page_press",
                "Press a key on a uniquely located control; for example Enter after filling a search box",
                schema({"selector": LOCATOR, "key": {"enum": ["Enter", "Tab", "Escape", "ArrowDown", "ArrowUp", "Space"]}}, ["selector", "key"]),
                NULL,
                "WRITE",
            ),
            (
                "page_select_option",
                "Select one native HTML select option by observed value or label",
                schema({"selector": LOCATOR, "option": {"oneOf": [
                    {"type": "object", "properties": {"value": STRING}, "required": ["value"], "additionalProperties": False},
                    {"type": "object", "properties": {"label": STRING}, "required": ["label"], "additionalProperties": False},
                ]}}, ["selector", "option"]),
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
                "Observe verified locators and field groups; optionally inspect a bounded local DOM tree",
                schema(INSPECT_PARAMETERS),
                {"type":"object","properties":{"title":STRING,"url":STRING,"captured_at":STRING,"elements":{"type":"array"},"frames":{"type":"array"},"truncated":{"type":"boolean"},"role":STRING,"task_id":STRING,"run_id":STRING},"required":["title","url","captured_at","elements","frames","truncated"]},
                "READ",
            ),
            (
                "page_handoff",
                "Bring browser forward for manual interaction; pause task separately",
                schema(),
                {"type":"object","properties":{"role":STRING,"ready":{"const":True}},"required":["role","ready"]},
                "READ",
            ),
        ]
        entries.extend([
            ('page_targets', 'Enumerate live pages in the owning role session; opaque IDs do not change the primary page', schema(), {'type':'object','properties':{'targets':{'type':'array'},'truncated':{'type':'boolean'}},'required':['targets','truncated']}, 'READ'),
            ('page_check', 'Set a uniquely scoped native or semantic checkbox/radio checked state; cannot uncheck a native radio', schema({'selector':LOCATOR, 'checked':{'type':'boolean'}}, ['selector','checked']), NULL, 'WRITE'),
            ('page_checked', 'Read checked state; mixed/indeterminate reports checked=null', schema({'selector':LOCATOR}, ['selector']), {'type':'object','properties':{'checked':{'type':['boolean','null']},'mixed':{'type':'boolean'}},'required':['checked','mixed']}, 'READ'),
            ('page_assert_checked', 'Wait for observable checked state to equal the expected boolean', schema({'selector':LOCATOR,'checked':{'type':'boolean'}}, ['selector','checked']), {'type':'object','properties':{'matched':{'const':True}},'required':['matched']}, 'READ'),
            ('page_element_image', 'Read a visible uniquely located element as PNG Base64, for local image-processing plugins', schema({'selector':LOCATOR}, ['selector']), {'type':'object','properties':{'image_base64':STRING,'mime_type':{'const':'image/png'}},'required':['image_base64','mime_type']}, 'READ'),
            ('page_input_value', 'Read the actual value of an input, textarea or select; never use page_text for values', schema({'selector': LOCATOR}, ['selector']), {'type':'object','properties':{'value':STRING},'required':['value']}, 'READ'),
            ('page_assert_value', 'Wait until the control value equals the expected value', schema({'selector':LOCATOR,'value':STRING}, ['selector','value']), {'type':'object','properties':{'matched':{'const':True}},'required':['matched']}, 'READ'),
            ('page_assert_title', 'Wait until page title contains expected text', schema({'text':STRING}, ['text']), {'type':'object','properties':{'matched':{'const':True}},'required':['matched']}, 'READ'),
            ('page_assert_url', 'Wait for a URL glob such as **/search?**; credentials must not be in URL', schema({'url':STRING}, ['url']), {'type':'object','properties':{'matched':{'const':True}},'required':['matched']}, 'READ'),
        ])
        entries.extend(common_entries(schema, LOCATOR))
        entries.extend(side_effect_entries(schema, LOCATOR))
        return {
            "playwright." + n: BrowserAction(n, d, i, o, e) for n, d, i, o, e in entries
        }

    def tools(self):
        return {
            "playwright.page_inspect": ReadTool(
                "page_inspect",
                "Inspect selected URL without clicking",
                schema({"url": STRING, **INSPECT_PARAMETERS}, ["url"]),
                {"type":"object","properties":{"title":STRING,"url":STRING,"captured_at":STRING,"elements":{"type":"array"},"frames":{"type":"array"},"truncated":{"type":"boolean"}},"required":["title","url","captured_at","elements","frames","truncated"]},
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
            """通过 ctx.call 使用 Playwright 动作；同一业务会话使用一致的 role，不同 role 对应独立浏览器上下文。
默认继续已保留页面。只有步骤明确要求导航时调用 page_open，不为读取页面而重新打开登录页或重启流程。
定位依据对应页面或阶段的已采集上下文。优先使用明确可见、可用且匹配唯一的控件，以及上下文给出的 selector 和 frame；不要根据常见网站习惯猜测选择器。不同页面的控件不能混用。
未命名图片或 canvas 可以带有观测到的 DOM-path selector；page_element_image 使用该 selector，不从列表序号推断父类名、src 或全局 nth-of-type。定位失效时需要新证据，不能无依据重复失败定位。
page_wait 支持 attached、detached、visible、hidden；不传不存在的等待状态，不使用 sleep。按操作需要等待控件或目标状态，不能用固定延时掩盖定位错误。
page_text/page_assert_text 面向可见文本；输入框、textarea、select 的实际值使用 page_input_value/page_assert_value。返回对象按动作 schema 读取。
原生 select 用 page_select_option 按采集到的 value 或 label 选择；自定义下拉先展开，再采集可见 option 或列表项并点击。需要键盘确认时可对唯一输入框调用 page_press Enter。填入、按键或点击候选后仍需验证实际选中结果，不把输入文本等同于已选中。
page_assert_url 使用 URL glob；路径匹配需要完整URL或明确的 glob，例如 **/TreatyManagement/Treaty/add。page_assert_title 使用标题包含匹配。
成功检查只针对本步骤：填写检查填写值，导航检查目标页面，提交检查真实业务状态。点击成功或非空页面快照不能代替这些检查；不要额外执行下一步业务。
Playwright 只负责采集图像和页面操作，不识别验证码。采图、OCR、填写、登录步骤按用户划分分别实现；只有当前步骤明确包含完整登录且能力齐备时才组合。
page_handoff 只把页面交给用户，步骤代码没有 ctx.pause；恢复后检查实际状态。
定位器兼容原 CSS/role/label/placeholder，并支持 within（CSS 或嵌套定位器）、显式零基 nth 和 frame（单个 iframe CSS 或外到内的数组）。同名控件应优先通过字段组/范围限定，只有现场证据说明顺序时才用 nth，禁止猜第一个。所有动作可传 target_id 和 1–20000 的 timeout_ms；目标 ID 由 page_targets 获取，属于当前 role 会话，不能跨采集/编写/运行复用，过期需重新枚举，不随意切换到最后一个页面。
page_inspect 返回实际验证的 candidate_selectors/preferred_selector/match_count、字段组与祖先、checked/mixed 等状态；语义匹配0或多命中时使用唯一且实际验证的 CSS 备选，不把选择器字符串本身当可靠证据。可指定 selector、scope、include_ancestors/include_descendants、depth（0–6）、max_nodes（1–300）观察局部 DOM，truncated 表示覆盖不完整，密码/token 等值被遮蔽，不能据此猜缺失状态。使用 page_check 设置 checked、page_checked 读取、page_assert_checked 验证，mixed 不等于 true；原生 radio 不能直接取消，应选择另一个选项。
page_hover/page_double_click 共用唯一定位器；page_drag 的 selector 与 destination 须在同一 frame 且均唯一，不猜屏幕坐标。page_scroll 默认把已定位元素滚入视口，提供 delta_x/delta_y 时在目标容器内相对滚动（每次最多10000像素）；虚拟化页面滚动后重新观察，不假定所有行已经加载。这些动作可能触发页面逻辑，均为 WRITE 且不可自动重试。
page_state 返回 match_count；不是唯一元素时 visible/enabled/editable 为 null，不把多命中当第一个。page_assert_state 的 expected 可含 count、visible、enabled、editable；状态字段必须对应唯一已挂载元素，隐藏不等于不存在，消失使用 count=0 或 page_wait detached。editable 断言仅用于表单/contenteditable控件。
page_attribute 只读声明允许的 DOM/ARIA 属性，最长8192字符；不读 value、事件处理器或 data-*，输入值仍用专用动作。page_list/page_table 只读当前DOM中的文本，默认过滤隐藏项，不读取表单值、不自动翻页。列表最多100项，表格最多100行/30列，每项/单元格最多2048字符，总体在浏览器内按字节预算截断；truncated 表示证据或输出不完整。表格保留单元格 header/row_span/col_span，不展开合并单元格、不把嵌套表格混入父表。统计数量只针对当前渲染且所选可见性范围的元素，不能当全业务数据总数；确需完整结果时由明确步骤执行翻页/滚动并逐次核对，不自动漏行后声称完成。
page_upload 使用明确文件名、mime_type、content_base64，不接受本机路径；file.read 的 base64 输出可通过步骤绑定传入。单文件最多1MiB、总量8MiB、最多10个文件，空数组明确清除。mode=input定位input[type=file]（可隐藏）；mode=chooser定位触发文件选择的唯一可见控件，不猜新建文件框。上传返回文件大小仅证明浏览器文件已设置，仍须按本步骤要求核对页面实际接收结果。
page_dialog 在触发click/double_click/press前安装本次动作的原生弹窗处理，dialogs须列出实际观察到的type、完整message和accept/dismiss；prompt_text仅用于接受prompt。按顺序精确匹配，额外或不符弹窗拒绝，结束/取消移除监听。普通HTML弹窗继续用DOM定位；不凭常见提示猜确认内容，不用长期自动接受监听，也不认为处理确认框就代表业务成功。
运行时 page_inspect 读取当前保留页面；编写工具中同名动作根据 URL 在独立浏览器观察，二者现场不同。
保存并展示截图时，把 page_screenshot 的完整返回对象交给 ctx.output("playwright.image", "capture", screenshot)，将 output 放入 outputs，将 {"output":"capture"} 放入 data，并用 playwright.screenshot view 指向该字段。临时 staged_file 不能直接展示；未要求截图时不自动增加。""",
            examples=(
                """async def run(ctx, inputs):
    await ctx.call("playwright.page_open", {"url": inputs["url"], "role": "operator"})
    title = await ctx.call("playwright.page_title", {"role": "operator"})
    assert title["title"], "未取得页面标题"
    return ctx.result(data=title)
""",
                """async def run(ctx, inputs):
    screenshot = await ctx.call("playwright.page_screenshot", {"role": "operator"})
    output = ctx.output("playwright.image", "capture", screenshot)
    return ctx.result(data={"capture": {"output": "capture"}}, outputs=[output], views=[{"title": "当前页面", "renderer": "playwright.screenshot", "pointer": "/capture"}])
""",
            ),
            context_provider_ids=("playwright.page",),
            tool_ids=("playwright.page_inspect",),
            channel_overrides={"web_chat": {"instructions":
                "本渠道不能启动浏览器或验证定位。根据提供的页面证据生成调用代码；缺少关键定位依据时明确指出，不声称已观察未提供的页面。"}},
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

    async def list_context_targets(self, provider_id, ctx, request):
        if provider_id != "playwright.page":
            raise PluginError("CONTEXT_PROVIDER_UNAVAILABLE")
        targets = []
        for role, resource in ctx.resources.active("playwright.session"):
            for target_id, page in _live_context_targets(resource):
                try:
                    title = await page.title()
                except Error:
                    if page.is_closed():
                        continue
                    title = ""
                if page.is_closed():
                    continue
                parsed = urlparse(page.url)
                url = parsed._replace(netloc=parsed.netloc.rsplit("@", 1)[-1], query="", fragment="").geturl()
                targets.append({
                    "target_id": target_id,
                    "label": f"{role} · {title or '(无标题)'} · {url} · {target_id[:8]}",
                    "request": {"role": role, "target_id": target_id, "url": ""},
                })
        return targets

    async def record_context(self, provider_id, ctx, command, request, *, include_view=True):
        from .recording import record
        if provider_id != 'playwright.page':
            raise PluginError('CONTEXT_PROVIDER_UNAVAILABLE')
        role = request.get('role', 'operator')
        candidates = [(active_role, resource) for active_role, resource in ctx.resources.active('playwright.session')
                      if 'role' not in request or active_role == role]
        resource = next((resource for active_role, resource in candidates if active_role == role), None)
        if command.operation == 'start':
            if request.get('target_id') and request.get('url'):
                raise PluginError('CONTEXT_TARGET_REQUEST_INVALID')
            if request.get('target_id'):
                selected = next(((active_role, candidate_resource, page)
                    for active_role, candidate_resource in candidates
                    for target_id, page in _live_context_targets(candidate_resource)
                    if target_id == request['target_id']), None)
                if selected is None:
                    raise PluginError('CONTEXT_TARGET_UNAVAILABLE', 'The selected page is no longer available; refresh the target list')
                role, resource, page = selected
            elif request.get('url'):
                if urlparse(request['url']).scheme not in {'http', 'https'}:
                    raise PluginError('URL_INVALID')
                if resource is None:
                    await page_for(ctx, role)
                    resource = next(resource for active_role, resource in ctx.resources.active('playwright.session') if active_role == role)
                page = await resource['context'].new_page()
                await page.goto(request['url'], wait_until='domcontentloaded')
            elif resource is not None:
                page = await page_for(ctx, role, request.get('target_id'))
            else:
                raise PluginError('SESSION_NOT_AVAILABLE')
        else:
            # A selected page can close after recording; the recording ID
            # still belongs to its retained role resource and can be saved.
            resource = next((candidate_resource for _, candidate_resource in candidates
                if command.recording_id in getattr(candidate_resource.get('context_recorder'), 'recordings', {})), None)
            if resource is None or resource.get('context_recorder') is None:
                raise PluginError('CONTEXT_RECORDING_UNAVAILABLE')
            page = None
        return await record(resource, page, command, include_view=include_view)

    async def collect_context(self, provider_id, ctx, request, *, include_view=True):
        if provider_id != "playwright.page":
            raise PluginError("CONTEXT_PROVIDER_UNAVAILABLE")
        url = request.get("url")
        if "target_id" in request:
            if url:
                raise PluginError("CONTEXT_TARGET_REQUEST_INVALID", "An existing page target cannot be combined with a URL")
            selected = None
            for active_role, resource in ctx.resources.active("playwright.session"):
                if "role" in request and request["role"] != active_role:
                    continue
                for target_id, candidate in _live_context_targets(resource):
                    if target_id == request["target_id"]:
                        selected = (active_role, candidate)
                        break
                if selected is not None:
                    break
            if selected is None:
                raise PluginError("CONTEXT_TARGET_UNAVAILABLE", "The selected page is no longer available; refresh the target list")
            role, page = selected
        else:
            if url and urlparse(url).scheme not in {"http", "https"}:
                raise PluginError("URL_INVALID")
            role = request.get("role", "operator")
            if not url and not any(
                r == role for r, _ in ctx.resources.active("playwright.session")
            ):
                raise PluginError("SESSION_NOT_AVAILABLE")
            if url:
                active = next(
                    (resource for active_role, resource in ctx.resources.active("playwright.session") if active_role == role),
                    None,
                )
                page = (
                    await active["context"].new_page()
                    if active is not None
                    else await page_for(ctx, role)
                )
                await page.goto(url, wait_until="domcontentloaded")
            else:
                page = await page_for(ctx, role)
        scope = request.get('scope', 'full_page')
        if scope not in {'viewport', 'full_page'}:
            raise PluginError('FORM_INVALID', 'scope must be viewport or full_page')
        try:
            data = await snapshot(page, scope=scope)
            data['role'] = role
            data['task_id'] = ctx.scope.task_id
            data['run_id'] = ctx.scope.run_id
        except Error as exc:
            if "target_id" in request and page.is_closed():
                raise PluginError("CONTEXT_TARGET_UNAVAILABLE", "The selected page closed during collection; refresh the target list") from exc
            raise
        views = ()
        if include_view:
            image = await page.screenshot(type='png', full_page=scope == 'full_page')
            views = (ContextView(
                '完整页面截图' if scope == 'full_page' else '当前页面截图',
                'playwright.screenshot',
                {'image_base64': base64.b64encode(image).decode('ascii'), 'mime_type': 'image/png'},
            ),)
        return ContextCollection((
            ContextItem(
                "text",
                "application/json",
                json.dumps(data, ensure_ascii=False),
                "playwright.page",
                truncated=data.get('truncated', False),
            ),
        ), views)

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
