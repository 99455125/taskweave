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

### macOS 应用

Apple Silicon 构建入口为 `uv run --no-sync python scripts/build_macos.py`。脚本使用独立 `build/macos/venv` 和现有锁文件同步全部 extras 与 build 组，不替换开发虚拟环境。产物位于 `dist/macos/TaskWeave.app`，同时生成 ZIP、SHA256 和发布清单。目标机器日常双击应用启动，无需 uv、Python 或源码目录。

包内包含全部 11 个插件、GUI 资源、OCR 模型/运行库和匹配 Chromium。Chromium 的嵌套应用、Framework 和签名按原目录复制到 Resources，应用最后做本地 ad-hoc 签名。HBuilderX、微信开发者工具、外部 Node/SDK 和服务器按插件的显式配置准备；应用启动不联网补依赖。当前交付目标为本机 arm64，公开分发所需 Developer ID 签名、公证及 Intel 实机分别验收。

工作空间沿用 `TASKWEAVE_HOME`、位置配置与平台默认规则，用户数据留在 `.app` 外。已有 `plugins.json` 保持原启用选择；缺失配置时在协调器锁保护下初始化全部插件。冻结窗口启动前同步初始化 Application，使实例锁/数据库/模型配置等前置错误进入原生告警；前置失败写入仅含公开错误信息的启动日志。原服务占用时不强占、不切换空库。

`scripts/verify_macos_bundle.py` 在精简环境与临时当前目录执行冻结诊断，并生成隔离 UI 验收副本；该副本仅通过测试用 LSEnvironment 指向独立工作空间，正式包不带这个配置。Native GUI 的实际操作与插件动作证据见 [Mac 应用验收记录](design/macos-app-acceptance-2026-10-18.md)。

Windows 目标是完整便携 ZIP：程序、Python 依赖、插件、匹配 Chromium 和必要 WebView 运行组件随包提供。目标机不调用安装器、不提权、不联网补依赖。构建配置存在不等于已经生成并验收可交付包。

维护入口：[Windows 构建脚本](../scripts/build_windows.ps1)、[PyInstaller 配置](../packaging/windows/taskweave.spec)、[项目依赖](../pyproject.toml)。构建与验证必须在相应平台及目标权限环境进行；macOS 开发测试不能代替 Windows 断网实机验证。

源码安装、编译打包成功、功能测试通过、真实平台验收是四种不同证据，交付时分别说明。

Windows目标约束、构建命令、包布局与完整实机清单见 [便携交付](windows-portable.md)。HTTP/CLI及配置见 [API与配置](reference/api-and-configuration.md)，发布证据按 [集成验收](release-checklist.md) 记录。

## DevOps 可选组合

`uv sync` 只保留显式选择的 extras；仅选择六新包会移除未选择的旧可选包。需要保留 gui/browser/database/utility/files 等时，须把对应 flags 一并带上。本次原项目实际选择六包与 gui/browser/database/utility（未选择 OCR/files）：`uv sync --locked --extra process --extra ssh --extra baota_dashboard --extra wordpress --extra uniapp --extra wechat_dev --extra browser --extra database --extra gui --extra utility`。同步后可用 `uv run --no-sync taskweave workbench` 复用该环境；本次未自动启动。建站示例需 browser，可选 TiDB 核对需 database；固定执行不安装外部 Node/HX/微信/PHP/WP-CLI/SSH/Chromium。包源码与 API v1/0.1.0 不改变核心默认依赖、任务包或数据库格式。具体变量、逻辑秘密引用、工具准备及输出见 [组合示例](../examples/devops/README.md)。

真实工具 targets 登记在模块映射的 opt-in browser_targets 通道，普通快速目标不会隐式跑 WordPress 集成、HX/微信工具。先 changed dry-run 检查选中范围，外部目标仅显式选择并配置自有环境。macOS 证据不替代 Windows/真机；uniapp Windows native 缺安全目录原语时返回准备要求，宝塔已按用户确认采用本地验收口径；公网 ACME 签发/续期及有效 uni-app AppID 下原生 H5 production 的外部验收不再阻塞本次交付，其未实测记录保留。
