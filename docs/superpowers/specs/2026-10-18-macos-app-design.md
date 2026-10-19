# TaskWeave macOS 应用交付设计

日期：2026-10-18。状态：设计及实施计划已获确认；本机应用交付和主窗口原生操作验收完成，证据及未验范围见[验收记录](../../design/macos-app-acceptance-2026-10-18.md)。

## 目标与已确认范围

将当前 TaskWeave 交付为独立 `TaskWeave.app`，用户拖入“应用程序”后双击启动，日常启动不需要终端、uv、源码目录或外部 Python。带上全部现有插件，保留已有规划、任务、步骤、运行记录、素材、环境及配置。以 Codex 通过原生应用界面实际完成操作作为验收条件。

用户已确认：“确认，按这个范围做，插件都带上，已有数据保留。”

本次目标平台为当前机器的 macOS Apple Silicon（arm64）。Intel、Windows、应用商店和联网自动更新不纳入此次验收。本次提供本机构建与安装；签名、公证及其他机器的 Gatekeeper 验收分别记录，不能把本机启动等同于可公开分发。

## 当前实现依据

- `docs/deployment.md`：NiceGUI 提供界面，pywebview 提供独立窗口，macOS 使用系统 WebKit。
- `src/taskweave/desktop/launcher.py`：回环服务、临时访问凭据、原生窗口与独立日志窗口；目前冻结包浏览器目录只查找可执行文件旁的 `browsers`。
- `src/taskweave/infrastructure/runtime.py`：运行器通过 multiprocessing spawn 启动 worker；独立日志窗口同样使用 spawn。
- `src/taskweave/infrastructure/storage.py`：已有 `TASKWEAVE_HOME`、平台默认目录及 `taskweave-location.json` 位置配置。
- 本机只读检查：默认工作空间解析为 `/Users/xiaojuju/taskweave/workspace`；位置配置不存在待清理旧目录标记。
- `src/taskweave/application/service.py`：Application 已有同工作空间的协调器实例锁，不能并行启动另一个实例占用同一数据。
- `src/taskweave/plugins/manager.py`：按 distribution entry points 发现插件，按已有 `plugins.json` 决定启用项。
- `packaging/windows/`：已有 PyInstaller 冻结交付模式，尚无 macOS 构建入口；Windows spec 仅收集五个旧可选插件，不能直接代表全部插件。
- 本机环境发现 11 个插件；当前虚拟环境未安装 PyInstaller。构建依赖组已声明 PyInstaller，保留现有锁文件版本约束。

## 方案选择

采用 PyInstaller 的 macOS app bundle，继续使用现有 NiceGUI、pywebview 和 Application 边界。新增独立 macOS 构建入口，不重写业务界面或引入第二套前端。

相比只用 `.app` 外壳调用现有 uv 环境，该方案能摆脱开发目录与外部 Python；相比重写成 Swift 或 Electron，能够保留现有界面、插件和数据契约，改动集中于交付和启动。

应用包含 Python 运行时、GUI 静态资源、原生桥接依赖、插件代码及元数据、OCR 模型和对应本地库，以及匹配版本的 Playwright Chromium。构建产物不包含用户工作空间、数据库、凭据、浏览器会话和本地环境文件。

### 全部插件

逐项收集并验证以下插件及其声明依赖、包资源和 entry-point 元数据：

| ID | 包 |
| --- | --- |
| playwright | taskweave-playwright |
| ocr | taskweave-ocr |
| tidb | taskweave-tidb |
| utility | taskweave-utility |
| file | taskweave-file |
| process | taskweave-process |
| ssh | taskweave-ssh |
| baota_dashboard | taskweave-baota-dashboard |
| wordpress | taskweave-wordpress |
| uniapp | taskweave-uniapp |
| wechat_dev | taskweave-wechat-dev |

已有工作空间保留原有启用/禁用配置。全新工作空间由应用首次启动初始化全部 11 个插件的启用配置，后续遵循用户选择；不改变源码 CLI 的默认行为。

“带上插件”包含其可分发的软件依赖与资源。HBuilderX、微信开发者工具、服务器、数据库服务、业务账号等外部目标继续使用本机已有配置；不擅自打包商业工具或把未连接外部服务写成通过。构建核对各插件的外部依赖并在交付清单列明。

## 启动与进程

- 设置稳定的应用名称、Bundle ID、图标和版本，Finder、Dock 及原生控制工具能识别 TaskWeave。
- 专用入口在 GUI 和业务模块导入前执行冻结子进程分流与 `freeze_support`，避免 worker 递归打开新窗口。
- 根据 bundle 的 Resources/Frameworks 布局定位内置 Chromium 和资源，子进程继承同一解析结果；不依赖当前工作目录。
- 不把整个源码目录加入运行搜索路径，不在首次启动时同步依赖或下载浏览器。
- 继续仅监听回环地址，并保留页面、Socket 和 API 访问保护；不添加无凭据的控制入口。
- 启动异常写入应用日志，并显示可理解的错误及日志位置；日志不输出访问令牌或环境秘密。
- 重复启动遵循现有实例锁，不能偷偷切到新工作空间。若原源码服务占用同一工作空间，清楚提示，不强制结束旧进程。
- 正常退出验证服务、worker 和独立日志窗口收尾；不结束用户自行打开的浏览器或其他应用。

## 数据保留与兼容

沿用现有工作空间解析规则，不改变数据库格式、任务包格式和插件协议，不把数据搬进 `.app`。更新或替换应用不会替换用户数据。

接入现有工作空间前先核对占用、执行状态和位置配置，保留可恢复的本地备份：SQLite 使用一致性备份方式，素材与配置保留完整副本，避免只复制仍在写入的数据库主文件。备份包含本地秘密，使用受限权限且不纳入产物或 Git。

首先用独立验收工作空间验证打包和原生控制。现有工作空间如有正在执行的任务或录制，保持原服务运行，待安全释放实例锁后再接入；不通过清理锁文件或杀进程强占。

应用接入原工作空间时核对规划、任务、步骤和素材清单。业务操作仅通过现有 Application/界面完成，不能直接改库修补数据。首次验收只查看既有内容，演示操作使用明确标记的新增测试内容。

## Codex 原生界面验收

安装包和可访问性是两个独立验收项。使用当前原生控制接口按应用名称或 Bundle ID 获取应用，读取可访问性树并操作窗口，不用 Chrome 替代此项。

在独立验收工作空间实际完成：

1. 从应用目录打开应用，识别独立 TaskWeave 窗口。
2. 通过可见按钮打开“新建规划”，输入名称并保存，重启后仍存在。
3. 创建任务，新增步骤，编辑并保存代码和参数。
4. 运行安全的本地演示步骤，确认 spawn worker 能执行并返回结果。
5. 打开插件页，11 个插件均已安装且加载无错误。
6. 用内置 Chromium 打开本地测试页面；OCR 识别普通固定测试图片；文件插件完成临时文件读写。其余插件验证导入、注册及资源完整性，不触发外部发布、交易或服务器写入。
7. 打开日志窗口，退出并再次启动，确认生命周期正常。

如果 WebKit 内部控件未被暴露，先定位原生桥接、控件语义和可访问性标签，优先修复受影响控件。截图坐标操作可作为诊断证据，不能代替关键控件可识别、可操作的验收。若必须更换 GUI 引擎或引入另一套应用外壳，属于实质方案变化，先提供现场证据和变更方案。

## 构建、验证与交付

构建使用独立 uv 构建环境和现有锁文件，选择所有 extras 与 build 组，避免同步当前自测环境导致插件移除。输出至专用 `build/macos`、`dist/macos`；构建只管理自己的目录。

交付 `.app`、便于保留 bundle 结构的归档、版本/架构/插件/浏览器清单与 SHA256。确认目标位置无已有同名应用后安装到本机“应用程序”；遇到已有应用先核对归属和处理方式。

验证分层记录：

- 定向单元测试：冻结资源路径、启动参数和子进程分流、全新/已有工作空间插件初始化、现有数据位置兼容。
- 打包实测：在 Finder 风格的精简环境中启动，脱离源码目录、项目虚拟环境和终端 PATH；检查缺失动态库、资源与插件元数据。
- 实际原生控制：上述七项界面和运行流程，记录结果与截图。
- 原工作空间：备份与只读清单核对、既有内容可见；不重跑既有业务流程。
- 工程检查与差异检查；按源码影响选择已有回归，不执行全量测试。

实现后更新 `docs/deployment.md` 及实际受影响模块说明；状态只写本次真实结果。编译成功、窗口启动、原生可操作、插件实际动作及签名公证分别记录。Git 提交、推送、PR 和非本地发布仍须单独授权。

## 参考

- [PyInstaller spec 与 BUNDLE 配置](https://pyinstaller.org/en/stable/spec-files.html)
- [冻结程序的 multiprocessing 与运行注意事项](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html)
