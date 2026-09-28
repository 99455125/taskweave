# 验证记录

## 架构师 B 独立兼容与基线归因 · 2026-09-25

在冻结 stage-a-ready 与新 AB `taskweave-req010-ab-review-6ioeo41x/source` 的独立 cwd/PYTHONPATH 下，分别创建临时Application、相同含note输入的任务/已确认步骤/运行，读取dispatch run.get.request_json：原A包含initial_inputs与step_inputs，新AB删除两字段，两个探针退出0。证实本轮新返回契约变化，已按design第14节退回返修；不是以测试通过替代兼容判断。

另从冻结A独立执行 `PYTHONPATH="$PWD/src" uv run --project /Users/dasensen/PycharmProjects/taskweave python -m unittest tests.test_runtime_inputs.RuntimeInputs.test_pending_popup_reads_local_inputs_not_public_summary -v`：退出码1，1项error，1.263秒。Workbench.pending_inputs.update_submit在必填org缺失时，异常处理再次调用同一个会抛FORM_INVALID的form.task_values，弹窗初始化失败。此为既有UI基线缺陷，C提取RunInputDialog时修复：提前构造所需schema，错误处理不得重复调用失败的验证读取；保留弹窗和草稿，禁用提交并显示缺字段/格式提示，填完后恢复。保留原测试并补缺值到有效值的行为检查，不在B静默删测或改判通过。

## B 中间复审与资源快照修正 · 2026-09-25

新审核会话在保留原253文件hash、另补两个SQL资源的验证副本中执行9个相关模块：48项中46通过、2 errors，具体命令、版本和三个P2见 review.md。不是B通过。架构师核对新增查询的无效列、导入失败fixture的递归patch及隐私fixture未迁移，整改与规划依赖归属写入 design.md 第13节；产品代码尚未返修。

原 stage-b-in-progress 漏收 SQL 属于架构师冻结材料问题，项目 SQL 未删除。架构师另建基线目录下 stage-b-resource-complete：原253文件逐项hash保持一致，补入 stage-a-ready 中且与当前项目字节一致的 control.sql/task-data.sql，共255文件。manifest SHA256：`3d3c01154fdbf7a73018e6a008a0708535c8a2c4ce62a86041c0fa9ddbef15ab`。使用该副本 cwd、PYTHONPATH 指向其src、uv run --project 指向原工程，核实导入路径后创建临时 Application 并读取空任务列表：退出码0。此项仅证明补全快照可初始化，不覆盖或改变审核发现。

## 当前 B 中间状态核查 · 2026-09-25

架构师执行 `uv run python -m unittest tests.application.test_dispatch_policy tests.application.test_application_composition -v`：退出码 0，4 项通过，0.334 秒。验证路由名称/异步/锁豁免清单、未知操作错误码、任务/步骤路由归属、插件重新配置后用例采用新 registry。静态核对旧 Application 22、Repository 40、PlanRepository 24 个公开方法参数与冻结基线一致，共86个、0差异。`uv run python scripts/check_project.py` 退出码0（116份 Markdown）。

以上仅为 B 中间状态证据；Coordinator 持久化 SQL 与 DesktopController 直接仓储访问尚未完成迁移，B 专项执行/恢复回归尚未交付。Luna 随后结束汇报的是旧 REQ-005 多采集项任务，其95项测试报告不能替代 B 验收。原会话交接异常待用户决定处理方式；不得记录 B 或整体通过。

阶段 A 已实施并提交独立审核；整体改造及最终验收未完成。

2026-09-25 架构师补充 B 操作参数基线：从冻结原源码的 dispatch 路由及临时 Application 实例提取 85 个同步、4 个异步 callable 的参数名、种类、必填性与默认值，保存为下述源码基线目录的 `route-signatures.json`。这是原版契约证据，不代表新实现已通过比对。首次提取脚本遗漏 capture_routes 的占位 operation 参数而退出 1，补全参数后退出 0；未修改产品代码。

## 源码基线

2026-09-24 创建独立快照：`/var/folders/mp/_s5dz9l54dg01fgqd1f_jk2h0000gn/T/taskweave-ddd-baseline-ym4aaase`，包含 source.tar.gz、manifest.json、git-status.txt。包含 src/tests/docs/scripts/plugins/packaging 与项目入口/锁文件，不包含运行库或用户凭据。此路径为当前机器临时证据，最终审查前保留。

每条后续记录需写明：阶段、命令、退出码、用例数、基线已有失败/新增失败、运行条件、未验证边界。只记录实际执行，不以历史 REQ 通过记录替代。

## 设计交接前检查

- `uv run python scripts/check_project.py`：退出码 0，检查 115 份 Markdown、源码语法/边界及 CLI version。
- `git diff --check`：退出码 0。
- 在独立快照生成 `contracts.json`：85 个同步 dispatch 操作、4 个异步操作，及 Application/Repository/PlanRepository/Store/Results 公共方法签名；供终验核对兼容性。此为静态基线，不替代行为测试。

## 架构师独立 UI 基线（改造前快照）

工作目录为快照 `source/`，`PYTHONPATH` 显式指向快照 `source/src`，通过当前工程 uv 环境执行，未使用用户工作空间数据。

命令：`uv run --project /Users/dasensen/PycharmProjects/taskweave python -m unittest tests.test_desktop_step_save tests.test_task_config_refresh tests.test_input_ui tests.test_confirmation_ui tests.test_context_cards tests.test_workbench_changes -v`。

结果：退出码 1；34 项，33 通过、1 失败；77.921 秒。失败为 `InputUi.test_dependency_picker_and_task_then_step_input`，快照 tests/test_input_ui.py:64；点击“2. 当前步骤”后，步骤名称仍为“前一步”，5000ms 内未切换。此为改造前失败，原因继续核对，不能计作重构回归或删除断言掩盖。其余确认交互/上下文草稿和工作台功能检查通过。本命令包含 1 个真实 Chromium UI 用例，不是全量测试。

单项原样复跑仍失败（70.034 秒）。临时诊断副本显示第二步点击进入 navigate，但未执行到 dirty 检查；浏览器无 pageerror、无未保存提示。源码与最小运行复现确认：`Workbench.save_context_edits()` 调用 `ContextCards.save_all()`，而最新 ContextCards 已删除该方法。使用真实两类的 `object.__new__` 和 `panel.is_deleted=False` 执行 `asyncio.run(bench.save_context_edits())` 稳定得到 `AttributeError: 'ContextCards' object has no attribute 'save_all'`。已交 Luna 在 C 阶段按当前弹窗提交契约清理旧调用、补导航/保存测试；Sol 复审。此为既有集成缺陷，不允许以空成功 shim 或删除测试掩盖。

附加静态数据基线：在临时 home 创建控制库，保存 schema.json（22 个 sqlite_master 对象，user_version=14），用于最终核对持久化结构未变化。没有读取用户数据库。

## 执行与恢复基线

Sol 的第一轮冻结基线执行因任务中断未完成，runtime-baseline.log 只有部分结果，不计作通过。架构师随后在相同独立快照重新完整执行指定四模块：`uv run --project /Users/dasensen/PycharmProjects/taskweave python -m unittest tests.test_execution_control tests.test_executor_recovery tests.test_interval_scheduler tests.test_step_outputs -v`（PYTHONPATH 为快照 source/src）。

退出码 0，21 项通过，34.598 秒；完整日志为快照目录 runtime-baseline-complete.log。覆盖暂停/继续、失败显式重试、命令幂等、运行并发及容量、UNKNOWN 核对、重启恢复、间隔、结果回执与输出隔离。仅为改造前基线，不是阶段 A/B 通过证明。

## 阶段 A 实施中验证

- 改动前基线：`uv run python -m unittest tests.test_step_authoring tests.test_task_copy_lifecycle tests.test_task_transfer tests.test_storage_integrity tests.test_control_db_migration tests.test_context_captures tests.test_context_collection tests.test_planning`：退出码 0，39 项通过，无失败。
- 首批事务测试：`uv run python -m unittest tests.repositories.test_unit_of_work`：退出码 0，7 项通过。测试覆盖 Store 兼容查询/执行同连接、外层回滚、捕获内层失败回滚 savepoint、内层成功仍受外层回滚、内层异常传播后整体回滚、跨线程隔离、asyncio 子任务连接隔离及外键。
- 仓储首批迁移：`uv run python -m unittest tests.test_step_authoring tests.test_task_copy_lifecycle tests.test_task_transfer tests.repositories.test_unit_of_work`：退出码 0，15 项通过。
- `python scripts/check_project.py`：退出码 0（布局、源码语法、依赖边界、115 份 Markdown、CLI version）。
- 最终 A 定向复核：`uv run python -m unittest tests.repositories.test_unit_of_work tests.test_step_authoring tests.test_task_copy_lifecycle tests.test_task_transfer tests.test_storage_integrity tests.test_control_db_migration tests.test_context_captures tests.test_context_collection tests.test_planning`：退出码 0，46 项通过，无失败；`git diff --check`：退出码 0。
- 最终 A 定向验证：`uv run python -m unittest tests.repositories.test_unit_of_work tests.repositories.test_task_repository tests.repositories.test_plan_repository tests.test_step_authoring tests.test_task_copy_lifecycle tests.test_task_transfer tests.test_storage_integrity tests.test_control_db_migration tests.test_context_captures tests.test_context_collection tests.test_planning tests.test_variables tests.test_execution_control tests.test_executor_recovery tests.test_interval_scheduler tests.test_step_outputs tests.test_task_cleanup`：退出码 0，83 项通过。覆盖真实 SQLite 嵌套事务、外层/内层回滚、asyncio 子任务与线程隔离、复制与导入中途失败、规划冻结上下文导入、运行恢复及结果路径。
- `uv run python scripts/check_project.py`：退出码 0；`git diff --check`：退出码 0。
- 从改造前快照核对 Application/Repository/PlanRepository/Store/Results 的 86 个方法签名：0 处差异。dispatch 操作数量及公开协议保持原样；schema v14、插件 API v1 与任务包格式未改。
- 尚未验证：Sol 独立代码审核与架构师阶段验收；因此阶段 A 未标为审核通过，B 未开始。运行/结果跨库清理仍依赖既有 receipt、DELETING 与恢复流程，已由定向测试覆盖，但未执行真实 worker 崩溃演练。

## 架构师 A 独立静态兼容检查 · 2026-09-25

通过 `uv run python` 在新临时 home 建库，逐项对比冻结 schema.json：v14、22 个 sqlite_master 对象（类型/名称/表名/完整 SQL）完全相同。AST 提取当前 Application.dispatch 操作列表，对照 contracts.json：85 同步、4 异步的名称与顺序完全相同。退出码 0。此检查不替代 Sol 对事务和行为的独立审核。

## Sol 首轮意见返修 · 2026-09-25

- 定向命令：`uv run python -m unittest tests.repositories.test_unit_of_work tests.repositories.test_task_repository tests.repositories.test_plan_repository tests.repositories.test_repository_wiring tests.repositories.test_repository_contracts tests.repositories.test_plan_metadata_repository tests.repositories.test_plan_context_repository tests.repositories.test_plan_generation_repository tests.test_step_authoring tests.test_task_copy_lifecycle tests.test_task_transfer tests.test_storage_integrity tests.test_context_captures tests.test_context_collection tests.test_planning -v`：退出码 0，59 项通过。
- `uv run python scripts/check_project.py`：退出码 0（116 份 Markdown）；`git diff --check`：退出码 0。
- 返修点验证：业务仓储只经构造注入的仓储端口访问跨域操作；组合测试覆盖注入端口替换、任务/计划复制及同一 UoW 外层回滚；Protocol 参数名与适配器签名逐项比对，删除契约声明映射返回；计划元数据、上下文、生成记录三个模块各有独立真实调用测试。
- 未运行全量测试。Sol 复审及架构师最终验收待完成；阶段 B 尚未开始。

## A 运行复审回归修复 · 2026-09-25

- 架构师在当前 A 返修代码中重跑 `tests.test_execution_control tests.test_executor_recovery tests.test_interval_scheduler tests.test_step_outputs`：21 项中 18 通过、3 项因后台 `Store.receipt()` 错误路由至 `RunRepository` 而超时，退出码 1。测试代码来自当前工作区；原始完整日志保存在架构师快照目录 `stage-a-runtime-review.log`，不覆盖。
- 新增回归：`uv run python -m unittest tests.repositories.test_storage_compatibility -v`：先观察到 2 项失败，异常均为 `RunRepository` 缺少 `receipt`，确认了兼容路由根因。
- 修复 `Store.receipt()` 后重跑同一兼容模块：退出码 0，2 项通过。重跑架构师指定模块：`uv run python -m unittest tests.test_execution_control tests.test_executor_recovery tests.test_interval_scheduler tests.test_step_outputs -v`：退出码 0，21 项通过，34.073 秒。
- 复查旧转发路由：Store 的 `task/steps/step/definition_hash/assert_unlocked` 指向任务/步骤端口，`event/register_refs/finish_attempt/recover` 指向运行端口，`environment` 指向环境端口，`read_output/receipt` 指向结果端口；Repository 同类门面方法显式委托对应仓储。除已修复的 `receipt` 外未发现迁移后失效的桥接。
- 尚待 Sol 再复审；阶段 B 未开始，全量测试未运行。

## 架构师 A 返修后运行复验：发现回归

命令：`uv run python -m unittest tests.test_execution_control tests.test_executor_recovery tests.test_interval_scheduler tests.test_step_outputs -v`。当前返修代码实际结果：退出码 1，21 项、3 errors，97.913 秒。完整日志为冻结快照目录 stage-a-runtime-review.log。

故障链：`Coordinator._drive -> Store.receipt -> RunRepository.receipt`，但该方法已迁到 ResultRepository，旧兼容转发未同步。后台执行线程 AttributeError，导致结果提交恢复及 UNKNOWN 核对等三项 WAIT_TIMEOUT。改造前同组 21 项通过，故这是本轮新增回归，不能列作基线限制。已同时退回 Luna 与 Sol；修复后须补旧入口行为测试并重跑受影响运行模块。阶段 A 保持不通过。

## 架构师回执修复后复验

当前工作区运行 `uv run python -m unittest tests.test_execution_control.ExecutionControlTests.test_pause_restart_continue_and_edit_lock tests.test_execution_control.ExecutionControlTests.test_recovery_after_result_commit_before_control_ack tests.test_execution_control.ExecutionControlTests.test_worker_kill_unknown_requires_reconciliation -v`：退出码 0，3 项通过，4.117 秒。

随后运行 `uv run python -m unittest tests.test_execution_control.ExecutionControlTests.test_pause_cancel_and_timeout -v`：退出码 0，1 项通过，3.770 秒。合计覆盖上轮全部 3 个出错场景及暂停后重启继续场景。仍等待 Sol 对全部 A 整改的独立结论，不以单个修复通过替代整个阶段审核。

## A-R1/A-R2 与 B-R1/R2/R3 返修 · 2026-09-25

- 按 design.md 第12、13节完成返修：修正 core 仓储 Protocol 返回类型并去重；新增基础设施协作端口并补类型注解；按 task_id 查询运行记录并迁移实际清理消费者；修复任务导入回滚测试的真实 bound-method patch；更新 Authoring/Planning 隐私测试至当前依赖与真实持久化上下文。
- 定向验证命令：`uv run python -m unittest tests.repositories.test_unit_of_work tests.repositories.test_task_repository tests.repositories.test_plan_repository tests.repositories.test_repository_wiring tests.repositories.test_repository_contracts tests.repositories.test_plan_metadata_repository tests.repositories.test_plan_context_repository tests.repositories.test_plan_generation_repository tests.repositories.test_context_return_contracts tests.repositories.test_collaboration_ports tests.repositories.test_run_repository tests.application.test_application_composition tests.test_task_transfer tests.test_planning tests.test_privacy_settings tests.test_context_sessions tests.test_task_cleanup -v`；退出码 0，67 项通过，12.041 秒。
- `uv run python scripts/check_project.py`：退出码 0，检查布局、源码语法、依赖边界、116 份 Markdown 与 CLI version；`git diff --check`：退出码 0。
- 未运行全量测试。A/B 独立复审尚未完成，以上结果只证明列出的定向用例和静态项目检查通过，不等同于 A/B 或 REQ-010 验收通过。B 的 Coordinator SQL 与 DesktopController 仓储边界迁移及其完整专项验收仍未完成。

## F-R1/F-R2 返修与纯 A 快照复验 · 2026-09-25

- F-R1：恢复 `StepContextRepository.update_step_context_capture_label` 的 `Sequence[Mapping[str, Any]]` 返回注解；新增常驻协议返回类型检查与真实 SQLite 改名行为测试，断言返回列表、规范化后的 label 与 revision 增量。
- F-R2：从冻结 `stage-a-ready` 新建 `stage-a-r1-r2-reround-pure`，只应用 A 的 Protocol 返回修正/去重、协作 Protocol 与 A 测试补丁。A 快照保留其原有 `RunRepository` 和 `ResultRepository` 范围，不含 B 新增 `UnitOfWork`、`runs_for_task`、`refs_for_attempt` 等；锁测试以临时控制库的低层 SQL 删除 lease，不调用 B `release_lease`。快照包含原有 `control.sql`/`task-data.sql`，复制时排除 `__pycache__` 与 `*.pyc`。
- 快照文件数 251；manifest SHA256：`78939a8b9b68d36ccd2cee2a19c911644ef67f1bbc63f544600cc8f67fbe920c`。补丁文件清单与逐文件 SHA256 见该目录 `manifest.json`。
- 在该纯 A 快照运行 `PYTHONPATH="$PWD/src" uv run --project /Users/dasensen/PycharmProjects/taskweave python -m unittest tests.repositories.test_repository_contracts tests.repositories.test_context_return_contracts tests.repositories.test_collaboration_ports tests.repositories.test_unit_of_work tests.repositories.test_plan_context_repository tests.repositories.test_plan_metadata_repository tests.repositories.test_plan_repository tests.repositories.test_plan_generation_repository tests.repositories.test_repository_wiring tests.repositories.test_task_repository -v`：退出码 0，27 项通过，1.080 秒。未运行全量测试。
- 原项目 `uv run python scripts/check_project.py`（116 份 Markdown）及 `git diff --check` 待本记录提交前复验。新 supervisor 仍需独立确认 F-R1/F-R2 关闭；B-R1/R2/R3沿用其通过结论。本次不代表 A 阶段或 REQ-010 整体验收通过。

## 阶段 B 剩余实现与 A/B 返修 · 2026-09-25

- 按 design.md 第12节修复 A-R1/R2：Context 仓储返回 Protocol 与真实行为一致，协作端口明确声明并可替换；按 review.md 的闭环记录和新 supervisor 结论，本节只记录实现及验证，不替代独立复审。
- 按 design.md 第13节修复 B-R1/R2/R3：`runs_for_task` 查询仅选择当前 v14 存在的 `run_id,status`，实际用于清理路径并由多任务 SQLite 测试覆盖；任务导入失败测试 patch 具体 StepRepository bound method 并验证第二步异常前首步已落库；Authoring/Planning 隐私测试按新依赖构造并用真实组/采集项上下文。
- 完成 B 剩余架构迁移：Coordinator 与 CoordinatorPool 不再执行 SQL 或调用 query/execute/transaction；两个类显式接收 Run/Task/Step/Environment/ResultRepository、registry/factory 与 home。Coordinator 读运行状态/命令回执和控制状态走 RunRepository 语义方法，定义读取走 Task/Step/EnvironmentRepository，结果输出与回执走 ResultRepository。worker 的既有进程算法与其 Results 适配器未改。
- PlanningService 直接注入 StepRepository、StepContextRepository 和 `plan_files_root`；ContextSessions 接收显式计划文件根路径；DesktopController 移除 `application.repo` 访问，通过 Runs 用例读取运行输入、私有请求、环境和输出。`run.get` 保持基线的 `request_json` 完整初始/步骤/等待输入值字段，且不新增顶层 `inputs_json`；页面内部另有私有查询接口；`run.wait` 保持既有调用结果。
- 定向命令：`uv run python -m unittest tests.test_http_task_api tests.test_execution_control tests.test_executor_recovery tests.test_interval_scheduler tests.test_step_outputs tests.test_task_cleanup tests.test_task_transfer tests.test_ai_authoring tests.test_planning tests.test_context_sessions tests.application.test_application_composition tests.application.test_dispatch_policy tests.repositories.test_repository_contracts tests.repositories.test_unit_of_work tests.repositories.test_run_repository tests.test_architecture_boundaries -v`：退出码 0，83 项通过，55.582 秒。
- 附加命令：`uv run python -m unittest tests.test_runtime_inputs.RuntimeInputs -v`：退出码 1，9 项中8通过、1 error，9.667秒。`test_pending_popup_reads_local_inputs_not_public_summary` 在表单缺少必填 `org` 时重复调用 `form.task_values()` 并抛 `FORM_INVALID`；该相同失败已从冻结 `stage-a-ready` 独立复现，归类为既有 UI 基线缺陷，不归因于本次 B 私有读取迁移。其余运行输入行为通过。
- `uv run python scripts/check_project.py`：退出码 0，布局、源码语法、application/runtime/desktop 依赖边界、116 份 Markdown、CLI version 通过。`git diff --check`：退出码 0。
- 未运行全量测试；未更改 schema/API dispatch 清单/worker 算法；C、D 与架构师终验未进行。AB 独立快照初始化检查、逐文件 manifest 与 supervisor 复审记录见交接消息及后续 review.md 追加项。


## design.md §14 run.get 兼容修复 · 2026-09-25

- 删除 `RunUseCases.get` 上新增的 request_json 过滤函数，恢复直接返回 `Coordinator.describe_run()`；DesktopController 的 `stored/request/input_values` 私有用例查询保留。
- 修改架构边界测试：验证返回对象不含顶层 `inputs_json`，并断言 `request_json` 的 `initial_inputs`、`initial_step_inputs`、`step_inputs`、`environment_hash`、`flow_trial` 及 `waiting_input.values` 与存储一致；独立断言 controller 私有查询返回所需输入。
- 命令 `uv run python -m unittest tests.test_architecture_boundaries tests.test_runtime_inputs tests.test_execution_control -v`：退出码 1，25 项中24通过、1 error，23.600秒。唯一失败 `test_pending_popup_reads_local_inputs_not_public_summary` 为冻结 A 已复现的 UI 必填字段 `org` 错误；本次未改 UI。新增兼容性测试通过，执行/恢复模块通过。
- 保留已交付首个 AB 快照不变；按第14节生成独立增量快照，含全部实际包资源与 manifest，单独发 supervisor 复核本次变更及其公开契约影响。

## Supervisor B-R5/R6 返修 · 2026-09-25

- B-R5：在 `core.repositories.RunRepository` 增加 `attempt_versions(attempt_id) -> Mapping[str, str]`。新增 `tests.application.test_step_run_repository_port`，用只转发 Protocol 声明能力的包装端口接入真实 SQLite RunRepository，覆盖 `StepUseCases.confirm` 成功返回 VALIDATED，以及版本不匹配抛 `PLUGIN_VERSION_MISMATCH` 且步骤仍为 DRAFT。
- B-R6：`scripts.check_project` 导出并集中调用三类窄 AST 守卫，架构边界测试复用同一守卫。Coordinator/Pool 对 runtime 文件中任意 query/execute/transaction 调用报错；Application 层拒绝 query、SQL execute 与仓储写事务旁路；DesktopController 检查 application 用例后继续访问仓储的多层属性链及直接 repository 属性。保留 `self.uow.transaction()`、插件 `tool.execute()`、`application.registry.manifests.values()` 与 `application.authoring.conversations.setdefault()` 合法形态。
- 新增正/负守卫测试。负例覆盖 `self.runs.query/execute/transaction`、`self.application.runs.runs.run`、`self.runs.query(f"SELECT ...")`；正例覆盖 UoW 事务、插件 execute 与现有 authoring/registry 链。
- `uv run python -m unittest tests.repositories.test_repository_contracts tests.test_architecture_boundaries tests.application.test_step_run_repository_port -v`：退出码 0，14 项通过，1.812 秒。`uv run python scripts/check_project.py`：退出码 0，116 份 Markdown、语法与边界检查、CLI version 通过；`git diff --check`：退出码 0。
- supervisor 提供的 `supervisor-probes.py` 在当前源码执行：B-R4 request 字段删除数为0，waiting_input.values 保留；B-R5 真实端口包装 confirm 返回 VALIDATED；B-R6 三个注入的违规代码分别使边界单测失败；同一临时副本中的 `scripts/check_project.py` 退出1并逐条报告三处违规。临时注入仅发生在外部临时副本，未改源码。
- 保留先前快照不变；新版增量快照待生成并发 supervisor。未运行全量测试，既有通过的 A 与 B-R1/R2/R3 不重开。

## C 阶段继续实施记录 · 2026-09-25

- Workbench 当前已有 Tasks/Environment/Planning、Executions、History、Plugins、Marketplace、Settings 页面对象，以及 RunInputDialog、ExecutionDetails、ResultViewer、StepContextPanel。`PlanningPage` 使用显式 state/callback，没有 `self.host`。本次未宣称 StepEditor/StepList/StepDebugPanel/StepAIEditor 已完成独立提取；WorkBench 编辑器、AI 和调试流程仍有大量主体代码。
- 此后 StepList 已独立至 `desktop/components/step_list.py`，新增行为测试验证先调用保存/排序，再移动现有按钮和本地行顺序。步骤文档生成及串行保存现已抽到 `desktop/components/step_editor.py`，新增排队保存身份重检测试。StepDebugPanel 现在持有调试动作按钮、失败样式和结束状态同步；AI 生成步骤描述与候选预览已由 StepAIEditor 持有。`start_trial`/`start_flow_trial`/`refresh_trial` 和步骤内容生成/修复主流程仍在 Workbench。
- `Workbench.button` 不再读取调试专属 `trial_actions`、`trials`、`step_id`；其失败/收尾通过显式回调注册。结束按钮查询迟到时重新核对 page/step/editor generation/run 身份。新增 `test_button_dispatch`、迟到调试状态测试和页面 timer 删除测试。
- 移除规划保存中对过期 `ContextCards.save_all` 的调用路径；待输入错误路径不再二次读取已校验失败的表单值。将步骤列表原位移动行为、规划“先保存再执行动作”、上下文表单/高级/目标参数合并顺序改为行为测试；`test_planning.py` 中两项源码读取断言改为渲染与 schema helper 行为。映射见 `tests/ui/MIGRATION.md`。
- 最新主定向命令覆盖 `tests.ui.*`（含 step AI 组件）、`tests.test_workbench_changes`、`tests.test_planning`、待输入弹窗、步骤保存、结果视图、任务配置刷新、调试变量、执行控制和 AI authoring，共 **84 项通过**（31.165 秒）。`scripts/check_project.py` 通过（117 份 Markdown）；`git diff --check` 通过。
- 本地 fixture 浏览器命令 `PYTHONDONTWRITEBYTECODE=1 uv run python -m unittest tests.test_workbench_browser.WorkbenchAcceptance.test_real_task_authoring_ai_trial_run_history_and_configuration -v`：最初修复选择器后 **1 项通过，92.348 秒**；StepEditor/StepDebugPanel 接线后 **1 项通过，91.627 秒**；StepAIEditor 接线后复跑（与5项 AI authoring、3项StepAI行为测试同命令）**9 项通过，94.645 秒**。测试旧的“调试”标签选择器已改为真实 UI 的“展开调试”按钮。
- 计划指定的附加模块批次中，`test_confirmation_ui`、`test_trial_variable_groups`、`test_context_cards`、`test_display` 等通过。`test_task_config_refresh` 最初使用 Workbench 已迁移的 task dialog 接口构造，已改为真实 TasksPage 组合后通过；trial fixture 增加当前 DesktopController 私有 `run_request` 端口后通过。`tests.test_input_ui.InputUi.test_dependency_picker_and_task_then_step_input` 仍失败：切换/展开环境后页面显示“当前环境未配置变量”，未出现保存于真实环境仓储中的描述；尚未定性为基线或 C 回归。`tests.test_web_chat.WebChatTests.test_selected_history_is_not_silently_dropped_when_it_does_not_fit` 仍失败，冻结 C 基线记录中已有相同失败，作为已知基线缺陷单列。
- 以上为阶段 C 中间记录，不是 C 完成/审核通过。StepEditor/StepList/Debug/AI 独立组件、完整页面 dispose 所有权与离页取消/排队保存/迟到 AI 覆盖测试、上述 input UI 失败归因仍未收口。C 快照和 supervisor 复审暂不标记完成；没有运行全量测试。


- 2026-09-25 supervisor 对 r5-r6 增量复审通过并关闭 B-R5/R6；结合之前B及§14复验，阶段B独立审核通过。最终记录、manifest核验与复审测试证据见 [review.md](review.md) 最后一节。C/D与leader整体终验未完成。


### Leader 独立 C 中间诊断 · 2026-09-25（未验收 C）

- 环境切换：使用当前 Workbench.trial_variables.change 的 AST 编译真实回调，配合真实 ValueForm.values 与空必填 org，执行返回 `FORM_INVALID org 为必录项`，render 调用次数为 0。回调 AST 与已验收 B 的 `/var/folders/mp/_s5dz9l54dg01fgqd1f_jk2h0000gn/T/taskweave-req010-ab-r5-r6-0z786mmr/source` 完全相同。这是继承问题；修复要求见 design §15，仍需完整原输入 UI 回归。
- 排队保存：真实 StepEditor 与 StepEditorState，第一保存阻塞后排队第二保存，释放后两次 controller.save_draft 收到的 old_step.content_hash 为 `h0,h0`。预期 `h0,h1`；修复要求见 design §15，已交原 Luna 编码任务。
- 当前源码执行 `uv run python -m unittest tests.test_web_chat.WebChatTests.test_selected_history_is_not_silently_dropped_when_it_does_not_fit -v`：1 项失败，0.548s，test_web_chat.py:78 的 `TaskError not raised`。
- 原始工作树冻结基线 `/var/folders/mp/_s5dz9l54dg01fgqd1f_jk2h0000gn/T/taskweave-ddd-baseline-ym4aaase/source`：通过 `uv run python` 启动，并将该快照的 src 与根目录前置 sys.path，核实 taskweave.__file__、tests.test_web_chat.__file__ 均来自该快照，再加载同名 unittest：1 项失败，0.889s，同一第78行 `TaskError not raised`。因此该项有实际原始基线失败证据，不是 C 新增失败；本轮不擅自调整 AI 历史容量策略或删测。若涉及该逻辑变更，仍须重新评估。

以上为诊断结果，不代表 C 完成或所有 UI 回归通过；未运行全量测试。

## Leader §15 裁决跟进与 A/B 返修复核准备 · 2026-09-25

- 按 §15 修复环境切换时直接读取已校验表单的问题：环境选择现在读取原始草稿，保留空必填项、未完成 JSON 与编辑值，同时刷新未编辑字段的新环境默认值；严格表单校验仍用于实际提交。新增 TrialInputPanel 行为测试覆盖这些边界。
- 按 §15 修复 StepEditor 排队保存：文档仍在请求时捕获，但 `old_step` 在锁内重新读取并做目标身份复检。新增回归先观察到失败 `h0,h0`，修复后通过并得到 `h0,h1`。
- 定向命令：`PYTHONDONTWRITEBYTECODE=1 uv run python -m unittest tests.ui.test_trial_inputs tests.ui.test_step_editor_state tests.repositories.test_repository_contracts tests.repositories.test_context_return_contracts tests.repositories.test_collaboration_ports tests.repositories.test_unit_of_work tests.repositories.test_run_repository tests.test_task_transfer tests.test_privacy_settings -v`：退出码 0，37 项通过，4.143 秒。
- 原输入 UI 浏览器路径命令 `PYTHONDONTWRITEBYTECODE=1 uv run python -m unittest tests.test_input_ui -v`：退出码 1，1 项失败，83.217 秒。环境默认/草稿保留以及 staged required-input 断言已通过；后续在调试结束交互处失败（`tests/test_input_ui.py:134-138`，未观察到“确认结束”弹窗且操作未变为禁用）。因此端到端模块未通过，不能据此宣称 C 验收完成。
- `tests.test_web_chat.WebChatTests.test_selected_history_is_not_silently_dropped_when_it_does_not_fit` 在当前源码和冻结原始工作树均以相同 `TaskError not raised` 失败（leader 已分别复核；详见本文件先前 C 诊断记录），保留为已知基线失败，不在本次范围调整。
- `uv run python scripts/check_project.py`：退出码 0，布局、源码语法、应用/运行时/桌面依赖边界、117 份 Markdown 与 CLI version 检查通过；`git diff --check`：退出码 0。未运行全量测试。A/B 的最终 supervisor 结论待独立复审。
- 新 supervisor 在冻结快照独立复审后，确认 A-R1/A-R2/B-R1/B-R2/B-R3 均可关闭；在快照运行两组定向测试：37 项通过（4.080 秒），28 项通过（7.925 秒）。逐项依据与限制见 `review.md` 新增复审记录。该结论不代表 REQ-010 整体验收通过。

## C 实施候选定向验证 · 2026-09-25

- UI 行为组件：`PYTHONDONTWRITEBYTECODE=1 uv run python -m unittest discover -s tests/ui -v`：退出码 0，39 项通过，0.134 秒。
- 受影响页面/工作台与输入路径：`PYTHONDONTWRITEBYTECODE=1 uv run python -m unittest tests.test_input_ui tests.test_confirmation_ui tests.test_trial_variable_groups tests.test_context_cards tests.test_display tests.test_result_views tests.test_task_config_refresh tests.test_desktop_step_save tests.test_planning tests.test_workbench_changes -v`：退出码 0，61 项通过，94.980 秒。包括原输入 UI 浏览器流程。
- 本地 fixture 主浏览器流程：`PYTHONDONTWRITEBYTECODE=1 uv run python -m unittest tests.test_workbench_browser -v`：修复 RunPage 的页面 getter / 代次检查后，退出码 0，1 项通过，93.595 秒。首次失败时数据库运行状态实际已为 `SUCCEEDED`，仅 UI 轮询未刷新；定位到定时器将页面 getter 函数与字符串比较，修复后浏览器验收通过。失败调试代码已移除。
- `uv run python scripts/check_project.py`：退出码 0，目录布局、语法、依赖边界、117 份 Markdown 与 CLI version 检查通过；`git diff --check`：退出码 0。
- `tests.test_web_chat.WebChatTests.test_selected_history_is_not_silently_dropped_when_it_does_not_fit` 仍是已知基线失败：冻结 C 源码与当前源码均在同一断言以 `TaskError not raised` 失败（先前已由 leader 分别执行核对）。本轮没有运行该失败项或全量测试，也没有调整其历史容量行为。
- 复审快照为本记录更新后冻结的新版本；路径、文件数、manifest SHA-256 与资源核验结果随 supervisor 交接消息提供。快照包含源码 SQL 运行资源（`control.sql` 与 `task-data.sql`）。使用快照 `source/src` 配置 `PYTHONPATH`、项目 uv 环境并创建临时 home，`Application(temp_home)` 初始化且 `task.list` 返回空列表，退出码 0；证实快照可运行且资源可读。
- 状态：仅为 C 实施候选；等待新 supervisor 对该冻结快照独立复审。未运行全量测试；阶段 D、leader 综合审查及架构师最终验收尚未完成。

## C-R1..R5 返修增量验证 · 2026-09-25

- `PYTHONDONTWRITEBYTECODE=1 uv run python -m unittest discover -s tests/ui -v`：退出码 0，44 项通过。
- C-R1..R4 定向集合 `tests.ui.test_step_context_panel tests.ui.test_step_debug_session tests.ui.test_step_editor_state tests.ui.test_navigation tests.test_trial_variable_groups tests.test_runtime_inputs.RuntimeInputs.test_pending_popup_reads_local_inputs_not_public_summary`：退出码 0，20 项通过。另行复跑调试 session 4 项及上下文 Workbench/组件 4 项通过。
- `PYTHONDONTWRITEBYTECODE=1 uv run python scripts/check_project.py`：退出码 0，布局、语法、依赖边界、117 份 Markdown 与 CLI version 通过；`git diff --check` 退出码 0。
- C-R2 增量覆盖调试反馈响应期间切换步骤、同一步骤换 run、离开编辑器；旧响应不改当前反馈，不继续请求 run.events。Workbench 真实同步环境装配重复调试路径也有行为测试。
- 新快照的逐文件摘要/哈希、快照 cwd 检查日志将随复审交接提供。以上是实施侧验证，supervisor 独立复审仍待完成；不代表 C 或整体 REQ-010 验收通过。

## C-R3 增量返修验证 · 2026-09-25

- `PYTHONDONTWRITEBYTECODE=1 uv run python -m unittest discover -s tests/ui -v`：50项通过。
- `PYTHONDONTWRITEBYTECODE=1 uv run python -m unittest tests.ui.test_step_context_panel tests.ui.test_navigation tests.ui.test_button_dispatch -v`：12项通过，覆盖ContextPanel dispose、取消确认时保留暂存项、保存失败可重试、重叠提交抑制、dirty editor取消离页、规划保存异常不导航。
- `PYTHONDONTWRITEBYTECODE=1 uv run python scripts/check_project.py`：退出码0，117份Markdown及布局/语法/边界检查通过；`git diff --check`通过。
- C-R3 supervisor增量复审快照及manifest信息随本节后续补充。未运行全量/A/B测试；R1/R2/R4/R5已由独立supervisor关闭，R3待增量复审。

## C-R3 第2轮返修验证 · 2026-09-25

- `PYTHONDONTWRITEBYTECODE=1 uv run python -m unittest discover -s tests/ui -v`：52项通过。
- `PYTHONDONTWRITEBYTECODE=1 uv run python -m unittest tests.ui.test_step_context_panel tests.test_context_cards tests.ui.test_navigation tests.ui.test_button_dispatch -v`：23项通过；新增真实ContextCards方法通过StepContextPanel回调等待控制器响应、随后dispose的排序和删除组合路径验证共享列表及UI句柄不再后置修改。
- `PYTHONDONTWRITEBYTECODE=1 uv run python scripts/check_project.py`：退出码0；`git diff --check`通过。
- 新冻结快照经本地hash校验与snapshot cwd验证后交独立supervisor复核。未运行A/B大组或全量测试。

## C-R3 最终 supervisor 增量复审 · 2026-09-25

冻结快照 `/var/folders/mp/_s5dz9l54dg01fgqd1f_jk2h0000gn/T/taskweave-req010-c-r3-final-xeuleo0_/source`，manifest SHA-256 `0203ee5c0112dc73579151372db3317bbaeee4c732f0576c59465c48d95ff535`；346项哈希和尺寸复核匹配。supervisor在快照cwd执行上下文/卡片/导航/按钮测试23项通过，并执行 `scripts/check_project.py` 通过，C-R3关闭。原A/B与全量测试未运行；C-R1..C-R5关闭不等于阶段D或最终验收。

## C-R3 职责返修与 D 模块测试映射 · 2026-09-25

- C 职责迁移：`mark_step_pending` / `refresh_trial_inputs` 由 StepEditor 持有，`enter_debug` / `settle_trial_start` 由 StepDebugSession 持有，暂停补录校验与 `run.inputs` / `run.start` 由 RunInputDialog 持有。Workbench 兼容方法仅做委托；run.inputs 已提交后发生导航时，仍完成原 run_id 的 run.start，仅跳过过期 UI 回填/刷新。补有离页身份探针和回填顺序测试。
- 定向命令 `PYTHONDONTWRITEBYTECODE=1 uv run python -m unittest tests.ui.test_step_editor_state tests.ui.test_step_debug_session tests.ui.test_run_input_validation tests.test_runtime_inputs tests.test_trial_variable_groups tests.test_confirmation_ui tests.ui.test_step_context_panel -v`：退出码 0，45 项通过，8.749 秒。原确认模块已迁为实际 StepAIEditor 组件调用，保留成功证据、缺失/过期证据、手动确认取消及 API/Chat/取消断言，并 patch `taskweave.desktop.components.step_ai.ui`。
- 真实 Workbench 浏览器验收 `PYTHONDONTWRITEBYTECODE=1 uv run python -m unittest tests.test_workbench_browser.WorkbenchAcceptance.test_real_task_authoring_ai_trial_run_history_and_configuration -v`：退出码 0，1 项通过，97.379 秒。指定 supervisor 后续在 C 冻结快照运行 `tests.test_workbench_browser tests.test_input_ui`：2 项通过，173.888 秒；证据及 C 结论见 [review.md](review.md)。
- D 新增 `scripts/test_modules.py` 与 `tests/module-map.json`。依赖边按真实 consumer → prerequisite 装配；包含 §17 的 `application.environments`、跨应用 operations 路由、SQL shared.storage、混合 `test_workbench_changes` 方法归属及 Playwright Chromium opt-in。`test_playwright_choices`、`test_image_locators`、`test_input_ui`、完整 `BrowserTests` 类和工作台 browser 流程仅在显式 browser targets；`test_web_chat` 留在 `application.authoring` 快速映射，既有容量基线失败仍单独保留。
- `PYTHONDONTWRITEBYTECODE=1 uv run python -m unittest tests.test_module_selection -v`：退出码 0，20 项通过，1.401 秒。覆盖产品源码与 SQL 映射、所有既有 unittest ID 均有映射、实际加载 targets 后 ID 唯一、仓储/应用 consumer 闭包、`ui.tasks` 不选择 `ui.settings`、未知路径、CLI list/changed/dry-run/非法输入及 browser opt-in。覆盖验证只加载/收集测试对象，不执行整套测试。
- `PYTHONDONTWRITEBYTECODE=1 uv run python scripts/test_modules.py --module ui.tasks`：退出码 0，13 项通过，2.755 秒；无浏览器目标。`PYTHONDONTWRITEBYTECODE=1 uv run python scripts/test_modules.py --module plugins.playwright`：退出码 0，19 项通过，0.160 秒；Chromium 启动测试未执行。
- **指定 supervisor 已签署 C 通过**：`review.md` 的正式结论关闭 C-R3/R6/R7/R8/R9，并确认与原关闭项合并后阶段 C 独立审核通过。此签署只针对 C，D 仍待同一 supervisor 审核。
- 本节为 D 实施验证，不代表 D 审核通过或 REQ-010 完成。最终工程检查、diff 检查与 D 冻结快照/manifest 在下节补记。未运行全量测试；`test_web_chat` 容量基线未重新运行。

## D-R1 应用依赖映射返修与 supervisor 增量复审 · 2026-09-25

- 根因：application 层模块只按同名/局部仓储映射，未表达实际构造端口。`application.runs` 漏 `repository.runs` 与 `application.authoring`；`application.steps` 漏 `repository.tasks`/`repository.runs` 及运行/authoring 协作；`application.authoring` 错误依赖 `application.steps` 且漏五个直接仓储（含 `repository.results`）；tasks/environments/planning 同样缺少实际直接依赖。
- 修正 `tests/module-map.json`：应用模块边按 design.md §17 的真实构造关系补齐；共享 `infrastructure/context_sessions.py` 映射至运行、规划、环境三个实际消费者，不添加伪造反向边。`tests/test_module_selection.py` 增加运行仓储变更到 steps/authoring/runs 与 UI/关键目标的闭包断言、结果仓储到 authoring/AI UI 的闭包断言、六个 application 模块依赖精确断言及共享 session 文件消费者映射断言。
- RED 证据：新增的三项主要回归在修正 map 前失败；runs/results 变更分别漏掉 application/UI 消费者，六个 application 依赖集合均与预期不符。随后按实际依赖修正后复跑通过。
- 实施者定向命令 `PYTHONDONTWRITEBYTECODE=1 uv run python -m unittest tests.test_module_selection -v`：退出码 0，24 项通过，1.001 秒。覆盖实际目标可解析/无重复、所有现存 test ID 被映射、源覆盖、闭包、browser opt-in 与非法输入；未执行映射到的全套目标。
- 实施者运行 `scripts/test_modules.py --changed src/taskweave/infrastructure/repositories/runs.py --dry-run` 与同命令替换 `results.py`：退出码 0，不启动测试；输出分别包含 runs → steps/authoring/UI 及 results → authoring/AI UI 的完整闭包。
- 实施者 `PYTHONDONTWRITEBYTECODE=1 uv run python scripts/check_project.py` 通过（119 份 Markdown、布局/语法/依赖边界/CLI version）；`git diff --check` 通过。
- 指定 supervisor 在增量冻结对象 `/var/folders/mp/_s5dz9l54dg01fgqd1f_jk2h0000gn/T/taskweave-leader-d-r1-a46wf7gt/source`（340 文件，manifest SHA-256 `3b6019f96afe591101a7793650e0797af7273be4f5732f09f29ff42ece1a3460`）确认相对首轮 D 快照变化严格为 10 文件：map、selector 测试和 8 份文档；产品源码/SQL/selector 脚本不变，快照验证后仍一致。
- 指定 supervisor 的六条 source 闭包探针覆盖 runs.py、results.py、step_contexts.py、application/environments.py、runtime.py、context_sessions.py，均通过，默认 browser targets 为 0。逐文件加载与映射目标 ID 对照仅收集：默认 349 个唯一 ID，browser opt-in 增加 17 个，共 366；全覆盖、无重复、无 loader errors。24 项 selector 测试以冻结对象实跑结果为准（1.339 秒）；首轮 D 的 CLI/负输入/dry-run 证据继续有效。
- **复审结论**：指定 supervisor 关闭 D-R1/P2，并签署阶段 D 独立审核通过。结合既有 A/B/C 签署，四阶段独立审核已齐；REQ-010 仍待 leader 最终验收。没有运行全量测试或 A/B/C 浏览器大组。


## 架构师最终验收 · 2026-09-25

A/B/C/D 独立签署齐备，架构师核对179份受审源码/SQL/测试/选择器/map与最终D冻结完全一致，无额外Git可见产品源码；当前工作树选择器24项再次通过（1.612秒）。全部366个测试ID映射完整是只读收集结论，不是全量执行结论。最终结论、兼容性证据与保留限制见 [final-acceptance.md](final-acceptance.md)。
