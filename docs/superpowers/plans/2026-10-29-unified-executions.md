# 统一执行实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 当前用户已授权直接实施，当前主 Agent 串行执行，所有已有修改保留；无 Git 写操作。

**Goal:** 在执行页统一管理任务与组合，组合编辑仅支持编排和独立调试。

**Architecture:** 沿用任务执行及组合调度，查询投影合并顶层正式运行，共用组合详情组件处理正式与调试控制。调试模式存入组合快照并传递至全部子运行，不新增 SQL 结构。

**Tech Stack:** Python、uv、NiceGUI、SQLite。

**Spec:** `docs/superpowers/specs/2026-10-29-unified-executions-design.md`

## Global Constraints

- 使用当前混合工作区，保护已有修改和数据；不提交、推送或写 PR。
- core/application/presentation 不依赖 GUI；调试不产生 EXECUTION 子运行。
- 只执行受影响定向测试；全量测试需明确授权。

## Review Focus

- 同一任务的独立运行和组合子运行同时存在时，只隐藏子运行。
- 仅有组合、筛选无匹配、切换选中记录时列表正常，异步旧响应不覆盖选择。
- 重复任务、循环和并行路径的重试/补参明确定位节点实例。
- 组合调试运行整个任务流程，不因步骤调试目标提前结束循环。
- 删除只清理所选组合及其子记录；正式/调试命令身份不串用。

### Task 1: 组合调试与运行归属

**Files:** application/sequences.py、application/sequence_driver.py、application/operations.py；infrastructure/repositories/runs.py、sequences.py；core/run_ports.py；tests/test_task_sequences.py。

**Interfaces:** 新增 `sequence.trial`，复用现有启动参数；`prepare_start(..., mode='EXECUTION')` 冻结模式，仓储 `create_run(..., trial=False)` 提供完整任务调试。run.list 返回组合归属。

- [x] 先增加真实 worker 用例：未确认任务组合调试、完整循环、正式模式隔离及命令幂等冲突；运行并确认失败。
- [x] 实现模式传播、启动校验与归属，执行上述测试确认通过。

### Task 2: 统一执行列表、启动与组合详情

**Files:** presentation/execution.py；desktop/pages/executions.py、sequences.py；desktop/components/execution_details.py、新增 sequence_execution.py；desktop/workbench.py；相关 presentation/UI 测试。

**Interfaces:** `ExecutionInteraction.load_rows` 合并顶层任务与组合；组合投影保留 sequence_run_id 并设置 execution_kind；共用 `SequenceExecution` 展示和控制节点。编辑页默认调试，正式启动回到执行页选择组合。

- [x] 先写列表、筛选、异步切换、组合编辑调试及正式启动测试，确认旧行为失败。
- [x] 实现合并查询和组件拆分，删除子运行独立入口，补齐日志/结果和实例控制；执行定向 UI/查询测试。

### Task 3: 文档、集成验证与复核

**Files:** docs/modules/execution.md、docs/contracts/operations.md、docs/maintenance.md；tests/module-map.json；受影响测试。

- [x] 同步当前知识及测试映射；定向验证正式组合、调试、删除、重试生命周期。
- [x] 执行工程检查和本次差异检查，逐条复核验收条件并记录实际结果、失败和限制。

### Task 4: 浏览器步骤自动截图（用户追加范围）

**Files:** core/result_views.py；infrastructure/worker.py、storage.py；plugins/playwright/ 的 browser_actions.py、results.py、plugin.py；desktop/components/result_viewer.py；结果、插件与浏览器定向测试。

**Interfaces:** 可选插件 `result_artifacts(ctx, result)` 返回仅有 outputs/views 的 StepResult；图片 view 支持 `output` 与 pointer 互斥，引用同次图片结果。Playwright 仅截图该步骤实际涉及的页面，最多 8 页，每页 3 秒，失败保留告警。

- [x] 先增加输出引用 view 与真实 Chromium 正式/调试截图测试，观察缺少截图的失败。
- [x] 实现自动截图和持久化展示，保持业务数组/标量不变；真实测试通过。
- [x] 追加异常、重名、查看器、失败诊断回归并同步契约。

## 完成记录

- Task 1–4 已完成：组合正式启动/管理统一进入执行；子执行收进详情；组合编辑只编排和调试；实际页面步骤成功和失败均追加保存截图及图片 view。
- 已通过 145 项范围内的主回归；后续删除恢复/页面测试 26 项、截图/仓储/查看器测试 10 项通过（与主回归有重叠，不合计为唯一用例数）。
- 最终真实 Chromium 验证 3 项通过：统一组合正式启动、子详情、调试隔离和删除范围；正式/调试自动截图保持业务数组不变；失败截图持久化及 view 引用一致且不生成成功回执。
- `uv run python scripts/check_project.py`、`git diff --check` 通过；新增源码及测试的模块映射 dry-run 通过。未运行全量测试。
- 初次 UI 回归发现拆分后的测试仍使用旧组件方法/标签，以及启动对话框替身缺少现行任务流程/Schema；已将测试转至共用组件及实际启动表单后通过。
- 独立只读复核发现并修复：切换记录后的控制弹窗旧响应、失败截图目标/展示声明，以及无成功回执的诊断图片命名。修复经 red→green 验证；最终复核无剩余重要发现。
- 删除中断后由 cleanup 清单保持子运行归属，提供“重试删除”；相关生命周期回归通过。
- 未操作真实业务记录，未重启用户应用，未进行 Git 写操作或发布构建。新增截图仅对后续执行生效；页面关闭、截图超时及多页面上限保留明确警告。
