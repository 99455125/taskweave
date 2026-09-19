# REQ-007 进度

2026-09-15：完成需求拆分与实施输入。

2026-09-19：新增 PyInstaller onedir Windows x64 入口与 spec、一键 PowerShell 构建脚本和手动触发的 Windows CI。构建会收集核心、NiceGUI/pywebview、Playwright、示例、验证码及 TiDB 插件，下载配套 Chromium，要求显式提供 WebView2 Fixed Version，并输出便携 zip、发布清单和 SHA-256。冻结运行时会将 `PLAYWRIGHT_BROWSERS_PATH` 指向包内 browsers。当前 macOS 不能产出或验收 Windows EXE，目标 Windows 10 x64 离线 VM 验收仍待执行。

下一步：在 Windows x64 构建机生成便携包，再到无 Python、无缓存、断网的目标 Windows 10 VM 验收。

本需求交付基础顺序任务版本；条件/循环/嵌套与图形编排随后由 REQ-008/009 实现和验证。
