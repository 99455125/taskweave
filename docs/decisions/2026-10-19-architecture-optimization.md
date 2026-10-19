# TaskWeave 架构优化需求与设计

状态：已完成已确认范围的架构整改与定向验收；2026-10-19。

2026-10-19修订：按用户要求纳入UI可替换性，保留NiceGUI，明确框架无关交互层及无界面验收；方案已获用户确认，实施包含本节新增目标。

## 目标与依据

用户要求整改整体架构审核中可读性、可扩展性不足的部分；评价较好的部分也纳入复核，对有依据的局部问题一并整改。成功标准是职责可定位、状态有明确所有者、消费者依赖足够窄、公开契约可持续兼容，而非单纯减少文件行数。

UI可替换性是本次明确目标：未来替换界面框架时，应用用例和主要交互状态/流程可以复用，仅重建框架渲染、控件事件绑定和平台适配。本次保留NiceGUI作为实际界面，不开发第二套UI；独立Web前端需要的远程传输、认证及分布式会话协议不在本次范围内。

审核基于当前工作区（包含已有未提交修改）。当前主包92个Python文件、19771行；桌面层11323行。Workbench文件1572行、PlanningPage文件1122行；RunRepository协议53个方法，具体类68个方法定义。规模仅用于定位，不能单独作为拆分理由。

现行约定见[架构决策](architecture.md)、[维护索引](../maintenance.md)、[测试规则](../testing.md)。关键代码依据：

- [Workbench](../../src/taskweave/desktop/workbench.py)、[TasksPage](../../src/taskweave/desktop/pages/tasks.py)、[StepEditorRenderContext](../../src/taskweave/desktop/components/step_editor.py)：跨组件回调、共享状态与兼容转发集中。
- [运行协议](../../src/taskweave/core/repositories.py)、[运行仓储](../../src/taskweave/infrastructure/repositories/runs.py)、[运行协调](../../src/taskweave/infrastructure/runtime.py)：查询、状态写入、租约、事件、恢复、通信职责集中。
- [Authoring](../../src/taskweave/application/authoring.py)：直接构造基础设施Resources、PluginContext和Results。
- [DesktopController](../../src/taskweave/desktop/controller.py)：操作调用、编写请求保留、配置及工作空间操作集中。
- [Store](../../src/taskweave/infrastructure/storage.py)、[Repository](../../src/taskweave/infrastructure/repository.py)：底层存储与仓储适配互相可达，兼容入口与当前入口并存。
- [插件SDK](../../src/taskweave/plugins/sdk.py)、[Registry](../../src/taskweave/plugins/registry.py)：公开扩展基础良好；[Playwright入口](../../plugins/playwright/src/taskweave_playwright/__init__.py)仍混合会话、动作、结果与插件装配。

已核对源码：控制库当前版本17、任务数据版本2，现有架构文档的控制库v14及九仓储描述已过时；当前装配包含organization共十个仓储。实施时同步这些受影响的事实描述，数据库结构不因文档纠正而变化。

## 路线选择与范围

推荐在现有模块化单体上分阶段收紧边界。仅移动文件不能解决状态耦合；整体重建领域层、替换存储或引入框架会扩大行为变化和兼容风险。采用前者，完整覆盖以下工作包，不将分阶段理解为缩减交付范围。

保留Python/uv、SQLite、NiceGUI、现有插件发现机制和JSON边界。不引入ORM、事件总线、DI框架或微服务；不新增产品功能、不调整UI视觉和业务规则、不升级依赖。不操作用户真实工作空间、外部业务系统或已安装应用。

## 目标结构

### A. 桌面状态与组件

- 新增与desktop同级的presentation包，承载框架无关的交互状态、流程协调及其窄接口，按任务工作区、编辑、规划、调试、上下文、执行和设置等职责组织。依赖方向为NiceGUI适配层→presentation→应用用例/契约；application、core不反向依赖presentation。presentation不得导入desktop、NiceGUI、pywebview或具体基础设施，也不接收经Any/Callable隐藏的控件、客户端和页面容器。
- Workbench拥有应用外壳、路由呈现和组件装配；首页渲染移入pages下独立页面。导航许可、未保存离开判断等交互决策属于presentation，URL解析/写入及实际页面切换属于NiceGUI适配。
- 引入框架无关的任务工作区协调对象，拥有选中任务/步骤、标签切换、离开校验及草稿恢复的协调。编辑状态对象拥有草稿、已保存版本、冲突与保存状态；调试、上下文、执行等交互对象分别拥有各自逻辑状态。一个状态只有一个写入所有者，其他组件通过只读快照与明确动作访问。
- StepEditor等NiceGUI组件拥有控件、焦点、布局和渲染资源；输入事件及时更新交互状态，渲染从状态快照获取值，禁止业务动作临时读取控件树作为唯一数据源。交互层输出普通Python数据和明确结果，提示、确认、文件选择等由适配层呈现，再将用户选择作为动作输入；不传入创建控件或弹窗的回调。
- 按导航、编辑、调试、上下文等实际消费者收窄接口，替换TasksPage的大量离散回调以及StepEditorRenderContext的跨组件控件集合。不得用一个新的全能context或service locator平移原耦合。
- 拆出PlanningPage的上下文采集和候选/生成历史视图，页面移至pages目录，原导入位置保留明确兼容导出；生成、选择候选、导入及采集提交的交互编排进入presentation，业务校验与持久化仍由应用用例负责。
- DesktopController保留兼容桌面入口，逐步委托给交互协调对象、应用服务和平台适配。编写请求保留归共享应用会话服务，标签页草稿归各自交互会话，设置/工作空间业务操作经应用接口执行。presentation通过注入的窄应用接口调用，Application/实际服务在组合入口装配。
- 框架无关层可以使用asyncio处理串行化和在途工作；请求标识、版本/代次、过期结果判断与忙状态属于交互层或共享应用服务。NiceGUI适配负责定时器与客户端事件，传入普通会话标识以及进入、离开、可见性、断开、重连事件；交互层决定是否刷新及是否接受结果。共享请求生命周期仍跨客户端存在，页面dispose不能取消已接受的后台工作。
- 文件选择、剪贴板、窗口操作和页面计时分别由小型适配接口或明确交互结果连接；平台实现留在desktop，禁止交互对象直接调用ui、pywebview或打开系统窗口。错误以既有错误码/结构化结果传递，显示文案与通知样式由视图负责，不能吞异常。
- 保持草稿冲突、防重复提交、迟到响应身份检查、标签隔离、轮询可见性及资源释放语义。页面控件不得反向挂回Workbench形成第二套所有权。

目标调用链：用户事件→NiceGUI适配→交互动作→应用用例→执行/存储/插件；结果返回交互状态→快照→NiceGUI渲染。后端运行状态仍以应用/持久化事实为准，交互层只拥有选择、草稿、请求状态等展示所需状态，不复制执行状态机或业务校验规则。

覆盖所有现有桌面页面及共享交互组件：有交互决策或状态的流程归presentation；简单只读页面直接呈现应用查询结果，无需机械增加协调类。主题、纯格式化和控件布局继续留在desktop。未来更换UI时需要重写渲染与平台适配，进程外前端还需要额外通信设计；本次通过无界面测试证明可复用边界，不承诺零成本替换。

### B. 运行端口与协调

- 根据实际调用方拆出运行查询、执行状态写入、事件、租约/回执等窄Protocol。旧RunRepository保留为兼容聚合协议，新消费者声明所需接口。
- 初期允许同一个SQLite RunRepository实现多个窄端口；按事务一致性决定实现拆分，不能按表名机械拆CRUD，也不能通过通用query/execute接口绕过边界。
- runtime拆为运行编排、worker通信/生命周期、实例池三个内部职责。Coordinator继续负责状态机协调，CoordinatorPool管理实例选择与容量，通信适配负责进程与消息收发。
- 保留线程/进程模型、锁和事务边界、命令幂等、租约、补录、取消、恢复、UNKNOWN与人工核对机制；本次不改变调度算法或IPC载荷。

### C. 应用服务与基础设施

- 在core定义编写服务实际需要的资源会话接口与工厂；基础设施实现会话创建、插件上下文及结果设施装配，Application负责注入。Authoring不再直接构造worker内部对象或具体Results。
- 共享资源实现可供固定执行和编写复用；AI策略、提示与模型调用仍只属于编写路径。
- 清理依赖方向时区分真正的基础设施和纯数据/纯函数，按多个真实消费者提取公共契约，避免为消除导入而复制逻辑。
- 保留Application作为显式组合入口，分离其依赖装配细节和公开操作兼容转发；组织分类操作等新增入口也核对应用职责，统一经用例进入仓储。

### D. 数据与操作契约

- 为任务、步骤、运行摘要、执行请求及关键命令返回定义稳定的TypedDict/数据类型；JSON对外形状保持原样，插件扩展载荷允许开放字段。
- 对跨组件Callable补全参数和结果语义；用窄Protocol表达行为依赖。避免用Any掩盖核心协作边界。
- 公开操作名、参数默认值、返回形状、同步/异步和锁豁免集中维护；无需为每个简单转发增加类。
- 类型声明配合静态结构守卫与边界契约测试；本次不新增类型检查器依赖，不把类型标注存在等同于运行时校验完成。

### E. 存储与兼容入口

- 将SQLite连接、迁移、UoW和共享基础函数归于低层存储模块；领域仓储只依赖该低层模块，装配在组合入口进行。
- Store/Repository/PlanRepository原路径和已使用签名保留显式委托；旧Store适配层可依赖仓储，但新低层存储实现不得反向构造仓储。
- 为兼容入口登记实际消费者与保留原因；迁移项目内正常调用到规范入口，保留专门的兼容测试。删除入口需证明不属于公开/持久化/插件/打包契约，并在本任务记录依据。
- 不删除现有测试来掩盖兼容损失，不保留双写业务实现。事务、迁移、文件清理及错误传播保持当前语义。

### F. 插件与良好部分的局部优化

- 保留SDK入口、独立包、entry point、版本约束、可选依赖隔离和声明式结果展示；补强宿主与插件边界守卫。
- Playwright按会话、定位/动作、结果处理及插件装配拆分；__init__保留入口和必要兼容导出。类移动须检查多进程、打包收集和已使用导入路径。
- 对其余十个插件逐个完成职责/依赖复核，记录“已整改”或“保留及依据”。仅对混合职责、重复协议实现、内部依赖泄漏等具体问题修改；简单插件不强制套统一目录层级。
- core协议按业务主题组织，公开重导出保持兼容；将desktop/dependencies.py等不准确名称调整为实际职责名，迁移引用并保留必要兼容。
- 新增/移动源码同步module-map、打包资源/入口和文档导航；将架构守卫覆盖到新的职责边界及插件宿主导入路径。

## 实施任务与依赖

下表为同一方案的实施工作包；审核后继续在本记录细化文件/接口与实际结果，避免生成重复的权威进度。

| 顺序 | 工作包 | 交付与完成判据 |
| --- | --- | --- |
| 0 | 固定当前基线 | 重查已有修改；记录公共入口、UI状态所有者、关键消费者与模块验证选择；相关历史失败单列 |
| 1 | 稳定数据/行为契约 | 按消费者定义类型与窄接口，明确presentation状态/动作/快照、生命周期事件和应用端口；兼容聚合入口保留，以替身验证实际可替换性 |
| 2 | 存储和运行边界 | 完成低层存储与兼容适配分离、运行职责拆分；事务/租约/恢复/通信契约验证 |
| 3 | 编写与应用组合 | 资源会话工厂注入、应用装配和用例归属收敛；模型fixture及固定执行分离验证 |
| 4 | 框架无关交互与NiceGUI适配 | 先迁移状态与交互决策并做无界面测试，再接回NiceGUI；完成单一状态所有者、控制器委托、首页/规划拆分及真实界面回归 |
| 5 | 插件结构与发现 | 十一个插件逐项结论、必要结构整改、公开SDK及入口兼容；受影响插件验证 |
| 6 | 集成与知识同步 | 兼容消费者迁移、映射/守卫/打包核查；更新受影响模块和架构事实，记录剩余限制 |

每阶段保持可运行；公共文件和状态由当前实施者串行维护。沿用当前工作区，保护既有修改，不自动转移、覆盖、重置或清理。若实施前出现与基线不同的新修改，重新核对受影响部分。

## 验收与验证

结构验收：

1. Workbench不再拥有任务编辑/调试/采集的第二份可写状态及组件控件镜像；页面和组件经窄接口协作。
2. 新运行消费者只声明实际需要的端口，不能通过泛型SQL调用绕过边界；实例池、通信及运行编排职责可分别定位。
3. Authoring不直接构造worker内部资源与具体结果存储；固定执行无模型依赖。
4. 新低层存储模块不依赖领域仓储；正常调用与兼容门面的使用者可区分。
5. 稳定业务数据和协作接口具备可读契约；十一插件完成逐项结论，公开SDK和可选依赖隔离保持。
6. 文档、映射、导入与打包入口反映真实实现；文件长度和方法数量作为辅助指标，不设置机械拆分类阈值。
7. presentation及其导入链不加载NiceGUI/pywebview/desktop；应用层和core不反向依赖交互层。使用真实交互对象、应用替身和普通数据即可运行交互测试，不构造UI控件，不模拟ui全局对象。
8. 每类交互状态具有明确所有者；状态/快照/动作参数不包含控件、框架客户端、页面容器或渲染回调。NiceGUI适配不保留重复的保存、冲突、候选采纳、运行补参和过期判断规则。
9. 在阻止GUI框架导入的测试进程中完成关键交互场景；同一交互实现被实际NiceGUI页面使用，不能仅为通过验收建立未接入的独立状态模型。平台适配可由内存替身替换，后端执行与现有公开契约不依赖具体界面。

行为验收：现有路由/参数/返回/锁语义、插件API v1、步骤格式、任务包、数据库版本和用户数据保持兼容。关键路径覆盖任务导入复制与回滚、步骤保存确认、规划生成导入、AI请求保留、上下文采集、正式执行/调试/补录/重跑/恢复及结果查看。保持错误传播和隐私处理，不以吞异常或自动降级维持表面通过。

验证执行按[测试规则](../testing.md)：

- 本轮仅文档：`uv run python scripts/check_project.py`、`git diff --check`。
- 实施时按实际修改逐批运行changed dry-run，核对真实消费者闭包后选择定向测试；不按工作包分组拼成全量。闭包等同全量时先列出范围取得明确确认。
- 复用架构边界、仓储契约/装配、存储完整性、执行恢复、运行输入、规划、AI编写、UI组件及插件契约测试。新增测试验证边界行为，不镜像文件布局或私有实现。
- 受影响既有测试先记录基线；失败区分既有问题与回归，不能静默修改期望值。新增文件补module-map并运行模块选择器测试。
- UI可替换性新增定向无界面场景：编辑→保存→版本冲突后保留草稿；切换任务/步骤时保存或放弃的选择；标签隔离与重连草稿恢复；启动调试→缺参→补录→继续；AI请求跨视图保留、重复提交拦截及候选采纳身份核验；规划候选导入与上下文保存失败后的暂存保留；离页后迟到响应不更新新视图且后台工作继续；不可见时停止查询、恢复可见后按原规则同步。断言操作调用与状态结果，不仅断言类型或文件名。
- 增加依赖方向守卫以及禁止GUI导入的交互层导入/运行测试；测试入口避免从旧desktop兼容模块间接加载GUI。按实际消费者将presentation源码及反向依赖加入module-map。
- UI装配/生命周期变更在临时工作空间做真实浏览器验证，保留核心场景证据；Playwright结构改变做本地真实浏览器集成。使用本地fixture，不调用真实模型、生产数据库或发布服务。
- 移动影响启动/冻结路径时验证worker spawn、资源收集和相应打包测试；原生macOS/Windows实机与完整发布构建分别报告，未执行不得推断通过。

## 风险、审核事项与进度

主要风险是UI异步生命周期、运行恢复与兼容入口的隐含消费者；交互解耦还可能产生两份状态或两套规则。通过先固定契约、逐阶段迁移到单一所有者、同一交互实现接入NiceGUI、保留明确适配以及临时环境回归控制。当前混合工作树本身是实施基线，新增修改必须与既有成果同时保持有效。

已确认按本记录全部范围（包含保留NiceGUI、交互状态与逻辑框架解耦及无界面验收），以保持现有行为和公开契约的渐进方式实施。若需要改变业务规则、存储格式或公开协议，另列具体方案确认。本次实施确认不包含全量测试、Git写操作或非本地部署授权。

进度：各工作包已落地；完整范围复审后的补齐与最终验收以本文末尾台账为准，前文为阶段证据。

2026-10-19文档验证：`uv run python scripts/check_project.py`通过（182份Markdown及工程结构检查）；`git diff --check`通过。方案已自查范围、兼容约束、验收与阶段依赖；这些检查不代表功能整改完成。

## 已确认实施与执行记录

用户已确认上述方案并要求开始实施。按当前工作区实施；沿用本记录作为设计、任务和验证的权威入口。技术细化由实施者按已确认边界完成，不再重复需求审核。

实施分工：主实施者负责presentation/desktop、公共映射、集成与文档；插件、存储、运行/应用各独立文件范围并行。所有Git写操作、全量运行及真实业务数据操作继续遵守原授权边界。

### 接口与文件细化

- [x] 交互基础：presentation/state.py保存普通状态；editor.py的EditorSession(state, save_draft, page_generation).save(document)负责串行与版本身份；forms.py的schema_from_rows(original, rows)保留无效草稿；application/authoring_sessions.py的AuthoringRequests(call).submit/get保留在途请求，presentation/requests.py保留纯兼容导出；inputs.py的RunInputs(port, drafts, identity).resume返回ResumeResult(current, waiting)。desktop旧入口委托同一实现。
- [x] 编辑和工作区：将表单原始值、草稿快照和导航离开决策迁入presentation；NiceGUI只同步输入和显示结果。控件引用留在desktop适配，保存冲突不清空草稿，迟到结果不污染新选择。
- [x] 页面组织：首页独立页面，规划视图/交互分离，控制器的平台操作与交互编排分开，保留旧入口兼容。
- [x] 存储：sqlite_storage.py提供无仓储依赖的SQLiteStorage及连接/迁移函数；storage.py保留兼容Store/Results。仓储仅依赖底层存储，原事务与版本保持。
- [x] 运行/应用：运行端口按消费者拆分，runtime保留公开Coordinator/CoordinatorPool入口；资源会话由工厂注入Authoring，应用组合统一用例归属。
- [x] 插件：Playwright拆会话/动作/结果/装配；十一插件逐项复核，保留SDK和入口兼容。
- [x] 集成：逐文件登记module-map，新增presentation依赖守卫和禁GUI导入运行测试；运行选定的回归及真实临时浏览器场景，更新实际模块文档。

验证重点：并发保存使用前次成功版本；保存失败保留编辑；页面离开不取消已接受操作；暂停补参恢复原执行模式；原导入路径和多进程入口保持可用。各任务先执行新增边界测试观察失败，再接入实现和既有定向回归；每次结果记录在下方。

首批无界面交互测试：5项RED（presentation尚不存在）→5项GREEN。已接入NiceGUI保存、参数schema、AI请求保留及补参入口；既有UI定向回归执行中。此为阶段证据，不代表全部UI解耦或整体完成。

### 已落地的边界与兼容消费者

| 边界 | 当前规范入口 | 保留的消费者与原因 |
| --- | --- | --- |
| SQLite | SQLiteStorage + build_sqlite_repositories；组合入口复用同一集合/UoW | storage.Store旧构造、Repository/PlanRepository兼容门面及原测试；Results仍为具体结果适配，并未移除文件/数据库契约 |
| 运行 | run_coordinator / coordinator_pool / worker_transport；查询、事件、租约、写入窄端口 | runtime.Coordinator/CoordinatorPool旧导入及测试保留；未改IPC或数据库格式 |
| 编写 | ResourceSessionFactory注入；应用会话共享AuthoringRequests | DesktopController旧调用委托同一服务，多个Controller共享在途请求；页面取消等待不取消已接受工作 |
| 规划 | desktop/pages/planning及采集/生成组件 + presentation/planning | desktop/planning旧导出保留；页面测试patch规范入口 |
| 编辑/任务 | EditorSession、WorkspaceNavigation、TaskTabTransition、TaskDraft、TaskOrganization | Workbench/desktop.state旧属性显式转发到唯一普通状态；窄Task面板只在桌面适配协作 |
| 设置/环境 | ApplicationSettings + SettingsSession / EnvironmentSession | Controller和页面原入口保留，控件事件更新普通草稿；平台调用仍在desktop/platform |
| 结果字段 | presentation/result_fields | desktop/dependencies旧导入保留兼容，正常编辑器引用规范入口 |
| 插件 | 各插件独立SDK入口；Playwright分工模块、TiDB database | 旧entry point、类pickle路径及两个既有测试替换钩子保留；详见[十一插件复核](2026-10-19-plugin-structure-review.md) |

### 集成验证阶段记录

以下是实际执行的定向证据，存在重复覆盖，不汇总为一个去重测试总数。未运行全量或用分组拼接全量；共享存储/组合入口的changed dry-run闭包很广，仅用于核对映射和选择本次必要代表场景。

- 存储边界及现有契约34项、运行/补录/控制27项、编写/端口等25项定向通过；插件修改前45项基线及修改后52项通过。
- 两个真实Chromium插件场景通过：角色隔离与跨步骤会话复用、实际浏览器工作流文件保存及无重复提交（8.974秒），使用本地fixture。
- UI编辑/AI/补参44项、任务与导航27项、首页7项、步骤素材11项通过；后续集成80项（交互禁GUI、编辑、任务、导航、素材、模块选择）通过，3.826秒。
- 执行页21项通过，0.373秒；打包收集相关、存储分层及运行架构22项通过，0.792秒。前者包含重绘后轮询、文档隐藏与恢复可见回归，后者不等于完成原生发布构建。
- 规划完整交互54项定向通过，包含禁GUI/desktop/infra进程中的实际交互测试；环境新增4项先失败后通过，环境定向共15项通过，1.428秒。
- 任务组织与设置草稿新增4项先失败后通过；页面/组织/任务配置及交互定向24项通过，0.382秒；实际NiceGUI设置输入事件另有8项定向通过。
- 独立审核确认并修复三处本次回归：连接测试提示的async契约、异步前序字段类型未同步普通草稿、执行页dispose意外关闭后续轮询。三项新增回归均先失败后通过，复核者再次独立运行通过。
- 真实工作台大场景首次停在旧“添加步骤”入口；已核对HEAD同样先打开概览且旧测试缺少切换步骤管理。测试将旧标签/入口更新到现行界面，保留业务结果断言，最终结果待后续记录。
- 既有失败单列：web_chat的所选历史容量断言，以及planning列表的旧按钮/删除图标断言，已在本次对应修改前或HEAD实现确认；不修改产品规则或删除断言来隐藏失败。

调试普通草稿已接入、最终浏览器已通过；源码/测试映射与受影响模块文档已同步。未执行完整发布构建、原生macOS/Windows实机验收、第二套UI或真实外部模型/业务系统验收。

### 前一阶段界面验收与限制

- 调试输入完成单一普通草稿所有权：45项调试/编辑器定向及11项补参回归通过。输入事件同步raw，提交不依赖临时读取控件，未完成JSON/必填留空/环境变化/断线恢复保留原语义。
- 独立复核新增发现的Schema根变量遮蔽、TaskDraft初始化、设置页重挂载会话问题已补回归并修复；44项表单/编辑/设置/任务定向通过（2.735秒）。Schema根约束与字段约束同时保留；旧设置动作只消费原会话草稿。
- 最终工作台真实Chromium验收：`env -u PYTHONPATH uv run python -m unittest tests.test_workbench_browser.WorkbenchAcceptance.test_real_task_authoring_ai_trial_run_history_and_configuration -v`，1项通过，25.407秒。覆盖创建任务、编辑与离开取消、AI生成、成功/失败调试、网页/API修复、正式执行、历史只读、插件、环境、设置及实时日志。3次本地模型fixture调用，正式执行没有增加模型调用；page_errors、backend_errors、external_requests均为空。
- 浏览器验收发现重绘后URL同步仍读取已删除控件的客户端上下文；先用后端完整堆栈断言复现失败，再在launcher捕获稳定client写路由，最终同一场景通过。未变路由参数及用户导航行为。
- 浏览器证据位于工作区`.runtime/architecture-ui-evidence/`（acceptance.json、server.log、application.log及界面截图），修复前堆栈保存在before-route-fix/；本地运行产物不作为源码或永久用户数据处理。
- Python3.10语法解析覆盖当前147个主包及受影响插件源码，通过；运行测试实际使用Python3.12，不能等同于3.10解释器实测。工程/文档守卫与diff空白检查通过。

UI替换验收的含义：主要交互流程与草稿由普通Python对象拥有，NiceGUI实际复用这些实现，并在禁止GUI导入进程执行关键交互。将来仍需为新框架实现布局、事件与平台适配；本次未实现第二套UI或远程前端协议。

未运行：全量测试、完整原生发布构建、macOS/Windows原生窗口实机验收及真实外部模型/业务系统验收。已有web_chat与planning旧断言失败仍独立保留，不计为本次通过。已有混合工作树修改及用户数据保留，本轮未执行Git提交/推送/PR写操作。

最终集成复验：禁GUI交互进程、模块选择、共享编写请求与工作区导航共33项通过（1.058秒）；独立审核者另运行6项调试输入/实际控件/恢复场景通过（0.629秒），未发现新的实质问题。183份Markdown与工程边界检查、`git diff --check`最终通过。

### 完整范围补齐与最终验收

再次按原方案复审发现上一阶段遗漏了部分已有交互，因此曾撤回整体完成结论；已有定向结果保留为阶段证据。本节记录补齐后的当前结果，覆盖原A–F全部工作包，不以先前关键路径通过替代完整范围核对。

| 原工作包 | 当前实现及验收依据 |
| --- | --- |
| A. 桌面交互与UI可替换性 | 编辑/导航/规划/调试/设置/环境之外，现已补齐RunCreation、StepActions、TaskImportSession、CategorySession、PluginSelection、CatalogFilter、AIInteraction/AIChoiceDraft、CollectionForm/TargetSelection、ExecutionInteraction及HistoryLoadState。RunInputs/InputSubmission拥有补参草稿、校验、打开/提交防重。实际NiceGUI消费相同普通状态；兼容辅助入口只委托现实现。无GUI进程实际运行所有对应交互测试，实际控件测试验证事件更新后业务提交不读控件。 |
| B. 运行端口与协调 | core/run_ports按实际消费者定义查询、事件、租约、写入端口，旧RunRepository聚合兼容。run_coordinator、coordinator_pool、worker_transport分开编排、实例选择及进程通信；事务、命令幂等、恢复和IPC语义保持。当前定向运行边界及真实worker/浏览器执行证据通过。 |
| C. 应用服务与基础设施 | composition统一装配用例与ResourceSessionFactory；Authoring依赖core资源接口，固定执行无模型调用。共享AuthoringRequests跨Controller保留请求；组织和设置归应用用例。正常demo改用用例与规范存储路径。 |
| D. 数据及操作契约 | data_contracts定义任务、步骤、运行摘要、执行请求和命令结果；公开操作元数据从实际handler生成默认值、异步与锁契约。交互消费者协议明确操作、命名参数及返回形状，插件JSON扩展保留开放字段；静态守卫和实际契约测试通过，未引入类型检查器或改变JSON校验。 |
| E. 存储及兼容 | SQLiteStorage可在阻止仓储/旧门面导入的独立进程初始化迁移、事务回滚；正规仓储装配同样独立于旧门面。正常helper消费者迁到sqlite_storage，Store/Repository/PlanRepository保留显式兼容及相应测试；无数据库或任务包迁移。 |
| F. 插件及良好部分局部优化 | 十一插件均有逐项结论；Playwright拆分职责、TiDB提取数据库共享实现，其他插件依据已记录。core增加json_types、capability_contracts、context_contracts、model_ports并保留ports/SDK同类重导出及旧pickle路径。result_fields替代不准确的dependencies规范入口；源码、测试映射、入口及模块文档同步。 |

九项结构验收的对应证据：1、8、9由实际页面接线、普通交互行为、禁GUI进程和真实浏览器共同证明；2由运行端口消费者与通信/实例池行为测试证明；3由注入会话及模型失败清理、固定执行测试证明；4由底层存储与正规装配隔离进程证明；5由数据/操作契约、SDK兼容及十一插件复核证明；6由模块选择器、工程/文档检查及打包收集定向证据证明；7由依赖守卫及禁止GUI/desktop导入的交互运行证明。交互快照不包含控件、框架客户端、页面容器或渲染回调。

本轮补齐与最终验证（各组有重复覆盖，不合并成去重总数）：

- RunCreation 31项、StepActions 18项；AI草稿/防重25项、执行查询/历史32项通过。
- 采集表单/目标选择68项通过，实际NiceGUI新增4项覆盖步骤/规划入口、目标恢复及session转发；禁GUI进程通过。
- TaskImport提交防重、关闭和失败重试21项通过；RunInputs/InputSubmission 25项通过，实际UI在移除控件句柄后仍能提交。已接受业务操作不会因关闭或离页被取消。
- 任务/规划/执行筛选46项及旧规划导出入口1项通过，包含event.value与控件值不同的真实事件测试，证明提交消费普通状态。
- 八处消费者协议49项、余下四处协议31项定向通过；EditorSession保存参数签名同步明确。独立复核补参和日志关键回归8项通过。
- 核心契约独立导入与SDK/旧pickle兼容、存储分层、运行架构、编写资源、插件结构、模块映射及禁GUI交互最终46项通过（2.926秒）。之后新增目录筛选映射/禁GUI入口、操作协议、实际采集与执行详情最终45项通过（1.125秒）。执行手动/尝试日志复用HistoryLoadState，16项日志及详情定向通过。
- 正常demo五步真实worker替换、工作空间迁移及macOS bundle边界12项通过；此前真实Chromium插件集成及打包收集定向结果见上文。
- 最终真实工作台：`env -u PYTHONPATH uv run python -m unittest tests.test_workbench_browser.WorkbenchAcceptance.test_real_task_authoring_ai_trial_run_history_and_configuration -v`，1项通过（25.988秒）。3次本地模型fixture请求，正式执行未增加模型调用；acceptance.json的page_errors、backend_errors、external_requests均为空。证据位于`.runtime/architecture-ui-evidence/`。
- 最新160个主包/受影响插件源码通过Python3.10语法解析；实际运行解释器为Python3.12，此项不等同于3.10实机运行。最终工程/文档及空白检查结果见下条。

本次已完成的是保留NiceGUI的架构优化与约定定向验收；未来更换UI仍需重写布局、控件事件和平台适配。第二套UI、远程前端协议、全量测试、完整原生发布构建、macOS/Windows原生实机及真实外部业务服务均不属于本轮已执行验证。既有web_chat容量与planning旧界面断言失败继续保留，不计入通过，也未修改业务规则掩盖失败。既有混合工作树、用户数据与配置保留。

最终工程检查：`uv run python scripts/check_project.py`通过（183份Markdown、源码语法、依赖边界、对话框策略及CLI版本）；`git diff --check`通过。
