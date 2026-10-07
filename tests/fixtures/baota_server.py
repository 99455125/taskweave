"""Owned loopback protocol fixture. Never claims to be an actual BaoTa installation."""
from contextlib import contextmanager
import datetime
import hashlib
import io
import ipaddress
import json
from pathlib import Path
import ssl
import tarfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


# Independent primary-source route allowlist. A typo in the product endpoint fails
# against this server even when that test substitutes a specific response payload.
ROUTES={
 '/system': 'GetSystemTotal GetConcifInfo ServiceAdmin',
 '/ajax': 'GetSoftList', '/plugin': 'get_soft_list',
 '/data': 'getData setPs',
 '/site': 'GetPHPVersion AddSite SetPath SetSiteRunPath GetSiteRunPath SetIndex SiteStart SiteStop AddDomain DelDomain SetPHPVersion GetSitePHPVersion GetSSL SetSSL SetSSLConf CloseSSLConf HttpToHttps CloseToHttps ToBackup GetSiteLogs get_site_errlog',
 '/database': 'AddDatabase ResDatabasePassword GetDatabaseAccess SetDatabaseAccess DeleteDatabase ToBackup GetBackup InputSql GetInfo GetImportLog',
 '/acme': 'apply_cert_api renew_cert',
 '/files': 'GetFileBody SaveFileBody UnZip GetDirNew get_file_attribute',
 '/task': 'get_task_lists', '/download': ''}


# Independently transcribed from the official 11.7.0 methods, not EndpointSpec.
# panelSite.py SetPath/SetSiteRunPath/GetSiteRunPath/SetIndex/GetPHPVersion;
# data.py setPs; panelPlugin.py get_soft_list:1930; database.py
# GetDatabaseAccess/SetDatabaseAccess/GetBackup:2011/GetInfo:2760;
# panelTask.py get_task_lists:60; files.py GetDirNew/get_file_attribute.
FIELD_CONTRACTS={
 'SetPath':({'id','path'},set()), 'SetSiteRunPath':({'id','runPath'},set()),
 'GetSiteRunPath':({'id'},set()), 'SetIndex':({'id','Index'},set()),
 'setPs':({'id','ps','table'},set()), 'GetPHPVersion':(set(),{'all','s_type'}),
 'get_soft_list':({'type','p','row'},{'query'}),
 'apply_cert_api':({'id','domains','auth_type','auth_to','auto_wildcard'},{'ca'}),
 'renew_cert':({'index'},set()), 'GetSSL':({'siteName'},set()),
 'SetSSL':({'siteName','key','csr'},set()),
 'GetDatabaseAccess':({'name'},set()), 'SetDatabaseAccess':({'name','access'},set()),
 'GetBackup':({'p','limit'},{'search'}), 'GetInfo':({'db_name'},set()),
 'get_task_lists':({'num'},{'task_id','status'}),
 'GetDirNew':({'path','p','showRow'},{'search'}),
 'get_file_attribute':({'filename'},set()),
}


class BaotaServer:
    secret = 'fixture-only-api-secret'
    def __init__(self, root, tls=False):
        self.enforce_fields=False; self.root = Path(root); self.requests=[]; self.overrides={}; self.version='11.7.0'
        self.sites=[dict(id=1,name='example.test',path='/www/wwwroot/example.test',status='1',project_type='PHP')]
        self.domains=[dict(id=1,pid=1,name='example.test',port=80)]
        self.databases=[dict(id=1,name='example',username='example',password='db-secret',sid=0,type='MySQL')]
        self.access='127.0.0.1'; self.php='00'; self.ssl=dict(status=False,httpTohttps=False,key='',csr='',index='order1',cert_data={})
        self.files={'/www/wwwroot/example.test/index.html':b'old', '/www/server/panel/vhost/nginx/example.test.conf': b'server {}', '/www/server/panel/vhost/rewrite/example.test.conf': b''}
        bio=io.BytesIO()
        with tarfile.open(fileobj=bio,mode='w:gz') as archive:
            member=tarfile.TarInfo('./index.html'); member.size=5; archive.addfile(member,io.BytesIO(b'hello'))
        self.directories={'/www','/www/wwwroot','/www/wwwroot/example.test'}; self.links={}; self.run_paths={1:'/'}
        self.archive=bio.getvalue(); self.backups=[]; self.db_backups=[]; self.tls=tls

    def start(self):
        fixture=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_GET(self): self.handle_request()
            def do_POST(self): self.handle_request()
            def handle_request(self):
                parsed=urlsplit(self.path); query=parse_qs(parsed.query)
                if self.command=='POST': query.update(parse_qs(self.rfile.read(int(self.headers.get('Content-Length',0))).decode(),keep_blank_values=True))
                params={k:v[-1] for k,v in query.items()}; action=params.get('action','')
                if self.command=='POST' and 'action' not in parse_qs(parsed.query):
                    return self.respond({'status':False,'msg':'fixed action must be in route query'})
                fixture.requests.append((self.command,parsed.path,action,params))
                ts=params.get('request_time',''); expected=hashlib.md5((ts+hashlib.md5(fixture.secret.encode()).hexdigest()).encode()).hexdigest()
                if params.get('request_token')!=expected or not ts.isdigit() or abs(time.time()-int(ts))>10:
                    return self.respond({'status':False,'msg':'signature rejected'})
                if parsed.path not in ROUTES or (parsed.path!='/download' and action not in ROUTES[parsed.path].split()):
                    return self.respond({'status':False,'msg':'unverified route/action'})
                if fixture.enforce_fields and action in FIELD_CONTRACTS:
                    required,optional=FIELD_CONTRACTS[action]; fields=set(params)-{'action','request_time','request_token'}
                    if not required<=fields or fields-(required|optional): return self.respond({'status':False,'msg':'independent business fields rejected'})
                override=fixture.overrides.get(action)
                if callable(override): override=override(params)
                if isinstance(override,tuple):
                    code,body,headers=override; return self.respond(body,code,headers)
                if override is not None: return self.respond(override)
                result=fixture.dispatch(parsed.path,action,params)
                self.respond(result)
            def respond(self,body,code=200,headers=None):
                data=body if isinstance(body,bytes) else json.dumps(body).encode()
                self.send_response(code)
                self.send_header('Content-Type','application/octet-stream' if isinstance(body,bytes) else 'application/json')
                self.send_header('Content-Length',str(len(data)))
                for k,v in (headers or {}).items(): self.send_header(k,v)
                self.end_headers()
                try: self.wfile.write(data)
                except (BrokenPipeError,ssl.SSLEOFError): pass
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        if self.tls:
            self.generate_tls()
            ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(self.cert_path,self.key_path)
            self.server.socket=ctx.wrap_socket(self.server.socket,server_side=True)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start()
        self.url=('https' if self.tls else 'http')+'://127.0.0.1:'+str(self.server.server_port)
        return self
    def close(self): self.server.shutdown(); self.server.server_close(); self.thread.join()
    def generate_tls(self):
        self.key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'fixture-only')]); now=datetime.datetime.now(datetime.timezone.utc)
        cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(self.key.public_key()).serial_number(x509.random_serial_number())
              .not_valid_before(now-datetime.timedelta(minutes=1)).not_valid_after(now+datetime.timedelta(days=1))
              .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1')),x509.DNSName('example.test')]),critical=False)
              .add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True).sign(self.key,hashes.SHA256()))
        self.cert_pem=cert.public_bytes(serialization.Encoding.PEM).decode(); self.key_pem=self.key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
        self.cert_path=self.root/'fixture-ca.pem'; self.key_path=self.root/'fixture-key.pem'
        self.cert_path.write_text(self.cert_pem); self.key_path.write_text(self.key_pem); self.key_path.chmod(0o600)
    def dispatch(self,path,a,p):
        ok={'status':True,'msg':'ok'}
        if path=='/download': return self.files.get(p['filename'],self.archive)
        if a=='GetSystemTotal': return dict(version=self.version,system='Debian fixture',cpuNum=1,memTotal=100,memFree=50)
        if a=='GetConcifInfo': return dict(webserver='nginx',backup_path='/www/backup',sites_path='/www/wwwroot',php=[],web={'type':'nginx','setup':True,'version':'1.26','status':True,'secret':'never expose'},mysql_root='root-secret',panel={'admin_path':'secret-path'})
        if a=='GetSoftList': return [dict(name='nginx',check=True,versions=[dict(version='1.26',status=True,task=False)])]
        if a=='get_soft_list': return dict(list=dict(data=[dict(name='plugin',setup=True)],page=''))
        if a=='GetPHPVersion': return [dict(version='00',name='Static',status=True)]
        if a=='getData':
            table=p['table']; data={'sites':self.sites,'domain':self.domains,'databases':self.databases,'backup':self.backups}[table]
            return dict(data=data,page='')
        if a=='AddSite':
            name=json.loads(p['webname'])['domain']; self.sites.append(dict(id=2,name=name,path=p['path'],status='1',project_type='PHP'))
            return dict(siteStatus=True,siteId=2,ftpStatus=p['ftp']=='true',databaseStatus=p['sql']=='true',ftpPass='ftp-secret',databasePass='db-secret')
        if a=='SetPath': self.sites[0]['path']=p['path']; return ok
        if a=='SetSiteRunPath': self.run_paths[int(p['id'])]=p['runPath']; return ok
        if a in ('SetIndex','setPs'): return ok
        if a in ('SiteStart','SiteStop'): self.sites[0]['status']='1' if a=='SiteStart' else '0'; return ok
        if a=='AddDomain': self.domains.append(dict(id=2,pid=1,name=p['domain'].split(':')[0],port=int(p['domain'].split(':')[1]) if ':' in p['domain'] else 80)); return dict(domains=[dict(name=p['domain'].split(':')[0],status=True,msg='添加成功')])
        if a=='DelDomain': self.domains=[d for d in self.domains if d['name']!=p['domain']]; return ok
        if a=='GetFileBody':
            if p['path'] not in self.files: self.files[p['path']]=b''
            return dict(status=True,data=self.files[p['path']].decode(),encoding='utf-8',size=len(self.files[p['path']]),st_mtime='1')
        if a=='SaveFileBody':
            if 'invalid' in p['data']: return dict(status=False,msg='configuration invalid')
            self.files[p['path']]=p['data'].encode(); return ok
        if a=='SetPHPVersion': self.php=p['version']; return ok
        if a=='GetSiteRunPath': return dict(runPath=self.run_paths.get(int(p['id']),'/'),dirs=['/','/public'])
        if a=='GetSitePHPVersion': return dict(phpversion=self.php)
        if a=='ServiceAdmin': return ok
        if a=='AddDatabase': self.databases.append(dict(id=2,name=p['name'],username=p['db_user'],password=p['password'],sid=0,type='MySQL')); return ok
        if a=='ResDatabasePassword': self.databases[0]['password']=p['password']; return ok
        if a=='GetDatabaseAccess': return dict(status=True,msg=self.access)
        if a=='SetDatabaseAccess': self.access=p['access']; return ok
        if a=='DeleteDatabase': self.databases=[d for d in self.databases if str(d['id'])!=p['id']]; return ok
        if a=='GetSSL': return self.ssl
        if a=='SetSSL': self.ssl.update(status=True,key=p['key'].strip(),csr=p['csr'].strip(),cert_data={'notAfter':'tomorrow'}); return ok
        if a=='apply_cert_api': return dict(status='pending',index='order1',auths=[dict(token='dns-secret')]) if p['auth_type']=='dns' else dict(status=True,cert='certificate',private_key='cert-secret',cert_timeout=10)
        if a=='renew_cert': return dict(status=True,cert='new-cert',cert_timeout=20,private_key='cert-secret')
        if a in ('SetSSLConf','CloseSSLConf'): self.ssl['status']=a=='SetSSLConf'; return ok
        if a in ('HttpToHttps','CloseToHttps'): self.ssl['httpTohttps']=a=='HttpToHttps'; return ok
        if a=='ToBackup':
            if path=='/site':
                name='example.test_20261002_120000.tar.gz'; filename='/www/backup/site/example.test/'+name; self.files[filename]=self.archive
                self.backups.append(dict(id=1,pid=1,name=name,filename=filename,size=len(self.archive)))
            else:
                filename='/www/backup/database/mysql/example/example.sql.gz'; self.files[filename]=b'sql'; self.db_backups.append(dict(name='example.sql.gz',path=filename,size=3))
            return ok
        if a=='GetBackup': return dict(data=self.db_backups,page='')
        if a=='UnZip':
            with tarfile.open(fileobj=io.BytesIO(self.files[p['sfile']]),mode='r:gz') as tar:
                for m in tar:
                    if m.isfile(): self.files[p['dfile']+'/'+m.name.removeprefix('./')]=tar.extractfile(m).read()
            return ok
        if a=='InputSql': return ok
        if a=='GetInfo': return dict(database=p['db_name'],tables=[dict(table_name='example_table')])
        if a=='get_task_lists': return [dict(id=1,name='fixture task',type=2,status=1,shell='secret shell',other='secret other',log='completed')]
        if a in ('GetSiteLogs','get_site_errlog','GetImportLog'): return dict(status=True,msg='hello log fixture-only-api-secret')
        if a=='GetDirNew':
            base=p['path'].rstrip('/'); entries={}
            for filename in set(self.files)|self.directories|set(self.links):
                data=self.files.get(filename,b'')
                if filename.startswith(base+'/'):
                    rest=filename[len(base)+1:]; child=rest.split('/')[0]
                    entries[child]=dict(nm=child,sz=len(data),lnk=self.links.get(base+'/'+child,''),is_dir='/' in rest or filename in self.directories or filename in self.links)
            result=[v for v in entries.values() if p.get('search','') in v['nm']]
            return dict(path=p['path'],dir=[v for v in result if v['is_dir']],files=[v for v in result if not v['is_dir']],page='')
        if a=='get_file_attribute':
            filename=p['filename']; directory=filename in self.directories or filename in self.links or any(f.startswith(filename.rstrip('/')+'/') for f in self.files)
            if filename not in self.files and not directory: return dict(status=False,msg='指定文件不存在!')
            data=self.files.get(filename,b''); return dict(name=Path(filename).name,path=str(Path(filename).parent),st_size='dir' if directory else len(data),is_dir=directory,is_link=filename in self.links,md5=hashlib.md5(data).hexdigest())
        return dict(status=False,msg='unknown fixture action '+a)


def concurrent_journal_registry():
    """Worker test harness: exercise the real action concurrently inside one call.

    Task Python disallows imports/asyncio, so this fixture-only wrapper makes
    distinct-role calls with the real PluginContext; no product batch API exists.
    """
    import asyncio
    from taskweave.plugins.registry import Registry
    from taskweave_baota_dashboard import BaotaDashboardPlugin
    class ConcurrentPlugin(BaotaDashboardPlugin):
        def actions(self):
            actions=super().actions(); original=actions['baota_dashboard.check_config']
            class ConcurrentAction:
                spec=original.spec
                async def preflight(self,ctx,inputs): return await original.preflight(ctx,inputs)
                async def verify(self,ctx,inputs,output): return []
                async def execute(self,ctx,inputs):
                    for _ in range(82): await original.execute(ctx,{'service':'nginx'})
                    responses=await asyncio.gather(*(original.execute(ctx,{'service':'nginx','role':'concurrent'+str(n)}) for n in range(16)),return_exceptions=True)
                    rejected=[r for r in responses if isinstance(r,Exception)]
                    if any(getattr(r,'code',None)!='BAOTA_DIAGNOSTIC_CAPACITY' for r in rejected): raise rejected[0]
                    return {'completion':'completed','response':{'status':True,'msg':'fixture batch done'}}
            actions['baota_dashboard.check_config']=ConcurrentAction(); return actions
    return Registry([ConcurrentPlugin()])
