# REQ-010 阶段 A 独立审核

审核者：taskweave-supervisor-sol\
日期：2026-09-25\
结论：**阶段 A 暂不通过，待 Luna 返修后复审。** 本记录仅审仓储与工作单元；B 应用、C UI、D 测试映射尚未实施，不计作 A 缺陷。

## 已核实证据

- 以 2026-09-24 冻结快照为行为基线，未将大量既有未提交功能当成新变更；控制库 v14、插件/任务包契约未发现本阶段改动。根任务另已核对控制库 schema 与 dispatch 清单完全相同。
- 独立执行 `uv run python -m unittest tests.repositories.test_unit_of_work tests.repositories.test_task_repository tests.repositories.test_plan_repository -v`：退出码 0，11 项通过。真实 SQLite 测试覆盖同连接读写、外层回滚、捕获/传播内层异常的 savepoint、线程隔离、asyncio 子任务隔离、外键及复制中途失败。
- 独立执行 `uv run python scripts/check_project.py` 与 `git diff --check`：均退出码 0。旧 `Repository` 与 `PlanRepository` 的公开方法是显式委托，未见原巨仓储 SQL 主体继续留在这两个门面。
- Luna 报告的 83 项定向回归及 86 个签名静态比对已阅；本审查没有重复运行这 83 项。冻结基线 21 项执行/恢复测试由架构师独立完整运行并记录在 `validation.md`，未把它误写成本阶段通过证据。

## 需返修问题

### [P1] 新业务仓储仍通过完整 Store 互相调用，职责边界未落实

位置：`src/taskweave/infrastructure/repositories/tasks.py:27-30,40-43,65-67`、`runs.py:28-41`、`storage.py:315-380`。

`TaskRepository` 已注入 `steps`，但定义 hash/复制读取仍调用 `self.store.steps()`；`RunRepository` 已注入 `tasks`，但任务、步骤、环境及定义 hash 通过 `Store` 兼容桥寻找其他领域。`Store._repository_adapter()` 因而成为新仓储内部的业务服务定位器。更换一个领域仓储时，其他仓储依旧绕过显式依赖读取旧 Store 路径；当前通过门面构造的测试无法证明可独立替换。设计第 3 节要求 Store 只保留基础存储/兼容桥，新仓储显式接收所需端口，不以旧桥接实现新仓储内部耦合。

最小复现：使用临时 `Store`，`TaskRepository(store)` 加一条步骤后调用 `copy_task()` 得到 `AttributeError: 'NoneType' object has no attribute 'save_step'`；`PlanMetadataRepository(store)` 创建计划后调用 `copy()` 得到 `AttributeError: 'NoneType' object has no attribute 'copy_contexts'`。这些类由 `repositories/__init__.py` 公开导出，构造函数却允许缺少必需依赖。此复现退出码 0，只捕获并打印两个异常，不改用户数据。

需要：构造时显式提供必需的业务端口、去掉可产生半初始化对象的 `None` 默认值；新仓储之间经注入端口调用，`Store.task/steps/step/environment/...` 留给旧兼容入口。保持同一 UoW、原返回值及错误码。补定向测试：直接使用导出的仓储组合执行任务/计划复制；替换一个注入的读取端口时，消费仓储实际调用该端口；外层事务失败仍回滚跨仓储写入。若某跨域逻辑应移到 B 用例层，请先让架构师裁定具体归属，不能以当前 Store 隐式路由作为 A 的完成状态。

### [P2] core 仓储端口与实现签名/返回值不一致，且缺关键操作

位置：`src/taskweave/core/repositories.py:6-67`。

例如 `delete_task`、`delete_step`、`delete_environment`、`delete_result`、`PlanRepositoryPort.delete`、`mark_imported` 都声明返回 `None`，而具体实现返回字典；环境保存、运行创建、上下文批量保存及计划更新退化为 `*args/**kwargs/Any`。`StepRepository` 端口缺少手动/导入确认，`PlanRepositoryPort` 缺少复制等现有调用。当前只有具体类被使用，端口并未实际约束这些调用；B 阶段若按此端口注入，必须回退到 `Any` 或完整门面，违背窄端口设计。

需要：按现有 DTO 和调用路径补齐准确的参数、返回值与必要方法，明确哪个用例消费哪个端口；不要求本阶段重写为 ORM 实体。加轻量结构/类型契约检查，防止实现返回形状与端口继续漂移。B 阶段用例正式迁移仍在 B 验收。

### [P2] 计划三个仓储仍同放 `plans.py`，不满足阶段 A 的模块边界

位置：`src/taskweave/infrastructure/repositories/plans.py:9,72,328`；`src/taskweave/infrastructure/repositories/__init__.py:3`。

`PlanMetadataRepository`、`PlanContextRepository`、`PlanGenerationRepository` 虽然是三个类，却都在 349 行 `plans.py` 中。实施计划 A 明确目标文件为 `plans.py`、`plan_contexts.py`、`plan_generations.py`。D 阶段要按源码模块精确选回归，当前任何计划元数据、上下文或生成记录改动都会命中同一个文件，无法独立映射。此问题是边界交付缺口，不是运行回归。

需要：拆为三个模块并保留 `PlanRepository` 旧导入/委托与相同共享 Store/UoW；给三个模块各自一个真实调用和定向测试，确保复制时的上下文子项仍随同一事务提交或回滚。

## 未覆盖与后续阶段

- 未运行全量测试；未做真实 worker 崩溃注入，跨控制库/任务库/文件恢复仍需在 B/终验核对现有 receipt、DELETING 和 UNKNOWN 语义。阶段 A 的运行/结果路径仅经现有定向测试及静态审查。
- 冻结基线的 `Workbench.save_context_edits -> ContextCards.save_all` 缺陷属于 C 阶段修复范围，不能当作 A 回归，也不能以空 shim 掩盖。

## A 返修后的运行复审补充 · 2026-09-25

架构师在返修后的执行/恢复复核中发现 `Store.receipt()` 仍委托至 `RunRepository`，而回执已迁至 `ResultRepository`；导致运行后台线程抛出 `AttributeError` 并引发等待超时。此项为 A 阶段返修引入的 P1 回归，返修未通过，待再次复审。

修复：兼容入口现委托 `ResultRepository.receipt()`；新增 `tests/repositories/test_storage_compatibility.py`，分别直接调用旧 `Store.receipt()` 和旧 `Repository.receipt()` 验证归属路由。Sol 指定执行/恢复模块定向复跑 21 项通过，另兼容路由测试 2 项通过。架构师原始失败日志保存在其快照目录 `stage-a-runtime-review.log`，作为红灯证据保留；当前验证结果追加于 `validation.md`。未进入 B。

## 接手独立复审 · 2026-09-25

审核署名：REQ-010 独立审核接手任务（Codex，接替原 taskweave-supervisor-sol）。

结论：**冻结阶段 A 暂不通过，剩余两项 P2 端口整改。** 本轮未发现新的 P0/P1；原隐式 Store 业务互调、必需依赖 None 默认、计划仓储未分文件及 receipt 错误转发已在本次范围确认修正。既有审核历史保留。B 已部分实施但不在本结论内；C、D 和 leader 最终验收未完成，不能声明整体改造完成。

### 审查版本与范围

- 审查对象为 `/var/folders/mp/_s5dz9l54dg01fgqd1f_jk2h0000gn/T/taskweave-ddd-baseline-ym4aaase/stage-a-ready/`，不是新 worktree HEAD，也不是持续修改中的原工作区 B。
- 248 个 manifest 条目逐个 SHA-256 核对，全部一致。manifest SHA-256：`8b50d6c24daec4c677210c6a9713be285364c31fbb3296ad2545cd7e3d9e50ba`。
- 行号均指上述冻结 A；实际导入路径确认位于该快照 `src/taskweave`（macOS 实际路径前缀显示 `/private/var`）。所有功能测试使用临时 home；未访问用户数据库，未修改生产源码或冻结文件。
- 阅读了实际原项目规则、项目文档、REQ-010 设计/计划/映射/进度/验证/前审，以及相关目录说明。核对九仓储构造、领域调用、兼容桥、UoW、计划三模块、Protocol、结果与恢复实现。

### 实际验证

冻结 A cwd 下执行以下标准模块入口，退出码 0：**85 项通过，50.227 秒**，无失败或跳过。日志为基线目录 `handoff-a-review-tests-module.log`。

```bash
PYTHONPATH="$PWD/src" uv run --project /Users/dasensen/PycharmProjects/taskweave python -m unittest tests.repositories.test_unit_of_work tests.repositories.test_task_repository tests.repositories.test_plan_repository tests.repositories.test_repository_wiring tests.repositories.test_repository_contracts tests.repositories.test_plan_metadata_repository tests.repositories.test_plan_context_repository tests.repositories.test_plan_generation_repository tests.repositories.test_storage_compatibility tests.test_step_authoring tests.test_task_copy_lifecycle tests.test_task_transfer tests.test_storage_integrity tests.test_control_db_migration tests.test_context_captures tests.test_context_collection tests.test_planning tests.test_execution_control tests.test_executor_recovery tests.test_interval_scheduler tests.test_step_outputs tests.test_task_cleanup -v
```

覆盖真实 SQLite 同连接可见性、savepoint 三种异常路径、线程与 asyncio task 隔离、外键、跨仓储复制失败回滚、规划冻结导入、上下文修订、结果旧入口、UNKNOWN 人工核对、worker 丢失及结果提交后控制库确认前恢复。静态检查确认 DELETING 标记、文件/任务库操作及后续控制库清理仍保留分阶段路径；没有将文件删除当成可回滚 SQL 操作。本轮未额外注入 DELETING 每个崩溃时间窗。

另在冻结 A cwd 执行：

```bash
PYTHONPATH="$PWD/src" uv run --project /Users/dasensen/PycharmProjects/taskweave python ../diagnostics/handoff_a_contracts.py
```

退出码 0，日志 `handoff-a-contracts.log`。该独立诊断脚本在快照外保留；其中的预期异常用于复现下述问题，退出码 0 不表示端口正确。确认：

- 临时 SQLite schema 与 `schema.json` 完全一致：v14、22 个对象的完整 SQL 不变。
- 74 个已声明端口方法的参数名、参数种类、默认值与实现一致；这不等于返回契约或依赖完整性正确。
- 原 Repository、PlanRepository、Store/Results、Application 的原有公开方法参数未变；Application.dispatch 的完整 AST 与原始 source 一致，包含异步操作分类。
- core/ports.py、core/task_package.py、plugins/sdk.py、runtime.py、worker.py 与原始 source 逐字节一致；插件 API v1、python-async-v1、taskweave-task-2 未改。另独立 AST 比对 connect、initialize、Results 均一致。
- 原工作区执行 `uv run python scripts/check_project.py`：退出码 0，116 份 Markdown 及源码/依赖边界/CLI 检查通过；原工作区 `git diff --check`：退出码 0。工程检查对象是当前原工作区，不混称冻结 A 的功能证据。

审核运行说明：第一次用 stdin Python 包装 unittest，macOS spawn 无法重载 `<stdin>`，85 项中出现 25 failures、3 errors（22.551 秒，退出码 1）；原日志 `handoff-a-review-tests.log` 保留。上述标准 `python -m unittest` 重跑修正了审核启动方式，未改产品代码。一次静态探测误找不存在的 dispatch_async，以及在无 Git 元数据快照中尝试 git diff，均未作为通过证据；最终以实际 dispatch AST 和原工作区检查为准。

### [P2] A-R1：三个上下文方法的返回契约仍与真实实现相反

位置：`src/taskweave/core/repositories.py:70,94,96`；实现分别为 `infrastructure/repositories/step_contexts.py:212-235`、`plan_contexts.py:206-223,41-52`。

- StepContextRepository.reorder_step_context_capture 声明 Mapping，实际返回上下文组 list。
- PlanContextRepository.reorder_context 声明 Sequence，实际返回含 revision 的计划 dict。
- PlanContextRepository.update_capture_label 声明 Sequence，实际也返回计划 dict。

复现：临时库创建计划及一个含采集项的上下文组，调用重命名与上移；再创建任务/步骤/采集组并上移采集项。上述诊断脚本输出实际类型依次为 dict、dict、list，与声明相反。列表消费者按端口使用下标会得到 KeyError；按 Mapping 处理步骤组列表同样错误。现有 test_repository_contracts 只核对参数名和删除方法的返回注解，不能发现这些错误。

返修/补测：保留原实际返回值与对外行为，修正三个注解；补真实调用结果的 Mapping/Sequence 契约断言，排序边界无变化与实际移动路径均应覆盖。将已独立核对的参数 kind/default 纳入常驻契约测试，避免只比较参数名。此项是前审 Protocol 准确性问题的未完成整改，不能因现有 85 项通过而关闭。

### [P2] A-R2：仓储间依赖仍需要声明端口之外的方法

位置：`src/taskweave/infrastructure/repositories/plans.py:64`、`results.py:113`；对应 `core/repositories.py:6-13,84-98`。

PlanMetadataRepository.copy 调用注入对象的 copy_contexts，但 PlanContextRepository Protocol 未声明此能力；ResultRepository.delete_result 调用 tasks.assert_unlocked，TaskRepository Protocol 同样没有此方法。构造现在是必需依赖且无回填，但消费方仍要求比声明端口更大的具体适配器，按端口替换不能保证正常工作。

复现：诊断脚本用仅暴露 PlanContextRepository 已声明方法、全部委托真实 SQLite 仓储的 PortOnly 代替计划上下文依赖，执行计划复制，稳定得到 `AttributeError: outside PlanContextRepository port: copy_contexts`。直接完整具体类组合可通过，所以现有组合测试漏掉这一边界。

返修/补测：明确并声明复制与锁校验实际需要的窄协作接口，给消费方准确依赖类型，并以只提供该接口的替代对象验证调用；继续证明复制失败同 UoW 回滚。不要为补签名把 sqlite3.Connection 强塞进 core 公共端口；若需要基础设施内部协作 Protocol 或共享纯 helper，具体归属请 leader 按设计第9节裁决。结果删除的锁校验必须保留，不可删掉调用让替代测试通过。

### 交接与后续

上述 A-R1/A-R2 退回原 Luna，并同步 leader。本审核任务不接管编码、不重设计、不修改生产代码。返修需提供更新快照/哈希及相应定向验证，随后只复核修复及影响范围；全量测试、B/C/D 与最终验收均不在本次通过声明内。

## B 已实现部分中间审核 · 2026-09-25

审核署名：REQ-010 独立审核接手任务（Codex）。按 leader 后续委托，在等待 A 返修期间审查冻结 B 的已实现部分。

**本记录是 B 中间意见，不是 B 通过或整体验收。发现三项 P2；A-R1/R2 仍未修复。** Coordinator SQL 迁移、DesktopController 仓储边界及 C/D 未完成属于既定剩余实施，不写成新的 A 失败。

### 版本、运行副本和验证证据

原冻结对象：基线目录 `stage-b-in-progress/`，253 个 manifest 条目逐项 SHA-256 一致；manifest SHA-256 为 `1071c233506d93546f8786241d38bd6d21065a05cb110635ca931c03829b94ad`。对比冻结 A 阅读了六个新用例/路由模块及 service、authoring、planning、task_transfer、context_sessions、新增仓储查询和对应测试。

该 B 快照漏收 `src/taskweave/infrastructure/sql/control.sql` 与 `task-data.sql`，直接构造 Application 就 FileNotFoundError，属于快照素材缺失，不能归为 B 产品代码删除 SQL。为验证创建了独立 `stage-b-review-resources/`：253 文件保持原 hash，仅补入冻结 A 的两个 SQL 文件，另存 review-resources.json；两个资源同时与实际原项目逐字节一致，hash 分别为 `50c63ed303581b3bcc63342ad767c3779e79d3da47587f1c66aa7c3f8b0b7628`、`298f799b923af7195b6273eb05c9d921c974943f255358fb9f23afce88aef50f`。未修改原快照或生产代码。后续冻结需把包资源纳入 manifest，保证独立可运行。

在这个验证副本 cwd 下，PYTHONPATH 指向副本 src，确认实际导入路径后执行：

```bash
PYTHONPATH="$PWD/src" uv run --project /Users/dasensen/PycharmProjects/taskweave python -m unittest tests.application.test_application_composition tests.application.test_dispatch_policy tests.test_http_task_api tests.test_task_transfer tests.test_planning tests.test_ai_authoring tests.test_context_sessions tests.test_privacy_settings tests.test_step_authoring -v
```

退出码 1：**48 项，46 通过、2 errors，13.308 秒**，详见基线目录 `handoff-b-tests-resources.log`。两项 errors 均为 privacy 测试未适配构造参数，详见 B-R3。原快照首次测试日志 `handoff-b-tests.log` 保留（48 项、37 errors，7.691 秒），含缺 SQL 及审核命令误写 test_composition 模块名，不能作为产品缺陷计数。未重复运行 A 的 85 项，也未运行全量测试。

独立诊断脚本放在快照外 `diagnostics/handoff_b_review.py`，在同一验证副本 cwd 执行：

```bash
PYTHONPATH="$PWD/src" uv run --project /Users/dasensen/PycharmProjects/taskweave python ../diagnostics/handoff_b_review.py
```

退出码 0，日志 `handoff-b-probes.log`。脚本明确断言预期缺陷，因此其成功退出不代表 B 正确。证据如下：

- 85 同步、4 异步路由的名称及顺序与 route-signatures.json 完全一致。70 个路由直接比对参数名/kind/default；19 个原 *args/**kwargs 路由展开到实际委托目标核对，有效参数相同。没有将消除宽泛包装签名误判成对外参数丢失。
- 与 dispatch-policy.json 核对锁豁免集，并替换路由 handler 逐个执行全部 89 路由，验证同步路由是否进入 coordinator.lock、四个异步路由保持原锁外执行。此为分派层检查，不替代未完成的运行并发验收。
- 插件重配后 tasks、steps、runs、contexts、planning、authoring、context_sessions、CoordinatorPool 及已存在的 Coordinator 均指向新 registry。Pool.registry setter 会更新已有实例；未发现本轮注册表遗漏。原有 composition 测试也通过。
- 任务包往返、草稿/确认状态、规划冻结上下文导入、重复导入、规划上下文/回执失败清理、AI 与采集会话相关现有用例通过。另用正确的第二步注入探针确认任务导入实际回滚，源任务及两步骤保留。

### [P2] B-R1：新增 runs_for_task 查询使用不存在的列

位置：`src/taskweave/infrastructure/repositories/runs.py:225-226`，声明为 `core/repositories.py:57`。

SQL 对 task_runs 使用 `ORDER BY created_at,run_id`，但当前 v14 task_runs 没有 created_at 列，已有运行时间字段为 started_at。临时空库直接调用 `app.repo.repositories.runs.runs_for_task('not-a-task')` 即得到 `sqlite3.OperationalError: no such column: created_at`，有无任务记录都失败。

该新端口在冻结 B 尚无实际 consumer，故不能声称现有 UI 已因它崩溃；但后续 Coordinator/用例迁移一旦接入就会失败，须在 B 完整交付前修复或移除无用途接口。按实际业务排序语义使用现有列，不能为重构加 schema 迁移；补真实 SQLite 空集、同任务多运行及跨任务隔离检查。

### [P2] B-R2：导入中途失败测试迁移后在第一步写入前递归触发异常

位置：`tests/test_task_transfer.py:53-63`。

测试保存了兼容门面的 `app.repo.save_step`，却把 patch 位置迁到了它内部委托的 `app.repo.repositories.steps.save_step`。第一次进入 fail_second 后调用旧门面，再次进入同一 patch，被误当第二步骤而抛错。因此当前绿灯仅说明空目标清理，不能证明“第一步已经写入、第二步失败”的回滚。

复现：在两次 fail_second 入口记录目标步骤数，实际为 `[0, 0]`。独立探针改为保存被 patch 的具体仓储原方法后，观测为 `[0, 1]` 且外层失败后仅保留源任务，说明产品回滚本身在此路径有效，问题是常驻测试保护点丢失。

返修：保存真正被替换方法的原 bound method，再注入第二步失败；断言抛错时目标已存在一个步骤，并断言失败后目标任务/步骤均不残留、源任务不变。不要删除此测试或只检查调用次数。

### [P2] B-R3：Authoring 构造迁移漏掉已有隐私开关测试

位置：`tests/test_privacy_settings.py:43`，对应 `application/authoring.py:94`。

test_authoring_ai_toggle 仍用 `Authoring(None, None, redact_for_ai=...)`，B 改为显式仓储及 home 依赖后，测试在任何隐私断言前就 TypeError（缺 environments/runs/results/home/registry）。冻结 A 单独运行该模块时此项通过，故这是 B 新增的测试迁移回归。按新依赖构造测试对象并保留开关前后及输入原文不变的断言；不要求为内部构造维持旧巨仓储接口。

同文件 test_planning_ai_toggle_keeps_stored_context_raw 在 B 也因旧 PlanningService 构造而 TypeError；但它在冻结 A 已因旧 fixture 缺 context_records、仍使用 item 格式而失败，不能算 B 新增的业务回归。独立 A 归因命令为 `PYTHONPATH="$PWD/src" uv run --project /Users/dasensen/PycharmProjects/taskweave python -m unittest tests.test_privacy_settings -v`，5 项中4通过、1 error，0.011秒，退出码1；日志 `handoff-b-privacy-baseline-a.log`。需单列修正 fixture 为真实组/采集项结构，并保留存储原文及 AI 开关断言，不能把这条历史红灯藏在构造错误后。

### B 后续依赖收口与交接

新 Task/Step/Environment/Run/Context 用例已显式持有所需仓储；Authoring 已移除 repo 巨门面，相关 SQL 已迁往语义查询。PlanningService 虽不再持有 Application，仍通过 `self.tasks.steps.steps` 和 `self.tasks.step_contexts` 访问 TaskUseCases 内部仓储（planning.py:258-269），并依赖 `plans.root`（161等行）这个未在 core PlanRepositoryPort 声明的存储路径。完整 B 交付时应由 leader 明确按需注入的读取/上下文能力及生成文件根目录归属，避免把用例对象当成新的仓储容器；目前仅列为未收口边界，不擅自更改设计或重复计作 A-R2。

三项 P2 和快照资源遗漏同步 leader；不再向未执行委托的原 Luna 反复发送编码指令。等待 leader 确认编码接手方案及新冻结版本后再审核。记录追加后，原项目 `uv run python scripts/check_project.py`（116份 Markdown）与 `git diff --check` 均退出码0；本阶段不声称 Coordinator、DesktopController、C/D 或真实浏览器流程已验收。

## 五项指定返修独立复审 · 2026-09-25

审核署名：REQ-010 独立审核接手任务（Codex）。本次仅复审 A-R1/A-R2、B-R1/B-R2/B-R3 及返修直接引入的问题，依据 design.md §12、§13。实施者67项通过记录不作为独立结论。

**结论：B-R1/B-R2/B-R3 通过；A 原修复已见有效实现，但出现新的返回契约错误，且 A 独立快照未正确隔离 B，A 暂不通过。** B 整阶段、C/D 和最终验收仍未完成。

### 对象与实际命令

所有快照位于前述 `taskweave-ddd-baseline-ym4aaase/`。分别检查：

- `stage-a-r1-r2-review/`，manifest SHA-256 `272c29f4200313bba95c8f69aa3d54cd3cdf3e51dcced378a83303a2f6f0c7f2`，321条。
- `stage-ab-r1-r2-b1-b2-b3-review/`，manifest SHA-256 `0adda44b93e432722f665d87fd38d35e5dac7eb2469e6ca06e9e592d65311a5a`，524条。

两个 manifest 本体 hash 与交付值一致。所有非缓存条目逐文件 hash 一致，AB 全部条目一致；A 包含的5个 pyc 在运行后重生成而与 manifest 不同，不认作源码改动。此次 manifest 改为 files 列表格式，审核最初按旧格式读取失败，随后按新结构完成核对，未将解析失败误判成产品文件丢失。后续请排除可重生成的 __pycache__/pyc，使冻结证据稳定。

每条功能命令都在所述快照 cwd，使用 `PYTHONPATH="$PWD/src" uv run --project /Users/dasensen/PycharmProjects/taskweave`，实际 taskweave 导入路径分别确认来自对应快照。测试均用临时 home，未读取用户数据库或修改生产源码。

独立 A：

```bash
PYTHONPATH="$PWD/src" uv run --project /Users/dasensen/PycharmProjects/taskweave python -m unittest tests.repositories.test_repository_contracts tests.repositories.test_context_return_contracts tests.repositories.test_plan_context_repository tests.repositories.test_collaboration_ports tests.repositories.test_unit_of_work -v
```

退出码1，**16项、8 errors（含7个同一契约测试的子项错误），0.503秒**，日志 `review-reround-a.log`。原因见 F-R2，不是 SQLite 事务回滚失效。

综合 A+B：

```bash
PYTHONPATH="$PWD/src" uv run --project /Users/dasensen/PycharmProjects/taskweave python -m unittest tests.repositories.test_run_repository tests.repositories.test_repository_contracts tests.repositories.test_context_return_contracts tests.repositories.test_plan_context_repository tests.repositories.test_collaboration_ports tests.application.test_application_composition tests.test_task_transfer tests.test_planning tests.test_privacy_settings tests.test_context_sessions tests.test_task_cleanup -v
```

退出码0，**50项通过，11.884秒**，日志 `review-reround-ab.log`。另执行审核者新增的外部探针 `python ../diagnostics/rereview_label_contract.py`（相同前缀与AB cwd）：1项失败，退出码1，日志 `review-reround-label.log`，证明现有50项未覆盖 F-R1。未运行全量或重跑A全部85项。原项目 `uv run python scripts/check_project.py`（116份 Markdown）与 `git diff --check` 均退出码0。

### 五项逐条结论

| 原发现 | 本次结论 | 独立证据 |
| --- | --- | --- |
| A-R1 | 原列三个返回类型已修正，原子项验证通过；A契约整改整体仍不通过，见F-R1/F-R2 | 两个快照均有正确的3个注解、参数kind/default检查及重复声明去重；真实步骤/计划排序覆盖边界不动、两项交换、顺序、revision；计划重命名返回dict及revision通过 |
| A-R2 | 窄协作实现验证通过；独立A交付暂不能完整关闭，见F-R2 | collaboration.py仅在基础设施定义两个Protocol，构造注解正确，core无sqlite导入；真实端口替代对象完成计划复制及写后失败回滚。AB真实文件结果测试验证锁拒绝时状态AVAILABLE/文件保留，解锁后UNAVAILABLE/文件删除；A同测试在解锁fixture调用B方法时报错 |
| B-R1 | 通过、关闭原发现 | runs_for_task移除无效排序，使用裁定SQL；真实SQLite验证空集、多运行、跨任务隔离，Coordinator.clear_task_runs实际消费该查询，目标2条运行删除、其他任务保留；任务清理测试通过，无schema修改 |
| B-R2 | 通过、关闭原发现 | patch与保存原bound method均为同一个具体steps对象；第二次调用抛错前断言恰有一个新任务和一个已写步骤，退出后仅源任务/原两步保留，调用恰好两次；实跑通过 |
| B-R3 | 通过、关闭原发现 | 隐私5项全部通过：Application真实装配替代旧构造；规划fixture使用临时真实仓储组/采集项，分别验证AI开关及显示配置独立，库内原文保持。旧规划fixture基线失败也在此范围修正，未删除原断言 |

§13 Planning依赖补充同时已核对：直接注入StepRepository/StepContextRepository，只调用TaskUseCases公开业务方法；Application显式提供 `home / 'plans'`，不再读取plans.root。冻结引用、相对路径组织、失败清理/回执顺序未改，规划定向测试通过。其余Coordinator SQL、DesktopController边界迁移仍为原剩余范围，不扩成这五条的失败理由。

### [P2] F-R1：返修把原本正确的步骤采集项重命名返回类型改错

两个快照相同位置：`src/taskweave/core/repositories.py:79`，StepContextRepository.update_step_context_capture_label。原A及原B声明均为 Sequence[Mapping[str, Any]]，本次改成 Mapping；具体 `infrastructure/repositories/step_contexts.py:237-252` 没有变化，仍返回上下文组列表。这不是要求调整的 PlanContextRepository.update_capture_label。

最小真实复现：创建临时任务、步骤、上下文组及一个采集项，调用 update_step_context_capture_label，实际得到 list（包含已改名的采集项），get_type_hints 却是 Mapping。外部探针已先断言实际列表与label正确，再对照预期Sequence注解失败；原始行为没有变，错误来自本次新增注解改动。需恢复此方法的Sequence注解并补其实际返回契约断言，不能为迎合错误注解改变对外结果。

### [P2] F-R2：声称独立A的快照混入B声明及测试依赖，无法独立验证

对象仅 `stage-a-r1-r2-review/`：`core/repositories.py:52-58` 加入B的7个RunRepository方法，但该快照的 runs.py仍为A实现，完全没有这些方法；契约测试逐项产生7个AttributeError。`tests/repositories/test_collaboration_ports.py:101` 又调用B的release_lease，导致结果锁测试无法进入解锁后的删除断言。该A快照还混入了B的UnitOfWork端口、ResultRepository.refs_for_attempt，说明共享文件整份取自AB，而非仅应用A修复。

这是违反§12独立冻结要求的交付/验证问题，不能借AB50项通过覆盖；也不是要求提前完成Coordinator迁移。需从原stage-a-ready重新构造仅含A补丁的新目录，分离core/repositories.py与results.py中的B变化；A测试fixture解锁用A已有的低层临时库操作，不把B生产方法移进A来让测试通过。保留当前失败快照和日志，提供新manifest（含SQL、不含缓存）及独立A定向结果。

本次两项新问题退回实施者并同步leader；不覆盖任何历史结论，不接管代码。修复F-R1并提供正确隔离A快照后，可只复验相关契约/协作路径；B三条原发现无需因A素材问题重新打开。

## F-R1/F-R2 纯 A 最终复审 · 2026-09-25

审核署名：REQ-010 独立审核接手任务（Codex）。本次严格限于返回契约修正、纯A隔离及相关协作路径。

**结论：F-R1、F-R2通过并关闭；A-R1/A-R2可完整关闭，阶段A独立审核通过。** 这是结合前次冻结A审核与本次增量复验的结论，不代表B整阶段、C/D或leader最终验收通过。B-R1/R2/R3保持关闭，未重开或重复验收。

审查对象为 `stage-a-r1-r2-reround-pure/`，manifest SHA-256 `78939a8b9b68d36ccd2cee2a19c911644ef67f1bbc63f544600cc8f67fbe920c`。独立核对251个文件全部hash一致、无缓存条目，两个SQL资源完整。与stage-a-ready逐文件对比：只修改3个产品源码文件（core/repositories.py、repositories/plans.py、results.py），新增collaboration.py；其余差异为4个测试文件和design/review文档，与manifest补丁清单一致。没有混入B的UnitOfWork、运行查询端口或refs_for_attempt，运行器及其他业务实现保持原A版本。

- F-R1：步骤采集项重命名恢复Sequence返回声明；常驻测试同时检查协议类型、真实列表返回、规范化label及revision增量。上轮审核者的独立失败探针原样重跑已通过，实际返回行为未改。
- F-R2：锁测试改用临时控制库低层SQL解除lease，未依赖B方法。真实窄端口替代、计划复制及写后失败回滚、结果锁拒绝时状态/文件保留、解锁后状态转换与文件删除、同连接/savepoint/线程/async隔离均在纯A中通过。

在上述快照cwd，确认实际导入来自快照src，并执行：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/src" uv run --project /Users/dasensen/PycharmProjects/taskweave python -m unittest tests.repositories.test_repository_contracts tests.repositories.test_context_return_contracts tests.repositories.test_collaboration_ports tests.repositories.test_unit_of_work tests.repositories.test_plan_context_repository tests.repositories.test_plan_metadata_repository tests.repositories.test_plan_repository tests.repositories.test_plan_generation_repository tests.repositories.test_repository_wiring tests.repositories.test_task_repository -v
```

退出码0，**27项通过，1.074秒**，完整日志为基线目录 `review-pure-a-final.log`。随后同样前缀执行 `python ../diagnostics/rereview_label_contract.py`：退出码0，**1项通过，0.054秒**，与前轮保留的红灯证据对应。所有测试使用临时home，没有用户数据或生产源码修改；未运行全量测试。

原项目 `uv run python scripts/check_project.py`（116份Markdown）及 `git diff --check` 均退出码0。历史失败快照与记录全部保留；本结论同步leader和原实施任务，后续按原分工推进B剩余范围。

## A-R1/A-R2、B-R1/R2/R3 返修与 B 实施交付 · 2026-09-25

编码方按 leader 裁决 design.md 第12、13节完成返修；A-R1/A-R2、B-R1/R2/R3 仍须由 supervisor 在新快照上独立复审确认关闭。本记录不代替审核者签署。

- A-R1：修正步骤上下文重排及计划上下文重排/标签更新的 Protocol 返回契约，常驻真实行为及形状检查已在既有定向验证中通过。
- A-R2：仓储协作接口声明为基础设施端口，添加仅满足所声明能力的替代适配测试；复制/结果删除的事务与锁校验定向覆盖沿用前述 67 项验证。
- B-R1：`runs_for_task` 删除不存在的 `created_at` 排序字段，保留 `run_id,status` 语义读取并被任务运行清理路径消费；SQLite 空集、多运行及跨任务隔离测试通过。
- B-R2：任务导入失败探针 patch 实际 StepRepository 并确认第二步失败前已有一个步骤落库，随后验证目标任务/步骤回滚而源任务不变。
- B-R3：Authoring/Planning 隐私测试 fixture 适配当前依赖及有序上下文组结构，保留原文落库与隐私开关断言。
- B 剩余实施：Coordinator/Pool SQL 与低层持久化调用改为语义仓储调用，且依赖明确注入；PlanningService、ContextSessions、DesktopController 边界依 design.md 第13节收口。代码映射与逐项验证见 `code-mapping.md`、`validation.md`。
- 当前快照 B 定向回归83项通过，项目检查和 `git diff --check` 通过。另运行输入模块9项中8项通过；剩余弹窗用例在冻结 A 已复现的必填输入错误保持为单列基线限制，详见 validation.md。未运行全量测试。

### 新 supervisor 复审请求

请在当前 AB 快照独立核验第12、13节返修与 B 剩余边界、逐项复跑适用的定向模块，检查快照内源码/SQL 包资源及 manifest，并只对 A-R1/A-R2、B-R1/R2/R3 与 B 阶段给出结论。C、D 和整体终验不在本次交付声明内。


## design.md §14 run.get 兼容增量返修 · 2026-09-25

leader 独立比较冻结 A 与首个 AB 后新增 design.md §14，指出应用层 `_public_run` 删除原有 `request_json.initial_inputs`、`step_inputs` 与 `waiting_input.values`，属于未授权公开返回变化。编码方已移除过滤函数，`RunUseCases.get` 恢复原样返回 `Coordinator.describe_run()`；DesktopController 的私有 stored/request/input_values 查询不变。架构边界测试现断言原有 request 字段与等待值兼容、不新增顶层 `inputs_json`，不再要求返回中完全无输入值。

增量命令 `uv run python -m unittest tests.test_architecture_boundaries tests.test_runtime_inputs tests.test_execution_control -v`：25 项、24通过、1 error。唯一错误为冻结 A 已复现的 `pending_inputs` 必填 `org` UI 基线缺陷；本轮未触碰 UI。旧 AB 快照及其 manifest 保持不变。增量快照、manifest、新哈希及复审请求另行发送；本项及之前 A/B 审核结论仍待 supervisor，不自行标阶段通过。


## B 剩余范围及 §14 增量独立复审 · 2026-09-25

审核署名：REQ-010 独立审核接手任务（Codex）。**阶段B暂不通过：尚有B-R5、B-R6两项P2。B-R4返回兼容问题经§14增量复验关闭。** 阶段A已独立通过，A-R1/A-R2/F-R1/F-R2及B-R1/B-R2/B-R3保持关闭；前面编码方的待审核措辞不撤销审核者既有结论。本轮未发现新的P0/P1，不扩展到C/D或整体终验。

### 冻结对象与验证

- 首个AB对象：`/var/folders/mp/_s5dz9l54dg01fgqd1f_jk2h0000gn/T/taskweave-req010-ab-review-6ioeo41x/source`，manifest SHA-256 `7d212c810cb663fdaf7f1e9eedcc0472fbc2ffd14d3d96fa54c38a60f82cc7f9`。
- §14增量对象：`/var/folders/mp/_s5dz9l54dg01fgqd1f_jk2h0000gn/T/taskweave-req010-ab-r14-pwye56h8/source`，manifest SHA-256 `ba82c31e4bd138f7be461ed378602a4a7f21a19046cc72d06e188a3eec687295`，delta-manifest SHA-256 `d5714a1b5cba6012f343c46747398033462d26c4b738154fed8c48dfaf1c8b97`。
- 两个对象各472个文件，审核者逐文件校验hash；SQL资源完整，从各自快照src导入，真实临时Application可初始化。§14仅7个增量文件，其中产品修改仅application/runs.py，另为架构测试及5份需求文档；没有删除文件。

全部运行使用快照cwd及以下前缀，使用临时home，不访问用户库：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/src" uv run --project /Users/dasensen/PycharmProjects/taskweave python
```

首个AB执行 `-m unittest` 后接：

```text
tests.test_http_task_api tests.test_execution_control tests.test_executor_recovery
tests.test_interval_scheduler tests.test_step_outputs tests.test_task_cleanup
tests.test_task_transfer tests.test_ai_authoring tests.test_planning tests.test_context_sessions
tests.application.test_application_composition tests.application.test_dispatch_policy
tests.repositories.test_repository_contracts tests.repositories.test_unit_of_work
tests.repositories.test_run_repository tests.test_architecture_boundaries -v
```

退出0，**83项通过，51.327秒**。另执行tests.test_runtime_inputs.RuntimeInputs下4项：test_missing_task_and_step_inputs_pause_before_actions_and_resume_same_run、test_flow_trial_uses_task_inputs_and_only_current_step_override、test_flow_repair_feedback_uses_this_failed_run、test_combined_first_inputs_and_default_environment_persistence，退出0，**4项通过，3.452秒**。日志分别为首个快照父目录supervisor-b-tests.log、supervisor-b-inputs.log。

§14新快照执行 `-m unittest tests.test_architecture_boundaries -v`，退出0，**7项通过，1.104秒**，日志为新快照父目录supervisor-r14-tests.log。未重复A全组或运行全量测试。pending_inputs必填org错误由leader在冻结A独立复现，属于已记录的UI基线限制，本轮未重复运行或算作B回归。

### B-R4 [P2]：run.get删除既有request_json字段；§14增量已关闭

首个AB的application/runs.py中get调用新增_public_run，删除request_json.initial_inputs、step_inputs及waiting_input.values。独立真实临时库探针确认初始字段少两项、等待值丢失。依leader design.md §14，原限制是不得新增顶层inputs_json，不能据此删除既有request_json内容；本轮不引入新脱敏策略。

§14增量移除过滤并原样返回describe_run，私有stored/request/input_values查询保留。相同独立探针在新快照确认没有字段被删除、waiting_input.values保留、无顶层inputs_json；上述7项常驻测试进一步比较请求字段内容。该项通过关闭。

### B-R5 [P2]：步骤确认消费未声明的运行仓储能力

冻结对象 `src/taskweave/application/steps.py:79` 调用self.runs.attempt_versions；`core/repositories.py` 的RunRepository Protocol未声明此方法，具体仓储却实现它。现有协议检查只遍历声明项检查具体实现，不能发现消费者依赖了声明外能力。

独立真实SQLite复现：临时Application创建任务、步骤、试运行及成功attempt，具体仓储路径confirm返回VALIDATED；将同一仓储包装为只转发RunRepository声明方法的端口对象后，StepUseCases.confirm抛出 `AttributeError: outside RunRepository port: attempt_versions`。无需改动运行数据或mock确认逻辑即可触发。§14没有修改此处，新快照同样复现。

需在RunRepository补齐准确的attempt_versions签名/返回类型，并通过仅暴露声明能力的真实仓储替代测试验证确认成功及插件版本不一致时的PLUGIN_VERSION_MISMATCH。此发现属于B当前消费契约完整性，不重开A已通过的契约修复。

### B-R6 [P2]：架构守卫只拦截旧写法，无法保护新的依赖边界

冻结对象 `tests/test_architecture_boundaries.py:16-50` 及 `scripts/check_project.py:48-68`：runtime低层调用检查仅识别db或self.repo接收者，desktop仅识别application.repo，application SQL仅识别Constant字符串。新结构允许的实际绕过分别为：

```python
# runtime
self.runs.query("SELECT 1")
self.runs.execute("UPDATE task_runs SET status='READY'")
with self.runs.transaction():
    pass
# desktop controller
self.application.runs.runs.run("review")
# application
self.runs.query(f"SELECT * FROM {table}")
```

审核者在快照的外部临时副本追加包含这些语句但不执行的函数；三项真实边界测试全部错误通过，check_project.py也错误通过。§14新快照再次复现：3项0.062秒、检查脚本均退出0。这些通过是负例漏报证据，不能作为边界验收成功；原快照/生产源码未被改写，临时副本已自动移除。

需让两个检查入口覆盖这些实际新增结构，并加入能证明拒绝违规代码的负例；无需泛化成任意Python数据流分析器。实际正常源文件仍应通过。复现脚本位于首个快照父目录supervisor-probes.py；首个及新快照父目录分别保留supervisor-b-probes.log、supervisor-r14-probes.log，包含B-R4/B-R5真实库探针和B-R6完整检查输出。

本轮只追加审核记录，不接管生产修复。B-R5/B-R6已退回原实施任务并同步leader；后续针对新冻结增量复验即可，既有通过项目无需无差别重跑。

## B-R5/R6 实施者返修响应 · 2026-09-25

- B-R5 已补 `RunRepository.attempt_versions(attempt_id: str) -> Mapping[str, str]`。新测试将真实 RunRepository 用只暴露 Protocol 声明方法的 wrapper 替代，分别确认成功验证和插件版本不匹配错误路径。
- B-R6 两个入口现在共用 `scripts/check_project.py` 内的三项边界规则函数。负例测试覆盖 supervisor 给定的三种具体绕过，正例覆盖 UoW `transaction()`、插件 `tool.execute()`、registry/authoring 多层读取等既有合法调用。check_project 保留动态 SQL execute 检查并拒绝仓储 `.query`。
- 定向测试14项通过；项目检查和 diff 检查通过。Supervisor `supervisor-probes.py` 实跑确认真实 R5 成功，R6 三条注入违规分别导致单测失败；临时副本 check_project 退出1并定位三条违规。详见 validation.md。
- 尚未由 supervisor 复审本次修复，不标记 R5/R6 关闭；不重开已关闭项目，不声明 B 通过。增量快照及哈希将另行交付。


## B-R5/B-R6 冻结增量最终复审 · 2026-09-25

审核署名：REQ-010 独立审核接手任务（Codex）。**B-R5、B-R6通过并关闭；结合前轮B范围审核及§14复验，阶段B独立审核通过。** A阶段及A-R1/A-R2/F-R1/F-R2、B-R1至B-R4保持关闭。本结论不代表C/D或leader整体终验通过，已记录的pending_inputs必填org UI基线问题仍保留。

对象：`/var/folders/mp/_s5dz9l54dg01fgqd1f_jk2h0000gn/T/taskweave-req010-ab-r5-r6-0z786mmr/source`。manifest SHA-256 `9bda8068ac15b1170494961fd8c8ec8020b65d9816798c914f080df2b40088a8`；delta-manifest SHA-256 `f05708f959011dd6192a96e7cee925c526e9bc71e141d6a46ad2d0ae55541b60`。审核者独立核验473个文件的大小/hash，且与r14 manifest实际差异恰为7文件、零删除。产品源码仅core/repositories.py增添端口声明，其余为检查脚本、两份测试及三份需求文档；SQL资源保持完整。

- B-R5：RunRepository声明 `attempt_versions(attempt_id: str) -> Mapping[str, str]`，与具体仓储读取插件版本映射及确认用例一致。真实临时SQLite的声明端口包装确认成功；版本替代对象返回不一致映射时抛PLUGIN_VERSION_MISMATCH且步骤仍为DRAFT。审核者上轮原始独立探针不改动重跑，具体仓储VALIDATED、仅暴露端口声明的包装同样成功，原AttributeError消失。
- B-R6：architecture tests与check_project共用三个检查函数；runtime检查低层query/execute/transaction，application识别query及SQL execute（含f-string）/仓储低层调用，Controller识别application到仓储的越界链。常驻负例覆盖审核列出的三类绕过；正例覆盖application UoW transaction、插件tool.execute及现有registry/authoring多层调用。审核者将原探针在外部临时副本注入的五条违规语句原样重跑，三项边界测试全部按预期失败，check_project退出1并报告各位置；正常快照检查退出0。临时副本自动移除，未修改产品代码或冻结原件。本项验证的是规定结构边界，并不声称进行任意Python别名/数据流分析。

在新快照cwd实际运行：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/src" uv run --project /Users/dasensen/PycharmProjects/taskweave python -m unittest tests.repositories.test_repository_contracts tests.test_architecture_boundaries tests.application.test_step_run_repository_port -v
```

退出0，**14项通过，1.807秒**；日志为快照父目录 `reviewer-r5-r6-tests.log`。同样运行前缀执行首个AB父目录保留的supervisor-probes.py，探针记录上述端口成功与边界负例拒绝（3项预期失败，0.070秒），详见新快照父目录 `reviewer-r5-r6-probes.log`。运行前缀下独立确认taskweave.__file__指向该快照src，并执行check_project.main，退出0、116份Markdown检查通过。另一次仅核对manifest的系统Python辅助命令在完成差异断言后误附加import，因未设置包路径报ModuleNotFoundError；随后上述规定uv/PYTHONPATH命令验证导入正确，非产品失败。

只增量复验R5/R6，没有重复A/B全组、全量测试或已知UI基线失败测试。所有业务探针使用临时home。审核者仅追加本审核记录，结论同步leader及原实施者。

## A-R1/A-R2 与 B-R1/R2/R3 新 supervisor 复审 · 2026-09-25

范围仅限 design.md 第12、13节涉及的五项，不代表 C/D 或整体验收通过。首轮审核对象为 `stage-b-r5-r6` 冻结快照：`/var/folders/mp/_s5dz9l54dg01fgqd1f_jk2h0000gn/T/taskweave-req010-ab-r5-r6-0z786mmr/source`。manifest SHA-256 为 `9bda8068ac15b1170494961fd8c8ec8020b65d9816798c914f080df2b40088a8`；473 个条目逐项大小/hash 核对一致，两个 SQL 包资源存在且哈希与记录一致。B-R2 补测在工作区做增量复审。

- **A-R1 通过**：Protocol 返回类型与实际返回值一致；契约测试覆盖签名 kind/default、重复声明、排序边界与实际交换、顺序和 revision。
- **A-R2 通过**：协作协议仅在基础设施层；仅暴露声明能力的适配对象覆盖计划复制中途失败回滚，以及结果删除锁拒绝时状态/文件保留和解锁后删除。
- **B-R1 通过**：真实 SQLite 覆盖空集、同任务多运行、跨任务隔离，且 `Coordinator.clear_task_runs` 实际消费此查询。
- **B-R2 首轮提出 P2 补测要求，后续通过关闭**：最初 `tests/repositories/test_task_repository.py` 未在第二次写入失败前断言目标已有一步，也未完整比较源快照。返修增加失败前目标任务存在/恰有一步及源快照不变断言；失败后断言只保留源任务、目标步骤为空、源快照仍完全一致。patch 继续使用同一具体 StepRepository 和原 bound method。新 supervisor 增量复审确认通过，无新增问题。
- **B-R3 通过**：隐私测试适配当前 Application 及真实规划组/采集项；覆盖存储原文及显示/AI 开关独立生效。

首轮 supervisor 的直接相关复跑 13 项通过；`tests.test_planning` 全模块因快照环境缺少 nicegui 有 4 项导入错误，未将其计为通过。B-R2 返修复跑 `tests.repositories.test_task_repository.TaskRepositoryTests.test_copy_failure_rolls_back_partial_task_and_keeps_source` 和 `tests.test_task_transfer.TaskTransfer.test_mid_import_failure_leaves_no_partial_task`：2 项通过。

返修后本工作区复跑：

```bash
PYTHONDONTWRITEBYTECODE=1 uv run python -m unittest tests.repositories.test_repository_contracts tests.repositories.test_context_return_contracts tests.repositories.test_collaboration_ports tests.repositories.test_run_repository tests.repositories.test_task_repository tests.test_task_transfer tests.test_privacy_settings -v
```

退出码 0，24 项通过，4.064 秒。`PYTHONDONTWRITEBYTECODE=1 uv run python scripts/check_project.py` 退出码 0；`git diff --check` 退出码 0。未运行全量测试。此结论只关闭 A-R1/A-R2、B-R1/R2/R3，不改变其他阶段状态。

## 新 supervisor 对 A/B 五项及 §15 修复的增量复审 · 2026-09-25

复审者：`/root/supervisor_final_reround`（本轮新建的独立只读 supervisor）。复审对象为冻结源码目录 `/var/folders/mp/_s5dz9l54dg01fgqd1f_jk2h0000gn/T/taskweave-ddd-baseline-ym4aaase/stage-ab-five-findings-c15-review/source`，manifest 声明 359 个文件，逐项路径/大小/SHA-256 校验均匹配；manifest 摘要记录于相邻 `manifest.sha256`。

**结论：A-R1、A-R2、B-R1、B-R2、B-R3 均可关闭。** §15 环境草稿保留与排队保存修复的定向行为也通过复审。该结论仅覆盖列明问题，不代表 B 阶段、REQ-010、C/D 或 leader 最终验收完成。

复审者从冻结源码运行两组定向测试：

- 仓储契约/上下文返回/协作端口/UoW/运行仓储/任务导入/隐私/TrialInputPanel/StepEditor：37 项通过，4.080 秒。
- Application composition/planning/context sessions/task cleanup：28 项通过，7.925 秒。

逐项结论依据：A-R1 的上下文标签与重排实际行为、边界和 revision 断言及适配器协议签名一致；A-R2 的可替换 copier/lock guard、复制回滚和锁定删除路径有覆盖；B-R1 的 task-scoped 查询被实际清理消费者使用并由测试覆盖；B-R2 在同一 steps 对象上 patch 原 bound method，并在注入第二步失败前确认首步落库；B-R3 使用真实 Application 装配和持久化上下文验证隐私行为。§15 的 `TrialInputPanel` 保留空必填值、无效 JSON 与编辑覆盖；新执行仅允许省略未填写的必填输入、已填写值仍验证；排队保存保留请求时文档快照，并在锁内读取最新 `old_step`，测试核对 `h0` 后 `h1`。

限制：`tests.test_input_ui` 的整条浏览器路径仍在后续调试结束交互失败，不能称端到端通过。`test_web_chat` 已由 leader 在当前与原始冻结源码确认相同基线失败，继续单独记录。两者均不改变上述五项 findings 的关闭结论，也不应扩展为 REQ-010 整体通过。


## C 冻结候选独立复审 · 2026-09-25

审核署名：taskweave-supervisor-sol-req010，task `01a0d501-6da3-77a2-98d4-484a9f1a7731`（Codex）。**阶段C暂不通过，C-R1至C-R5五项P2待返修。** 没有重新审核或撤销A/B：对比已通过B冻结manifest，A/B产品代码保持一致；额外test_task_repository复制回滚测试补强单列保留，不混同B-R2任务导入。A-R1/A-R2/F-R1/F-R2及B-R1至B-R6保持关闭。D与整体终验不在本轮结论内。

### 审核对象与范围

只审冻结目录 `/var/folders/mp/_s5dz9l54dg01fgqd1f_jk2h0000gn/T/taskweave-req010-c-review-final-30ennoqt/source`；manifest SHA-256 `54cded2c61f9cbc56c3bb78516e28aa39560d223153ebe9d1c77d5acef97d298`。独立逐项核对324文件大小/hash全部一致；测试后再次核对324项未变。两个SQL资源存在，hash与交付声明一致。规定uv运行前缀下确认taskweave导入来自冻结src，临时Application初始化成功且task.list返回[]。

审阅design §§5/8/11/15、plan C、组件/页面/状态/Workbench接线及受影响测试迁移。无任意host/mixin新增，但具体职责和生命周期仍未达到设计边界，见C-R3。leader本轮确认没有批准所有权例外。生产修复仍由原Luna负责，审核者只追加本记录；未读取原工作区HEAD替代冻结对象、未修改冻结源码或用户数据库。

### 实际验证

以下均在冻结source cwd，使用前缀：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/src" uv run --project /Users/dasensen/PycharmProjects/taskweave python
```

| 命令/范围 | 实际结果 | 冻结目录父层日志 |
| --- | --- | --- |
| `-m unittest discover -s tests/ui -v` | 39通过，0.117秒，退出0 | reviewer-c-ui.log |
| `-m unittest tests.test_input_ui tests.test_confirmation_ui tests.test_trial_variable_groups tests.test_context_cards tests.test_display tests.test_result_views tests.test_task_config_refresh tests.test_desktop_step_save tests.test_planning tests.test_workbench_changes -v` | 61通过，94.609秒，退出0；含真实输入浏览器路径 | reviewer-c-regression.log |
| `-m unittest tests.test_workbench_browser -v` | 1通过，95.269秒，退出0；本地模型fixture和临时home | reviewer-c-browser.log |
| WebChatTests除已知容量断言外7方法，加RuntimeInputs.test_pending_popup_reads_local_inputs_not_public_summary | 7通过、1失败，3.526秒，退出1，失败详见C-R4 | reviewer-c-extra.log |
| `scripts/check_project.py` | 退出1，缺3个目录和1个链接目标，详见C-R5 | reviewer-c-check.log |
| `../reviewer-c-probes.py` | 确认C-R1真实装配回调错误及C-R2迟到反馈污染，退出0表示成功复现问题 | reviewer-c-probes.log |

WebChat定向集合通过TestLoader获取WebChatTests全部方法，仅排除 `test_selected_history_is_not_silently_dropped_when_it_does_not_fit`；没有重跑已由leader归因的容量基线失败。没有运行全量测试或重复A/B大组。原运行补录测试此轮必须覆盖，因为C授权修复原org异常，不能沿用旧豁免。

已确认的正向证据：§15同目标串行保存使用h0、h1并保留各自触发时的文档；跨目标/页面迟到保存不改新old_step；环境切换的真实浏览器流程保留空必填和未完成JSON、更新环境说明；提交校验仍拒绝无效输入。旧save_all调用已移除，当前上下文批量提交行为测试通过。编辑器/执行详情已有timer.delete幂等测试及离页run.list迟到回复保护，但不能据此推断全部异步路径或所有页面生命周期已覆盖。

### [P2] C-R1：同步环境回调被await，再次调试启动后报错

位置：`desktop/workbench.py:376`（实际装配update_environment同步lambda/setattr）；`desktop/components/step_debug.py:115`及`:141`（await该回调）。组件测试注入AsyncMock，掩盖真实同步约定。

独立复现使用真实Workbench构造（仅替代UI绘制及外部controller），保留实际装配的update_environment；配置同环境、可继续的已有调试，调用start_trial(..., continue_session=True)。repeat_trial被调用一次、trials已登记new-run，随后抛 `TypeError: object NoneType can't be used in 'await' expression`，settle_trial_start调用次数为0。运行已启动，UI却报失败且跳过后续同步；普通弹窗launch也有相同静态错误。完整可运行脚本位于快照父目录reviewer-c-probes.py。

修复要求：统一回调同步/异步契约，按真实装配验证再次调试及弹窗启动路径，确认环境/表单/tabs与settle调用完成。不要仅把测试回调继续设为AsyncMock，也不要在异常后重新启动已创建的run。

### [P2] C-R2：迟到调试反馈覆盖另一编辑器状态

位置：`desktop/workbench.py:955-959`；同方法978行日志await之后也没有身份检查。refresh_trial前半段虽然检查task/step/代次，但trial_feedback返回后直接赋值debug_feedback/debug_feedback_run_id。

独立Event探针阻塞step-a/run-a的trial_feedback；等待期间切换为step-b，递增step/page代次并设置B的新反馈，释放A请求后实际得到 `current step step-b; feedback run run-a; feedback {'trial_logs': 'OLD STEP A'}`。这违反§11迟到结果不能污染新步骤，定时刷新不受全局button busy保护。

修复要求：将完整调试刷新放入拥有该状态的组件，并在各await后检查捕获的task/step/run及页面代次，再更新状态或渲染；旧run请求可完成，不能为了导航终止后台运行。补跨步骤、同一步骤替换run及离页/重绘后迟到反馈与日志的行为测试。仅比较当前step不足以关闭此项。

### [P2] C-R3：Workbench仍承担组件主体，RenderContext反向同步保留共享控件耦合

位置：`desktop/workbench.py:785-817`、`:885-981`、`:1105-1328`；`desktop/components/step_editor.py:24-109`；`desktop/components/step_contexts.py:6-34`。

Workbench.refresh_trial仍拥有完整反馈/结果/日志渲染与状态更新；上下文save_context_batch、采集/预览/删除/排序及collect_context弹窗主体仍在Workbench。StepContextPanel仅构建ContextCards，把主要工作回调到外壳。StepEditorRenderContext同时携带大量跨调试/AI/上下文回调和控件，_sync_editor_view再把12个控件反向复制进Workbench供业务方法读取。这不是约定的“外壳+显式兼容转发”，也没有让StepEditor真正拥有并组合自己的子组件。缺少render/dispose协议的页面（含PlanningPage）仍未纳入统一离页生命周期；当前paint只直接dispose StepEditor和ExecutionDetails。

leader本轮已明确没有设计例外。需按既有§5/11把调试显示/输入/反馈与上下文草稿/采集CRUD放到对应组件，组件持有局部状态和控件；Workbench保留导航、公共busy helper、装配及明确委托。避免进一步扩大RenderContext或增加镜像属性。页面按设计管理render/dispose及失效身份，离页获准后释放绑定，取消/保存失败保留当前草稿与实例。补组件可独立运行的上下文取消/一次提交/失败保留、离页取消/保存失败不导航、迟到刷新及timer卸载测试；不能只验证类名/字段存在或mock掉实际组合接线。

### [P2] C-R4：补录弹窗测试漏迁UI替代目标，当前失败不是旧基线错误

位置：`tests/test_runtime_inputs.py:182-187`。迁移后已patch run_inputs.ui、workbench.ui、forms.ui，却遗漏实际创建三组expansion的trial_inputs.ui。原样执行当前快照用例，titles实际[]，与三组标题断言不等，退出1；不是此前已归因的org FORM_INVALID。

审核者不改冻结文件，仅在外部诊断脚本把同一fake UI额外路由到trial_inputs.ui后，原测试与原断言完整通过（1项1.942秒）。脚本及日志为快照父目录reviewer-c-popup-fixture.py/.log；命令使用上述前缀且PYTHONPATH增加冻结cwd以导入tests。首轮外部脚本未加入cwd时仅因找不到tests包退出，修正运行路径后获得上述有效结果。该诊断支持fixture根因，并确认原org异常路径已经修复，不能用删除三组断言来掩盖迁移遗漏。

需补准确测试依赖或迁为等价真实组件行为验证，并保留私有输入读取、单请求不重复弹窗和三组布局断言；重新执行该方法，将当前失败如实记入返修前证据。

### [P2] C-R5：交付快照不能独立执行规定工程检查

对象：冻结manifest/source；`src/taskweave/desktop/README.md`的新链接。虽然324项hash与SQL可运行性都正确，source没有apps、config、examples，而scripts/check_project.py要求它们；README链接的 `.superpowers/sdd/req010-ui-components/progress.md` 也没有包含。原样从快照cwd运行check_project退出1，依次报告三个Missing及该Broken link。交付中引用的这份C实施记录也无法阅读。

这是交付/验证完整性问题，不推断产品SQL资源损坏，也不撤销A/B。请保留当前失败冻结对象，另发包含检查所需目录/文件及有效文档链接的新冻结目录与manifest；从新快照自身cwd执行规定检查并提供结果，不借原工作树隐式补文件，不削弱工程检查来迎合省略的快照。

上述五项已直接通知原Luna并同步leader。C阶段继续待返修；既有通过测试与已关闭A/B不因本轮发现被无差别重跑。原工作区git diff --check仅为实施者声明，本轮遵守只审冻结对象要求，未以原HEAD检查替代冻结验证，也不声称本轮工程检查通过。

## C-R1..R5 新 supervisor 返修复审 · 2026-09-25

复审者为独立 C reround supervisor，范围仅限冻结快照 `/var/folders/mp/_s5dz9l54dg01fgqd1f_jk2h0000gn/T/taskweave-req010-c-review-ready-azlcdgjx/source`。manifest SHA-256 `b5d76a2d1eb3d27ede4001e4853bc5a86cd23d5b72964e3621397e96e5b75c25`，346 项哈希均匹配。C-R1、R2、R4、R5 通过关闭；C-R3 仍待返修，不代表阶段 C 或整体 REQ-010 通过。

- C-R1 关闭：重复调试同步环境回调行为测试通过；supervisor另以只读fake UI探针走完新调试弹窗路径，确认run登记、环境与表单更新、settle完成。
- C-R2 关闭：完整刷新位于StepDebugPanel；每个await后按task/step/editor generation/page generation/run id校验。切步骤、同一步骤替换run、离页三条迟到响应测试通过。
- C-R3 未关闭：采集、CRUD和调试刷新已提取，但StepContextPanel缺dispose且遗留panel/cards引用；缺上下文取消/单次提交/失败保留草稿及离页取消/保存失败不导航行为覆盖。实施者在本轮为ContextPanel加入dispose/代次防护，Workbench离开editor时释放；新增取消确认维持草稿、失败后重试、Workbench重叠点击只提交一次、编辑器取消离页及规划保存失败留页测试。待新快照复审。
- C-R4 关闭：trial_inputs.ui fake patch修正，三组标题断言保留并通过。
- C-R5 关闭：supervisor从冻结快照cwd执行check_project.py退出0；apps/config/examples及README链接目标均齐备。

首次C返修快照定向20项通过，快照工程检查通过。C-R3增量定向测试及下一次复审快照的hash/运行结果见validation.md。A/B不重开，D与整体验收不在该结论范围。

### C-R3 第2轮返修补充 · 2026-09-25

第1个返修快照的复审确认C-R1/R2/R4/R5关闭；C-R3仍开放。具体复现：ContextCards.move_entry在await StepContextPanel.move_group之后无条件修改共享entries及旧panel；remove同样在delete回调await后继续修改列表/卡片。supervisor在346文件冻结快照验证所有hash一致并复现该竞态。返修现将`is_active`生命周期守卫传给ContextCards，在move/delete await返回后、改动列表/卡片前检查，并在组件失活后抑制旧UI错误提示。新增真实ContextCards操作方法与StepContextPanel回调/共享状态的组合测试，覆盖等待中的排序及删除离页；50项UI测试此前通过，本次23项上下文/卡片/导航/按钮集合通过。全新冻结快照待独立复审，C-R3目前仍记为开放。

## C-R3 最终增量复审关闭 · 2026-09-25

新 supervisor 仅针对C-R3复核冻结快照 `/var/folders/mp/_s5dz9l54dg01fgqd1f_jk2h0000gn/T/taskweave-req010-c-r3-final-xeuleo0_/source`，manifest SHA-256 `0203ee5c0112dc73579151372db3317bbaeee4c732f0576c59465c48d95ff535`；346个文件的大小和SHA-256全部匹配，复审后再次核验仍一致。**C-R3关闭**。审查确认 `ContextCards.move_entry()` 和 `remove()` 在await之后、修改共享列表/卡片前检查is_active；离页后抑制旧UI错误通知。StepContextPanel.dispose递增代次并释放panel/cards，Workbench仅在导航获准后调用离页释放。新增的组合测试在排序/删除请求等待期间执行dispose，确认共享条目和卡片控件均未发生迟到写入。

从快照cwd运行 `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/src" uv run --project /Users/dasensen/PycharmProjects/taskweave python -m unittest tests.ui.test_step_context_panel tests.test_context_cards tests.ui.test_navigation tests.ui.test_button_dispatch -v`：23项通过；同cwd执行 `scripts/check_project.py`：PASS，布局、语法、依赖边界、117份Markdown和CLI version检查通过。首个不带项目环境指定的uv命令在reviewer环境触发过缺NiceGUI的隔离环境，reviewer移除该临时虚拟环境后使用已配置项目依赖及快照PYTHONPATH重跑成功；冻结源码未改。A/B和全量测试未运行。

至此本次C-R1..C-R5复审范围内五项均关闭。该结论不代表阶段D或REQ-010整体验收完成。


## 指定审核者最终 C 候选复审 · 2026-09-25

审核署名：taskweave-supervisor-sol-req010，task `01a0d501-6da3-77a2-98d4-484a9f1a7731`。leader明确要求本任务核实其他reround记录并决定C整体结论。**C仍暂不通过：原C-R1/R2/R4/R5本轮确认关闭，C-R3仅部分修复，新增C-R6（P1）、C-R7/C-R8（P2）待修。** 不接受仅ContextCards竞态修复即等于C整体完成；A/B已通过结论不变，D及整体终验另行验收。

### 冻结对象与独立验证

对象：`/var/folders/mp/_s5dz9l54dg01fgqd1f_jk2h0000gn/T/taskweave-req010-c-r3-final-xeuleo0_/source`，manifest SHA-256 `0203ee5c0112dc73579151372db3317bbaeee4c732f0576c59465c48d95ff535`。此manifest以files数组列条目，审核者按实际格式逐项核对346项大小/hash一致。相对首个C无删除，变化限desktop与相关测试/文档及补齐的检查目录；A/B业务代码未改，不重复其大组。

运行均从冻结source cwd，前缀为 `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/src" uv run --project /Users/dasensen/PycharmProjects/taskweave python`；导入tests的外部诊断脚本另把冻结cwd加入PYTHONPATH。日志均保存在本冻结父目录：

- `-m unittest discover -s tests/ui -v`：52通过，0.197秒，退出0，designated-c-ui.log。
- `-m unittest tests.test_runtime_inputs.RuntimeInputs.test_pending_popup_reads_local_inputs_not_public_summary -v`：1通过，1.509秒，退出0，designated-c-popup.log。
- `scripts/check_project.py`：退出0，117份Markdown，designated-c-check.log。C-R5原缺目录及文档链接已恢复。
- `-m unittest tests.test_workbench_browser -v`：1失败，85.711秒；tests/test_workbench_browser.py:162等待“采纳到编辑器”超时，designated-c-browser.log。为保留现场仅追加一次诊断重跑，未改产品源码/测试断言，仍同处失败，81.730秒，designated-c-browser-diagnostic.log。不是已知web_chat容量基线失败。
- `../designated-c-render.py`：真实临时Application、DesktopController和实际NiceGUI控件渲染，复现C-R6；designated-c-render.log。
- `../designated-c-probes.py`：实际Workbench装配（仅UI绘制/外部controller替代）复现C-R7/C-R8，并以诊断性正确getter复核原C-R1回调修复；designated-c-probes.log。
- `../designated-c-context-submit.py`：捕获真实StepContextPanel.collect创建的确认保存on_click，Event阻塞后重入，复现双提交；designated-c-context-submit.log。

探针退出0代表成功确认所述问题，不代表业务通过。没有运行全量、A/B大组或已知web_chat容量失败。未改用户库、原冻结源码；所有业务数据为临时home。

### 原五项结论

| 发现 | 本轮结论与依据 |
| --- | --- |
| C-R1 | 关闭原同步回调被await问题：同步返回值仅在awaitable时等待。52组件测试相关项通过；实际Workbench保留原同步setter、诊断性修正C-R7 getter后，repeat调用1、settle调用1，无TypeError。新的getter错误单列C-R7，不能以关闭R1掩盖。 |
| C-R2 | 关闭：完整刷新已迁入StepDebugPanel，反馈和日志await后检查task/step/编辑器代次/页面代次/run。跨步、换run及离页相关行为测试通过。C-R8是另一个共享映射装配问题。 |
| C-R3 | 部分修复、未关闭，具体剩余见下。 |
| C-R4 | 关闭：补录测试新增正确trial_inputs.ui替代目标，原三组标题和单弹窗断言保留，原样实跑通过。 |
| C-R5 | 关闭：当前冻结cwd独立check_project通过，所需apps/config/examples及文档链接目标齐全。 |

### C-R3 [P2]剩余：真实组件入口与所有权仍未完全落地

已认可的修复：refresh_trial反馈/日志主体迁入StepDebugPanel；context采集/CRUD/草稿主体迁入StepContextPanel；AI生成/确认逻辑迁入StepAIEditor；移除_sync_editor_view反向赋值；ContextCards move/delete在await后检查组件活性，ContextPanel.dispose清理引用；取消离页及保存失败留页测试通过。这些是实质进展，不再重复旧“主体完全未搬”的描述。

但原要求的“确认一次提交”仍未成立。`components/step_contexts.py:296-317` 中确认保存绑定裸ui.button，其回调没有busy/in-flight保护。当前test_overlapping_clicks_submit_once只测试Workbench.button，实际确认入口不经过它。审核者调用真实collect渲染出来的on_click，第一个context.save_batch挂起期间再次点击，controller被调用2次，返回后state.entries为两个新group（['1','2']）。不是只按静态代码推测。需保护实际入口，并验证重叠点击一次提交、失败草稿保留且可单次重试。

完整所有权也仍有剩余：Workbench.mark_step_pending（793起）和refresh_trial_inputs（807起）仍读写StepEditor.view中的控件并实现编辑器/调试状态流程；settle_trial_start/resume_inputs（882起）仍在外壳调度和更新调试输入。_editor_view/_set_editor_view只是改变访问位置，不等同把这些行为委托给拥有控件的组件。按原§5/11完成这些具体职责委托，不恢复镜像属性或扩大上下文；以真实组合验证输入/保存状态/调试生命周期。新增C-R6至R8正说明仅独立子组件测试不足以验收接线。

### [P1] C-R6：调试组件覆盖同名UI容器，步骤编辑器渲染中断

位置：`components/step_editor.py:447` 将此前 `with ui.column(...) as debug_panel` 的容器局部变量覆盖成 `ctx.debug_panel`（StepDebugPanel业务对象）。464行仍调用debug_panel.set_visibility，后续visible及抽屉切换闭包也继续当作UI容器使用。

真实临时Application创建任务及一步，Workbench(DesktopController(app))后await editor()，实际抛 `AttributeError: 'StepDebugPanel' object has no attribute 'set_visibility'`；edit_controls仍为None。主浏览器因编辑器未完成接线，在AI生成后等不到采纳按钮；本轮两次失败位置一致。这阻断普遍步骤编辑路径，不能被52项mock组件测试绿灯豁免。

需清晰分离抽屉容器与调试业务组件，修复全部闭包引用，并用真实render与主浏览器验证四个标签/抽屉开合/保存/AI/调试。不要为业务组件添加伪造UI方法规避所有权错误。

### [P2] C-R7：装配仍读取已删除的Workbench调试环境属性

位置：`desktop/workbench.py:375`。控件现只存在StepEditor.view['trial_environment']，实际注入却是 `lambda: getattr(self, "trial_environment", None)`，源码没有再赋值该外壳属性。

真实Workbench装配放入view环境uat与输入表单，session.trial_environment()仍为None；首次start_trial(...continue_session=True)抛 `AttributeError: 'NoneType' object has no attribute 'value'`，controller.trial调用0。即便先修复C-R6，也会在正常调试入口触发。本问题也由leader独立复现。

需从真实拥有者注入正确访问入口，并覆盖首次、重复及流程调试的真实装配；不能恢复外壳重复控件字段。修复后确认选中环境、输入、run登记与settle均完成。

### [P2] C-R8：空trials映射被替换，调试历史恢复与AI消费者失去共享状态

位置：`components/step_debug.py:173`、`components/step_ai.py:16` 的 `trials or {}`。Workbench初始trials={}是有意共享对象，两个构造函数因空字典为假各建新字典。

实际装配复现panel.trials is Workbench.trials为False。refresh_trial从run.list发现step s的历史run old，写入panel.trials后通过外部run_id getter核验时得到None，因此提前退出：panel={'s':'old'}、Workbench={}、trial_area.clear调用0，历史反馈始终不显示。AIEditor也不会看到后续由StepDebugSession写入Workbench.trials的run，修复/确认无法按真实最近运行选择证据。

需只在未提供映射时创建默认对象，保留传入空映射的身份，并测试真实装配从空映射恢复历史run及新调试后AI修复/确认读取同一run；不要在每处复制同步字典。

上述结论已直接发原Luna并抄送leader。指定审核者不签署当前C通过，返修只针对未关闭部分和新增回归；原R1/R2/R4/R5及A/B通过部分保持，不无差别重跑。其他reround关闭记录仅代表其当时限定范围，不覆盖本轮独立复现。


### [P1] C-R9 补充：旧上下文弹窗迟到确认会写入新步骤（同轮生命周期探针）

leader提示后，审核者对上述同一最终冻结对象独立验证实际入口。位置：`components/step_contexts.py:46-54` 的save_batch启动时读取动态self.step_id()；collect的确认保存闭包在调用它之前不检查打开弹窗时的generation/目标。collect开头若干await同样没有检查开场身份；返回后UI活性保护不能阻止错误目标写入。

探针真实执行StepContextPanel.collect并捕获“确认保存”on_click（仅UI绘制和controller替代），打开目标为step-a；随后dispose并将当前目标改为step-b，调用旧弹窗排队的确认回调。实际controller收到1次context.save_batch，step_id为step-b，组件列表也添加新组。回调应失效，不得向新步骤发持久化请求。证据为冻结父目录designated-c-context-stale.py/.log：`disposed step-a dialog confirmation: context.save_batch calls=1; persisted target step_ids=['step-b']; groups=['1']`。

该问题单列C-R9（P1），也证明C-R3生命周期尚未完整关闭。需在开弹窗时绑定task/step/代次，在可能持久化前检查身份并使用原目标；collect前置await、目标刷新、采集/保存/预览及关闭回调也应守护同一生命周期。失效后应不发写请求、不污染新组件；不通过删除后台run或取消原已授权持久化来伪装修复。补真实collect入口的开场await中离页与旧弹窗迟到确认测试，与重复提交、失败重试一起验证。最终开放项为C-R3、C-R6、C-R7、C-R8、C-R9；原R1/R2/R4/R5保持关闭。


## 指定审核者 C 最终返修验收 · 2026-09-25

审核署名：taskweave-supervisor-sol-req010，task `01a0d501-6da3-77a2-98d4-484a9f1a7731`。**本轮C-R3、C-R6、C-R7、C-R8、C-R9通过关闭；结合此前C范围审核与已关闭C-R1/R2/R4/R5，阶段C独立审核通过。** A/B既有签署保持不变。本结论不验收D，也不代表REQ-010整体或leader最终验收完成。

### 对象、范围与不变性

对象为leader冻结的 `/var/folders/mp/_s5dz9l54dg01fgqd1f_jk2h0000gn/T/taskweave-leader-c-reround-rhb45c0h/source`；manifest SHA-256 `f724c2f859d1206ab55801dc3ab112016c7924cf7e374335781b63e3afd9d478`。审核者独立按files数组核对339项大小/hash，验证后再核对全部339项未变。SQL资源、apps/config/examples及链接的C实施记录齐全。真实临时Application初始化并经DesktopController渲染NiceGUI编辑器成功。

依据design §§5/11/15/16核验开放问题、方法所有权、实际控件组合、迟到响应和补录时序；没有只复验ContextCards竞态即推定整个C通过。D在途选择器、映射与文档随快照存在，仅作为可重现材料，本轮没有签署其正确性。没有改动产品源码、冻结文件或用户数据库；业务探针使用临时home，其他组件测试使用外部controller替代。

### 五项逐条关闭依据

| 发现 | 独立核验结果 |
| --- | --- |
| C-R3 | 按§16，mark_step_pending/refresh_trial_inputs主体在StepEditor，settle_trial_start/enter_debug在StepDebugSession，resume_inputs校验与两条运行命令在RunInputDialog；Workbench对应方法仅明确委托，输入回填/刷新失效通过身份受限回调，不恢复镜像控件。StepEditor fallback先clear容器再创建控件，并在返回后校验身份。上下文真实确认入口具备组件在途保护，复用原探针从2次写入变为1次；取消保留、失败重试、离页取消/保存失败、timer卸载及卡片迟到响应相关行为测试通过。 |
| C-R6 | 抽屉UI容器与StepDebugPanel业务对象分别命名/引用。真实Application+实际NiceGUI渲染完成且edit_controls非空，不再触发set_visibility错误；主浏览器覆盖编辑、AI、调试、正式运行等真实接线通过。 |
| C-R7 | 实际StepDebugSession环境getter返回StepEditor.view持有的同一控件。真实装配探针断言对象身份；首次调试由主浏览器覆盖，再次调试的实际Workbench接线测试验证环境/输入/run登记与settle调用，未恢复Workbench控件镜像。 |
| C-R8 | 传入空trials字典保留同一对象，Workbench、StepDebugPanel、StepAIEditor身份相同。真实装配测试覆盖历史run恢复后继续读取步骤/事件及新调试后AI/调试消费者看到同一run；不再发生私有空映射导致的提前退出。 |
| C-R9 | collect建立时绑定task/step/组件代次；前置await及持久化前检查原身份。复用原真实collect按钮探针，在step-a弹窗dispose后切step-b，旧确认回调不发任何写请求、无新组。已合法发送的原目标请求允许完成，旧UI更新受限；不结束后台run。 |

补录时序另以真实Workbench装配的RunInputDialog协作和Event独立验证两种情况：run.inputs等待期间离页，以及不离页而把同一步骤当前run替换。两者均按捕获的run-a执行run.start恰好一次，mode=ONE/target保留；新表单不回填，run/trial signature保持新页面值。写前身份失效的常驻测试也通过。这验证§16的“写后仍完成原运行继续命令”，没有因UI过期把已清除waiting_input的PAUSED运行搁置。

原确认模块已迁到真实StepAIEditor职责，保留成功证据、缺失/过期证据、手动确认取消及API/Chat/取消选择断言；不为旧Workbench.__new__ fixture修改产品接口。

### 实际命令与证据

全部从上述source cwd运行，前缀：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/src" uv run --project /Users/dasensen/PycharmProjects/taskweave python
```

| 命令/探针 | 结果 | 同冻结父目录日志 |
| --- | --- | --- |
| `-m unittest discover -s tests/ui -v` | 63通过，0.199秒，退出0 | designated-c2-ui.log |
| `-m unittest tests.test_confirmation_ui tests.test_trial_variable_groups tests.ui.test_run_input_validation tests.test_runtime_inputs.RuntimeInputs.test_pending_popup_reads_local_inputs_not_public_summary -v` | 10通过，1.190秒，退出0；与上一组部分重复，不宣称唯一用例总数 | designated-c2-targeted.log |
| `-m unittest tests.test_workbench_browser tests.test_input_ui -v` | 2通过，173.888秒，退出0；真实NiceGUI/Chromium、本地模型fixture、临时home | designated-c2-browsers.log |
| `scripts/check_project.py` | 退出0，118份Markdown及工程/边界检查通过 | designated-c2-check.log |
| `../designated-c2-render.py` | 真实Application/NiceGUI编辑器渲染、环境getter、共享空映射身份断言通过 | designated-c2-render.log |
| `../designated-c2-context-submit.py` | 真实渲染确认入口重叠点击仅1次持久化请求/1个组 | designated-c2-context-submit.log |
| `../designated-c2-context-stale.py` | 旧弹窗确认在持久化前被拒绝，写请求0、组0 | designated-c2-context-stale.log |
| `../designated-c2-input-race.py` | 两种Event时序均原run.start一次且新UI不变 | designated-c2-input-race.log |

上述独立脚本均在冻结父目录，可重现；旧失败快照和探针继续保留。没有运行全量、A/B大组或重复已明确归因的web_chat容量失败；Windows/真实模型账号等也未新增验收。只追加本审核记录，结论同步原Luna与leader，后续接续D审核和leader终验。


## 指定审核者 D 首轮独立审核 · 2026-09-25

审核署名：taskweave-supervisor-sol-req010，task `01a0d501-6da3-77a2-98d4-484a9f1a7731`。**D暂不通过：D-R1/P2开放。** A/B/C既有独立签署保持不变，REQ-010整体和leader终验未完成。

对象为leader冻结的 `/var/folders/mp/_s5dz9l54dg01fgqd1f_jk2h0000gn/T/taskweave-leader-d-final-n55ajq4k/source`；manifest SHA-256 `802e1c43ddf88daf380cd63f494d7f935f3d3e60a88fe42a542e9ec5b4da2a7a`。独立核对340项文件大小/hash，验证后复核340项未变。产品src代码和资源相对已签署C无变更，因此没有重跑A/B大组或C浏览器。

### [P2] D-R1：应用消费者依赖漏边导致 changed 选择器漏选回归

`tests/module-map.json`中application.runs/steps/authoring未声明repository.runs依赖。实际RunUseCases直接使用RunRepository；StepUseCases使用trial、反馈和attempt_versions；Authoring读取run反馈。独立执行 `--changed src/taskweave/infrastructure/repositories/runs.py --dry-run`，仅选中repository.runs，漏掉实际应用消费者及其UI、HTTP、interval、确认、AI回归。

Authoring还直接调用ResultRepository.refs_for_attempt，但application.authoring缺少repository.results依赖。results.py变化虽选中repository.runs、repository.results、application.runs和部分UI，却遗漏Authoring及其消费者。EnvironmentUseCases也直接消费RunRepository和PlanRepositoryPort，当前仅声明repository.environments同样不足。该问题属于实际依赖图不完整，不是反向闭包算法本身失效。

需按leader§17完整应用依赖裁决核对直接仓储及用例/运行协作消费者，调整错误依赖方向，补实际源文件变更到消费模块和测试目标的断言。不得只补单个示例或以粗模块标签强造循环；共享文件可映射多个实际消费者。已将阻断同步原Luna和leader，等待新的D冻结增量。

### 独立验证证据

命令均从冻结source执行，Python前缀为 `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/src" uv run --project /Users/dasensen/PycharmProjects/taskweave python`；收集脚本另将source根加入PYTHONPATH。日志位于同冻结父目录。

| 验证 | 实际结果 | 日志 |
| --- | --- | --- |
| `-m unittest tests.test_module_selection -v` | 20通过，2.006秒，退出0 | designated-d-tests.log |
| `scripts/test_modules.py --module ui.tasks` | 实际执行13测试通过，2.900秒，退出0 | designated-d-cli.log |
| `scripts/check_project.py` | 119份Markdown及工程检查通过，退出0 | designated-d-check.log |
| 所有test_*.py逐文件加载，与全部映射目标实际ID对照，仅收集 | 默认345个唯一ID；include-browser后362个唯一ID；缺失0、多余0、重复0、loader errors为0；默认排除17个浏览器ID | designated-d-ids.log |
| 未指定范围、未知模块、未知核心/插件源码、无映射README | 均退出2；没有退回全量discover | designated-d-negative.log |
| dry-run替换run_targets为抛错哨兵 | 正常退出0，未调用测试执行函数 | designated-d-negative.log |
| runs.py实际changed CLI及results.py选择 | 复现D-R1漏选 | designated-d-runs-selection.log、designated-d-ids.log |
| 验证后manifest及340项文件复核 | 全部一致 | designated-d-negative.log |

测试ID核验没有执行全量测试。首次尝试unittest discover收集时因tests为namespace目录不可import而失败，改用逐文件模块名加载后成功；未改变产品或测试结构。默认排除集合包含Workbench/Input UI、Playwright真实浏览器集成/choices及image locator；源码启动入口静态核对与该集合一致。已知web_chat容量基线仍保留映射，本轮未重复运行。

文档收口另有leader指出的全局当前状态头部滞后（requirements索引、docs/progress）；本冻结不视为已修复。待明确文档增量核对ABC通过/D审核中，保留历史，不为状态文本重复功能测试。最终验收稿保持D待审核与leader待终验，不提前签署。


## 指定审核者 D-R1 增量复审与 D 阶段签署 · 2026-09-25

审核署名：taskweave-supervisor-sol-req010，task `01a0d501-6da3-77a2-98d4-484a9f1a7731`。**D-R1/P2关闭，阶段D独立审核通过。** 结合此前A/B/C签署，四阶段独立审核均已完成；REQ-010整体仍须leader最终验收，本签署不替代leader终验。

对象：`/var/folders/mp/_s5dz9l54dg01fgqd1f_jk2h0000gn/T/taskweave-leader-d-r1-a46wf7gt/source`，manifest SHA-256 `3b6019f96afe591101a7793650e0797af7273be4f5732f09f29ff42ece1a3460`。独立验证全部340项大小/hash，并逐文件对照首轮802e1冻结，变化严格等于delta.json所列10文件：map、selector测试及8份文档。产品src、SQL资源、选择器脚本零变化；验证后再次核对340项未变。首轮D的CLI实跑、负输入、dry-run及浏览器分类证据继续有效，不重跑A/B/C浏览器。

依据design §17对照真实应用构造/调用：Authoring五个仓储前置齐全，已移除错误application.steps反边；RunUseCases五仓储和authoring前置齐全；Steps、Tasks、Environments具备直接仓储及runtime/worker所属application.runs的协作依赖；Planning具备planning/contexts/steps仓储及tasks/authoring前置。context_sessions明确多映射到运行、规划、环境实际消费者，图校验无循环。D-R1不再只在仓储层修补。

独立六路径选择探针验证runs.py、results.py、step_contexts.py、application/environments.py、runtime.py、context_sessions.py的消费者闭包和关键目标：runs变更包括steps/authoring/runs/environments及editor/debug/executions/environments UI，HTTP、interval、确认、AI和port测试均被选中；results变更包括Authoring/AI；上下文仓储变更包括任务复制；环境用例变更包括环境UI；runtime与共享session包括各实际应用消费者。六路径默认browser_targets均为空。只断言选择结果，没有执行这些大集合。

从冻结source运行，统一前缀 `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/src" uv run --project /Users/dasensen/PycharmProjects/taskweave python`；独立收集探针另将source根加入PYTHONPATH。

| 验证 | 实际结果 | 同冻结父目录证据 |
| --- | --- | --- |
| `-m unittest tests.test_module_selection -v` | **24通过，1.339秒，退出0**；以本冻结实跑为准，不沿用提交消息中的23项 | designated-d-r1-tests.log |
| 六路径实际变更闭包探针 | 全部断言通过，默认浏览器目标0 | designated-d-r1-probe.log |
| 全部test文件与映射目标逐项加载实际ID，仅收集 | 默认349个唯一ID，浏览器opt-in增加17个，共**366**；覆盖完整、无重复、无loader errors。较首轮362新增4个selector测试 | designated-d-r1-probe.log |
| `scripts/check_project.py` | 119份Markdown及工程/边界检查通过，退出0 | designated-d-r1-check.log |
| manifest及全部文件复核 | 340项一致 | designated-d-r1-probe.log |

文档当前状态头部已统一为A/B/C通过、D返修待审、leader未终验，较早记录明确保留为历史；未提前宣称D或整体通过。本签署发布后由leader统一更新最终状态与final-acceptance稿。首轮与本轮证据共同支持D整体通过。已知web_chat容量基线保持映射及原有限制说明，未掩盖或重复运行；本轮没有执行全量测试，也未修改产品、冻结对象或用户数据库。


## A-R1/A-R2、B-R1/R2/R3 指定返修新 supervisor 复审 · 2026-09-26

复审者：本轮新建的独立 supervisor `/root/req010_ab_five_supervisor`。**A-R1、A-R2、B-R1、B-R2、B-R3 均通过并可关闭。** 结论仅覆盖 design.md §12/§13 指定的五项及 PlanningService 依赖核对，不代表 B 阶段、C/D 或 REQ-010 整体验收。

冻结对象：`/tmp/taskweave-req010-ab-five-review-final-ii3vSl/source`；manifest 共 650 个文件，摘要 SHA-256 `a7a0af6bbe34b414d131a8f35323ad08c26828d9cf76c82d0b2cf748b571364a`。复审者逐项核对路径、大小与 SHA-256，全部一致；验证后快照没有新增 manifest 外文件。包资源 `control.sql`（3970 字节，SHA-256 `50c63ed303581b3bcc63342ad767c3779e79d3da47587f1c66aa7c3f8b0b7628`）和 `task-data.sql`（523 字节，SHA-256 `298f799b923af7195b6273eb05c9d921c974943f255358fb9f23afce88aef50f`）均存在且匹配记录。临时 home 的 Application 初始化成功并创建控制库。首次让 uv 在只读快照下建立虚拟环境因权限失败，改用原工程依赖环境并将 `PYTHONPATH` 指向快照源码后验证成功；该环境尝试未作为产品缺陷。

- **A-R1 通过**：Protocol 返回类型与真实仓储返回值相符；参数名、kind/default 和重复声明由契约测试检查；真实排序验证覆盖边界不动、实际交换、返回形状、顺序及 revision。
- **A-R2 通过**：协作 Protocol 仅位于 infrastructure，core 不导入 SQLite；仅暴露窄能力的替代对象实际完成上下文复制/回滚以及锁定结果删除保护和解锁后删除。
- **B-R1 通过**：`runs_for_task` 只按任务查询 `run_id/status`；真实 SQLite 覆盖空集、同任务多运行、跨任务隔离，且由 `Coordinator.clear_task_runs` 消费。
- **B-R2 通过**：同一具体 `StepRepository.save_step` bound method 被保存并 patch；第二次写入失败前确认目标任务已有一步；失败后断言目标任务/步骤清理，并比较源任务及步骤完整快照保持不变。本轮实施补强了源快照及目标步骤空集断言。
- **B-R3 通过**：Authoring/Planning 隐私用例通过真实 Application 装配和持久化组/采集项验证；显示与 AI 开关独立，库内原文保留。
- **§13 PlanningService 依赖核对通过**：直接注入步骤/上下文仓储与 `plan_files_root`，由 Application 提供 `home / "plans"`；未发现对任务用例内部仓储或 `plans.root` 的越界访问。

复审者在冻结快照 cwd 运行以下八个定向模块，退出码 0，共 26 项通过，4.149 秒：

```bash
PYTHONPATH="$PWD/src" uv run --project /Users/dasensen/PycharmProjects/taskweave python -m unittest \
  tests.repositories.test_repository_contracts \
  tests.repositories.test_context_return_contracts \
  tests.repositories.test_collaboration_ports \
  tests.repositories.test_plan_context_repository \
  tests.repositories.test_run_repository \
  tests.repositories.test_task_repository \
  tests.test_task_transfer \
  tests.test_privacy_settings -v
```

未运行全量测试。上述签署不改变其他阶段和整体验收状态。

## B-R3 隐私开关独立性补测与新 supervisor 增量复审 · 2026-09-26

在当前工作区重新委托一位新的独立 supervisor 审核上述五项后，A-R1、A-R2、B-R1、B-R2 均再次通过；B-R3 暂缓关闭。该审核指出原规划隐私测试在翻转 `redact_on_display` 与 `redact_for_ai` 时只断言 AI 消息，未验证规划预览的显示开关接线，因此不足以证明两开关独立。该发现仅针对测试证据，不是生产行为回归。

返修只修改 `tests/test_privacy_settings.py`：使用真实 `PlanningPage.show_context_preview`，将 NiceGUI UI 控件替换为捕获适配器；在固定 AI 设置时独立切换显示脱敏，再固定显示设置时独立切换 AI 脱敏；保留真实 Application 规划消息断言和按 capture ID 读回未脱敏持久化内容的断言。测试实测组合为 `display=True, AI=False`（预览脱敏、AI 原文）、`display=False, AI=False`（两者原文）及 `display=False, AI=True`（预览原文、AI 脱敏）。

新 supervisor `/root/fresh_b_r3_review` 对此增量复审通过，未发现问题，并独立运行 `tests.test_privacy_settings.PrivacySettingsTests.test_planning_ai_toggle_keeps_stored_context_raw`，1 项通过。返修后在原工作区运行以下定向模块，退出码 0，共 **28 项通过**；未运行全量测试：

```bash
PYTHONDONTWRITEBYTECODE=1 uv run python -m unittest \
  tests.repositories.test_repository_contracts \
  tests.repositories.test_context_return_contracts \
  tests.repositories.test_collaboration_ports \
  tests.repositories.test_plan_context_repository \
  tests.repositories.test_run_repository \
  tests.repositories.test_task_repository \
  tests.test_task_transfer \
  tests.test_privacy_settings \
  tests.ui.test_planning_page -v
```

因此 A-R1、A-R2、B-R1、B-R2、B-R3 指定返修均经新 supervisor 复核通过；此结论不代表 B 阶段、C/D 或 REQ-010 整体验收。

## A-R1/A-R2、B-R1/R2/R3 当前工作树独立复审 · 2026-09-26

新 supervisor `/root/fresh_req010_ab_review_20260926` 对当前工作树重新独立核验，没有引用此前 review 结论。**A-R1、A-R2、B-R1、B-R2、B-R3 及 PlanningService 依赖裁决全部通过，未发现实质阻断。** 结论范围只包括 design.md §§12–13 的五项及直接相关的规划装配和运行资源，不代表其他 A/B 项、C/D 或 REQ-010 整体验收。

复审开始时记录 HEAD `5f3a5c8098374944fef99039f792f22c18e31447` 与完整 Git 状态，并冻结相关文件副本及全源码副本。选定文件 manifest SHA-256 为 `d3bc6b689303f0393db357e105a48d73f5aef3c2fe548cd779aa1406d667c230`；全源码副本 630 文件 manifest SHA-256 为 `122a1700cc4435e337644cdc467ed2597d08624de7f53d71ae105a46197343f1`。资源 `control.sql` 与 `task-data.sql` 均存在，哈希分别为 `50c63ed303581b3bcc63342ad767c3779e79d3da47587f1c66aa7c3f8b0b7628`、`298f799b923af7195b6273eb05c9d921c974943f255358fb9f23afce88aef50f`；临时 home 的真实 Application 初始化成功。验证后 HEAD、Git 状态和冻结相关文件均未变化；审核者没有修改文件。

逐项核验确认：A-R1 的端口注解、参数契约、真实返回形状、边界排序、交换顺序及 revision 行为匹配；A-R2 的窄协作 Protocol 位于 infrastructure，复制失败事务回滚与结果删除锁定保护得到替代端口行为验证；B-R1 的 task-scoped SQL 由 `Coordinator.clear_task_runs` 实际消费并有 SQLite 隔离测试；B-R2 在同一具体 `save_step` bound method 上注入第二步失败，验证失败前已落一步、失败后目标清理且源快照不变；B-R3 使用真实 Application、规划预览与 AI 消息分别验证两个隐私开关，并读回未脱敏持久化内容。PlanningService 直接注入步骤/上下文仓储及显式 `plan_files_root`，仅使用任务用例公开操作，没有访问任务用例内部仓储或 `plans.root`。

审核者在冻结全源码副本运行定向测试：

```bash
PYTHONPATH="$PWD/src" uv run --project /Users/dasensen/PycharmProjects/taskweave python -m unittest \
  tests.repositories.test_repository_contracts \
  tests.repositories.test_context_return_contracts \
  tests.repositories.test_plan_context_repository \
  tests.repositories.test_collaboration_ports \
  tests.repositories.test_run_repository \
  tests.application.test_application_composition \
  tests.test_task_transfer \
  tests.test_privacy_settings \
  tests.test_planning -v
```

结果为 **42 项通过，退出码 0**；另在快照副本以临时 home 初始化并关闭 Application 成功。当前工作树的 `git diff --check` 通过。未运行全量测试。
