# DDD 模块化实施计划

> 执行者：taskweave-builder-luna，使用 executing-plans 技能逐阶段实施；用户已指定现有任务分工，不再另派设计者或新实施任务。审核者：taskweave-supervisor-sol-req010。架构设计及变更裁决只由 taskweave-navigator-astra 负责。

**Goal:** 保留当前功能与数据兼容，将领域仓储、应用用例、UI 组件及回归边界落实到代码。

**Architecture:** 现有 core/application/infrastructure/desktop 的模块化单体；窄仓储端口、共享 SQLite 工作单元、显式组合 UI。旧导入/dispatch 为兼容门面，保留原并发控制与恢复算法。

**Tech Stack:** Python >=3.10、SQLite、现有 NiceGUI/pywebview、unittest、uv；不新增依赖。

**Spec:** [design.md](design.md)，必须全文阅读。

2026-09-25 历史调度补充：设计第10节曾覆盖阶段 A 的审核交接异常，并允许在保留审核条件下继续 B。A/B 后续已由 supervisor 独立签署通过；C 已按 §16 通过；D-R1 已关闭，D 独立审核通过；leader 已完成最终验收，见 [最终验收记录](final-acceptance.md)。

## 全局约束

- 基线是当前工作区；禁止 reset/clean/stash 或覆盖未提交功能。不自动提交用户混合改动，不创建只含 HEAD 的工作树来丢弃现场。
- 控制库 v14、插件 API v1、step python-async-v1、taskweave-task-2 不变。
- 每阶段仅一个写代码任务。Sol 审核期间 Luna 停止修改被审阶段，返修继续使用原任务。
- 所有命令用 uv run；不运行全量测试。脚本须明确列出选中的功能模块。
- 设计偏差向架构师报告；不得以“只移动方法”“抽成 mixin”“测试已绿”代替边界要求。

## 评审重点

1. 嵌套仓储操作中内层异常后外层是否全部回滚，线程是否串用连接（A）。
2. 相同 command_id/过期 hash/revision 是否仍拒绝冲突，UNKNOWN 是否被错误重试（A/B）。
3. 切换步骤或导航时迟到的 AI/自动保存回调是否污染新页面（C）。
4. 确认采集失败/取消是否保留草稿且数据库不改变，冻结规划是否错误读取最新上下文（A/C）。
5. 修改共享端口/组件是否选到所有受影响 consumer，未知路径是否静默漏测（D）。

## A：领域仓储与工作单元

文件：core/repositories.py；infrastructure/unit_of_work.py；infrastructure/repositories/{tasks,steps,environments,runs,results,step_contexts,plans,plan_contexts,plan_generations}.py；修改 repository.py、plan_repository.py、storage.py；测试 tests/repositories/。

- [x] 记录基线：运行现有 test_step_authoring、test_task_copy_lifecycle、test_task_transfer、test_storage_integrity、test_control_db_migration、test_context_captures、test_context_collection、test_planning；记录任何已有失败，禁止顺手删测。
- [x] 定义窄 Protocol，沿用现有方法参数及返回值。显式仓储集合属性 `tasks/steps/environments/runs/results/step_contexts/plans/plan_contexts/plan_generations`；各仓储必须有实际调用方。兼容门面旧名称显式转发到对应对象。
- [x] 建立 UoW 事务绑定，先写真实 SQLite 的 rollback/isolation 测试。断言模式如下，具体 DTO 使用已有 fixture：

```python
with self.assertRaises(RuntimeError):
    with uow.transaction():
        task = repositories.tasks.create_task('rollback')
        repositories.steps.save_step(task['task_id'], document)
        raise RuntimeError('rollback')
self.assertEqual(repositories.tasks.list_tasks(), [])
```

- [x] 添加内层异常不提交、并发线程连接隔离和 DB 外键校验，运行新仓储测试确认保护点，再拆分 SQL 主体。连接绑定不得包含活跃模型/插件调用。
- [x] 按设计表拆仓储，Step 保存与 task graph 同事务；context 批量保持原修订/确认失效；结果文件/跨库清理保留现有恢复逻辑。迁移函数及常量不变。
- [x] 任务/计划复制和导入在临时库注入中途失败，验证不留下新任务/半组，源数据仍在；规划导入保持 frozen context 和重复导入行为。
- [x] 验证旧 facade 与新仓储在各自临时 home 的同一操作序列返回等价结构（归一化 UUID/时间，不剔除状态/hash/排序/正文/预览）。
- [x] 运行工程检查及 A 受影响模块，更新 validation/code-mapping；提交给 Sol 审核，修复后复审。未通过不进入 B。

## B：应用用例、路由及运行持久化边界

文件：application/{tasks,steps,environments,runs,contexts,operations}.py；修改 service/authoring/planning/task_transfer；runtime、worker、context_sessions 的持久化调用；desktop/controller.py；tests/application/。

- [x] 建立 dispatch 操作清单测试：基线所有操作名存在、未知操作仍 OPERATION_UNKNOWN，原只读/锁豁免分类和 async 分类不变。
- [x] 逐组建立用例服务，显式注入所需仓储/registry/coordinator；Application 只装配、生命周期、兼容转发和调度。Authoring、PlanningService 不经巨门面或整 Application 访问任意数据。
- [x] 将 application 中 SQL 移到语义仓储方法，例如 trial leases、unsafe attempts、environment runs；将 runtime 的运行持久化交给 RunRepository，保留原锁与命令事务回调时序，禁止重写 worker 控制。
- [x] DesktopController 所需运行输入等通过应用查询接口获取；保留 UI 收到的现有数据，不把内部完整输入泄露到现有公共 run.get。
- [x] 新增架构检查：AST 检查 application 不含 SQL 字面量执行、core 不导入基础设施/UI、desktop 不直接访问 repo/query/execute；兼容适配仅列明精确例外，不能整个目录放行。
- [x] 运行 test_http_task_api、test_execution_control、test_executor_recovery、test_interval_scheduler、test_step_outputs、test_runtime_inputs、test_task_cleanup、test_task_transfer、test_ai_authoring、test_planning 及新 application/repository 测试，记录命令与失败归因。运行工程检查，Sol 审核/返修。

## C：UI 组件组合与局部行为测试

文件：desktop/pages/{tasks,executions,history,environments,plugins,settings,marketplace}.py；desktop/components/{step_editor,step_list,step_debug,step_ai,step_contexts,execution_details,run_inputs,result_viewer}.py；desktop/state.py；workbench.py、planning.py、contexts.py；tests/ui/。

- [x] 先为 TasksPage/EnvironmentPage 的渲染、CRUD controller 调用及失败保留建立组件测试，再搬迁现有实现；保持全部标签和布局。依赖以 controller、navigate、button helpers、状态显式提供，不能接收任意 host proxy。
- [x] 创建 StepEditorState/DebugState，搬迁 document/save_editor 等；串行保存和 expected_hash 使用原行为。测试两次保存串行、保存失败不导航、A 步迟到回调不能改 B 步。
- [x] 将 StepList、StepDebugPanel、StepAIEditor、StepContextPanel 组合到 StepEditor。共享局部状态明确归属；上层通过 callback 收到保存/选择/执行事件。
- [x] 提取执行页、输入补录、详情、结果和历史；每页 render/dispose 管理 timer 和事件订阅，测试离页不再刷新旧容器，应用运行不随导航结束。
- [x] 规划页从 `self.host` 任意状态访问改为显式页面状态/依赖，继续共享 ContextCards/ContextCaptureDraft。测试取消采集无写入、失败草稿保留、确认一次请求、删除撤销顺序不变。
- [x] 将旧源码字符串 UI 测试映射到新组件行为测试，维护 migration 清单，不以源码新增注释字符串骗过断言。现有测试迁移后不能重复 discover 同一类。
- [x] 运行 tests/ui 对应组件、test_desktop_step_save、test_task_config_refresh、test_input_ui、test_confirmation_ui、test_trial_variable_groups、test_context_cards、test_display、test_result_views、test_web_chat，及触及的旧模块。
- [x] 用已有 test_workbench_browser 中相关测试方法验证临时工作空间真实创建任务/保存步骤/调试/执行/结果/规划上下文路径；拆组件后快速测试不能替代关键浏览器连接检查。使用本地 fixture，若环境阻塞如实记录。
- [x] 工程检查、Sol 审核/返修，确保 Workbench 仅剩外壳与显式兼容转发，不把全局 self 分散到多个文件。

## D：精确测试选择与文档交付

文件：scripts/test_modules.py、tests/module-map.json、tests/test_module_selection.py、tests/test_architecture_boundaries.py、tests/README.md、docs/testing.md、各目录 README、REQ-010 与受影响 REQ 映射。

- [x] 建立模块键：domain.tasks/domain.steps/domain.contexts、repository.tasks/steps/planning/contexts/environments/runs/results、application.tasks/steps/planning/authoring/runs、ui.tasks/editor/debug/planning/contexts/executions/results/environments/plugins/settings/history、shared.storage/contracts/ui、plugins.playwright/ocr/tidb/utility；并按 §17 增加 `application.environments` 与 `shared.testing`。精确映射源码和现有 unittest targets，不使用 `tests` 根目录作为默认 target。
- [x] 实现 CLI `--list`、`--module`、`--changed`、`--dry-run`、`--include-browser`。默认只运行快速 targets；共享变化按反向传递闭包选择 consumer。
- [x] 用选择器测试证明以下行为：

```python
self.assertIn('ui.tasks', select_changed(['src/taskweave/desktop/pages/tasks.py']))
self.assertNotIn('ui.settings', select_changed(['src/taskweave/desktop/pages/tasks.py']))
self.assertIn('application.steps', select_changed(['src/taskweave/core/repositories.py']))
with self.assertRaises(UnmappedSourceError):
    select_changed(['src/taskweave/new_unknown_module.py'])
```

- [x] `--dry-run` 不启动测试；未知 module、未映射源码和空非法输入非零退出；打印选择理由与去重 targets。覆盖检查包括产品源码及每个 unittest ID 映射。
- [x] 更新 docs/testing、scripts/tests/desktop/plugins README、REQ-003/004/005 映射与 REQ-010 状态/映射/验证记录；保留已知 `test_web_chat` 基线失败归属。
- [x] 运行工程检查、选择器测试和本轮累计受影响模块（明确列表，禁止全量）；Sol 综合审核，无 P0/P1/P2 未解决项后汇报根任务做最终验收。

## 任务交接

Luna 每阶段结束向本任务报告修改列表、验证证据、设计偏差和可审核状态；本任务指定 Sol 审核。Sol 将问题写入 review.md，给出路径/行号、可复现行为、严重度、应补测试，并通过 send_message_to_thread 退回同一个 Luna。返修完成 Luna 通知 Sol 复审；Sol 通过后通知本任务。双方不得把阶段通过写成整个项目终验通过。
