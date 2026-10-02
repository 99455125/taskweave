"""Common interaction and bounded DOM reading against real Chromium."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from playwright.async_api import async_playwright
from taskweave.core.validation import TaskError, validate
from taskweave_playwright import PlaywrightPlugin, _live_context_targets


class PlaywrightActionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.runtime = await async_playwright().start()
        self.browser = await self.runtime.chromium.launch(headless=True)
        self.context = await self.browser.new_context(viewport={'width': 800, 'height': 600})
        self.page = await self.context.new_page()
        self.resource = {'page': self.page, 'context': self.context}
        self.ctx = SimpleNamespace(resources=SimpleNamespace(acquire=AsyncMock(return_value=self.resource)),
            environment={}, task_parameters={}, emit=lambda *args: None)
        self.actions = PlaywrightPlugin().actions()

    async def asyncTearDown(self):
        await self.browser.close()
        await self.runtime.stop()

    async def call(self, action_name, **inputs):
        action = self.actions['playwright.' + action_name]
        validate(inputs, action.spec.input_schema)
        output = await action.execute(self.ctx, inputs)
        validate(output, action.spec.output_schema)
        return output

    async def test_hover_and_double_click_use_scoped_frame_target(self):
        await self.page.set_content('''<button>重复</button><iframe id="frame" srcdoc="
          &lt;section id=local&gt;&lt;button onmouseenter='this.dataset.hovered=1'
          ondblclick='this.textContent=String(2)'&gt;重复&lt;/button&gt;&lt;/section&gt;"></iframe>''')
        selector = {'kind': 'role', 'value': 'button', 'name': '重复', 'within': '#local', 'frame': '#frame'}
        await self.call('page_hover', selector=selector)
        control = self.page.frame_locator('#frame').locator('button')
        self.assertEqual(await control.get_attribute('data-hovered'), '1')
        await self.call('page_double_click', selector=selector)
        self.assertEqual(await control.inner_text(), '2')
        self.assertEqual(await self.page.locator('button').inner_text(), '重复')

    async def test_interaction_rejects_ambiguous_source_and_drag_destination(self):
        await self.page.set_content('<button>重复</button><button>重复</button><div id=source draggable=true>源</div>')
        for name, inputs in [('page_hover', {'selector': 'button'}),
                             ('page_double_click', {'selector': 'button'}),
                             ('page_drag', {'selector': '#source', 'destination': 'button'})]:
            with self.assertRaises(TaskError) as error:
                await self.call(name, **inputs)
            self.assertEqual(error.exception.code, 'LOCATOR_AMBIGUOUS')

    async def test_drag_and_scroll_do_not_depend_on_global_coordinates(self):
        await self.page.set_content('''<div id=source draggable=true ondragstart="event.dataTransfer.setData('text/plain','evidence')">源</div>
          <div id=target ondragover="event.preventDefault()" ondrop="event.preventDefault();this.textContent=event.dataTransfer.getData('text/plain')" style="height:90px">目标</div>
          <div style="height:1200px"></div><button id=bottom>底部</button>''')
        await self.call('page_drag', selector='#source', destination='#target')
        self.assertEqual(await self.page.locator('#target').inner_text(), 'evidence')
        await self.call('page_scroll', selector='#bottom')
        box = await self.page.locator('#bottom').bounding_box()
        self.assertLess(box['y'], 600)
        self.assertGreater(box['y'], 0)

    async def test_scroll_can_advance_a_virtualized_container_by_bounded_delta(self):
        await self.page.set_content('<div id=viewport style="height:100px;overflow:auto"><div style="height:2000px">长列表</div></div>')
        await self.call('page_scroll', selector='#viewport', delta_y=250)
        self.assertEqual(await self.page.locator('#viewport').evaluate('e=>e.scrollTop'), 250)
        with self.assertRaises(TaskError):
            await self.call('page_scroll', selector='#viewport', delta_y=20000)

    async def test_cross_frame_drag_is_explicitly_unsupported(self):
        await self.page.set_content('<div id=source draggable=true>源</div><iframe id=frame srcdoc="&lt;div id=target&gt;目标&lt;/div&gt;"></iframe>')
        with self.assertRaises(TaskError) as error:
            await self.call('page_drag', selector='#source', destination={'kind': 'css', 'value': '#target', 'frame': '#frame'})
        self.assertEqual(error.exception.code, 'DRAG_FRAME_MISMATCH')

    async def test_state_handles_absence_hidden_disabled_readonly_and_plural(self):
        await self.page.set_content('<input id=readonly readonly><button disabled>禁用</button><div id=hidden hidden>隐藏</div>')
        missing = await self.call('page_state', selector='#missing')
        self.assertEqual(missing, {'match_count': 0, 'visible': None, 'enabled': None, 'editable': None})
        hidden = await self.call('page_state', selector='#hidden')
        self.assertFalse(hidden['visible'])
        self.assertFalse((await self.call('page_state', selector='button'))['enabled'])
        self.assertFalse((await self.call('page_state', selector='#readonly'))['editable'])
        plural = await self.call('page_state', selector='input,button')
        self.assertEqual(plural['match_count'], 2)
        self.assertIsNone(plural['visible'])
        await self.call('page_assert_state', selector='#missing', expected={'count': 0})
        await self.call('page_assert_state', selector='#hidden', expected={'visible': False})
        await self.call('page_assert_state', selector='#readonly', expected={'editable': False})

    async def test_state_assertion_waits_and_failure_is_business_diagnostic(self):
        await self.page.set_content('<button id=ready disabled>稍后启用</button>')
        await self.page.evaluate("setTimeout(()=>document.querySelector('button').disabled=false,100)")
        await self.call('page_assert_state', selector='#ready', expected={'enabled': True}, timeout_ms=1500)
        with self.assertRaises(TaskError) as error:
            await self.call('page_assert_state', selector='#ready', expected={'count': 2}, timeout_ms=100)
        self.assertEqual(error.exception.code, 'BUSINESS_ASSERTION_FAILED')
        with self.assertRaises(TaskError) as error:
            await self.call('page_assert_state', selector='body,button', expected={'enabled': True}, timeout_ms=100)
        self.assertEqual(error.exception.code, 'LOCATOR_AMBIGUOUS')

    async def test_attribute_reads_absent_and_truncated_without_form_values(self):
        await self.page.set_content('<input id=secret type=password value="do-not-copy"><div id=data></div>')
        self.assertIsNone((await self.call('page_attribute', selector='#data', name='title'))['value'])
        await self.page.locator('#data').evaluate("e=>e.setAttribute('title','中'.repeat(9000))")
        result = await self.call('page_attribute', selector='#data', name='title')
        self.assertEqual(len(result['value']), 8192)
        self.assertTrue(result['truncated'])
        for attribute in ['value', 'onclick', 'data-token']:
            with self.assertRaises(TaskError):
                await self.call('page_attribute', selector='#secret', name=attribute)

    async def test_list_read_is_scoped_bounded_and_does_not_read_input_values(self):
        await self.page.set_content('<ul id=list><li>甲</li><li hidden>隐藏</li><li>乙<input value=secret></li><li>丙丙丙丙</li></ul><li>范围外</li><textarea>private-textarea-value</textarea>')
        result = await self.call('page_list', selector={'kind': 'css', 'value': 'li', 'within': '#list'}, max_items=2)
        self.assertEqual(result['total_count'], 3)
        self.assertEqual([row['text'] for row in result['items']], ['甲', '乙'])
        self.assertTrue(result['truncated'])
        full = await self.call('page_list', selector='#list li', include_hidden=True, max_text=2)
        self.assertEqual(full['total_count'], 4)
        self.assertEqual(full['items'][-1]['text'], '丙丙')
        self.assertTrue(full['items'][-1]['truncated'])
        self.assertNotIn('secret', json.dumps(full))
        empty = await self.call('page_list', selector='#absent')
        self.assertEqual(empty['items'], [])
        self.assertFalse(empty['truncated'])
        inputs = await self.call('page_list', selector='textarea')
        self.assertEqual(inputs['items'][0]['text'], '')

    async def test_table_preserves_headers_spans_excludes_nested_tables_and_limits(self):
        await self.page.set_content('''<table id=outer><thead><tr><th colspan=2>标题</th></tr></thead><tbody>
          <tr><td rowspan=2>甲</td><td>乙<table><tr><td>嵌套内容</td></tr></table></td></tr>
          <tr><td>丙</td></tr><tr hidden><td>隐藏</td></tr></tbody></table>''')
        result = await self.call('page_table', selector='#outer', max_rows=2)
        self.assertEqual(result['total_rows'], 3)
        self.assertEqual(len(result['rows']), 2)
        self.assertTrue(result['truncated'])
        header = result['rows'][0]['cells'][0]
        self.assertTrue(header['header'])
        self.assertEqual(header['col_span'], 2)
        self.assertEqual(result['rows'][1]['cells'][0]['row_span'], 2)
        self.assertEqual(result['rows'][1]['cells'][1]['text'], '乙')
        with self.assertRaises(TaskError) as error:
            await self.call('page_table', selector='body')
        self.assertEqual(error.exception.code, 'LOCATOR_NOT_TABLE')

    async def test_aria_grid_in_frame_and_payload_limit_are_explicit(self):
        await self.page.set_content('''<iframe id=grid srcdoc="&lt;div role=grid&gt;&lt;div role=row&gt;&lt;span role=columnheader&gt;名称&lt;/span&gt;&lt;/div&gt;&lt;div role=row&gt;&lt;span role=gridcell&gt;值&lt;/span&gt;&lt;/div&gt;&lt;/div&gt;"></iframe>''')
        result = await self.call('page_table', selector={'kind': 'role', 'value': 'grid', 'frame': '#grid'})
        self.assertEqual(result['total_rows'], 2)
        self.assertTrue(result['rows'][0]['cells'][0]['header'])
        await self.page.set_content('<table id=large></table>')
        await self.page.locator('#large').evaluate("e=>e.innerHTML=('<tr>'+('<td>'+('中'.repeat(1024))+'</td>').repeat(5)+'</tr>').repeat(60)")
        large = await self.call('page_table', selector='#large', max_rows=100, max_columns=30, max_text=2048)
        self.assertTrue(large['truncated'])
        self.assertLess(len(json.dumps(large, ensure_ascii=False).encode()), 131072)

    async def test_new_actions_honor_target_identity_and_declared_write_effect(self):
        page = await self.context.new_page()
        await page.set_content('<button disabled>另一个页面</button>')
        target = next(key for key, value in _live_context_targets(self.resource) if value is page)
        self.assertFalse((await self.call('page_state', target_id=target, selector='button'))['enabled'])
        await page.close()
        with self.assertRaises(TaskError) as error:
            await self.call('page_state', target_id=target, selector='button')
        self.assertEqual(error.exception.code, 'BROWSER_TARGET_STALE')
        for name in ['page_hover', 'page_double_click', 'page_drag', 'page_scroll']:
            spec = self.actions['playwright.' + name].spec
            self.assertEqual(spec.effect, 'WRITE')
            self.assertFalse(spec.retry_safe)
        for name in ['page_state', 'page_assert_state', 'page_attribute', 'page_list', 'page_table']:
            self.assertEqual(self.actions['playwright.' + name].spec.effect, 'READ')
