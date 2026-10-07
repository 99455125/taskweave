"""Passive bounded project metadata; never execute project JavaScript."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import json5
from taskweave.plugins.sdk import PluginError
from taskweave_process.artifacts import read_artifact

LIMIT=16*1024*1024

def require(condition,code='UNIAPP_CONFIG_INVALID',message=None):
    if not condition: raise PluginError(code,message)

def configuration(ctx):
    result={**ctx.environment.get('uniapp_config',{}),**getattr(ctx,'task_parameters',{}).get('uniapp_config',{})}
    require(isinstance(result.get('project_root'),str),'UNIAPP_PREPARATION_REQUIRED','Configure uniapp_config.project_root')
    try: root=Path(result['project_root']).expanduser().resolve(strict=True)
    except (OSError,RuntimeError): raise PluginError('UNIAPP_PREPARATION_REQUIRED','Project root is unavailable')
    require(root.is_dir());result['project_root']=str(root)
    require(result.get('kind') in ('cli','hbuilderx'))
    for key in ('env','env_secret_refs','build_scripts','test_scripts','outputs'):
        require(isinstance(result.get(key,{}),dict))
    return result

def path_inside(root,path,*,exists=True):
    root=Path(root).resolve(strict=True)
    try:
        candidate=(root/path).resolve(strict=exists);candidate.relative_to(root)
    except (OSError,ValueError,RuntimeError,TypeError):raise PluginError('UNIAPP_PATH_INVALID')
    return candidate

def read_bytes(root,path,budget=LIMIT):
    try: return read_artifact(str(root),str(path),budget)[1]
    except OSError as error:raise PluginError('UNIAPP_FILE_READ_FAILED') from error

def read_json(root,path,budget=1024*1024):
    try: value=json5.loads(read_bytes(root,path,budget).decode('utf-8'),allow_duplicate_keys=False)
    except (ValueError,UnicodeError):raise PluginError('UNIAPP_JSON_INVALID')
    require(isinstance(value,dict),'UNIAPP_JSON_INVALID');return value

def pages_list(document):
    require(isinstance(document.get('pages'),list),'UNIAPP_PAGES_INVALID')
    output=[]
    for row in document['pages']:
        value=row.get('path') if isinstance(row,dict) else row
        require(isinstance(value,str) and value and not value.startswith('/') and '..' not in value.split('/'),'UNIAPP_PAGES_INVALID');output.append(value)
    subs=document.get('subPackages',document.get('subpackages',[]));require(isinstance(subs,list),'UNIAPP_PAGES_INVALID')
    for item in subs:
        require(isinstance(item,dict) and isinstance(item.get('root'),str) and isinstance(item.get('pages'),list),'UNIAPP_PAGES_INVALID')
        for row in item['pages']:
            value=row.get('path') if isinstance(row,dict) else row;require(isinstance(value,str),'UNIAPP_PAGES_INVALID')
            joined=item['root'].rstrip('/')+'/'+value;require(not joined.startswith('/') and '..' not in joined.split('/'),'UNIAPP_PAGES_INVALID');output.append(joined)
    require(0<len(output)<=500 and len(set(output))==len(output),'UNIAPP_PAGES_INVALID');return output

def test_schema(config):
    root=config.get('test_plugin_root')
    require(isinstance(root,str),'UNIAPP_PREPARATION_REQUIRED','Configure installed hbuilderx-for-uniapp-test root')
    require((Path(root)/'package.json').is_file(),'UNIAPP_PREPARATION_REQUIRED','Install official HBuilderX test plugin');package=read_json(root,'package.json');require(package.get('name')=='hbuilderx-for-uniapp-test','UNIAPP_PREPARATION_REQUIRED')
    commands=package.get('contributes',{}).get('clicommands')
    require(isinstance(commands,(dict,list)),'UNIAPP_PREPARATION_REQUIRED','Installed test plugin CLI schema unavailable')
    return package

def inspect_project(ctx,config):
    root=Path(config['project_root']);layout='src' if (root/'src/manifest.json').is_file() else '.';base=root/layout
    manifest=read_json(root,str((base/'manifest.json').relative_to(root)));pages=pages_list(read_json(root,str((base/'pages.json').relative_to(root))))
    package=read_json(root,'package.json') if (root/'package.json').is_file() else {}
    scripts=package.get('scripts',{});require(isinstance(scripts,dict));requirements=[]
    require(isinstance(package.get('engines',{}),dict));require(isinstance(manifest.get('mp-weixin',{}),dict),'UNIAPP_JSON_INVALID')
    dependencies={**package.get('dependencies',{}),**package.get('devDependencies',{})};require(len(dependencies)<=128)
    for name in dependencies:
        require(re.fullmatch(r'(?:@[A-Za-z0-9_.-]+/)?[A-Za-z0-9_.-]+',name) is not None)
        if not (root/'node_modules'/name/'package.json').is_file():requirements.append('dependency missing: '+name)
    if config['kind']=='cli':
        for key in ('node_path','package_manager'):
            if not isinstance(config.get(key),str) or not shutil.which(config[key]):requirements.append(key+' missing')
        if type(config.get('node_major')) is not int:requirements.append('explicit compatible node_major required')
        if not (root/'node_modules').is_dir():requirements.append('project dependencies missing')
    else:
        if not isinstance(config.get('hbuilderx_path'),str) or not shutil.which(config['hbuilderx_path']):requirements.append('native HBuilderX CLI missing')
    versions={}
    for name in ('vue','jest','@dcloudio/vue-cli-plugin-uni','@dcloudio/uni-automator'):
        source='node_modules/'+name+'/package.json'
        if (root/source).is_file():
            installed=read_json(root,source);require(installed.get('name')==name and isinstance(installed.get('version'),str),'UNIAPP_JSON_INVALID');versions[name]=installed['version']
    if config['kind']=='hbuilderx' and isinstance(config.get('hbuilderx_path'),str):
        import plistlib
        bundle=next((p for p in Path(config['hbuilderx_path']).parents if p.suffix=='.app'),None)
        if bundle and (bundle/'Contents/Info.plist').is_file():
            try:info=plistlib.loads(read_bytes(bundle,'Contents/Info.plist',1024*1024));versions['hbuilderx']=str(info.get('CFBundleShortVersionString',info.get('CFBundleVersion','unknown')))
            except (ValueError,plistlib.InvalidFileException):require(False,'UNIAPP_JSON_INVALID')
    if config.get('test_plugin_root') and (Path(config['test_plugin_root'])/'package.json').is_file():versions['hbuilderx-for-uniapp-test']=str(test_schema(config).get('version','unknown'))
    from .lease import native_write_state
    return {'native_write_state':native_write_state(root),'project_root':str(root),'kind':config['kind'],'layout':layout,'vue_version':str(manifest.get('vueVersion','unknown')),
       'appid':manifest.get('mp-weixin',{}).get('appid',''),'uniapp_appid':manifest.get('appid',''),'pages':pages,'scripts':scripts,
       'outputs':config.get('outputs',{}),'build_scripts':config.get('build_scripts',{}),'test_scripts':config.get('test_scripts',{}),'engines':package.get('engines',{}),'node_major_configured':config.get('node_major'),'preparation_required':requirements,
       'tool_versions':versions,'test_plugin_installed':bool(config.get('test_plugin_root') and (Path(config['test_plugin_root'])/'package.json').is_file())}

def walk_files(root,directory,ctx=None):
    stack=[path_inside(root,str(directory))];count=0
    while stack:
        directory=stack.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                count+=1;require(count<=4000,'UNIAPP_ARTIFACT_LIMIT')
                if ctx:require(not ctx.cancelled(),'CANCELLED')
                source=path_inside(root,entry.path)
                if entry.is_dir(follow_symlinks=False):stack.append(source)
                else:yield Path(entry.path)

def snapshot(root,path,budget=LIMIT,ctx=None):
    directory=path_inside(root,path,exists=False)
    if not directory.exists():return {}
    require(directory.is_dir(),'UNIAPP_PATH_INVALID');result={};total=0
    for source in walk_files(root,directory,ctx):
        require(len(result)<2000,'UNIAPP_ARTIFACT_LIMIT');data=read_bytes(root,str(source),budget-total);total+=len(data)
        require(total<=budget,'UNIAPP_ARTIFACT_LIMIT');stat=source.stat();name=str(source.relative_to(directory))
        result[name]={'sha256':hashlib.sha256(data).hexdigest(),'size':len(data),'mtime_ns':stat.st_mtime_ns,'ctime_ns':stat.st_ctime_ns,'inode':stat.st_ino}
    return result

CONDITION_PLATFORMS={'H5','MP-WEIXIN','APP-PLUS','APP','APP-NVUE','MP-ALIPAY','MP-BAIDU','MP-QQ','MP-TOUTIAO','MP-LARK','MP-JD','MP-XHS','MP-KUAISHOU','MP-HARMONY','MP-360','QUICKAPP-WEBVIEW','QUICKAPP-NATIVE'}

def selected_page_plan(config,platform):
    root=Path(config['project_root']);source='src/pages.json' if (root/'src/manifest.json').is_file() else 'pages.json';raw=read_bytes(root,source,1024*1024)
    try:text=raw.decode('utf-8')
    except UnicodeError:require(False,'UNIAPP_JSON_INVALID')
    stack=[];selected=[];symbol='MP-WEIXIN' if platform=='mp-weixin' else 'H5'
    for line in text.splitlines():
        directive=re.fullmatch(r'\s*//\s*#(ifdef|ifndef|endif)\s*(.*?)\s*',line)
        if directive:
            name,expression=directive.groups()
            if name=='endif':require(not expression and bool(stack),'UNIAPP_PREPARATION_REQUIRED','Unbalanced page conditions');stack.pop()
            else:
                tokens=[part.strip() for part in expression.split('||')];require(bool(tokens) and all(token in CONDITION_PLATFORMS for token in tokens),'UNIAPP_PREPARATION_REQUIRED','Unsupported pages condition symbol/expression')
                value=symbol in tokens;stack.append(value if name=='ifdef' else not value);require(len(stack)<=32,'UNIAPP_ARTIFACT_LIMIT')
            continue
        require(not re.search(r'(?:^\s*//|/\*)\s*#(?:if|else|endif)',line),'UNIAPP_PREPARATION_REQUIRED','Only line-comment ifdef/ifndef/endif platform OR conditions are supported')
        if all(stack):selected.append(line)
    require(not stack,'UNIAPP_PREPARATION_REQUIRED','Unbalanced page conditions')
    try:document=json5.loads('\n'.join(selected),allow_duplicate_keys=False)
    except ValueError:require(False,'UNIAPP_JSON_INVALID')
    require(isinstance(document,dict),'UNIAPP_JSON_INVALID');pages=pages_list(document)
    main=[row['path'] if isinstance(row,dict) else row for row in document['pages']];subs={}
    for row in document.get('subPackages',document.get('subpackages',[])):
        require(row['root'] not in subs,'UNIAPP_PAGES_INVALID');subs[row['root']]=[page['path'] if isinstance(page,dict) else page for page in row['pages']]
    return {'pages':pages,'main_pages':main,'subpackages':subs,'source_path':source,'source_sha256':hashlib.sha256(raw).hexdigest(),'conditional_policy':'platform-line-ifdef-ifndef-endif-or-v1'}
