# REQ-007 进度

2026-09-15：完成需求拆分与实施输入。

2026-09-19：新增 PyInstaller onedir Windows x64 入口与 spec、一键 PowerShell 构建脚本和手动触发的 Windows CI。构建会收集核心、NiceGUI/pywebview、Playwright、示例、验证码及 TiDB 插件，下载配套 Chromium，要求显式提供 WebView2 Fixed Version，并输出便携 zip、发布清单和 SHA-256。冻结运行时会将 `PLAYWRIGHT_BROWSERS_PATH` 指向包内 browsers。当前 macOS 不能产出或验收 Windows EXE，目标 Windows 10 x64 离线 VM 验收仍待执行。

2026-09-20：修复 Windows PowerShell 5.1 不提供 `$IsWindows` 自动变量而误判非 Windows 的问题；改用 Windows 各 PowerShell 版本均提供的 `$env:OS -eq "Windows_NT"` 判定。同时补上 PowerShell 5.1 不会因原生命令非零退出码自动停止的处理，以及 64 位进程、Chromium、WebView2、TaskWeave.exe 和最终 ZIP 的实体校验，防止生成残缺包。

2026-09-20：WebView2 构建输入改为微软官方 Fixed Version x64 CAB，由脚本使用 `expand.exe` 解压并校验 `msedgewebview2.exe`；CI 同步改为 CAB 流程。Windows 启动时除环境变量外，显式设置 pywebview 6 的 `webview.settings["WEBVIEW2_RUNTIME_PATH"]`，确保使用包内固定版。

下一步：在 Windows x64 构建机生成便携包，再到无 Python、无缓存、断网的目标 Windows 10 VM 验收。

本需求交付基础顺序任务版本；条件/循环/嵌套与图形编排随后由 REQ-008/009 实现和验证。
