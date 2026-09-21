param(
    [string]$WebView2Runtime = $env:WEBVIEW2_FIXED_RUNTIME_DIR,
    [string]$WebView2Cab = $env:WEBVIEW2_FIXED_RUNTIME_CAB,
    [switch]$SkipWebView2
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$BuildRoot = Join-Path $Root "build/windows"
$BrowserCache = Join-Path $BuildRoot "playwright-browsers"
$DistRoot = Join-Path $Root "dist/windows"
$AppRoot = Join-Path $DistRoot "TaskWeave"
$ZipPath = Join-Path $DistRoot "TaskWeave-portable-win-x64.zip"

if ($PSVersionTable.PSVersion -lt [Version]"5.1") {
    throw "构建脚本需要 Windows PowerShell 5.1 或 PowerShell 7。"
}
$RunningOnWindows = $env:OS -eq "Windows_NT"
if (-not $RunningOnWindows) {
    throw "Windows 便携包必须在 Windows x64 上构建。"
}
if (-not [Environment]::Is64BitOperatingSystem) {
    throw "仅支持 Windows x64 构建机。"
}
if (-not [Environment]::Is64BitProcess) {
    throw "请使用 64 位 PowerShell 构建，当前 PowerShell 是 32 位进程。"
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "构建机缺少 uv。请先安装 uv；目标机不需要 uv 或 Python。"
}
if (-not $SkipWebView2 -and -not $WebView2Runtime -and -not $WebView2Cab) {
    throw "请用 -WebView2Cab 指定官方 Fixed Version x64 CAB，或用 -WebView2Runtime 指定已解压目录。"
}
if (-not $SkipWebView2 -and $WebView2Cab -and -not (Test-Path $WebView2Cab -PathType Leaf)) {
    throw "WebView2 CAB 不存在：$WebView2Cab"
}
if (-not $SkipWebView2 -and -not $WebView2Cab -and -not (Test-Path $WebView2Runtime -PathType Container)) {
    throw "WebView2 已解压目录不存在：$WebView2Runtime"
}

Remove-Item $BuildRoot -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $DistRoot -Recurse -Force -ErrorAction SilentlyContinue
New-Item $BrowserCache -ItemType Directory -Force | Out-Null
New-Item $DistRoot -ItemType Directory -Force | Out-Null

if (-not $SkipWebView2) {
    if ($WebView2Cab) {
        $ExpandedWebView2 = Join-Path $BuildRoot "webview2-fixed"
        New-Item $ExpandedWebView2 -ItemType Directory -Force | Out-Null
        & "$env:SystemRoot\System32\expand.exe" $WebView2Cab "-F:*" $ExpandedWebView2
        if ($LASTEXITCODE -ne 0) {
            throw "WebView2 CAB 解压失败，退出码：$LASTEXITCODE"
        }
        $WebView2Runtime = $ExpandedWebView2
    }
    $WebViewExecutable = Get-ChildItem $WebView2Runtime -Recurse -Filter "msedgewebview2.exe" -File |
        Select-Object -First 1
    if (-not $WebViewExecutable) {
        throw "WebView2 内容中没有 msedgewebview2.exe，请提供完整的 Fixed Version x64 Runtime。"
    }
    $WebView2Runtime = $WebViewExecutable.Directory.FullName
}

Push-Location $Root
try {
    & uv sync --locked --group build --extra gui --extra browser --extra ocr --extra database
    if ($LASTEXITCODE -ne 0) {
        throw "uv sync 失败，退出码：$LASTEXITCODE"
    }
    $PythonBits = & uv run python -c "import struct; print(struct.calcsize('P') * 8)"
    if ($LASTEXITCODE -ne 0) {
        throw "检查 Python 架构失败，退出码：$LASTEXITCODE"
    }
    if (($PythonBits -join "").Trim() -ne "64") {
        throw "uv 当前选择的 Python 不是 64 位，无法生成 Windows x64 便携包。"
    }
    $env:PLAYWRIGHT_BROWSERS_PATH = $BrowserCache
    & uv run playwright install chromium
    if ($LASTEXITCODE -ne 0) {
        throw "Playwright Chromium 下载失败，退出码：$LASTEXITCODE"
    }
    $ChromiumExecutable = Get-ChildItem $BrowserCache -Recurse -Filter "chrome.exe" -File |
        Select-Object -First 1
    if (-not $ChromiumExecutable) {
        throw "Playwright 执行完成，但构建缓存中没有 chrome.exe。"
    }

    $PyInstallerWork = Join-Path $BuildRoot "pyinstaller"
    & uv run pyinstaller --noconfirm --clean --distpath $DistRoot --workpath $PyInstallerWork packaging/windows/taskweave.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller 构建失败，退出码：$LASTEXITCODE"
    }
    $ExecutablePath = Join-Path $AppRoot "TaskWeave.exe"
    if (-not (Test-Path $ExecutablePath -PathType Leaf)) {
        throw "PyInstaller 未生成 TaskWeave.exe。"
    }

    Copy-Item $BrowserCache (Join-Path $AppRoot "browsers") -Recurse -Force
    if (-not (Get-ChildItem (Join-Path $AppRoot "browsers") -Recurse -Filter "chrome.exe" -File | Select-Object -First 1)) {
        throw "Chromium 复制后校验失败。"
    }
    if (-not $SkipWebView2) {
        Copy-Item $WebView2Runtime (Join-Path $AppRoot "webview2") -Recurse -Force
        if (-not (Get-ChildItem (Join-Path $AppRoot "webview2") -Recurse -Filter "msedgewebview2.exe" -File | Select-Object -First 1)) {
            throw "WebView2 复制后校验失败。"
        }
    }

    $VersionOutput = & uv run taskweave --version
    if ($LASTEXITCODE -ne 0) {
        throw "读取 TaskWeave 版本失败，退出码：$LASTEXITCODE"
    }
    $Manifest = [ordered]@{
        product = "TaskWeave"
        version = ($VersionOutput -join "`n").Trim()
        platform = "windows-x64"
        built_at_utc = [DateTime]::UtcNow.ToString("o")
        bundled_chromium = $true
        bundled_webview2 = (-not $SkipWebView2)
    }
    $Manifest | ConvertTo-Json | Set-Content (Join-Path $AppRoot "release.json") -Encoding UTF8

    Compress-Archive -Path $AppRoot -DestinationPath $ZipPath -CompressionLevel Optimal
    if (-not (Test-Path $ZipPath -PathType Leaf) -or (Get-Item $ZipPath).Length -eq 0) {
        throw "Windows 便携 ZIP 未生成或文件为空。"
    }
    Get-FileHash $ZipPath -Algorithm SHA256 |
        ForEach-Object { "{0}  {1}" -f $_.Hash.ToLowerInvariant(), (Split-Path $ZipPath -Leaf) } |
        Set-Content "$ZipPath.sha256" -Encoding ASCII
    Write-Host "Windows 便携包已生成：$ZipPath"
}
finally {
    Pop-Location
}
