"""Shared locator scopes and checkbox state against actual Chromium."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from playwright.async_api import async_playwright
from taskweave.core.validation import TaskError, validate
from taskweave_playwright import PlaywrightPlugin, locate, _live_context_targets


class PlaywrightScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_frame_path_releases_temporary_element_handles(self):
        from taskweave_playwright.observation import frame_path
        frame = self.page.frames[1]
        connection = self.page._impl_obj._connection
        def handles():
            return {key for key, value in connection._objects.items()
                    if value._type == 'ElementHandle'}
        initial = handles()
        for _ in range(8):
            self.assertEqual(await frame_path(self.page, frame), '#frame')
        self.assertEqual(handles(), initial)

    async def test_default_snapshot_omits_values_but_explicit_dom_can_read_them(self):
        import json
        from taskweave_playwright import snapshot
        await self.page.set_content('<div id="form"><input id="account" value="ordinary-input"><input type="password" value="private-password"></div>')
        data = await snapshot(self.page)
        self.assertTrue(data['elements'])
        self.assertTrue(all('value' not in item for item in data['elements']))
        self.ctx.scope = SimpleNamespace(task_id='t', run_id='r')
        result = await self.actions['playwright.page_inspect'].execute(self.ctx, {'selector': '#form'})
        nodes = result['dom']['root']['children']
        self.assertEqual(nodes[0]['value'], 'ordinary-input')
        self.assertEqual(nodes[1]['value'], '[redacted]')
        self.assertNotIn('private-password', json.dumps(result))

    async def asyncSetUp(self):
        self.runtime = await async_playwright().start()
        self.browser = await self.runtime.chromium.launch(headless=True)
        self.context = await self.browser.new_context()
        self.page = await self.context.new_page()
        await self.page.set_content('''
            <fieldset id="reservation"><legend>预约分保</legend><label><input type="radio" name="reservation">否</label></fieldset>
            <section id="other"><h2>其他合约信息</h2>
              <fieldset id="open"><legend>开口保单</legend><label><input type="radio" name="open">是</label><label><input type="radio" name="open">否</label></fieldset>
              <fieldset id="agent"><legend>代出单</legend><label><input type="radio" name="agent">是</label><label><input type="radio" name="agent">否</label></fieldset>
            </section>
            <div id="status"></div><div role="checkbox" aria-label="自定义" aria-checked="false" tabindex="0"
                onclick="this.setAttribute('aria-checked',this.getAttribute('aria-checked')==='true'?'false':'true')">自定义</div>
            <label><input type="checkbox" id="disabled" disabled>禁用项</label>
            <iframe id="frame" srcdoc="&lt;div id='group'&gt;&lt;button onclick='this.textContent=String(7)'&gt;确定&lt;/button&gt;&lt;/div&gt;"></iframe>
        ''')
        self.resource = {'page': self.page, 'context': self.context}
        self.ctx = SimpleNamespace(resources=SimpleNamespace(acquire=AsyncMock(return_value=self.resource)),
            environment={}, task_parameters={}, emit=lambda *args: None)
        self.actions = PlaywrightPlugin().actions()

    async def asyncTearDown(self):
        await self.browser.close()
        await self.runtime.stop()

    async def test_scoped_radio_only_changes_its_business_field(self):
        selector = {'kind': 'label', 'value': '否', 'within': {'kind': 'css', 'value': '#agent', 'within': '#other'}}
        validate({'selector': selector}, self.actions['playwright.page_click'].spec.input_schema)
        await self.actions['playwright.page_click'].execute(self.ctx, {'selector': selector})
        self.assertTrue(await self.page.locator('#agent input').nth(1).is_checked())
        self.assertFalse(await self.page.locator('#reservation input').is_checked())
        self.assertFalse(await self.page.locator('#open input').nth(1).is_checked())
        with self.assertRaises(TaskError) as error:
            await self.actions['playwright.page_click'].execute(self.ctx, {'selector': {'kind': 'label', 'value': '否'}})
        self.assertEqual(error.exception.code, 'LOCATOR_AMBIGUOUS')

    async def test_nth_is_explicit_bounded_and_reported_in_observation(self):
        observed = []
        self.ctx.emit = lambda name, data: observed.append((name, data))
        selector = {'kind': 'label', 'value': '否', 'within': '#other', 'nth': 1}
        await self.actions['playwright.page_click'].execute(self.ctx, {'selector': selector})
        self.assertTrue(await self.page.locator('#agent input').nth(1).is_checked())
        self.assertEqual(observed[0][1]['base_match_count'], 2)
        with self.assertRaises(TaskError) as error:
            await self.actions['playwright.page_click'].execute(self.ctx, {'selector': {**selector, 'nth': 8}})
        self.assertEqual(error.exception.code, 'LOCATOR_NOT_FOUND')
        with self.assertRaises(TaskError):
            validate({'selector': {**selector, 'nth': -1}}, self.actions['playwright.page_click'].spec.input_schema)

    async def test_frame_scope_and_old_locators_are_compatible(self):
        selector = {'kind': 'role', 'value': 'button', 'name': '确定', 'frame': '#frame', 'within': '#group'}
        await self.actions['playwright.page_click'].execute(self.ctx, {'selector': selector})
        self.assertEqual(await self.page.frame_locator('#frame').locator('button').inner_text(), '7')
        self.assertEqual(await locate(self.page, '#status').count(), 1)
        self.assertEqual(await locate(self.page, {'kind': 'label', 'value': '禁用项'}).count(), 1)

    async def test_check_read_and_assert_support_native_and_aria_controls(self):
        self.assertIn('playwright.page_check', self.actions)
        for selector in ('#open input:last-of-type', {'kind': 'role', 'value': 'checkbox', 'name': '自定义'}):
            # Select the native radio by label because it is nested in labels.
            if isinstance(selector, str):
                selector = {'kind': 'label', 'value': '是', 'within': '#open'}
            await self.actions['playwright.page_check'].execute(self.ctx, {'selector': selector, 'checked': True})
            state = await self.actions['playwright.page_checked'].execute(self.ctx, {'selector': selector})
            self.assertTrue(state['checked'])
            result = await self.actions['playwright.page_assert_checked'].execute(self.ctx, {'selector': selector, 'checked': True, 'timeout_ms': 500})
            self.assertTrue(result['matched'])
        await self.actions['playwright.page_check'].execute(self.ctx, {'selector': {'kind': 'role', 'value': 'checkbox', 'name': '自定义'}, 'checked': False})
        self.assertFalse((await self.actions['playwright.page_checked'].execute(self.ctx, {'selector': {'kind': 'role', 'value': 'checkbox', 'name': '自定义'}}))['checked'])
        with self.assertRaises(TaskError) as error:
            await self.actions['playwright.page_check'].execute(self.ctx, {'selector': '#disabled', 'checked': True})
        self.assertEqual(error.exception.code, 'LOCATOR_DISABLED')

    async def test_explicit_target_cannot_change_primary_or_use_stale_page(self):
        other = await self.context.new_page()
        await other.set_content('<title>第二个页面</title>')
        targets = _live_context_targets(self.resource)
        target_id = next(key for key, page in targets if page is other)
        result = await self.actions['playwright.page_title'].execute(self.ctx, {'target_id': target_id})
        self.assertEqual(result['title'], '第二个页面')
        self.assertIs(self.resource['page'], self.page)
        await other.close()
        with self.assertRaises(TaskError) as error:
            await self.actions['playwright.page_title'].execute(self.ctx, {'target_id': target_id})
        self.assertEqual(error.exception.code, 'BROWSER_TARGET_STALE')

    async def test_snapshot_fallback_is_executable_for_today_and_ambiguous_labels(self):
        from taskweave_playwright import snapshot
        await self.page.locator('body').evaluate("e => e.insertAdjacentHTML('beforeend', '<div id=popup><a>今天</a></div>')")
        data = await snapshot(self.page)
        today = next(item for item in data['elements'] if item['name'] == '今天')
        self.assertEqual(today['match_count'], 1)
        self.assertEqual(await locate(self.page, today['selector']).count(), 1)
        candidates = today['candidate_selectors']
        self.assertTrue(any(item['match_count'] == 0 and item['selector']['kind'] == 'role' for item in candidates))
        radio = next(item for item in data['elements'] if item['tag'] == 'input' and item['label'] == '否')
        self.assertEqual(radio['match_count'], 1)
        self.assertEqual(await locate(self.page, radio['selector']).count(), 1)
        self.assertEqual(radio['field_group']['name'], '预约分保')

    async def test_local_dom_has_bounded_hierarchy_field_groups_and_redacted_values(self):
        await self.page.locator('#agent').evaluate("e => e.insertAdjacentHTML('beforeend', '<input type=password id=password value=private-secret><input name=api_token value=another-secret>')")
        inputs = {'selector': '#other', 'include_ancestors': True, 'include_descendants': True, 'depth': 4, 'max_nodes': 30}
        validate(inputs, self.actions['playwright.page_inspect'].spec.input_schema)
        self.ctx.scope = SimpleNamespace(task_id='t', run_id='r')
        result = await self.actions['playwright.page_inspect'].execute(self.ctx, inputs)
        dom = result['dom']
        self.assertEqual(dom['root']['id'], 'other')
        self.assertTrue(dom['ancestors'])
        self.assertLessEqual(dom['node_count'], 30)
        self.assertIn('children', dom['root'])
        text = str(dom)
        self.assertIn('代出单', text)
        self.assertIn('checked', text)
        self.assertNotIn('private-secret', text)
        self.assertNotIn('another-secret', text)
        self.assertIn('redacted', text)
        small = await self.actions['playwright.page_inspect'].execute(self.ctx, {**inputs, 'max_nodes': 2})
        self.assertEqual(small['dom']['node_count'], 2)
        self.assertTrue(small['dom']['truncated'])

    async def test_local_dom_and_locators_retain_nested_frame_identity(self):
        outer = self.page.frames[1]
        await outer.set_content('''<iframe id="inner" srcdoc="&lt;div id='scope'&gt;&lt;label&gt;&lt;input type='checkbox'&gt;选项&lt;/label&gt;&lt;/div&gt;"></iframe>''')
        selector = {'kind': 'label', 'value': '选项', 'frame': ['#frame', '#inner'], 'within': '#scope'}
        self.ctx.scope = SimpleNamespace(task_id='t', run_id='r')
        await self.actions['playwright.page_check'].execute(self.ctx, {'selector': selector, 'checked': True})
        result = await self.actions['playwright.page_inspect'].execute(self.ctx, {'selector': {'kind': 'css', 'value': '#scope', 'frame': ['#frame', '#inner']}})
        node = result['dom']['root']
        self.assertEqual(node['match_count'], 1)
        self.assertEqual(await locate(self.page, node['selector']).count(), 1)
        input_node = node['children'][0]['children'][0]
        self.assertTrue(input_node['checked'])
        self.assertEqual(await locate(self.page, input_node['selector']).count(), 1)

    async def test_mixed_checkbox_is_not_asserted_as_selected(self):
        await self.page.locator('#open').evaluate("e => e.insertAdjacentHTML('beforeend','<input type=checkbox id=mixed checked>')")
        await self.page.locator('#mixed').evaluate('e => e.indeterminate=true')
        state = await self.actions['playwright.page_checked'].execute(self.ctx, {'selector': '#mixed'})
        self.assertTrue(state['mixed'])
        self.assertIsNone(state['checked'])
        with self.assertRaises(TaskError) as error:
            await self.actions['playwright.page_assert_checked'].execute(self.ctx, {'selector': '#mixed', 'checked': True, 'timeout_ms': 200})
        self.assertEqual(error.exception.code, 'BUSINESS_ASSERTION_FAILED')

    async def test_authoring_tool_navigates_before_scoped_dom_inspection(self):
        import asyncio
        html = b'<iframe id="toolFrame" srcdoc="&lt;div id=field&gt;&lt;button&gt;OK&lt;/button&gt;&lt;/div&gt;"></iframe>'
        async def serve(reader, writer):
            await reader.readuntil(b'\r\n\r\n')
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: ' + str(len(html)).encode() + b'\r\nConnection: close\r\n\r\n' + html)
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        server = await asyncio.start_server(serve, '127.0.0.1', 0)
        try:
            tool = PlaywrightPlugin().tools()['playwright.page_inspect']
            inputs = {'url': 'http://127.0.0.1:' + str(server.sockets[0].getsockname()[1]),
                'selector': {'kind': 'css', 'value': '#field', 'frame': '#toolFrame'}, 'max_nodes': 10}
            validate(inputs, tool.spec.input_schema)
            self.ctx.scope = SimpleNamespace(task_id='t', run_id='r')
            result = await tool.execute(self.ctx, inputs)
            self.assertEqual(result['dom']['root']['id'], 'field')
            self.assertEqual(result['dom']['root']['match_count'], 1)
        finally:
            server.close()
            await server.wait_closed()

    async def test_unique_semantic_match_must_be_the_observed_element(self):
        from taskweave_playwright import snapshot
        await self.page.set_content('<a>今天</a><a href="/other">今天</a>')
        data = await snapshot(self.page)
        first = data['elements'][0]
        selector = first['selector']
        locator = locate(self.page, selector)
        self.assertFalse(await locator.evaluate("e => e.hasAttribute('href')"))

    async def test_open_shadow_dom_same_tag_siblings_have_distinct_verified_locators(self):
        self.ctx.scope = SimpleNamespace(task_id='t', run_id='r')
        await self.page.set_content('<div id="host"></div>')
        await self.page.locator('#host').evaluate("e => {e.attachShadow({mode:'open'}).innerHTML='<button>重复</button><button>重复</button>'}")
        result = await self.actions['playwright.page_inspect'].execute(self.ctx, {'selector': '#host'})
        nodes = result['dom']['root']['children']
        self.assertEqual(len(nodes), 2)
        self.assertNotEqual(nodes[0]['selector'], nodes[1]['selector'])
        for index, node in enumerate(nodes):
            self.assertTrue(await locate(self.page, node['selector']).evaluate('(e, index) => Array.from(e.parentNode.children).indexOf(e)===index', index))
