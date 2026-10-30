# 任务执行流程路径展示实施计划

**目标与已确认方案：** 任务执行的路径展示与步骤管理保持一致，复用流程画布的顺序、分支、循环和连接路径。依据本次对话已审核方案实施。

**实现与边界：** FlowTree 增加只读模式及执行节点渲染入口；ExecutionDetails 使用运行 definition_json 中的 flow 和 steps。无 flow 的历史记录按快照步骤顺序构造展示结构。保留结果、错误、步骤选择、逐轮记录和原进度统计。使用现有 Python/NiceGUI/CSS，不引入依赖或变更执行与持久化协议。

**工作区：** 沿用当前混合工作区，保护已有 UI 改动；本次只增量修改相关文件。按项目约定不执行未经审核的 Git 写操作，不运行全量测试。

## 任务与验收

- [x] 先增加执行详情组件回归：快照顺序、分支及循环布局、旧记录、只读操作、步骤和结果/错误身份、跨轮状态标签；观察原实现失败。
- [x] 在 flow_tree.py 增加可选只读与节点渲染配置，保持步骤管理的默认行为；在 execution_details.py 复用画布，并为跨轮动作明确显示最近一次状态。
- [x] 按需增加执行节点样式；更新 docs/modules/desktop.md 中的当前事实。
- [x] 运行执行详情、流程编辑与分支组件相关定向测试、工程检查及差异检查。
- [x] 使用独立本地 fixture 浏览器核对线性/分支/循环、长步骤、窄窗口与点击入口，保存截图证据。
- [x] 审查本次增量改动及验收证据，记录结果和限制。

## 重点边界

历史图来自运行快照；无尝试的节点显示未执行；未命中分支不推断成功；循环节点保留逐轮结果，最近一次动作状态有明确标签；只读画布没有移动、删除、配置入口；画布自行滚动，长路径不撑破页面。

## 验证记录

- 新增三项主要回归先运行失败（缺少共享画布、分支路径及快照流程顺序），实施后通过；另补充 UNKNOWN/未执行/选中区分及逐轮结果 attempt_id 回归，共五项。
- `uv run python -m unittest tests.ui.test_execution_details tests.ui.test_flow_editor tests.ui.test_flow_tree_branches tests.ui.test_flow_branches tests.ui.test_executions_page -q`：49 项通过。
- `uv run python -m unittest tests.ui.test_step_editor_state tests.ui.test_history_page -q`：37 项通过。步骤保存冲突测试产生预期 EDIT_CONFLICT 日志，测试结果为 OK。
- 扩展检查 `tests.ui.test_run_page` 的两个既有弹窗用例失败：`test_real_dialog_submits_plain_selection_and_input_state`、`test_standalone_dialog_selects_task_then_calls_completion`。它们使用 tests.presentation.test_run_creation.Application，其 task.flow.get 走默认响应（只有 run_id）；现有 executions.py render_inputs 读取 flow.root 时 KeyError。失败在新建弹窗装配阶段，与本次改动的执行画布未相交；本次保留范围外实现与测试。
- `uv run python scripts/check_project.py`、`git diff --check`：通过。未运行全量测试。
- 独立审查：只读检查本次增量，无确定性缺陷；审查者复跑五项新组件测试通过。
- 独立组件浏览器：线性历史快照和分支/遍历/条件循环、九个长名称节点、选择/结果/错误及本轮结果入口均通过；1440px、650px 页面无横向溢出，画布可滚动至结束，无浏览器 pageerror。
- 真实应用浏览器：独立临时 home 中创建并真实运行线性九步及条件/循环任务，两条执行成功，各九次动作。实际执行页面的流程、未执行出口、逐轮记录、步骤选择、保存结果弹窗及本轮结果弹窗通过；1440px/650px 的 documentWidth 分别等于视口宽度，画布内部滚动正常。没有真实外部服务或业务账号验收。
- 浏览器证据目录：`/Users/xiaojuju/.codex/visualizations/2026/10/24/01a16d81-4956-7a23-99b2-abc6f1eb7d29/execution-flow/`。workbench-report.json 记录实际页面检查；workbench-{structured,linear}-{1440,650}.png 为实际页面截图；report.json 及其余四张截图为独立组件检查。
- 验收脚本首次创建本地 worker 时因未加 multiprocessing 主入口保护而中断；补充保护后在新的独立临时 home 重建，两条真实执行成功。此问题仅在临时验收脚本，产品代码无对应变更。
- 本次文件增量：flow_tree.py、execution_details.py、theme.py、test_execution_details.py、desktop.md 与本计划。已有其他修改保持原位。

## 2026-10-24 补齐实际执行路径（用户已确认继续）

前轮完成的是共享结构画布，尚未把实际分支选择投影到连线。本轮验收以实际运行记录为依据：经过的入口和出口分别标记，失败节点之后的连线不标为已走；已判定但未选中的分支显示未命中，尚无判定记录的分支显示尚未判定。控制判定失败也不推断未命中。

- [x] 新增无 GUI 的执行路径投影，以 execution_path、有效动作尝试、控制访问和已完成轮次推导状态；不重新计算业务条件。定向测试覆盖失败阻断、空路径、首个匹配、轮次混合、零轮循环与历史线性记录。
- [x] FlowTree 增加可选路径状态，标记顺序连线、分支入口/出口及循环返回；默认编辑画布行为保留。多出口仍使用现有无损 if 链展开。
- [x] 执行详情接入投影、图例和循环轮次视角；所选轮次内的节点结果/错误绑定对应尝试，其余节点保持汇总。按运行保留视角，保留原进度、历史、日志、输入、快照及执行操作。
- [x] 更新模块知识和测试映射，运行路径投影、画布与执行组件回归、工程及差异检查。
- [x] 在独立真实运行数据中浏览器核对命中/未命中/尚未执行、混合轮次切换、失败边界、原结果错误入口和窄窗口，保存证据并独立审查。

路径汇总表示已记录轮次的累计事实，循环轮次选择仅限定对应循环及嵌套路径，不把一轮选择视为所有轮次选择。没有记录时保留未知/未执行，避免补造历史路径。所有已有修改保持原位。


### 本轮最终验证与审查记录

- 实现文件：新增 presentation/execution_paths.py；FlowTree 使用可选 paths 投影，默认编辑画布保持原行为。执行页保留完整运行记录与操作，仅节点视角随路径轮次变化。
- 连线以实际到达目标和前驱完成为依据；部分执行成功不会标记未到达的流程终点。循环返回表示当前轮到下一轮已实际进入的路径，末轮退出不会标记为继续循环。
- 独立审查发现并修复 P2：真实控制错误持久化到节点路径的 /$error，原投影没有识别；现在结合该错误记录和活动 cursor.frames 标记节点到达，保留未判定分支及未完成出口。新增两项对应回归先失败后通过。
- SVG 分支覆盖层按实际行几何绘制完整转折连线，尺寸变化重绘，移除时解除观察；已走过的共享线段最后绘制。新增断言先失败后通过。独立审查该新增覆盖层后未发现确定性缺陷。
- `uv run python -m unittest tests.presentation.test_execution_paths tests.ui.test_execution_details tests.ui.test_flow_tree_branches tests.ui.test_flow_editor tests.ui.test_flow_branches tests.ui.test_executions_page tests.ui.test_step_editor_state tests.ui.test_history_page tests.test_execution_interactions -q`：108 项通过。步骤保存冲突用例的预期 EDIT_CONFLICT 日志不影响 OK 结果。没有运行全量测试；前轮记录的两项新建弹窗测试替身问题保持原位，本轮未重跑或修改它们。
- 新增15项普通投影测试覆盖轮次汇总/选择、嵌套作用域、无损 else-if 展开对应路径、空路径、零轮循环、控制判定失败、活动游标、旧线性尝试、失效尝试、从中途开始与部分执行终点。执行组件新增失败边界和真实轮次选择事件回归，核对结果/错误尝试身份；无 socket 的组件测试替代浏览器 JavaScript 边界，实际 SVG 在浏览器验证。
- 真实应用浏览器使用五条独立本地运行：多轮不同分支成功、判定前动作失败、零轮循环成功、线性首步失败、条件类型错误失败。八个页面状态和原结果/错误入口、节点选择后轮次保留、日志/结果/输入/快照页签切换通过；逐轮结果身份同时由组件回归验证；SVG 路径数、蓝色 stroke 和实际长度均验证。1440px、650px documentWidth 等于视口宽度，无页面横向溢出或 pageerror。
- 额外浏览器几何检查：将分支卡片最小高度从240px改到84px，SVG 转折端点持续与实际分支中心对齐；切换运行移除覆盖层后重建正常，无 pageerror。
- `uv run python scripts/check_project.py` 与 `git diff --check`：通过。
- 本轮证据目录：`/Users/xiaojuju/.codex/visualizations/2026/10/24/01a16d81-4956-7a23-99b2-abc6f1eb7d29/recorded-execution-paths/`；report.json 为实际页面验证，geometry-report.json 为尺寸与重建验证，PNG 为各状态截图。使用独立临时 home、纯本地动作和真实 worker/数据库；不据此声称外部业务系统或其他平台验收。
- 收尾：本轮独立验收服务已停止，证据和临时数据保留；没有操作业务工作空间。
