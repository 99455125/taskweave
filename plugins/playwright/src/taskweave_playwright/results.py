"""Staged browser files and failure evidence."""

import asyncio
from taskweave.plugins.sdk import PreparedResult
from ._compat import snapshot


async def result_artifacts(ctx, result):
    return await _capture_pages(ctx, result, "步骤结束页面截图")


async def _capture_pages(ctx, result, caption, *, budget=None):
    """Save the final state of pages observed by this step, preserving business data."""
    from taskweave.plugins.sdk import ResultRequest, StepResult
    deadline = asyncio.get_running_loop().time() + budget if budget is not None else None
    requests, views = [], []
    names = {output.name for output in result.outputs}
    titles = {view['title'] for view in result.views}
    pages = getattr(ctx, '_playwright_result_pages', [])
    if len(pages) > 8:
        ctx.log('WARNING', '步骤涉及超过 8 个页面，自动截图仅保存前 8 个页面')
    for index, (role, page) in enumerate(pages[:8], 1):
        timeout = min(3000, max(0, int((deadline - asyncio.get_running_loop().time()) * 1000))) if deadline else 3000
        if timeout < 50:
            ctx.log('WARNING', '截图时间预算已用尽，剩余页面未保存截图')
            break
        name = 'page_capture_' + str(index)
        while name in names:
            name += '_auto'
        names.add(name)
        title = caption + ' · ' + str(role) + ' · ' + str(index)
        while title in titles:
            title += '（自动）'
        titles.add(title)
        try:
            staged = await ctx.allocate_file(name)
            await page.screenshot(path=staged.local_path, type='png', full_page=True,
                                  timeout=timeout, animations='disabled')
            requests.append(ResultRequest('playwright.image', name, {'staged_file': staged.token}))
            views.append({'title': title, 'renderer': 'playwright.screenshot', 'output': name})
        except Exception as exc:
            ctx.emit('ScreenshotCaptureFailed', {'role': role, 'error_code': type(exc).__name__})
            ctx.log('WARNING', '步骤结束页面截图未保存：' + type(exc).__name__)
    return StepResult(outputs=requests, views=views)


class FileResult:
    def __init__(self, media_type):
        self.media_type = media_type

    def schema(self):
        return {"kind": "file"}

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


async def failure_results(ctx, error):
    from taskweave.plugins.sdk import StepResult

    deadline = asyncio.get_running_loop().time() + .75
    for role, page in getattr(ctx, '_playwright_result_pages', [])[:8]:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            break
        if not page.is_closed():
            try:
                data = await asyncio.wait_for(snapshot(page), remaining)
                ctx.emit('BrowserFailureSnapshot', {'role': role, 'snapshot': data})
            except Exception:
                ctx.emit('BrowserFailureSnapshotUnavailable', {'role': role})
    return await _capture_pages(ctx, StepResult(), '失败页面截图', budget=3.75)
