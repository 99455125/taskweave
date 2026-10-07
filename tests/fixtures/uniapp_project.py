"""Owned Node protocol projects; never represent real uni-app compiler acceptance."""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

def project(root, *, src=False):
    base=root/'src' if src else root;base.mkdir(parents=True,exist_ok=True)
    (base/'manifest.json').write_text('{/* comment */"appid":"__UNI__FIXTURE","vueVersion":"2","mp-weixin":{"appid":"touristappid"},}')
    (base/'pages.json').write_text('{"pages":[{"path":"pages/index/index"}],"subPackages":[{"root":"pkg","pages":[{"path":"second"}]}]}')
    (base/'App.vue').write_text('<template/>')
    (root/'package.json').write_text(json.dumps({'engines':{'node':'>=22 <23'},'scripts':{'build:mp-weixin':'node build.cjs','build:h5':'node build.cjs','test:mp-weixin':'jest'},'devDependencies':{'jest':'29.7.0'}}))
    (root/'node_modules/jest').mkdir(parents=True)
    (root/'node_modules/jest/package.json').write_text('{"name":"jest","version":"29.7.0"}')
    (root/'build.cjs').write_text('''const fs=require('fs');const path=require('path');
if(process.env.MODE==='delay'){setTimeout(()=>{},3000);}
const d=process.env.UNI_OUTPUT_DIR;fs.mkdirSync(d,{recursive:true});
if(process.env.MODE!=='noop'){
 const files=process.env.UNI_PLATFORM==='h5'?{'index.html':'<script src="assets/app.js"></script>','assets/app.js':'console.log("ok")'}:{'app.json':JSON.stringify({pages:['pages/index/index'],subPackages:[{root:'pkg',pages:['second']}]}),'project.config.json':JSON.stringify({appid:'touristappid',miniprogramRoot:'./'}),'app.js':'App({})','app.wxss':'page{}','pages/index/index.js':'Page({})','pages/index/index.wxml':'<view/>','pages/index/index.json':'{}','pkg/second.js':'Page({})','pkg/second.wxml':'<view/>','pkg/second.json':'{}'};
 for(const [f,v]of Object.entries(files)){fs.mkdirSync(path.dirname(path.join(d,f)),{recursive:true});fs.writeFileSync(path.join(d,f),v);}
}
console.log('BUILD_COMPLETE');if(process.env.MODE==='fail')process.exit(9);
''')
    return base

def install_jest_report_protocol(root):
    """A complete Jest JSON boundary double, not genuine Jest execution."""
    directory=root/'node_modules/.bin';directory.mkdir()
    script=directory/'jest'
    script.write_text('''#!/usr/bin/env node
const fs=require('fs'),path=require('path');const args=process.argv.slice(2);const get=n=>args[args.indexOf(n)+1];
if(process.env.REPORT_MODE==='missing')process.exit(0);
const file=get('--runTestsByPath')||'a.test.js';const name='selected case';const selected=get('--testNamePattern');
const start=Date.now()-(process.env.REPORT_MODE==='stale'?10000:0);const fail=process.env.REPORT_MODE==='failed';
const report={success:!fail,wasInterrupted:false,startTime:start,numTotalTests:2,numPassedTests:fail?0:1,numFailedTests:fail?1:0,numPendingTests:1,numTodoTests:0,numTotalTestSuites:1,numPassedTestSuites:fail?0:1,numFailedTestSuites:fail?1:0,numPendingTestSuites:0,numRuntimeErrorTestSuites:0,testResults:[{name:path.resolve(file),status:fail?'failed':'passed',startTime:start,endTime:start,message:fail?'failed':'',assertionResults:[{fullName:name,status:fail?'failed':'passed'},{fullName:'unselected',status:'pending'}]}]};
fs.writeFileSync(get('--outputFile'),JSON.stringify(report));fs.writeFileSync('.reports/forwarded.json',JSON.stringify({file,selected}));
''');script.chmod(0o755);(root/'a.test.js').write_text('// protocol input file');(root/'.reports').mkdir()

def compatible_test_node():
    """Explicit prerequisite wins; discovery accepts verified Node22 only."""
    explicit=os.environ.get('TW_UNIAPP_TEST_NODE')
    candidates=[Path(explicit).expanduser()] if explicit else ([Path(shutil.which('node'))] if shutil.which('node') else [])+sorted((Path.home()/'.nvm/versions/node').glob('v22.*/bin/node'),reverse=True)
    for candidate in candidates:
        if not candidate.is_file():continue
        try:result=subprocess.run([str(candidate),'--version'],capture_output=True,text=True,timeout=2)
        except (OSError,subprocess.TimeoutExpired):continue
        if result.returncode==0 and re.fullmatch(r'v22\.\d+\.\d+\s*',result.stdout):return str(candidate.resolve())
    raise AssertionError('Prepare compatible Node22 and set TW_UNIAPP_TEST_NODE to its absolute executable; no automatic install or implementation skip')
