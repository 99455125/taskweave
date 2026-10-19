# Mac 应用验收记录 · 2026-10-18

设计：[Mac 应用设计](../superpowers/specs/2026-10-18-macos-app-design.md)。实施：[计划与进度](../superpowers/plans/2026-10-18-macos-app.md)。

## 已执行

- 本机 macOS arm64、Python 3.12.14；独立构建环境按原 uv.lock 同步。当前开发虚拟环境保持原位。
- 生成 `dist/macos/TaskWeave.app`、ZIP、SHA256 和 `release.json`；应用约 999 MiB，ZIP 约 456 MiB，实际大小以产物为准。
- 在无开发 PYTHONPATH、无 uv/Python PATH、临时当前目录下执行包内诊断：frozen=true、11 个插件 entry points 和注册完整、browser_bundled=true。
- `codesign --verify --deep --strict --verbose=1` 通过。当前使用本地 ad-hoc 签名，未做 Developer ID 签名与公证。
- 原生控制工具按完整 `.app` 路径成功获得窗口与可访问性控件。完成首页新建规划、保存名称、新建任务、添加步骤、编辑代码、保存、运行调试；未使用 Chrome 替代原生控件验收。
- 原生创建并持久化：规划 `Mac App Native Acceptance`、任务 `Mac App Native Task`、步骤 `Native saved step`。
- 实际冻结 worker 运行 `928fdb71-5e3d-484f-a4f8-7de457c9c5f6` 成功，输出 `{"native_app": true, "value": 42}`。
- 实际冻结 worker 运行 `a1da7f5f-f3ba-4bbc-821b-a6c938e0a936` 成功：utility 精确金额 `0.30`、file 读取明确允许目录中的固定文件、包内 Chromium 打开回环测试页面并读取标题、包内 OCR 识别普通固定测试图得到 `1234`。图片未用于任何网站验证码或登录。
- 审核修正后的最终构建在独立 acceptance-3 再次运行上述四插件任务，运行 `535f3e39-029b-402f-b7f4-7367ada866ca` 成功，输出一致。随后关闭验收窗口，核对无遗留验收应用进程，结束自有回环夹具服务。
- 原生插件页显示全部 11 个插件已启用；退出后工作台服务、worker 和日志子进程退出，再次启动保留规划/任务/步骤。关闭窗口后的原生状态读取超时按窗口已消失处理，并用进程及端口检查核对退出。
- 独立日志窗口子进程已实际创建并在退出时回收；控制工具选回主窗口，尚未单独取得日志子窗口的可访问性树，不宣称该子窗口可控。

## 数据保护

接入原数据前已在无现有协调器锁占用的现场取得锁并备份，备份目录：`/Users/xiaojuju/taskweave/macos-app-backups/20261018-224112`。228 个文件；SQLite 采用一致性备份且 quick_check 返回 ok。目录与文件采用受限权限；备份不纳入构建和 Git。

原清单为 18 个任务、174 个步骤、6 个规划、528 个步骤上下文组、38 个规划上下文组。原工作空间 `backups/` 目录仍保留，避免递归备份旧备份，本次副本排除该历史备份目录。

界面创建及插件试跑发生在独立 `build/macos/acceptance-2/workspace`；测试 app 的可执行程序与正式包一致，只有测试副本的 Info.plist 设置了 LSEnvironment 工作空间路径。审核后修正版本在 acceptance-3 继续验收。正式 app 不带测试工作空间或用户数据。

正式应用已安装到 `/Applications/TaskWeave.app` 并通过原生工具打开；工作台显示原有 18 个任务和既有 UAT/本地自测记录。打开插件页确认 11 个插件均已安装，保留原启用的 6 项与未启用的 5 项。安装前核对所有原表记录数量及非数据库配置/素材文件 SHA256 与备份一致；安装启动后再次核对所有表记录数量、原 plugins.json 字节不变。正式 Info.plist 不含测试 LSEnvironment，安装副本 deep strict 签名校验通过；应用留在原数据工作台供用户使用。

## 构建与审核中修复的问题

1. Chromium 作为 PyInstaller 待处理二进制收集时，重签名破坏嵌套 Framework。改为构建后完整复制浏览器树，补 Framework 符号链接保留回归用例，RED→GREEN，外层签名及 deep strict 校验通过。
2. macOS 的 `_MEIPASS` 指向 Frameworks，后拷入的浏览器在 Resources。增加 Contents/Resources 定位，回归 RED→GREEN，冻结诊断确认找到浏览器。
3. 独立审核发现首次插件初始化在实例锁前写配置。补占用工作空间用例先失败，再在配置创建期间持有同一协调器锁；既有配置字节保持不变。
4. 独立审核确认 NiceGUI 异步启动错误不传播给外层原生告警。冻结模式改为打开窗口前同步创建 Application；补错误同步传播与日志 handler 释放用例，RED→GREEN。
5. 前置插件配置错误早于 ServerLogs，旧告警指向不存在的日志。增加脱敏启动记录，并只在实际可写时展示日志路径；用例 RED→GREEN。

最近一次定向运行：`uv run --no-sync python -m unittest tests.test_macos_bundle tests.test_macos_packaging tests.test_desktop_port tests.test_desktop_security tests.test_plugin_contract tests.test_module_selection -q`，52 项通过。未运行全量测试。

## 证据与限制

本机证据保存在 `.superpowers/sdd/2026-10-18-macos-app/`，包括构建失败及成功日志、RED 与 GREEN、备份摘要和限定审核进度；原生成功截图在 `build/macos/acceptance-2/native-worker-success.png`、`native-plugins-success.png`、`native-all-plugins.png`。这些本地目录不作为发布数据。

最终构建证据为 `build/macos/acceptance-3/final-plugins-success.png`、`installed-existing-workspace.png`、`installed-verification.json`；发布 ZIP 的 SHA256 已重新核对一致。原工作区及本地证据均保留，采用批准的当前工作区，未创建或清理工作树；后续集成审核须限定本次文件清单，避免混入其他来源修改。

外部 Node/SDK、HBuilderX、微信开发者工具、SSH/宝塔/WordPress/数据库远端动作未在本次应用交付中重验；插件注册与实际外部操作分列。现有 file 插件提供读取能力，夹具写入由本地验收准备完成，没有宣称新增 file.write。

独立审核 Minor 待办：Bundle 版本当前固定 0.1.0，与本次元数据版本一致；后续升级需同步 spec，自动统一版本来源留待后续。Git 未提交、未推送，未执行非本地发布。
