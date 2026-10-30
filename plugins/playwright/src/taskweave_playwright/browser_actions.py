"""Registered browser actions and read-only authoring tools."""

import asyncio
import re
from urllib.parse import urlparse
from playwright.async_api import expect, Error, TimeoutError
from taskweave.plugins.sdk import CapabilitySpec, Diagnostic, PluginError
from .actions import INTERACTIONS, READS, SINGULAR_READS, perform as common_perform
from .side_effects import SPECIAL_WRITES, perform as side_effect_perform
from .protocol import reply
from .observation import inspect_dom
from .locators import locate, target_state
from ._compat import snapshot
from .session import page_for, _live_context_targets

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
        pages = getattr(ctx, '_playwright_result_pages', None)
        if pages is None:
            pages = ctx._playwright_result_pages = []
        if not any(observed is page for _, observed in pages):
            pages.append((role, page))
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
                    if not state.get('enabled') and self.name != 'page_input_value':
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
