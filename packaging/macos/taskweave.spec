"""Standalone macOS bundle, with all first-party plugins and Chromium."""

import os
from pathlib import Path
import runpy
from PyInstaller.utils.hooks import collect_all, copy_metadata

ROOT = Path(SPECPATH).parents[1]
settings = runpy.run_path(str(ROOT / 'scripts/build_macos.py'))
modules = list(settings['PLUGINS'].values())
datas, binaries, hiddenimports = [], [], []
for package in ['taskweave', *modules, 'nicegui', 'webview', 'playwright', 'ddddocr', 'onnxruntime', 'cv2', 'tzdata', 'pypdfium2', 'pypdfium2_raw', 'openpyxl', 'et_xmlfile', 'defusedxml', 'ruamel.yaml']:
    data, binary, hidden = collect_all(package)
    datas += data
    binaries += binary
    hiddenimports += hidden
for distribution in ['taskweave', *[m.replace('_', '-') for m in modules], 'nicegui', 'pywebview', 'playwright', 'pypdfium2', 'openpyxl', 'et-xmlfile', 'defusedxml', 'ruamel-yaml']:
    datas += copy_metadata(distribution)

a = Analysis(
    [str(ROOT / 'packaging/macos/taskweave_launcher.py')],
    pathex=[str(ROOT / 'src')], binaries=binaries, datas=datas,
    hiddenimports=hiddenimports, hookspath=[], runtime_hooks=[],
    excludes=['torch', 'tensorflow', 'matplotlib', 'IPython', 'pytest'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='TaskWeave',
          debug=False, strip=False, upx=False, console=False, target_arch='arm64')
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='TaskWeave')
app = BUNDLE(coll, name='TaskWeave.app', icon=str(ROOT / 'packaging/macos/TaskWeave.icns'),
             bundle_identifier='local.taskweave.desktop', version='0.1.0',
             info_plist={'CFBundleDisplayName': 'TaskWeave',
                         'NSHighResolutionCapable': True,
                         'NSRequiresAquaSystemAppearance': False})
