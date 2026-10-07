"""Thirty-three separate typed actions, fixed mappings and explicit partial writes."""
import asyncio
import hashlib
import gzip
import io
import json
import posixpath
import re
import tarfile
import time
from jsonschema import Draft202012Validator
from taskweave.plugins.sdk import CapabilitySpec, PreparedResult, ResultRequest
from .client import BaotaError, redact, _Timeout, SUMMARY_FIELDS, SUMMARY_CHAR_LIMIT
from .endpoints import PROFILE


def obj(properties,required=()):
    return {'type':'object','properties':properties,'required':list(required),'additionalProperties':False}
TEXT={'type':'string','minLength':1,'maxLength':4096}
NAME={'type':'string','pattern':r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,252}$'}
DBNAME={'type':'string','pattern':r'^[a-z][a-z0-9_]{0,31}$'}
ID={'type':'integer','minimum':1}
BOOL={'type':'boolean'}
DATA={'type':'object'}
ROWS={'type':'array','items':DATA}
STRINGS={'type':'array','items':NAME,'minItems':1,'maxItems':100}
KIND={'enum':['site','database']}
PAGE={'type':'integer','minimum':1,'maximum':10000}
LIMIT={'type':'integer','minimum':1,'maximum':100,'default':20}
COMMON={'role':TEXT,'timeout_seconds':{'type':'integer','minimum':1,'maximum':1800,'default':60},'max_response_bytes':{'type':'integer','minimum':1024,'maximum':67108864,'default':16777216},'max_output_bytes':{'type':'integer','minimum':1024,'maximum':1048576,'default':65536}}
SITE={'site_id':ID}
PAGINATION={'page':PAGE,'limit':LIMIT}
CONTENT={'type':'string','maxLength':1048576}
PORT={'type':'integer','minimum':1,'maximum':65535,'default':80}
COMPLETION={'enum':['completed','accepted','issued','unknown']}
# Every action owns an input and output schema. No arbitrary operation dispatcher is public.
DEFINITIONS={}

def declaration(name,properties,required,outputs,effect='READ'):
    DEFINITIONS[name]=(obj({**COMMON,**properties},required),obj({'completion':COMPLETION,**outputs},['completion',*outputs]),effect)

declaration('check_connection',{},[],{'version':TEXT,'profile':TEXT,'system':TEXT})
declaration('system_status',{},[],{'system':DATA,'services':DATA})
declaration('list_software',{'include_plugins':BOOL,**PAGINATION},[],{'software':ROWS,'plugins':ROWS,'truncated':BOOL})
declaration('list_php_versions',{'include_uninstalled':BOOL},[],{'versions':ROWS})
declaration('list_sites',{'search':TEXT,**PAGINATION},[],{'sites':ROWS,'truncated':BOOL})
declaration('create_site',{'domain':NAME,'path':TEXT,'php_version':NAME,'port':PORT,'remark':TEXT,'ftp_username':NAME,'ftp_password_ref':TEXT,'database_name':DBNAME,'database_username':DBNAME,'database_password_ref':TEXT},['domain','path'],{'site_id':ID,'site':DATA,'suboperations':DATA},'WRITE')
declaration('configure_site',{**SITE,'path':TEXT,'run_path':TEXT,'default_documents':STRINGS,'remark':TEXT},['site_id'],{'site':DATA,'steps':ROWS},'WRITE')
declaration('set_site_status',{**SITE,'enabled':BOOL},['site_id','enabled'],{'site':DATA},'WRITE')
declaration('list_domains',{**SITE,**PAGINATION},['site_id'],{'domains':ROWS,'truncated':BOOL})
for n in ('add_domain','remove_domain'): declaration(n,{**SITE,'domain':NAME,'port':PORT},['site_id','domain'],{'domains':ROWS,'response':DATA},'WRITE')
for n in ('get_site_config','get_rewrite'): declaration(n,SITE,['site_id'],{'path':TEXT,'content':{'type':'string'},'mtime':{'type':'integer'},'checksum':TEXT})
for n in ('set_site_config','set_rewrite'): declaration(n,{**SITE,'content':CONTENT,'expected_mtime':{'type':'integer','minimum':0}},['site_id','content','expected_mtime'],{'path':TEXT,'checksum':TEXT},'WRITE')
declaration('set_php_version',{**SITE,'version':NAME},['site_id','version'],{'version':TEXT},'WRITE')
for n in ('check_config','reload_service'): declaration(n,{'service':{'enum':['nginx','httpd']}},['service'],{'response':DATA},'WRITE')
declaration('list_databases',{'search':TEXT,**PAGINATION},[],{'databases':ROWS,'truncated':BOOL})
declaration('create_database',{'name':DBNAME,'username':DBNAME,'password_ref':TEXT,'access':TEXT,'charset':{'enum':['utf8mb4','utf8','gbk','latin1']},'remark':TEXT},['name','username','password_ref','access'],{'database':DATA},'WRITE')
declaration('set_database_credentials',{'database_id':ID,'password_ref':TEXT,'username':DBNAME},['database_id','password_ref'],{'database':DATA,'password_changed':BOOL},'WRITE')
declaration('set_database_access',{'database_id':ID,'access':{'type':'array','items':TEXT,'minItems':1,'maxItems':32}},['database_id','access'],{'access':{'type':'array','items':TEXT}},'WRITE')
declaration('delete_database',{'database_id':ID},['database_id'],{'database_id':ID,'deletion_mode':{'enum':['panel_policy']}},'WRITE')
declaration('get_certificate',SITE,['site_id'],{'certificate':DATA})
declaration('deploy_certificate',{**SITE,'key_ref':TEXT,'certificate':CONTENT},['site_id','key_ref','certificate'],{'certificate':DATA,'deployment_verified':BOOL},'WRITE')
declaration('request_certificate',{**SITE,'domains':STRINGS,'auth_type':{'enum':['http','tls','dns']},'ca':{'enum':['letsencrypt','zerossl']}},['site_id','domains','auth_type'],{'certificate':DATA,'deployment_verified':BOOL},'WRITE')
declaration('renew_certificate',SITE,['site_id'],{'certificate':DATA,'deployment_verified':BOOL},'WRITE')
declaration('set_https',{**SITE,'enabled':BOOL,'redirect':BOOL},['site_id','enabled'],{'certificate':DATA,'steps':ROWS},'WRITE')
declaration('create_backup',{'kind':KIND,'target_id':ID},['kind','target_id'],{'backups':ROWS},'WRITE')
declaration('list_backups',{'kind':KIND,'target_id':ID,**PAGINATION},['kind','target_id'],{'backups':ROWS,'truncated':BOOL})
declaration('restore_backup',{'kind':KIND,'target_id':ID,'backup_id':ID,'backup_name':NAME,'expected_tables':STRINGS,'max_archive_bytes':{'type':'integer','minimum':1,'maximum':67108864,'default':16777216},'max_unpacked_bytes':{'type':'integer','minimum':1,'maximum':67108864,'default':16777216},'max_members':{'type':'integer','minimum':1,'maximum':1000,'default':100}},['kind','target_id'],{'restore_mode':{'enum':['overlay','sql_import']},'verified_files':{'type':'integer','minimum':0},'verified_tables':{'type':'array','items':TEXT}},'WRITE')
declaration('task_status',{'task_id':ID,'status':{'enum':[-3,-1,0,1]}},[],{'tasks':ROWS,'business_success_verified':BOOL})
declaration('read_logs',{**SITE,'kind':{'enum':['access','error']},'cursor':{'type':'integer','minimum':0}},['site_id'],{'text':{'type':'string'},'cursor':{'type':'integer','minimum':0},'truncated':BOOL,'cursor_scope':{'enum':['response_snapshot']},'availability':{'enum':['present','empty','missing','unavailable']}})


def require(condition,code='BAOTA_RESPONSE_INVALID'):
    if not condition: raise BaotaError(code)


def safe_path(path,root=None):
    require(isinstance(path,str) and path.startswith('/') and path!='/' and not re.search(r"[^A-Za-z0-9_./-]",path) and '..' not in path.split('/') and posixpath.normpath(path)==path,'BAOTA_PATH_INVALID')
    if root: require(path.startswith(root.rstrip('/')+'/') and path!=root,'BAOTA_PATH_OUTSIDE_ROOT')
    return path


def safe_name(name):
    require(isinstance(name,str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,252}',name),'BAOTA_TARGET_INVALID'); return name


async def success(client,ctx,endpoint,params):
    output=await client.write(ctx,endpoint,params)
    require(output.get('status') is True,'BAOTA_WRITE_UNCONFIRMED')
    client.sent_writes[-1]['completion']='completed'
    return output


async def page(client,ctx,endpoint,params=None,*,page_number=1,limit=20,key='data'):
    result=await client.call(ctx,endpoint,{**(params or {}),'p':page_number,'row' if endpoint=='plugins' else 'limit':limit})
    if endpoint=='plugins': result=result.get('list')
    require(isinstance(result,dict) and isinstance(result.get(key),list))
    require(all(isinstance(row,dict) for row in result[key]))
    return result[key],len(result[key])>=limit  # conservative continuation; no unbounded auto-page


async def target(client,ctx,kind,identity=None,name=None,missing_ok=False):
    endpoint='sites' if kind=='site' else 'databases'
    # Exact names/IDs checked after server-side search. Scan is bounded (20 pages).
    matches=[]
    for number in range(1,21):
        rows,truncated=await page(client,ctx,endpoint,{'search':name} if name else {},page_number=number,limit=100)
        matches.extend(row for row in rows if (identity is None or str(row.get('id'))==str(identity)) and (name is None or row.get('name')==name))
        if matches or not truncated: break
    else: raise BaotaError('BAOTA_TARGET_SCAN_INCOMPLETE')
    if not matches and missing_ok: return None
    require(len(matches)==1,'BAOTA_TARGET_NOT_FOUND' if not matches else 'BAOTA_TARGET_AMBIGUOUS')
    row=matches[0]; safe_name(row.get('name')); require(str(row.get('id','')).isdigit(),'BAOTA_TARGET_INVALID')
    if kind=='site':
        safe_path(row.get('path')); require(row.get('project_type') in ('PHP',''),'BAOTA_DASHBOARD_CAPABILITY_UNSUPPORTED')
    else:
        require(str(row.get('type','')).lower()=='mysql' and str(row.get('sid',0))=='0','BAOTA_DASHBOARD_CAPABILITY_UNSUPPORTED'); safe_name(row.get('username'))
    return row


async def attributes(client,ctx,path,*,missing_ok=False):
    safe_path(path)
    # directory exact search proves existence without triggering GetFileBody's creation.
    parent,name=posixpath.split(path)
    listing=await client.call(ctx,'directory',{'path':parent,'search':name,'p':1,'showRow':100})
    require(listing.get('path')==parent and isinstance(listing.get('files'),list) and isinstance(listing.get('dir'),list),'BAOTA_PATH_UNVERIFIED')
    rows=[row for row in listing['files']+listing['dir'] if row.get('nm')==name]
    if not rows and missing_ok:
        require(len(listing['files'])+len(listing['dir'])<100,'BAOTA_PATH_UNVERIFIED')
        return None
    require(len(rows)==1,'BAOTA_FILE_MISSING' if not rows else 'BAOTA_PATH_UNVERIFIED')
    require(not rows[0].get('lnk'),'BAOTA_SYMLINK_REJECTED')
    result=await client.call(ctx,'file_attributes',{'filename':path})
    require(result.get('name')==name and result.get('path')==parent and result.get('is_link') is False,'BAOTA_PATH_UNVERIFIED')
    return result


async def checked_path(client,ctx,path,*,missing_ok=False):
    safe_path(path)
    parts=path.strip('/').split('/'); current=''
    for index,part in enumerate(parts):
        current+='/'+part
        metadata=await attributes(client,ctx,current,missing_ok=missing_ok)
        if metadata is None: return None
        if index<len(parts)-1: require(metadata.get('is_dir') is True,'BAOTA_PATH_UNVERIFIED')
    return metadata


async def site_file(client,ctx,site,rewrite=False):
    config=await client.call(ctx,'environment'); server=config.get('webserver')
    require(server in ('nginx','apache'),'BAOTA_DASHBOARD_CAPABILITY_UNSUPPORTED')
    if rewrite and server=='apache':
        await checked_path(client,ctx,site['path'])
        run=await client.call(ctx,'site_run_path',{'id':site['id']})
        suffix=run.get('runPath'); require(isinstance(suffix,str) and suffix.startswith('/') and '..' not in suffix.split('/'),'BAOTA_PATH_INVALID')
        path=site['path']+suffix.rstrip('/')+'/.htaccess'
    else: path='/www/server/panel/vhost/'+('rewrite' if rewrite else server)+'/'+site['name']+'.conf'
    safe_path(path); metadata=await checked_path(client,ctx,path); require(metadata.get('is_dir') is False,'BAOTA_PATH_UNVERIFIED')
    return path


async def file_body(client,ctx,path):
    result=await client.call(ctx,'file',{'path':path})
    require(result.get('status') is True and isinstance(result.get('data'),str))
    mtime=result.get('st_mtime')
    # Official 11.7 GetFileBody uses str(int(stat.st_mtime)). Preserve the
    # typed public result and the exact concurrency guard, without coercing
    # booleans, floats, signs, whitespace or noncanonical decimal text.
    if isinstance(mtime,str):
        require(re.fullmatch(r'0|[1-9][0-9]{0,18}',mtime) is not None)
        mtime=int(mtime)
    require(type(mtime) is int and 0<=mtime<=9223372036854775807)
    return {**result,'st_mtime':mtime}


async def domain_rows(client,ctx,site):
    rows,truncated=await page(client,ctx,'domains',{'search':site['id']},limit=100)
    require(not truncated,'BAOTA_TARGET_SCAN_INCOMPLETE'); require(all(str(row.get('pid'))==str(site['id']) for row in rows),'BAOTA_TARGET_INVALID')
    return rows


async def certificate(client,ctx,site):
    result=await client.call(ctx,'certificate',{'siteName':site['name']})
    require(type(result.get('status')) is bool and 'httpTohttps' in result)
    return result


def certificate_summary(client,value):
    safe=redact(value,client.secrets); safe['key_present']=bool(value.get('key') or value.get('private_key')); safe['certificate_present']=bool(value.get('csr') or value.get('cert'))
    return safe


async def backups(client,ctx,kind,row,page_number=1,limit=20):
    config=await client.call(ctx,'environment'); root=safe_path(config.get('backup_path'))
    if kind=='site':
        rows,truncated=await page(client,ctx,'site_backups',{'search':row['id']},page_number=page_number,limit=limit)
        base=root+'/site/'+row['name']+'/'
        rows=[backup for backup in rows if str(backup.get('pid'))==str(row['id'])]
        for backup in rows:
            filename=safe_path(backup.get('filename'),root+'/site/'+row['name'])
            require(posixpath.dirname(filename)+'/'==base and re.fullmatch(re.escape(row['name'])+r'_\d{8}_\d{6}\.tar\.gz',posixpath.basename(filename)),'BAOTA_BACKUP_OWNERSHIP_INVALID')
    else:
        rows,truncated=await page(client,ctx,'database_backups',page_number=page_number,limit=limit)
        base=root+'/database/mysql/'+row['name']+'/'
        rows=[backup for backup in rows if isinstance(backup.get('path'),str) and posixpath.dirname(backup['path'])+'/'==base]
        for backup in rows: safe_path(backup['path'],base.rstrip('/'))
    return rows,truncated


async def backup_archive(client,ctx,path,inputs):
    metadata=await checked_path(client,ctx,path)
    limit=inputs.get('max_archive_bytes',16777216)
    require(metadata.get('is_dir') is False and type(metadata.get('st_size')) is int and 0<metadata['st_size']<=limit,'BAOTA_BACKUP_SIZE_INVALID')
    data=await client.binary(ctx,path,limit)
    require(len(data)==metadata['st_size'] and hashlib.md5(data).hexdigest()==metadata.get('md5'),'BAOTA_BACKUP_INTEGRITY_FAILED')
    return data


class FailureEvidence:
    """Bounded attempt journals; resources own cleanup, never credentials/connections."""
    BUDGET=65536
    MAX_ATTEMPTS=32
    MAX_OWNERS=128
    def __init__(self):
        self.journals={}; self.owners={}; self.reservations={}
    def begin(self,ctx,client):
        attempt=ctx.scope.attempt_id; owner=id(client)
        require(owner in self.owners or len(self.owners)<self.MAX_OWNERS,'BAOTA_DIAGNOSTIC_CAPACITY')
        previous=self.owners.get(owner)
        self.owners[owner]=attempt
        if previous!=attempt and previous not in self.owners.values(): self.discard(previous)
        require(attempt in self.journals or len(self.journals)<self.MAX_ATTEMPTS,'BAOTA_DIAGNOSTIC_CAPACITY')
        self.journals.setdefault(attempt,{'action_id':'baota_dashboard.write','error_code':'BAOTA_ATTEMPT_FAILED','effect_state':'UNKNOWN','requests':[]})
        return attempt
    def close(self,client):
        previous=self.owners.pop(id(client),None)
        if previous not in self.owners.values(): self.discard(previous)
    def discard(self,attempt):
        self.journals.pop(attempt,None)
        for key in list(self.reservations):
            if key[0]==attempt: self.reservations.pop(key)
    def accounted_bytes(self,attempt,prospective=None):
        journal=self.journals[attempt]
        # JSON escapes control characters to six ASCII bytes each. An empty
        # entry is not its reservation: outstanding replies own their entire
        # worst-case scalar envelope until the request terminates.
        worst_response={key:'\x00'*SUMMARY_CHAR_LIMIT for key in SUMMARY_FIELDS}
        entries=[]
        for entry in [*journal['requests'],*([prospective] if prospective else [])]:
            item={**entry,'completion':'completed','action_state':'completed'}
            if entry is prospective or (attempt,entry['sequence']) in self.reservations:
                item['response']=worst_response
            entries.append(item)
        # Reserve future metadata/state growth as well as response bytes, so
        # final action/capture/hook updates cannot invalidate accepted writes.
        payload={**journal,'requests':entries,'error_code':'\x00'*128,
                 'action_id':max(('baota_dashboard.'+name for name in DEFINITIONS),key=len)}
        return len(json.dumps(payload,ensure_ascii=False,allow_nan=False).encode())
    def start_write(self,attempt,name,role,endpoint):
        journal=self.journals[attempt]
        # Roles are identifiers only. Long identifiers use a digest instead of
        # retaining arbitrary input text or allowing unbounded journal fields.
        identity=role if re.fullmatch(r'[A-Za-z0-9_.-]{1,64}',role) else 'sha256:'+hashlib.sha256(role.encode()).hexdigest()
        entry={'action_id':'baota_dashboard.'+name,'role':identity,'sequence':len(journal['requests'])+1,'endpoint':endpoint,'completion':'unknown','action_state':'unknown'}
        # No await between accounting and reservation: distinct clients share
        # this attempt ledger on the host event loop, before any transport send.
        require(self.accounted_bytes(attempt,entry)<=self.BUDGET,'BAOTA_DIAGNOSTIC_CAPACITY')
        self.reservations[(attempt,entry['sequence'])]=True
        journal['action_id']=entry['action_id']; journal['requests'].append(entry)
        return entry
    def finish_write(self,attempt,entry):
        # Client finally invokes this after response, business/transport/shape
        # errors or cancellation. The actual unknown/completed entry remains.
        self.reservations.pop((attempt,entry['sequence']),None)
    def capture(self,ctx,name,error,client):
        journal=self.journals.get(ctx.scope.attempt_id)
        if journal is None: return
        journal['error_code']=getattr(error,'code','CANCELLED' if isinstance(error,asyncio.CancelledError) else 'BAOTA_UNEXPECTED_ERROR')[:128]
        for entry in client.sent_writes:
            entry['action_state']='partial' if entry.get('completion') in ('completed','partial') else 'unknown'
    def complete(self,client):
        for entry in client.sent_writes: entry['action_state']='completed'
    async def results(self,ctx,error):
        journal=self.journals.get(ctx.scope.attempt_id)
        if not journal or not journal['requests']: return []
        # The host invokes this hook before resource close. Copy, retaining the
        # journal until close/rebind so repeated observation cannot erase writes.
        payload=json.loads(json.dumps(journal,ensure_ascii=False))
        code=getattr(error,'code',None)
        if code and re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',code): payload['error_code']=code
        require(len(json.dumps(payload,ensure_ascii=False).encode())<=self.BUDGET,'BAOTA_DIAGNOSTIC_CAPACITY')
        return [ResultRequest('baota_dashboard.operation_failure','baota_operation_failure',payload)]


class OperationResultHandler:
    def schema(self): return {'version':1,'tables':{},'migrations':{},'indexes':{}}
    def prepare(self,request):
        schema=obj({'action_id':TEXT,'error_code':TEXT,'effect_state':{'enum':['UNKNOWN']},'requests':ROWS},['action_id','error_code','effect_state','requests'])
        require(Draft202012Validator(schema).is_valid(request.payload),'BAOTA_FAILURE_RESULT_INVALID')
        return PreparedResult('json',payload=request.payload)
    def parse(self,stored): return stored
    def preview(self,parsed): return {'renderer':'json','data':parsed}


class JsonResultHandler:
    def schema(self): return {'version':1,'tables':{},'migrations':{},'indexes':{}}
    def prepare(self,request):
        require(isinstance(request.payload,dict),'BAOTA_RESULT_INVALID'); return PreparedResult('json',payload=request.payload)
    def parse(self,stored): return stored
    def preview(self,parsed): return {'renderer':'json','data':parsed}


class PanelAction:
    def __init__(self,name,evidence):
        self.name=name; self.evidence=evidence
        ins,outs,effect=DEFINITIONS[name]
        self.spec=CapabilitySpec('baota_dashboard.'+name,'BaoTa 11.7.0 '+name.replace('_',' '),ins,outs,effect,timeout_ms=1810000,retry_safe=effect=='READ',resource_ids=('baota_dashboard.connection',))
    async def preflight(self,ctx,inputs):
        require(Draft202012Validator(self.spec.input_schema).is_valid(inputs),'BAOTA_INPUT_INVALID'); return []
    async def verify(self,ctx,inputs,output): return []
    async def execute(self,ctx,inputs):
        await self.preflight(ctx,inputs)
        if ctx.cancelled(): raise BaotaError('CANCELLED')
        client=await ctx.resources.acquire('baota_dashboard.connection',inputs.get('role','default'))
        require(not client.busy,'BAOTA_CONNECTION_BUSY')
        client.busy=True
        try:
            client.start_operation(inputs)
            attempt=self.evidence.begin(ctx,client)
            client.write_observer=lambda endpoint:self.evidence.start_write(attempt,self.name,redact(inputs.get('role','default'),client.secrets),endpoint)
            client.write_finalizer=lambda entry:self.evidence.finish_write(attempt,entry)
            async with asyncio.timeout(inputs.get('timeout_seconds',client.timeout)) if hasattr(asyncio,'timeout') else _Timeout(client.timeout):
                total=await client.identify(ctx)
                output=await execute_action(self.name,client,ctx,inputs,total)
                output=redact(output,client.secrets)
                budget=inputs.get('max_output_bytes',65536)
                require(len(json.dumps(output,ensure_ascii=False).encode())<=budget,'BAOTA_OUTPUT_TOO_LARGE')
                self.evidence.complete(client)
                return output
        except BaseException as error:
            self.evidence.capture(ctx,self.name,error,client)
            if isinstance(error,TimeoutError): raise BaotaError('BAOTA_TRANSPORT_FAILED') from error
            raise
        finally: client.busy=False; client.write_observer=None; client.write_finalizer=None


async def execute_action(name,c,ctx,i,total):
    done={'completion':'completed'}
    if name=='check_connection': return {**done,'version':c.version,'profile':PROFILE,'system':total['system']}
    if name=='system_status':
        services=await c.call(ctx,'environment')
        summary={k:services[k] for k in ('webserver','php','mysql','redis','pure-ftpd') if k in services}
        web=services.get('web')
        if web is not None:
            require(isinstance(web,dict),'BAOTA_RESPONSE_INVALID')
            summary['web']={}
            for field in ('type','version','setup','status'):
                if field not in web: continue
                value=web[field]
                require((type(value) is bool) if field in ('setup','status') else ((field=='version' and value is False) or (isinstance(value,str) and len(value)<=128)),'BAOTA_RESPONSE_INVALID')
                summary['web'][field]=value
        return {**done,'system':total,'services':summary}
    if name=='list_software':
        software=await c.call(ctx,'software'); require(all(isinstance(row,dict) and 'name' in row and isinstance(row.get('versions'),list) for row in software))
        plugins,truncated=(await page(c,ctx,'plugins',page_number=i.get('page',1),limit=i.get('limit',20))) if i.get('include_plugins') else ([],False)
        return {**done,'software':software,'plugins':plugins,'truncated':truncated}
    if name=='list_php_versions':
        versions=await c.call(ctx,'php_versions',{'all':1} if i.get('include_uninstalled') else {})
        require(all(isinstance(row,dict) and isinstance(row.get('version'),str) for row in versions)); return {**done,'versions':versions}
    if name in ('list_sites','list_databases'):
        rows,truncated=await page(c,ctx,'sites' if name=='list_sites' else 'databases',{'search':i['search']} if i.get('search') else {},page_number=i.get('page',1),limit=i.get('limit',20))
        return {**done,'sites' if name=='list_sites' else 'databases':rows,'truncated':truncated}
    if name=='create_site':
        domain=safe_name(i['domain']); path=safe_path(i['path']); require(await target(c,ctx,'site',name=domain,missing_ok=True) is None,'BAOTA_TARGET_EXISTS')
        config=await c.call(ctx,'environment'); root=safe_path(config.get('sites_path')); safe_path(path,root)
        root_attr=await checked_path(c,ctx,root); require(root_attr.get('is_dir') is True,'BAOTA_PATH_UNVERIFIED')
        leaf=await checked_path(c,ctx,path,missing_ok=True)
        require(leaf is None or leaf.get('is_dir') is True,'BAOTA_PATH_UNVERIFIED')
        version=i.get('php_version','00'); versions=await c.call(ctx,'php_versions')
        require(any(v.get('version')==version and (version=='00' or v.get('status')) for v in versions),'BAOTA_PHP_VERSION_UNAVAILABLE')
        ftp='ftp_username' in i; sql='database_name' in i
        require(ftp==('ftp_password_ref' in i) and sql==('database_password_ref' in i) and sql==('database_username' in i),'BAOTA_INPUT_INVALID')
        params={'webname':json.dumps({'domain':domain,'domainlist':[],'count':0}),'path':path,'type':'PHP','version':version,'port':i.get('port',80),'type_id':0,'ps':i.get('remark',domain),'ftp':str(ftp).lower(),'sql':str(sql).lower()}
        if ftp: params.update(ftp_username=i['ftp_username'],ftp_password=c.secret(ctx,i['ftp_password_ref']))
        if sql:
            require(i['database_name']==i['database_username'] and len(i['database_name'])<=16,'BAOTA_DASHBOARD_CAPABILITY_UNSUPPORTED')
            require(await target(c,ctx,'database',name=i['database_name'],missing_ok=True) is None,'BAOTA_TARGET_EXISTS')
            params.update(datauser=i['database_username'],datapassword=c.secret(ctx,i['database_password_ref']),codeing='utf8mb4')
        result=await c.write(ctx,'create_site',params)
        require(result.get('siteStatus') is True and (not ftp or result.get('ftpStatus') is True) and (not sql or result.get('databaseStatus') is True),'BAOTA_PARTIAL_FAILURE')
        row=await target(c,ctx,'site',name=domain); require(row['path']==path and str(row['id'])==str(result.get('siteId')),'BAOTA_POSTVERIFY_FAILED')
        if sql:
            db=await target(c,ctx,'database',name=i['database_name']); require(db['username']==i['database_username'],'BAOTA_POSTVERIFY_FAILED')
        c.sent_writes[-1]['completion']='completed'; return {**done,'site_id':int(row['id']),'site':row,'suboperations':result}
    if name in ('check_config','reload_service'):
        response=await success(c,ctx,'service',{'name':i['service'],'type':'test' if name=='check_config' else 'reload'}); return {**done,'response':response}
    if name in ('create_database','set_database_credentials','set_database_access','delete_database'):
        return await database_action(name,c,ctx,i)
    if name in ('create_backup','list_backups','restore_backup'): return await backup_action(name,c,ctx,i)
    if name=='task_status':
        rows=await c.call(ctx,'tasks',{k:i[k] for k in ('task_id','status') if k in i}|{'num':15})
        require(all(isinstance(row,dict) and 'id' in row and 'status' in row for row in rows))
        if 'task_id' in i: rows=[row for row in rows if str(row['id'])==str(i['task_id'])]
        return {**done,'tasks':[{k:row[k] for k in ('id','name','type','status','exectime','endtime','addtime','log') if k in row} for row in rows],'business_success_verified':False}
    site=await target(c,ctx,'site',i['site_id'])
    if name=='configure_site':
        steps=[]; require(any(k in i for k in ('path','run_path','default_documents','remark')),'BAOTA_INPUT_INVALID')
        if 'path' in i:
            config=await c.call(ctx,'environment'); safe_path(i['path'],safe_path(config.get('sites_path'))); attr=await checked_path(c,ctx,i['path']); require(attr.get('is_dir') is True,'BAOTA_PATH_UNVERIFIED')
        if 'run_path' in i:
            run=i['run_path']; require(run.startswith('/') and '..' not in run.split('/') and re.fullmatch(r'[A-Za-z0-9_/.-]+',run),'BAOTA_PATH_INVALID'); attr=await checked_path(c,ctx,i.get('path',site['path'])+run.rstrip('/')); require(attr.get('is_dir') is True,'BAOTA_PATH_UNVERIFIED')
        for key,endpoint,field in [('path','site_path','path'),('run_path','run_path','runPath'),('default_documents','index','Index'),('remark','remark','ps')]:
            if key in i:
                value=','.join(i[key]) if key=='default_documents' else i[key]
                response=await success(c,ctx,endpoint,{'id':site['id'],field:value}); steps.append({'endpoint':endpoint,'response':response})
        site=await target(c,ctx,'site',site['id']); require('path' not in i or site['path']==i['path'],'BAOTA_POSTVERIFY_FAILED')
        if 'run_path' in i:
            selected=await c.call(ctx,'site_run_path',{'id':site['id']}); require(selected.get('runPath')==i['run_path'],'BAOTA_POSTVERIFY_FAILED')
        return {**done,'site':site,'steps':steps}
    if name=='set_site_status':
        await success(c,ctx,'start_site' if i['enabled'] else 'stop_site',{'id':site['id'],'name':site['name']}); site=await target(c,ctx,'site',site['id'])
        require(str(site.get('status'))==('1' if i['enabled'] else '0'),'BAOTA_POSTVERIFY_FAILED'); return {**done,'site':site}
    if name=='list_domains':
        rows,truncated=await page(c,ctx,'domains',{'search':site['id']},page_number=i.get('page',1),limit=i.get('limit',20)); require(all(str(d.get('pid'))==str(site['id']) for d in rows),'BAOTA_TARGET_INVALID'); return {**done,'domains':rows,'truncated':truncated}
    if name in ('add_domain','remove_domain'):
        domain=safe_name(i['domain']); port=i.get('port',80); rows=await domain_rows(c,ctx,site)
        matches=[d for d in rows if d.get('name')==domain and str(d.get('port'))==str(port)]
        if name=='add_domain': require(not matches,'BAOTA_TARGET_EXISTS'); params={'id':site['id'],'webname':site['name'],'domain':domain+':'+str(port)}; endpoint='add_domain'
        else:
            require(len(matches)==1 and len(rows)>1,'BAOTA_DOMAIN_REMOVAL_INVALID'); params={'id':site['id'],'webname':site['name'],'domain':domain,'port':port}; endpoint='remove_domain'
        if name=='add_domain':
            response=await c.write(ctx,endpoint,params)
            added=response.get('domains')
            if isinstance(added,list) and any(isinstance(d,dict) and d.get('status') is True for d in added):
                c.sent_writes[-1]['completion']='partial'
            # Official AddDomain returns per-domain statuses without a
            # top-level status. This action requests exactly one domain;
            # empty, mixed, unrelated or malformed rows cannot confirm it.
            require(isinstance(added,list) and len(added)==1 and isinstance(added[0],dict)
                    and added[0].get('name')==domain and type(added[0].get('status')) is bool)
            require(added[0]['status'] is True,'BAOTA_PARTIAL_FAILURE')
            c.sent_writes[-1]['completion']='completed'
        else: response=await success(c,ctx,endpoint,params)
        rows=await domain_rows(c,ctx,site); exists=any(d.get('name')==domain and str(d.get('port'))==str(port) for d in rows); require(exists==(name=='add_domain'),'BAOTA_POSTVERIFY_FAILED')
        return {**done,'domains':rows,'response':response}
    if name in ('get_site_config','get_rewrite','set_site_config','set_rewrite'):
        path=await site_file(c,ctx,site,'rewrite' in name); before=await file_body(c,ctx,path)
        if name.startswith('get_'): return {**done,'path':path,'content':before['data'],'mtime':before['st_mtime'],'checksum':hashlib.sha256(before['data'].encode()).hexdigest()}
        require(i['expected_mtime']==before['st_mtime'],'BAOTA_MTIME_CONFLICT')
        await success(c,ctx,'save_file',{'path':path,'data':i['content'],'encoding':'utf-8','st_mtime':i['expected_mtime']})
        after=await file_body(c,ctx,path); require(after['data']==i['content'],'BAOTA_POSTVERIFY_FAILED')
        return {**done,'path':path,'checksum':hashlib.sha256(after['data'].encode()).hexdigest()}
    if name=='set_php_version':
        versions=await c.call(ctx,'php_versions'); require(any(v.get('version')==i['version'] and (i['version']=='00' or v.get('status')) for v in versions),'BAOTA_PHP_VERSION_UNAVAILABLE')
        await success(c,ctx,'set_php',{'siteName':site['name'],'version':i['version']}); after=await c.call(ctx,'site_php',{'siteName':site['name']}); require(after.get('phpversion')==i['version'],'BAOTA_POSTVERIFY_FAILED'); return {**done,'version':i['version']}
    if name in ('get_certificate','deploy_certificate','request_certificate','renew_certificate','set_https'): return await certificate_action(name,c,ctx,i,site)
    if name=='read_logs':
        result=await c.call(ctx,'error_log' if i.get('kind')=='error' else 'access_log',{'siteName':site['name']}); require(result.get('status') is True and isinstance(result.get('msg'),str))
        text=redact(result['msg'],c.secrets).encode(); cursor=i.get('cursor',0); require(cursor<=len(text),'BAOTA_LOG_CURSOR_INVALID')
        try: text[:cursor].decode('utf-8')
        except UnicodeDecodeError as error: raise BaotaError('BAOTA_LOG_CURSOR_INVALID') from error
        budget=i.get('max_output_bytes',65536)
        candidate=text[cursor:cursor+budget].decode('utf-8','ignore')
        def output(length):
            chunk=candidate[:length]; consumed=len(chunk.encode())
            return {**done,'text':chunk,'cursor':cursor+consumed,'truncated':cursor+consumed<len(text),'cursor_scope':'response_snapshot','availability':result.get('availability','present' if result['msg'] else 'empty')}
        low,high=0,len(candidate)
        while low<high:
            middle=(low+high+1)//2
            if len(json.dumps(output(middle),ensure_ascii=False).encode())<=budget: low=middle
            else: high=middle-1
        return output(low)
    raise BaotaError('BAOTA_DASHBOARD_CAPABILITY_UNSUPPORTED')


async def database_action(name,c,ctx,i):
    done={'completion':'completed'}
    if name=='create_database':
        require(await target(c,ctx,'database',name=i['name'],missing_ok=True) is None,'BAOTA_TARGET_EXISTS')
        require_access(i['access'].split(','))
        password=c.secret(ctx,i['password_ref']); valid_password(password)
        await success(c,ctx,'create_database',{'sid':0,'name':i['name'],'db_user':i['username'],'password':password,'address':i['access'],'codeing':i.get('charset','utf8mb4'),'ps':i.get('remark',i['name'])})
        row=await target(c,ctx,'database',name=i['name']); require(row.get('username')==i['username'] and row.get('password')==password,'BAOTA_POSTVERIFY_FAILED')
        access=await c.call(ctx,'database_access',{'name':row['username']}); verify_access(access,i['access'].split(',')); return {**done,'database':row}
    row=await target(c,ctx,'database',i['database_id'])
    if name=='set_database_credentials':
        require(i.get('username',row['username'])==row['username'],'BAOTA_DASHBOARD_CAPABILITY_UNSUPPORTED'); password=c.secret(ctx,i['password_ref']); valid_password(password)
        await success(c,ctx,'database_password',{'id':row['id'],'name':row['username'],'data_name':row['name'],'password':password})
        after=await target(c,ctx,'database',row['id']); require(after.get('password')==password,'BAOTA_POSTVERIFY_FAILED'); return {**done,'database':after,'password_changed':True}
    if name=='set_database_access':
        require_access(i['access']); await c.call(ctx,'database_access',{'name':row['username']})
        await success(c,ctx,'set_database_access',{'name':row['username'],'access':','.join(i['access'])})
        after=await c.call(ctx,'database_access',{'name':row['username']}); verify_access(after,i['access']); return {**done,'access':i['access']}
    await success(c,ctx,'delete_database',{'id':row['id'],'name':row['name']})
    require(await target(c,ctx,'database',identity=row['id'],missing_ok=True) is None,'BAOTA_POSTVERIFY_FAILED'); return {**done,'database_id':int(row['id']),'deletion_mode':'panel_policy'}


def valid_password(password):
    require(re.fullmatch(r'[\x21-\x7e]{1,128}',password) is not None and not any(ch in password for ch in "'\"\\"),'BAOTA_PASSWORD_INVALID')


def require_access(values):
    import ipaddress
    for value in values:
        if value in ('%','127.0.0.1','localhost'): continue
        try: ipaddress.ip_address(value)
        except ValueError as error: raise BaotaError('BAOTA_DATABASE_ACCESS_INVALID') from error


def verify_access(output,expected):
    require(output.get('status') is True and isinstance(output.get('msg'),str))
    actual={x.strip() for x in output['msg'].split(',') if x.strip()}-{'localhost'}
    require(actual==set(expected)-{'localhost'},'BAOTA_POSTVERIFY_FAILED')


def pem_certificates(value,error_code):
    from cryptography import x509
    require(isinstance(value,str),error_code)
    # Permit PEM whitespace/line-ending normalization, never unrelated text
    # around a parseable certificate or an altered/reordered chain.
    block=r'-----BEGIN CERTIFICATE-----\s+[A-Za-z0-9+/=\s]+-----END CERTIFICATE-----'
    require(bool(re.search(block,value)) and not re.sub(block,'',value).strip(),error_code)
    try: certificates=x509.load_pem_x509_certificates(value.encode('ascii'))
    except (ValueError,UnicodeError) as error: raise BaotaError(error_code) from error
    require(bool(certificates),error_code)
    return certificates


async def certificate_action(name,c,ctx,i,site):
    done={'completion':'completed'}; before=await certificate(c,ctx,site)
    if name=='get_certificate': return {**done,'certificate':certificate_summary(c,before)}
    if name=='deploy_certificate':
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization
        key=c.secret(ctx,i['key_ref'])
        try:
            private=serialization.load_pem_private_key(key.encode(),password=None)
            chain=pem_certificates(i['certificate'],'BAOTA_CERTIFICATE_INVALID')
            require(bool(chain),'BAOTA_CERTIFICATE_INVALID')
            public=lambda k:k.public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
            require(public(private.public_key())==public(chain[0].public_key()),'BAOTA_CERTIFICATE_KEY_MISMATCH')
            import datetime
            now=datetime.datetime.now(datetime.timezone.utc)
            for cert in chain: require(cert.not_valid_before_utc<=now<cert.not_valid_after_utc,'BAOTA_CERTIFICATE_INVALID')
            for leaf,issuer in zip(chain,chain[1:]): leaf.verify_directly_issued_by(issuer)
            names=chain[0].extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)
            require(site['name'] in names or any(n.startswith('*.') and site['name'].split('.',1)[-1]==n[2:] for n in names),'BAOTA_CERTIFICATE_DOMAIN_MISMATCH')
        except (ValueError,TypeError,x509.ExtensionNotFound) as error: raise BaotaError('BAOTA_CERTIFICATE_INVALID') from error
        await success(c,ctx,'deploy_certificate',{'siteName':site['name'],'key':key,'csr':i['certificate']})
        after=await certificate(c,ctx,site)
        received=pem_certificates(after.get('csr'),'BAOTA_POSTVERIFY_FAILED')
        require([cert.public_bytes(serialization.Encoding.DER) for cert in received]
                ==[cert.public_bytes(serialization.Encoding.DER) for cert in chain],'BAOTA_POSTVERIFY_FAILED')
        try: received_key=serialization.load_pem_private_key(after.get('key','').encode(),password=None)
        except (ValueError,TypeError,AttributeError) as error: raise BaotaError('BAOTA_POSTVERIFY_FAILED') from error
        require(public(received_key.public_key())==public(private.public_key()),'BAOTA_POSTVERIFY_FAILED')
        return {**done,'certificate':certificate_summary(c,after),'deployment_verified':True}
    if name=='request_certificate':
        rows=await domain_rows(c,ctx,site); available={r['name'] for r in rows}; require(all(domain in available for domain in i['domains']),'BAOTA_CERTIFICATE_DOMAIN_MISMATCH')
        await checked_path(c,ctx,site['path'])
        auth_to='dns' if i['auth_type']=='dns' else site['path']
        if i['auth_type']!='dns':
            run=await c.call(ctx,'site_run_path',{'id':site['id']}); suffix=run.get('runPath'); require(isinstance(suffix,str) and suffix.startswith('/') and '..' not in suffix.split('/'),'BAOTA_PATH_INVALID'); auth_to=site['path']+suffix.rstrip('/'); await checked_path(c,ctx,auth_to)
        result=await c.write(ctx,'request_certificate',{'id':site['id'],'domains':json.dumps(i['domains']),'auth_type':i['auth_type'],'auth_to':auth_to,'auto_wildcard':0,**({'ca':i['ca']} if 'ca' in i else {})})
        if result.get('status')=='pending':
            require(isinstance(result.get('index'),str),'BAOTA_RESPONSE_INVALID'); return {'completion':'accepted','certificate':certificate_summary(c,result),'deployment_verified':False}
        require(result.get('status') is True and isinstance(result.get('cert'),str) and bool(result.get('cert')),'BAOTA_CERTIFICATE_NOT_ISSUED')
        c.sent_writes[-1]['completion']='completed'; return {'completion':'issued','certificate':certificate_summary(c,result),'deployment_verified':False}
    if name=='renew_certificate':
        index=before.get('index'); require(isinstance(index,str) and bool(index),'BAOTA_CERTIFICATE_ORDER_UNAVAILABLE')
        result=await c.write(ctx,'renew_certificate',{'index':index}); require(result.get('status') is True and isinstance(result.get('cert'),str) and bool(result['cert']) and result.get('cert_timeout'),'BAOTA_CERTIFICATE_NOT_ISSUED')
        after=await certificate(c,ctx,site); changed=bool(after.get('cert_data')) and after.get('cert_data')!=before.get('cert_data')
        c.sent_writes[-1]['completion']='completed'; return {'completion':'issued','certificate':certificate_summary(c,result),'deployment_verified':changed}
    require(not i.get('redirect') or i['enabled'],'BAOTA_HTTPS_INVALID'); require(not i['enabled'] or bool(before.get('csr')),'BAOTA_CERTIFICATE_UNAVAILABLE')
    steps=[]
    steps.append(await success(c,ctx,'https_on' if i['enabled'] else 'https_off',{'siteName':site['name']}))
    if 'redirect' in i: steps.append(await success(c,ctx,'redirect_on' if i['redirect'] else 'redirect_off',{'siteName':site['name']}))
    after=await certificate(c,ctx,site); require(after['status']==i['enabled'] and ('redirect' not in i or bool(after['httpTohttps'])==i['redirect']),'BAOTA_POSTVERIFY_FAILED'); return {**done,'certificate':certificate_summary(c,after),'steps':steps}


async def backup_action(name,c,ctx,i):
    done={'completion':'completed'}; kind=i['kind']; row=await target(c,ctx,kind,i['target_id']); rows,truncated=await backups(c,ctx,kind,row,i.get('page',1),i.get('limit',20))
    if name=='list_backups': return {**done,'backups':rows,'truncated':truncated}
    require(not truncated,'BAOTA_BACKUP_SCAN_INCOMPLETE')
    if name=='create_backup':
        before={r.get('filename',r.get('path')) for r in rows}
        if kind=='site': await checked_path(c,ctx,row['path'])
        await success(c,ctx,'site_backup' if kind=='site' else 'database_backup',{'id':row['id']})
        after,truncated=await backups(c,ctx,kind,row); require(not truncated,'BAOTA_BACKUP_SCAN_INCOMPLETE'); added=[r for r in after if r.get('filename',r.get('path')) not in before]
        require(len(added)==1,'BAOTA_BACKUP_COMPLETION_UNKNOWN'); data=await backup_archive(c,ctx,added[0].get('filename',added[0].get('path')),i)
        require(bool(data),'BAOTA_BACKUP_INTEGRITY_FAILED'); return {**done,'backups':added}
    matches=[backup for backup in rows if (kind=='site' and str(backup.get('id'))==str(i.get('backup_id'))) or (kind=='database' and backup.get('name')==i.get('backup_name'))]
    require(len(matches)==1,'BAOTA_BACKUP_OWNERSHIP_INVALID'); backup=matches[0]; path=backup.get('filename',backup.get('path')); data=await backup_archive(c,ctx,path,i)
    if kind=='database':
        require(bool(i.get('expected_tables')),'BAOTA_RESTORE_VERIFICATION_REQUIRED')
        await success(c,ctx,'restore_database',{'name':row['name'],'file':path})
        after=await c.call(ctx,'database_info',{'db_name':row['name']}); require(after.get('database')==row['name'] and isinstance(after.get('tables'),list))
        actual={table.get('table_name') for table in after['tables']}; require(set(i['expected_tables']).issubset(actual),'BAOTA_POSTVERIFY_FAILED')
        return {**done,'restore_mode':'sql_import','verified_files':0,'verified_tables':i['expected_tables']}
    root=safe_path(row['path']); await checked_path(c,ctx,root)
    members=[]; total=0
    try:
        # Bound total decompression before tarfile can allocate large PAX/extension headers.
        header_allowance=i.get('max_members',100)*2048+10240
        decompression_limit=i.get('max_unpacked_bytes',16777216)+header_allowance
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as compressed:
            expanded=compressed.read(decompression_limit+1)
        require(len(expanded)<=decompression_limit,'BAOTA_ARCHIVE_SIZE_LIMIT')
        with tarfile.open(fileobj=io.BytesIO(expanded),mode='r:') as archive:
            for member in archive:
                require(len(members)<i.get('max_members',100),'BAOTA_ARCHIVE_MEMBER_LIMIT')
                normalized=member.name[2:] if member.name.startswith('./') else member.name
                if normalized in ('','.'): continue
                require(not normalized.startswith('/') and '..' not in normalized.split('/') and re.fullmatch(r'[A-Za-z0-9_./-]+',normalized) and not member.issym() and not member.islnk() and (member.isfile() or member.isdir()),'BAOTA_ARCHIVE_UNSAFE')
                require(not member.pax_headers.get('linkpath'),'BAOTA_ARCHIVE_UNSAFE')
                destination=safe_path(root+'/'+normalized.rstrip('/'),root)
                await checked_path(c,ctx,destination,missing_ok=True)
                total+=member.size; require(total<=i.get('max_unpacked_bytes',16777216),'BAOTA_ARCHIVE_SIZE_LIMIT')
                if member.isfile():
                    content=archive.extractfile(member).read(member.size+1); require(len(content)==member.size,'BAOTA_BACKUP_INTEGRITY_FAILED')
                    members.append((destination,len(content),hashlib.md5(content).hexdigest()))
                else: members.append((destination,None,None))
    except (tarfile.TarError,EOFError,OSError) as error: raise BaotaError('BAOTA_ARCHIVE_INVALID') from error
    require(bool(members),'BAOTA_ARCHIVE_EMPTY'); await success(c,ctx,'restore_site',{'sfile':path,'dfile':root})
    for destination,size,checksum in members:
        attr=await checked_path(c,ctx,destination)
        require((attr.get('is_dir') is True) if size is None else (attr.get('is_dir') is False and attr.get('st_size')==size and attr.get('md5')==checksum),'BAOTA_POSTVERIFY_FAILED')
    await target(c,ctx,'site',row['id'])
    return {**done,'restore_mode':'overlay','verified_files':sum(size is not None for _,size,_ in members),'verified_tables':[]}
