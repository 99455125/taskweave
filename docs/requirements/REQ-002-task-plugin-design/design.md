# 总体设计基线 · 2026-09-16

本文件及同目录契约是 REQ-003/004 的实现基线。API/schema 的兼容版本仅用于协议识别，不是步骤版本。后续变更须同步文档和契约验证。

## 1. 已定边界

- 本地单用户使用，总库存任务/步骤配置及执行记录，任务业务库和文件目录按需创建。
- AI 和纯手写都可生成相同的 step content；试跑成功后保存，正式执行不调用模型。
- 不设计步骤版本表、历史版本选择或回滚树。运行日志与验证记录不是步骤版本。
- 插件贡献执行、提示词、上下文、AI 工具、内容校验、业务断言、诊断、资源管理、结果结构与解析。
- Playwright 是第一个真实插件，不在核心设置浏览器专用分支。不迁移 Excel 功能。
- 基础版本顺序执行、单活跃会话；条件/循环/子流程及拖拽分别在 REQ-008/009 实现。

## 2. 分层

```text
UI / CLI
  └─ application：步骤编写服务、运行协调器、导入导出用例
      ├─ core：任务/步骤、绑定、状态规则、结果与存储端口
      ├─ plugins：注册表及统一贡献接口
      │   └─ Playwright / 自定义插件
      └─ infrastructure：SQLite、AI provider、worker、文件、配置
```

UI 不直接调模型/插件/SQL。模型适配器只被编写服务使用；执行 worker 没有模型调用职责。插件调用只通过声明的 action/tool/resource/result-handler ID 解析。

## 3. 实现选择

- Python >=3.10，step content 使用单一异步 Python 入口；协议与领域模型用标准库 dataclass/Protocol。
- SQLite 使用显式 SQL 迁移与标准库 sqlite3，先不引入 ORM。JSON 参数契约采用 JSON Schema 2020-12，完整校验器在 REQ-003 引入；本轮不新增依赖。
- 安装插件用 Python distribution entry point：`taskweave.plugins`；仅加载本机显式启用的插件。一插件 ID 启用一个已安装版本。
- 协调器持总库写职责；单 worker 进程使用 `multiprocessing.get_context("spawn")` 与固定 asyncio event loop，避免 UI 线程池共享浏览器对象。
- IPC 只传可 JSON 序列化命令/事件，不传 ORM、浏览器或连接。任务数据写入由 worker 内的任务作用域适配器负责。
- UI 确定为 Windows 独立客户端：NiceGUI native mode + pywebview/WebView2；REQ-005 实现窗口，REQ-007 交付包含 Playwright/Chromium 的免安装便携包。具体平台依赖与真实打包需验证，不影响核心接口。
- 本地服务默认 127.0.0.1。数据根目录优先 `TASKWEAVE_HOME`，否则 Windows `%LOCALAPPDATA%/TaskWeave`，macOS `~/Library/Application Support/TaskWeave`，Linux `${XDG_DATA_HOME:-~/.local/share}/taskweave`。

entry point 和 spawn 的标准接口参考 [Python metadata](https://docs.python.org/3/library/importlib.metadata.html#entry-points) 与 [multiprocessing](https://docs.python.org/3/library/multiprocessing.html#contexts-and-start-methods)。Playwright 对象在所属 worker 的同一事件循环使用，见 [Playwright Library](https://playwright.dev/python/docs/library)。

## 4. 首次可用闭环

REQ-003 用模拟模型和最小动作适配实现编写/执行/保存，不等待真实插件。REQ-004 用 Playwright 和另一简单插件验证扩展通用性。REQ-005 只接服务和事件。随后 REQ-006 分享、REQ-007 基础交付，最后控制流和图形编排。

具体契约见 [步骤](step-content.md)、[插件](plugin-contract.md)、[运行](runtime.md)、[存储](storage.md)。

## 5. 旧实现迁移结论

旧 `Step.step_content` 是目标描述，`step_sql` 是生成并验证的 SQL；旧 Step 无版本。新模型将目标放 `goal`，可执行 Python 放 `step_content`，不得自动把旧自然语言当 Python 执行。旧总库 `task.db_server`、任务库 `task_<id>.db_server` 保留不动；本轮只给新 schema，不自动迁移旧业务或数据。旧模型只有当前成功状态，新的逐次 run/attempt 记录是新增能力。

## 6. 复用原则

旧代码只用于理解需求及现状，不是新架构的兼容契约。无需保留旧模型、函数签名、Flask/SQL 执行耦合或旧目录布局；不合理部分直接重新设计。只有符合当前接口且通过独立验证的纯逻辑才考虑提取。总库/任务库思路来自已确认需求，不意味着沿用旧数据库表或路径。旧数据迁移不作为 REQ-003 的前置任务。
