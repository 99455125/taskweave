# 条件多分支与并行执行设计（待审核）

> 2026-10-27 状态更新：用户已授权步骤与组合条件并行一并实施，当前权威方案为[修正设计](2026-10-27-sequence-control-flow-design.md)，实施与验证见[控制流计划](../plans/2026-10-27-control-flow.md)。下文保留原提案的调研依据，原待审核状态及串行范围由新方案覆盖。

## 状态与范围

2026-10-23，用户提出条件节点应有多个出口，并可选择“按顺序只执行首个匹配”或“所有匹配分支同时执行”；随后确认先完成当前 UI 重构，单独设计并行能力。本文记录现状与建议，尚未获得方案审核，不是实现计划，也不表示并行能力已经可用。

当前 UI 工作继续按[界面落地计划](../plans/2026-10-23-ui-ux-rollout.md)推进：条件节点支持多个出口、每个出口可配置复合条件、默认出口和对应步骤。首个匹配模式可以用现有 `if → else 中的 if` 表达；界面显示为多条路径，保存及运行仍遵守现行流程契约。并行设计单列不会把当前 UI 需求退回两个出口。本轮 UI 不实现并行调度，不写入后端不认识的执行方式，也不把串行执行标成并行成功。

本设计面向一个任务、一次 Run 内的步骤分支。任务组合继续保留既有串行任务调用边界；组合的条件、循环和并行仍需另行设计。固定执行继续不调用模型，沿用单一 Python/uv 工程与现有分层约束。

## 目标

- 同一条件组拥有多个有稳定身份的分支，每个分支可包含多个条件，支持全部满足、任一满足与取反。
- 提供两种执行方式，默认“首个匹配”：按配置顺序只执行第一个满足条件的分支；“所有匹配并行”执行本次判定中所有满足条件的分支。
- 运行详情能说明哪些分支命中、未命中、等待资源、执行中、失败或需核对；后续步骤在明确的汇合条件满足后开始。
- 保留已有步骤、AI 编写与修复、单步和流程调试、插件、补参、暂停恢复、结果及人工核对能力。

执行顺序、匹配方式与运行事实应分别表达。选择多个条件组中的条件并不自动建立多个出口；多个出口也不自动代表同时执行。

## 当前实现事实

以下事实以 2026-10-23 工作区源码为依据。历史[控制流设计](2026-10-21-task-step-control-flow-design.md)用于追溯需求，实际可用能力以源码为准。

| 边界 | 当前行为 | 权威实现 |
| --- | --- | --- |
| 定义与校验 | 流程 version 2 允许 sequence/action/if/foreach/loop；if 只有 then/else；每个动作步骤在树中出现一次；控制嵌套最多 8 层 | [task_flow.py](../../../src/taskweave/core/task_flow.py) |
| 条件 | 支持 all/any/not 及受限值比较；每个 if 选择一个出口 | [task_flow.py](../../../src/taskweave/core/task_flow.py)、[flow_machine.py](../../../src/taskweave/core/flow_machine.py) |
| 核心推进 | 一个 frames 栈、一个 pending 动作；next_action 一次返回一个动作，完成后推进 | [flow_machine.py](../../../src/taskweave/core/flow_machine.py) |
| 实际执行 | FlowRunner 等待一个动作尝试完成后才推进下一动作；单个 Coordinator 持有一个 worker 通道 | [flow_runner.py](../../../src/taskweave/infrastructure/flow_runner.py)、[run_coordinator.py](../../../src/taskweave/infrastructure/run_coordinator.py) |
| 既有并发 | CoordinatorPool 按正式 run_id 隔离 Coordinator，现有上限为 1–8 个活跃执行；这是独立 Run 的并发 | [coordinator_pool.py](../../../src/taskweave/infrastructure/coordinator_pool.py) |
| worker | 收到一条命令后等待 execute 完成，再读取下一条；取消事件与保留资源属于该 worker | [worker.py](../../../src/taskweave/infrastructure/worker.py)、[worker_transport.py](../../../src/taskweave/infrastructure/worker_transport.py) |
| 持久化 | 每个 Run 保存一份游标；比较旧游标后，将实例访问与新游标在控制库事务内提交；重试定位一个 execution_path | [flow_runs.py](../../../src/taskweave/infrastructure/repositories/flow_runs.py) |
| 资源 | 按 provider_id 与 role 复用；同一 Playwright role 取得保留的 browser context/page，未建立分支级隔离与占用规则 | [resource_sessions.py](../../../src/taskweave/infrastructure/resource_sessions.py)、[session.py](../../../plugins/playwright/src/taskweave_playwright/session.py) |
| 输出 | 分支公共输出读取选中出口的映射；分支外引用需满足当前作用域规则 | [flow_values.py](../../../src/taskweave/core/flow_values.py)、[flow_runner.py](../../../src/taskweave/infrastructure/flow_runner.py) |
| 异常与恢复 | 失败停止当前流程推进；UNKNOWN 阻塞继续并要求核对；补参、暂停、取消及核对主要按 Run 管理 | [run_coordinator.py](../../../src/taskweave/infrastructure/run_coordinator.py)、[runs.py](../../../src/taskweave/infrastructure/repositories/runs.py) |

因此当前代码不支持同一 Run 内多个分支并行。嵌套 if 能表达首个匹配；并列多个 if 只能依次判定与执行，先执行的分支还可能影响后续条件读取的值。两者都没有并行分叉、等待全部完成的汇合、分支资源隔离及部分完成恢复语义。

现有 if 链每增加一个条件会占用一层控制深度，外层循环和路径内部控制也占额度。当前 UI 必须沿用这一校验；未来显式多分支组如何计算深度属于新契约，不能仅改界面就放宽限制。

## 方案比较

| 方案 | 能覆盖什么 | 代价与判断 |
| --- | --- | --- |
| 继续组合现有 if | 满足当前 UI 的多出口、首个匹配 | 无法提供所有匹配并行，适合作为本轮 UI 的实现边界 |
| 在一个 Run 内增加显式条件组与分支执行实例 | 统一任务身份、输入、分支结果、调试和恢复 | 需要核心调度、持久化与资源协议扩展；推荐作为后续能力方向，待审核 |
| 将每个命中分支拆成独立任务 Run | 可以复用现有独立 Run 并发池 | 需要重新建立子 Run 所有权、上下文继承、引用和汇合，改变当前步骤分支边界；当前不推荐 |

推荐方向保留既有 Run/Attempt 与结果回执，不要求通用任意图执行器。具体 schema 版本、字段和存储布局须在语义审核后设计并接受运行时校验；本文不提前指定可直接写入的 JSON 结构。

## 建议执行语义（待确认）

### 判定与分叉

首个匹配模式继续按配置顺序短路判定；后续条件不因未被访问而报错，保留原有行为。所有匹配并行模式建议在分叉前，基于同一组已完成上游结果、任务输入与可读取环境值评估全部条件，冻结本次命中的分支 ID 集合，然后才启动分支动作。任一条件计算错误时，记录条件诊断并阻止本次分叉，避免只启动一部分后才发现其余条件无效。

冻结判定保证重试或恢复不会因某个分支已经修改外部状态而重新选择出口。分支动作本身继续按插件规则读取现场；冻结判定不表示冻结浏览器、数据库或其他外部系统。

默认分支只在没有任何条件匹配时执行，不与命中分支同时执行。建议保留唯一、不可参与排序的默认出口；它可以为空，表示本次无动作后汇合。

### 并行与汇合

建议将一个命中分支作为一条独立执行路径，路径内部仍遵守现有顺序、条件和循环语义。受容量与资源占用约束时，部分分支可以等待资源；界面应显示等待，不承诺所有分支在同一时刻开始。并发上限需要同时覆盖同一 Run 和多个 Run，不能让分支绕过现有执行容量控制。

建议汇合等待所有命中分支成功，或经有效人工核对确认完成；其余错误、未补参数和 UNKNOWN 均阻止后续公共步骤。未命中的分支明确记为跳过，不占汇合等待。零命中时执行默认路径后汇合。分支完成顺序不改变配置顺序与结果索引。

### 输出与引用

建议按稳定 branch_id 汇合分支输出，同时保留分支名称、命中事实、状态和对应结果引用。输出按配置顺序展示，不按完成时间排列；同名输出属于各自分支命名空间。未命中、已完成但值为 null、执行失败以及结果缺失分别表达。

分支内可读分叉前已完成的上游数据、当前分支内前序结果及所属循环变量。兄弟分支在汇合前不能直接互读；跨分支依赖应移到汇合后，避免隐含等待和循环依赖。下游可选择某分支输出，或显式定义聚合映射；缺失与类型不符继续报错，不自动取最快完成者或覆盖同名值。

既有首个匹配公共输出需要保持兼容。当前 if 链的各层输出和节点身份不得因界面展开而丢失；迁移到显式条件组时要保留可追溯映射及旧运行的读取规则。

### 插件资源与副作用

建议默认对并行分支隔离有状态资源，资源归属需包含分支执行身份。Playwright 分支应有独立 browser context/page；同一分支内后续步骤仍可复用自己的 role。已有 role 名称不能被直接理解为可并发共享同一个页面。

从分叉前保留浏览器进入多个分支时，不能自动假设登录态、当前页面或 target_id 能跨隔离会话复制。建议首版要求每条并行路径显式建立可用会话；需要继承的资源由插件声明支持的快照/重建方式，并单独验证。若允许显式共享资源，应按资源键串行占用，展示等待；共享不安全的资源拒绝并行使用。

隔离进程或浏览器上下文不保证外部业务隔离。两个分支可能写同一数据库记录或文件，作者仍需声明业务依赖；运行器不得将本地隔离标为外部写入无冲突。取消、超时或进程丢失后，插件副作用未知状态继续传播，不能因另一分支成功而覆盖。

### 失败、补参与控制

失败策略存在以下可选方向，尚未获用户确认：

| 策略 | 行为 | 取舍 |
| --- | --- | --- |
| 完成独立分支后阻塞汇合 | 失败分支停止；其他命中分支继续；全部稳定后统一呈现成功、失败、UNKNOWN 等结果，后续公共步骤不开始 | 建议默认。保留独立成果，减少取消已发出外部动作带来的额外不确定性 |
| 首次失败即停止整组 | 不再启动等待中的分支；向运行中的分支请求取消，收集它们的最终状态后阻塞汇合 | 更快停止后续动作；已发出的动作不能保证撤销，可能增加 UNKNOWN |

两种策略均不能自动重试副作用不明的动作。重试针对明确失败分支内的执行实例，保留其他成功分支；人工核对绑定准确 attempt_id 与分支路径，继续时读取已保存匹配集合与结果。核对“已完成”不补造缺失输出；下游需要该输出时仍需明确处理。

补参建议只阻塞对应分支，其他独立分支继续；每条请求有独立身份，列表可同时呈现多个待补参数。用户暂停建议作用于整个 Run：停止调度新动作，已运行动作按既有可协作边界收束；取消则请求终止全部活跃分支，并保留每条路径的实际结果与未知副作用。具体控制策略待与失败策略一并确认。

## 后端与界面影响

| 层/契约 | 需要设计的边界 | 现有入口 |
| --- | --- | --- |
| core | 带执行方式的条件组定义、分支身份、作用域、分叉与汇合状态机、多个待执行动作、输出聚合 | [task_flow.py](../../../src/taskweave/core/task_flow.py)、[flow_machine.py](../../../src/taskweave/core/flow_machine.py)、[flow_values.py](../../../src/taskweave/core/flow_values.py)、[run_ports.py](../../../src/taskweave/core/run_ports.py) |
| application | 创建/启动、分支重试与补参、核对、运行范围、能力发现和错误语义；原调用者的兼容入口 | [runs.py](../../../src/taskweave/application/runs.py)、[steps.py](../../../src/taskweave/application/steps.py)、[operations.py](../../../src/taskweave/application/operations.py)、[agent](../../../src/taskweave/application/agent) |
| infrastructure | 分支调度与容量、worker 通道及事件关联、资源所有权、分支与汇合原子提交、恢复及清理 | [flow_runner.py](../../../src/taskweave/infrastructure/flow_runner.py)、[run_coordinator.py](../../../src/taskweave/infrastructure/run_coordinator.py)、[coordinator_pool.py](../../../src/taskweave/infrastructure/coordinator_pool.py)、[flow_runs.py](../../../src/taskweave/infrastructure/repositories/flow_runs.py)、[resource_sessions.py](../../../src/taskweave/infrastructure/resource_sessions.py) |
| presentation/desktop | 模式、优先级与默认出口编辑；分支运行状态；多补参、重试/核对选择；调试范围与汇合结果；迟到响应和草稿保护 | [flow_editor.py](../../../src/taskweave/presentation/flow_editor.py)、[execution.py](../../../src/taskweave/presentation/execution.py)、[debug.py](../../../src/taskweave/presentation/debug.py)、[step_editor.py](../../../src/taskweave/desktop/components/step_editor.py)、[execution_details.py](../../../src/taskweave/desktop/components/execution_details.py) |
| 包、持久化及插件契约 | 流程/包版本与旧定义映射、旧运行游标读取、运行时校验、插件资源并发声明、结果与视图引用 | [task_package.py](../../../src/taskweave/core/task_package.py)、[task_transfer.py](../../../src/taskweave/application/task_transfer.py)、[sqlite_storage.py](../../../src/taskweave/infrastructure/sqlite_storage.py)、[契约索引](../../contracts/README.md) |

不得将现有活跃 Run 的游标直接替换成并行游标，也不得仅据当前任务定义解释旧历史。升级方案应明确旧定义、旧包、旧运行与新运行的版本边界；需要迁移时使用增量迁移并保留回执和结果关联。精确 schema、SQL 和协议在审核后的设计细化中以源码和契约维护，不在本文另建一份字段清单。

## 建议验收场景

以下是后续能力的验收目标，不是本次 UI 已通过的测试记录。测试入口继续统一维护在 [module-map.json](../../../tests/module-map.json)，按[测试指南](../../testing.md)选择受影响验证，全量测试另行授权。

- 匹配：首个匹配保持短路与顺序；多个条件同时命中时并行模式全部选择；零命中只走默认；复合条件、缺失值和条件错误有明确结果；恢复不重新判定已冻结集合。
- 真并行与汇合：两个独立本地动作的活跃时间确有重叠；容量受限时明确排队；全部完成前不启动汇合后步骤；不能只靠画布或总耗时推断并行。
- 身份与输出：重复名称、不同完成顺序、null、跳过和失败保持 branch_id 区分；同名输出不覆盖；非法兄弟引用被拒绝；循环内多分支按所属轮次聚合。
- 资源：同 role 的隔离会话互不导航/输入；显式共享资源按约定排队；分支关闭与重试不关闭其他分支资源；原先采集的 target_id 不被错误复用。
- 失败与控制：一支失败、其他支成功/运行中/待资源；多支同时补参；暂停、继续、取消；UNKNOWN 和缺失输出分别阻塞正确位置；重试不重做成功分支。
- 恢复：在匹配集合提交、分支启动、结果回执、分支完成和 join 提交边界中断并真正重启。已确认完成的实例不重做，未启动实例继续调度；动作已发出而结果不明的实例进入 UNKNOWN 并阻塞汇合，经核对后恢复，不自动重试。验证游标与回执一致且不会提前汇合，不承诺外部效果恰好一次。
- 兼容与编辑：旧线性、if 链、循环、任务包往返、单步/流程调试和组合子任务仍可用；流程编辑、版本冲突与 AI 候选采纳不丢失分支身份或错误切换执行方式。

本地 worker/浏览器 fixture 只能证明相应本地生命周期与隔离，不能代替真实外部业务系统的并发写入、事务或会话继承验收。

## 待用户确认

1. 是否采纳并行模式的“分叉前统一判定并冻结命中集合、零命中执行唯一默认出口、全部命中分支完成后汇合”语义。
2. 失败时采用“其他独立分支继续后阻塞汇合”（推荐）还是“首次失败即请求停止整组”；补参只阻塞本分支、暂停作用于全 Run 的建议是否适用。
3. 是否接受默认资源隔离及首版每条并行路径显式建立会话；有必须共用登录页面或其他有状态资源的场景时，需明确共享边界。
4. 下游是否按分支 ID 选择结果并显式聚合；同一 Run 并发上限与全局容量的期望范围，以及并行流程调试的“下一步/运行到”应如何选择分支。

上述事项确认前，本文保持待审核。当前 UI 的多出口编排继续使用可执行的首个匹配语义完成验收；后续并行实现需有独立授权和实施计划。
