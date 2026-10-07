"""Independent action contracts and WordPress business validation."""
from taskweave.plugins.sdk import CapabilitySpec


def obj(properties, required=()):
    return {'type':'object','properties':properties,'required':list(required),'additionalProperties':False}

TEXT={'type':'string','minLength':1,'maxLength':4096,'pattern':r'^[^\u0000\r\n]+$'}
CONTENT={'type':'string','maxLength':1048576}
NAME={'type':'string','pattern':r'^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$'}
TABLE={'type':'string','pattern':r'^[A-Za-z0-9_]{1,64}$'}
TABLES={'type':'array','items':TABLE,'minItems':1,'maxItems':100,'uniqueItems':True}
ID={'type':'integer','minimum':1}
ZERO_ID={'type':'integer','minimum':0}
BOOL={'type':'boolean'}
HASH={'type':'string','pattern':r'^[0-9a-f]{64}$'}
PAGE={'limit':{'type':'integer','minimum':1,'maximum':100,'default':20},'offset':{'type':'integer','minimum':0,'maximum':1000000,'default':0}}
POST_TYPE={'enum':['post','page']}
STATUS={'enum':['draft','publish','pending','private','future','trash']}
COMMON={'role':TEXT,'timeout_seconds':{'type':'integer','minimum':1,'maximum':1800,'default':60},'max_output_bytes':{'type':'integer','minimum':1024,'maximum':1048576,'default':65536}}
OUTPUT=obj({'completion':{'enum':['completed','noop']},'result':{},'steps':{'type':'array','items':{'type':'object'}},'artifact':{'type':'object'}},['completion','result','steps'])
DEFINITIONS={}

def declaration(name, properties=None, required=(), effect='WRITE'):
    DEFINITIONS[name]=(obj({**COMMON,**(properties or {})},required),OUTPUT,effect)

for name in ('check_environment','is_installed','verify_checksums'):
    declaration(name,{'network':BOOL} if name=='is_installed' else {'version':NAME,'locale':NAME} if name=='verify_checksums' else {},effect='READ')
declaration('core_download',{'version':NAME,'locale':NAME,'skip_content':BOOL},['version','locale'])
declaration('core_install',{'url':TEXT,'title':TEXT,'admin_user':NAME,'admin_email':TEXT,'admin_password_ref':TEXT},['url','title','admin_user','admin_email','admin_password_ref'])
declaration('core_update',{'version':NAME},['version'])
declaration('config_create',{'dbname':NAME,'dbuser':NAME,'dbhost':TEXT,'dbprefix':TABLE,'db_password_ref':TEXT},['dbname','dbuser','dbhost','dbprefix','db_password_ref'])
for name in ('config_get','config_set'):
    declaration(name,{'name':NAME,'type':{'enum':['constant','variable']},**({'value':TEXT,'value_ref':TEXT} if name=='config_set' else {})},['name'],'READ' if name=='config_get' else 'WRITE')
declaration('option_get',{'key':NAME},['key'],'READ')
declaration('option_set',{'key':NAME,'value':{},'autoload':{'enum':['on','off','yes','no']}},['key','value'])
declaration('set_permalink_structure',{'structure':TEXT,'category_base':TEXT,'tag_base':TEXT,'hard':BOOL},['structure'])
for entity in ('theme','plugin'):
    declaration('list_'+entity+'s',{**PAGE,'status':NAME},effect='READ')
    for verb in ('install','activate','update','delete')+ (('deactivate',) if entity=='plugin' else ()):
        declaration(verb+'_'+entity,{'slug':NAME,**({'source':TEXT} if verb=='install' else {}),**({'version':NAME} if verb in ('install','update') else {}),**({'network':BOOL} if entity=='plugin' and verb in ('activate','deactivate') else {})},['slug'])
declaration('list_posts',{**PAGE,'post_type':POST_TYPE,'status':STATUS,'author':ID,'search':TEXT},effect='READ')
POST_PATCH={'title':TEXT,'status':STATUS,'slug':NAME,'author':ID,'date':TEXT,'excerpt':CONTENT,'parent':ZERO_ID,'content':CONTENT}
declaration('create_post',{'post_type':POST_TYPE,**POST_PATCH},['post_type','title','status','content'])
declaration('update_post',{'id':ID,'post_type':POST_TYPE,**POST_PATCH},['id','post_type'])
declaration('delete_post',{'id':ID,'post_type':POST_TYPE,'force':BOOL},['id','post_type'])
TERM_PATCH={'name':TEXT,'slug':NAME,'description':CONTENT,'parent':ZERO_ID}
declaration('list_terms',{'taxonomy':NAME,**PAGE,'hide_empty':BOOL},['taxonomy'],'READ')
declaration('create_term',{'taxonomy':NAME,**TERM_PATCH},['taxonomy','name'])
declaration('update_term',{'taxonomy':NAME,'id':ID,**TERM_PATCH},['taxonomy','id'])
declaration('delete_term',{'taxonomy':NAME,'id':ID},['taxonomy','id'])
declaration('list_menus',PAGE,effect='READ')
declaration('create_menu',{'name':TEXT},['name'])
declaration('delete_menu',{'menu':ID},['menu'])
MENU_PATCH={'title':TEXT,'link':TEXT,'description':CONTENT,'attr_title':TEXT,'target':{'enum':['_blank','_self']},'classes':TEXT,'position':ID,'parent_id':ZERO_ID}
declaration('add_menu_item',{'menu':ID,'kind':{'enum':['post','term','custom']},'post_id':ID,'term_id':ID,'taxonomy':NAME,**MENU_PATCH},['menu','kind'])
declaration('update_menu_item',{'menu':ID,'id':ID,**MENU_PATCH},['menu','id'])
declaration('delete_menu_item',{'menu':ID,'id':ID},['menu','id'])
declaration('list_media',PAGE,effect='READ')
MEDIA_PATCH={'title':TEXT,'caption':CONTENT,'description':CONTENT,'alt':CONTENT}
declaration('import_media',{'source':TEXT,'parent':ID,'featured_image':BOOL,**MEDIA_PATCH},['source'])
declaration('update_media',{'id':ID,**MEDIA_PATCH},['id'])
declaration('delete_media',{'id':ID},['id'])
USER_ROLE={'enum':['administrator','editor','author','contributor','subscriber']}
declaration('list_users',{**PAGE,'user_role':USER_ROLE,'search':TEXT},effect='READ')
declaration('create_user',{'login':NAME,'email':TEXT,'user_role':USER_ROLE,'password_ref':TEXT},['login','email','user_role','password_ref'])
declaration('set_user_role',{'id':ID,'user_role':USER_ROLE},['id','user_role'])
declaration('set_user_password',{'id':ID,'password_ref':TEXT,'skip_email':BOOL},['id','password_ref'])
declaration('delete_user',{'id':ID,'reassign':ID,'delete_content':BOOL,'network':BOOL},['id'])
TRANSFER={'max_bytes':{'type':'integer','minimum':1,'maximum':67108864,'default':16777216}}
declaration('db_export',{'path':TEXT,'tables':TABLES,**TRANSFER},['path','tables'])
declaration('db_import',{'path':TEXT,'tables':TABLES,'checksum':HASH,**TRANSFER},['path','tables','checksum'])
ARCHIVE={**TRANSFER,'max_unpacked_bytes':{'type':'integer','minimum':1,'maximum':536870912,'default':268435456},'max_members':{'type':'integer','minimum':1,'maximum':100000,'default':10000}}
declaration('backup',{'tables':TABLES,**ARCHIVE},['tables'])
declaration('restore',{'path':TEXT,'checksum':HASH,'tables':TABLES,**ARCHIVE},['path','checksum','tables'])
declaration('search_replace',{'old':TEXT,'new':{'type':'string','maxLength':4096},'tables':TABLES,'dry_run':BOOL,'skip_columns':{'type':'array','items':TABLE,'maxItems':30},'preview_token':HASH,'max_replacements':{'type':'integer','minimum':0,'maximum':100000,'default':1000}},['old','new','tables'])
declaration('cache_flush',{'exclusive_cache':{'const':True}},['exclusive_cache'])
declaration('set_maintenance_mode',{'enabled':BOOL},['enabled'])

import asyncio
import hashlib
import json
import re
import time
from jsonschema import Draft202012Validator
from taskweave.plugins.sdk import PluginError
from .commands import build_command,require,validate_input
from .transport import prompt_input


def completed(value,steps=(),*,noop=False,artifact=None):
    output={'completion':'noop' if noop else 'completed','result':value,'steps':list(steps)}
    if artifact is not None: output['artifact']=artifact
    return output


async def data(ctx,site,command):
    return (await site.execute(ctx,command,parse_json=True))['data']


async def installed(ctx,site,network=False):
    output=await site.execute(ctx,['core','is-installed']+(['--network'] if network else []),allow_exit=(1,))
    require(not output['stdout_truncated'] and not output['stderr_truncated'],'WORDPRESS_OUTPUT_TRUNCATED')
    if output['exit_code']==0: return True
    require(not output['stdout'].strip() and not output['stderr'].strip(),'WORDPRESS_INSTALLED_STATE_UNKNOWN')
    # Establish independent config/core/database prerequisites before accepting
    # native silent exit 1 as an uninstalled site. Never swallow DB auth errors.
    await site.execute(ctx,['core','version'])
    await site.execute(ctx,['config','path'])
    query=await site.execute(ctx,['db','query','SELECT 1','--skip-column-names'])
    require(query['stdout'].strip()=='1','WORDPRESS_INSTALLED_STATE_UNKNOWN')
    return False


async def entity(ctx,site,kind,identity,taxonomy=None):
    command=['term','get',taxonomy,str(identity),'--format=json'] if kind=='term' else [kind,'get',str(identity),'--format=json']
    if kind=='user': command+=['--fields=ID,user_login,user_email,display_name,roles']
    result=await data(ctx,site,command)
    require(isinstance(result,dict),'WORDPRESS_ENTITY_INVALID');return result


async def inventory(ctx,site,kind):
    rows=await data(ctx,site,[kind,'list','--format=json','--fields=name,status,update,version'])
    require(isinstance(rows,list) and all(isinstance(row,dict) for row in rows),'WORDPRESS_LIST_INVALID');return rows


def matching(rows,key,value,*,missing=False):
    matches=[row for row in rows if str(row.get(key))==str(value)]
    require(len(matches)==1 or missing and not matches,'WORDPRESS_TARGET_NOT_FOUND' if not matches else 'WORDPRESS_TARGET_AMBIGUOUS')
    return matches[0] if matches else None


async def menu_items(ctx,site,menu):
    menus=await data(ctx,site,build_command('list_menus',{}));matching(menus,'term_id',menu)
    rows=await data(ctx,site,['menu','item','list',str(menu),'--format=json','--fields=db_id,type,title,link,position,menu_item_parent,object_id,object,target,attr_title,description,classes'])
    require(isinstance(rows,list) and len(rows)<=1000,'WORDPRESS_MENU_TOO_LARGE');return rows


def check_fields(result,inputs,mapping):
    for key,field in mapping.items():
        if key in inputs: require(str(result.get(field))==str(inputs[key]),'WORDPRESS_POSTCHECK_FAILED')


def output_id(output):
    lines=output['stdout'].strip().splitlines()
    require(lines and re.fullmatch(r'[1-9][0-9]*',lines[-1].strip()),'WORDPRESS_ID_UNCONFIRMED')
    return int(lines[-1].strip())


async def perform(ctx,site,name,inputs):
    validate_input(name,inputs)
    if name=='backup':
        from .backup import backup_site
        return await backup_site(ctx,site,inputs)
    if name=='restore':
        from .backup import restore_site
        return await restore_site(ctx,site,inputs)
    if name=='check_environment':
        info=await data(ctx,site,build_command(name,inputs));require(isinstance(info,dict),'WORDPRESS_ENVIRONMENT_INVALID')
        require(info.get('wp_cli_version')=='2.12.0','WORDPRESS_CLI_VERSION_UNSUPPORTED')
        return completed({'cli':info,'site_path':str(site.site),'mode':site.config.get('mode','local'),'database_verified':False})
    if name=='is_installed': return completed({'installed':await installed(ctx,site,inputs.get('network',False))})
    if name=='core_install':
        if await installed(ctx,site): return completed({'installed':True},noop=True)
    if name=='config_create':
        path=str(site.site)+'/wp-config.php'
        try: await site.path(path)
        except PluginError as exc:
            require(exc.code=='WORDPRESS_PATH_NOT_FOUND','WORDPRESS_CONFIG_STATE_UNKNOWN')
        else: return completed({'config_exists':True},noop=True)
    if name=='core_download':
        # Download is allowed without installed core/config/database.
        if await site.files(1048576,100): require(False,'WORDPRESS_DOWNLOAD_DESTINATION_NOT_EMPTY')
    early={'core_download','core_install','config_create','config_get','config_set','check_environment','is_installed','db_export','db_import'}
    if name not in early: require(await installed(ctx,site),'WORDPRESS_NOT_INSTALLED')
    if name=='config_set' and 'value_ref' in inputs:
        info=await data(ctx,site,['cli','info','--format=json'])
        require(info.get('wp_cli_version')=='2.12.0','WORDPRESS_PROMPT_VERSION_UNSUPPORTED')
        require(not info.get('global_config_path') and not info.get('project_config_path'),'WORDPRESS_PROMPT_CONFIG_UNSUPPORTED')
    if name.startswith('list_'):
        rows=await data(ctx,site,build_command(name,inputs));require(isinstance(rows,list) and all(isinstance(row,dict) for row in rows),'WORDPRESS_LIST_INVALID')
        native=name in ('list_posts','list_media','list_terms','list_users')
        offset=0 if native else inputs.get('offset',0);limit=inputs.get('limit',20)
        selected=rows[offset:offset+limit]
        return completed({'items':selected,'truncated':len(rows)>offset+limit or native and len(selected)>=limit,'next_offset':inputs.get('offset',0)+len(selected)})
    if name in ('config_get','option_get'):
        output=await site.execute(ctx,build_command(name,inputs),parse_json=name=='option_get')
        return completed(output.get('data',output['stdout'].strip()))
    if name=='verify_checksums':
        output=await site.execute(ctx,build_command(name,inputs));return completed({'verified':True,'report':output['stdout']})
    # Extension prechecks also establish local/network active scope explicitly.
    extension=re.fullmatch(r'(install|activate|deactivate|update|delete)_(theme|plugin)',name)
    if extension:
        verb,kind=extension.groups();rows=await inventory(ctx,site,kind)
        target=matching(rows,'name',inputs['slug'],missing=verb=='install')
        if target is not None:
            state=target.get('status')
            if verb=='install':
                require(not inputs.get('version') or target['version']==inputs['version'],'WORDPRESS_EXTENSION_VERSION_CONFLICT')
                return completed(target,noop=True)
            if verb=='activate' and state==('active-network' if inputs.get('network') else 'active') or verb=='deactivate' and state=='inactive': return completed(target,noop=True)
            if verb=='deactivate' and state=='active-network': require(inputs.get('network') is True,'WORDPRESS_NETWORK_SCOPE_REQUIRED')
            if verb=='delete':
                require(state=='inactive','WORDPRESS_ACTIVE_EXTENSION_DELETE_DENIED')
                if kind=='theme':
                    template=await data(ctx,site,['option','get','template','--format=json'])
                    require(template!=inputs['slug'],'WORDPRESS_ACTIVE_THEME_PARENT_DELETE_DENIED')
            if verb=='update' and (inputs.get('version')==target['version'] or not inputs.get('version') and target.get('update')=='none'): return completed(target,noop=True)
        if verb=='install' and inputs.get('source') and not re.match(r'^https?://',inputs['source']):
            inputs={**inputs,'source':await site.path(inputs['source'])}
        output=await site.execute(ctx,build_command(name,inputs),write=True)
        after=matching(await inventory(ctx,site,kind),'name',inputs['slug'],missing=verb=='delete')
        require(after is None if verb=='delete' else after is not None,'WORDPRESS_POSTCHECK_FAILED')
        if verb=='activate': require(after['status']==('active-network' if inputs.get('network') else 'active'),'WORDPRESS_POSTCHECK_FAILED')
        if verb=='deactivate': require(after['status']=='inactive','WORDPRESS_POSTCHECK_FAILED')
        if inputs.get('version') and verb in ('install','update'): require(after['version']==inputs['version'],'WORDPRESS_POSTCHECK_FAILED')
        return completed(after or {'deleted':inputs['slug']},[{'stage':name,'completion':'completed'}])
    if name in ('update_post','delete_post','update_media','delete_media'):
        before=await entity(ctx,site,'post',inputs['id'])
        require(before.get('post_type')==('attachment' if name.endswith('media') else inputs['post_type']),'WORDPRESS_TARGET_TYPE_MISMATCH')
    if name=='import_media' and not re.match(r'^https?://',inputs['source']):
        inputs={**inputs,'source':await site.path(inputs['source'])}
    if name in ('create_post','update_post','import_media') and inputs.get('parent'):
        await entity(ctx,site,'post',inputs['parent'])
    if name in ('create_term','update_term','delete_term'):
        if name!='create_term': await entity(ctx,site,'term',inputs['id'],inputs['taxonomy'])
        if inputs.get('parent'): await entity(ctx,site,'term',inputs['parent'],inputs['taxonomy'])
        if name=='create_term' and inputs.get('slug'):
            found=await data(ctx,site,['term','list',inputs['taxonomy'],'--slug='+inputs['slug'],'--number=2','--format=json'])
            if found: return completed(matching(found,'slug',inputs['slug']),noop=True)
    if name in ('create_menu','delete_menu'):
        rows=await data(ctx,site,build_command('list_menus',{}))
        if name=='create_menu':
            found=[row for row in rows if row['name']==inputs['name']]
            if found: return completed(matching(found,'name',inputs['name']),noop=True)
        else: matching(rows,'term_id',inputs['menu'])
    if name in ('add_menu_item','update_menu_item','delete_menu_item'):
        rows=await menu_items(ctx,site,inputs['menu'])
        if name!='add_menu_item': matching(rows,'db_id',inputs['id'])
        if inputs.get('parent_id'):
            matching(rows,'db_id',inputs['parent_id']);require(inputs.get('parent_id')!=inputs.get('id'),'WORDPRESS_MENU_PARENT_INVALID')
        if name=='add_menu_item' and inputs['kind']=='post': await entity(ctx,site,'post',inputs['post_id'])
        if name=='add_menu_item' and inputs['kind']=='term': await entity(ctx,site,'term',inputs['term_id'],inputs['taxonomy'])
    if name in ('create_user','set_user_role','set_user_password','delete_user'):
        if name=='create_user':
            for key,field in [('login','user_login'),('email','user_email')]:
                require('*' not in inputs[key],'WORDPRESS_USER_IDENTITY_INVALID')
                rows=await data(ctx,site,['user','list','--search='+inputs[key],'--number=2','--format=json','--fields=ID,user_login,user_email,roles'])
                require(not any(row.get(field)==inputs[key] for row in rows),'WORDPRESS_USER_ALREADY_EXISTS')
        else:
            user=await entity(ctx,site,'user',inputs['id'])
            if name=='delete_user' or name=='set_user_role' and inputs['user_role']!='administrator':
                roles=user.get('roles',[])
                if 'administrator' in roles:
                    admins=await data(ctx,site,['user','list','--role=administrator','--number=2','--format=json','--fields=ID'])
                    require(len(admins)>1,'WORDPRESS_FINAL_ADMINISTRATOR_PROTECTED')
            if name=='delete_user' and inputs.get('reassign'): await entity(ctx,site,'user',inputs['reassign'])
    if name in ('db_export','db_import'):
        from .backup import verified_tables,validate_sql,digest,stage_bytes,import_sql,normalize_export,export_sql
        await verified_tables(ctx,site,inputs['tables'])
        path=await site.path(inputs['path'],must_exist=name=='db_import',site_only=name=='db_export')
        if name=='db_import':
            content=await site.read(path,inputs.get('max_bytes',16777216));require(digest(content)==inputs['checksum'],'WORDPRESS_BACKUP_INTEGRITY_FAILED');validate_sql(content,inputs['tables'])
        else:
            try: await site.path(path)
            except PluginError as exc: require(exc.code=='WORDPRESS_PATH_NOT_FOUND','WORDPRESS_EXPORT_TARGET_INVALID')
            else: require(False,'WORDPRESS_EXPORT_TARGET_EXISTS')
        if name=='db_import': await import_sql(ctx,site,content,inputs['tables'])
        else:
            content=await export_sql(ctx,site,inputs['tables'],inputs.get('max_bytes',16777216))
            entry=site.evidence.dispatch(ctx,name,site.role,'database_export_file') if site.evidence else None
            await site.write(path,content)
            if entry: entry['completion']='completed'
        if name=='db_export':
            return completed({'tables':inputs['tables'],'sha256':digest(content)},artifact=await stage_bytes(ctx,'wordpress-database.sql',content))
        await verified_tables(ctx,site,inputs['tables']);return completed({'tables':inputs['tables'],'imported':True})
    if name=='search_replace': return await search_replace(ctx,site,inputs)
    if name=='set_maintenance_mode':
        probe=await site.execute(ctx,['maintenance-mode','is-active'],allow_exit=(1,))
        require(not probe['stderr'] and not probe['stdout_truncated'],'WORDPRESS_MAINTENANCE_STATE_UNKNOWN')
        if (probe['exit_code']==0)==inputs['enabled']: return completed({'enabled':inputs['enabled']},noop=True)
    # A single prompt field per command; no secret values are placed in argv.
    refs={}
    for key,field in [('admin_password_ref','admin_password'),('db_password_ref','dbpass'),('password_ref','user_pass'),('value_ref','config_value')]:
        if key in inputs: refs[field]=inputs[key]
    stdin,secrets=prompt_input(ctx,refs)
    if name in ('create_post','update_post') and 'content' in inputs: stdin=inputs['content'].encode()
    if name=='option_set': stdin=json.dumps(inputs['value'],ensure_ascii=False,allow_nan=False).encode()
    steps=[]
    if name=='update_media' and not any(key in inputs for key in ('title','caption','description')): output=None
    else:
        command=build_command(name,inputs)
        if name=='config_set': command+=['--config-file='+str(site.site)+'/wp-config.php']
        output=await site.execute(ctx,command,stdin=stdin,secrets=secrets,write=True)
        steps.append({'stage':name,'completion':'completed'})
    if name=='update_media' and 'alt' in inputs:
        await site.execute(ctx,['post','meta','update',str(inputs['id']),'_wp_attachment_image_alt','--format=plaintext'],stdin=inputs['alt'].encode(),write=True)
        steps.append({'stage':'attachment_alt','completion':'completed'})
    if name in ('create_post','update_post','import_media','update_media'):
        identity=output_id(output) if name in ('create_post','import_media') else inputs['id']
        after=await entity(ctx,site,'post',identity)
        mapping={'title':'post_title','status':'post_status','slug':'post_name','content':'post_content'} if name.endswith('post') else {'title':'post_title','caption':'post_excerpt','description':'post_content'}
        check_fields(after,inputs,mapping)
        if name=='update_media' and 'alt' in inputs:
            alt=await site.execute(ctx,['post','meta','get',str(identity),'_wp_attachment_image_alt']);require(alt['stdout'].rstrip('\n')==inputs['alt'],'WORDPRESS_POSTCHECK_FAILED')
        return completed({'id':identity,'post':after},steps)
    if name in ('delete_post','delete_media'):
        permanent=name=='delete_media' or inputs.get('force',False)
        after=await data(ctx,site,['post','list','--post__in='+str(inputs['id']),'--post_type='+('attachment' if name=='delete_media' else inputs['post_type']),'--post_status='+('any' if permanent else 'trash'),'--posts_per_page=2','--format=json','--fields=ID,post_status'])
        require(not after if permanent else any(str(row['ID'])==str(inputs['id']) and row['post_status']=='trash' for row in after),'WORDPRESS_POSTCHECK_FAILED')
        return completed({'id':inputs['id'],'state':'deleted' if permanent else 'trashed'},steps)
    if name in ('create_term','update_term'):
        identity=output_id(output) if name=='create_term' else inputs['id'];after=await entity(ctx,site,'term',identity,inputs['taxonomy']);check_fields(after,inputs,{key:key for key in TERM_PATCH});return completed(after,steps)
    if name=='delete_term':
        rows=await data(ctx,site,['term','list',inputs['taxonomy'],'--include='+str(inputs['id']),'--number=2','--format=json']);require(not rows,'WORDPRESS_POSTCHECK_FAILED');return completed({'deleted':inputs['id']},steps)
    if name in ('create_menu','delete_menu'):
        identity=output_id(output) if name=='create_menu' else inputs['menu'];after=matching(await data(ctx,site,build_command('list_menus',{})),'term_id',identity,missing=name=='delete_menu');require(after is None if name=='delete_menu' else after is not None,'WORDPRESS_POSTCHECK_FAILED');return completed(after or {'deleted':identity},steps)
    if name in ('add_menu_item','update_menu_item','delete_menu_item'):
        identity=output_id(output) if name=='add_menu_item' else inputs['id'];after=matching(await menu_items(ctx,site,inputs['menu']),'db_id',identity,missing=name=='delete_menu_item');require(after is None if name=='delete_menu_item' else after is not None,'WORDPRESS_POSTCHECK_FAILED')
        if after: check_fields(after,inputs,{'title':'title','link':'link','parent_id':'menu_item_parent'})
        return completed(after or {'deleted':identity},steps)
    if name in ('create_user','set_user_role','set_user_password'):
        identity=output_id(output) if name=='create_user' else inputs['id'];after=await entity(ctx,site,'user',identity)
        if 'user_role' in inputs: require(inputs['user_role'] in after.get('roles',[]),'WORDPRESS_POSTCHECK_FAILED')
        return completed({'id':identity,'user':after,'password_updated':name in ('create_user','set_user_password')},steps)
    if name=='delete_user':
        after=await data(ctx,site,['user','list','--include='+str(inputs['id']),'--number=2','--format=json','--fields=ID']);require(not after,'WORDPRESS_POSTCHECK_FAILED');return completed({'deleted':inputs['id']},steps)
    if name=='option_set':
        after=await data(ctx,site,['option','get',inputs['key'],'--format=json']);require(after==inputs['value'],'WORDPRESS_POSTCHECK_FAILED');return completed(after,steps)
    if name=='config_set':
        if secrets:
            content=await site.read(str(site.site)+'/wp-config.php',16777216)
            # WP config transformer writes quoted PHP literals. Parse the
            # configured field only; comparison booleans leave the worker.
            match=re.search(rb"define\s*\(\s*['\"]"+re.escape(inputs['name'].encode())+rb"['\"]\s*,\s*'((?:\\.|[^'\\])*)'\s*\)",content) if inputs.get('type','constant')=='constant' else re.search(rb'\$'+re.escape(inputs['name'].encode())+rb"\s*=\s*'((?:\\.|[^'\\])*)'\s*;",content)
            actual=match.group(1).replace(b"\\'",b"'").replace(b'\\\\',b'\\') if match else None
            require(actual==secrets[0].encode(),'WORDPRESS_SECRET_POSTCHECK_FAILED');return completed({'name':inputs['name'],'secret_matches':True},steps)
        after=await site.execute(ctx,build_command('config_get',{'name':inputs['name'],'type':inputs.get('type','constant')}));require(after['stdout'].strip()==inputs['value'],'WORDPRESS_POSTCHECK_FAILED');return completed({'name':inputs['name'],'verified':True},steps)
    if name=='set_permalink_structure':
        after=await data(ctx,site,['option','get','permalink_structure','--format=json']);require(after==inputs['structure'],'WORDPRESS_POSTCHECK_FAILED');return completed({'structure':after},steps)
    if name=='set_maintenance_mode':
        after=await site.execute(ctx,['maintenance-mode','is-active'],allow_exit=(1,));require((after['exit_code']==0)==inputs['enabled'] and not after['stderr'],'WORDPRESS_POSTCHECK_FAILED');return completed({'enabled':inputs['enabled'],'expires_after_seconds':600},steps)
    if name in ('core_install','core_update','core_download'):
        version=(await site.execute(ctx,['core','version']))['stdout'].strip()
        require(name=='core_install' or version==inputs['version'],'WORDPRESS_POSTCHECK_FAILED')
        if name=='core_install': require(await installed(ctx,site),'WORDPRESS_POSTCHECK_FAILED')
        return completed({'version':version},steps)
    if name=='config_create':
        await site.path(str(site.site)+'/wp-config.php');return completed({'config_created':True},steps)
    return completed({'acknowledged':True,'stdout':output['stdout'],'stderr':output['stderr']},steps)


async def search_replace(ctx,site,inputs):
    from .backup import verified_tables,site_identity
    await verified_tables(ctx,site,inputs['tables'])
    preview={**inputs,'dry_run':True};command=build_command('search_replace',preview)
    output=await site.execute(ctx,command)
    require(not output['stdout_truncated'] and re.fullmatch(r'[0-9]+\s*',output['stdout']),'WORDPRESS_REPLACEMENT_COUNT_INVALID')
    count=int(output['stdout']);maximum=inputs.get('max_replacements',1000)
    require(count<=maximum,'WORDPRESS_REPLACEMENT_BUDGET_EXCEEDED')
    identity={'site':await site_identity(ctx,site),'old':inputs['old'],'new':inputs['new'],'tables':inputs['tables'],'skip_columns':inputs.get('skip_columns',['guid']),'count':count,'maximum':maximum}
    token=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    if inputs.get('dry_run',True):
        require(len(site.previews)<64 or token in site.previews,'WORDPRESS_PREVIEW_CAPACITY')
        site.previews[token]=(time.monotonic(),identity)
        return completed({'dry_run':True,'count':count,'preview_token':token,'warnings':output['stderr'],'concurrency':'external writes may change after preview'})
    previous=site.previews.get(inputs.get('preview_token'))
    require(previous and time.monotonic()-previous[0]<=300 and previous[1]==identity and inputs['preview_token']==token,'WORDPRESS_PREVIEW_STALE_OR_MISSING')
    site.previews.pop(token)
    output=await site.execute(ctx,build_command('search_replace',inputs),write=True)
    require(not output['stdout_truncated'] and re.fullmatch(r'[0-9]+\s*',output['stdout']),'WORDPRESS_REPLACEMENT_COUNT_INVALID')
    require(int(output['stdout'])==count,'WORDPRESS_REPLACEMENT_POSTCHECK_FAILED')
    return completed({'dry_run':False,'count':int(output['stdout']),'preview_count':count,'warnings':output['stderr'],'atomic':False},[{'stage':'search_replace','completion':'completed'}])


class WordPressAction:
    def __init__(self,name,evidence):
        self.name=name;self.evidence=evidence
        ins,outs,effect=DEFINITIONS[name]
        self.spec=CapabilitySpec('wordpress.'+name,'WordPress '+name.replace('_',' '),ins,outs,effect,timeout_ms=1810000,retry_safe=effect=='READ',resource_ids=('wordpress.site',))
    async def preflight(self,ctx,inputs): validate_input(self.name,inputs);return []
    async def verify(self,ctx,inputs,output): return []
    async def execute(self,ctx,inputs):
        await self.preflight(ctx,inputs)
        from .transport import configuration
        config=configuration(ctx)
        timeout=inputs.get('timeout_seconds',config.get('timeout_seconds',60))
        require(type(timeout) is int and 1<=timeout<=1800,'WORDPRESS_TIMEOUT_INVALID')
        async def operation():
            site=await ctx.resources.acquire('wordpress.site',inputs.get('role','default'))
            require(not site.busy,'WORDPRESS_SITE_BUSY');site.busy=True
            try:
                effective=dict(inputs)
                if self.name in ('db_export','db_import','backup','restore'):
                    effective.setdefault('max_bytes',site.config.get('max_transfer_bytes',16777216))
                site.start(ctx,self.name,inputs.get('role','default'),effective)
                result=await perform(ctx,site,self.name,effective)
                require(Draft202012Validator(self.spec.output_schema).is_valid(result),'WORDPRESS_RESULT_INVALID')
                require(len(json.dumps(result,ensure_ascii=False).encode())<=site.max_output,'WORDPRESS_OUTPUT_TOO_LARGE')
                return result
            finally: site.busy=False
        try: return await asyncio.wait_for(operation(),timeout=timeout)
        except BaseException as exc:
            self.evidence.capture(ctx,exc);raise
