"""Playwright choice evidence and actions against a local, in-memory page."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from playwright.async_api import async_playwright
from taskweave_playwright import PlaywrightPlugin, snapshot


class PlaywrightChoiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.runtime = await async_playwright().start()
        self.browser = await self.runtime.chromium.launch(headless=True)
        self.page = await self.browser.new_page(viewport={"width": 1000, "height": 700})
        await self.page.set_content("""
            <label for="region">地区</label>
            <select id="region"><option value="">请选择</option><option value="east">华东</option></select>
            <input id="agency" aria-label="机构代码" onkeydown="if(event.key==='Enter')document.querySelector('#status').textContent='已确认'">
            <div id="status"></div>
            <div role="listbox" aria-label="机构候选">
              <div role="option" onclick="document.querySelector('#agency').value='第一机构'">第一机构</div>
              <div role="option">第二机构</div>
            </div>
            <table role="grid"><tr><td role="gridcell">24</td></tr></table>
        """)
        self.plugin = PlaywrightPlugin()
        self.ctx = SimpleNamespace(
            resources=SimpleNamespace(acquire=AsyncMock(return_value={"page": self.page})),
            environment={}, task_parameters={}, emit=lambda *args: None,
        )

    async def asyncTearDown(self):
        await self.browser.close()
        await self.runtime.stop()

    async def test_snapshot_includes_native_and_custom_choices(self):
        observed = await snapshot(self.page, scope="viewport")
        self.assertFalse(observed["truncated"])
        select = next(item for item in observed["elements"] if item["tag"] == "select")
        self.assertEqual(select["options"][1], {"label": "华东", "value": "east", "disabled": False})
        choices = [item for item in observed["elements"] if item["role"] == "option"]
        self.assertEqual([item["name"] for item in choices], ["第一机构", "第二机构"])
        self.assertTrue(all(item["match_count"] == 1 and item["selector"] for item in choices))
        self.assertTrue(any(item["role"] == "gridcell" and item["name"] == "24" for item in observed["elements"]))
        await self.plugin.actions()["playwright.page_click"].execute(
            self.ctx, {"selector": choices[0]["selector"]},
        )
        self.assertEqual(await self.page.locator("#agency").input_value(), "第一机构")

    async def test_press_and_native_select_option(self):
        actions = self.plugin.actions()
        self.assertIn("playwright.page_press", actions)
        self.assertIn("playwright.page_select_option", actions)
        await actions["playwright.page_select_option"].execute(
            self.ctx, {"selector": "#region", "option": {"label": "华东"}},
        )
        self.assertEqual(await self.page.locator("#region").input_value(), "east")
        await actions["playwright.page_press"].execute(
            self.ctx, {"selector": "#agency", "key": "Enter"},
        )
        self.assertEqual(await self.page.locator("#status").inner_text(), "已确认")
