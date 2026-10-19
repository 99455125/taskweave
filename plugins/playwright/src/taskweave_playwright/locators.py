"""Scoped locators and bounded, verified page snapshots."""

import asyncio
from datetime import datetime, timezone
from taskweave.plugins.sdk import PluginError
from .observation import ELEMENTS_JS, verify_candidates, frame_path, attach_frame
from .protocol import reply

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
