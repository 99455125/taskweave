# REQ-007 代码映射

- `packaging/windows/taskweave_launcher.py`：冻结后直接启动本地工作台的 Windows EXE 入口。
- `packaging/windows/taskweave.spec`：PyInstaller onedir 收集规则，包含核心、GUI、Playwright 与内置插件及 distribution metadata。
- `scripts/build_windows.ps1`：Windows x64 一键构建、Chromium 下载、WebView2 校验、zip 及 SHA-256 生成。
- `.github/workflows/windows-portable.yml`：手动触发的 Windows 便携包 CI。
- `src/taskweave/desktop/launcher.py`：冻结环境中将 Playwright 指向便携包内的 `browsers/`。
- `docs/requirements/REQ-007-v1-release/windows-package.md`：构建和目标 VM 验收手册。

本需求交付基础顺序任务版本；条件/循环/嵌套与图形编排随后由 REQ-008/009 实现和验证。
