"""Build the standalone arm64 app without changing the development environment."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PLUGINS = {
    'playwright': 'taskweave_playwright', 'ocr': 'taskweave_ocr',
    'tidb': 'taskweave_tidb', 'utility': 'taskweave_utility',
    'file': 'taskweave_file', 'process': 'taskweave_process', 'ssh': 'taskweave_ssh',
    'baota_dashboard': 'taskweave_baota_dashboard', 'wordpress': 'taskweave_wordpress',
    'uniapp': 'taskweave_uniapp', 'wechat_dev': 'taskweave_wechat_dev',
}


def validate_inventory(found, chromium):
    missing = set(PLUGINS) - set(found)
    if missing:
        raise RuntimeError('Missing plugins: ' + ', '.join(sorted(missing)))
    if not chromium.is_file():
        raise RuntimeError('Bundled Chromium executable is missing')


def require_resources(root):
    required = [
        'taskweave/infrastructure/sql', 'nicegui/static',
        'ddddocr/common.onnx', 'taskweave_wechat_dev/node/bridge.cjs',
        'taskweave_wechat_dev/node/release.cjs', 'taskweave_wechat_dev/node/ci/package-lock.json',
        'browsers',
    ]
    for relative in required:
        if not (root / relative).exists():
            raise RuntimeError('Missing bundled resource: ' + relative)


def release_manifest(version, plugins):
    return {
        'product': 'TaskWeave', 'version': version, 'platform': 'macos-arm64',
        'built_at_utc': datetime.now(timezone.utc).isoformat(),
        'plugins': plugins, 'browser': 'bundled Playwright Chromium',
        'external_tools': ['Node and configured SDKs', 'HBuilderX', 'WeChat developer tools', 'remote services'],
    }


def bundle_browsers(cache, app):
    # Preserve Chromium's signed nested app/framework layout instead of letting
    # PyInstaller reclassify and rewrite individual browser Mach-O files.
    destination = app / 'Contents/Resources/browsers'
    shutil.copytree(cache, destination, symlinks=True)


def make_icon(path):
    from PIL import Image, ImageDraw
    image = Image.new('RGBA', (1024, 1024))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((32, 32, 992, 992), radius=215, fill='#2563eb')
    for y in (310, 470, 630):
        draw.line([(260, y), (512, y + 160), (764, y)], fill='white', width=58, joint='curve')
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format='ICNS')


def main():
    if sys.platform != 'darwin' or platform.machine() != 'arm64':
        raise RuntimeError('Build on macOS arm64')
    uv = shutil.which('uv')
    if not uv:
        raise RuntimeError('Build machine requires uv')
    build = ROOT / 'build/macos'
    dist = ROOT / 'dist/macos'
    build.mkdir(parents=True, exist_ok=True)
    dist.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.pop('PYTHONPATH', None)
    env['UV_PROJECT_ENVIRONMENT'] = str(build / 'venv')
    env['PLAYWRIGHT_BROWSERS_PATH'] = str(build / 'browsers')
    env['TASKWEAVE_BUILD_BROWSERS'] = str(build / 'browsers')
    subprocess.run([uv, 'sync', '--locked', '--all-extras', '--group', 'build', '--python', '3.12'], cwd=ROOT, env=env, check=True)
    python = build / 'venv/bin/python'
    subprocess.run([str(python), '-m', 'playwright', 'install', 'chromium'], cwd=ROOT, env=env, check=True)
    inspection = subprocess.check_output([str(python), '-c', '''
import importlib.metadata as m, json
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
 print(json.dumps({'plugins': {e.name:e.dist.version for e in m.entry_points(group='taskweave.plugins')}, 'version':m.version('taskweave'), 'chromium':p.chromium.executable_path}))
'''], cwd=ROOT, env=env, text=True)
    inventory = json.loads(inspection)
    validate_inventory(inventory['plugins'], Path(inventory['chromium']))
    make_icon(ROOT / 'packaging/macos/TaskWeave.icns')
    subprocess.run([str(python), '-m', 'PyInstaller', '--noconfirm',
                    '--distpath', str(dist), '--workpath', str(build / 'pyinstaller'),
                    str(ROOT / 'packaging/macos/taskweave.spec')], cwd=ROOT, env=env, check=True)
    app = dist / 'TaskWeave.app'
    bundle_browsers(build / 'browsers', app)
    require_resources(app / 'Contents/Resources')
    subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', str(app)], check=True)
    release = release_manifest(inventory['version'], inventory['plugins'])
    (dist / 'release.json').write_text(json.dumps(release, ensure_ascii=False, indent=2) + '\n')
    archive = dist / 'TaskWeave-macos-arm64.zip'
    subprocess.run(['/usr/bin/ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(app), str(archive)], check=True)
    with archive.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    (dist / (archive.name + '.sha256')).write_text(digest + '  ' + archive.name + '\n')
    print('Built:', app)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
