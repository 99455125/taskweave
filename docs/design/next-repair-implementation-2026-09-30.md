# 下一轮修复实施与证据

状态：2026-10-01 已完成本轮；断连/跳首页项按用户“无法复现说明已解决”的验收口径关闭。完整根因未确定不再作为本轮阻塞，验证范围仍按下文记录。

目标：完成 [统一清单](next-repair-round-2026-09-28.md) 的全部清单项（原六项加新增 SQL/文件读取链路），不以部分测试通过代替整体验收。

沿用用户已确认的布局、保存与插件方案，负责人直接实施。保留 NiceGUI、业务数据、事务和运行身份保护；不自动提交，不做全量或拼组全量测试。修改以当前主树为基础，保留已有文档修改。

## 实施顺序

1. **补参生命周期**：`components/run_inputs.py`、`state.py`、Workbench 装配。查看运行只提供补参入口，主动打开时才读取并构建表单；弹窗挂在稳定布局下，草稿按运行/补参请求身份保留；提交防重且重新核对请求，防止旧窗口提交到新请求。用真实 NiceGUI 组件及浏览器验证暂缓、A/B 切换、新请求、无效草稿、慢响应和重复提交。
2. **性能与重绘**：核查执行列表/详情、调试、规划及其他定时器；同类查询不重叠，无变化不重绘，隐藏/终态停止不必要轮询。真实浏览器记录响应、请求数、重载数和慢请求期间交互。
3. **首次可见状态**：规划的非当前区域创建即隐藏，调试重内容首次展开才构建；异步构建保持代次保护。慢响应下验证无闪现。
4. **步骤保存与调试边界**：步骤配置、调试、日志独立容器；移除步骤周期自动保存，以编辑事件维护未保存状态，顶部保存，底部校验/确认验证；验证离页保存/放弃/取消、失败草稿和旧结果版本。
5. **复杂页面定位证据**：Playwright 插件定位范围、checked 读取/断言、有界局部 DOM、实际验证候选定位器；旧定位器兼容。浏览器验证同名 radio、今天、浮层、iframe 等。
6. **可选录制**：通过通用可选提供器契约实现会话开始/暂停/结束/游标读取/保存确认/丢弃，Playwright 实现操作目标与页面证据；兼容快照、预览开关和任务包，敏感输入不落证据，保存失败保留缓冲。真实复杂页面及导入导出验证。

7. **SQL 与文件链路**：新增独立文件读取插件，输出经步骤绑定传给 TiDB SQL 执行动作；保留只读查询兼容，写动作标明副作用和不可自动重试，事务失败与多语句脚本边界先明确。

每项先复现/写失败用例，再修复、运行相关测试和实际交互；后续接口以现行插件源码细化并记录兼容裁决。最终逐条审核清单，证据不足的项目保持未完成。

## 进展

- [x] 补参生命周期及真实交互
- [x] 逐页轮询/重绘/断连审计与验证（偶发原生问题按用户认可的无法复现口径关闭）
- [x] 首次可见状态与懒加载
- [x] 独立调试容器与手动保存
- [x] Playwright 复杂页面采集
- [x] 通用可选录制及上下文链路
- [x] TiDB SQL 执行与文件读取链路（本地协议验收，非真实 TiDB 实机验收）
- [x] 全清单完成审计

以上勾选对应下文当前源码、针对性测试、真实临时浏览器证据及最终用户验收口径。历史段落中的阶段性待办以末节关闭记录为准。

### 既有弹窗改动审查

`c066567` 改动统一 ESC/点外关闭，并增加前端点击守卫。它没有修改补参自动打开或草稿生命周期；`RunInputDialog.show` 仍由执行/调试刷新调用，详情删除弹窗或页面身份变化后重新创建并 `open()`。因此其关闭策略不能证明补参重复弹窗已修复。保留已有正常关闭策略，修复实际触发源。

### 已实施与当前证据（仍在验收）

- 补参改为显式打开，弹窗挂稳定布局；按运行/请求保存原始草稿，提交原子核对 `expected_input_id`。真实临时 A/B 运行反复切换不弹窗，无效 JSON 草稿恢复，双击只提交一次并续启一次；不是仅关闭策略变更。
- 执行列表增加事件 revision 与结果数量读模型，无变化复用详情；空闲 5 秒、运行中 1 秒轻量检查，隐藏/重叠跳过。真实浏览器 11 秒观察仅 2 次列表查询，没有详情或日志重读、没有页面重载。尚未完成所有页面、长 AI 请求及原生窗口断连审计。
- 调试重内容首次打开才构建，配置/调试/日志分为独立容器；去掉步骤自动保存定时器，顶部手动保存，底部仅校验与确认验证。失败草稿保留，dirty 确认先要求保存，离页原保护保留；四宽布局仍在复验。
- 日志入口复核：顶部服务日志从未删除，改名“实时日志”；执行完整日志入口已恢复，实时组件共用游标接口 `run.events.page`（旧 `run.events` 不变）。默认关闭，增量获取最多 100 条/次，显示最近 24000 字符；单条长事件摘要明确提示截短，完整文本仍可分页查看/复制。停止、隐藏、离页和请求重叠受保护；执行日志容器不随详情刷新销毁。
- 日志/执行/调试组件及游标接口此前 26 项通过；步骤手动保存、懒构建等此前相关 60 项通过。上述都是受影响测试，不是全量验收；SQL/文件与 Playwright 共用定位底层已有实现，录制和其他能力族仍待实施，不能据此宣称本轮完成。

### 插件阶段统一能力规划（2026-09-30；以下增强仍待实现）

现行动作目录由 `PlaywrightPlugin.actions()` 的实际 spec 核对，共 18 个。全部动作支持可选 `role`，未填时取任务/环境中的 `playwright_role`，默认 operator。现行 selector 是字符串 CSS，或 `{kind: css|role|label|placeholder, value, name?, exact?, frame?}`。接口表用于保留兼容，不把计划中的字段写成现有能力。

| 现行方法（playwright. 前缀） | 业务参数（* 必填） | 返回/用途 |
| --- | --- | --- |
| page_open | url* | HTTP/HTTPS 导航，等待 DOM 就绪 |
| page_title | 无 | title |
| page_text | selector? | 可见文本，当前最多 65536 字符 |
| page_fill | selector*, value* | 填写输入 |
| page_click | selector* | 点击，可能提交业务 |
| page_press | selector*, key* | Enter/Tab/Escape/ArrowDown/ArrowUp/Space |
| page_select_option | selector*, option* | 原生 select 的 value 或 label |
| page_wait | selector*, state? | attached/detached/visible/hidden |
| page_assert_text | selector*, text* | 文本包含断言 |
| page_screenshot | 无 | 暂存完整页面 PNG；需 output 才保存 |
| page_download | selector* | 点击下载；staged_file/suggested_filename |
| page_inspect | 无 | 标题、URL、扁平控件、frame、截断标记 |
| page_handoff | 无 | 将有窗口浏览器前置，不自行暂停运行 |
| page_element_image | selector* | 唯一可见元素 PNG Base64，最大 1MB |
| page_input_value | selector* | 实际输入值 |
| page_assert_value | selector*, value* | 输入值断言 |
| page_assert_title | text* | 标题包含断言 |
| page_assert_url | url* | URL glob 断言 |

编写工具同名 `page_inspect(url*)` 在隔离浏览器观察；上下文 `playwright.page(url?, role?, target_id?, scope?)` 采集保留页面或新 URL，可选 viewport/full_page 与图片预览。这三类现场必须继续区分。

增强按共用能力族实施，而非每遇到一个页面新增专用方法：

1. **目标与定位**：所有页面动作共用 role/target_id、定位器和 timeout；保留 CSS/语义/frame，统一 within、受证据约束的 nth、候选定位验证。已有 target 枚举用于采集，新标签页也通过显式目标 ID 访问，禁止随便选择最后一页。
2. **页面观察**：扩展 inspect 的范围、selector、祖先和有界子树；统一输出标签/字段组、语义、状态、属性、实际值、可见浮层和可执行候选，明确截断。密码/敏感值脱敏。CSS fallback 必须实际验证匹配数量，不能只有看似合理的字符串。
3. **交互**：保留已用 fill/click/press/select；统一补充 check/uncheck、hover/double-click、滚动、拖拽、文件上传与原生 dialog 处理，复用定位和错误映射，不写“今天”“第几个否”等业务专用动作。操作后由明确状态断言核对，不能把点击成功当业务成功。
4. **读取与断言**：专用 checked/assert_checked 兼容原生与语义控件；统一读取属性/列表/表格及 visible/enabled/count 等有界状态断言。等待依赖可观测条件，避免 sleep 或全页面不断扫描。
5. **文件与结果**：截图、元素图像、下载保留原暂存/保存结果契约；上传读取受控文件内容。共享文件读取插件输出普通 JSON，不能把浏览器资源句柄交给其他插件。
6. **人工录制**：可选提供器扩展，用统一 session/target/cursor 身份提供 start/pause/end/read/ack/discard；浏览器监听真实人工目标，记录基线、有限结构、操作后状态和缺失证据。缓冲有界、保存失败不消费；可见预览与 send_preview 开关兼容，规划/步骤/任务包沿用现有上下文流转。
7. **错误与限制**：无命中/多命中/隐藏/禁用/过期目标分别报错；frame 和浮层使用现场证据；虚拟化未加载内容、closed shadow DOM、跨页面切换及浏览器权限限制需明确提示，不能声称 DOM 全覆盖。录制不保证自动回放可靠、不自动执行业务。

浏览器录制拟使用 context 级初始化脚本与绑定，以覆盖同一 context 的新页和 frame；与宿主通用录制协议分离。依据 [Playwright BrowserContext 官方接口](https://playwright.dev/python/docs/api/class-browsercontext#browser-context-add-init-script) 与 [Locator 官方接口](https://playwright.dev/python/docs/api/class-locator)。实际版本能力与监听、定位行为仍必须用本地 Chromium 验证，文档参考不替代测试。

文件到 SQL 链路：文件插件读取 SQL 文本（路径、编码、最大字节数明确）→ 当前步骤返回 data → 下一步骤的 sql 输入绑定读取该数据 → `tidb.execute_sql`。同一步可组合两种声明能力，但插件间不直接调用。旧 `tidb.query` 保持只读；新增执行动作标为 WRITE、不可安全重试，参数化 DML 使用显式事务，脚本拆分保留语义。DDL/隐式提交、部分成功/提交结果未知和取消时机必须单独说明并返回可核对证据，不伪称全部已回滚。此处是本轮实施设计，不是已交付清单。

### SQL / 文件实施证据

- 新增可选 file 插件及 files extra，无核心默认依赖；完整读取、格式限制、路径范围和超限失败。新增 TiDB `execute_sql` WRITE 动作，保留旧只读 query 的 schema、结果和行为。新增动作不扩展为 authoring 只读工具。
- 默认事务整批提交；显式 autocommit 支持 DDL，失败报告部分/未知副作用，COMMIT 或 ROLLBACK 失联不伪造成功。脚本按词法分号分割，保留原 SQL 和参数绑定，100条/1MB上限，整批共享结果行数。成功返回逐条报告，无 SQL/参数值回显。
- 新动作缺失时 8 个失败用例 RED；实现后 SQL/只读/文件共 20 项针对性测试通过。随后补充非法 JSON/CSV、提交前结果 JSON 检查的 RED→GREEN。真实 worker 的 file.read → `/content` 绑定 → TiDB 执行，通过真实 PyMySQL 与本地 MySQL 协议 fixture 跑通，观察到 BEGIN→两条原 SQL→COMMIT，结果持久化 COMMITTED。
- Windows spec 和构建 extras 纳入 file 包；尚未在 Windows 构建或运行便携包。没有连接实际 TiDB 或改用户文件/数据库；协议 fixture 不能作为真实 TiDB SQL 语义验收。
- Ruling：DDL 不能纳入可回滚批事务，采用显式 autocommit；默认拒绝而不静默切模式。兼容旧只读接口与任务包，无存储迁移。

### Playwright 统一底层实施证据

- 新增共用 within/nth/frame链解析，动作目标ID、局部timeout、page_targets；不改变主页面，不自动选最后一页，过期ID报错。旧CSS/语义/frame兼容。新增check/checked/assert_checked；mixed不伪称selected。
- snapshot 使用同一有界DOM描述器：候选实际匹配计数、CSS备选、字段组/祖先、属性与checked、敏感值遮蔽；新增局部DOM参数，编写工具与运行时同参，并在隔离URL导航后再检查范围。frame路径逐级唯一验证，DOM结果携带frame身份。
- 新增浏览器失败用例确认旧版within/nth被忽略、today的语义match_count=0仍被推荐、局部DOM不支持、工具参数不支持。RED→GREEN覆盖真实Chromium，包括field/radio、nth、native/ARIA/mixed、目标关闭、nested frame、DOM截断/敏感值、隔离工具导航。局部DOM旧实现丢frame身份与mixed断言误通过均通过独立失败用例修复。
- 注册为browser_targets，所有本轮浏览器测试显式运行；录制契约/监听/上下文UI尚未实现，其他交互/文件/读取断言族也仍待完成，不能将共用底层完成等同整份插件增强完成。
- 版本：Playwright 0.4.0、TiDB 0.2.0、file 0.1.0，SDK v1不变；旧任务包/代码格式兼容，但旧运行仍按原版本快照检查，不静默绕过。uv.lock同步，核心默认依赖不含新增插件。

### 本次回归收口

- 原有真实浏览器集成发现默认快照新增 value 字段违反不读输入值约束，已修复：默认快照不读取值，显式局部 DOM 保留有界值与敏感输入遮蔽。新增真实 Chromium 对照用例先失败后通过；原有上下文采集、AI 只读工具与手工提案流程通过。
- SQL 驱动异常链可能包含数据库消息，已通过失败用例复现并抑制链式回显。解析异常同样抑制内部诊断，保留公开错误码和副作用状态；没有为了脱敏改变提交或回滚裁决。
- 本次插件选定回归 33 项：初跑 32 项通过，新增测试漏导入 json 导致 1 项测试代码错误；补导入后单项复跑通过。包含真实 Chromium 及 worker/PyMySQL 协议 fixture，不代表实际 TiDB 或 Windows 验收。
- 实时日志终态/读取失败后原先把 enabled 置为 false，但没有隐藏面板，导致下一次点击反而重开。新增用例先失败后修复，面板开合状态保留，停止跟随时只停定时器；重新打开可更新或重试。本次日志、执行详情及步骤调试选定 27 项通过。
- 仍未完成：全页面长请求/原生断连审计、规划重内容完整懒加载、剩余 Playwright 交互/读取/文件能力族、通用录制及上下文全链路、最终逐项验收。目标继续保持进行中。

### 规划页签按需构建验收

- 已移除基础配置入口的插件/环境查询、素材卡片提前构建及重复历史构建。基础配置与持续 AI 侧栏先创建；素材首次选择后并行读取能力和环境，身份有效时再创建控件。重复切换复用控件，尚未打开素材时保存直接保留原环境/插件值。
- 历史首次打开查询；隐藏时生成/解析/导入只增加失效版本，下次打开再加载。请求在途发生失效不会被旧响应标记成最新。候选侧栏保持立即读取最新记录，不把侧栏摘要也推迟。
- 新增失败用例先复现原先基础页立即查询/构建，再验证首开、重复切换、基础页保存、隐藏历史失效以及旧规划慢响应不落新页面。本次规划 UI 25 项通过。
- 真实 NiceGUI + Chromium 使用临时应用与 8 组非空长中文材料，插件/环境响应延迟 2 秒；进入基础配置仅一次候选列表查询，没有插件/环境请求，素材树为空。打开素材后立即切回基础，等待完成仍保持素材隐藏，草稿不变；后续打开素材/历史并反复切换，总计能力/环境各一次、生成列表两次（侧栏一次、历史一次）。loads=1，浏览器错误=0。
- 1024/1280/1440/1920 截图保存于 `output/playwright/next-repair/planning-lazy-materials-*.png`，已查看 1440 图核对环境、插件、折叠素材组及持续侧栏；四宽无横向溢出。仅说明此场景，不能代替全部页面/长 AI 请求/原生断连验收。
- 本节取代上节“规划重内容完整懒加载待完成”的状态；其余未完成项继续推进，没有提交或修改用户数据。

### 可选录制协议与规划会话基础

- SDK 追加独立可选 ContextRecordingProvider/Command/Batch，基础 Plugin API v1 不增加必需方法。统一 start/pause/resume/stop/read/ack/discard，批次沿用 ContextCollection 与既有 renderer 校验；读取范围最多100条、序列必须有限非负整数、序列边界明确、返回最多2MB，旧插件录制失败但快照仍正常。
- 新增 plan.context.record 路由与规划会话生命周期，非开始命令要求原实例身份；同一会话串行执行，重复读取无持久化/消费，不能确认未读取证据，停止后的未保存缓冲继续阻止配置变更和结束实例。确认最终停止游标才解除保护，重复 ack 可重试；丢弃明确解除，应用退出临时缓冲随资源关闭。
- 新增3项失败测试先证明旧实现缺少契约/会话入口，再验证协议范围、旧插件兼容、重复读取、未读确认拒绝、原实例身份、缓冲保护与确认后关闭。45项协议/上下文/路由/模块映射相关测试通过；这是通用 fixture，不是浏览器录制端到端验收。
- 路由冻结 fixture 原先漏登记9个已有接口（组织接口、规划生成记录、增量日志）；逐项核对方法与锁策略，仅追加旧遗漏项和本次录制入口，无旧接口删除或异步分类变化。
- 后续必须继续完成：Playwright真实目标/页面证据与监听缓冲、步骤/运行会话通道、规划和步骤采集弹窗控制、保存成功才 ack、预览/发AI与导入导出实际验收。当前不向用户宣称可以开始录制。


### Playwright 真实人工事件提供器

- 可选 record_context 已实现 start/pause/resume/stop/read/ack/discard；初始3项真实 Chromium 用例先证明入口缺失，再通过实际点击、填写与 frame 操作验证，未使用伪造事件替代人工操作路径。
- 页面监听可信 click/input/change；浏览器侧先遮蔽敏感值，记录 actual_target、captured_target 与操作后 target。定位核对原 DOM 元素身份，字段组区分同名“否”，新页面/iframe 携带目标 ID 与 frame 路径。原页面基线和后续新文档首次操作观察明确区分时机，后者不能称为操作前全页快照。
- 暂停/恢复、停止后不追加、重复读取、未读确认拒绝已验证。新增失败用例发现捕获状态被覆盖及已确认回执仍占16个待保存预算，两者已修复；缓冲上限及可选旧截图 renderer 也通过验证。提供器不自动写库、不回放、不进行每秒全页扫描。
- 本次录制及定位共19项真实浏览器测试通过，通用录制/旧采集目标/插件契约/模块映射45项通过。其后新增预览超限缺失标记用例先失败后修复，最终录制提供器7项复验通过；工程检查通过（166篇 Markdown），git diff --check 无错误。
- 产品 UI、步骤/运行会话通道、保存成功后 ack 与导入导出端到端仍待完成；当前不得宣称用户已经可以在产品中录制。没有提交或修改用户数据。

- 实时日志入口追加实际交互：重新确认临时验收服务句柄仍运行后，在本地执行页等待数据加载，界面出现“运行日志”的“实时日志”按钮；真实点击后打开面板。临时 controller 没有原生 open_logs 回调，因此这次只证明运行日志入口，不能代表用户桌面实例顶部服务日志窗口已验收。

- 随后发现旧临时服务仍加载修改前日志文案，已主动停止并重新启动新的临时工作空间加载当前源码，再用真实 Chromium 复验：点击实时日志显示 InputRequested 事件，暂停终态停跟随后点击“收起实时日志”一次即隐藏文本区，返回 containsInputEvent=true、closedWithOneClick=true。未操作用户应用；顶部原生服务日志窗口仍不在此测试范围。


### 保留 worker 录制通道与保存确认基础

- 新增 context.record 到保留的调试/运行 worker，采用现有 IPC 的独立 ContextRecordingCompleted 响应，不污染步骤结果或业务日志。非 start 强制原 session_id，按步骤/提供器/录制 ID 核对归属；不支持独立步骤观察会话时明确报错，不暗中新建浏览器。
- 真实 spawn fixture 先证明接口缺失，再复现空闲监听停住：等待250ms后只推进1次。根因是 worker 主循环阻塞 connection.recv；改为事件循环内 asyncio.to_thread 等待，后台监听可推进，退出取消剩余任务并回收执行器。没有新增页面/数据库心跳或轮询。
- 未保存录制阻止开始/重跑/结束/删除/清理；实例池清理原先绕过子协调器的保护，新增失败用例复现，再改为全部实例前置检查后关闭，失败不会先销毁录制。15项受影响录制/执行控制/恢复/目标/共享暂存测试通过。
- 共享 RecordingDraft 读取后暂存、提交后确认；保存失败保留缓冲，确认失败不重复提交组，已删除录制项不得确认。末批预览只生成一次，避免分批读取反复截图；新增用例先失败（2次预览）后修复。
- 真实 Chromium + retained worker + 临时数据库链路通过：通过第二个 CDP 连接点击实际页面radio并填写密码，核对操作证据字段组和checked，密码未持久化；保存失败时库内没有组，重试后提交并确认；任务包导出/导入后标题、说明、默认关闭发送预览、items 和 views 完整保留。首跑本地CDP受到环境代理502影响，运行环境仅对localhost设置NO_PROXY后验证通过，没有改变用户配置。
- 路由/模块映射27项通过；新增浏览器往返测试登记为可选 browser_targets，没有运行全量或拼组全量。产品采集弹窗按钮、ESC/取消/恢复流程和独立步骤观察会话仍待完成，保留整轮目标进行中。

### 录制收尾边界补验

- 新增两个失败用例，复现保存回调返回 None 仍确认消费，以及已提交后确认失败仍可走丢弃。修复后未提交保留缓冲，已提交只可重试确认，不暗示丢弃能够撤销数据库内容；共享暂存6项与真实 Chromium/worker/任务包往返合计7项通过。
- 真实 spawn 复现录制后清空步骤 capabilities，stop 报 CONTEXT_PROVIDER_UNAVAILABLE，导致原缓冲无法收尾。协调器现在仅对已归属的录制收尾使用开始时能力快照，新 start 仍按当前步骤能力拒绝；快照随回执预算淘汰及 worker 关闭清理。相关录制/浏览器/执行控制/恢复/目标/共享暂存19项通过。
- 上述组合运行出现 Python 3.13 multiprocessing resource_tracker 重入清理警告；随后执行控制与恢复单独10项复验通过且未出现该警告。警告尚不能认定已经排除，后续生命周期验收继续观察；没有将其隐藏为干净验证。
- 非默认浏览器角色的选定 target 原先被错误限定到 operator。录制按实际目标资源选择角色，后续按录制ID查找原资源，已送达证据的页面关闭后仍可停止、读取及确认。快速关闭页面可能发生在浏览器 binding 送达之前，不能声称所有关闭前最后事件都可靠记录；需要在产品停止/保存流程完成 flush 后再结束实例。
- 最终真实录制提供器8项及 Chromium/worker/任务包往返1项，共9项通过；输出包含 asyncio 慢任务诊断和上游 Node url.parse 弃用警告，没有未取回的关闭异常。工程检查166篇 Markdown通过，git diff --check通过；采集弹窗与独立步骤观察仍未交付。

### 独立步骤观察会话

- 新增失败用例先复现独立 context.read 后 targets 为空，无法兼容持续录制。复用 ContextSessions 的线程事件循环、资源、串行观察及录制缓冲保护，增加步骤所有者描述；没有另起执行或增加轮询。Scope 使用真实任务/步骤身份，任务输入默认值可供插件配置，context.read 保持 items/views 兼容。
- 继续复现删除步骤可销毁待保存录制的所有者，修复为步骤/任务删除前检查全部相关会话，操作失败不先关闭资源。实例列表新增 step 类型与环境身份，工作台“结束实例”路由对应处理，环境删除按实际保留会话锁定；应用退出取消独立循环残留任务。
- 13项上下文/录制/运行目标针对性测试通过，包括独立快照→目标→录制、空闲监听推进、无运行记录、拒绝结束/删除、环境锁定、确认后结束。真实 Chromium 的独立观察与原保留 worker 两条链路共2项通过，均覆盖人工目标、密码遮蔽、保存失败重试及任务包 items/views 完整往返；输出有上游 Node url.parse 弃用警告。
- 相关应用装配、上下文持久化/元数据、Workbench及环境回归初跑43项，42项通过，1项旧 Workbench.__new__ 测试未装配已拆出的 StepContextPanel；按当前组件装配补齐测试 fixture，Workbench18项复验通过。未用生产兼容分支遮蔽错误，也没有运行全量。
- 最终上述相关43项复跑全部通过，工程检查166篇 Markdown与 git diff --check通过。
- 采集弹窗录制入口、关闭/重新打开草稿、共享控制条及最终真实 UI 验收仍待完成；本节只关闭独立观察后端缺口。

### 共享录制界面与重载修复

- 规划和步骤已接入同一 RecordingControls，保留原快照按钮、预览与默认关闭的发送预览；开始/暂停/继续/停止暂存/明确丢弃采用同一忙状态。录制期间冻结提供器、运行会话、目标和请求参数；持久化后才 ack，确认失败只重试确认。已有组未改字段但仍在录制时，确认保存不能走“无变化直接关闭”的旧分支。
- 实际 NiceGUI + Chromium 首轮没有到录制接口，排查发现临时验收 Controller 的 operation 形参和录制命令冲突，修正验收工具，未用生产兼容分支掩盖。随后实际页面重载复现新客户端打开旧弹窗而无界面；新增失败用例后改为重新装配控件、保留字段和录制身份、暂停活动录制，并拒绝在途重绑及旧 hide 写新草稿。
- 带参数的步骤采集器继续复现 copy 被条件内 import 遮蔽，导致关闭/重载捕获表单时 NameError；把 fixture 从空参数扩为真实非空表单，先失败，再移除局部 import 后通过。
- 真实规划与独立步骤两条 UI 流程均执行实际 radio 与密码输入、重载暂停并恢复原中文标题、停止暂存、注入保存失败再重试。失败时库内0组、录制仍待确认，重试后各1组且工作区缓存清除；两端发送预览默认不勾选。规划另有 ESC→重开→继续流程实测。步骤四宽1024/1280/1440/1920无横向溢出，截图 recording-step-*.png；规划四宽 recording-plan-*.png，查看1280步骤和1440规划图，保留纵向滚动及独立采集项预览入口。截图位于 output/playwright/next-repair。
- 最终本次共享录制/规划UI/Workbench/上下文卡片与元数据共72项定向测试通过，包含保存失败、确认失败不重复提交、旧客户端重载和在途重绑拒绝。没有运行全量或拼组全量。浏览器出现 NiceGUI 动态监听重渲染警告、CDP出现上游 Node url.parse 弃用提示；不能称为零警告。
- 真实步骤界面追加明确丢弃→取消：未新增保存组，工作区缓存清除。服务仍运行时显式释放观察会话返回 closed=true，再停止临时服务，没有 Browser.close 释放异常；不能据此替代原生正常退出验收。此前直接使用 Ctrl-C 停止时曾触发 driver 先断开的 Browser.close 异常，该观察保留；后续审计仍包含原生关闭。
- 全页面长请求/原生断连、剩余 Playwright 交互/文件/读取断言族及最终逐项验收仍待完成；本节不撤销整轮目标，也不标整体完成。

### 通用交互、读取与状态断言

- 按已确认的能力族设计增加9个动作：hover、double_click、scroll、drag、state、assert_state、attribute、list、table。仍复用旧CSS/结构化/within/nth/frame解析和显式target_id；交互WRITE且retry_safe=false，读取READ。代码限于Playwright插件，不向核心增加浏览器依赖，不改SDK/存储/任务包。
- 真实Chromium先验证缺失能力失败，再实施。覆盖iframe内范围hover/双击、真实HTML拖放、源/目标多匹配拒绝、相对滚动、跨frame拖拽明确拒绝、隐藏/禁用/只读/缺失/多命中、延迟状态断言、过期页面目标，以及声明输入/输出schema与读写效果。scope读取仍不导航主页面或自动换页。
- 读取在浏览器内限制字节、项数/行列与单项文字后才传回；table保留header和span、不展开跨行跨列、不混入嵌套表格，支持ARIAgrid与iframe。大中文表格（60行×5列×1024字）验证显式truncated及整体JSON小于128KiB。数量仅当前DOM及可见性范围，不承诺虚拟化或远端全表。
- 初版测试以600万中文字符表格触发既有target_state的2秒预检超时，并伴随浏览器关闭后的未消费future警告。排查发现集合读取仍走点击的可见/可编辑预检；新读取改为仅查匹配数量，状态读取/断言自己处理目标状态，保留旧交互预检。最终采用上述可复核代表性表格验证返回预算，不将结果扩大为任意大DOM性能保证。
- 追加textarea根选择用例发现初版text过滤只排除子级表单控件，会读取根textarea初始值；先失败后修正为根与子级均跳过表单值、脚本和样式，最终12项真实浏览器用例全部通过。属性仅允许声明列表及aria-*，不提供value/data-*/事件处理器，不自动读取敏感业务数据。
- 本次组合命令 tests.test_playwright_actions、tests.test_plugin_contract、tests.test_context_targets_playwright、tests.test_module_selection 共54项通过；追加上述textarea防泄漏后12项真实Chromium复验通过。旧scope的13项也在本次23项浏览器组合中通过。没有运行全量或拼组全量，新增浏览器测试已映射到plugins.playwright可选browser_targets。
- `uv build plugins/playwright --no-build-logs --out-dir /private/tmp/taskweave-playwright-actions-build` 成功生成0.4.0的sdist和wheel；逐字节核对两包中的actions.py与最终源码一致，并从wheel导入确认9个新增能力均存在（当前共31动作）。最初使用workspace package参数提示该插件不是uv workspace成员，改用独立插件目录构建，未改依赖或使用pip。工程检查166篇Markdown与git diff --check通过。
- 上传、原生dialog、录制能力配置变更/迟到/取消边界与完整复杂页面验收，以及全页面长AI/原生断连审计仍待继续。顶部实时日志入口源代码仍在，本次没有将用户原生窗口的缺失现象标为已修复。

### 上传与原生弹窗能力

- 新增page_upload/page_dialog至Playwright可选包，WRITE且不可自动重试；仍共用页面身份、定位范围、frame和timeout，SDK v1/核心依赖/存储/任务包不变。上传使用显式文件名/MIME/Base64内存数据，整批先校验，支持隐藏input、动态chooser、多文件及明确清除；原生弹窗按类型、完整提示与有序响应处理，不长期自动接受。
- 真实浏览器先复现能力缺失，实施后继续发现expect_filechooser在外层取消时保留监听器，改用本次动作拥有的监听与finally清理。又复现响应中途取消仍留下阻塞confirm，改为仅已完成响应才移除待关闭身份，取消时明确dismiss。多文件选择事件与click响应有时分属协议回调，renderer往返核对同次触发的全部文件框，多目标报错、不任选第一个。
- 本次最终命令tests.test_playwright_files_dialogs、tests.test_playwright_actions、tests.test_playwright_scope、tests.test_plugin_contract、tests.test_file_plugin、tests.test_module_selection，共77项定向测试通过（112.566秒），不是全量或拼组全量。包含18项上传/弹窗与真实worker用例，覆盖隐藏iframe、动态选择、多文件/空文件/清除、9MiB总量拒绝、超时/取消、键盘/双击、有序/额外/错提示弹窗、beforeunload真实跳转。
- 真实Application→spawn worker→file.read→步骤data绑定→默认BrowserSession→page_upload/page_dialog链路通过：页面读取完整中文文件与原文一致，确认框响应后实际页面结果为true。使用临时文件、临时数据库和localhost页面，无用户数据或外部服务。
- 组合验证前的一次17项运行出现未取回的Playwright协议future超时警告；最终77项日志没有再次出现，不能据此认定所有取消时序已排除。上述限制已记录在插件说明，生命周期审计继续保留。
- uv build plugins/playwright成功生成0.4.0的wheel/sdist，逐字节核对side_effects.py与源码一致，从wheel导入确认目前33动作。编写贡献与插件/文件使用说明同步了参数、限制、步骤绑定方式及业务结果核对要求。
- 顶部日志入口另用正式launcher临时浏览器验收：1024/1280/1440/1920宽度按钮可见且在视口内，实际点击打开/logs并出现服务实时日志标题。它不证明用户原生窗口中的入口缺失已解决。

### 历史详情日志按需加载

- 当前用户继续追问实时日志按钮：顶部独立服务日志及执行/调试的增量实时日志入口均保留，没有以性能优化为由取消日志。此前正式launcher四宽验证可证明当前浏览器源码入口可见；用户原生窗口的缺失现象仍未复现。
- 排查发现另一条旧路径：HistoryPage打开记录时先等待run.events全量读取，再创建整份代码高亮，弹窗因此需要等待日志。真实本地调试/正式执行测试增加“打开不读日志”断言后先失败，再改为显式点击“查看 / 刷新日志”。
- 与执行详情共用纯文本分页，每页24000字符，翻页及复制保留全文；JSON格式化在线程执行。重复点击不重复请求，关闭/切换视图后丢弃迟到显示，失败可重试。旧服务日志按钮名称的浏览器断言同步为“实时日志”；本次没有重跑该完整工作台端到端用例。
- 历史/实时日志/执行详情22项、步骤调试与映射35项定向测试通过，分别见`/private/tmp/taskweave-history-log-verification.log`和`/private/tmp/taskweave-history-consumer-verification.log`。新增测试覆盖长中文完整分页与复制、防重、关闭/导航迟到和失败重试；没有运行或拼组全量测试。
- 真实NiceGUI/Chromium临时验收：运行日志322112字符，人为延迟4秒；快速双击加载仅新增一次run.events，等待期间中文输入收到服务端回显耗时41ms，整个读取4446ms，页面加载计数保持1、URL未变。1024/1280/1440/1920截图位于`output/playwright/next-repair/history-logs-<宽度>.png`，已目视检查1024宽度。夹具`serve-history-logs.py`只操作临时工作空间，响应测试输入仅存在于夹具。
- 上述测量只证明慢历史日志请求期间该界面可响应；不代表外部AI长请求、原生断连或所有历史尝试元数据已验收。整轮其余范围继续保留。
- 映射补齐历史页面对共享日志组件的依赖后，最终五个受影响测试模块合跑57项通过（`/private/tmp/taskweave-history-final-verification.log`）；工程检查166份Markdown与源码/依赖边界通过，`git diff --check`通过。临时浏览器与服务已关闭，没有提交。
- 整轮尚需录制配置/迟到/取消与完整复杂页面验收、全页面长AI/原生断连审计，以及最终逐项验收，保持进行中。

### 长请求、逐页空闲和连接恢复证据

- 使用真实 Application、失败调试运行、HttpModel 和 NiceGUI/Chromium，模型仅连接本地临时 HTTP 提供器。35秒延迟期间连点API两次及Chat一次，实际只有一次 `step.generate` 和一次模型请求；中文步骤草稿编辑响应484ms。50ms事件循环采样691次，最大额外延迟88.08ms。等待期间模拟0.5秒断网，客户端重新连接，clientId、路由、草稿不变；loads=1、paints=1始终不变，候选最终正常展示后舍弃，没有采纳到业务步骤。另测网页Chat连点两次，只产生一个导出请求和一个回复弹窗，未调用模型。
- 盘点源码仅有执行列表、步骤调试、显式开启的运行日志及独立服务日志的UI定时器；没有统一高频业务服务在线探测。执行器保护保持原行为。浏览器逐页导航并等待加载完成后，工作台、规划、任务、插件、集市、环境、设置各观察4秒，均无新增查询/加载/整体重绘；执行页观察11秒只有两次 `run.list`，无日志/详情重读或重绘。这是临时非空任务/失败调试数据的空闲场景，不能推断任意数据量与所有操作成本。
- 逐页检查复现空环境页没有任何表单也提示未保存。原因是空表单基线为None、当前值为 `('', ())`。初始化为空基线后，未编辑空页面可正常离开；真实组件失败用例先失败后通过，环境与导航19项通过，重启临时浏览器再次完整导航到设置没有误报。
- 对安装中的NiceGUI重载分支及客户端回收做源码核查：disconnect先显示提示，握手失效/连接超时及try_reconnect才重载；默认客户端断开3秒后清理。真实模拟4.5秒断网，console记录 `reloading because implicit handshake failed`，loads从1变2、clientId变化，当前设置路由仍保留。这证明一条会话过期重载路径，未改连接超时，也未替换框架脚本；不代表原生窗口的原始跳首页触发链已完全复现，长断网后的所有未持久化表单恢复也没有验收。
- 证据保存于 `output/playwright/next-repair/slow-ai-35-evidence.log`、`all-pages-idle-evidence.log`、`expired-reconnect-evidence.log`；临时夹具 `serve-slow-ai.py` 不访问外部模型或用户数据。

### 录制能力变更收尾及服务日志停止条件

- 步骤移除原插件能力后重开录制弹窗，原先在查找当前提供器时直接报无可用上下文，导致旧录制无法通过原入口收尾。现在原录制的提供器/观察会话保留，停止与丢弃仍可用；新快照和新录制按当前能力限制。保存失败不确认消费，恢复能力后可重试；丢弃后不再开放已移除插件的录制入口。真实 Application + NiceGUI用例覆盖重开、暂停身份、停止、失败保存保留和丢弃；UI/协议/会话16项通过。
- 独立服务日志原本无隐藏停止条件，窗口隐藏仍每半秒扫描内存增量。现在暂停或隐藏时停定时器，恢复从原游标补读，后台日志文件仍写入。日志/模型/调试30项通过。真实浏览器点击暂停后1500ms读数不变；本机浏览器换标签没有产生document.hidden，所以隐藏验收通过模拟标准visibilitychange信号完成：前端事件传到后端后1500ms读数不变，恢复继续读取。该证据不冒称实际原生窗口隐藏验证。
- 完整复杂页面补验使用独立步骤会话、真实worker/Chromium：多个同名“否”的字段组、日期“今天”与body下option的实际唯一选择器、iframe操作、新标签页及跳转的新基线，一次录制保留全部证据。密码遮蔽、截图预览默认关闭、开启发送预览后任务包保留、注入保存失败再重试、导入后items/views完全一致一起核对。与上下文元数据12项通过，未执行全量或拼组全量。
- 首次CDP连接受到本机HTTP代理影响报502，设置本次测试进程的 `NO_PROXY=127.0.0.1,localhost` 后正常；没有修改用户代理配置。相关浏览器测试仍输出上游Node `url.parse()`弃用警告，不将其称为无警告输出。
- 本节关闭上述具体缺口；原生窗口实时日志缺失/原始跳首页现象、长断网草稿恢复范围、较早Playwright取消future警告，以及最终全清单审计仍保留，整轮未标完成。

### 当前逐项审计（不作整轮完成结论）

| 原始要求 | 当前源码/本轮证据 | 尚不能据此证明的范围 |
| --- | --- | --- |
| 复核其他AI的弹窗修改 | 本文“既有弹窗改动审查”及真实backdrop事件记录；关闭策略不能修复自动重建，保留策略并改生命周期 | 不将点击穿透假设写成已确认根因 |
| 暂缓、A/B切回、新请求、草稿、防重与迟到 | RunInputDialog仅在显式按钮中调用_open；request_key含运行和补参ID，run.inputs核对expected_input_id；临时实际A/B及草稿/重复提交截图和组件证据 | 仍需最终按当前主树核对所有失败路径的证据关联 |
| 全页面查询/重绘、慢请求与断连 | 八主页面空闲查询计数、35秒真实HTTP模型、4秒长日志、本轮定时器盘点；短断连保持客户端；4.5秒断连握手失败重载路径实测 | 用户原生窗口原始现象、长断网后全部未保存表单恢复没有验收 |
| 首次显示无闪现、懒构建 | 规划8组长中文/2秒响应的真实交互与四宽图；步骤调试首次构建和可见状态源代码/测试 | 不推断全部弹窗及任意数据量首屏成本 |
| 并列配置/调试/日志、显式保存 | StepEditor并列容器；无保存定时器，顶部保存步骤，底部仅校验内容/确认验证；本轮四宽截图、失败/离页/版本保护用例 | 全部原生窗口尺寸未逐一验证 |
| 复杂页面定位与状态证据 | 共用within/nth/frame/目标ID，候选经实际locator验证；本轮真实radio/ARIA/日期/option/iframe测试；新完整录制链路 | 虚拟化未加载、closed shadow DOM等限制明确保留 |
| 可选录制、敏感值、边界、保存与旧快照/预览/任务包 | SDK可选协议、独立及保留worker会话；真实规划/步骤UI重载/ESC/失败重试、能力移除收尾用例；复杂页面保存与任务包往返 | 本次专项已修复并验证已复现的协议取消/导航归属路径；不保证任意取消时序或跨进程重启保存缓冲 |
| file→步骤绑定→TiDB执行SQL | 可选插件和动作契约；真实worker/PyMySQL本地协议链路，事务/部分/未知效果失败测试；旧query保留 | 没有实际TiDB账号，未将协议fixture当作真实SQL语义验证；Windows构建未验证 |
| 顶部服务日志及调试/执行实时日志入口 | launcher绑定open_logs、顶部入口、共享LiveRunLogs默认关闭；官方浏览器四宽及实际打开记录保留；增量/分页/完整复制/停止条件用例；用户随后确认“顶部找到了”，本次正式启动器浏览器入口也已点击验证 | 入口疑问已关闭；不将浏览器弹窗等同于全部原生窗口平台验收 |

本次新增验证：录制边界16项、日志/模型/调试30项、空环境/导航19项、复杂录制与元数据12项均成功；工程检查166篇Markdown和git diff --check通过。各组是受影响范围的定向运行，不能累计成全量通过。临时浏览器验收独立于用户数据，没有提交。

### 步骤草稿断连恢复与授权跳转路由

- 真实Chromium先复现4.5秒断网后客户端过期重载，步骤补充说明变为空。现在仅在disconnect捕获一次原始步骤字段、代码、参数定义与输入绑定，存于同一服务的标签页内存缓存；运行补参草稿按原运行/请求身份保留。没有增加定时扫描、自动保存或写用户数据库。
- 恢复保留原始保存基线和expected_hash；不完整的JSON、空绑定名也原样恢复，不能为了恢复绕过校验。并发修改仍报EDIT_CONFLICT；已保存、干净或显式放弃的步骤不缓存。复制标签页后深层缓存相互隔离。实际NiceGUI ObservableDict会复制赋入的普通字典，启动器绑定其实际存储映射，避免首次直达步骤时缓存引用失效。
- 正式launch入口以临时Application和临时数据库验证：首次带凭据直达步骤并展开调试，填写中文名称、20行说明、代码和无效number默认值；4.5秒断网后clientId变化、URL不变，全部原始值恢复且数据库仍未改变。修正默认值后点击顶部保存，数据库才更新。前端可见性监听仍在；点击顶部实时日志成功打开“服务实时日志”。证据为`output/playwright/next-repair/recovery-official-evidence.log`，只有临时数据。
- 同时发现LocalAccess授权原先重定向到裸路径，删除全部查询参数，实际首次带access和步骤路由会落到工作台。现仅删除access，保留其余视图/任务/步骤/debug及空值参数；目标仍为本站相对路径，原Host/Origin/Token/Cookie/WebSocket校验保留。这是实际证实的一条跳首页路径，不能认定就是用户原生窗口此前所有跳转的唯一触发原因。
- 安全路由、步骤状态、导航、补参、步骤保存、模型日志和测试映射共88项定向测试通过（14.419秒），见`output/playwright/next-repair/recovery-routing-verification.log`。新增失败用例覆盖原始草稿、已保存/放弃不缓存、版本冲突、未完成绑定、补参草稿和标签隔离；未运行全量或拼组全量。
- 该缓存不保证服务重启、关闭标签页或框架缓存过期后的恢复；规划/环境表单、调试运行输入和AI弹窗尚未纳入长断网恢复。未提高NiceGUI连接超时或替换重载脚本，整轮目标仍保持进行中。
- 更新记录后工程检查通过（166篇Markdown、源码语法及依赖边界），git diff --check通过。临时浏览器已关闭，两个临时服务以Ctrl-C停止；中断退出包含KeyboardInterrupt堆栈，不将其当作正常原生退出验收。没有提交或改动用户数据。

### 2026-10-01：调试原始状态及跨客户端AI防重

- 调试区原来已有读取最近运行的逻辑；缺口是重载后未必保留该标签原先明确选中的运行，其他窗口新运行可能替代它，运行输入、AI说明及移除反馈也丢失。现在disconnect时一次捕获这些状态，重新构建时先填原始值，不做周期保存。真实Application/NiceGUI组件用两个冻结失败运行验证原选记录、未完成JSON、中文说明及移除项恢复，期间没有启动worker、没有新增尝试。这是UI恢复验收，不把预置记录称为真实执行成功。
- 真实浏览器先复现：35秒本地HTTP模型请求期间断网4.5秒，旧客户端过期后新页面再次点击修复，实际发出第二次模型请求，见`output/playwright/next-repair/retained-ai-browser-red.log`。原页面按钮锁只覆盖同一客户端，不能覆盖会话重载。
- DesktopController现按步骤保留在途生成/描述/修复任务，UI等待取消不取消已发出的模型操作；新客户端同一步骤防重继续有效。最多保留16个步骤的最新请求，容量满时只回收已完成项。在步骤配置中提供“查看上次 AI 结果”，显式等待或查看原API候选/网页Chat导出，不重复生成、不自动写库或执行。旧客户端删除时使页面代次失效，迟到响应不能在已删除客户端创建弹窗。恢复及采纳复核原请求、步骤版本、当前代码及修复运行/尝试编号；新尝试或编辑冲突拒绝旧候选。
- 最终浏览器验收使用真实Application、HttpModel、NiceGUI和Chromium，模型连接独立临时本地HTTP提供器。35秒期间断网4.5秒触发框架握手失败重载；clientId变化，路由、原尝试及中文补充说明保留。重载后连续点击修复、内容生成、描述生成均没有追加调用，step.generate=1、模型请求=1，显式查看最终候选并舍弃。loads=2、paints=2对应首次加载及实际重载，没有等待期间整体重绘。50ms循环采样665次，最大额外延迟106.5ms；该数值只说明本次本机运行，不代表所有机器或原生窗口性能。
- 随后网页Chat描述生成暴露独立缺口：重载的默认环境为`''`，原描述请求未转换为None，后端将其作为环境编号查询而报NOT_FOUND。真实浏览器和真实Application失败用例均复现后，UI请求统一使用无环境None。再次验收网页Chat生成描述、关闭及重载后显式恢复，提示词完全一致，step.generate_goal=1且没有追加模型请求。最终只读临时数据库核对原代码和DRAFT状态未改变。证据为`retained-ai-complete-browser.log`及`retained-ai-complete-evidence.json`，同在上述输出目录。
- 最终受影响步骤AI、编辑状态、导航、调试输入/会话、步骤保存、模型日志及测试映射102项定向测试通过（32.683秒），见`retained-ai-final-tests.log`；取消等待后的真实模型仍完成且只调用一次，旧版本/旧尝试恢复和采纳被拒绝均有用例。未运行全量或拼组全量，没有外部模型调用或用户数据修改。
- 请求缓存及标签页草稿仍只在同一服务内存中，不保证重启、关闭标签页或缓存过期后的恢复；未提交的AI弹窗输入、规划/环境表单还未纳入恢复。未改NiceGUI连接超时或重载脚本，未声称完整复现用户原生窗口此前所有跳首页触发，整轮目标保持进行中。
- 工程检查通过（166篇Markdown、源码语法及依赖边界），git diff --check通过。临时浏览器已关闭，最后临时服务Ctrl-C退出码130，未将该中断退出称为原生窗口正常退出验收。没有提交。


### 2026-10-01：Playwright取消协议回复与iframe句柄

- 复现了当前源码中的未取回协议Future，而不是将此前偶发警告猜成已解决：遮挡文件选择按钮时外层超时取消Python等待，浏览器点击随后才返回TimeoutError；定位预检、快照和列表预算超时后关闭浏览器会留下TargetClosedError。失败日志分别为`playwright-cancel-red.log`、`playwright-preflight-red.log`、`playwright-read-reply-red.log`，保存于`output/playwright/next-repair/`。
- 新增插件内部protocol.reply，只保留已发的单次协议调用并接收异常，外层调用仍立即收到取消/超时；后续步骤不继续，不做自动重试、不屏蔽全局异常、不修改第三方Playwright源码。专门的失败用例发现简单shield会在取消先入队时仍发送点击，现核对调用方取消计数后才发命令，该用例先失败后通过。
- 上传与弹窗流程、定位预检、快照和集合读取接入同一回复归属。包含真实Chromium及原生弹窗的85项定向回归通过（117.711秒）；未出现未取回Future/Task异常，仍有asyncio慢任务诊断，不能称为无警告。真实worker录制和旧浏览器消费者另行复验，结果待下条记录。
- 另外实际连接对象计数证明iframe路径检查未释放元素句柄：8次检查遗留8个句柄。现在使用finally释放，单项失败用例先失败后通过；此证据针对临时句柄，不是浏览器全部资源泄漏审计。
- Playwright wheel/sdist构建成功，protocol.py、side_effects.py、observation.py、actions.py和__init__.py均逐字节与当前源码核对一致。不修改SDK/核心/存储接口，旧动作参数与不可自动重试边界保留。
- 以上关闭已复现的具体取消时序，不把它推断为任意原生窗口、服务重启或所有取消路径的保证。整轮完整验收继续，未自动提交或改用户数据。


### 2026-10-01：快速导航的录制文档身份

- worker录制复验首次3项均停在CDP localhost连接read ETIMEDOUT；仅本次测试进程设置NO_PROXY后，独立/保留会话两项通过，复杂页面出现真实断言失败：没有/next基线。没有修改用户代理配置。
- 不通过固定sleep掩盖时序：失败用例刻意延迟snapshot，并在完成前导航，证明原实现把新文档DOM作为旧document_id的基线。第二个用例将旧元素token在新文档复用，证明后状态可能验证到新文档的另一元素。另发现about:blank等非安全上下文没有crypto.randomUUID，原初始化留下document_id=None；独立断言先失败后修复为getRandomValues兼容生成。
- 录制操作现在保留发生时的文档ID、无查询参数/凭据的URL和短标题；基线采集前后核对源frame文档ID，已跳转时写PAGE_DOCUMENT_CHANGED及原URL，不声称仍能抓到已销毁DOM。后状态同时核对文档ID，旧token即使在新文档复用也不作为原元素的定位证据。
- 原复杂页面测试改为核对/next操作与其同一文档的有效基线或明确缺失说明；仍要求/final实际基线、两个页面目标ID、全部字段组/今天/option/frame操作、密码遮蔽及任务包往返。额外两个确定性失败用例防止用“缺失”掩盖错误归属，不用通过测试替代用户页面完整覆盖保证。

- 最终录制及真实worker13项通过（33.999秒），定向映射消费者17项通过（5.606秒）。首次消费者组合37项中34项通过，3项CDP连接错误明确保留原日志；旁路localhost代理后的复验又发现导航断言失败，已保留该失败及最终通过日志，不把失败运行写成通过。最终日志仍有上游Node url.parse弃用警告，无未取回Future/Task异常。
- 本次另按当前RunInputDialog与原子请求身份核对12项补参用例，全部通过（1.411秒）：A/B切换/重建不重开，手动入口，旧请求拒绝，保存失败保留，慢重复提交只写/续启一次，迟到只作用原运行。本次为真实NiceGUI组件和Application定向测试，不新增浏览器点击证据；与本文此前真实A/B交互证据结合，来源范围明确。
- 最终重新构建Playwright wheel/sdist，6个插件Python文件全部与当前源码逐字节一致，包括本节recording.py。证据为`playwright-protocol-package-check.log`；全部测试原日志已保留。测试启动的浏览器、临时服务随各用例清理，未操作用户数据。
- 当前仍需补齐清单指定的打开调试、“更多”、起点弹窗及补参的独立延迟/重绘/请求测量，并将最终全清单证据逐条关联。已证明的框架会话过期及授权参数丢失路径不等于原生窗口此前全部触发链；不会仅因测试通过宣布整轮完成。

### 2026-10-01：指定交互响应与四宽复验

使用当前源码的真实 Application、NiceGUI 和 Chromium，夹具只创建临时数据库、10 个已确认长中文步骤和一个真实等待补参的暂停调试运行；不访问用户数据。记录实际 controller 调用、50ms 事件循环采样、整体 paint/页面加载计数，并比较步骤配置 DOM 节点是否仍为同一个。

| 操作 | 点击至可见耗时 | 实际读取 | 最大额外循环延迟 | 整页加载/重绘增量 |
| --- | --- | --- | --- | --- |
| 配置“更多” | 173ms | 无 | 2.029ms | 0 / 0 |
| 首次展开调试 | 394ms | 6 次环境/任务/运行/请求/步骤读取 | 22.349ms | 0 / 0 |
| 从选定步骤起点弹窗 | 457ms | step.get、environment.list、step.list 各一次 | 14.592ms | 0 / 0 |
| 补充必录参数弹窗 | 542ms | run.request、run.input_values、environment.list 各一次 | 13.301ms | 0 / 0 |
| 收起后再次展开调试 | 145ms | run.get 一次 | 0.894ms | 0 / 0 |

这些操作的配置 DOM 均未被重建；取消起点弹窗、输入中文草稿后稍后填写均未开始执行，实际运行保持 PAUSED、attempt_count=0。计数基线 loads=3、paints=3 包含此前夹具调试中的重新加载；表格只报告各测量窗口的增量，不伪称整个会话只加载一次。

另将夹具补参读取故意延迟 2 秒，真实双击入口，等待期间打开“更多”：菜单 110ms 可见，实际 run.request 仅一次、弹窗仅一个、原始中文草稿恢复；整个弹窗读取 2580ms、最大额外循环延迟 2.453ms，加载/重绘计数未变，运行仍暂停。该延迟只在夹具中，不在产品里加入等待或改变业务请求。

- 证据：`output/playwright/next-repair/interaction-metrics.json`、`interaction-metrics-browser.log`、`interaction-layout.json`、`interaction-layout-browser.log`；夹具为 `serve-interaction-metrics.py`，浏览器动作记录为 `measure-interactions.js`。
- 1024/1280/1440/1920 宽度截图为上述目录的 `interaction-debug-top-<宽度>.png`。重置主页面及调试区滚动后截图，目视核对 1024 和 1440：配置、调试并列；日志位于调试下方独立容器。1024 下配置操作栏正常换行，调试保持在右侧，没有落入配置容器或页面横向溢出。截图使用非空输入和长中文，不是空页验收。
- 夹具没有顶部 open_logs 回调，因此这组截图不重复证明顶部服务日志；其证据仍为正式启动器的 `recovery-official-evidence.log` 与用户“顶部找到了”的反馈。
- 当前文件/SQL/定位源码再核对 33 项定向测试，全部通过（36.429秒），包含真实 worker 的文件→步骤绑定→PyMySQL 协议链路和真实 Chromium 范围/状态/候选定位器，见 `file-sql-scope-audit.log`。未连接实际 TiDB，未运行全量。
- 本次浏览器已关闭，临时 UI 服务 Ctrl-C 停止、退出码130；这是中断清理，不是原生桌面正常退出验收。

### 2026-10-01：要求与当前证据逐项关联

以下按原始清单核对，不把“实现存在”或测试总数当作完整证明。路径省略前缀时：组件位于 `src/taskweave/desktop/components/`，浏览器/测试原始日志位于 `output/playwright/next-repair/`。`current-evidence-index.json` 记录本次核对的24个源码文件与80个证据文件的哈希，仅用于识别证据对应版本，不是功能验证器。

| 要求/不变量 | 当前源码与针对性证明 | 审计结论 |
| --- | --- | --- |
| 其他 AI 的点外/ESC 改动是否解决重弹 | `run_inputs.show` 原刷新重建路径与本文 backdrop 真实事件记录；关闭策略保留，自动打开源另行修复 | 已核对；“点击穿透”归因不成立 |
| 稍后填写、暂停执行 A→B→A，不主动运行/重弹 | `run_inputs.py` 只注册手动入口；真实 A/B 图 `input-draft-restored.png`，当前 `next-repair-p0-audit.log` | 已证明；补参读取等待期间此次仍 PAUSED、无尝试 |
| 后续新请求不被旧暂缓屏蔽 | `state.request_key` 包含 run/request/scope/step；手动入口重新读取，提交用 expected_input_id；`test_stale_input_request_cannot_resume_replacement_request` | 已证明，旧窗口不能提交到替换请求 |
| 草稿、失败保留、防重、迟到归属 | `RunInputDialog._open/_submit`；`test_submit_failure_retains_draft_and_displays_error`、`test_slow_double_submit_writes_and_resumes_only_once`、`test_run_input_write_finishes_original_run_after_page_changes`；本次慢双击交互 | 已证明，迟到完成原授权运行，不污染新页面 |
| 逐页查询盘点、空闲成本 | `all-pages-idle-evidence.log`：八主页面非空场景；源码定时器仅执行/调试/显式日志，执行 idle 5s/running 1s 轻量列表 | 已证明本机场景；空闲执行仍需发现其他窗口新运行，未宣称完全零查询 |
| 隐藏/终态/重叠/无变化不重绘 | `ExecutionDetails.poll`、`StepDebugPanel`、`LiveRunLogs.poll`、`server_logs` 可见性事件；`next-repair-p0-audit.log`、`log-visibility-verification.log`、`log-visibility-signal.log` | 已证明组件停止条件；原生隐藏信号未做实机验收 |
| 更多/打开调试/起点/补参响应 | 当前实际交互表、`interaction-metrics.json`，配置 DOM 保留，加载/paint 增量均0 | 已证明本机10步骤/长中文场景 |
| AI/日志长请求不阻塞界面、防重 | `DesktopController.call/execution_inputs/run_request` 在线程调用业务；`slow-ai-35-evidence.log`、`retained-ai-complete-evidence.json`、`history-final-verification.log`，35秒模型及4秒32万字符日志期间仍响应 | 已证明本地真实请求场景，不推断任意外部服务耗时 |
| 连接心跳/执行器保护/状态查询区分 | 现行 UI 无额外服务探活；NiceGUI 连接保留，worker/协调器失联保护仍存在；业务查询停止条件见上述源码 | 已核对，未取消执行器保护或调整超时掩盖问题 |
| 短断连、握手失效、重载路由/步骤状态 | 0.5秒断网不重载；4.5秒实际会话过期重载；`security.LocalAccess` 保留路由，`Workbench.capture_reload_state` disconnect一次捕获，`recovery-official-evidence.log`/`retained-ai-final-tests.log` | 已证明这些路径；原生原始完整触发链未证明，用户认可按本轮无法复现关闭 |
| 首屏规划页签/调试从创建即隐藏、懒加载 | `desktop/planning.py` 首开素材/历史，身份失效后不发布；`step_editor.py` 隐藏空调试容器，首次展开才构建；慢响应规划交互及四宽 `planning-lazy-materials-*.png` | 已证明；隐藏时无提前构建重内容 |
| 配置/调试/日志独立、只刷新受影响输入 | `StepEditor` 三容器、`snapshot_debug_inputs`/输入同步；`test_debug_is_sibling_and_reopens_without_rebuilding_inputs_or_writing_draft`；本次四宽及 DOM 保留 | 已证明；日志跟随调试开合 |
| 无步骤自动保存/全表单高频扫描、顶部保存/底部文案 | `mark_dirty` 编辑事件；顶部“保存步骤”，底部仅“校验内容”“确认验证”；`test_step_editor_is_manual_and_builds_debug_only_on_open` | 已证明；其他页面没有一刀切取消保存 |
| 离页保存/放弃/取消、保存失败与版本证据 | `step_editor`/Workbench 导航保护；`test_step_editor_manual_save_failure_keeps_dirty_draft`、`test_reload_restores_raw_step_draft_without_saving_or_relaxing_conflicts`；AI恢复/采纳复核 content_hash 和 run/attempt | 已证明；旧成功不能确认新代码，未保存操作有保存边界 |
| within/nth/frame/旧定位器兼容 | Playwright共用解析器；本次 `file-sql-scope-audit.log`，同名“否”只影响字段组、旧CSS/语义/frame、nth实际顺序/计数 | 已证明；不猜索引或自动换目标 |
| radio/checkbox/ARIA状态和断言 | `page_check/checked/assert_checked`，本次原生/ARIA/mixed实际浏览器用例 | 已证明，mixed不伪称已选中 |
| 局部DOM/祖先/字段组/截断、唯一可执行备选 | `observation.py`，`test_snapshot_fallback_is_executable_for_today_and_ambiguous_labels`、`test_unique_semantic_match_must_be_the_observed_element`；本次范围用例及 `recording-navigation-final.log` | 已证明；不能定位时明确缺失，未加载/closed shadow等限制保留 |
| 日期“今天”/body浮层/iframe/新页面与目标归属 | `test_complex_page_recording_live_selectors_preview_and_package_roundtrip`；真实worker/Chromium及导航文档归属修复，`recording-navigation-final.log` | 已证明采集覆盖和执行定位；已销毁文档不伪造基线 |
| 可选通用插件协议、核心不处理DOM、旧提供器兼容 | `core/context_recording.py`、SDK可选协议、`ContextSessions.record`、worker通道；浏览器实现仅在插件；映射消费者日志及边界16项 | 已证明，固定执行不调用模型或自动回放 |
| 手动开启/暂停/停止/游标/确认/丢弃、释放资源 | `ContextRecordingControls`/`RecordingDraft`、上下文会话与worker；`recording-boundary-verification.log`、`recording-capabilities-tests.log`、`recording-navigation-final.log` | 已证明未保存保护、移除能力收尾、保存后确认及停止监听 |
| 真实目标/字段组/前后状态/页面基线/预览 | 插件 `recording.py` 可信事件、文档ID与有界基线，旧截图renderer；复杂录制实际点击、密码遮蔽、真实唯一选择器 | 已证明；新页首操作基线不是操作前快照，缺失理由明确 |
| 敏感输入不持久化、输入合并和大记录量有界 | 浏览器端敏感遮蔽；1000事件/2MB缓冲、100条有界读取、128KiB单项与可选图片限制；录制边界/真实worker任务包用例 | 已证明所定义边界；不声称识别所有业务敏感字段 |
| 规划/步骤UI、快照并存、标题说明/发送预览、任务包 | 共用控制条，默认不发送额外预览；真实规划/步骤图 `recording-plan/step-*.png`，旧快照及任务包往返实际证据；保存失败不ack、ack失败不重复写组 | 已证明兼容链路，未增加自动回放/业务提交 |
| TiDB旧只读与新增WRITE/不可自动重试 | `tidb.query`保留；`execution.py`单条/脚本/参数/事务，`file-sql-scope-audit.log` | 已证明动作契约及事务/部分/未知效果处理；非实际TiDB服务验收 |
| 文件路径/编码/完整读取→返回data→绑定→SQL | `file.read`可选插件，root/符号链接/1MB/格式检查；真实两个worker与PyMySQL协议链路观察BEGIN→两语句→COMMIT，结果已持久化 | 已证明，不通过插件间直接调用或用户数据运行 |
| Playwright统一能力规划、方法/参数/限制文档 | 插件 actions/spec 共用定位底层，README按定位/观察/交互/状态/集合/文件/dialog/录制说明；6个wheel/sdist文件字节核对日志 | 已核对当前实现，不宣称任意页面都能自动编写 |
| 顶部实时日志、显式增量、完整分页复制与停止 | 正式launcher入口实测及用户确认；共享 `LiveRunLogs` 默认关闭、100条游标/24000字符摘要，完整日志显式分页/复制；历史57项和日志30项记录 | 已证明，未取消实时日志功能 |

**当时未关闭的要求（已由末节用户验收口径更新）**：用户原生桌面窗口此前“打开调试/长AI等待→断连→重载→跳首页”的完整原始触发链，尚无该环境的连续观测证据。当前已实际证实并修复授权重定向丢路由、过期客户端草稿丢失及跨客户端重复模型请求，并消除本地慢请求阻塞；不能把这些推断为原始现象的全部原因。因此性能项和全清单完成项仍不勾选，目标保持进行中。

**验证边界**：实际TiDB账号、Windows便携包、服务重启/关闭标签页后的恢复，以及全部规划/环境/未提交AI弹窗的长断网恢复未验收。它们不能由本地协议/浏览器结果推断；本轮没有取消运行保护、没有提高框架超时、没有全量或拼组全量测试、没有提交和用户数据修改。阶段性历史测试日志已归档，红灯运行仍保留，不将其记为通过。


### 2026-10-01：事件式连接诊断与现场验收边界

正式启动器补充有限的 `UI_LIFECYCLE` 事件日志，用同一标签页 UUID 关联旧/新客户端，区分短重连、客户端释放和页面恢复。仅连接/页面生命周期回调写入，不增加轮询、业务读取、定时全表单扫描、重绘或自动重试，也未调整框架断连超时。结构化诊断不包含业务对象标识、草稿、URL或异常正文；恢复失败记录类型及格式受限的公开错误码。原有服务异常日志行为未被删除，因此“诊断不含正文”不代表整份服务日志从不记录异常。

- 先运行真实 NiceGUI Client/ServerLogs 的失败测试：公开路由错误码缺失，`None != NOT_FOUND`；保留 `connection-trace-code-red.log`。最小补充错误码后，端口/安全/服务日志/导航35项定向测试通过，6.912秒，见 `connection-trace-code-green.log`。此前事件日志新增的红/绿过程为 `connection-trace-red.log` / `connection-trace-green.log`，不将红灯记为通过。
- 真实官方启动器、临时数据库与 Chromium 的断网证据见 `connection-trace-browser-evidence.log`：0.5秒断网后同一客户端重连，实测间隔581.5ms；4.5秒断网后旧客户端释放、新客户端在同一标签页恢复 editor，中文草稿保留，诊断未包含草稿内容。此结果证明受控断网路径，不能替代原生窗口的原始卡顿触发链。
- 错误码补充后的启动器另用刻意无效的临时任务路由验收：`requested_view=editor`、恢复失败 `TaskError/NOT_FOUND`、最终 `page_ready=home`；清理完成后4秒空闲新增诊断事件为0。见 `connection-trace-final-evidence.log`。这是预期失效对象回退，不是复现此前偶发跳首页。
- 首次浏览器脚本把旧客户端延迟释放误计为空闲日志，验收失败；原始文件 `connection-trace-final-first-failure.log` 及完整观察 `connection-trace-failed-observation.log` 保留。核对实际事件后，脚本等待旧客户端清理再开始空闲测量，产品代码未因该脚本失败改动。
- 页面创建/连接时 Workbench 仍可能显示初始 home 状态，应结合请求视图及 `page_ready`，不能把尚未恢复路由的初始外壳判为跳首页。断开回调可能来自其中一个 socket，释放也可能由多种生命周期路径导致，日志本身不伪称已判定原因。
- 两次自建临时服务均已 Ctrl-C 终止、退出码130，CLI浏览器已关闭；未操作用户进程或业务数据。这是测试资源清理，不证明原生正常退出。

**阶段性阻塞（已由末节关闭记录解除）**：当前工具不提供原生窗口控制，尚未收到此前现场验证问题的答复。事件诊断已经可用；需要加载本轮代码后的现场操作与连续日志，才能判断原始问题是否仍发生及原因。不能继续用新的浏览器夹具、重复通过的测试或附加重构代替这条证据。目标保持进行中，未标整体完成。源码与本次证据的版本见 `connection-trace-evidence-index.json`；上一节索引保留原快照意义。


### 2026-10-01：用户确认验收口径与本轮关闭

用户明确确认“无法复现说明已解决”。据此，原生窗口此前偶发断连/跳首页按本轮修复后已执行场景未复现的结果关闭；不再要求原始完整因果链作为本轮完成门槛，也不把这句话写成用户已经完成原生现场复测。保留事件式诊断，日后有新复现证据再排查。

最终核对原始七项范围和上述逐条审计：补参显式入口、草稿/身份/防重；八页查询及指定慢请求/交互；懒构建；独立配置/调试/日志与手动保存；Playwright统一能力；可选录制及旧快照/预览/任务包兼容；文件→步骤绑定→TiDB SQL及事务/副作用，均已有对应实现与本轮证据。性能项最后的原生完整触发链门槛由上述用户裁决关闭，未缩减其他要求。

关闭前只读复核24个产品源码与80个证据文件：80个证据未变，产品源码仅启动器在后续连接诊断中变更，已与诊断索引和35项定向验证对应；其他23个源码未变。重新查看补参12项、文件/SQL/定位33项、复杂录制13项、日志30项、历史57项、AI恢复102项的实际通过记录，以及八页空闲/指定交互/长AI的实际JSON结果，不将哈希或通过总数单独作为验收证明。

本次仅更新完成状态及验收裁决，不改功能代码、不重复功能回归；工程文档检查与差异空白检查结果随本次关闭记录保存。未运行全量、未提交/推送、未修改用户数据。实际TiDB服务、Windows实机、关闭标签/服务重启及全部表单长断网恢复仍属于已列明的验证边界，不新增跨平台/全场景保证。此前红灯及阶段性阻塞记录保留，不能读作当前仍待实现。
