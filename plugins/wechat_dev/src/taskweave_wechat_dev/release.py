"""Finite official CI preview/upload, independent of simulator sessions."""
import asyncio
import hashlib
import json
import os
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from jsonschema import Draft202012Validator
from taskweave.plugins.sdk import CapabilitySpec, ResultRequest
from taskweave_process import RedactingContext, run_command
from taskweave_process.artifacts import ARTIFACT_SCHEMA, read_artifact, _stage_bytes
from .actions import obj, SHORT, TEXT
from .bridge import require, representations
from .qrcode import image_extension

CI_VERSION = '2.1.48'
BRIDGE = Path(__file__).parent / 'node' / 'release.cjs'
COMMON = {'project_path': TEXT, 'desc': {'type':'string','maxLength':1024},
          'robot': {'type':'integer','minimum':1,'maximum':30},
          'timeout_seconds': {'type':'integer','minimum':1,'maximum':1800},
          'expected_artifacts': {'type':'object','minProperties':1,'maxProperties':2000,'additionalProperties':obj({'sha256':{'type':'string','pattern':'^[0-9a-f]{64}$'},'size':{'type':'integer','minimum':0,'maximum':67108864}},['sha256','size'])}}


def release_configuration(ctx, inputs):
    try:
        environment = ctx.environment.get('wechat_release_config', {})
        parameters = ctx.task_parameters.get('wechat_release_config', {})
        require(isinstance(environment,dict) and isinstance(parameters,dict),'WECHAT_RELEASE_CONFIGURATION_INVALID')
        config = {**environment,**parameters}
        root = Path(config['project_root']).expanduser().resolve(strict=True)
        node = Path(config['node_path']).expanduser().resolve(strict=True)
        module = Path(config['module_root']).expanduser().resolve(strict=True)
        require(root.is_dir() and node.is_file() and module.is_dir(), 'WECHAT_RELEASE_CONFIGURATION_INVALID')
        if 'project_path' in inputs:
            require(Path(inputs['project_path']).resolve(strict=True) == root, 'WECHAT_RELEASE_BUILD_MISMATCH')
        _, raw = read_artifact(root, 'project.config.json', 1024*1024)
        project = json.loads(raw)
        require(isinstance(project,dict),'WECHAT_RELEASE_CONFIGURATION_INVALID')
        appid = project.get('appid', '')
        require(isinstance(appid,str) and re.fullmatch(r'wx[0-9a-fA-F]{16}',appid), 'WECHAT_RELEASE_APPID_REQUIRED')
        mini = (root / project.get('miniprogramRoot', './')).resolve(strict=True)
        mini.relative_to(root)
        require(mini.is_dir(), 'WECHAT_RELEASE_CONFIGURATION_INVALID')
        _, app = read_artifact(root, str(mini/'app.json'), 1024*1024)
        require(isinstance(json.loads(app),dict) and isinstance(json.loads(app).get('pages'),list), 'WECHAT_RELEASE_ARTIFACT_INVALID')
        _, metadata = read_artifact(module, 'node_modules/miniprogram-ci/package.json', 65536)
        require(isinstance(json.loads(metadata),dict) and json.loads(metadata).get('version') == CI_VERSION, 'WECHAT_RELEASE_SDK_PREPARATION_REQUIRED')
        ref = config['private_key_ref']
        require(isinstance(ref,str) and bool(ref), 'WECHAT_RELEASE_PRIVATE_KEY_REQUIRED')
    except (KeyError, TypeError, ValueError, OSError) as exc:
        from taskweave.plugins.sdk import PluginError
        raise PluginError('WECHAT_RELEASE_CONFIGURATION_INVALID', 'Prepare compiled project, Node, pinned CI SDK and private_key_ref') from exc
    if 'expected_artifacts' in inputs:
        snapshot_project(root,inputs['expected_artifacts'])
    return {'project_root':str(root),'node_path':str(node),'module_root':str(module),'appid':appid,'private_key_ref':ref}


def snapshot_project(root, expected=None):
    root=Path(root);files={};total=0;count=0;stack=[root]
    while stack:
        directory=stack.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                count+=1
                require(count<=4000 and not entry.is_symlink(),'WECHAT_RELEASE_ARTIFACT_INVALID')
                if entry.is_dir(follow_symlinks=False):stack.append(Path(entry.path));continue
                require(entry.is_file(follow_symlinks=False) and len(files)<2000,'WECHAT_RELEASE_ARTIFACT_INVALID')
                name=Path(entry.path).relative_to(root).as_posix()
                _,data=read_artifact(root,name,max(1,67108864-total))
                total+=len(data);require(total<=67108864,'WECHAT_RELEASE_ARTIFACT_INVALID')
                files[name]=data
    if expected is not None:
        actual={name:{'sha256':hashlib.sha256(data).hexdigest(),'size':len(data)} for name,data in files.items()}
        require(actual==expected,'WECHAT_RELEASE_ARTIFACT_CHANGED')
    return files


class ReleaseEvidence:
    """Last release receipt for the current attempt, including post-upload errors."""
    def __init__(self):
        self.attempt = None
        self.receipt = None
        self.preview_artifact = None
    async def results(self, ctx, error):
        if self.attempt != ctx.scope.attempt_id or self.receipt is None:
            return []
        return [*([ResultRequest('wechat_dev.image','preview_qr',dict(self.preview_artifact))] if self.preview_artifact else []),ResultRequest('wechat_dev.operation_failure','wechat_release_operation',dict(self.receipt))]


class ReleaseAction:
    def __init__(self, name, evidence):
        self.name, self.evidence = name, evidence
        properties = dict(COMMON)
        if name == 'preview':
            properties.update(page_path=SHORT,search_query={'type':'string','maxLength':4096},scene={'type':'integer','minimum':0,'maximum':65535})
        else:
            properties['version'] = {'type':'string','minLength':1,'maxLength':64,'pattern':r'^\S+$'}
        output = {'remote_state':{'const':'completed'},'appid':SHORT,'project_path':TEXT,
                  'sub_packages':{'type':'array'},'plugins':{'type':'array'}}
        output.update({'artifact':ARTIFACT_SCHEMA} if name=='preview' else {'version':SHORT})
        self.spec = CapabilitySpec('wechat_dev.'+name,'Official WeChat CI '+name,
            obj(properties, ['version'] if name=='upload' else []), obj(output,output),
            'WRITE',timeout_ms=1810000,retry_safe=False,resource_ids=())
    async def preflight(self, ctx, inputs):
        require(Draft202012Validator(self.spec.input_schema).is_valid(inputs),'WECHAT_INPUT_INVALID')
        release_configuration(ctx,inputs)
        return []
    async def verify(self, ctx, inputs, output):
        return []
    async def execute(self, ctx, inputs):
        await self.preflight(ctx,inputs)
        config = release_configuration(ctx,inputs)
        require(not ctx.cancelled(),'CANCELLED')
        key = ctx.resolve_secret(config['private_key_ref'])
        require(isinstance(key,str) and 0<len(key.encode())<=65536,'WECHAT_RELEASE_PRIVATE_KEY_REQUIRED')
        patterns = representations([key]+[line for line in key.splitlines() if len(line)>=8])
        context = RedactingContext(ctx,patterns)
        files=snapshot_project(config['project_root'],inputs.get('expected_artifacts'))
        if self.evidence.attempt != ctx.scope.attempt_id:
            self.evidence.preview_artifact=None
        receipt = {'action_id':self.spec.id,'effect_state':'NOT_STARTED','appid':config['appid']}
        self.evidence.attempt,self.evidence.receipt = ctx.scope.attempt_id,receipt
        with TemporaryDirectory(prefix='taskweave-wechat-preview-') as temporary:
            frozen=Path(temporary)/'project';frozen.mkdir()
            for name,data in files.items():
                target=frozen/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
            request = {'action':self.name,'project_path':str(frozen),'module_root':config['module_root'],
                'appid':config['appid'],'private_key':key,'options':{k:v for k,v in inputs.items() if k not in ('project_path','timeout_seconds','expected_artifacts')},
                'qrcode_path':str(Path(temporary)/'preview.png')}
            try:
                receipt['effect_state']='UNKNOWN'
                result = await run_command(context,config['node_path'],[str(BRIDGE)],cwd=config['project_root'],env={},
                    stdin=json.dumps(request).encode(),timeout_seconds=inputs.get('timeout_seconds',300),max_output_bytes=65536)
                receipt['exit_code'] = result['exit_code']
                require(result['exit_code']==0,'WECHAT_RELEASE_SDK_FAILED','Official CI operation failed; remote effect may be unknown')
                lines = [line[len('TASKWEAVE_CI:'):] for line in result['stdout'].splitlines() if line.startswith('TASKWEAVE_CI:')]
                require(len(lines)==1 and not result['stdout_truncated'],'WECHAT_RELEASE_PROTOCOL_INVALID')
                payload = json.loads(lines[0])
                require(isinstance(payload,dict) and set(payload)=={'sub_packages','plugins'},'WECHAT_RELEASE_PROTOCOL_INVALID')
                require(isinstance(payload['sub_packages'],list) and isinstance(payload['plugins'],list),'WECHAT_RELEASE_PROTOCOL_INVALID')
                for row in payload['sub_packages']:
                    require(isinstance(row,dict) and set(row)=={'name','size'} and isinstance(row['name'],str) and type(row['size']) is int and row['size']>=0,'WECHAT_RELEASE_PROTOCOL_INVALID')
                for row in payload['plugins']:
                    require(isinstance(row,dict) and set(row)=={'pluginProviderAppid','version'} and all(isinstance(v,str) for v in row.values()),'WECHAT_RELEASE_PROTOCOL_INVALID')
                receipt['effect_state']='COMPLETED'
                output = {'remote_state':'completed','appid':config['appid'],'project_path':config['project_root'],**payload}
                if self.name=='preview':
                    _, data = read_artifact(temporary,'preview.png',4*1024*1024)
                    extension=image_extension(data)
                    output['artifact'] = await _stage_bytes(ctx,'wechat-preview.'+extension,data)
                    self.evidence.preview_artifact=output['artifact']
                else:
                    output['version']=inputs['version']
                return output
            except (json.JSONDecodeError,ValueError,OSError) as exc:
                from taskweave.plugins.sdk import PluginError
                receipt['error_code']='WECHAT_RELEASE_PROTOCOL_INVALID'
                raise PluginError('WECHAT_RELEASE_PROTOCOL_INVALID') from exc
            except BaseException as exc:
                receipt['error_code']=getattr(exc,'code','CANCELLED' if isinstance(exc,asyncio.CancelledError) else 'WECHAT_RELEASE_FAILED')
                raise
