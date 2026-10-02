"""Common locator interactions and bounded DOM reads; no host or UI dependencies."""
import asyncio
from playwright.async_api import expect
from taskweave.plugins.sdk import PluginError
from .protocol import reply


INTERACTIONS = {'page_hover', 'page_double_click', 'page_scroll', 'page_drag'}
READS = {'page_state', 'page_assert_state', 'page_attribute', 'page_list', 'page_table'}
SINGULAR_READS = {'page_attribute', 'page_table'}
ATTRIBUTE_PATTERN = r'^(id|class|role|name|type|title|placeholder|alt|tabindex|disabled|checked|selected|readonly|required|colspan|rowspan|aria-[a-z][a-z-]*)$'


def entries(schema, locator):
    boolean = {'type': 'boolean'}
    integer = lambda maximum: {'type': 'integer', 'minimum': 1, 'maximum': maximum}
    matched = {'type': 'object', 'properties': {'matched': {'const': True}}, 'required': ['matched']}
    text = {'type': 'string'}
    nullable = {'type': ['boolean', 'null']}
    result = []
    for name, description in [
        ('page_hover', 'Hover a unique observed control; may reveal menus or trigger handlers'),
        ('page_double_click', 'Double-click a unique observed control; may submit business'),
    ]:
        result.append((name, description, schema({'selector': locator}, ['selector']), {'type': 'null'}, 'WRITE'))
    delta = {'type': 'integer', 'minimum': -10000, 'maximum': 10000}
    result.append(('page_scroll', 'Scroll an observed element into view, or scroll its container by bounded pixel deltas; inspect again for virtualized rows',
        schema({'selector': locator, 'delta_x': delta, 'delta_y': delta}, ['selector']), {'type': 'null'}, 'WRITE'))
    result.append(('page_drag', 'Drag between two unique observed controls in the same frame',
        schema({'selector': locator, 'destination': locator}, ['selector', 'destination']), {'type': 'null'}, 'WRITE'))
    result.append(('page_state', 'Read current match count; visible/enabled/editable are null unless exactly one element matches',
        schema({'selector': locator}, ['selector']), {'type': 'object', 'properties': {
            'match_count': {'type': 'integer', 'minimum': 0}, 'visible': nullable, 'enabled': nullable, 'editable': nullable},
            'required': ['match_count', 'visible', 'enabled', 'editable']}, 'READ'))
    result.append(('page_assert_state', 'Wait for observed count/state; state fields require exactly one attached element (hidden is not absent)',
        schema({'selector': locator, 'expected': {'type': 'object', 'properties': {
            'count': {'type': 'integer', 'minimum': 0, 'maximum': 10000},
            'visible': boolean, 'enabled': boolean, 'editable': boolean},
            'minProperties': 1, 'additionalProperties': False}}, ['selector', 'expected']), matched, 'READ'))
    result.append(('page_attribute', 'Read one allowlisted DOM attribute; excludes input values, event handlers and data-*; bounded to 8192 characters',
        schema({'selector': locator, 'name': {'type': 'string', 'pattern': ATTRIBUTE_PATTERN}}, ['selector', 'name']),
        {'type': 'object', 'properties': {'value': {'type': ['string', 'null']}, 'truncated': boolean},
         'required': ['value', 'truncated']}, 'READ'))
    list_item = {'type': 'object', 'properties': {'index': {'type': 'integer'}, 'text': text, 'truncated': boolean},
                 'required': ['index', 'text', 'truncated']}
    result.append(('page_list', 'Read bounded text from currently rendered matches in DOM order; no waiting, paging or input values',
        schema({'selector': locator, 'max_items': integer(100), 'max_text': integer(2048), 'include_hidden': boolean}, ['selector']),
        {'type': 'object', 'properties': {'items': {'type': 'array', 'items': list_item},
            'total_count': {'type': 'integer'}, 'truncated': boolean}, 'required': ['items', 'total_count', 'truncated']}, 'READ'))
    cell = {'type': 'object', 'properties': {'text': text, 'header': boolean, 'row_span': {'type': 'integer'},
        'col_span': {'type': 'integer'}, 'truncated': boolean}, 'required': ['text', 'header', 'row_span', 'col_span', 'truncated']}
    row = {'type': 'object', 'properties': {'index': {'type': 'integer'}, 'cells': {'type': 'array', 'items': cell},
        'truncated': boolean}, 'required': ['index', 'cells', 'truncated']}
    result.append(('page_table', 'Read one native table or ARIA table/grid in DOM order; keep cell spans/headers, exclude nested tables, mark truncation; no virtualized paging',
        schema({'selector': locator, 'max_rows': integer(100), 'max_columns': integer(30),
            'max_text': integer(2048), 'include_hidden': boolean}, ['selector']),
        {'type': 'object', 'properties': {'rows': {'type': 'array', 'items': row}, 'total_rows': {'type': 'integer'},
            'truncated': boolean}, 'required': ['rows', 'total_rows', 'truncated']}, 'READ'))
    return result


# Bound text and serialized result in the browser before sending it to Python.
# The traversal skips scripts/form values/nested tables and stops once text is
# over the requested per-item limit; it never returns a full HTML string.
DOM_HELPERS = r"""
const visible = e => e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden';
const tableSelector = 'table,[role=table],[role=grid],[role=treegrid]';
const text = (root, limit, skipTables) => {
    let value='', overflow=false;
    const walk = node => {
        if (overflow) return;
        if (node.nodeType===3) {
            const space=limit-value.length;
            value+=node.textContent.slice(0,space);
            if (node.textContent.length>space) overflow=true;
        } else if (node.nodeType===1) {
            if (node.matches('script,style,input,textarea,select')) return;
            if (node!==root && (skipTables && node.matches(tableSelector) ||
                !options.include_hidden && !visible(node))) return;
            for (const child of node.childNodes) {walk(child); if (overflow) break;}
        }
    };
    walk(root);
    return {text:value.trim(),truncated:overflow};
};
const byteSize = item => new TextEncoder().encode(JSON.stringify(item)).length;
const budget=98304;
"""

LIST_JS = '(elements, options) => {' + DOM_HELPERS + r"""
    const chosen=elements.map((e,index)=>({e,index})).filter(({e})=>options.include_hidden || visible(e));
    const items=[]; let used=0,truncated=chosen.length>options.max_items;
    for (const {e,index} of chosen.slice(0,options.max_items)) {
        const item={index,...text(e,options.max_text,false)};
        const size=byteSize(item);
        if (used+size>budget) {truncated=true;break;}
        items.push(item); used+=size; truncated ||= item.truncated;
    }
    return {items,total_count:chosen.length,truncated};
}"""

TABLE_JS = '(root, options) => {' + DOM_HELPERS + r"""
    if (!root.matches(tableSelector)) return null;
    const all=Array.from(root.querySelectorAll('tr,[role=row]')).filter(e=>
        e.closest(tableSelector)===root && (options.include_hidden || visible(e)));
    const rows=[]; let used=0,truncated=all.length>options.max_rows;
    for (let index=0;index<Math.min(all.length,options.max_rows);index++) {
        const element=all[index];
        const allCells=Array.from(element.querySelectorAll('td,th,[role=cell],[role=gridcell],[role=columnheader],[role=rowheader]')).filter(e=>
            e.closest('tr,[role=row]')===element && e.closest(tableSelector)===root && (options.include_hidden || visible(e)));
        const row={index,cells:[],truncated:allCells.length>options.max_columns};
        for (const e of allCells.slice(0,options.max_columns)) {
            const span=name=>Math.max(1,Math.min(10000,Number(e.getAttribute(name))||1));
            const cell={...text(e,options.max_text,true),header:e.matches('th,[role=columnheader],[role=rowheader]'),
                row_span:span(e.hasAttribute('aria-rowspan')?'aria-rowspan':'rowspan'),
                col_span:span(e.hasAttribute('aria-colspan')?'aria-colspan':'colspan')};
            const size=byteSize(cell)+1;
            if (used+size+64>budget) {row.truncated=true;truncated=true;break;}
            row.cells.push(cell);used+=size;row.truncated ||= cell.truncated;
        }
        rows.push(row);used+=64;truncated ||= row.truncated;
        if (used+64>=budget || row.cells.length<Math.min(allCells.length,options.max_columns)) {truncated=true;break;}
    }
    return {rows,total_rows:all.length,truncated};
}"""


async def perform(name, page, inputs, locate, target_state):
    locator = locate(page, inputs['selector'])
    timeout = inputs.get('timeout_ms', 10000)
    if name == 'page_hover':
        await locator.hover(timeout=timeout)
    elif name == 'page_double_click':
        await locator.dblclick(timeout=timeout)
    elif name == 'page_scroll':
        if 'delta_x' in inputs or 'delta_y' in inputs:
            await locator.evaluate('''(e,delta)=>{
                const doc=e.ownerDocument;
                const target=e===doc.body || e===doc.documentElement ? doc.scrollingElement : e;
                target.scrollBy({left:delta.x,top:delta.y,behavior:'instant'});
            }''', {'x': inputs.get('delta_x', 0), 'y': inputs.get('delta_y', 0)}, timeout=timeout)
        else:
            await locator.scroll_into_view_if_needed(timeout=timeout)
    elif name == 'page_drag':
        state = await asyncio.wait_for(target_state(page, inputs['destination']), timeout / 1000)
        for condition, code in [(state['match_count'] == 0, 'LOCATOR_NOT_FOUND'),
                                (state['match_count'] > 1, 'LOCATOR_AMBIGUOUS'),
                                (not state.get('visible'), 'LOCATOR_HIDDEN'),
                                (not state.get('enabled'), 'LOCATOR_DISABLED')]:
            if condition:
                raise PluginError(code, 'Drag destination is not a unique visible enabled element')
        destination = locate(page, inputs['destination'])
        source_handle = await locator.element_handle(timeout=timeout)
        destination_handle = None
        try:
            destination_handle = await destination.element_handle(timeout=timeout)
            if source_handle is None or destination_handle is None:
                raise PluginError('LOCATOR_NOT_FOUND', 'Drag endpoint detached before operation')
            if await source_handle.owner_frame() is not await destination_handle.owner_frame():
                raise PluginError('DRAG_FRAME_MISMATCH', 'Drag endpoints must be in the same frame')
        finally:
            if source_handle is not None:
                await source_handle.dispose()
            if destination_handle is not None:
                await destination_handle.dispose()
        await locator.drag_to(destination, timeout=timeout)
    elif name == 'page_state':
        state = await target_state(page, inputs['selector'])
        return {'match_count': state['match_count'], **{key: state.get(key) for key in ('visible', 'enabled', 'editable')}}
    elif name == 'page_assert_state':
        expected = inputs['expected']
        if any(key != 'count' for key in expected) and expected.get('count', 1) != 1:
            raise PluginError('STATE_EXPECTATION_INVALID', 'Visible/enabled/editable require a unique attached element')
        if any(key != 'count' for key in expected) and await locator.count() > 1:
            raise PluginError('LOCATOR_AMBIGUOUS', 'State assertion matches multiple elements')
        deadline = asyncio.get_running_loop().time() + timeout / 1000
        remaining = lambda: max(1, int((deadline - asyncio.get_running_loop().time()) * 1000))
        try:
            await expect(locator).to_have_count(expected.get('count', 1), timeout=remaining())
            if 'visible' in expected:
                await expect(locator).to_be_visible(visible=expected['visible'], timeout=remaining())
            if 'enabled' in expected:
                await expect(locator).to_be_enabled(enabled=expected['enabled'], timeout=remaining())
            if 'editable' in expected:
                # Static containers have no editable state in Playwright's
                # matcher; report an explicit unsupported target instead.
                supported = await locator.evaluate('e=>e.matches("input,textarea,select") || e.isContentEditable', timeout=remaining())
                if not supported:
                    raise PluginError('LOCATOR_NOT_EDITABLE_CONTROL', 'Editable assertions require a form or contenteditable control')
                await expect(locator).to_be_editable(editable=expected['editable'], timeout=remaining())
        except AssertionError as exc:
            raise PluginError('BUSINESS_ASSERTION_FAILED', 'Expected element count or state was not observed') from exc
        return {'matched': True}
    elif name == 'page_attribute':
        return await locator.evaluate('''(e,name)=>{
            const value=e.getAttribute(name);
            return {value:value===null?null:value.slice(0,8192),truncated:value!==null && value.length>8192};
        }''', inputs['name'], timeout=timeout)
    elif name in {'page_list', 'page_table'}:
        options = {'include_hidden': inputs.get('include_hidden', False), 'max_text': inputs.get('max_text', 1024),
                   'max_items': inputs.get('max_items', 100), 'max_rows': inputs.get('max_rows', 100),
                   'max_columns': inputs.get('max_columns', 30)}
        if name == 'page_list':
            return await asyncio.wait_for(reply(locator.evaluate_all(LIST_JS, options)), timeout / 1000)
        data = await locator.evaluate(TABLE_JS, options, timeout=timeout)
        if data is None:
            raise PluginError('LOCATOR_NOT_TABLE', 'Target must be a native table or ARIA table/grid/treegrid')
        return data
    return None
