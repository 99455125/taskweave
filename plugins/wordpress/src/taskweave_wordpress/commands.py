"""Typed WP-CLI 2.12 argv; neither shell text nor arbitrary CLI flags."""
import re
from jsonschema import Draft202012Validator
from taskweave.plugins.sdk import PluginError


def require(condition, code='WORDPRESS_INPUT_INVALID'):
    if not condition:
        raise PluginError(code)


def secret_field(name):
    return bool(re.search(r'password|passwd|secret|token|salt|(?:^|_)key(?:$|_)', name, re.I))


def validate_input(name, inputs):
    from .actions import DEFINITIONS
    require(name in DEFINITIONS and Draft202012Validator(DEFINITIONS[name][0]).is_valid(inputs))
    if name in ('config_get', 'option_get', 'option_set'):
        require(not secret_field(inputs.get('name', inputs.get('key', ''))), 'WORDPRESS_SECRET_READ_DENIED')
    if name == 'config_set':
        require(('value' in inputs) != ('value_ref' in inputs))
        require(not secret_field(inputs['name']) or 'value_ref' in inputs, 'WORDPRESS_SECRET_REFERENCE_REQUIRED')
    if name == 'add_menu_item':
        keys={'post': ('post_id',), 'term': ('taxonomy','term_id'), 'custom': ('title','link')}[inputs['kind']]
        require(all(key in inputs for key in keys))
    if name == 'delete_user':
        require(('reassign' in inputs) != inputs.get('delete_content', False))
        require(inputs.get('reassign') != inputs['id'])
    if name in ('update_post','update_term','update_menu_item','update_media'):
        patches=set(inputs)-{'id','taxonomy','menu','post_type','role','timeout_seconds','max_output_bytes'}
        require(bool(patches))


def build_command(action_id: str, inputs: dict) -> list[str]:
    name=action_id.removeprefix('wordpress.')
    validate_input(name,inputs)
    def flags(mapping):
        result=[]
        for key,cli in mapping.items():
            if key in inputs:
                value=inputs[key]
                if isinstance(value,bool) and cli=='hide_empty': result.append('--'+cli+'='+str(int(value)))
                elif value is not False: result.append('--'+cli if value is True else '--'+cli+'='+str(value))
        return result
    if inputs.get('source'): require(not inputs['source'].startswith('-'),'WORDPRESS_POSITIONAL_FLAG_REJECTED')
    positional={'create_menu':['name'],'create_term':['name'],'config_set':['value'],'search_replace':['old','new'],'set_permalink_structure':['structure'],'import_media':['source'],'add_menu_item':['title','link']}
    for key in positional.get(name,[]):
        if key in inputs: require(not str(inputs[key]).startswith('-'),'WORDPRESS_POSITIONAL_FLAG_REJECTED')
    ident=str(inputs.get('id',''))
    if name=='check_environment': return ['cli','info','--format=json']
    if name=='is_installed': return ['core','is-installed']+flags({'network':'network'})
    if name=='core_download': return ['core','download']+flags({'version':'version','locale':'locale','skip_content':'skip-content'})
    if name=='core_install': return ['core','install']+flags({'url':'url','title':'title','admin_user':'admin_user','admin_email':'admin_email'})+['--prompt=admin_password','--quiet']
    if name=='core_update': return ['core','update']+flags({'version':'version'})
    if name=='verify_checksums': return ['core','verify-checksums']+flags({'version':'version','locale':'locale'})
    if name=='config_create': return ['config','create']+flags({'dbname':'dbname','dbuser':'dbuser','dbhost':'dbhost','dbprefix':'dbprefix'})+['--prompt=dbpass','--quiet']
    if name=='config_get': return ['config','get',inputs['name'],'--type='+inputs.get('type','constant')]
    if name=='config_set':
        return ['config','set',inputs['name']]+([str(inputs['value'])] if 'value' in inputs else [])+['--type='+inputs.get('type','constant')]+(['--prompt','--quiet'] if 'value_ref' in inputs else [])
    if name=='option_get': return ['option','get',inputs['key'],'--format=json']
    if name=='option_set': return ['option','update',inputs['key'],'--format=json']+flags({'autoload':'autoload'})
    if name=='set_permalink_structure': return ['rewrite','structure',inputs['structure']]+flags({'category_base':'category-base','tag_base':'tag-base','hard':'hard'})
    if name in ('list_themes','list_plugins'): return ['theme' if name=='list_themes' else 'plugin','list','--format=json','--fields=name,status,update,version']+flags({'status':'status'})
    for entity in ('theme','plugin'):
        for verb in ('install','activate','deactivate','update','delete'):
            if name==verb+'_'+entity:
                return [entity,verb,inputs.get('source',inputs['slug'])]+(['--format=json'] if verb=='update' else [])+flags({'version':'version','network':'network'})
    if name in ('list_posts','list_media'):
        media=name=='list_media'
        return ['post','list','--post_type='+('attachment' if media else inputs.get('post_type','post'))]+(['--post_status=inherit'] if media else [])+['--posts_per_page='+str(inputs.get('limit',20)),'--offset='+str(inputs.get('offset',0)),'--orderby=ID','--order=ASC','--format=json','--fields='+('ID,post_title,post_excerpt,post_content,post_mime_type,guid,post_parent' if media else 'ID,post_title,post_name,post_status,post_type')]+flags({'status':'post_status','author':'author','search':'s'})
    post_flags={'title':'post_title','status':'post_status','slug':'post_name','author':'post_author','date':'post_date','excerpt':'post_excerpt','parent':'post_parent'}
    if name=='create_post': return ['post','create','-','--post_type='+inputs['post_type']]+flags(post_flags)+['--porcelain']
    if name=='update_post': return ['post','update',ident]+(['-'] if 'content' in inputs else [])+flags(post_flags)
    if name=='delete_post': return ['post','delete',ident]+flags({'force':'force'})
    if name=='list_terms': return ['term','list',inputs['taxonomy'],'--number='+str(inputs.get('limit',20)),'--offset='+str(inputs.get('offset',0)),'--orderby=id','--order=ASC','--format=json','--fields=term_id,name,slug,parent,count']+flags({'hide_empty':'hide_empty'})
    if name=='create_term': return ['term','create',inputs['taxonomy'],inputs['name'],'--porcelain']+flags({'slug':'slug','description':'description','parent':'parent'})
    if name=='update_term': return ['term','update',inputs['taxonomy'],ident]+flags({'name':'name','slug':'slug','description':'description','parent':'parent'})
    if name=='delete_term': return ['term','delete',inputs['taxonomy'],ident]
    if name=='list_menus': return ['menu','list','--format=json','--fields=term_id,name,slug,locations,count']
    if name=='create_menu': return ['menu','create',inputs['name'],'--porcelain']
    if name=='delete_menu': return ['menu','delete',str(inputs['menu'])]
    menu_flags={'title':'title','link':'link','description':'description','attr_title':'attr-title','target':'target','classes':'classes','position':'position','parent_id':'parent-id'}
    if name=='add_menu_item':
        kind=inputs['kind']; args=[str(inputs['post_id'])] if kind=='post' else [inputs['taxonomy'],str(inputs['term_id'])] if kind=='term' else [inputs['title'],inputs['link']]
        return ['menu','item','add-'+kind,str(inputs['menu']),*args,'--porcelain']+flags({k:v for k,v in menu_flags.items() if kind!='custom' or k not in ('title','link')})
    if name=='update_menu_item': return ['menu','item','update',ident]+flags(menu_flags)
    if name=='delete_menu_item': return ['menu','item','delete',ident]
    if name=='import_media': return ['media','import',inputs['source'],'--porcelain']+flags({'title':'title','caption':'caption','description':'desc','alt':'alt','parent':'post_id','featured_image':'featured_image'})
    if name=='update_media': return ['post','update',ident]+flags({'title':'post_title','caption':'post_excerpt','description':'post_content'})
    if name=='delete_media': return ['post','delete',ident,'--force']
    if name=='list_users': return ['user','list','--number='+str(inputs.get('limit',20)),'--offset='+str(inputs.get('offset',0)),'--orderby=ID','--order=ASC','--format=json','--fields=ID,user_login,user_email,display_name,roles']+flags({'user_role':'role','search':'search'})
    if name=='create_user': return ['user','create',inputs['login'],inputs['email'],'--role='+inputs['user_role'],'--prompt=user_pass','--porcelain','--quiet']
    if name=='set_user_role': return ['user','set-role',ident,inputs['user_role']]
    if name=='set_user_password': return ['user','update',ident,'--prompt=user_pass','--quiet']+flags({'skip_email':'skip-email'})
    if name=='delete_user': return ['user','delete',ident,'--yes']+flags({'reassign':'reassign','network':'network'})
    if name=='db_export': return ['db','export',inputs['path'],'--porcelain','--tables='+','.join(inputs['tables']),'--single-transaction']
    if name=='db_import': return ['db','import',inputs['path']]
    if name=='search_replace': return ['search-replace',inputs['old'],inputs['new'],*inputs['tables'],'--format=count','--skip-columns='+','.join(inputs.get('skip_columns',['guid']))]+(['--dry-run'] if inputs.get('dry_run',True) else [])
    if name=='cache_flush': return ['cache','flush']
    if name=='set_maintenance_mode': return ['maintenance-mode','activate' if inputs['enabled'] else 'deactivate']
    require(False,'WORDPRESS_ORCHESTRATED_ACTION')
