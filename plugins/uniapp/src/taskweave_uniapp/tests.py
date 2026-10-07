"""Existing Jest/native test execution and complete THISRUN reports."""
import json
from pathlib import Path
import re
import shlex
import time
import uuid
from .redaction import representations,mask_data
from .project import require,inspect_project,path_inside,read_json,read_bytes,test_schema,snapshot
from .build import command_environment,node_ready,execute_command
from taskweave_process.artifacts import _stage_bytes
from taskweave_process.runner import redact_text


def report_area(config,*,exists=False):
    value=config.get('report_root');require(isinstance(value,str) and value,'UNIAPP_PREPARATION_REQUIRED','Explicit report_root required')
    raw=Path(value).expanduser();base=raw.resolve(strict=exists) if raw.is_absolute() else path_inside(config['project_root'],value,exists=exists)
    require(base!=Path(base.anchor),'UNIAPP_PATH_INVALID','Filesystem root is not an allowed report area')
    if exists:require(base.is_dir(),'UNIAPP_PATH_INVALID')
    return base

def report_snapshot(base):
    return snapshot(base,'.') if base.exists() else {}

def verify_jest_script(script):
    require(isinstance(script,str) and not any(c in script for c in (';','|','&','`','$','\n','>','<')),'UNIAPP_PREPARATION_REQUIRED','Jest script must forward directly without shell control syntax')
    try:tokens=shlex.split(script)
    except ValueError:require(False,'UNIAPP_PREPARATION_REQUIRED')
    if tokens and tokens[0] in ('cross-env','./node_modules/.bin/cross-env'):
        tokens=tokens[1:]
        while tokens and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*=[A-Za-z0-9_./:-]+',tokens[0]):tokens=tokens[1:]
    require(bool(tokens) and tokens[0] in ('jest','./node_modules/.bin/jest'),'UNIAPP_PREPARATION_REQUIRED','Configure an existing direct Jest script')
    require(not any(t.startswith(('--outputFile','--testNamePattern','--runTestsByPath','--json','--watch','--listTests','--showConfig','--help','--version','--testPathPattern')) for t in tokens[1:]),'UNIAPP_PREPARATION_REQUIRED','Existing Jest script conflicts with THISRUN reporting/filtering')
    return True

def validate_jest_report(report,root,start,end,*,file=None,case=None):
    code='UNIAPP_TEST_REPORT_INVALID';require(isinstance(report,dict),code)
    fields=('numTotalTests','numPassedTests','numFailedTests','numPendingTests','numTodoTests','numTotalTestSuites','numPassedTestSuites','numFailedTestSuites','numPendingTestSuites','numRuntimeErrorTestSuites')
    require(all(type(report.get(k)) is int and report[k]>=0 for k in fields),code)
    require(report.get('success') is True and report.get('wasInterrupted') is False,code)
    require(type(report.get('startTime')) in (int,float) and start<=report['startTime']<=end,code)
    require(report['numTotalTests']==sum(report[k] for k in ('numPassedTests','numFailedTests','numPendingTests','numTodoTests')) and report['numPassedTests']>0,code)
    require(report['numFailedTests']==report['numFailedTestSuites']==report['numRuntimeErrorTestSuites']==0,code)
    require(report['numTotalTestSuites']==sum(report[k] for k in ('numPassedTestSuites','numFailedTestSuites','numPendingTestSuites')),code)
    rows=report.get('testResults');require(isinstance(rows,list) and len(rows)==report['numTotalTestSuites'],code)
    observed={'passed':0,'failed':0,'pending':0,'todo':0};suites={'passed':0,'failed':0,'pending':0};selected=0
    for row in rows:
        require(isinstance(row,dict) and row.get('status') in ('passed','focused','failed','pending','skipped') and isinstance(row.get('name'),str),code)
        suite_status={'focused':'passed','skipped':'pending'}.get(row['status'],row['status']);suites[suite_status]+=1;name=Path(row['name']);require(name.is_absolute(),code)
        try:relative=str(name.resolve().relative_to(Path(root).resolve()))
        except (ValueError,OSError):raise __import__('taskweave.plugins.sdk',fromlist=['PluginError']).PluginError(code)
        require(not file or relative==file,code)
        assertions=row.get('assertionResults');require(isinstance(assertions,list),code)
        require(type(row.get('startTime')) in (int,float) and type(row.get('endTime')) in (int,float) and start<=row['startTime']<=row['endTime']<=end,code)
        require(isinstance(row.get('message'),str) and not row['message'],code)
        for assertion in assertions:
            require(isinstance(assertion,dict) and assertion.get('status') in observed and isinstance(assertion.get('fullName'),str),code)
            status=assertion['status'];observed[status]+=1
            if status=='passed':require(not case or assertion['fullName']==case,code);selected+=1
    require(observed['passed']==report['numPassedTests'] and observed['failed']==report['numFailedTests'] and observed['pending']==report['numPendingTests'] and observed['todo']==report['numTodoTests'],code)
    require(suites['passed']==report['numPassedTestSuites'] and suites['pending']==report['numPendingTestSuites'],code)
    require(selected>0,code)
    if 'snapshot' in report:require(report['snapshot'].get('failure') is False and report['snapshot'].get('unmatched',0)==0,code)
    return {'passed':True,'executed':observed['passed'],'pending':observed['pending'],'todo':observed['todo'],'suites':suites['passed']}

async def run_tests(ctx,config,inputs,session=None):
    require(session is not None);platform=inputs['platform'];metadata=inspect_project(ctx,config);safe,env=command_environment(ctx,config)
    report_root=config.get('report_root');require(isinstance(report_root,str),'UNIAPP_PREPARATION_REQUIRED','Explicit report_root required')
    directory=report_area(config);file=inputs.get('file');case=inputs.get('case')
    if file:path_inside(session.root,file)
    run_id=str(uuid.uuid4());report_path=None;runner_version=None
    if config.get('test_scripts',{}).get(platform) is not None:
        runner_version=await node_ready(safe,config,metadata,env);spec=config['test_scripts'][platform];script=spec.get('script')
        require(script in metadata['scripts'] and spec.get('forwards_jest_args') is True,'UNIAPP_PREPARATION_REQUIRED','Verified direct Jest script forwarding required')
        verify_jest_script(metadata['scripts'][script]);package=read_json(session.root,'node_modules/jest/package.json');require(package.get('name')=='jest','UNIAPP_PREPARATION_REQUIRED');runner_version=package.get('version')
        require(directory.exists(),'UNIAPP_PREPARATION_REQUIRED','Prepare report directory explicitly')
        report_path=directory/(run_id+'.json');args=['run',script,'--','--runInBand','--json','--outputFile',str(report_path)]
        if file:args+=['--runTestsByPath',file]
        if case:args+=['--testNamePattern','^'+re.escape(case)+'$']
        executable=config['package_manager'];jest_exit='same_as_cli'
    else:
        require(config['kind']=='hbuilderx','UNIAPP_PREPARATION_REQUIRED','Existing configured Jest test script required')
        package=test_schema(config);lib=config.get('native_test_lib_root',str(Path(config['test_plugin_root']).parent/'hbuilderx-for-uniapp-test-lib'));require((Path(lib)/'node_modules/jest/bin/jest.js').is_file(),'UNIAPP_PREPARATION_REQUIRED','Prepare native test-library dependencies explicitly; runtime must not initialize/install them');command='uniapp.test '+('mp-weixin' if platform=='mp-weixin' else 'web-chrome')
        commands=package['contributes']['clicommands'];row=next((r for r in commands if r.get('name')==command),None)
        require(row is not None and any(a.get('name')=='project' and a.get('type')=='string' for a in row.get('args',[])),'UNIAPP_PREPARATION_REQUIRED')
        require(case is None,'UNIAPP_PREPARATION_REQUIRED','Native test schema has no case-name flag; configure direct Jest script')
        require(config.get('owned_test_project') is True and (Path(session.root)/'jest.config.js').is_file() and (Path(session.root)/'env.js').is_file(),'UNIAPP_PREPARATION_REQUIRED','Explicit independently prepared owned test project required; native runner may rewrite Jest config')
        require(not metadata['preparation_required'],'UNIAPP_PREPARATION_REQUIRED');executable=config['hbuilderx_path'];args=['uniapp.test',command.split(' ',1)[1],'--project',session.root]
        if file:
            require(any(a.get('name')=='testcaseFile' and a.get('type')=='string' for a in row.get('args',[])),'UNIAPP_PREPARATION_REQUIRED');args+=['--testcaseFile',file]
        runner_version=package.get('version');jest_exit='unavailable'
    before=report_snapshot(directory);started=time.time_ns();record={'test_run_id':run_id,'started_at':started,'project_root':session.root,'platform':platform,'file':file,'case':case,'state':'running','before':before,'report_root':report_root,'report_root_real':str(directory)}
    session.tests[run_id]=record
    try:
        result,entry=await execute_command(session,safe,'run_tests',executable,args,env,inputs);finished=time.time_ns();record.update(command=result,finished_at=finished)
        require(result['exit_code']==0,'UNIAPP_TEST_COMMAND_FAILED')
        if report_path is None:
            require(not result['stdout_truncated'] and not result['stderr_truncated'],'UNIAPP_TEST_REPORT_MISSING')
            matches=re.findall(r'测试报告[:：]\s*([^\r\n]+\.json)',result['stdout']+result['stderr']);require(len(matches)==1,'UNIAPP_TEST_REPORT_MISSING');report_path=path_inside(directory,matches[0].strip())
        report_path=path_inside(directory,str(report_path));after=report_snapshot(directory);relative=str(report_path.relative_to(directory))
        require(relative in after and after[relative]!=before.get(relative) and started<=after[relative]['mtime_ns']<=finished,'UNIAPP_TEST_REPORT_STALE')
        try:report=json.loads(read_bytes(directory,str(report_path)).decode('utf-8'))
        except (ValueError,UnicodeError):require(False,'UNIAPP_TEST_REPORT_INVALID')
        summary=validate_jest_report(report,session.root,started//1000000,finished//1000000,file=file,case=case)
        record.update(state='verified',report_path=str(report_path),after=after,summary=summary)
        return {'test_run_id':run_id,'started_at':started,'passed':True,'summary':summary,'command':result,'cli_exit':result['exit_code'],'jest_exit':result['exit_code'] if jest_exit=='same_as_cli' else 'unavailable','runner_version':runner_version,'report_path':str(report_path)}
    except BaseException:record['state']='failed';raise

async def collect_report(ctx,config,inputs,session=None):
    require(session is not None);root=Path(session.root);allowed=config.get('report_root');require(isinstance(allowed,str),'UNIAPP_PREPARATION_REQUIRED')
    base=report_area(config,exists=True);budget=inputs.get('max_bytes',16*1024*1024);total=0;files=[]
    record=None
    if inputs.get('test_run_id'):
        record=session.tests.get(inputs['test_run_id']);require(record is not None and record['state']=='verified','UNIAPP_TEST_IDENTITY_INVALID')
    for value in inputs['paths']:
        candidate=Path(value) if Path(value).is_absolute() else (base/value if Path(allowed).is_absolute() else root/value);source=path_inside(base,str(candidate));require(source.suffix.lower() in ('.json','.log','.txt','.png','.jpg','.jpeg'),'UNIAPP_REPORT_TYPE_INVALID')
        data=read_bytes(base,str(source),budget-total);total+=len(data);require(total<=budget,'UNIAPP_ARTIFACT_LIMIT');files.append((source,data))
    if record:require(str(Path(record['report_path'])) in [str(p) for p,_ in files] and str(base)==record['report_root_real'] and report_snapshot(base).get(str(Path(record['report_path']).relative_to(base)))==record['after'].get(str(Path(record['report_path']).relative_to(base))),'UNIAPP_TEST_REPORT_CHANGED')
    artifacts=[]
    secrets=[ctx.resolve_secret(ref) for ref in config.get('env_secret_refs',{}).values()]
    prepared=[];staged_bytes=0
    for source,data in files:
        if source.suffix.lower() in ('.json','.txt','.log'):
            try:
                text=data.decode('utf-8')
                if source.suffix.lower()=='.json' and secrets:
                    try:text=json.dumps(mask_data(json.loads(text),representations(secrets)),ensure_ascii=False)
                    except (ValueError,RecursionError):require(False,'UNIAPP_JSON_INVALID')
                data=redact_text(text,representations(secrets)).encode('utf-8')
            except UnicodeError:require(False,'UNIAPP_REPORT_ENCODING_INVALID')
        staged_bytes+=len(data);require(staged_bytes<=budget,'UNIAPP_ARTIFACT_LIMIT');prepared.append((redact_text(source.name,representations(secrets)),data))
    for name,data in prepared:artifacts.append(await _stage_bytes(ctx,name,data))
    return {'artifacts':artifacts,'total_bytes':total,'test_run_verified':record is not None}
