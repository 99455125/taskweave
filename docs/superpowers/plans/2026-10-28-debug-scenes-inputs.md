# 调试现场与结构化录入 Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development / executing-plans. 沿用用户指定工作区；本次不执行 Git 写操作。进度和验证维护在本文。

**Goal:** 完成已确认的实例选择、流程调试修复、实际路径展示、数组逐行录入四项。
**Architecture:** 复用 worker 资源现场并按物理现场串行调度；新试跑保留自身结果归属。现有 Schema 和路径投影作为表单和显示的共同依据。
**Tech Stack:** Python、uv、NiceGUI、unittest；不引入依赖。
**Spec:** 本计划的目标及四项任务定义实施范围。

## Global Constraints

- 保留所有已有修改；当前工作区继续使用，不修改共享任务 workspace。
- core/presentation 保持既有依赖边界；运行操作不调用模型。
- 不新增旧配置兼容或自动迁移；不执行 commit、push、PR 写操作；定向验证。

## Review Focus

- 跨任务复用场景，结果归属 B，A 的历史输出仍在。
- 现场被占用/过期或有未处理录制时，启动前拒绝，不能误开新现场。
- 显式结果来源缺失时直接报错，不能回退其他历史。
- 部分试跑和跳过分支不能显示虚假的已完成路径。
- 数组无默认值、空数组、非法数字及草稿恢复不丢用户填写内容。

### Task 1: 现场选择与前序结果

Files: application/steps.py、infrastructure/coordinator_pool.py、run_coordinator.py、worker_transport.py、desktop/controller.py、components/debug_drawer.py、step_debug.py、presentation/state.py；新增定向集成/UI 测试。
Interfaces: step.trial 增加可选现场参数；step.trial.sessions 枚举可用资源；controller.trial 接受明确来源运行和路径。共享物理 transport 的执行互斥，记录本次试跑的来源。
- [x] 先写跨任务复用同一资源、串行保护、显式新建、失效现场及结果来源测试并观察失败。
- [x] 实现主机资源复用和一行选择，输入绑定优先显式样本，结果存储归新 run。
- [x] 运行定向测试，记录结果。

### Task 2: 流程调试入口

Files: application/steps.py、desktop/components/step_debug.py；tests/ui/test_step_debug_session.py、定向 flow trial 测试。
Interfaces: 受控流程从根到目标不传 start_step_id；非法中段在写入前拒绝。
- [x] 写条件流程首步/非法中段、线性起点回归并观察失败。
- [x] 修复前置验证和实际入口，运行定向测试。

### Task 3: 调试路径视图

Files: 新共享 desktop/components/debug_paths.py，step_debug.py 接线；tests/ui/test_debug_paths.py。
Interfaces: render_debug_paths(run, steps) 消费冻结定义和 ExecutionPaths；单步构造实际单动作范围。
- [x] 写空分支、历史定义、单步范围和轮次选择测试并观察失败。
- [x] 复用 FlowTree / ExecutionPaths 呈现，运行定向测试。

### Task 4: 数组对象逐行录入

Files: desktop/forms.py、新数组编辑组件及 presentation 表单辅助、相关输入解码；tests/ui/test_array_inputs.py。
Interfaces: ValueForm 保持 controls/value/change 契约，支持同构 object.items 的行编辑及原始草稿；复杂 Schema 使用现有 JSON。
- [x] 写增删行、字段约束、空数组/可选项及调试/补录草稿测试并观察失败。
- [x] 实现组件并接入公共输入表单；运行定向测试。

## 进度

已复查当前混合工作区，保留现有内容。主 Agent 负责现场调度、共享接线、文档和集成；数组组件独立负责文件，路径组件独立负责文件，公共接线由主 Agent 串行完成。用户已授权按四项实施，沿用当前分支；不重复执行计划审核门禁。

## 执行记录（延续至 2026-10-29）

- Task 1：现场枚举、新建和跨任务复用已接线；同物理现场及所属分支用层级锁保护执行、采集、结束、删除及清理。新试跑保存现场来源，输出仍归新任务；显式结果来源运行/轮次不回退到历史输出。
- Task 2：受控流程首起点归一为从根推进，中段非法起点在创建记录前拒绝；UI 根据真实流程提供入口，选定现场也用于受控流程的外层资源路径。
- Task 3：调试区已接入冻结定义、实际动作/分支/轮次投影。
- Task 4：同构对象数组支持标量及简单字符串列表；枚举列表多选，其他字符串列表逐项增删。可选默认值展示，非法布尔/数值/列表及扩展字段草稿保留，提供行字段错误定位。
- 用户追加的启动输入：StartupInputDraft / StartupInputs 覆盖单任务全部步骤、组合全部调用节点。按任务节点/步骤折叠，填充值按身份冻结，空白必录留给运行时补参；切换任务、环境及起点保留草稿。执行选择入口可选择组合，独立启动视图保留已有组合编辑草稿。组合高级启动 Schema 的现行校验独立保留。
- 独立审核复现并修复：非法布尔草稿重建失败、共享分支现场被原运行结束、恢复结果路径未回显、显式现场未列入采集列表、组合本地/固定默认值被任务自动映射误隐藏。集成补查复现并修复了受控流程未采用所选外层现场；各修复有针对性 RED→GREEN 证据。
- 验证使用临时目录、本地保留资源及 NiceGUI 内存组件；没有启动 Workbench、浏览器或业务服务，没有操作共享示例 workspace。本次不执行 Git 写操作，不运行全量测试。

本次验证：24 个定向测试模块共 138 项通过（`uv run python -m unittest`，完整目标见下）；随后补查组合资源回收与共享现场的并发占用，回归先失败后修复，相关现场/组合 21 项通过。工程检查、`git diff --check`、新增模块映射 dry-run 均通过。源码可由使用者重启原工作台加载；本轮没有重启用户工作台。完整测试入口仍统一维护在 tests/module-map.json。

138 项运行目标：`tests.test_debug_scenes`、`tests.test_scene_reservations`、`tests.ui.test_debug_sources`、`tests.ui.test_debug_paths`、`tests.ui.test_array_inputs`、`tests.presentation.test_startup_inputs`、`tests.ui.test_startup_inputs`、`tests.test_sequence_startup_inputs`、`tests.ui.test_sequence_startup_inputs`、`tests.ui.test_execution_entry`、`tests.ui.test_sequence_execution_entry`、`tests.ui.test_step_debug_session`、`tests.test_runtime_inputs`、`tests.test_trial_variable_groups`、`tests.test_context_targets_runtime`、`tests.test_flow_parallel_context`、`tests.presentation.test_run_creation`、`tests.ui.test_executions_page`、`tests.test_task_sequences`、`tests.test_task_sequences_storage`、`tests.ui.test_run_input_validation`、`tests.presentation.test_debug_inputs`、`tests.presentation.test_input_dialog`、`tests.application.test_dispatch_policy`。21 项补查命令为 `uv run python -m unittest tests.test_debug_scenes.DebugScenes.test_shared_scene_rejects_concurrent_run_and_context_mutation tests.test_task_sequences tests.test_sequence_startup_inputs -q`；范围内负向用例的 `OUTPUT_NOT_AVAILABLE` 日志是预期失败断言，测试结果为 OK。
