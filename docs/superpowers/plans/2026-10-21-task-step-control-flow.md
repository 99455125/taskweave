# 任务步骤控制流与编辑界面实施计划

## 2026-10-22 复审状态

用户要求重新审查编排与现有系统的适配并重设计。代码复审、6 项问题及推荐方案统一维护在[原设计文档的复审章节](../specs/2026-10-21-task-step-control-flow-design.md)。以下已勾选项记录上一轮实施过程，不代表本轮复审问题已修复。

- [x] 审查流程定义、顺序、保存、复制、执行、调试输出与任务组合接线，完成临时库/真实 worker 最小复现。
- [x] 提出保留任务组合分层、统一任务内定义与执行语义的重设计，记录迁移约束与验收条件。
- [ ] 用户审核重设计；审核后按同一方案细化本文件中的后续实施任务。
- [ ] 实现并验证复审修订。产品代码本轮尚未修改，R1–R6 尚未修复。

## 上一轮实施记录

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. The user delegated product decisions to Astra. Git commit, push, PR writes and deployment are not authorized.

**目标：**让一个任务可配置结果分支、条件循环、列表遍历，并在更清爽的步骤页面完整编辑、运行和查看逐轮结果。

**架构：**`graph_json` 承载结构化流程树；每次动作出现有独立执行路径和持久化控制实例。纯核心模块负责结构、条件与作用域校验；仓储负责定义版本、实例和游标的原子更新；运行器驱动现有 worker；桌面流程树与控制表单调用同一应用操作。

**技术栈：**Python 3.10+、uv、SQLite、NiceGUI、unittest、现有 worker/插件 SDK。

**规格：**[任务步骤控制流与编辑界面设计](../specs/2026-10-21-task-step-control-flow-design.md)

## 全局约束

- 保留旧任务、线性执行、单步调试、中间重跑、任务组合及插件 SDK 的现行行为。
- 流程最大嵌套深度 8；条件循环上限默认 100、可配置 1–10,000；列表遍历默认 1,000、可配置 1–10,000；运行最多 100,000 次动作尝试；控制推进每批最多 128 条访问事实、单运行最多 1,000,000 条。
- `run.output` 默认返回完整聚合；现有任务组合 JSON Pointer 仍作用于完整返回值，逐项投影需新显式字段。
- UNKNOWN 和不确定副作用必须人工核对，不自动重发；用户已有工作区修改原样保留。
- 每项运行针对性测试；不运行全量测试。Git commit、push、PR 写入和部署待独立授权。

## 审查重点

1. 同一动作在不同迭代路径的成功记录必须分别生效，重试不能向聚合追加两次。
2. 缺失路径：`exists` 为 false，其他条件报错；布尔值不能参与数字大小比较。
3. 空列表、零轮循环和分支跳过产生正确形状，业务数组不被误认成循环层级。
4. 崩溃发生在动作成功与游标提交之间时不得重新执行已产生副作用的动作。
5. UI 保存冲突或离页后，流程草稿与动作草稿都不能覆盖他人的版本。

## 任务 1：流程树与纯条件语义

**文件：**新增 `src/taskweave/core/task_flow.py`；修改 `src/taskweave/core/validation.py`；新增 `tests/test_task_flow.py`。

**接口：**`normalize_flow(graph: dict, steps: list[dict]) -> dict` 将旧线性图转换为结构化根序列；`validate_flow(flow: dict, steps: list[dict]) -> None` 检查唯一位置、引用、嵌套深度和上限；`evaluate_condition(condition: dict, read: Callable) -> bool` 实现严格类型与缺失规则；`is_linear_flow(flow: dict) -> bool` 按结构判断兼容行为。

- [x] 先写旧线性转换、嵌套结构、重复动作、无效引用和深度边界失败用例；运行 `uv run python -m unittest tests.test_task_flow -v`，确认新用例失败。
- [x] 实现流程归一化和结构校验；重跑该模块，确认通过。
- [x] 写 `exists`、`empty`、类型比较及缺失路径用例；先确认失败，再实现条件求值并确认通过。`while`/`until` 运行真值由任务 4 覆盖。

## 任务 2：定义保存、确认与任务包兼容

**文件：**修改 `src/taskweave/infrastructure/sqlite_storage.py`、`src/taskweave/infrastructure/repositories/steps.py`、`tasks.py`、`src/taskweave/application/tasks.py`、`runs.py`、`operations.py`、`src/taskweave/application/task_transfer.py`、`src/taskweave/core/task_package.py`；新增或扩展 `tests/test_task_transfer.py`、`tests/repositories/test_task_repository.py`、`tests/test_control_db_migration.py`。

**接口：**`TaskRepository.save_flow(task_id, flow, expected_hash) -> dict` 原子检查任务定义版本并保存流程草稿；`confirm_flow(task_id, expected_hash) -> dict` 静态校验后确认；`TaskUseCases.flow/ save_flow/ confirm_flow` 暴露操作。先迁移任务级流程确认字段，再启用正式 `run.create/start` 门禁，任务组合子运行也走同一门禁。步骤保存、移动、删除只更新关联流程位置，不重建树；任务复制和新版包导入导出重映射节点引用。

- [x] 先写迁移保留旧任务、保存冲突、控制变更使整体确认失效、正式启动门禁、动作正文更新保留控制结构、线性旧包导入和新版包往返用例；确认失败。
- [x] 实现定义仓储和确认操作；保持旧线性任务不增加确认负担；运行上述定向测试。
- [x] 实现任务复制、导入导出与新版格式拒绝误读；运行 `uv run python -m unittest tests.test_task_transfer tests.repositories.test_task_repository -v`。

## 任务 3：执行实例与控制状态持久化

**文件：**修改 `src/taskweave/infrastructure/sqlite_storage.py`、`src/taskweave/infrastructure/sql/control.sql`、`src/taskweave/infrastructure/repositories/runs.py`、`results.py`、`src/taskweave/infrastructure/repositories/__init__.py`、`src/taskweave/application/composition.py`、`src/taskweave/core/run_ports.py`；新增 `src/taskweave/infrastructure/repositories/flow_runs.py`、`tests/test_flow_storage.py`；更新 `tests/test_control_db_migration.py`。

**接口：**`FlowRunRepository` 持久化 `(run_id,node_id,execution_path)` 控制/动作实例、游标、冻结列表及决策，并由仓储装配/应用组合注入；`create_attempt(..., execution_path=...)` 允许每个实例独立编号；`read_attempt_output(attempt_id, output, registry)` 精确读取结果；`commit_transition(run_id, expected_cursor, transition) -> bool` 同一控制库事务保存实例状态与下一游标；`retry_instance(run_id, execution_path)` 只失效目标实例及其后续控制事实，不能调用旧的按 `step_id` 批量失效接口。

- [x] 先写迁移保留旧数据、同一步骤多实例隔离、同实例重试与游标幂等提交，以及“第 3 轮失败重试保留第 1、2 轮结果”用例，确认失败。
- [x] 实现控制库新版本和实例仓储，保持旧数据可读；运行 `uv run python -m unittest tests.test_flow_storage tests.test_control_db_migration -v`。
- [x] 通过精确 attempt 读取验证 JSON 输出及旧 `run.output` 行为，运行结果仓储相关定向测试。

## 任务 4：纯流程推进与聚合

**文件：**新增 `src/taskweave/core/flow_machine.py`、`src/taskweave/core/flow_values.py`、`tests/test_flow_machine.py`。

**接口：**`next_action(flow, cursor, read_value) -> FlowTransition` 顺序推进控制块并产出待执行动作或终态；`advance_after_action(...) -> FlowTransition` 在成功输出后计算下一位置；`aggregate_output(flow, visits, step_id, output, item_pointer=None, loop_node_id=None) -> object` 按执行路径聚合。

- [x] 写双分支汇合、空列表、重复列表项、零/多轮 `while`、至少一轮 `until`、嵌套及跳过占位用例，确认失败。
- [x] 实现纯流程机，决策与循环状态作为显式持久化 transition 输出；运行 `uv run python -m unittest tests.test_flow_machine -v`。
- [x] 写聚合、逐轮投影、缺失输出及超限用例，确认失败后实现并重跑同一模块。

## 任务 5：结果作用域与统一读取

**文件：**修改 `src/taskweave/infrastructure/repositories/results.py`、`src/taskweave/core/validation.py`、`src/taskweave/application/runs.py`、`src/taskweave/core/run_ports.py`；通过 `tests/test_flow_execution.py`、`tests/test_flow_machine.py` 验证。

**接口：**步骤引用可指定循环 `node_id` 与 `item_pointer`；执行实例作用域解析内层当前轮、外层已完成值及循环外完整聚合。`run.output` 默认完整聚合，新增显式实例选择参数；旧 `pointer` 仍指完整返回值。运行器只调用该统一读取接口，不复制结果缓存。

- [x] 按真实 worker 测试覆盖同轮与跨轮读取、嵌套聚合、跳过占位、完整结果、精确执行路径和逐项投影；测试归入 tests.test_flow_execution 与 tests.test_flow_machine。
- [x] 实现统一结果解析及运行、步骤绑定、任务组合三处接线，并运行对应定向测试。

## 任务 6：运行器、恢复和控制命令

**文件：**新增 `src/taskweave/infrastructure/flow_runner.py`；修改 `src/taskweave/infrastructure/run_coordinator.py`、`repositories/runs.py`、`src/taskweave/application/composition.py`、`runs.py`、`sequences.py`、`sequence_driver.py`、`src/taskweave/core/task_sequences.py`、`src/taskweave/core/run_ports.py`；新增 `tests/test_flow_execution.py`、`tests/test_flow_recovery.py`，扩展 `tests/test_task_sequences.py`。

**接口：**`FlowRunner.drive(run_id, mode, target_step_id)` 使用定义快照、注入的流程仓储与现有 `_attempt`/worker；`NEXT` 计一个实际动作实例，`UNTIL` 寻找下一次可达目标；失败重试必须携带执行路径。命令指纹、最新尝试查询、成功判断、输入等待身份、worker 请求、结果回执和运行详情均传递执行实例身份；旧命令不能唯一定位实例时拒绝而非猜测。控制节点错误记录控制实例，UNKNOWN 仍使用现有人工核对入口。任务组合创建/启动子运行复用流程确认门禁；旧映射 `pointer` 仍读取完整聚合，新 `item_pointer` 才逐项投影。

- [x] 用真实 worker 覆盖分支、循环、遍历、补参、失败重试、控制上限和任务组合子运行。
- [x] 集成流程运行器，并验证同批控制结果可见、控制推进分批提交、暂停取消及租约心跳。
- [x] 验证动作结果与游标之间的恢复边界，不重复已成功动作；执行恢复定向测试。
- [x] 验证任务组合完整聚合与显式逐项投影，运行任务组合定向测试。
- [x] 验证旧线性 NEXT/UNTIL、中间重跑和人工核对，执行 execution_control 定向回归。

## 任务 7：流程树和步骤编辑界面

**文件：**新增 `src/taskweave/desktop/components/flow_tree.py`、`flow_controls.py`、`src/taskweave/presentation/flow_editor.py`；修改 `src/taskweave/desktop/components/step_editor.py`、`step_list.py`、`src/taskweave/desktop/pages/tasks.py` 及相关样式；新增 `tests/ui/test_flow_editor.py`，扩展现有步骤页面测试。

**接口：**流程树选择稳定 `node_id`；动作沿用现有 `StepEditor` 的保存、草稿、AI、采集和调试入口；控制表单覆盖分支公共输出、循环状态初始值与更新映射、带所属循环身份的 `item/index/state` 变量及跨循环投影，并提交任务级版本检查。流程整体确认入口固定可见。主操作固定可见，其他原操作仍可发现。

- [x] 记录原步骤入口，覆盖流程树增删移、控制表单和编辑状态的组件测试。
- [x] 实现流程树、控制表单和动作编辑分区，运行 flow_editor 及受影响 UI 定向测试。
- [x] 实际浏览器创建、编辑、确认列表遍历，并检查嵌套分支树与原步骤操作入口。

## 任务 8：运行呈现、知识同步与最终验证

**文件：**修改 `src/taskweave/desktop/components/execution_details.py`、调试/输入相关组件、`docs/contracts/steps.md`、`docs/modules/execution.md`、`docs/modules/tasks.md`、`docs/README.md`、`tests/module-map.json`；新增或扩展运行 UI 测试。

- [x] 实现逐轮历史、分支选择、控制错误、聚合结果及中间重跑提示；运行相关 UI 测试。
- [x] 实际浏览器查看一次列表遍历加分支的完整运行记录，核对两轮结果和决策展示。
- [x] 按映射审阅定向测试范围，运行定向回归、工程检查与 git diff --check；记录未执行全量测试。
- [x] 请 Astra 只读审查最终差异并修复其发现的阻断点；本地交付，不执行未经授权的 Git 写操作。
