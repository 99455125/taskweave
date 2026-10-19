"""Check a frozen app in a clean environment and prepare an isolated UI copy."""

import argparse
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--app', type=Path, default=Path('dist/macos/TaskWeave.app'))
    parser.add_argument('--out', type=Path, default=Path('build/macos/acceptance'))
    args = parser.parse_args()
    app, out = args.app.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    clean_env = {key: os.environ[key] for key in ('HOME', 'TMPDIR', 'USER', 'LOGNAME') if key in os.environ}
    clean_env.update(PATH='/usr/bin:/bin:/usr/sbin:/sbin', LANG='en_US.UTF-8')
    with tempfile.TemporaryDirectory() as cwd:
        result = subprocess.run([str(app / 'Contents/MacOS/TaskWeave'), '--diagnose'],
                                cwd=cwd, env=clean_env, capture_output=True, text=True, timeout=120)
    (out / 'diagnose.stdout').write_text(result.stdout)
    (out / 'diagnose.stderr').write_text(result.stderr)
    if result.returncode:
        raise RuntimeError(f'Frozen diagnostics failed ({result.returncode}); see {out}')
    report = json.loads(result.stdout)
    if not report['frozen'] or not report['browser_bundled'] or len(report['plugins']) != 11:
        raise RuntimeError('Frozen inventory is incomplete')
    target = out / 'TaskWeave.app'
    if target.exists():
        raise RuntimeError('UI copy already exists; use a fresh --out directory')
    shutil.copytree(app, target, symlinks=True)
    plist = target / 'Contents/Info.plist'
    data = plistlib.loads(plist.read_bytes())
    data['LSEnvironment'] = {'TASKWEAVE_HOME': str(out / 'workspace')}
    plist.write_bytes(plistlib.dumps(data))
    subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', str(target)], check=True)
    report['ui_app'] = str(target)
    report['ui_workspace'] = str(out / 'workspace')
    (out / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
