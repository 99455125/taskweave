# AI 编写、调用与验收实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 交付用户可通过外部 AI 编写、复用执行并一点击核对事实的 Skill/MCP 完整闭环。

**Architecture:** 少量按目的工具复用现有 application，用持久回执保护外部重试，MCP 连接唯一 Application 所有者。桌面展示与工具查询共用基于持久事实的验收投影。

**Tech Stack:** Python >=3.10、uv、JSON Schema、SQLite/本地文件、可选 MCP SDK、NiceGUI。

**Spec:** [设计](../specs/2026-10-21-ai-integration-design.md)

## Global Constraints

- 沿用当前工作区，前置保存点 f2cb961；既有 OCR 元数据与 tmp/ 不变。
- 主 Agent 实施，Astra 参与设计及最终审核；用户已要求自主完成最终版本，不重复逐阶段确认。
- core/application/presentation 不依赖 MCP 或 GUI；固定执行不调用模型。
- 使用 uv，SDK 为可选依赖，保留 uv.lock；不升级 Python 最低要求。
- 后续 commit/push/PR/非本地部署均需独立授权，本计划不自动执行。
- 测试定向选择，不以分组方式执行全量。

## Review Focus

- 桌面已占用工作空间时，MCP 连接同一所有者；过期描述符不能误连另一服务。
- 请求成功后响应丢失，不得重复创建/启动；回执不确定时明确报需核对。
- 保存冲突和旧材料不能覆盖当前定义，试跑证据必须匹配版本。
- 多任务节点/循环轮次/历史尝试不混淆；缺证据不能显示验收通过。
- 本地秘密、文件路径、图像与大日志不默认进入模型结果，验收路由不能漏鉴权。

---

### Task 1: 有界能力发现与真实操作契约

**Files:** application/agent/{discovery,contracts,projection}.py；tests/test_agent_discovery.py。

**Interfaces:** produces discover(kind, query, cursor, limit)、describe(kind, identity, sections)、显式操作策略与参数校验；consumes build_operation_contracts 与实际 registry。

- [x] 写并运行失败测试：分页、动态插件/动作契约、按需Schema、未知操作/额外/缺失/错误类型参数、秘密与绝对路径隔离。
- [x] 实现上述有界查询和策略；默认20、最大100，超量显式引用。
- [x] 运行 tests.test_agent_discovery，比较全量目录与按需返回的实际字节量。

### Task 2: 外部编写、持久回执与执行闭环

**Files:** application/agent/{service,authoring,execution}.py；core/agent_ports.py；infrastructure/agent_store.py；composition.py、operations.py；tests/test_agent_workflows.py。

**Interfaces:** consumes Task 1；produces AgentService 的 author/context/execute/wait/inspect；AgentStore 回执及冻结材料端口。

- [x] 写并运行失败测试：创建响应丢失、同ID异参、保存版本冲突、过期材料、无模型编写、流程确认、试跑证据、任务/组合启动与补参。
- [x] 实现真实用例映射、材料选择、候选校验、回执、紧凑状态/等待/证据读取。
- [x] 用真实 worker 完成编写→试跑→确认→正式执行；覆盖分支/循环与组合逐轮输出。

### Task 3: 验收要求、事实投影与人工决定

**Files:** application/agent/{review,checks}.py；presentation/review.py；infrastructure/agent_store.py；tests/test_agent_review.py。

**Interfaces:** consumes 持久运行/结果/流程实例；produces review.prepare/read、报告指纹、仅桌面使用的人工决定用例。

- [x] 写并运行失败测试：相等/比较/列表核对、缺失输出、失败/UNKNOWN、重试失效、重复任务节点、逐轮路径、无要求及伪造human来源。
- [x] 实现冻结要求、声明式核对与有界摘要；保持运行/自动核对/人工决定分离。
- [x] 运行 tests.test_agent_review，证明查看不会执行业务动作。

### Task 4: 唯一所有者连接、MCP 与 function calling 契约

**Files:** infrastructure/{agent_connection,mcp_server}.py；http.py、__main__.py、desktop/launcher.py；pyproject.toml、uv.lock；tests/test_agent_connection.py、tests/test_mcp_integration.py。

**Interfaces:** consumes AgentService；produces 本地描述符/鉴权桥、taskweave mcp、工具定义导出；不新建第二Application。

- [x] 写并运行失败测试：desktop/serve 共用app、过期描述符、无凭据/跨workspace、工具参数错误、协议握手及stdout无日志/令牌。
- [x] 使用可选官方SDK实现 stdio；工具Schema来自同一契约；CLI导出可供自有function calling复用。
- [x] 真实 stdio 客户端发现并调用，服务关闭清理自己的连接记录。

### Task 5: 一点击验收与 AI 连接设置

**Files:** desktop/pages/review.py、components/agent_settings.py；workbench.py、launcher.py、executions/sequences页面；presentation/review.py；tests/ui/test_review_page.py、tests/test_agent_browser.py。

**Interfaces:** consumes Task 3报告、Task 4鉴权服务；produces 运行/组合“查看验收”、安全定位路由、人工决定、可复制接入配置。

- [x] 写并运行失败测试：指定运行定位、证据查看、人工决定、组合零轮控制事实、旧决定过期；复用现有路由鉴权验证。
- [x] 实现首屏目标/路径/核对表和复用结果查看器，连接设置明确说明缺少的启动/依赖条件。
- [x] 用实际浏览器完成编写运行后一次打开验收、看证据并记录人工决定；无GUI返回明确状态。

### Task 6: 可安装 Skill、文档、完整审查

**Files:** packaged Skill 资源及安装/导出入口；docs/modules/agent.md、相关知识/契约、tests/module-map.json；tests/test_agent_skill.py。

**Interfaces:** consumes 全部最终工具契约；produces 可发现的TaskWeave Skill、按需参考材料及安装命令。

- [x] 按 skill-creator/writing-skills 写入口及编写/执行/验收参考，包含新控制流，不复制全量参数清单。
- [x] 校验Skill、安装包资源和目标目录冲突，以真实SDK完成业务调用；场景推演明确披露为有上下文的静态评估。
- [x] 更新受影响知识和测试映射；执行定向回归、check_project、git diff --check。
- [x] 新 Astra 对 f2cb961 后的完整未提交差异和目标覆盖作最终审核；主 Agent 修复并复验。
- [x] 按原始要求逐项审计，记录通过/失败/未覆盖，证据齐全后才标记目标完成。

## 持久进度

- 前置保存点：f2cb96129a6341425c781cea2607fa45a5f9eb9e，main，本地提交；原 OCR 元数据和 tmp/ 保留。本轮实现留在工作区。
- Task 1–6 已实现。实际文件使用 integration/{tools,mcp,skill}.py、infrastructure/agent_connection.py、desktop/components/agent_review.py；验收以同一已连接客户端弹窗实现，复用现有鉴权，不新增可泄漏授权的深链接路由。
- 开发按缺失功能/真实问题先失败再修复：发现与契约、回执事务、工作流、验收、传输、Skill安装和组件均有对应回归。
- 真实 MCP SDK stdio 完成发现→当前操作契约→材料→创建任务与步骤→试跑→证据确认→结束试跑→冻结要求→正式执行→自动验收报告闭环，无模型调用。
- 浏览器在临时工作空间验证外部 review.open→原始结果→人工决定→外部读取 ACCEPTED；截图位于 /tmp/taskweave-ai-acceptance.png。组件另覆盖组合内零轮循环无动作尝试时的控制事实。
- 104项定向整合回归通过（含agent、store、迁移、路由、任务包、原生组合生命周期、UI和step outputs）；17项HTTP/桌面鉴权/导航回归通过；真实浏览器1项通过。最终工程/差异检查及追加原生flow回归结果见下方最终核验。
- wheel 构建及4份Skill资源/可选MCP元数据检查通过；Skill quick_validate通过。安装冲突保持已有目录；未自动修改用户全局MCP配置或安装个人Skill。
- Astra初次规格/基础审核、完整审核和新鲜独立最终审核均已完成。最终发现的操作读取入口、大单项材料、采集契约、补参范围、组合成员版本及控制事实可见性均已修复并回归。新鲜Astra最后限定静态复核：未发现剩余阻塞；其没有运行测试。
- Skill评估包括受限无Skill/有Skill场景推演（同一审核Agent，具有会话背景，并非独立盲测）及真实SDK业务调用。没有将静态推演扩称模型自主使用验收。
- 限制：未运行全量测试、未验收真实外部业务服务/原生macOS窗口/Windows安装包；本地浏览器及wheel证明不替代这些平台验收。未做模型token消耗百分比基准，节省来自有界摘要/按需Schema/确定性执行。
- Ruling：共享主工作区，不按Skill另建工作树或自动提交。参数精确Schema来自当前运行契约；插件贡献去重且不裁剪语义。
- Ruling：sequence.prepare_start先提交运行、验收绑定和回执，再唤醒驱动；未经证明幂等的组合控制，PENDING回执不重发。
- Ruling：新增RunUseCases.project_output只用于在原始结果字段上下文中投影；公开output签名和默认原生聚合行为保持兼容。工具在Pointer/item_pointer/文本分块前脱敏和省略图片；报告actual/expected保留来源字段语义。
- 发现并修复受影响链路既有缺陷：instance.end原先以错误control签名调用，现在使用稳定命令ID及abandon；路由fixture补齐前序task.flow新增入口。

## 最终核验

- 最终整合：104项通过，44.617s；入口为agent discovery/store/workflows/review/transport/skill、验收与设置组件、迁移/分发/任务包/任务组合生命周期及step outputs的定向组合。
- HTTP/桌面鉴权/导航：17项通过，1.437s。
- 原生控制流执行：tests.test_flow_execution 19项通过，9.066s。
- 最终真实浏览器：tests.test_agent_browser 1项通过，4.738s；包括同一工作台外部打开报告、查看原始结果、人工验收及读取决定。
- 合计140项非浏览器定向测试与1项真实浏览器测试；没有全量测试授权，未运行全量。
- 最终wheel构建exit0；检查包含4份Skill资源、可选mcp元数据和最终project_output实现通过。Skill quick_validate通过。
- check_project通过：布局、语法、依赖边界、ESC策略、64份Markdown及CLI版本；git diff --check exit0。
- HEAD仍为f2cb961；本轮代码/文档尚未提交，原OCR元数据与tmp/保留。全局MCP配置及个人Skill目录未自动改写。
- 目标审计：外部编写材料/候选/试跑/确认、动态插件与采集契约、条件/foreach/while/until/嵌套/组合调用、低输出预算、持久回执与UNKNOWN保护、可视化证据/人工验收、安装接入说明均有实现及相应证据。真实外部平台/原生发布包和模型token节省率没有扩称为已验收。
