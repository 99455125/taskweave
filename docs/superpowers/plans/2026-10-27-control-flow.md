# 步骤与组合控制流实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. 按勾选项记录进度。

**Goal:** 步骤和任务组合条件可选择并行，组合支持条件、遍历、循环及实际执行。

**Architecture:** 以结构化多分支定义表达条件。纯控制推进产生可恢复路径，任务内由独立分支资源执行步骤，组合层由独立子运行执行任务；持久化冻结分支选择、轮次及执行身份。

**Tech Stack:** Python / uv / SQLite / NiceGUI，沿用已有分层。

**Spec:** [修正设计](../specs/2026-10-27-sequence-control-flow-design.md) 的“修正后的实施决策”为最终语义。

## Global Constraints

- 沿用当前工作区，保护已有修改与本机数据。无需旧格式和历史兼容，不清空数据库。
- Git commit、push、PR 写操作及非本地部署未获授权。
- 不运行全量测试；按 docs/testing.md 定向验证，不用分组拼接全量。
- 固定执行不调用模型；core/presentation 依赖边界保持。
- 并行必须有实际动作重叠、全部完成后汇合和独立资源会话的证据。

## Review Focus

- 两个命中条件在默认模式只执行第一个，开启并行才全部执行。
- 分支输出、补参、重试和 UNKNOWN 在嵌套循环中不能串实例。
- 并行失败/暂停/取消不能提前汇合或重复成功动作。
- 资源容量为 1 或嵌套并行时无死锁、无无限线程增长。
- 删除、关闭和重启覆盖全部子实例与分支资源。

### Task 1: 步骤级条件结构、并行执行与恢复

**Files:** core/task_flow.py、flow_machine.py、flow_values.py；infrastructure/flow_runner.py、run_coordinator.py、coordinator_pool.py、repositories/flow_runs.py；相关 core/run_ports.py、运行仓储与调用方；tests/test_task_flow*.py 及新增定向并行测试。

**Interfaces:** 输出明确多分支节点（稳定分支 ID、条件、路径、parallel 布尔值、默认路径、公共输出）；纯推进器可表示多个待执行路径；任务实例仍归属同一 run_id，执行路径唯一。

- [x] 先写并运行失败测试：首个匹配、全部匹配、零命中、条件冻结及非法并行字段。
- [x] 实现定义、作用域、纯控制游标、输出按分支 ID 聚合，保留循环状态语义。
- [x] 先写本地动作重叠与汇合失败测试，再实现分支独立 worker、容量、暂停取消、输入与重试定位、崩溃恢复。
- [x] 定向运行核心与执行相关测试，记录命令与结果；独立审核本任务差异。

### Task 2: 组合级结构、实例持久化与执行

**Files:** core/task_sequences.py、sequence_ports.py；application/sequences.py、sequence_driver.py；infrastructure/repositories/sequences.py、sqlite_storage.py；tests/test_task_sequences*.py。

**Interfaces:** 消费 Task 1 的多分支与控制语义；组合叶节点引用 node_id 配置，运行实例通过 execution_path 关联独立子 run_id。补参、重试、核对显式绑定组合实例。

- [x] 先写并运行失败测试：组合条件、foreach、while/until、嵌套与重复任务调用。
- [x] 实现流程校验、运行快照、游标、控制/任务实例及原子创建关联；来源可读当前项、状态、前序任务与控制输出。
- [x] 先写真实组合并行、恢复、暂停取消、第二轮重试及清理测试，再完成驱动与归属保护。
- [x] 运行组合与迁移相关定向测试并独立审核。

### Task 3: 步骤与组合画布接线

**Files:** desktop/components/flow_branches.py、branch_form.py、flow_tree.py、flow_controls.py、step_list.py；presentation/flow_editor.py、sequences.py；desktop/pages/sequences.py；相关 UI 测试。

**Interfaces:** 消费 Task 1、2 的同一条件结构和实例身份；两处均有“允许并行”选项，保存重载一致；组合所有控制结构可编辑。

- [x] 先写表单保存重载、模式切换、分支编辑与组合控制节点的失败测试。
- [x] 实现条件并行开关、结构化组合画布、配置与映射作用域，保留已有草稿和选择保护。
- [x] 运行历史显示分支/轮次、当前等待原因，操作绑定实例；定向 UI 验证与必要本地浏览器验证。

### Task 4: 契约同步、集成审查与验收

**Files:** docs/modules/execution.md、desktop.md、docs/contracts/steps.md、operations.md、architecture.md、tests/module-map.json 及受影响包契约。

**Interfaces:** 源码为当前格式权威，文档记录实际实现与边界。

- [x] 补映射，按实际消费者选择受影响回归，禁止将全量测试拆组执行。
- [x] 覆盖真实并行、资源隔离、循环、故障恢复、人工控制及两处 UI 的验收矩阵。
- [x] 工程检查、git diff --check、独立最终审查；修复重要发现并重新验证。
- [x] 完成交付审计，仅在全部目标有证据时标记目标完成。

## 进度与决策

- 2026-10-27：修正目标已获用户实施授权。仓库当前 main 且有大量已有修改；依用户“沿用当前工作区”规则原地推进，不转移或重置。
- 串行提案的“不并行/历史兼容”被用户本轮要求覆盖；保留现有文件中的参考实现分析，冲突以修正设计首节为准。
- 暂未运行本次功能验证。下一步 Task 1 的失败测试与运行契约实现。

- Task1 已经独立审查与一次修复复审通过；Task2/3 原四项问题及投影表单回归经两次修复复审通过。具体证据保存在本计划本地 progress.md 与测试日志。
- 真实 Chromium 已验证组合画布开关、保存、执行及两子任务成功；实际 NiceGUI 上下文面板已验证所选分支 worker 的采集身份。最终集成回归与全变更审查进行中。

## 最终验证与交付

2026-10-27，修正目标已完成本地实现：步骤与任务组合条件均有“允许并行”；关闭时首个匹配且步骤复用当前资源，开启时执行全部命中路径并等待汇合。组合画布可编辑条件、遍历与 while/until；实际任务调用按分支和轮次分别持久化。

- 最终受影响32个测试模块：279项通过，120.397秒，退出0；日志中的 step.save EDIT_CONFLICT 是既有冲突保护负例的预期诊断。
- 补充第二轮重试实测：1项通过，确认第一轮不重做、第二轮复用原子运行；因此本次最终验证共280项定向测试。
- 最终真实 Chromium：1项通过，4.947秒；实际画布勾选并行、保存、执行并查询两个成功子运行。
- 步骤并行有同一 Run 内实际 worker 动作重叠、不同进程及汇合时序证据；组合并行有独立子任务动作重叠及容量1排队证据。
- 独立审查及修复复审均通过；最终复审确认串行会话、literal业务数据、停止竞争及过期核对四类路径已解决。核心、组合及 UI 原先发现的问题分别补回归验证。
- 当前源工程检查、映射 dry-run、差异及新增文件空白检查通过。未运行全量测试，未执行真实外部业务系统、打包原生窗口或其他平台验收。

本次使用单一当前运行模型，没有新增旧历史执行适配层；保持既有本机数据和工作区修改，未执行 Git 写操作。本地审计与详细日志保留在本计划对应的 .superpowers/sdd 目录，方便继续复核。

## 后续缺陷修复：画布结束位置

2026-10-27 用户反馈结束节点叠入最后步骤。Chromium 单独未复现；本机隐藏 WKWebView 实测复现：100% 六节点直线的结束标记左侧约838.84，最后卡片右侧约998.84，覆盖160像素。根因是 WebKit 的 max-content 测量未计入仅有 flex-basis 的连接线。为共享连接线补 width:40px，保持现有 flex-basis，修正实际内容宽度。

浏览器回归使用真实 FlowTree、主题和编辑器布局，覆盖直线、条件分支、遍历、两档窗口宽度和75%/100%/125%缩放；macOS 同时使用本机 WKWebView，其他平台执行 Chromium。修复前 WKWebView 的原12个布局场景失败，修复后直线、分支、遍历共36个引擎/宽度/缩放组合通过几何断言；连同原流程组件回归共11项测试通过（2.093秒），工程检查、映射 dry-run 与差异空白检查通过。未运行全量测试。
