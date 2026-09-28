import importlib.util
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from taskweave.plugins.sdk import PluginError


class Page:
    def __init__(self, title, url):
        self.name = title
        self.url = url
        self.frames = []
        self.closed = False
        self.navigations = []

    async def title(self):
        return self.name

    def is_closed(self):
        return self.closed

    async def goto(self, url, **kwargs):
        self.navigations.append(url)
        self.url = url


class Resources:
    def __init__(self, entries=()):
        self.entries = dict(entries)
        self.acquisitions = []

    def active(self, provider_id):
        if provider_id != "playwright.session":
            raise AssertionError(provider_id)
        return list(self.entries.items())

    async def acquire(self, provider_id, role):
        self.acquisitions.append((provider_id, role))
        if role not in self.entries:
            page = Page("Opened", "about:blank")
            self.entries[role] = resource(page)
        return self.entries[role]


def resource(*pages):
    return {"page": pages[0], "context": Context(pages)}


class Context:
    def __init__(self, pages):
        self.pages = list(pages)

    async def new_page(self):
        page = Page("Opened", "about:blank")
        self.pages.append(page)
        return page


@unittest.skipUnless(
    importlib.util.find_spec("taskweave_playwright") and importlib.util.find_spec("playwright"),
    "Install browser extra to run Playwright context target tests",
)
class PlaywrightContextTargetTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from taskweave_playwright import PlaywrightPlugin

        self.plugin = PlaywrightPlugin()
        self.first = Page("Same title", "https://example.test/start")
        self.second = Page("Same title", "https://user:password@example.test/popup?token=secret#private")
        self.other = Page("Other role", "https://example.test/other")
        self.resources = Resources({"operator": resource(self.first, self.second), "reviewer": resource(self.other)})
        self.ctx = SimpleNamespace(resources=self.resources, environment={}, task_parameters={}, scope=SimpleNamespace(task_id="task", run_id="run"))

    async def targets(self):
        return await self.plugin.list_context_targets("playwright.page", self.ctx, {"role": "operator"})

    async def test_lists_every_live_page_without_acquiring_and_keeps_ids_after_reorder(self):
        closed = Page("Closed", "https://example.test/closed")
        closed.closed = True
        self.resources.entries["operator"]["context"].pages.append(closed)
        first = await self.targets()
        self.assertEqual(len(first), 3)
        self.assertEqual([item["request"]["role"] for item in first], ["operator", "operator", "reviewer"])
        self.assertEqual(len({item["target_id"] for item in first}), 3)
        self.assertEqual(len({item["label"] for item in first}), 3)
        self.assertEqual({"url": "https://example.test/old", **first[0]["request"]}["url"], "")
        self.assertIn("https://example.test/popup", first[1]["label"])
        for secret in ("password", "user:", "token", "secret", "private"):
            self.assertNotIn(secret, first[1]["label"])
        self.second.name = "Renamed"
        self.resources.entries["operator"]["context"].pages.reverse()
        second = await self.targets()
        self.assertEqual(second[0]["target_id"], first[1]["target_id"])
        self.assertEqual(second[1]["target_id"], first[0]["target_id"])
        self.assertEqual(self.resources.acquisitions, [])

    async def test_empty_listing_does_not_open_a_session(self):
        self.resources.entries.clear()
        self.assertEqual(await self.targets(), [])
        self.assertEqual(self.resources.acquisitions, [])

    async def test_manifest_declares_generic_page_target_selection(self):
        schema = self.plugin.manifest()['context_requests']['playwright.page']
        self.assertEqual(schema['x-taskweave-context-targets'], {
            'selector_label': '上下文实例 / 页面',
            'parameter_mode_label': '新建页面',
            'auto_select_single': True,
            'hide_parameters_when_selected': True,
            'keep_parameters_when_selected': ['scope'],
        })
        self.assertEqual(schema['required'], ['url'])
        self.assertEqual(schema['properties']['scope']['default'], 'full_page')
        self.assertEqual(schema['x-taskweave-context-surface-defaults'], {'planning': {'scope': 'viewport'}})
        self.assertEqual(schema['properties']['scope']['enum'], ['viewport', 'full_page'])
        self.assertEqual(schema['x-taskweave-context-view'], {'default': True})

    async def test_collection_returns_plugin_defined_screenshot_view(self):
        chosen = (await self.targets())[0]
        self.first.screenshot = AsyncMock(return_value=b'image')
        with patch('taskweave_playwright.snapshot', AsyncMock(return_value={
            'title': 'Same title', 'url': self.first.url, 'captured_at': 'now',
            'elements': [], 'frames': [], 'truncated': False,
        })) as observe:
            capture = await self.plugin.collect_context(
                'playwright.page', self.ctx,
                {**chosen['request'], 'scope': 'full_page'}, include_view=True,
            )
        self.assertEqual(len(capture.items), 1)
        self.assertEqual(capture.views[0].renderer, 'playwright.screenshot')
        self.assertEqual(capture.views[0].data['image_base64'], 'aW1hZ2U=')
        observe.assert_awaited_once_with(self.first, scope='full_page')
        self.first.screenshot.assert_awaited_once_with(type='png', full_page=True)

    async def test_collection_defaults_to_full_page(self):
        chosen = (await self.targets())[0]
        self.first.screenshot = AsyncMock(return_value=b'image')
        with patch('taskweave_playwright.snapshot', AsyncMock(return_value={
            'title': 'Same title', 'url': self.first.url, 'captured_at': 'now',
            'elements': [], 'frames': [], 'truncated': False,
        })) as observe:
            capture = await self.plugin.collect_context(
                'playwright.page', self.ctx, chosen['request'], include_view=True,
            )
        observe.assert_awaited_once_with(self.first, scope='full_page')
        self.first.screenshot.assert_awaited_once_with(type='png', full_page=True)
        self.assertEqual(capture.views[0].title, '完整页面截图')

    async def test_selects_second_page_without_changing_role_default_or_navigating(self):
        chosen = (await self.targets())[1]
        items = await self.plugin.collect_context("playwright.page", self.ctx, chosen["request"], include_view=False)
        data = json.loads(items.items[0].content)
        self.assertTrue(data["url"].endswith("/popup"))
        self.assertEqual(data["role"], "operator")
        self.assertIs(self.resources.entries["operator"]["page"], self.first)
        self.assertEqual(self.second.navigations, [])
        self.assertEqual(self.resources.acquisitions, [])

    async def test_selected_other_role_is_recorded_in_snapshot(self):
        chosen = (await self.targets())[2]
        items = await self.plugin.collect_context("playwright.page", self.ctx, chosen["request"], include_view=False)
        self.assertEqual(json.loads(items.items[0].content)["role"], "reviewer")
        self.assertEqual(self.resources.acquisitions, [])

    async def test_closed_unknown_and_wrong_role_targets_never_fall_back(self):
        chosen = (await self.targets())[1]
        self.second.closed = True
        for request in (chosen["request"], {"target_id": "missing"}, {"target_id": ""}, {**(await self.targets())[-1]["request"], "role": "operator"}):
            with self.subTest(request=request):
                with self.assertRaises(PluginError) as error:
                    await self.plugin.collect_context("playwright.page", self.ctx, request)
                self.assertEqual(error.exception.code, "CONTEXT_TARGET_UNAVAILABLE")
        self.assertEqual(len(await self.targets()), 2)
        self.assertEqual(self.resources.acquisitions, [])

    async def test_selected_page_with_url_is_rejected_before_navigation(self):
        chosen = (await self.targets())[1]
        with self.assertRaises(PluginError) as error:
            await self.plugin.collect_context("playwright.page", self.ctx, {**chosen["request"], "url": "https://example.test/new"})
        self.assertEqual(error.exception.code, "CONTEXT_TARGET_REQUEST_INVALID")
        self.assertEqual(self.second.navigations, [])
        self.assertEqual(self.resources.acquisitions, [])

    async def test_page_closed_during_capture_reports_target_unavailable(self):
        from playwright.async_api import Error

        chosen = (await self.targets())[1]

        async def closing_title():
            self.second.closed = True
            raise Error("Target page has been closed")

        self.second.title = closing_title
        with self.assertRaises(PluginError) as error:
            await self.plugin.collect_context("playwright.page", self.ctx, chosen["request"])
        self.assertEqual(error.exception.code, "CONTEXT_TARGET_UNAVAILABLE")
        self.assertEqual(self.resources.acquisitions, [])

    async def test_no_target_retains_existing_role_and_first_open_behavior(self):
        items = await self.plugin.collect_context("playwright.page", self.ctx, {"role": "reviewer"}, include_view=False)
        self.assertEqual(json.loads(items.items[0].content)["role"], "reviewer")
        items = await self.plugin.collect_context("playwright.page", self.ctx, {"role": "new", "url": "https://example.test/new"}, include_view=False)
        self.assertEqual(json.loads(items.items[0].content)["url"], "https://example.test/new")
        self.assertEqual(self.resources.entries["new"]["page"].navigations, ["https://example.test/new"])

    async def test_new_page_mode_does_not_navigate_an_existing_page(self):
        items = await self.plugin.collect_context(
            "playwright.page",
            self.ctx,
            {"role": "operator", "url": "https://example.test/new-page"},
            include_view=False,
        )
        self.assertEqual(json.loads(items.items[0].content)["url"], "https://example.test/new-page")
        self.assertEqual(self.first.navigations, [])
        pages = self.resources.entries["operator"]["context"].pages
        self.assertEqual(len(pages), 3)
        self.assertEqual(pages[-1].navigations, ["https://example.test/new-page"])

    async def test_unknown_provider_is_rejected(self):
        with self.assertRaises(PluginError) as error:
            await self.plugin.list_context_targets("missing", self.ctx, {})
        self.assertEqual(error.exception.code, "CONTEXT_PROVIDER_UNAVAILABLE")
