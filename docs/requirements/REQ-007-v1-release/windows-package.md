# Windows 免安装便携交付

## 硬约束

目标虚拟机不能联网下载依赖、不允许安装程序，但允许执行 exe。交付必须为解压即用的目录包：TaskWeave-portable-win-x64.zip（目标已确认 Windows 10 x64）。不提供 Setup 安装流程，不安装 WebView2/.NET/VC 运行库，不提权、不注册服务或组件、不修改系统配置。

```text
TaskWeave/
  TaskWeave.exe
  _internal/          # Python、应用及插件依赖
  browsers/           # 与 Playwright 配套的 Chromium 和所需文件
  webview2/           # 如使用 WebView2，随附 Fixed Version 完整运行文件
```

这是“一个 exe 启动完整程序”，不是只复制一个 exe 文件。整个目录一起传入虚拟机，解压到允许执行的位置。所有依赖在外部 Windows 构建机准备，目标机不运行 pip 或 playwright install。

## UI 运行环境与可行性门槛

界面保持 Windows 独立窗口，NiceGUI + pywebview 为当前方案。优先验证随目录携带 WebView2 Fixed Version，通过 pywebview 的 WEBVIEW2_RUNTIME_PATH 指向本地资源；它不同于需要安装的 Evergreen Runtime。

不能因此承诺所有 Windows 都能直接运行。pywebview 的 .NET/pythonnet 与操作系统组件要在目标机现状下验证；WebView2 Fixed Version 在部分 Windows 10 条件下涉及应用目录 ACL 要求。若需要被禁止的运行库安装、权限调整或系统修改，则本方案判定不通过，不能要求用户安装补齐。改用可完整随包分发的窗口后端并验证，保持应用服务和 NiceGUI 界面职责不变；不以旧浏览器或关闭沙箱规避限制。

目标已确认 Windows 10 x64；最终渲染后端须在该环境及禁止安装的策略下通过免安装原型确认。没有这个验证，不能把“包含所有文件”视为零依赖保证。

## 构建与运行

- 在目标 Windows 架构构建 PyInstaller onedir，收集 Python、NiceGUI 静态资源、显式启用插件及其原生依赖。
- 包含 Playwright Python 包、driver 与匹配 Chromium 全套资源，不只复制 chrome.exe；启动前将 PLAYWRIGHT_BROWSERS_PATH 指向包内 browsers。
- 使用默认用户权限，main guard 下 freeze_support，分别管理桌面窗口、回环服务和 Playwright worker；不能要求额外开放远程端口。
- UI 窗口和业务 Chromium 分开管理；全部 UI 静态资源本地加载，无 CDN。
- 数据仍保存在用户可写目录 %LOCALAPPDATA%/TaskWeave 或 TASKWEAVE_HOME，不写程序资源目录。更换便携程序目录不丢数据。
- 默认不做 onefile，避免大型浏览器每次解包及临时目录执行策略问题。单文件自解压不是规避系统限制的方式。
- 插件扩展的冻结兼容性在 REQ-006/007 验证，不承诺冻结环境中 pip 安装任意 wheel。
- 删除程序目录即可移除程序；用户数据清理由显式操作处理。升级通过替换完整便携包，停止进程并备份后迁移应用自身数据结构。

## 硬性验收

- [ ] 与实际虚拟机相同 Windows/架构，普通用户，禁止安装/提权、禁用公网下载。
- [ ] 无 Python、Playwright、Chromium 缓存，解压完整包后直接运行 TaskWeave.exe。
- [ ] 记录目标现有 .NET 等系统组件与权限条件；不自动安装或修改系统来通过测试。
- [ ] 客户端独立窗口、内置 Chromium、截图/下载、角色隔离、固定步骤执行均通过。
- [ ] 整个过程无依赖下载、安装器、UAC、服务注册或系统配置修改。
- [ ] 验证允许目录内的 exe 子进程/DLL 加载、中文/空格路径、重启、退出清理和覆盖升级。
- [ ] 缺系统能力或策略阻止执行时清楚报错，不规避企业限制。

## 官方依据

- [Playwright 打包](https://playwright.dev/python/docs/library)。
- [pywebview 本地运行时路径](https://pywebview.flowrl.com/api/)：WEBVIEW2_RUNTIME_PATH。
- [WebView2 Fixed Version 分发与平台要求](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution)。
- [pywebview Windows 依赖](https://pywebview.flowrl.com/guide/installation)。

仓库已提供 Windows x64 构建配置：

```powershell
./scripts/build_windows.ps1 -WebView2Runtime C:\build\Microsoft.WebView2.FixedVersionRuntime.x64
```

构建机需要 Windows x64、Windows PowerShell 5.1 或 PowerShell 7、`uv`、网络（用于同步锁定依赖和下载与 Playwright 匹配的 Chromium），以及已解压的 WebView2 Fixed Version x64 目录。产物为 `dist/windows/TaskWeave-portable-win-x64.zip` 和对应 SHA-256 文件。目标机只需解压完整目录后运行 `TaskWeave.exe`。

`.github/workflows/windows-portable.yml` 可在 Windows CI 构建；运行前必须把仓库变量 `WEBVIEW2_FIXED_RUNTIME_URL` 设置成经过审核的固定版 x64 zip 地址。构建不会静默退回需要安装的 WebView2。

构建工程已经补齐，尚未在本机 macOS 生成 Windows 产物，也尚未完成目标 Windows 10 VM 的离线免安装验收。

## 已确认目标及业务浏览器选择

目标：Windows 10 x64，断网下载、禁止安装，仅允许运行 exe。默认使用随便携包分发且与 Playwright 版本配套的 Chromium，运行自身浏览器可执行文件，无需系统 Chrome 或浏览器安装器。

现有 Google Chrome 仅作为可选 browser channel，在目标环境兼容性测试后支持，不作为默认依赖。不能笼统认为系统 Chrome 更差：企业 SSO、策略或特定编解码场景可能需要它；但它的更新和企业策略不由本工具控制。默认内置 Chromium 保证我们验证的是同一套引擎和驱动。

Playwright Chromium 与桌面 WebView2 是不同组件。即便业务浏览器可便携运行，Windows 10 下窗口后端的系统依赖/目录权限仍要独立验证；不得关闭浏览器沙箱或绕过企业策略。

## 与跨平台客户端的关系

本文仅定义 Windows 10 x64 免安装包。REQ-005 客户端同时支持 macOS，共用界面和服务；macOS 单独构建 TaskWeave.app，包含相应 Python、插件依赖及匹配的 macOS Chromium，桌面窗口使用系统 WebKit。Intel 与 Apple Silicon 包分别构建和验证，签名、公证及最低系统版本在 REQ-007 记录实际交付结论，不将 Windows 验证结果视为 macOS 验收。
