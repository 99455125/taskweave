"""Finite CLI/native builds and immutable provenance-bound artifact checks."""
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import time
import uuid
from urllib.parse import urlsplit,unquote
from taskweave_process import run_command,RedactingContext
from .redaction import representations
from .project import require,inspect_project,path_inside,read_json,read_bytes,pages_list,snapshot,LIMIT,selected_page_plan,walk_files

class References(HTMLParser):
    def __init__(self):super().__init__();self.references=[]
    def handle_starttag(self,tag,attrs):
        for key,value in attrs:
            if value and key in ('src','href') and tag in ('script','img','link','source','video','audio'):self.references.append(value)

def artifact_structure(config,platform,output,source_plan=None,ctx=None):
    root=Path(config['project_root']);base=path_inside(root,output);snapshot(root,output,ctx=ctx);required=[]
    if platform=='mp-weixin':
        project=read_json(root,str(base/'project.config.json'))
        if (base/'project.private.config.json').exists():project={**project,**read_json(root,str(base/'project.private.config.json'))}
        appbase=path_inside(base,project.get('miniprogramRoot','./'));app=read_json(root,str(appbase/'app.json'));pages=pages_list(app)
        intended=source_plan or selected_page_plan(config,platform);compiled_main=[row['path'] if isinstance(row,dict) else row for row in app['pages']];compiled_subs={row['root']:[page['path'] if isinstance(page,dict) else page for page in row['pages']] for row in app.get('subPackages',app.get('subpackages',[]))}
        require(compiled_main==intended['main_pages'] and compiled_subs==intended['subpackages'],'UNIAPP_PAGES_MISMATCH');pages=intended['pages']
        expected=inspect_project(None,config)['appid'];require(bool(expected) and project.get('appid')==expected,'UNIAPP_APPID_MISMATCH')
        required=[str((appbase/name).relative_to(base)) for name in ('app.json','app.js')]
        required.append('project.config.json')
        for page in pages:
            for ext in ('.js','.json','.wxml'):required.append(str((appbase/(page+ext)).relative_to(base)))
        # Validate local components recursively; plugin:// and external
        # components are explicitly external, never filesystem evidence.
        manifests=[appbase/'app.json',*[appbase/(p+'.json') for p in pages]];seen=set()
        while manifests:
            manifest=manifests.pop()
            if str(manifest) in seen:continue
            require(len(seen)<500,'UNIAPP_ARTIFACT_LIMIT');seen.add(str(manifest));document=read_json(root,str(manifest))
            components=document.get('usingComponents',{});require(isinstance(components,dict),'UNIAPP_ARTIFACT_INVALID')
            for value in components.values():
                require(isinstance(value,str),'UNIAPP_ARTIFACT_INVALID')
                if value.startswith(('plugin://','dynamicLib://')):continue
                component=appbase/value.lstrip('/') if value.startswith('/') else manifest.parent/value
                for ext in ('.json','.js','.wxml'):
                    source=path_inside(appbase,str(component)+ext);require(source.is_file(),'UNIAPP_ARTIFACT_INVALID');required.append(str(source.relative_to(base)))
                manifests.append(path_inside(appbase,str(component)+'.json'))
        for source in walk_files(root,appbase,ctx):
            if source.suffix not in ('.wxss','.wxml','.js'):continue
            text=read_bytes(root,str(source)).decode('utf-8')
            refs=[]
            if source.suffix=='.wxss':refs=re.findall(r"@import\s+['\"]([^'\"]+)['\"]",text)
            if source.suffix=='.wxml':refs=re.findall(r"<(?:import|include|image)\b[^>]*\bsrc=['\"]([^'\"]+)['\"]",text)
            if source.suffix=='.js':refs=re.findall(r"require\(['\"](\.[^'\"]+)['\"]\)",text)
            for ref in refs:
                if '{{' in ref or urlsplit(ref).scheme or ref.startswith('//'):continue
                resolved=appbase/ref.lstrip('/') if ref.startswith('/') else source.parent/ref
                if source.suffix=='.js' and not resolved.suffix:resolved=resolved.with_suffix('.js')
                source_ref=path_inside(appbase,str(resolved));require(source_ref.is_file(),'UNIAPP_ARTIFACT_INVALID');required.append(str(source_ref.relative_to(base)))
        # WXSS is optional for pages without local styles. Every present file
        # is still boundary/budget checked by snapshot, including subpackages.
    else:
        text=read_bytes(root,str(base/'index.html')).decode('utf-8');parser=References();parser.feed(text);required=['index.html']
        for value in parser.references:
            parsed=urlsplit(value)
            if parsed.scheme or parsed.netloc or value.startswith('#'):continue
            rel=unquote(parsed.path).lstrip('/')
            if rel:require(path_inside(base,rel).is_file(),'UNIAPP_ARTIFACT_INVALID');required.append(rel)
        for source in walk_files(root,base,ctx):
            if source.suffix.lower()!='.css':continue
            css=re.sub(r'/\*.*?\*/','',read_bytes(root,str(source)).decode('utf-8'),flags=re.S)
            quoted=r"(?:\\.|[^\"'\\])*"
            refs=[match[1] for match in re.finditer(r'@import\s+[\"\']('+quoted+r')[\"\']',css,re.I)]
            refs += [match[1].strip().strip('\"\'') for match in re.finditer(r'url\(\s*((?:\\.|[^)])*)\)',css,re.I)]
            for ref in refs:
                def css_escape(match):
                    value=match[1]
                    if re.fullmatch(r'[0-9a-fA-F]{1,6}\s?',value):
                        number=int(value.strip(),16);require(0<number<=0x10ffff,'UNIAPP_ARTIFACT_INVALID');return chr(number)
                    return value
                ref=re.sub(r'\\([0-9a-fA-F]{1,6}\s?|.)',css_escape,ref)
                if '{{' in ref or ref.startswith('var('):continue
                parsed=urlsplit(ref)
                if parsed.scheme or parsed.netloc or ref.startswith('#'):continue
                decoded=unquote(parsed.path)
                target=base/decoded.lstrip('/') if decoded.startswith('/') else source.parent/decoded
                target=path_inside(base,str(target));require(target.is_file(),'UNIAPP_ARTIFACT_INVALID');required.append(str(target.relative_to(base)))
    for name in required:require(path_inside(base,name).is_file(),'UNIAPP_ARTIFACT_INVALID')
    return required

def command_environment(ctx,config):
    env=dict(config.get('env',{}));values=[]
    for key,reference in config.get('env_secret_refs',{}).items():
        secret=ctx.resolve_secret(reference);env[key]=secret;values.append(secret)
    if config.get('node_path'):env['PATH']=str(Path(config['node_path']).parent)+os.pathsep+os.environ.get('PATH','')
    return RedactingContext(ctx,representations(values)),env

async def node_ready(ctx,config,metadata,env):
    require(not metadata['preparation_required'],'UNIAPP_PREPARATION_REQUIRED',str(metadata['preparation_required']))
    result=await run_command(ctx,config['node_path'],['--version'],cwd=config['project_root'],env=env,stdin=None)
    match=re.fullmatch(r'v(\d+)\.(\d+)\.(\d+)\s*',result['stdout']);require(result['exit_code']==0 and bool(match),'UNIAPP_PREPARATION_REQUIRED')
    actual=tuple(int(match[i]) for i in (1,2,3));major=actual[0];require(major==config['node_major'],'UNIAPP_NODE_INCOMPATIBLE')
    engine=metadata['engines'].get('node')
    if engine:
        # Parse a deliberately narrow verifiable subset; do not pretend npm
        # semver unions/prereleases were checked by a Python version parser.
        tokens=engine.split();require(all(re.fullmatch(r'(>=|<=|>|<|\^|~|=)?\d+(\.\d+){0,2}',t) for t in tokens),'UNIAPP_PREPARATION_REQUIRED','Complex Node engines range requires explicit compatibility preparation')
        for token in tokens:
            m=re.fullmatch(r'(>=|<=|>|<|\^|~|=)?(\d+(?:\.\d+){0,2})',token);op=m[1] or '=';parts=tuple(int(v) for v in m[2].split('.'));want=parts+(0,)*(3-len(parts))
            if op in ('^','~'):
                upper=(want[0]+1,0,0) if (op=='^' and want[0]>0) or len(parts)==1 else (want[0],want[1]+1,0)
                if op=='^' and want[0]==want[1]==0 and len(parts)==3:upper=(0,0,want[2]+1)
                good=want<=actual<upper
            elif op=='=':good=actual[:len(parts)]==parts
            else:good={'>=':actual>=want,'<=':actual<=want,'>':actual>want,'<':actual<want}[op]
            require(good,'UNIAPP_NODE_INCOMPATIBLE')
    nvm=Path(config['project_root'])/'.nvmrc'
    if nvm.exists():
        value=read_bytes(config['project_root'],'.nvmrc',1024).decode().strip().lstrip('v');require(re.fullmatch(r'\d+(\.\d+){0,2}',value),'UNIAPP_NODE_INCOMPATIBLE');parts=tuple(int(v) for v in value.split('.'));require(actual[:len(parts)]==parts,'UNIAPP_NODE_INCOMPATIBLE')
    return result['stdout'].strip()


def config_identity(config):
    return hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()

def command_summary(result):
    summary=dict(result)
    for stream in ('stdout','stderr'):
        text=result.get(stream,'');summary[stream]=text[:256]
        summary[stream+'_truncated']=result.get(stream+'_truncated',False) or len(text)>256
    return summary

async def execute_command(session,ctx,action,executable,args,env,inputs):
    require(len(session.evidence.operations(ctx))<16,'UNIAPP_DIAGNOSTIC_CAPACITY')
    entry={'action_id':'uniapp.'+action,'role':hashlib.sha256(inputs.get('role','default').encode()).hexdigest(),'completion':'unknown','action_state':'unknown','command':None}
    # Library raises before sending for absent executable; reserve journal,
    # removing only entries whose failure explicitly says NOT_STARTED.
    session.evidence.operations(ctx).append(entry)
    try:
        result=await run_command(ctx,executable,args,cwd=session.root,env=env,stdin=None,timeout_seconds=inputs.get('timeout_seconds',60),max_output_bytes=inputs.get('max_output_bytes',65536))
        entry['command']=command_summary(result);entry['completion']='completed' if result['exit_code']==0 else 'partial';return result,entry
    except BaseException as error:
        result=getattr(error,'result',None)
        if result is not None:entry['command']=command_summary(result);entry['completion']='unknown'
        elif getattr(error,'effect_state',None)=='NOT_STARTED':session.evidence.operations(ctx).remove(entry)
        raise

async def build_project(ctx,config,inputs,session=None):
    require(session is not None);metadata=inspect_project(ctx,config);platform=inputs['platform'];environment=inputs.get('environment','production');key=environment+':'+platform
    safe,env=command_environment(ctx,config);output=config.get('outputs',{}).get(key)
    in_memory=config['kind']=='hbuilderx' and environment=='development' and platform=='h5'
    require(in_memory or isinstance(output,str),'UNIAPP_PREPARATION_REQUIRED','Configure explicit output mapping')
    source_plan=selected_page_plan(config,platform);before=snapshot(session.root,output,ctx=ctx) if output else {};version=None
    if config['kind']=='cli':
        version=await node_ready(safe,config,metadata,env);spec=config.get('build_scripts',{}).get(key)
        require(isinstance(spec,dict) and spec.get('script') in metadata['scripts'] and isinstance(spec.get('completion'),str) and spec['completion'],'UNIAPP_PREPARATION_REQUIRED','Existing finite build script and completion marker required')
        require(environment=='production' or spec.get('finite') is True,'UNIAPP_PREPARATION_REQUIRED','Development script must have explicit finite semantics')
        executable=config['package_manager'];args=['run',spec['script']];completion=spec['completion']
        env.update(UNI_PLATFORM=platform,NODE_ENV='production' if environment=='production' else 'development',UNI_OUTPUT_DIR=str(path_inside(session.root,output,exists=False)))
    else:
        require(not metadata['preparation_required'],'UNIAPP_PREPARATION_REQUIRED');executable=config['hbuilderx_path'];completion='编译成功'
        if environment=='production':
            proof=config.get('imported_project',{});require(proof.get('root')==session.root and isinstance(proof.get('name'),str) and proof.get('evidence'),'UNIAPP_PREPARATION_REQUIRED','Imported project name/root provenance required')
            args=['publish','--platform',platform,'--project',proof['name']]
        else:args=['launch','web' if platform=='h5' else platform,'--project',session.root,'--compile','true']
    started=time.time_ns();build_id=str(uuid.uuid4());record={'build_id':build_id,'started_at':started,'platform':platform,'environment':environment,'project_root':session.root,'argv':[executable,*args],'env_sha256':hashlib.sha256(json.dumps(env,sort_keys=True).encode()).hexdigest(),'before':before,'output':output,'state':'unknown','node_version':version,'config_sha256':config_identity(config),'source_plan':source_plan}
    session.builds[build_id]=record
    try:
        command,entry=await execute_command(session,safe,'build',executable,args,env,inputs);record['finished_at']=time.time_ns();record['command']=command
        require(command['exit_code']==0,'UNIAPP_BUILD_FAILED');text=command['stdout']+command['stderr'];require(not command['stdout_truncated'] and not command['stderr_truncated'] and completion in text,'UNIAPP_COMPLETION_UNVERIFIED')
        if config['kind']=='hbuilderx':require('已停止运行' in text or environment=='production','UNIAPP_COMPLETION_UNVERIFIED')
        if in_memory:record.update(state='compiled_in_memory',after={});return {'build_id':build_id,'started_at':started,'platform':platform,'environment':environment,'command':command,'completion':'compiled_in_memory','artifact_verified':False,'artifacts':{}}
        require(selected_page_plan(config,platform)==source_plan,'UNIAPP_SOURCE_PAGES_CHANGED')
        required=artifact_structure(config,platform,output,source_plan,ctx);after=snapshot(session.root,output,ctx=ctx);record['after']=after
        require(all(name in after and after[name]!=before.get(name) and started<=after[name]['mtime_ns']<=record['finished_at'] for name in required),'UNIAPP_ARTIFACT_STALE')
        record['state']='verified';return {'build_id':build_id,'started_at':started,'platform':platform,'environment':environment,'command':command,'completion':'completed','artifact_verified':True,'artifacts':after}
    except BaseException:
        record['state']='failed';raise

def check_artifact(ctx,config,inputs,session=None):
    require(session is not None);record=session.builds.get(inputs['build_id']);require(record is not None and record['state']=='verified' and record['started_at']==inputs['started_at'] and record['platform']==inputs['platform'] and record['project_root']==config['project_root'] and record['config_sha256']==config_identity(config),'UNIAPP_BUILD_IDENTITY_INVALID')
    require(selected_page_plan(config,inputs['platform'])==record['source_plan'],'UNIAPP_SOURCE_PAGES_CHANGED')
    artifact_structure(config,inputs['platform'],record['output'],record['source_plan'],ctx);current=snapshot(session.root,record['output'],ctx=ctx);require(current==record['after'],'UNIAPP_ARTIFACT_CHANGED')
    return {'build_id':record['build_id'],'provenance_verified':True,'structure_verified':True,'output_path':str(path_inside(session.root,record['output'])),'artifacts':current}
