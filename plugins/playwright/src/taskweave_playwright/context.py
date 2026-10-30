"""Page target selection, context collection and recording orchestration."""

import base64
import json
from urllib.parse import urlparse
from playwright.async_api import Error
from taskweave.plugins.sdk import ContextCollection, ContextItem, ContextView, PluginError
from ._compat import snapshot
from .session import page_for, _live_context_targets

async def list_context_targets(provider_id, ctx, request):
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


async def record_context(provider_id, ctx, command, request, *, include_view=True):
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
            if resource is not None and resource.get('context_recorder') is not None:
                resource['context_recorder'].ensure_start_available()
            if resource is None:
                # Opening a resource already allocates its initial main page.
                # Navigate that page instead of leaving it blank beside a second tab.
                page = await page_for(ctx, role)
                resource = next(resource for active_role, resource in ctx.resources.active('playwright.session') if active_role == role)
            elif (not resource['page'].is_closed() and resource['page'].url == 'about:blank'
                  and await resource['page'].evaluate(
                      "() => location.href === 'about:blank' && document.title === '' "
                      "&& document.body !== null && document.body.childNodes.length === 0")):
                # A retained resource may also still have its untouched initial tab.
                # A blank URL with DOM content is user work, not an unused page.
                page = resource['page']
            else:
                # An existing session can contain user work; do not navigate its main page.
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
    return await record(resource, page, command, include_view=include_view, role=role)


async def collect_context(provider_id, ctx, request, *, include_view=True):
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
