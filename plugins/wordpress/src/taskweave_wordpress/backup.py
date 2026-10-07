"""Bounded complete files+SQL envelopes, scope validation and partial receipts."""
import hashlib
import gzip
import io
import json
from pathlib import PurePosixPath
import re
import tarfile
import time
import uuid

from .commands import require


def digest(data): return hashlib.sha256(data).hexdigest()


def safe_member(name):
    require(isinstance(name,str) and name and '\\' not in name and '\x00' not in name and not name.startswith('/') and all(part not in ('','..','.') for part in name.split('/')),'WORDPRESS_ARCHIVE_PATH_INVALID')
    return name


def sql_statements(data):
    """Lex dump statements without mistaking string literals for scope tokens.

    Delimiters, routines, triggers, database switches and arbitrary SQL are
    refused. Ordinary WP table dumps use this constrained mysql dump grammar.
    Versioned SET/ALTER comments are inspected rather than executed blindly.
    """
    try: text=data.decode('utf-8')
    except UnicodeError: require(False,'WORDPRESS_SQL_INVALID')
    require('\x00' not in text,'WORDPRESS_SQL_INVALID')
    parts=[]; current=[]; quote=None; index=0;word_token=re.compile(r'[A-Za-z_][A-Za-z0-9_]*');comment_end=re.compile(r'\s*(?:;|$)')
    while index<len(text):
        c=text[index]
        if quote:
            current.append(c)
            if c=='\\' and quote!="`" and index+1<len(text):
                index+=1; current.append(text[index])
            elif c==quote:
                if index+1<len(text) and text[index+1]==quote: index+=1;current.append(text[index])
                else: quote=None
            index+=1;continue
        if c in "'\"`": quote=c;current.append(c);index+=1;continue
        word=word_token.match(text,index) if c.isalpha() and (index==0 or not (text[index-1].isalnum() or text[index-1]=='_')) else None
        if word:
            require(word[0].upper()!='DELIMITER','WORDPRESS_SQL_CLIENT_COMMAND_REJECTED')
            line_start=text.rfind('\n',0,index)+1
            if not text[line_start:index].strip():
                require(word[0].lower() not in {'charset','clear','connect','edit','ego','exit','go','help','nopager','notee','nowarning','pager','print','prompt','quit','rehash','source','status','system','tee','warning'},'WORDPRESS_SQL_CLIENT_COMMAND_REJECTED')
        if text.startswith('--',index) and (index+2==len(text) or text[index+2].isspace()) or c=='#':
            end=text.find('\n',index);current.append(' ');index=len(text) if end<0 else end;continue
        require(c!='\\','WORDPRESS_SQL_CLIENT_COMMAND_REJECTED')
        if text.startswith('/*',index):
            end=text.find('*/',index+2);require(end>=0,'WORDPRESS_SQL_INVALID')
            if text.startswith('/*!',index) or text.startswith('/*M!',index):
                payload=text[index+(4 if text.startswith('/*M!',index) else 3):end]
                version=re.match(r'[0-9]+',payload)
                if version:
                    require(len(version[0]) in (5,6),'WORDPRESS_SQL_INVALID')
                    payload=payload[len(version[0]):]
                # Only complete native-dump metadata/KEYS statements may be
                # conditional. Skipping one is an empty statement; executing
                # one preserves a whole validated owned target. Never join
                # conditional tokens into identifiers or surrounding SQL.
                require(not ''.join(current).strip() and '/*' not in payload and '*/' not in payload,'WORDPRESS_SQL_INVALID')
                require(comment_end.match(text,end+2) is not None,'WORDPRESS_SQL_INVALID')
                conditional=sql_statements(payload.encode('utf-8'))
                require(len(conditional)==1,'WORDPRESS_SQL_INVALID')
                body=conditional[0]
                require(re.fullmatch(r'SET\s+.+|ALTER\s+TABLE\s+`?[A-Za-z0-9_]+`?\s+(?:ENABLE|DISABLE)\s+KEYS',body,re.I|re.S),'WORDPRESS_SQL_SCOPE_INVALID')
                current.append(body);index=end+2;continue
            require('\\' not in text[index+2:end] and not text.startswith('/*+',index),'WORDPRESS_SQL_CLIENT_COMMAND_REJECTED')
            current.append(' ');index=end+2;continue
        if c==';':
            statement=''.join(current).strip()
            if statement: parts.append(statement)
            current=[]
        else: current.append(c)
        index+=1
    require(quote is None,'WORDPRESS_SQL_INVALID')
    if ''.join(current).strip(): parts.append(''.join(current).strip())
    return parts


def validate_sql(data,tables):
    require(isinstance(data,bytes) and data and tables,'WORDPRESS_SQL_INVALID')
    allowed=set(tables);seen=set()
    for statement in sql_statements(data):
        # Values may contain arbitrary content, but must not affect grammar.
        match=re.match(r'^(?:DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?|CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?|INSERT\s+INTO\s+|ALTER\s+TABLE\s+)(`[A-Za-z0-9_]+`|[A-Za-z0-9_]+)\s*(.*)$',statement,re.I|re.S)
        if match:
            table=match.group(1).strip('`');require(table in allowed,'WORDPRESS_SQL_SCOPE_INVALID');seen.add(table)
            suffix=match.group(2)
            grammar=_without_literals(suffix)
            require(not re.search(r'(?i)\b(?:CONNECTION|TABLESPACE|DATA\s+DIRECTORY|INDEX\s+DIRECTORY)\b',grammar),'WORDPRESS_SQL_SCOPE_INVALID')
            engine=re.search(r'(?i)\bENGINE\s*=\s*([A-Za-z0-9_]+)',grammar)
            require(not engine or engine.group(1).lower() in ('innodb','myisam','aria','memory'),'WORDPRESS_SQL_SCOPE_INVALID')
            require(not suffix.startswith('.') and not re.search(r'(?i)\b(?:SELECT|OUTFILE|INFILE|REFERENCES|TRIGGER|PROCEDURE|FUNCTION|RENAME)\b',_without_literals(suffix)),'WORDPRESS_SQL_SCOPE_INVALID')
            if statement.upper().startswith('ALTER'): require(re.fullmatch(r'(?:ENABLE|DISABLE)\s+KEYS',suffix.strip(),re.I),'WORDPRESS_SQL_SCOPE_INVALID')
            elif statement.upper().startswith('DROP'): require(not suffix.strip(),'WORDPRESS_SQL_SCOPE_INVALID')
            elif statement.upper().startswith('CREATE'): validate_create(suffix)
            elif statement.upper().startswith('INSERT'):
                # Native dumps contain scalar VALUES tuples, never executable
                # expressions, subqueries or additional target tables.
                scalar=re.sub(r"'(?:\\.|''|[^'\\])*'|\"(?:\\.|\"\"|[^\"\\])*\"",'0',suffix)
                value=r'(?:NULL|0x[0-9a-f]+|[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)'
                row=r'\(\s*'+value+r'(?:\s*,\s*'+value+r')*\s*\)'
                columns=r'(?:\(\s*`?[A-Za-z0-9_]+`?(?:\s*,\s*`?[A-Za-z0-9_]+`?)*\s*\)\s*)?'
                require(re.fullmatch(columns+r'VALUES\s*'+row+r'(?:\s*,\s*'+row+r')*',scalar.strip(),re.I),'WORDPRESS_SQL_SCOPE_INVALID')
            continue
        if re.fullmatch(r'UNLOCK\s+TABLES|COMMIT|START\s+TRANSACTION',statement,re.I): continue
        if re.match(r'^LOCK\s+TABLES\b',statement,re.I):
            tokens=statement[len('LOCK TABLES'):].strip().split(',')
            require(all(re.fullmatch(r'`?([A-Za-z0-9_]+)`?\s+(?:WRITE|READ)',token.strip(),re.I) and re.fullmatch(r'`?([A-Za-z0-9_]+)`?\s+(?:WRITE|READ)',token.strip(),re.I).group(1) in allowed for token in tokens),'WORDPRESS_SQL_SCOPE_INVALID');continue
        # Dump session metadata only: never GLOBAL/PERSIST or SQL expressions.
        if re.match(r'^SET\s+',statement,re.I):
            validate_session(statement)
            require(not re.search(r'(?i)\b(?:GLOBAL|PERSIST|PASSWORD|ROLE|DEFAULT|SELECT|LOAD|INTO|OUTFILE)\b',_without_literals(statement)),'WORDPRESS_SQL_SCOPE_INVALID')
            require(re.fullmatch(r'SET\s+(?:NAMES\s+[A-Za-z0-9_]+|(?:@?[A-Za-z0-9_]+|@@(?:SESSION\.)?[A-Za-z0-9_]+)\s*=\s*(?:@[A-Za-z0-9_]+|@@(?:SESSION\.)?[A-Za-z0-9_]+|[0-9]+|utf8mb4|utf8|latin1|binary|\'[^\']*\')(?:\s*,\s*(?:@?[A-Za-z0-9_]+|@@(?:SESSION\.)?[A-Za-z0-9_]+)\s*=\s*(?:@[A-Za-z0-9_]+|@@(?:SESSION\.)?[A-Za-z0-9_]+|[0-9]+|utf8mb4|utf8|latin1|binary|\'[^\']*\'))*)',statement,re.I),'WORDPRESS_SQL_SCOPE_INVALID');continue
        require(False,'WORDPRESS_SQL_SCOPE_INVALID')
    require(seen and seen<=allowed,'WORDPRESS_SQL_SCOPE_INVALID')



def normalize_export(data):
    # MariaDB 11 dump emits this fixed client sandbox directive. It is not SQL
    # and binary stdin does not recognize it. Only our native export removes
    # this exact leading header; external import never rewrites original bytes.
    header=b'/*M!999999\\- enable the sandbox mode */ '
    if data.startswith(header+b'\n'): return data[len(header)+1:]
    if data.startswith(header+b'\r\n'): return data[len(header)+2:]
    return data


def validate_session(statement):
    value=statement[3:].strip()
    if value.upper().startswith('NAMES '):
        require(value[6:].lower() in ('utf8','utf8mb4','latin1','binary','ascii'),'WORDPRESS_SQL_SCOPE_INVALID');return
    names={'character_set_client','character_set_results','collation_connection','time_zone','unique_checks','foreign_key_checks','sql_mode','autocommit','sql_notes','note_verbosity'}
    variables={'old_'+name:name for name in names};variables['saved_cs_client']='character_set_client'
    for assignment in value.split(','):
        pair=assignment.split('=',1);require(len(pair)==2,'WORDPRESS_SQL_SCOPE_INVALID')
        key,rhs=[item.strip().lower() for item in pair]
        if key.startswith('@') and not key.startswith('@@'):
            require(key[1:] in variables and rhs.removeprefix('@@session.').removeprefix('@@')==variables[key[1:]] and rhs.startswith('@@'),'WORDPRESS_SQL_SCOPE_INVALID');continue
        name=key.removeprefix('@@session.').removeprefix('@@')
        require(name in names,'WORDPRESS_SQL_SCOPE_INVALID')
        if rhs.startswith('@'):
            require(not rhs.startswith('@@') and variables.get(rhs[1:])==name,'WORDPRESS_SQL_SCOPE_INVALID');continue
        if name=='sql_mode':valid=rhs in ("'no_auto_value_on_zero'","''")
        elif name=='time_zone':valid=re.fullmatch(r"'[+-][0-9]{2}:[0-9]{2}'",rhs)
        elif name.startswith('character_set'):valid=rhs in ('utf8','utf8mb4','latin1','binary','ascii')
        elif name=='collation_connection':valid=re.fullmatch(r"'(?:utf8|utf8mb4|latin1|ascii)_[a-z0-9_]+'",rhs)
        else:valid=rhs in ('0','1')
        require(valid,'WORDPRESS_SQL_SCOPE_INVALID')


def validate_create(suffix):
    """Finite native dump definitions: scalar columns, local indexes, options.

    No expression productions; every token must belong to one supported rule.
    Unknown native dump variants fail before any target write.
    """
    literal=r"'(?:\\.|''|[^'\\])*'"
    identifier=r'`[A-Za-z0-9_]+`|[A-Za-z0-9_]+'
    # Lex rather than erase literals; punctuation inside values is inert.
    token=re.compile(literal+r'|`[A-Za-z0-9_]+`|[A-Za-z_][A-Za-z0-9_]*|[+-]?[0-9]+(?:\.[0-9]+)?|[(),=]')
    tokens=[];offset=0
    while offset<len(suffix):
        if suffix[offset].isspace():offset+=1;continue
        found=token.match(suffix,offset)
        require(found is not None,'WORDPRESS_SQL_SCOPE_INVALID')
        tokens.append(found[0]);offset=found.end()
    require(tokens and tokens[0]=='(','WORDPRESS_SQL_SCOPE_INVALID')
    depth=0;segments=[];start=1;end=None
    for i,t in enumerate(tokens):
        if t=='(':depth+=1
        elif t==')':
            depth-=1
            if depth==0:segments.append(tokens[start:i]);end=i+1;break
        elif t==',' and depth==1:segments.append(tokens[start:i]);start=i+1
    require(end is not None and all(segments),'WORDPRESS_SQL_SCOPE_INVALID')
    def ident(t):return re.fullmatch(identifier,t) is not None
    def scalar(t):return t.upper()=='NULL' or re.fullmatch(literal,t) or re.fullmatch(r'[+-]?[0-9]+(?:\.[0-9]+)?',t)
    columns=set();indexes=[]
    types={'tinyint','smallint','mediumint','int','integer','bigint','decimal','numeric','float','double','bit','char','varchar','binary','varbinary','tinytext','text','mediumtext','longtext','tinyblob','blob','mediumblob','longblob','date','datetime','timestamp','time','year','enum','set','bool','boolean'}
    for part in segments:
        if part[0].upper() in ('PRIMARY','UNIQUE','KEY','INDEX','FULLTEXT','SPATIAL'):
            indexes.append(part);continue
        require(len(part)>=2 and ident(part[0]) and part[1].lower() in types,'WORDPRESS_SQL_SCOPE_INVALID')
        name=part[0].strip('`');require(name not in columns,'WORDPRESS_SQL_SCOPE_INVALID');columns.add(name)
        i=2
        if i<len(part) and part[i]=='(':
            i+=1;expect=True
            while i<len(part) and part[i]!=')':
                require((re.fullmatch(r'[0-9]+',part[i]) or re.fullmatch(literal,part[i])) if expect else part[i]==',','WORDPRESS_SQL_SCOPE_INVALID')
                expect=not expect;i+=1
            require(i<len(part) and not expect,'WORDPRESS_SQL_SCOPE_INVALID');i+=1
        used=set()
        while i<len(part):
            attr=part[i].upper();require(attr not in used,'WORDPRESS_SQL_SCOPE_INVALID');used.add(attr);i+=1
            if attr=='NOT':require(i<len(part) and part[i].upper()=='NULL','WORDPRESS_SQL_SCOPE_INVALID');i+=1
            elif attr in ('NULL','UNSIGNED','ZEROFILL','AUTO_INCREMENT'):pass
            elif attr in ('DEFAULT','COMMENT'):
                require(i<len(part) and scalar(part[i]),'WORDPRESS_SQL_SCOPE_INVALID');i+=1
            elif attr in ('CHARACTER','COLLATE'):
                if attr=='CHARACTER':require(i<len(part) and part[i].upper()=='SET','WORDPRESS_SQL_SCOPE_INVALID');i+=1
                require(i<len(part) and re.fullmatch(r'[A-Za-z0-9_]+',part[i]),'WORDPRESS_SQL_SCOPE_INVALID');i+=1
            else:require(False,'WORDPRESS_SQL_SCOPE_INVALID')
    for part in indexes:
        i=1
        if part[0].upper()=='PRIMARY':require(i<len(part) and part[i].upper()=='KEY','WORDPRESS_SQL_SCOPE_INVALID');i+=1
        elif part[0].upper() in ('UNIQUE','FULLTEXT','SPATIAL'):
            if i<len(part) and part[i].upper() in ('KEY','INDEX'):i+=1
        if i<len(part) and ident(part[i]) and part[i]!='(':i+=1
        require(i<len(part) and part[i]=='(','WORDPRESS_SQL_SCOPE_INVALID');i+=1
        while True:
            require(i<len(part) and ident(part[i]) and part[i].strip('`') in columns,'WORDPRESS_SQL_SCOPE_INVALID');i+=1
            if i<len(part) and part[i]=='(':
                require(i+2<len(part) and re.fullmatch(r'[0-9]+',part[i+1]) and part[i+2]==')','WORDPRESS_SQL_SCOPE_INVALID');i+=3
            if i<len(part) and part[i].upper() in ('ASC','DESC'):i+=1
            require(i<len(part) and part[i] in (',',')'),'WORDPRESS_SQL_SCOPE_INVALID')
            if part[i]==')':i+=1;break
            i+=1
        if i<len(part):require(part[i:][0].upper()=='USING' and len(part[i:])==2 and part[i+1].upper() in ('BTREE','HASH'),'WORDPRESS_SQL_SCOPE_INVALID');i=len(part)
        require(i==len(part),'WORDPRESS_SQL_SCOPE_INVALID')
    options=tokens[end:];i=0;used=set()
    while i<len(options):
        key=options[i].upper();i+=1
        if key=='DEFAULT':require(i<len(options),'WORDPRESS_SQL_SCOPE_INVALID');key=options[i].upper();i+=1
        if key=='CHARACTER':require(i<len(options) and options[i].upper()=='SET','WORDPRESS_SQL_SCOPE_INVALID');i+=1;key='CHARSET'
        require(key in ('ENGINE','CHARSET','COLLATE','AUTO_INCREMENT','ROW_FORMAT','COMMENT','KEY_BLOCK_SIZE','PACK_KEYS','CHECKSUM','DELAY_KEY_WRITE') and key not in used,'WORDPRESS_SQL_SCOPE_INVALID');used.add(key)
        if i<len(options) and options[i]=='=':i+=1
        require(i<len(options),'WORDPRESS_SQL_SCOPE_INVALID');value=options[i];i+=1
        if key=='ENGINE':valid=value.lower() in ('innodb','myisam','aria','memory')
        elif key=='ROW_FORMAT':valid=value.upper() in ('DEFAULT','DYNAMIC','FIXED','COMPRESSED','REDUNDANT','COMPACT')
        elif key=='COMMENT':valid=re.fullmatch(literal,value)
        elif key in ('CHARSET','COLLATE'):valid=re.fullmatch(r'[A-Za-z0-9_]+',value)
        else:valid=re.fullmatch(r'[0-9]+',value)
        require(valid,'WORDPRESS_SQL_SCOPE_INVALID')

def _without_literals(text):
    return re.sub(r"'(?:\\.|''|[^'\\])*'|\"(?:\\.|\"\"|[^\"\\])*\"",'',text)


def make_archive(identity,tables,files,sql,*,max_bytes,max_members,max_unpacked_bytes=268435456,directories=None):
    directories=directories or {}
    validate_sql(sql,tables)
    require(len(files)+len(directories)+2<=max_members and sum(len(pair[0]) for pair in files.values())+len(sql)<=max_unpacked_bytes and all(len(pair[0])<=max_bytes for pair in files.values()) and len(sql)<=max_bytes,'WORDPRESS_BACKUP_TOO_LARGE')
    metadata={}
    for name,(data,mode) in files.items():
        safe_member(name);metadata[name]={'size':len(data),'sha256':digest(data),'mode':mode&0o777}
    for name,mode in directories.items():
        safe_member(name);require(name not in files and type(mode) is int and 0<=mode<=0o777,'WORDPRESS_MANIFEST_INVALID')
    manifest={'directories':directories,'format':'taskweave-wordpress-1','identity':identity,'tables':sorted(tables),'files':metadata,'sql':{'size':len(sql),'sha256':digest(sql)},'timestamp':int(time.time()),'consistency':'sequential-files-and-transactional-table-dump; external writers must be quiesced for consistency'}
    entries={'manifest.json':json.dumps(manifest,sort_keys=True).encode(),'database.sql':sql,**{'files/'+name:pair[0] for name,pair in files.items()}}
    require(sum(len(data) for data in entries.values())<=max_unpacked_bytes and all(len(data)<=max_bytes for data in entries.values()),'WORDPRESS_BACKUP_TOO_LARGE')
    target=io.BytesIO()
    with tarfile.open(fileobj=target,mode='w:gz') as archive:
        for name,mode in directories.items():
            entry=tarfile.TarInfo('files/'+name);entry.type=tarfile.DIRTYPE;entry.mode=mode;archive.addfile(entry)
        for name,data in entries.items():
            entry=tarfile.TarInfo(name);entry.size=len(data);entry.mode=0o600
            archive.addfile(entry,io.BytesIO(data))
    raw=target.getvalue();require(len(raw)<=max_bytes,'WORDPRESS_BACKUP_TOO_LARGE');return raw


def validate_archive(raw,identity,tables,*,max_bytes,max_members,max_unpacked_bytes=268435456):
    require(isinstance(raw,bytes) and len(raw)<=max_bytes,'WORDPRESS_BACKUP_TOO_LARGE')
    members={};total=0
    # Consume the complete compressed stream, including CRC/footer. Tar's
    # end-of-archive blocks alone do not prove a complete gzip envelope.
    try:
        decompressed=0
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            while block:=stream.read(65536):
                decompressed+=len(block)
                require(decompressed<=max_unpacked_bytes+max_members*2048+10240,'WORDPRESS_BACKUP_TOO_LARGE')
    except (OSError,EOFError): require(False,'WORDPRESS_ARCHIVE_INVALID')
    try:
        with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as archive:
            for entry in archive:
                safe_member(entry.name)
                require((entry.isfile() or entry.isdir() and entry.size==0) and entry.name not in members and len(members)<max_members,'WORDPRESS_ARCHIVE_MEMBER_INVALID')
                total+=entry.size;require(total<=max_unpacked_bytes and entry.size<=max_bytes,'WORDPRESS_BACKUP_TOO_LARGE')
                source=archive.extractfile(entry);data=source.read(entry.size+1) if entry.isfile() else None
                require(entry.isdir() or len(data)==entry.size,'WORDPRESS_ARCHIVE_MEMBER_INVALID');members[entry.name]=data
    except (tarfile.TarError,OSError,EOFError): require(False,'WORDPRESS_ARCHIVE_INVALID')
    try: manifest=json.loads(members['manifest.json']);sql=members['database.sql']
    except (KeyError,ValueError): require(False,'WORDPRESS_MANIFEST_INVALID')
    require(isinstance(manifest,dict) and manifest.get('format')=='taskweave-wordpress-1' and manifest.get('identity')==identity and manifest.get('tables')==sorted(tables),'WORDPRESS_BACKUP_IDENTITY_INVALID')
    require(isinstance(manifest.get('files'),dict) and isinstance(manifest.get('directories',{}),dict) and set(members)=={'manifest.json','database.sql'}|{'files/'+name for name in manifest['files']}|{'files/'+name for name in manifest.get('directories',{})},'WORDPRESS_MANIFEST_INVALID')
    require(manifest.get('sql')=={'size':len(sql),'sha256':digest(sql)},'WORDPRESS_BACKUP_INTEGRITY_FAILED')
    for name,mode in manifest.get('directories',{}).items():
        safe_member(name);require(name not in manifest['files'] and type(mode) is int and 0<=mode<=0o777 and members['files/'+name] is None,'WORDPRESS_MANIFEST_INVALID')
    files={}
    for name,metadata in manifest['files'].items():
        safe_member(name);data=members['files/'+name]
        require(isinstance(data,bytes) and isinstance(metadata,dict) and metadata.get('size')==len(data) and metadata.get('sha256')==digest(data) and type(metadata.get('mode')) is int and 0<=metadata['mode']<=0o777,'WORDPRESS_BACKUP_INTEGRITY_FAILED')
        files[name]=(data,metadata['mode'])
    validate_sql(sql,tables);return manifest,files,sql


async def site_identity(ctx,site):
    result={'site_path':str(site.site)}
    for key,name,kind in [('db_name','DB_NAME','constant'),('db_host','DB_HOST','constant'),('table_prefix','table_prefix','variable')]:
        output=await site.execute(ctx,['config','get',name,'--type='+kind]);result[key]=output['stdout'].strip()
    result['url']=(await site.execute(ctx,['option','get','siteurl','--format=json'],parse_json=True))['data']
    result['version']=(await site.execute(ctx,['core','version']))['stdout'].strip()
    # Explicit external config/content roots cannot be silently omitted.
    actual=(await site.execute(ctx,['config','path']))['stdout'].strip()
    require(await site.path(actual,site_only=True)==str(site.site)+'/wp-config.php','WORDPRESS_EXTERNAL_CONFIG_UNSUPPORTED')
    for name in ('WP_CONTENT_DIR','WPMU_PLUGIN_DIR','UPLOADS'):
        probe=await site.execute(ctx,['config','has',name,'--type=constant'],allow_exit=(1,))
        if probe['exit_code']==0:
            value=(await site.execute(ctx,['config','get',name,'--type=constant']))['stdout'].strip()
            await site.path(value,site_only=True)
        else: require(not probe['stderr'] and not probe['stdout'],'WORDPRESS_CONFIG_UNVERIFIED')
    return result


async def verified_tables(ctx,site,tables):
    from .actions import TABLES
    from jsonschema import Draft202012Validator
    require(Draft202012Validator(TABLES).is_valid(tables),'WORDPRESS_TABLE_SCOPE_INVALID')
    prefix=(await site.execute(ctx,['config','get','table_prefix','--type=variable']))['stdout'].strip()
    require(prefix and all(table.startswith(prefix) for table in tables),'WORDPRESS_TABLE_SCOPE_INVALID')
    configured=site.config.get('owned_tables')
    require(isinstance(configured,list) and set(tables)<=set(configured),'WORDPRESS_TABLE_OWNERSHIP_REQUIRED')
    available=(await site.execute(ctx,['db','tables','--all-tables','--format=csv']))['stdout'].strip().split(',')
    require(set(tables)<=set(available),'WORDPRESS_TABLE_NOT_FOUND')
    return sorted(tables)


async def export_sql(ctx,site,tables,max_bytes):
    from .commands import build_command
    path=await site.scratch(ctx)
    try:
        await site.write(path,b'',0o600)
        await site.execute(ctx,build_command('db_export',{'path':path,'tables':tables}),write=True)
        data=normalize_export(await site.read(path,max_bytes));validate_sql(data,tables);return data
    finally:
        await site.cleanup_scratch(ctx,path)


async def import_sql(ctx,site,data,tables):
    validate_sql(data,tables)
    return await site.execute(ctx,['db','import','-','--binary-mode','--skip-optimization',"--init-command=SET SESSION sql_mode='NO_AUTO_VALUE_ON_ZERO'"],stdin=data,write=True)


async def stage_bytes(ctx,name,data):
    from taskweave_process.artifacts import stage_artifact
    import tempfile
    from pathlib import Path
    # stage_artifact retains protected credential-bearing bytes, never inline.
    with tempfile.TemporaryDirectory(prefix='taskweave-wp-artifact-') as directory:
        path=Path(directory,name);path.write_bytes(data);path.chmod(0o600)
        return await stage_artifact(ctx,directory,name,max_bytes=len(data) or 1)


async def backup_site(ctx,config:dict,inputs:dict)->dict:
    from .transport import SiteTransport
    own=not isinstance(config,SiteTransport);site=SiteTransport(config) if own else config
    try:
        if site.site is None: await site.open(ctx)
        if own: site.start(ctx,'backup',inputs.get('role','default'),inputs)
        tables=await verified_tables(ctx,site,inputs['tables']);identity=await site_identity(ctx,site)
        limit=inputs.get('max_bytes',16777216);members=inputs.get('max_members',10000)
        sql=await export_sql(ctx,site,tables,limit)
        expanded=inputs.get('max_unpacked_bytes',268435456)
        files=await site.files(expanded-len(sql),members-2,limit)
        raw=make_archive(identity,tables,files,sql,max_bytes=limit,max_members=members,max_unpacked_bytes=expanded,directories=site.snapshot_directories)
        artifact=await stage_bytes(ctx,'wordpress-site.tar.gz',raw)
        return {'completion':'completed','result':{'files':len(files),'tables':tables,'package_sha256':digest(raw),'consistency':'requires external writers quiesced'},'steps':[{'stage':'database_export','completion':'completed'},{'stage':'files_archive','completion':'completed'}],'artifact':artifact}
    finally:
        if own: await site.close()


async def restore_site(ctx,config:dict,inputs:dict)->dict:
    from .transport import SiteTransport
    own=not isinstance(config,SiteTransport);site=SiteTransport(config) if own else config
    try:
        if site.site is None: await site.open(ctx)
        if own: site.start(ctx,'restore',inputs.get('role','default'),inputs)
        limit=inputs.get('max_bytes',16777216);raw=await site.read(inputs['path'],limit)
        require(digest(raw)==inputs['checksum'],'WORDPRESS_BACKUP_INTEGRITY_FAILED')
        tables=await verified_tables(ctx,site,inputs['tables']);identity=await site_identity(ctx,site)
        manifest,files,sql=validate_archive(raw,identity,tables,max_bytes=limit,max_members=inputs.get('max_members',10000),max_unpacked_bytes=inputs.get('max_unpacked_bytes',268435456))
        # Verify every destination before any destructive write.
        for name in list(files)+list(manifest.get('directories',{})): await site.path(str(site.site)+'/'+name,must_exist=False,site_only=True)
        stages=[]
        entry=site.evidence.dispatch(ctx,'restore',site.role,'files_overlay') if site.evidence else None
        if entry:
            entry['completed_files']=0;entry['completed_directories']=0
        for name in sorted(manifest.get('directories',{}),key=lambda item:item.count('/')):
            if entry: entry['pending_directory_sha256']=digest(name.encode())
            await site.mkdir(str(site.site)+'/'+name)
            if entry:
                entry['completed_directories']+=1;entry['completion']='partial';entry.pop('pending_directory_sha256',None)
        for name,(data,mode) in sorted(files.items()):
            if entry:
                entry['pending_file_sha256']=digest(name.encode())
            await site.write(str(site.site)+'/'+name,data,mode)
            require(digest(await site.read(str(site.site)+'/'+name,limit))==digest(data),'WORDPRESS_RESTORE_VERIFY_FAILED')
            if entry:
                entry['completed_files']+=1
                entry['completion']='partial'
                entry.pop('pending_file_sha256',None)
        for name,mode in sorted(manifest.get('directories',{}).items(),key=lambda item:-item[0].count('/')):
            await site.mkdir(str(site.site)+'/'+name,mode)
        if entry: entry['completion']='completed'
        stages.append({'stage':'files_overlay','completion':'completed','count':len(files)})
        path=await site.scratch(ctx)
        try:
            await site.write(path,sql)
            await import_sql(ctx,site,await site.read(path,limit),tables)
            await verified_tables(ctx,site,tables)
            stages.append({'stage':'database_import','completion':'completed'})
        finally:
            await site.cleanup_scratch(ctx,path)
        return {'completion':'completed','result':{'files':len(files),'tables':tables,'mode':'overlay-and-table-import','atomic':False},'steps':stages}
    except BaseException as exc:
        if site.evidence: site.evidence.capture(ctx,exc)
        raise
    finally:
        if own: await site.close()
