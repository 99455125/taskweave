"""Staged browser files and failure evidence."""

import asyncio
from taskweave.plugins.sdk import PreparedResult
from ._compat import snapshot

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


async def failure_results(ctx, error):
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
