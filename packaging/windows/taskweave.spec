from pathlib import Path

from PyInstaller.utils.hooks import collect_all, copy_metadata


ROOT = Path(SPECPATH).parents[1]

packages = [
    "taskweave",
    "taskweave_playwright",
    "taskweave_sample",
    "taskweave_captcha",
    "taskweave_tidb",
    "nicegui",
    "webview",
    "playwright",
    "pymysql",
    "ddddocr",
    "onnxruntime",
    "cv2",
]

datas = []
binaries = []
hiddenimports = []
for package in packages:
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

for distribution in [
    "taskweave",
    "taskweave-playwright",
    "taskweave-sample",
    "taskweave-captcha",
    "taskweave-tidb",
    "nicegui",
    "pywebview",
    "playwright",
]:
    datas += copy_metadata(distribution)

analysis = Analysis(
    [str(ROOT / "packaging" / "windows" / "taskweave_launcher.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="TaskWeave",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="TaskWeave",
)
