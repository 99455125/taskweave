param(
    [string]$WebView2Runtime = $env:WEBVIEW2_FIXED_RUNTIME_DIR,
    [switch]$SkipWebView2
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$BuildRoot = Join-Path $Root "build/windows"
$BrowserCache = Join-Path $BuildRoot "playwright-browsers"
$DistRoot = Join-Path $Root "dist/windows"
$AppRoot = Join-Path $DistRoot "TaskWeave"
$ZipPath = Join-Path $DistRoot "TaskWeave-portable-win-x64.zip"

if (-not $IsWindows) {
    throw "Windows 便携包必须在 Windows x64 上构建。"
}
if (-not [Environment]::Is64BitOperatingSystem) {
    throw "仅支持 Windows x64 构建机。"
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "构建机缺少 uv。请先安装 uv；目标机不需要 uv 或 Python。"
}
if (-not $SkipWebView2 -and (-not $WebView2Runtime -or -not (Test-Path $WebView2Runtime))) {
    throw "请通过 -WebView2Runtime 指定已解压的 WebView2 Fixed Version x64 目录，或显式使用 -SkipWebView2（仅适用于目标机已验证存在 WebView2 Runtime）。"
}
if (-not $SkipWebView2) {
    $WebViewExecutable = Get-ChildItem $WebView2Runtime -Recurse -Filter "msedgewebview2.exe" -File |
        Select-Object -First 1
    if (-not $WebViewExecutable) {
        throw "WebView2 目录中没有 msedgewebview2.exe，请提供完整的 Fixed Version x64 Runtime。"
    }
    $WebView2Runtime = $WebViewExecutable.Directory.FullName
}

Remove-Item $BuildRoot -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $DistRoot -Recurse -Force -ErrorAction SilentlyContinue
New-Item $BrowserCache -ItemType Directory -Force | Out-Null
New-Item $DistRoot -ItemType Directory -Force | Out-Null

Push-Location $Root
try {
    uv sync --locked --group build --extra gui --extra browser --extra sample --extra captcha --extra database
    $env:PLAYWRIGHT_BROWSERS_PATH = $BrowserCache
    uv run playwright install chromium
    uv run pyinstaller --noconfirm --clean --distpath $DistRoot --workpath (Join-Path $BuildRoot "pyinstaller") packaging/windows/taskweave.spec

    Copy-Item $BrowserCache (Join-Path $AppRoot "browsers") -Recurse -Force
    if (-not $SkipWebView2) {
        Copy-Item $WebView2Runtime (Join-Path $AppRoot "webview2") -Recurse -Force
    }

    $Manifest = [ordered]@{
        product = "TaskWeave"
        version = (uv run taskweave --version).Trim()
        platform = "windows-x64"
        built_at_utc = [DateTime]::UtcNow.ToString("o")
        bundled_chromium = $true
        bundled_webview2 = (-not $SkipWebView2)
    }
    $Manifest | ConvertTo-Json | Set-Content (Join-Path $AppRoot "release.json") -Encoding UTF8

    Compress-Archive -Path $AppRoot -DestinationPath $ZipPath -CompressionLevel Optimal
    Get-FileHash $ZipPath -Algorithm SHA256 |
        ForEach-Object { "{0}  {1}" -f $_.Hash.ToLowerInvariant(), (Split-Path $ZipPath -Leaf) } |
        Set-Content "$ZipPath.sha256" -Encoding ASCII
    Write-Host "Windows 便携包已生成：$ZipPath"
}
finally {
    Pop-Location
}
