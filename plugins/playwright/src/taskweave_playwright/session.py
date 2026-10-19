"""Browser resource lifecycle and role-scoped page identity."""

from uuid import uuid4
from ._compat import runtime_factory
from taskweave.plugins.sdk import PluginError

class BrowserSession:
    async def open(self, ctx, role):
        runtime = await runtime_factory().start()
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
