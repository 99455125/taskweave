# DDD 模块化设计 v1

设计责任人：taskweave-navigator-astra。日期：2026-09-24。用户已授权由本任务设计并协调 Luna 实施、Sol 审核、本人终验。本文是目标与约束，不代表已实现。

## 1. 意图、现状与方案

用户要求原功能不变，业务实体有清楚的 repository 边界，UI 对应独立组件，修改某组件能够准确选择回归测试。Repository 在本文指 Python 持久化组件，项目仍是一个 Git 仓库、一个 Python 工程。

现场：Repository(Store) 956 行包含任务、步骤、环境、运行、上下文、结果；Store 同时包含连接、迁移、任务读取、运行恢复及结果存储；PlanRepository 298 行混有计划、上下文、生成记录；Workbench 3031 行混有全部页面及编辑/调试状态。application 存在直接 SQL；部分 UI 测试检查源码字符串。已有按功能命名测试必须保留有效断言，不得重新按 REQ 聚合。

采用渐进式模块化单体：核心保留 core 名称，在其下定义业务端口与纯规则；SQLite 适配按业务拆分，公共 Application/dispatch 和旧导入保留兼容薄层；UI 使用对象组合。每阶段都应可运行。仅移动文件/多继承拼成原巨类不能满足职责隔离；一次重写所有模型与执行器会扩大保真风险，故不采用。无需新增 ORM、依赖注入框架、事件总线或服务进程。

DDD 的实体边界不等于一表一个独立事务。步骤拥有独立仓储，但步骤顺序、依赖及任务图受同一任务定义一致性约束；上下文采集项由组拥有，不为每项另起一个可绕过组修订的公共 CRUD 仓储。

## 2. 行为不变量

1. 保留所有 dispatch 操作名称、参数默认值、返回 JSON 形状、错误码、顺序和公开 CLI/HTTP 行为；旧 Repository/Store/PlanRepository 导入在兼容期可用。插件 API v1、step python-async-v1、taskweave-task-2、控制库 v14 不变。不改依赖、用户数据库和工作空间配置；不新增 schema 迁移。
2. 任务输入、步骤绑定、环境默认值及本次输入的现行优先级不变。步骤编辑和上下文改变后确认失效，内容 hash、expected_hash、规划 revision、上下文 revision 的检查保留。任务执行快照与当前定义分离。
3. 固定执行不调用模型；AI API/网页生成、解析、差异预览、采纳、修复会话和请求上限保持行为。规划冻结原始上下文、按引用导入草稿；重复导入返回既有任务。复制不复制活跃资源/运行记录。
4. 上下文采集仅暂存，取消不写库，组确认一次提交、一次修订及一次失效；冲突/采集失败保持弹窗草稿。组/项排序、撤销删除、原文存储与展示/AI 独立脱敏、图片完整性保持。
5. 调试按任务复用、正式运行按 run 隔离、并发上限、锁与幂等命令、暂停补录、间隔、失败停止、UNKNOWN 核对及崩溃恢复保持。不能为简化仓储删除协调器锁，不能自动重做未知副作用。
6. 结果属于 task/run/step/attempt 作用域。保留任务库按需创建、结果提交回执、跨库恢复、下游失效、文件清理和环境删除的历史名称。不能把跨文件/跨库操作伪装成 SQLite 单事务。
7. UI 标签、布局、操作入口、自动保存时机、按钮 busy 恢复、调试分栏、当前输入/选中项保留不变。页面卸载需停止仅属于该页面的定时器，避免旧回调改写新页面；应用级实例保持原有生命周期。

## 3. 业务边界与仓储

端口放 core/repositories.py（必要时按领域分文件），使用 Protocol 和现有 DTO 字典，不强制重写成 ORM entity。实现放 infrastructure/repositories/。构造函数显式接收共享 storage/session 及所需端口，禁止每个领域仓储各自初始化数据库。

| 领域仓储 | 负责 | 不负责 |
|---|---|---|
| TaskRepository | 任务元数据、定义图、定义快照/hash、生命周期 | UI、步骤代码编辑细节、结果解析 |
| StepRepository | 步骤读取/保存/顺序/删除/确认、绑定与归属检查 | AI 请求、规划生成 |
| EnvironmentRepository | 环境配置/说明/凭据引用、删除和历史脱钩 | 模型设置、窗口设置 |
| RunRepository | run、attempt、事件、命令回执、租约及运行查询 | worker 进程和插件资源对象 |
| ResultRepository | 结果引用、读取、失效/清理及恢复所需持久化操作 | 插件自定义解析算法、UI 渲染 |
| StepContextRepository | 步骤上下文组/项、组 revision、步骤确认失效 | 规划 revision、真实插件采集 |
| PlanRepository | 规划元数据、revision、复制/删除协调 | 模型调用、步骤执行 |
| PlanContextRepository | 规划组/项、规划 revision 检查/递增 | 步骤确认 |
| PlanGenerationRepository | 生成状态、候选/诊断、冻结快照索引、导入关联 | 实际模型调用、UI |

PlanRepository 的复制及 TaskRepository 对外复制行为可以委托应用用例；表间关系必须仍经显式端口与同一工作单元。跨仓储读模型可以联表，不能借查询通道新增跨领域随意写入。插件注册/配置、工作空间/model/privacy 设置已有专职组件，保留这些边界，不为 JSON 设置强造数据库实体。

旧 infrastructure/repository.py 中 Repository 改成兼容门面：显式方法委托、保留旧签名与必要的 query/execute/transaction 供低层及测试过渡；不得保留 SQL 业务主体，不得 __getattr__ 任意转发、动态复制函数或从原巨仓储继承。新应用代码使用具体仓储。旧 infrastructure/plan_repository.py 为兼容导出或显式委托。Store 只保留基础存储/兼容桥；业务读取与恢复归新仓储。Results 仍为 worker 侧结果写入适配，可独立文件并原路径重导出。

## 4. 事务及应用用例

提供 SQLiteUnitOfWork（infrastructure/unit_of_work.py），一个工作单元使用一个连接，业务仓储共享它。BEGIN IMMEDIATE、外键、busy timeout 与现有配置一致；成功提交、异常回滚；线程/异步上下文之间不能共享正在使用的连接。嵌套调用复用已绑定连接或使用 savepoint，禁止内层连接独立提交导致外层回滚无效。保持普通单操作自动事务兼容；显式跨仓储事务使用 `with uow.transaction():`。仓储 query/execute 必须路由到当前绑定连接。

需要真实测试的事务：step 保存/排序与 task graph 同步；任务 schema 更新与步骤确认失效；context 批量项/组 revision/步骤失效；plan 元数据与上下文 revision；环境删除与运行历史/步骤引用脱钩。任务导入、规划导入、复制保留既有失败清理语义，能使用单控制库事务时使用它，但不得把模型、插件采集或文件操作放进长事务。跨任务库/文件删除保留 DELETING/receipt 的恢复路径。

嵌套事务明确采用 savepoint：每个显式内层 transaction 建立 savepoint；内层异常回滚该 savepoint 并原样抛出。若外层捕获异常，可继续提交不属于失败内层的写入；若异常传播至最外层，整个事务回滚。内层成功只是释放 savepoint，不提前提交。事务内所有仓储及旧 Store/facade 的 query 都须读到当前连接未提交写入，另一个线程/连接不得读到它。以上三种嵌套路径均需单独测试。工作单元不得跨 worker 进程传递活动连接。

Application 是兼容 facade/composition root；拆出 application/tasks.py、steps.py、environments.py、runs.py、contexts.py 等用例服务。复杂跨领域规则在用例协调，纯校验仍在 core，SQL 在 infrastructure。每个服务按需注入端口，而不是接收全功能 Application/Repository 再任意访问。PlanningService/Authoring 继续负责其现有流程，改用细分依赖。Application.dispatch 路由分组放 application/operations.py，保留同步/异步分派和原锁豁免集，不能重写并发语义。

Coordinator/worker 是现有进程基础设施。本轮不重写调度算法，协调器中持久化 SQL移到 RunRepository 的语义方法，命令事务回调可在基础设施层受控保留；运行定义读取用 tasks/steps，输出用 results。不得创建只包装 execute(sql) 的“领域方法”伪装边界。DesktopController 使用用例/查询接口，不直接访问 application.repo 或数据库。

## 5. UI 组件与状态

Workbench 保留应用外壳、导航、公共按钮错误处理、页面容器与生命周期。desktop/pages/ 下 TasksPage、ExecutionsPage、HistoryPage、EnvironmentPage、PluginsPage、SettingsPage、MarketplacePage；已有 PlanningPage 纳入相同页面生命周期。每页 `render()` 与 `dispose()`，通过显式 controller、导航回调、公共 UI helpers 构造。

desktop/components/ 下 StepEditor、StepList、StepDebugPanel、StepAIEditor、StepContextPanel、ExecutionDetails、RunInputDialog、ResultViewer。现有 contexts/forms/dependencies/display 的通用代码保留或重导出。编辑器持有 StepEditorState（任务/步骤 ID、old_step、输入控件/草稿、save_lock），调试持有 DebugState（run、环境、本次输入、补充说明）；共享状态显式传入，不能把 Workbench 的全部属性通过代理重新暴露。

对应迁移：workbench.py task_list/task_dialog/import/export -> TasksPage；editor/document/save_editor/mark_step_pending -> StepEditor；start_trial/start_flow_trial/refresh_trial/end_trial -> StepDebugPanel；generate/web_chat/goal/confirm -> StepAIEditor 与编辑器用例；上下文方法 -> StepContextPanel；run/execution_hub/refresh_execution_rows/refresh_run -> ExecutionsPage + ExecutionDetails；pending_inputs/trial_variables -> RunInputDialog 与共享输入组件；结果/历史/环境/插件/设置各归组件。

页面只能调用 controller/注入回调，不相互读取 UI 控件。导航先完成现有的上下文/规划保存及步骤 dirty 检查；现有“继续编辑 / 舍弃修改并离开”确认仍须保留，不能把有确认的路径改成无条件自动保存。用户取消或保存失败时禁止跳走且保留草稿；允许离开后才释放页面绑定并渲染。保持已存在的串行保存锁；事件绑定在组件内部；异步完成必须核对当前 task/step/run，避免迟到响应更新另一步骤。测试可直接实例化组件状态和假 controller，无需启动整个工作台。兼容 Workbench 方法仅可显式委托，不能把多个 mixin 拼回全局 self。

## 6. 模块化测试

新增 tests/domain/、tests/repositories/、tests/application/、tests/ui/（都可由 unittest 发现），按业务文件命名。已有 test_*.py 继续运行；混合的 test_workbench_changes/test_planning 中 UI 用例可迁入对应组件模块，用迁移清单记录旧 TestCase.method -> 新入口，确保断言不丢失、不重复收集。

提供 scripts/test_modules.py 与 tests/module-map.json：每条记录包含 source globs、明确 unittest targets、depends_on、browser targets。`--list` 列模块；`--module ui.tasks` 运行本模块快速测试；`--changed PATH... --dry-run` 输出精确集合；真实执行输出选择理由。共享依赖变化走反向依赖闭包；ui.tasks 变化不得选 ui.settings；step 端口变化应选其 application/UI consumer；未知 src/plugins 路径失败并提示补映射，不能静默零测试。`--include-browser` 显式加入选中模块对应浏览器流程。不得暗中执行全量 discover。

快速组件测试断言渲染结果/状态/控制器调用顺序、保存失败不跳转、重复操作抑制与卸载行为；新测试不检查源码字符串。原源码测试改成行为等价断言或保留为明确结构检查，不能删断言以让重构变绿。SQLite 集成使用临时 home 和真实新仓储/UoW；mock 只能用于外部能力或纯 UI controller，不得 mock 掉事务本身。

| 变更模块 | 必须覆盖 |
|---|---|
| tasks/steps | CRUD、绑定顺序、hash 冲突、确认失效、复制与任务包导入 |
| planning/contexts | revision 冲突、批量回滚、顺序/删除撤销、冻结导入幂等与失败清理 |
| environments | 引用解除、历史名称、默认值与锁 |
| execution/results | 命令去重、暂停补录、重试/UNKNOWN、进程恢复、租约隔离、输出/文件作用域 |
| ui.tasks/editor/debug/executions | 当前交互不变、自动保存顺序、调试状态/输入保留、页面独立渲染 |
| ui.contexts/planning | 暂存取消/失败保留、确认一次提交、已存/新项预览 |
| shared/architecture | core 不依赖具体基础设施/UI；新 application 无 SQL；UI 无仓储访问；端口有真实调用方 |

## 7. 交付与评审门禁

基线包含当前未提交工作；先保存独立源码快照与 hash，再运行受影响测试记录基线。不得 reset/stash/clean 或以 HEAD 覆盖工作区。单写者 Luna 实施；Sol 只读审核及写 review.md，发现问题发回同一 Luna；设计偏差必须回到本任务裁决，不能由其它 agent 改设计。

阶段 A 仓储/UoW，阶段 B 应用路由，阶段 C UI 组合，阶段 D 测试映射与文档。每阶段报告实际命令/结果与相对基线差异，Sol 审查后返修。最后本人核对所有不变量、重点代码和实际定向验证；已知基线缺陷单列，不能声称其已修复。任何未完成阶段不能称整个 DDD 改造完成。

每阶段运行 `uv run python scripts/check_project.py` 与受影响功能测试。全量测试须另获用户明确同意，本轮不以架构变更名义偷偷运行全量；真实模型账号/Windows 便携包不具备本机验收条件，须标明未验证。源码浏览器关键流程使用临时 home 和本地 fixture，不操作用户业务。

## 8. 基线缺陷裁决

架构师在冻结源码独立复现 `Workbench.save_context_edits -> ContextCards.save_all` 的 AttributeError：当前 ContextCards 已改为弹窗批量提交并删除 save_all，旧导航/编辑器保存仍调用它。C 阶段清除过时调用和规划页相应死回调，保留当前弹窗一次提交语义；必须以步骤切换和保存的行为测试复验。不得增加空 save_all 来伪装已保存。该修复恢复既定功能，单列为改造前集成缺陷，不混记为本轮新回归。详见 [验证记录](validation.md)。

## 9. A 首轮审核后的依赖裁决 · 2026-09-25

Sol 提出的三项边界问题全部纳入 A 返修，不推迟至 B。具体实施约束如下：

- 新仓储持有的 storage 只可调用 query/execute/transaction、home/path/task_path/unit_of_work 等低层能力，禁止通过 Store.task/step/steps/environment/run/definition_hash/receipt 等业务兼容桥回到其它仓储；同领域读写调用 self 对应方法，跨仓储业务调用使用必需的显式依赖。
- 依赖组装必须无半初始化对象。环境仓储先构造；步骤仓储显式依赖环境读取端口；步骤上下文依赖步骤读取端口；任务仓储依赖步骤与上下文端口处理复制；运行仓储依赖任务、步骤、环境、结果端口。必需依赖不得以 None 默认值或构造后补写字段解决。兼容 Store 仍可延迟构造完整集合，但只能由兼容入口使用。
- 打破循环不需要新增服务定位器：ResultRepository 自己负责结果 receipt 读取，作用域需要的 run 元数据可由其明确的 SQLite 只读查询获得；RunRepository 恢复时通过注入的 ResultRepository 读取 receipt，不能 results.runs = runs 回填。步骤保存的父任务存在性、task graph 同步与任务锁属于任务定义聚合的持久化一致性，可用受控 SQL/共享纯查询 helper；不得借此复制跨领域业务用例。
- PlanContextRepository 与 PlanMetadataRepository 的循环通过共享、无状态的计划行解码和 revision 校验 helper 解除：上下文仓储无需持有能复制/删除计划的整个元数据仓储，元数据仓储显式依赖上下文复制端口。计划元数据、上下文、生成记录分别位于 plans.py、plan_contexts.py、plan_generations.py，共享 helper 只放纯查询/解码规则，不成为新的完整业务门面。
- A 保持已有复制/导入协调的成功和失败语义；B 再完成应用用例消费迁移。此处不得以“属于 B”保留隐式 Store 业务路由。
- core Protocol 必须按实际方法写明参数/默认值和返回结构，允许 JSON 值使用 Any，但不得用 *args/**kwargs 代替已知签名。补全调用方需要的确认/复制/读取等方法。返回删除结果字典的接口不能声明 None。轻量结构检查与可替换依赖测试验证端口和实现一致。

## 10. 审核任务交接异常时的推进决定 · 2026-09-25

原 Sol 任务首轮已完成有效审核，但后续多次被唤醒时只回复旧话题，未形成复审结论。架构师已向用户询问沿用原任务或改用 Sol 子代理。此问题不能被记录为审核通过。

为继续用户已授权的全项目实施，先冻结 A 当前代码为独立 stage-a-ready 快照，保留 hash、验证与未完成审核状态。架构师已核对修复路由、全部 74 个端口方法参数种类/默认值一致，并独立复验全部原失败运行场景；允许 Luna 继续 B。此为实施推进决定，取代“必须等 A 的 Sol 复审才可开始 B”的调度条件，不降低最终验收条件：A 的全部整改仍须由有效独立审核确认，B/C/D 也不能在未经审核时标记审核通过。最终交付前必须完成用户指定的审核职责与架构师终验。

## 11. C 的组件依赖与状态归属细化

本节由架构师在 UI 迁移前补充，细化第5节，不改变既有布局及交互。各组件构造参数可按现有代码命名，但以下依赖方向与所有权必须成立。

| 组件 | 持有状态 | 允许的协作入口 |
|---|---|---|
| Workbench | 当前路由、页面实例、页面容器、全局按钮 busy 调度 | controller、当前页面的 render/dispose/离页检查，明确的导航回调 |
| TasksPage / StepList | 自己的搜索/列表控件与选中显示 | controller、open_task/select_step、任务配置完成回调；不能读取 StepEditor 控件 |
| StepEditor | 当前 task/step、old_step、编辑控件、save_lock、保存状态、当前渲染代次 | controller、document/save、选择步骤回调；组合 Debug/AI/Contexts 子组件 |
| StepDebugPanel | 调试表单、反馈、运行显示、轮询 timer | 明确的 editor.save/document/当前身份查询、运行输入组件、controller |
| StepAIEditor | 请求期间的身份、生成候选与预览弹窗 | 保存当前草稿、对原目标采纳候选的回调、controller；不能借 Workbench 查任意页面 |
| StepContextPanel | 上下文组显示、采集弹窗草稿 | controller、当前步骤身份、确认成功后通知编辑器失效；取消不触发保存 |
| ExecutionsPage / ExecutionDetails | 各自筛选条件、选中 run、轮询 timer 与控件 | controller、打开步骤调试的回调、RunInputDialog/ResultViewer |
| PlanningPage | plan_id、搜索、规划表单、采集草稿、保存回调 | controller、按钮 helpers、导入后打开任务回调；移除 self.host |

允许为原先跨页面保留的 trials、debug_supplements、环境选择等定义专门的会话状态对象，由装配处提供；只能包含所需业务标识/数据，不能携带整个 Workbench 或其它页面控件。dispose 释放页面 timer/订阅/控件绑定，不删除仍需保留的调试会话或结束后台运行。不能借一个含所有 UI 字段的 state 对象重新制造巨型共享 self。

原 button() 同时管理全局 busy 与调试按钮状态：保留全局防重复点击及恢复行为，但调试失败样式/结束按钮可用性改由具体按钮注册的显式失败或收尾回调处理。通用 helper 不查 trial_actions/trials/step_id 等调试业务字段；旧 Workbench.button 签名可作为显式适配继续存在。

每次异步动作先捕获当前页面代次与 task/step/run 身份，await 返回后再决定是否更新该组件。保存请求使用启动时的目标与 expected_hash；排队保存进入锁后重新核对身份。旧请求可以完成原目标的持久化，但不得把返回值写进另一步骤的 old_step、预览或输入控件。页面离开许可获得后才 dispose，取消或保存失败保持原实例与草稿。用行为测试覆盖排队保存、迟到生成/刷新、取消离页与 timer 卸载，不能只测试存在一个 token 字段。

## 12. 接手复审 A-R1/A-R2 的架构裁决 · 2026-09-25

新审核会话对冻结 A 的两项 P2 成立，返修必须保留实际运行返回值与事务行为。

- A-R1：StepContextRepository.reorder_step_context_capture 的返回声明改为 Sequence[Mapping[str, Any]]；PlanContextRepository.reorder_context 与 update_capture_label 改为 Mapping[str, Any]。真实排序测试分别覆盖边界不移动与两个项的实际交换，并断言返回形状、顺序及既有 revision 行为。常驻契约测试核对参数 kind/default，而不只核对名称；当前工作区的重复 reorder_step_context 声明一并去重。
- A-R2：新增 infrastructure/repositories/collaboration.py，只定义 SQLite 适配器间的两个窄 Protocol：PlanContextCopier.copy_contexts(self, db: sqlite3.Connection, plan_id: str, target_id: str, stamp: str) -> None，以及 TaskLockGuard.assert_unlocked(self, db: sqlite3.Connection, task_id: str, allow_idle_trial: bool = False) -> None。这两项是参与既有事务的内部协作，不加入 core 的应用仓储端口，core 不导入 sqlite3。
- PlanMetadataRepository 的计划上下文依赖准确标注 PlanContextCopier；ResultRepository 的任务依赖准确标注 TaskLockGuard。现有完整适配器结构化实现这些窄协议，装配仍由 build_sqlite_repositories 完成，不引入服务定位器、None 默认依赖、事后回填或新事务。允许保留既有构造参数名称，避免无关兼容修改。
- 补仅暴露所声明窄协议、内部委托真实 SQLite 适配器的替代对象测试。计划复制应保留组/项并在注入中途异常时回滚新计划和上下文；结果删除必须保留事务内锁检查：被锁任务返回原 TASK_LOCKED，结果状态/文件不得先改；解锁后的原删除流程继续有效。不能仅用 hasattr 或任意 Mock 替代行为验证。
- 返修在原工作区完成并保留 B 中间改动。复审 A 使用新的独立快照，明确以 stage-a-ready 加本次 A 返修构造，不覆盖旧冻结快照；提供补丁文件清单、manifest/哈希和定向测试结果。若所改文件也含 B 改动，不能直接整文件覆盖旧 A，须分离 A 修复后独立验证。

## 13. B 中间审核整改与规划依赖裁决 · 2026-09-25

- B-R1：runs_for_task 保留为 Coordinator.clear_task_runs 的语义查询，返回该任务的 run_id/status，使用原调用点的 `SELECT run_id,status FROM task_runs WHERE task_id=?`，移除无效 created_at 排序；不修改 schema，不改变 list_runs 的既有显示排序。其清理调用方仅按集合和状态使用结果，接口不承诺额外顺序。真实 SQLite 测试验证空集、同任务多运行及跨任务隔离，B 收口时必须有对应实际 consumer。
- B-R2：导入失败测试保存具体 StepRepository.save_step 原 bound method，并 patch 同一对象。第二次调用抛错前明确观测新任务已持久化一步；失败后断言新任务/步骤均不存在、源任务和步骤未变。当前独立探针已证明产品回滚有效，但常驻测试未修复前不能关闭问题。
- B-R3：Authoring 隐私开关测试按新显式依赖构造，保留开关前后输出与输入原文不变的断言。规划隐私测试的旧构造及旧单 item 结构一并迁移至当前 context_records/组/有序 captures 结构，最好用临时真实仓储提供数据；保留存储原文、显示/AI 开关独立的断言。规划 fixture 过期在 A 已存在，单列基线缺陷，不算 B 新业务回归，不允许删测。
- PlanningService 按需直接注入 StepRepository 和 StepContextRepository 两个核心端口，完成导入后步骤查询与冻结上下文落库；TaskUseCases 依赖仅调用其公开的 validate_package/import_package/delete 等业务操作，禁止 self.tasks.steps 或 self.tasks.step_contexts。保持原冻结引用、重复导入、失败删除新任务与生成回执顺序，不重写为另一种导入流程。
- 生成文件的路径配置由 Application 装配处显式提供 `plan_files_root: pathlib.Path`，值保持 `home / 'plans'`。PlanningService 用该值组织原 generations 文件和相对路径，不再读取 plans.root 这个未声明实现属性；原计划仓储继续负责自己的计划目录复制/删除行为。此轮保留现有文件布局/恢复策略，不引入新依赖或存储框架。
- 后续冻结源码快照必须包括 src 的实际包资源（尤其两个 SQL 文件），并核对源码资源清单、manifest 与临时 Application 建库。禁止仅按 .py 等后缀白名单漏掉运行资源；旧有快照保持不变，补齐资源的版本使用新目录并记录来源及新增文件 hash。

## 14. B 完整交付中的 run.get 兼容裁决 · 2026-09-25

架构师在临时home独立对比冻结A与本轮AB快照：同一任务/运行操作，原run.get的request_json包含initial_inputs、initial_step_inputs、step_inputs、environment_hash、flow_trial，新RunUseCases._public_run删除initial_inputs和step_inputs，并另外删除waiting_input.values。该行为不属于DDD结构调整。

第4节及计划B的“不把内部完整输入泄露到现有公共run.get”是禁止为了替换Controller.repo读取而向原接口新增原本没有的完整inputs_json字段，并非授权删除基线已有的request_json字段。以第2节的公开JSON契约保真为准：恢复run.get原有返回形状与值，不新增该过滤函数。私有stored/request/input_values等查询继续供DesktopController使用，不通过扩展公开run.get代替。

调整本轮新增的隐私边界测试：检查run.get仍不包含基线原本排除的顶层inputs_json，同时对照原request_json字段及等待输入路径保持兼容，私有查询仍提供所需完整输入。不要保留本轮误增的“repr(public)中完全不存在输入值”断言来驱动未经授权的公开接口变更。既有隐私开关与脱敏规则不变，任何新的公开API隐私策略需另立需求，不混入本次行为保真的改造。


## 15. C 输入草稿与排队保存裁决 · 2026-09-25

架构师独立执行最小复现：trial_variables 的真实 change 回调在 org 必填留空时抛 FORM_INVALID，render 调用次数为 0；该回调 AST 与已验收 B 的 ab-r5-r6 冻结快照相同。属于继承缺陷，当前阻断原输入 UI 验收，不通过删除说明文字断言或预填必填项绕过。

环境切换读取的是未提交草稿，不执行提交校验。输入组件须保留空必填、未完成 JSON 和已编辑字段的原始控件值，同时刷新所选环境说明及未编辑字段的默认值；运行/调试提交继续执行原严格校验。原始草稿不得通过 JSON 解析失败后清空等方式丢失。增加环境切换行为回归，并继续原 test_input_ui 的完整交互路径。该测试中历史 taskweave-task-1 断言如与既定 taskweave-task-2 协议冲突，须核对原版本证据后修正测试并记录，不修改生产格式。

另独立复现 StepEditor 两个同目标排队保存传入的 expected_hash 为 h0、h0。细化第11节：触发时捕获文档快照与目标身份；进入串行锁并重新核对身份后，读取当前 state.old_step 作为版本基线。因此第一请求成功返回 h1 后，第二请求必须使用 h1；外部并发更改仍由持久层原乐观锁拒绝。不得重复使用锁外捕获的旧哈希，也不得取消 expected_hash 检查。测试覆盖同目标两次排队保存成功，以及跨目标、跨页面的迟到结果不污染新编辑器。


## 16. C 指定审核收口与 D 并行调度 · 2026-09-25

用户明确要求持续推进到完成。C 的局部增量审核关闭不替代指定审核任务 `01a0d501-6da3-77a2-98d4-484a9f1a7731` 对整体 C 的结论；最新 review.md 中 C-R3、R6、R7、R8、R9 仍开放。无组件所有权例外。原 Luna 继续单写者返修，指定审核者按实际装配、真实按钮回调及冻结源码复审，不能仅用组件 AsyncMock 测试或其他审核者的局部通过替代。

C-R9 的失效保护必须发生在持久化请求之前：采集弹窗建立时捕获原 task/step 与组件代次，任何后续确认或采集回调先确认该原身份仍有效；已离开的旧弹窗不得通过动态 step_id getter 写入新步骤。请求已合法发出后可以完成原目标持久化，但不能改写新页面状态。dispose 使旧回调失效并释放其界面资源，不终止后台运行。确认提交由组件自己的在途状态防重，失败允许重试且保留草稿，成功只提交一次；原取消/继续编辑交互保持。

环境控件的依赖从实际编辑器持有的位置显式传递，不恢复 Workbench 控件镜像；共享 trials 字典即使为空也保留同一对象引用。UI 容器与业务组件不得复用变量导致闭包错误。真实装配测试须覆盖第一次/再次/流程调试、已有运行恢复和 AI 确认读取最新运行。

允许 D 在 C 冻结复审期间实施其独立选择器、映射和文档；这只是调度并行，不代表 C 已通过。C 的阻断修复优先，旧冻结对象不覆盖，新增量重新生成 manifest。D 仍按第6节及 plan.md 实施，未经指定审核通过和 leader 最终验收，不得宣称整项完成。禁止借此运行未经用户确认的全量测试。


R3 剩余方法归属裁决：`mark_step_pending` 归 StepEditor，捕获身份后查询步骤，返回时重检再更新 old_step/控件；`refresh_trial_inputs` 归持有编辑器 view 的 StepEditor，通过显式 trial_variables 工厂创建表单，Workbench 不再拥有控件读写逻辑。`settle_trial_start` 与 `enter_debug` 归 StepDebugSession，使用 controller、identity、status、refresh 等窄依赖，保持原调试时序并逐 await 检查身份。`resume_inputs` 的校验、run.inputs、run.start 归 RunInputDialog 或其同文件输入协作方法；输入回填通过明确回调且检查捕获的 task/step/run/page 身份，外壳仅委托和协调刷新失效标志。保持原调用顺序、模式默认值及错误传播，不传入 Workbench/任意 host，不通过扩大共享 state 代替迁移。


补录迁移的时序约束：失效身份在 run.inputs 写入前拒绝；一旦合法请求已对捕获的 run_id 成功提交，仍须对同一运行完成原 run.start（保持 mode/target），离页只抑制旧 UI 回填/刷新。现有 provide_inputs 会清除 waiting_input 但保留 PAUSED，不能因 UI 身份变化中断两条已授权业务命令之间的继续步骤。以 Event 控制写入期间导航，验证原运行启动一次且新页面不被改动。输入身份包括当前 run 更替，不能仅比较同一 task/step。


## 17. D 实际映射收口裁决 · 2026-09-25

选择器算法通过示例测试，不等于业务映射正确。依赖方向为 consumer → prerequisite，须反映已实现装配。仓储边至少包括：steps → environments；contexts → steps（该模块包含 step_contexts）；tasks → steps、contexts；results → tasks（TaskLockGuard）；runs → tasks、steps、environments、results；planning → contexts。不得保留反向的 results → runs 伪依赖。已有 shared.storage/contracts 与领域规则边继续保留。以 step_contexts.py 变更选中任务复制回归、results.py 变更选中运行仓储回归作为实际闭包验收案例。

新增 `application.environments` 模块，映射 application/environments.py 与 Application 装配文件，依赖 repository.environments；ui.environments 依赖该用例模块。不能把环境用例变更仅映射成 application.tasks 而遗漏环境 UI。operations.py 为跨用例公开路由，应映射到全部受影响应用模块或公共契约模块，使路由变更能选择对应 HTTP/运行等回归。

已有测试必须有可追溯模块入口；不能只做到每个源码文件碰到一个 glob。以下首版遗漏须归入实际相关模块：

| 测试 | 模块归属与类型 |
|---|---|
| tests.ui.test_step_ai_editor | ui.editor 快速目标 |
| tests.ui.test_run_page | ui.executions 快速目标 |
| tests.test_input_ui | ui.editor/ui.debug 的 browser_targets |
| tests.test_playwright_choices、tests.test_image_locators | plugins.playwright 的 browser_targets（确实启动 Chromium） |
| tests.test_context_targets_playwright | plugins.playwright 快速目标（替代对象，不启动浏览器） |
| tests.test_context_targets_runtime | application.runs 或上下文协作模块的快速目标 |
| tests.test_http_task_api | application 路由/HTTP 相关模块的快速目标 |
| tests.test_variables | domain.steps 与相关输入模块的快速目标 |
| tests.test_export_io | 任务导出/导入相关快速目标 |
| tests.test_workbench_changes | 按实际方法映射任务/规划/上下文/执行等快速目标；其中 Playwright 配置测试使用替代对象，不能仅凭名称误归浏览器 |
| tests.test_web_chat | authoring/UI AI 相关快速目标，已确认的容量基线失败继续明确记录，不能通过完全不映射该模块掩盖 |
| tests.test_module_selection | 新增 shared.testing 或等价测试工具模块，映射 scripts/test_modules.py 与 tests/module-map.json |

快速/浏览器分类以实际执行路径为准。对混合模块可用明确 TestCase.method 目标；所有选中目标必须能解析，合并后的实际 test id 不重复，不能仅依靠 target 字符串去重。验收包括源码映射覆盖、既有测试的映射/迁移清单、真实消费者闭包和浏览器 opt-in；不因此运行全量测试。


D 独立审核补充：应用层也必须按实际构造与调用映射，不能只修仓储边。Authoring 直接依赖 repository.tasks/steps/environments/runs/results，不依赖 StepUseCases，因此移除首版错误的 application.steps 前置。RunUseCases 依赖上述五个仓储及 application.authoring；StepUseCases 依赖 repository.steps/tasks/runs、application.authoring 与运行协作；TaskUseCases 依赖 repository.tasks/steps/contexts、shared.storage、application.authoring 与运行协作；EnvironmentUseCases 依赖 repository.environments/runs/planning 与运行协作；PlanningService 依赖 repository.planning/contexts/steps 及 application.tasks/authoring。现有 runtime/worker 归 application.runs 模块，其消费者应可被逆向选择；不反过来声称该用例依赖 TaskUseCases。共用 context_sessions 源文件可映射运行、规划、环境等实际消费者，不通过错误反边消除或制造循环。至少验证 runs.py 变化能选择 steps/authoring/runs 及其 UI，results.py 变化能选择 authoring/AI；各模块名字相同的尾段不能导致仓储边误覆盖应用边。
