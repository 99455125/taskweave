# 代码映射（已实施并验收）

| 当前 | 目标职责 |
|---|---|
| infrastructure/repository.py、storage.py | repositories/tasks.py、steps.py、environments.py、runs.py、results.py、step_contexts.py；旧路径为显式兼容层 |
| infrastructure/plan_repository.py | repositories/plans.py、plan_contexts.py、plan_generations.py；旧类为显式兼容层 |
| storage.py transaction | unit_of_work.py / 同连接绑定 |
| application/service.py | facade/装配 + tasks/steps/environments/runs/contexts/operations |
| desktop/workbench.py | 外壳 + pages/ + components/ + 显式状态 |
| desktop/planning.py | 独立规划页面/状态，既有路径可兼容 |
| tests/test_workbench_changes.py 等 | 保留有效测试并迁到 tests/ui 各组件 |
| docs/testing.md | 模块映射、依赖传播、定向命令 |

阶段 A 已实现映射：`infrastructure/unit_of_work.py` 提供共享事务绑定；`infrastructure/repositories/` 下九个领域仓储承接任务、步骤、环境、运行、结果、步骤上下文、计划、计划上下文及生成记录。`Repository.repositories` 显式暴露这九个对象；`Repository`、`PlanRepository` 与 `Store` 的旧入口保留同签名委托和低层 query/execute/transaction 桥接。存储迁移及版本未变。

阶段 A 复审返修：仓储构造集中于 `repositories.build_sqlite_repositories()`，注入必需领域端口；`core/repositories.py` 描述窄端口；`tests/repositories/test_repository_wiring.py` 覆盖端口替换、直接组合复制与跨域回滚；三个计划仓储拆分模块分别由 `test_plan_metadata_repository.py`、`test_plan_context_repository.py`、`test_plan_generation_repository.py` 实际调用。

具体文件及旧测试迁移映射已由原 Luna 补充，指定 supervisor 逐阶段复审，架构师终验见 [最终验收记录](final-acceptance.md)。

## B 阶段实施映射 · 2026-09-25（supervisor 复审通过）

| 旧职责/调用 | 当前职责 |
|---|---|
| `infrastructure/runtime.py` 中 Coordinator/Pool 的控制库 SQL 与仓储门面调用 | 经 `RunRepository` 语义操作；任务/步骤/环境定义读取分别经 `TaskRepository`、`StepRepository`、`EnvironmentRepository`，结果读取/回执经 `ResultRepository`；home/task 数据根显式注入 |
| Application 装配 CoordinatorPool | `application/service.py` 仅组合运行、任务、步骤、环境、结果端口及 home；协调器不持有完整 Repository |
| PlanningService 通过 TaskUseCases 内部仓储、PlanRepository.root 读取数据/路径 | 直接注入 StepRepository、StepContextRepository 与 `plan_files_root`；Application 配置路径保持 `home / 'plans'` |
| ContextSessions 从计划仓储读取 root | Application 显式传 `plan_files_root`；会话仅依赖计划/环境端口及配置目录 |
| DesktopController 通过 `application.repo` 读取运行输入、请求、环境及输出 | 经 Runs 用例查询；保留 `run.get` 的原有 `request_json` 内容且不新增顶层 `inputs_json` |
| `tests/test_architecture_boundaries.py` 与 `scripts/check_project.py` | 覆盖 Coordinator/Pool 无直接 SQL、Application 无内嵌 SQL、DesktopController 不读 `application.repo`，并验证 core 依赖方向 |

B 的其余映射与复审证据见 [validation.md](validation.md)。阶段 B 独立审核通过；整体状态见最终验收记录。

## C 阶段实施映射 · 2026-09-25（独立复审通过）

| 旧职责/调用 | 当前职责 | 状态 |
|---|---|---|
| `Workbench.button` 中的全局 busy 与调试按钮副作用 | busy/恢复由 Workbench helper 统一管理；调试失败和结束状态通过显式回调 | 已实施并有行为测试 |
| 步骤列表渲染、选择、排序、删除与批量确认 | `desktop/components/step_list.py`；显式 controller/button/导航/保存/动画回调 | 已提取，当前有行为测试 |
| 步骤文档生成与串行草稿保存 | `desktop/components/step_editor.py` + `StepEditorState`；Workbench 提供显式兼容委托 | 已提取，排队/迟到保存有行为测试 |
| 上下文组/采集项 CRUD、采集与预览 | `StepContextPanel`；Workbench 只委托操作 | 组件持有采集草稿、列表刷新和预览流程 |
| 执行详情、运行补录输入、调试变量面板、结果展示 | `ExecutionDetails`、`RunInputDialog`、`TrialInputPanel`、`ResultViewer` | 已组合；环境切换非校验保留原始草稿，提交仍严格校验 |
| Tasks/Environment/Executions/History/Plugins/Settings/Marketplace/Planning 页面 | `desktop/pages/` 页面对象经 controller 与回调组合 | 已组合；部分页面生命周期仍由 Workbench 管理 |
| 编辑器渲染与子组件装配 | `StepEditor.render(StepEditorRenderContext)`；StepEditor 保存自身 view handles，Debug/AI/Contexts 子组件由编辑器组合 | 已提取，未再由 Workbench 镜像控件 |
| 调试运行生命周期、完整刷新与反馈渲染 | `components/step_debug.py` 的 `StepDebugSession` / `StepDebugPanel`；Workbench 保留显式兼容委托 | 已提取；异步阶段核对 task/step/run/页面代次 |
| AI 步骤内容生成、修复、候选预览及网页 Chat 草稿 | `components/step_ai.py` 的 `StepAIEditor`；调用前保存草稿，响应按目标身份校验 | 已提取，含迟到响应行为测试 |
| 正式运行列表与详情刷新 | `pages/executions.py` 的 `RunPage` + `ExecutionDetails`；组件持有刷新 timer | 已提取；浏览器验收曾捕获并修复页面 getter 条件导致的轮询停用 |
| 页面定时器/绑定生命周期 | 页面统一实现 `render()` / `dispose()`；Workbench 在获准离页或重绘时释放页面资源 | 包含 PlanningPage；有 timer 释放及导航行为测试 |

C 定向验证、已知基线限制与未覆盖项见 [validation.md](validation.md) 和 `.superpowers/sdd/req010-ui-components/progress.md`。指定 supervisor 已签署阶段 C 通过；D 独立复审及 leader 整体验收均已完成。

## D 阶段模块测试映射 · 2026-09-25（D-R1 关闭，独立复审通过）

| 模块职责 | 源码映射 | 快速 targets / 可选 browser targets |
|---|---|---|
| domain.tasks/steps/contexts | `src/taskweave/core/` 的任务包、校验、上下文值对象 | `tests/module-map.json` 明确列出功能测试 |
| repository.* | `infrastructure/repositories/*.py`，共享 SQLite/UoW 分开映射 | 仓储契约与真实临时 SQLite 测试；consumer → prerequisite 闭包对应 §17 |
| application.* | 用例文件；`operations.py` 映射到所有受影响用例，环境用例独立为 `application.environments` | dispatch、HTTP、迁移/任务运行及规划/AI 测试 |
| ui.* | pages/components 与共享 Workbench/UI 边界 | 组件快速测试；`test_input_ui` 与工作台流程列为显式 browser targets |
| shared.* / plugins.* | storage、contract、UI 与 selector 自身；插件包单独映射 | Playwright 原生 Chromium 选择与图像定位仅 browser opt-in；替代对象 context target 保持快速测试 |

选择器脚本为 `scripts/test_modules.py`，唯一模块清单为 `tests/module-map.json`。应用依赖边按实际构造更新：authoring 依赖五个实际仓储；runs 依赖五个仓储与 authoring；steps/tasks/environments/planning 的仓储和协作边见 map，并由闭包测试保护。共享 `infrastructure/context_sessions.py` 映射到运行、规划、环境三个实际消费者，没有添加反向边。快速与 browser target 分开，源码覆盖/旧 unittest ID 覆盖通过 `tests.test_module_selection` 验证；选择器不调用全量 discover。已知 `tests.test_web_chat.WebChatTests.test_selected_history_is_not_silently_dropped_when_it_does_not_fit` 保留在 `application.authoring` 快速映射中，仍按 validation.md 记录为原基线失败。D-R1 修复增量 `/var/folders/mp/_s5dz9l54dg01fgqd1f_jk2h0000gn/T/taskweave-leader-d-r1-a46wf7gt/source` 已由指定 supervisor 复审通过，D-R1 关闭。domain.* 是逻辑测试模块，复用既有功能测试，不要求另建 tests/domain 目录。
