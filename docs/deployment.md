# 运行与交付

本页维护当前启动方式和平台边界；交付进展与已知问题统一见 [当前状态](status.md)。

## 本地开发运行

```bash
uv sync --locked
uv run taskweave --help
uv run taskweave --home .runtime/workbench serve
uv run --extra gui --extra browser --extra ocr --extra database --extra utility --extra files taskweave workbench
```

serve 是本地 HTTP 入口，workbench 启动桌面工作台；按需要选择 extras，不要求默认核心安装所有插件。浏览器依赖需在开发/构建环境准备匹配 Chromium。工作空间配置和数据留在本地，迁移或删除之前先核对占用、路径与备份。

## 桌面与便携交付边界

NiceGUI 承载本地 UI，pywebview 提供独立窗口；macOS 使用系统 WebKit，Windows 方案需要 WebView2。工作台服务监听回环地址，启动凭据保护页面和 Socket.IO；业务自动化 Chromium 由插件单独管理。

Windows 目标是完整便携 ZIP：程序、Python 依赖、插件、匹配 Chromium 和必要 WebView 运行组件随包提供。目标机不调用安装器、不提权、不联网补依赖。构建配置存在不等于已经生成并验收可交付包。

维护入口：[Windows 构建脚本](../scripts/build_windows.ps1)、[PyInstaller 配置](../packaging/windows/taskweave.spec)、[项目依赖](../pyproject.toml)。构建与验证必须在相应平台及目标权限环境进行；macOS 开发测试不能代替 Windows 断网实机验证。

源码安装、编译打包成功、功能测试通过、真实平台验收是四种不同证据，交付时分别说明。

Windows目标约束、构建命令、包布局与完整实机清单见 [便携交付](windows-portable.md)。HTTP/CLI及配置见 [API与配置](reference/api-and-configuration.md)，发布证据按 [集成验收](release-checklist.md) 记录。
