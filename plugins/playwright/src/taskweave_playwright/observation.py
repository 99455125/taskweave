"""Shared bounded DOM descriptions for snapshots and optional local inspection."""
from playwright.async_api import Error
from taskweave.plugins.sdk import PluginError
from .protocol import reply

DESCRIBE_JS = r'''
const visible = e => {const s=getComputedStyle(e); return s.visibility!=='hidden' && s.display!=='none' && Array.from(e.getClientRects()).some(r=>r.width>0 && r.height>0)};
const inViewport = e => Array.from(e.getClientRects()).some(r=>r.bottom>=0 && r.right>=0 && r.top<=innerHeight && r.left<=innerWidth);
const parent = e => e.parentElement || e.getRootNode()?.host || null;
const domPath = e => {
  const parts=[];
  for(let node=e;node&&node.nodeType===1;node=parent(node)){
    const root=node.getRootNode();
    if(node.id && root===node.ownerDocument && root.querySelectorAll('#'+CSS.escape(node.id)).length===1){parts.unshift('#'+CSS.escape(node.id));break;}
    const tag=node.localName;
    const siblings=node.parentNode?.children?Array.from(node.parentNode.children).filter(s=>s.localName===tag):[node];
    parts.unshift(tag+':nth-of-type('+(siblings.indexOf(node)+1)+')');
  }
  return parts.join(' > ');
};
const ariaName = e => (e.getAttribute('aria-label')||(e.getAttribute('aria-labelledby')||'').split(/\s+/).map(id=>e.ownerDocument.getElementById(id)?.innerText||'').join(' ').trim());
const groupFor = e => {
  for(let node=parent(e),depth=0;node&&depth<8;node=parent(node),depth++){
    const role=node.getAttribute('role');
    if(node.localName==='fieldset' || ['group','radiogroup'].includes(role)){
      return {name:(ariaName(node)||node.querySelector(':scope > legend')?.innerText||'').trim().slice(0,160), selector:{kind:'css',value:domPath(node)}};
    }
  }
  return null;
};
const summary = e => ({tag:e.localName,id:e.id||'',role:e.getAttribute('role')||'',name:(ariaName(e)||e.querySelector(':scope > legend')?.innerText||'').trim().slice(0,160),selector:{kind:'css',value:domPath(e)}});
const describe = (e, includeValues = false) => {
  const tag=e.localName;
  const role=e.getAttribute('role')||({button:'button',textarea:'textbox',select:'combobox',a:'link',img:'img'}[tag])||(e.type==='radio'?'radio':e.type==='checkbox'?'checkbox':e.type==='submit'?'button':e.type==='text'||e.type==='search'?'textbox':'');
  const label=Array.from(e.labels||[]).map(l=>l.innerText).join(' ').trim().slice(0,240);
  const name=(ariaName(e)||label||e.getAttribute('alt')||(role==='button'&&tag==='input'?e.value:e.innerText)||'').replace(/\s+/g,' ').trim().slice(0,120);
  const placeholder=e.getAttribute('placeholder')||'';
  const css={kind:'css',value:domPath(e)};
  const semantic=placeholder?{kind:'placeholder',value:placeholder,exact:true}:label?{kind:'label',value:label,exact:true}:role&&name?{kind:'role',value:role,name,exact:true}:null;
  const candidates=e.id?[css,...(semantic?[semantic]:[])]:[...(semantic?[semantic]:[]),css];
  const sensitive=e.type==='password'||/pass(word)?|secret|token|credential|auth|api.?key|otp|验证码/i.test([e.id,e.name,e.getAttribute('autocomplete'),e.getAttribute('aria-label')].join(' '));
  const attributes={};
  for(const attr of Array.from(e.attributes)){
    if(['id','class','name','type','role','title','placeholder'].includes(attr.name)||attr.name.startsWith('aria-')) attributes[attr.name]=attr.value.slice(0,240);
    if(Object.keys(attributes).length>=16)break;
  }
  const nativeCheck=e.matches('input[type=checkbox],input[type=radio]');
  const ariaChecked=e.getAttribute('aria-checked');
  const checkable=nativeCheck||ariaChecked!==null;
  const mixed=nativeCheck?!!e.indeterminate:ariaChecked==='mixed';
  const ancestors=[];
  for(let node=parent(e),depth=0;node&&depth<4;node=parent(node),depth++)ancestors.push(summary(node));
  const choices=tag==='select'?Array.from(e.options).slice(0,80).map(o=>({label:o.label,value:o.value,disabled:o.disabled})):undefined;
  const hasValue=includeValues&&['input','textarea','select'].includes(tag);
  const value=hasValue?(sensitive?'[redacted]':String(e.value).slice(0,2048)):null;
  return {tag,width:Math.round(e.getBoundingClientRect().width),height:Math.round(e.getBoundingClientRect().height),id:e.id||'',type:e.type||'',role,name,label,placeholder,visible:visible(e),enabled:!e.matches(':disabled')&&e.getAttribute('aria-disabled')!=='true',editable:(tag==='textarea'||tag==='input'||e.isContentEditable)&&!e.readOnly&&!e.disabled,
    selector:candidates[0],css_selector:css.value,candidate_selectors:candidates.map(selector=>({selector})),attributes,
    ...(hasValue?{value,value_redacted:sensitive}:{}),
    ...(hasValue&&!sensitive&&String(e.value).length>2048?{value_truncated:true}:{}),
    ...(checkable?{checked:mixed?null:nativeCheck?e.checked:ariaChecked==='true',mixed}:{}),
    ...(nativeCheck?{selected:e.checked}:tag==='option'?{selected:e.selected}:{}),
    ancestor_chain:ancestors,field_group:groupFor(e),
    ...(choices?{options:choices,options_truncated:e.options.length>choices.length}:{})};
};
'''

ELEMENTS_JS = '(els, options) => {' + DESCRIBE_JS + '''
return els.filter(e=>visible(e)&&(options.allElements||inViewport(e)))
  .sort((a,b)=>a.getBoundingClientRect().top-b.getBoundingClientRect().top||a.getBoundingClientRect().left-b.getBoundingClientRect().left)
  .slice(0,options.limit).map(e=>describe(e));
}'''

DOM_JS = '(element, options) => {' + DESCRIBE_JS + '''
let count=0,truncated=false;
const walk=(e,depth)=>{
  if(count>=options.maxNodes){truncated=true;return null;}
  count++;
  const node=describe(e,true);
  node.children=[];
  if(options.includeDescendants){
    const children=Array.from(e.children).filter(child=>!['script','style','noscript','meta','link'].includes(child.localName));
    if(e.shadowRoot)children.push(...e.shadowRoot.children);
    if(depth>=options.depth){if(children.length)truncated=true;}
    else for(const child of children){
      if(count>=options.maxNodes){truncated=true;break;}
      const item=walk(child,depth+1);if(item)node.children.push(item);
    }
  }
  // Keep containers as structural parents. interactiveOnly suppresses their
  // descriptive text rather than flattening away the DOM hierarchy.
  if(options.interactiveOnly&&!e.matches('input,textarea,select,button,a,[role]'))node.name='';
  if(!options.includeAncestors)delete node.ancestor_chain;
  return node;
};
const root=walk(element,0);
return {root,ancestors:options.includeAncestors?root.ancestor_chain:[],node_count:count,truncated};
}'''


async def verify_candidates(page, item, locate):
    candidates = item['candidate_selectors']
    for candidate in candidates:
        try:
            observed = await reply(locate(page, candidate['selector']).evaluate_all(
                '(els, expected) => {' + DESCRIBE_JS + 'return {match_count:els.length,matches_element:els.length===1&&domPath(els[0])===expected};}',
                item['css_selector']))
            candidate.update(observed)
        except Error:
            candidate.update(match_count=None, matches_element=False)
    chosen = next((candidate for candidate in candidates if candidate['match_count'] == 1 and candidate['matches_element']), None)
    item['selector'] = chosen['selector'] if chosen else None
    item['preferred_selector'] = item['selector']
    item['match_count'] = 1 if chosen else None


async def frame_path(page, frame):
    chain = []
    current = frame
    while current != page.main_frame:
        handle = await current.frame_element()
        try:
            css = await reply(handle.evaluate('e => {' + DESCRIBE_JS + 'return domPath(e);}'))
            if await reply(current.parent_frame.locator(css).count()) != 1:
                return None
        finally:
            await reply(handle.dispose())
        chain.insert(0, css)
        current = current.parent_frame
    return chain[0] if len(chain) == 1 else chain or None


def attach_frame(item, frame_selector):
    if not frame_selector:
        return
    selectors = ([item['selector']] if item['selector'] else []) + [candidate['selector'] for candidate in item['candidate_selectors']]
    for selector in selectors:
        selector['frame'] = frame_selector
    for ancestor in item.get('ancestor_chain', []):
        ancestor['selector']['frame'] = frame_selector
    if item['field_group']:
        item['field_group']['selector']['frame'] = frame_selector


async def inspect_dom(page, inputs, locate):
    locator = locate(page, inputs.get('selector', 'body'))
    count = await locator.count()
    if count != 1:
        raise PluginError('LOCATOR_NOT_FOUND' if not count else 'LOCATOR_AMBIGUOUS', 'Local DOM inspection requires exactly one root')
    data = await locator.evaluate(DOM_JS, {'maxNodes': inputs.get('max_nodes', 100),
        'depth': inputs.get('depth', 3), 'includeDescendants': inputs.get('include_descendants', True),
        'includeAncestors': inputs.get('include_ancestors', True), 'interactiveOnly': inputs.get('interactive_only', False)})
    handle = await locator.element_handle()
    try:
        frame = await handle.owner_frame()
    finally:
        await handle.dispose()
    identity = await frame_path(page, frame)
    async def visit(node):
        await verify_candidates(frame, node, locate)
        attach_frame(node, identity)
        for child in node['children']:
            await visit(child)
    await visit(data['root'])
    return data
