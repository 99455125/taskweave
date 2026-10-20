"""Verify complete official exports in an isolated temporary workspace; no business calls."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from taskweave.application.service import Application

ROOT=Path(__file__).resolve().parents[2]
OUT=Path('/Users/xiaojuju/taskweave/local-selftest-20261016')

def main():
    receipt=json.loads((OUT/'authoring-receipt.json').read_text())
    checked=[]
    with tempfile.TemporaryDirectory(prefix='tw-local-roundtrip-') as directory:
        home=Path(directory)
        shutil.copy(Path(receipt['workspace'])/'plugins.json',home/'plugins.json')
        with Application(home) as app:
            for entry in receipt['tasks']:
                path=Path(entry['export']);package=json.loads(path.read_text())
                imported=app.dispatch('task.import',{'package':package})
                restored=app.dispatch('task.export',{'task_id':imported['task_id']})
                assert restored==package, entry['key']+' imported export differs, including context items/views'
                assert len({g['step_key'] for g in restored['contexts']})==len(restored['steps']),entry['key']+' missing step evidence'
                coded=[s for s in app.dispatch('step.list',{'task_id':imported['task_id']}) if s['step_content']]
                for step in coded:
                    compile(step['step_content'], entry['key'] + '/' + step['name'], 'exec')
                    assert app.dispatch('step.validate',{'step_id':step['step_id']})['valid'],step['name']
                checked.append({'key':entry['key'],'steps':len(restored['steps']),'coded_valid':len(coded),
                                'context_groups':len(restored['contexts']),'captures':sum(len(g['captures']) for g in restored['contexts']),
                                'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'roundtrip_equal':True})
    result={'purpose':'官方导出→隔离临时工作空间导入→再次官方导出；逐字段比较含所有素材预览，不执行业务操作。','tasks':checked,
            'counts':{'tasks':len(checked),'steps':sum(c['steps'] for c in checked),'coded_valid':sum(c['coded_valid'] for c in checked),'context_groups':sum(c['context_groups'] for c in checked),'captures':sum(c['captures'] for c in checked)}}
    (ROOT/'examples/reinsurance-local-selftest/package-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result['counts'],ensure_ascii=False))

if __name__=='__main__':main()
