"""Passive compiled-project configuration and explicit launch provenance."""
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from .bridge import require


def read_json(root,name):
    try:
        base=Path(root).resolve(strict=True);source=(base/name).resolve(strict=True);source.relative_to(base)
        require(source.is_file() and source.stat().st_size<=1048576,'WECHAT_PROJECT_INVALID')
        value=json.loads(source.read_text());require(isinstance(value,dict),'WECHAT_PROJECT_INVALID');return value
    except (OSError,ValueError,TypeError,RuntimeError):
        from taskweave.plugins.sdk import PluginError
        raise PluginError('WECHAT_PROJECT_INVALID')


def configuration(ctx):
    value={**ctx.environment.get('wechat_dev_config',{}),**getattr(ctx,'task_parameters',{}).get('wechat_dev_config',{})}
    require(isinstance(value.get('project_root'),str),'WECHAT_PREPARATION_REQUIRED','Configure compiled project root')
    try:root=Path(value['project_root']).expanduser().resolve(strict=True)
    except (OSError,RuntimeError):require(False,'WECHAT_PREPARATION_REQUIRED')
    require(root.is_dir(),'WECHAT_PROJECT_INVALID');value['project_root']=str(root)
    project=read_json(root,'project.config.json')
    if (root/'project.private.config.json').exists():project={**project,**read_json(root,'project.private.config.json')}
    try:appbase=(root/project.get('miniprogramRoot','./')).resolve(strict=True);appbase.relative_to(root)
    except (OSError,ValueError,TypeError):require(False,'WECHAT_PROJECT_INVALID')
    app=read_json(appbase,'app.json');pages=app.get('pages');require(isinstance(pages,list),'WECHAT_PROJECT_INVALID');pages=list(pages)
    for package in app.get('subPackages',app.get('subpackages',[])):
        require(isinstance(package,dict) and isinstance(package.get('root'),str) and isinstance(package.get('pages'),list),'WECHAT_PROJECT_INVALID')
        pages.extend(package['root'].rstrip('/')+'/'+page for page in package['pages'])
    require(0<len(pages)<=500 and all(isinstance(page,str) and page and not page.startswith('/') and '..' not in page.split('/') for page in pages) and len(pages)==len(set(pages)),'WECHAT_PROJECT_INVALID')
    appid=project.get('appid');require(isinstance(appid,str) and appid,'WECHAT_PREPARATION_REQUIRED','Compiled project AppID required')
    value.update(appid=appid,pages=pages)
    require(value.get('mode','attach') in ('attach','launch'),'WECHAT_CONFIG_INVALID')
    namespace=value.get('storage_namespace');require(isinstance(namespace,str) and 1<=len(namespace)<=128 and namespace.endswith(':'),'WECHAT_CONFIG_INVALID','Explicit test storage_namespace ending in colon required')
    for name in ('env','env_secret_refs'):
        mapping=value.get(name,{})
        require(isinstance(mapping,dict) and len(mapping)<=32 and all(isinstance(key,str) and 0<len(key)<=128 and isinstance(item,str) and len(item)<=4096 for key,item in mapping.items()),'WECHAT_CONFIG_INVALID')
    methods=value.get('component_methods',[]);require(isinstance(methods,list) and len(methods)<=32 and all(isinstance(method,str) for method in methods),'WECHAT_CONFIG_INVALID')
    endpoint=value.get('endpoint')
    if endpoint is not None:
        require(isinstance(endpoint,str),'WECHAT_CONFIG_INVALID');url=urlsplit(endpoint)
        require(url.scheme in ('ws','wss') and bool(url.hostname) and not url.username and not url.password and not url.query and not url.fragment,'WECHAT_CONFIG_INVALID')
    return value


def owned_root_proof(config):
    """Explicit private fixture preparation attestation, verified against disk.

    This is not an inferred SDK observed root or a bare ownership boolean.
    Runtime identity is still only AppID/page; argv/receipt provide launch roots.
    """
    reference=config.get('ownership_receipt')
    if not reference:return None
    try:
        receipt=Path(reference).resolve(strict=True);metadata=receipt.stat()
        require(metadata.st_size<=1048576 and metadata.st_mode&0o077==0,'WECHAT_OWNERSHIP_INVALID')
        record=json.loads(receipt.read_text());root=Path(config['project_root'])
        require(record.get('root')==str(root) and record.get('created_exclusively') is True and len(root.name)>=40 and root.name.startswith('tw-wechat-'),'WECHAT_OWNERSHIP_INVALID')
        if hasattr(root.stat(),'st_birthtime'):
            require(abs(int(root.stat().st_birthtime*1e9)-record['root_birth_ns'])<=10000,'WECHAT_OWNERSHIP_INVALID')
        files=record.get('files');require(isinstance(files,dict) and 1<=len(files)<=2000,'WECHAT_OWNERSHIP_INVALID')
        total=0
        for name,digest in files.items():
            source=(root/name).resolve(strict=True);source.relative_to(root);require(source.is_file(),'WECHAT_OWNERSHIP_INVALID');total+=source.stat().st_size;require(total<=16777216,'WECHAT_OWNERSHIP_INVALID')
            require(hashlib.sha256(source.read_bytes()).hexdigest()==digest,'WECHAT_OWNERSHIP_INVALID')
        return {'receipt_sha256':hashlib.sha256(receipt.read_bytes()).hexdigest(),'prepared_root':str(root),'files':len(files),'bytes':total,'creation':'exclusive_private_preparation'}
    except (OSError,ValueError,KeyError,TypeError):require(False,'WECHAT_OWNERSHIP_INVALID')
