# TaskWeave 三项优化实施清单（交接给 5.5）

> **For agentic workers:** 使用 superpowers:executing-plans 按本清单实施；如用户明确选择并行实施，再使用对应技能。复用既有用户决定，不重新讨论已敲定的字段和交互。复选框只有在实现并验证后才能勾选。

**Goal:** 提高 AI 生成可执行步骤的质量，新增多插件上下文驱动的计划转任务流程，并统一可配置的 AI 请求大小上限。

**Architecture:** 页面经 Controller 调用 application 用例。公共提示词和请求组装集中维护，插件贡献完整的自身规则与采集/展示能力。计划采集资源由 infrastructure 管理独立生命周期，不伪造任务执行记录，不给执行核心增加插件专用逻辑。

**Tech Stack:** 现有 Python/uv、NiceGUI、SQLite、插件注册器、模型适配器；不引入新的前端框架或 Agent 框架。

**Spec:** 必须先阅读 [完整规格与全部最终提示词](../specs/2026-09-23-ai-planning-design.md)。提示词正文以该文件第 2–3 节为准，不要求实施者再次自行设计措辞。

**工作目录:** `/Users/dasensen/PycharmProjects/taskweave`。调用任务的默认 cwd 可能是 smart_excel，不要因此修改错误项目。

**状态:** 仅完成代码核对与方案文档，以下产品改动全部待实施；本轮没有运行测试。

## Global Constraints

- 当前工作区已有大量前序未提交变更。先看 git status/diff，再基于当前文件继续；禁止 reset/覆盖这些变更，禁止把 main HEAD 当成本轮全部现状。
- 三项全部交付，不擅自只做优先部分。内部按依赖顺序执行即可。
- 用户最新纠正优先于任何旧聊天或文档：**AI 生成任务导入全部待确认；已有任务导出带各步骤状态，导入恢复各自状态。**
- `step_description` / `step_notes` / `repair_notes` 固定，不恢复 goal/ai_authoring_notes 等旧键。
- core 合并变量，AI 只收一份最终目录；不向模型解释环境/任务/步骤优先级。
- 所选插件规则和能力完整保留，页面上下文不自动压缩、不按动作筛规则；保留已有详细日志。
- 不重新加入页面语言切换限制。playwright_locale 的真实运行设置不因提示词修改而改变。
- 内容/描述无历史，修复历史 `-1/0/1–10` 与勾选去重保持；计划初次生成无历史。
- 请求预算默认 `512 * 1024` bytes，用户设置最高 `4096 * 1024` bytes；不是 token 数。
- 不建立新旧字段/任务格式兼容层。任务包升级为 taskweave-task-2；旧包提示重新导出。
- 全量测试必须先向用户确认。本轮按受影响模块运行，纯提示词文本和样式不增加逐字镜像测试。
- 产品新流程必须经服务入口；不把 SQL、浏览器资源管理和大段模型请求逻辑继续塞入 workbench.py。
- 不自动执行业务步骤、不自动采纳 AI 回复、不调用真实账号或数据库验证。

## Review Focus

1. 模型将“只填写/只识别”扩大为登录；插件公共规则必须服从当前步骤范围，不能通过删插件目录解决。
2. 模型给 AI 生成任务伪造 VALIDATED，或导出草稿被导入设绿；来源路径与每步状态必须同时校验。
3. 同一浏览器连续采集被关闭/重新导航，或计划误锁某任务；采集会话归属和环境一致性必须明确。
4. 中文、JSON 转义、工具 schema、历史或纠错追加让真实请求超过显示预算；使用最终发送 bytes 检查。
5. 网页任务 JSON 截断、缩进二次解码、重复导入或生成期间草稿改变；保留材料、显示错误/旧版本、不能导入半份或重复任务。

---

## A. 开工核对与文件责任

- [ ] 阅读 AGENTS.md 及其要求的项目文档，核对实际 schema 版本；不要凭文档中的旧状态重写当前实现。
- [ ] 记录本轮开始 git status，并检查下列入口。

| 文件 | 本轮职责 |
|---|---|
| src/taskweave/application/prompts.py | 按规格替换公共/描述/内容/修复/网页文本，新增计划文本 |
| src/taskweave/application/authoring.py | 公共请求组装、最终变量目录、显式 purpose、单步校验/修复 |
| src/taskweave/application/ai_requests.py（新增） | 共享请求材料、预算及网页文件组装，不按具体插件分支 |
| src/taskweave/application/planning.py（新增） | 计划 CRUD、采集、生成、解析和幂等导入用例 |
| src/taskweave/application/task_transfer.py | taskweave-task-2、共享纯校验、逐步确认状态导入导出 |
| src/taskweave/core/task_package.py（新增） | 唯一任务包 JSON Schema 与结构约束，无 UI/插件实现依赖 |
| src/taskweave/core/ports.py | 模型请求预算参数、采集 scope 的通用契约 |
| src/taskweave/core/result_views.py | 补齐内置展示器结构说明，供统一目录使用 |
| src/taskweave/infrastructure/model.py | 实际请求字节计量、格式纠错、回复过大/截断错误 |
| src/taskweave/infrastructure/plan_repository.py（新增） | 计划、上下文、生成记录的 SQLite 持久化 |
| src/taskweave/infrastructure/context_sessions.py（新增） | 持续的计划采集 worker、资源复用、文件作用域 |
| src/taskweave/infrastructure/storage.py | 新计划表/索引迁移与 IMPORTED 状态来源支持（如约束需要） |
| src/taskweave/infrastructure/http.py | 大型 AI/计划传输入口的外层字节上限 |
| src/taskweave/application/service.py | 接入计划、统一实例、AI 设置服务操作 |
| src/taskweave/desktop/controller.py | UI 到服务的适配、剪贴板/下载复用、解析预览 |
| src/taskweave/desktop/planning.py（新增） | 计划页面及其采集/生成/导入交互 |
| src/taskweave/desktop/workbench.py | 新菜单、设置控件、实例入口和现有 AI 调用接线 |
| src/taskweave/desktop/chat.py | 保留单步解析，新增完整任务回复校验入口；禁止双重反转义 |
| plugins/playwright/src/taskweave_playwright/__init__.py | 规则/示例、准确返回 schema、声明式采集表单 |
| plugins/ocr/src/taskweave_ocr/__init__.py | 当前步骤范围内的 OCR 规则 |
| plugins/tidb/src/taskweave_tidb/__init__.py | 当前步骤范围内的核对规则、准确返回 schema |

以上新增文件是职责划分，不要求无关地拆分旧文件。实际已有同职责模块时复用并在交付中注明对应位置。

## B. 三项交付的实施任务

### Task 1：统一提示词与请求材料（第一项）

**输入:** 当前步骤/草稿、规格第 2–3 节的完整固定文本、注册器能力和插件贡献。

**输出:** 所有入口使用场景清楚、契约一致的请求；同时为计划提供可复用组装函数。

- [ ] 在 prompts.py 添加 DOMAIN_RULES、EXECUTABLE_STEP_RULES、STEP_CONTENT_RULES、STEP_RESPONSE_RULES、PLAN_RULES、WEB_CHAT_RULES、WEB_CHAT_CODE_RULES，替换 STEP_DESCRIPTION_RULES、REPAIR_RULES；清除旧的重复网页前缀和冲突输出要求。描述生成不追加 WEB_CHAT_CODE_RULES，也不携带代码回复契约。
- [ ] 公共组装入口使用 `purpose` 枚举：description/content/repair/plan。普通内容请求不包含空 feedback/repair_notes，修复请求即使清除了错误也不丢失 repair 模式。
- [ ] 变量目录只组装一次，项为 `{name, schema, required}`，可选 secret；保存真实 enum/格式/描述等约束，去除默认实际值和 source。沿用 core 的合并与实际可访问范围，不在提示词里要求 AI 合并。
- [ ] AI 请求不再另发与最终目录重复的原始 input_schema；保留本地 schema 校验和 output_schema，提供仅有关前序输出的 input_dependencies。
- [ ] 增加由真实实现生成的 runtime_api、可用 builtins、result_handlers、result_views 和插件版本。工具/action/handler/renderer 分组正确，工具 ID 不等同于运行时 action。
- [ ] 上下文发送包含完整正文及名称、页面/对象、provider、时间、顺序和操作说明；不丢失用户用于说明多页面流程的元数据。
- [ ] API 单步响应严格要求 step_content 与 explanation 两字段；描述严格要求 step_description 与 step_notes 两字段。默认 additionalProperties=false。
- [ ] 空 step_content + 信息不足说明显示为需要补充材料，不生成占位代码、不进入采纳对比、不触发格式重试。
- [ ] 格式纠错保留无效 assistant 回复和具体校验错误，仍限制最多一次；每次重试走统一预算检查。
- [ ] 采纳流程保持“解析/校验 → 解释与差异 → 用户采纳”；描述采纳更新两字段，修复采纳仅更新代码。

**按模块验证：**

- [ ] 在 tests/test_model_logs.py / tests/test_web_chat.py 的请求截获测试验证：四种 purpose 契约不同且准确、修复三个字段都有、变量目录无同名重复、描述回复不混成代码。
- [ ] 用含 enum、必填项和闭合 schema 的输入定义检查最终变量目录与运行时可访问变量一致；仅需覆盖现有变量测试相关用例。
- [ ] 使用含中文、引号、真实字符串 `\\n` 与 `\\u0020` 的代码回复检查一次 JSON 解码及 Python 语法，防止二次反转义破坏内容。
- [ ] 使用模型 fixture 返回信息不足对象/空代码，断言草稿未被覆盖且未发起额外模型重试。

**推荐命令（按实际变更选择，不全部机械执行）：**

```bash
uv run python -m unittest tests.test_model_logs tests.test_web_chat -v
uv run python -m unittest tests.test_variables.VariablesTests.test_input_precedence_and_closed_schema -v
```

### Task 2：插件规则与数据契约对齐（第一项）

**输入:** 规格第 3 节全文、当前插件真实实现。

**输出:** 插件给 AI 的说明能够对应真实参数/返回/保存行为，单步目标不被通用规则扩大。

- [ ] 原样落实规格的 Playwright/OCR/TiDB 规则及网页附加文本；插件规则只追加一次，不按能力裁剪。
- [ ] Playwright 两个示例落实为规格中的短示例，明确各自目标；OCR 不再自动要求填写登录，TiDB 不自动替用户决定核对失败是否仍继续。
- [ ] 依据实现补齐 page_inspect/page_handoff/TiDB 查询及结构动作的 output_schema。可选字段/空值如实声明，不为了 schema 整齐改变返回业务语义。
- [ ] Playwright manifest 声明 `context_requests["playwright.page"]` 的可选 url/role 和默认值；计划采集 UI 通过插件 schema 渲染这些字段。
- [ ] 核对完整插件目录中 handler 与 renderer 的名称；截图保存必须用 playwright.image，展示才用 playwright.screenshot。
- [ ] 去除“识别了就自动登录”“所有步骤都必须做数据库核对”等超出当前步骤范围的规则，不添加用户已删除的语言策略。

**按模块验证：**

- [ ] 在现有插件契约测试中检查返回值符合新增 schema；使用现有本地页面/模拟数据库，不连接用户业务网站或真实数据库。
- [ ] 截图示例经静态校验时要求 handler 已授权，renderer 不能当 action；已有对应测试可复用。
- [ ] 三个规格案例人工核对组装后的提示：只采图、只OCR、只填写账号。提示应没有强迫当前步骤执行后续动作的规则。文本调整不写逐字快照测试。

### Task 3：任务包状态契约与共享预校验（第二项的基础）

**输入:** 当前 task_transfer.py，用户最新的导入确认规则。

**输出:** taskweave-task-2 成功包与纯校验方法，AI 生成和任务复制的状态语义正确。

- [ ] 新包顶层固定 format/origin/task/steps；origin 仅 ai_generated 或 task_export，每条 step 含 key、validation_state、document。
- [ ] 在 core/task_package.py 集中定义包的 schema；步骤业务字段来自当前正式契约，包含完整代码、输入输出、依赖、能力、版本和时间，状态放 document 外。
- [ ] 从 import_task 抽出无写入/无执行的 `validate_task_package(app, package, *, expected_origin=None)`；返回归一后的合法包和诊断。计划预览及正式导入使用同一方法。
- [ ] 将 `import_task(app, package)` 改为只接受 v2：先完成全部校验，再创建任务和步骤；中途失败不留下半份任务。
- [ ] export_task 写 origin=task_export，并逐步导出状态。仅当 VALIDATED 且 verified_hash==content_hash 才导出为 VALIDATED，其他为 DRAFT。
- [ ] origin=ai_generated 的每步必须 DRAFT；若出现 VALIDATED，返回 TASK_PACKAGE_INVALID，指出步骤 key。计划入口 additionally 要求 expected_origin=ai_generated，拒绝模型冒充任务导出。
- [ ] task_export 导入逐步恢复状态：DRAFT 不确认；VALIDATED 在 ID 重映射后依据当前代码重新建立 verified_hash，确认来源记录 IMPORTED，不复制旧环境、执行证据或本地ID。
- [ ] UI 显示 IMPORTED 来源且颜色仍由 DRAFT/VALIDATED 决定；不能把导入确认描述成本机已调试成功。
- [ ] 所有包的 schema、声明和绑定错误定位到 step key 和字段路径；拒绝后序引用、renderer 当 capability 和未知插件版本。AI 包每步以及导出包 VALIDATED 步骤还须通过完整代码检查，拒绝空代码、语法错误、未授权动作/缺 handler；导出包 DRAFT 保留尚未完成的代码，这类代码诊断仅预览提示，不拒绝、修正或确认草稿。
- [ ] v1 文件明确提示重新导出；不新增旧包默认已确认分支，不改动现有数据库任务内容。

**按模块验证：**

- [ ] tests/test_task_transfer.py：导出包含一绿一灰两步，再导入仍一绿一灰；hash 按新 ID 重新计算；来源为 IMPORTED。
- [ ] 同文件：导出空代码或未完成语法的 DRAFT，导入后原文与 DRAFT 状态保持；同样内容用于 AI 包或 VALIDATED 步骤时拒绝导入。
- [ ] 同文件：AI 包导入全 DRAFT，模型伪造 VALIDATED/错误 origin 在预校验时拒绝，数据库无新任务。
- [ ] 同文件：前序 data 绑定映射正确，未知格式/前向绑定/无效插件/第N步错误全部在写入前失败。

```bash
uv run python -m unittest tests.test_task_transfer -v
```

### Task 4：计划存储、采集会话与生成服务（第二项）

**输入:** Task 1 的提示组装、Task 2 插件贡献、Task 3 包校验。

**输出:** 规格第 6 节所有 plan 操作，独立计划实例，API/网页共用候选和导入流程。

- [ ] 用正式数据库迁移新增 plans/plan_contexts/plan_generations，字段见规格第 4.2 节。迁移只增加本轮对象，不清空用户已有任务/环境/运行。
- [ ] 新建 PlanRepository，所有上下文编辑检查 plan_id 归属；更新内容/元数据均增加 revision，使用 expected_revision 避免丢失编辑。
- [ ] 文件存储在 plans/<plan_id>；生成输入/回复独立保存；删除单条上下文仅删除其专属附件，不触及共享/其他计划文件。
- [ ] 新建持续的采集会话管理器，按 plan_id 取会话，按 provider/role 复用插件资源，使用真实 collection scope，不能创建占位 Task/Run/Step。
- [ ] 首次采集启动 worker 并执行插件 collect_context；后续采集复用 worker/事件循环。调用结束不关闭资源；同会话并发点击立即反馈忙碌。
- [ ] 耗时采集、模型调用、资源关闭绕开 dispatch 的全局 coordinator.lock，使用非阻塞会话锁与已有活跃调用容量预算；不同计划互不排队，短时数据库事务不跨网络等待。
- [ ] context.collect 采集前后检查 expected_revision 及冻结的会话/环境/插件配置；期间编辑或关闭导致失配时返回 EDIT_CONFLICT，清理本次暂存文件，不追加错配快照。context.update/delete 与 plan.delete 同样携带 expected_revision。
- [ ] 实现 `instance.list/end` 聚合现有执行实例和新计划实例。计划结束释放对应资源，现有 run.control 仍只处理执行记录。
- [ ] 环境删除/切换、插件停用、工作空间迁移和应用退出都处理计划资源占用；异常退出只恢复持久材料，不误报存活会话。
- [ ] PlanningService 实现规格第 6 节 plan.* 操作，通过统一注册器获取完整所选插件贡献；不按插件名称特殊拼提示词。
- [ ] plan.generate 冻结 revision、材料、渠道和当前请求预算；API 完成后读取 structured_content，不能从单步 proposed_content 提取整个任务。
- [ ] 按适配器能力检查图片等上下文；不支持时明确报错并保留材料供用户选择网页导出，不静默丢弃或扩展多模态功能。
- [ ] 模型成功任务包走 expected_origin=ai_generated 的共享预校验；PLAN_INFORMATION_MISSING 保存 BLOCKED，错误/截断保存 FAILED，只有合法包为 READY。
- [ ] plan.generation.parse 对网页粘贴/上传使用同样回复分支和包校验；不自动补括号、不粗暴反转义、不从无关嵌套 JSON 提取一部分导入。
- [ ] plan.generation.import 要求 READY，持有 generation 锁/事务完成创建和 imported_task_id 记录；重复调用返回相同任务。创建任务和状态记录必须原子化，不能仅使用进程内锁掩盖崩溃重复导入。
- [ ] 旧 revision 的候选明确标记并允许用户检查；不得静默用旧候选替换当前编辑。生成不会自行创建任务或执行步骤。

**按模块验证：**

- [ ] 新增 tests/test_planning.py：CRUD 持久化、context 归属、revision 冲突、生成快照冻结、错误回复不写任务、重复导入幂等、删除计划保留已导入任务。
- [ ] 新增 tests/test_context_sessions.py：用假资源提供器计数验证同计划 open 一次/close 一次、不同计划隔离且可同时采集、采集后仍存活、经 dispatch 重复请求立即反馈忙碌、结束后重新采集新建资源；采集中编辑/结束会话后不写入失配快照且清理暂存文件。
- [ ] 使用本地 Playwright 页面人工/单个浏览器用例：首次 URL 采集，页面填入标识，再留空 URL 采集，第二次看到保留值且浏览器仍在；不访问用户真实业务页面。
- [ ] 模拟进程失败/生成期间保存/导入中异常，验证状态与清理不破坏其他计划、任务或确认状态。

```bash
uv run python -m unittest tests.test_planning tests.test_context_sessions -v
```

### Task 5：计划 UI、网页交接与导入预览（第二项）

**输入:** Task 4 的公共操作、现有复制/下载和编辑器组件。

**输出:** 用户从连续采集到 API/网页生成再到任务导入的完整流程。

- [ ] 在“任务”上方新增“计划”；新增 desktop/planning.py 承载页面，workbench.py 仅接导航。
- [ ] 左侧计划列表、右侧编辑区；计划名称/描述/环境/插件均自动保存并显示保存状态，采集/生成前等待最新保存完成。
- [ ] 采集表单来自插件 schema，提供可选名称和操作说明；上下文整体及条目两级折叠、查看、编辑说明、统一垃圾桶删除。
- [ ] “AI 生成任务”选择 API/网页 Chat；生成按钮有立即可见的运行反馈，避免重复点击；实际模型请求前展示请求大小。
- [ ] 网页弹窗提供完整提示预览、复制、下载、粘贴回复与上传 JSON；文本下载 UTF-8，含图片附件时提供自包含 ZIP。下载文件不能依赖本机绝对路径。
- [ ] 使用同一生成快照进行复制/下载，调用成功才通知成功。原生客户端复用现有原生文件通道，浏览器复用下载通道。
- [ ] 候选预览展示任务名、步骤顺序、各步骤描述/说明、输入输出和依赖；代码/原始 JSON 展开查看，全部标注待确认。
- [ ] 校验失败或 BLOCKED 时显示缺失材料和具体路径，不显示可导入按钮；READY 才可导入。
- [ ] 导入成功能直接打开新任务，步骤全部灰色待确认；普通任务导入弹窗展示并恢复包里的混合状态。
- [ ] 页面显示实例保留状态及结束入口；不把“清空上下文”误实现为结束浏览器，或把结束浏览器误实现为删快照。
- [ ] 沿用普通按钮白底描边、主要提交浅青、危险操作红色、横向按钮组及两级折叠，无新增实心蓝色按钮。

**针对性 UI 验证：**

- [ ] 一个完整 API fixture 流程和一个网页文件/粘贴流程，确认预览、解析、导入以及新任务状态。
- [ ] 验证切换计划、离开再返回不丢描述与采集条目；大上下文仅滚动对应区域，按钮不被挤出可视区。
- [ ] 在实际可用的 native/browser 环境各检查一次复制/下载；未验证的平台在交付明确说明，不声称 Windows 已通过。

### Task 6：统一请求大小与系统设置（第三项）

**输入:** 所有 AI 请求组装入口，现有模型/HTTP 适配器。

**输出:** 设置可更改默认 2048 KiB/最高 4 MiB，请求准确计量且所有追加轮次受控。

- [ ] workbench 设置持久化 `ai_request_limit_kib`，默认512，整数范围1–4096；服务提供 ai.settings.get/update，UI不自行读写应用策略。
- [ ] 设置保存后新请求即时生效；请求开始冻结 budget，生成中修改设置不改变已开始请求的判断。
- [ ] 扩展 `ModelPort.complete(messages, tool_specs, response_contract, *, request_limit_bytes)`，所有真实适配器和测试 fixture 更新调用；预算不能只在页面检查。
- [ ] HttpModel 在工具别名映射、response_format 等最终 payload 构建后用 `json.dumps(..., ensure_ascii=False).encode("utf-8")` 得到唯一 body，检查后发送同一 body；不要先按 messages 粗估、实际又用 ASCII 转义扩增。
- [ ] 共享 prepare 函数返回请求快照和 size 信息；Controller 预览与发送复用同一材料，发送时再核对实时定义哈希/计划 revision，避免显示旧请求大小。
- [ ] 单步、描述、修复、计划 API、网页导出全部应用配置；删除 AUTHORING_REQUEST_LIMIT=128*1024 及固定128KiB文案。
- [ ] 工具调用后的下一次请求、自动格式纠错及能力纠错都执行相同预算检查；超限不再发模型请求。
- [ ] 网页统计最终 UTF-8 文本与附件原始字节，ZIP不能按压缩后大小绕过；显示“实际/上限”和分项。
- [ ] CONTEXT_TOO_LARGE 返回实际/上限/分项及可操作提示，保留编辑内容；不擅自调整历史、不压缩能力目录或页面正文。
- [ ] 针对 AI/计划上传入口放宽外层 HTTP 传输封装到8MiB，其余保持原2MiB；业务请求预算仍最高4MiB。认证、Origin、JSON类型检查保留。
- [ ] API 回复读取保持独立2MiB保护，超出用 MODEL_RESPONSE_TOO_LARGE；finish_reason=length 用 MODEL_OUTPUT_TRUNCATED，保留原回复，绝不导入半份任务。

**边界验证：**

- [ ] 新增 tests/test_ai_request_limits.py：默认/修改/重启生效，0、负数、小数、4097被拒绝。
- [ ] 对最终构建 body 精确设置边界：limit==len(body)通过；limit==len(body)-1拒绝且模型传输函数未调用。
- [ ] 中文和反斜杠、完整工具 schema、历史及模型字段参与字节计量；截获实际发送 body 与预览统计一致。
- [ ] 第一次请求合规、工具回复/纠错追加后超限：不发送第二次，已有会话/输入保留。
- [ ] 网页复制文本和下载文件内容一致，UTF-8计量一致；附件ZIP按未压缩大小检查。
- [ ] 外层请求大于2MiB但业务请求小于4MiB的计划数据可到达对应服务；超预算仍被业务层拒绝，其他接口限制没有意外扩大。
- [ ] 响应过大和输出截断不会混成请求超限、不会进入READY或导入。

```bash
uv run python -m unittest tests.test_ai_request_limits -v
```

## C. 实施顺序与交付状态

建议内部顺序：Task 1 → Task 2 → Task 3 → Task 4 → Task 6 → Task 5。Task 6 的预算公共接口应在 Task 1 设计时定好；次序不表示任何项目可以省略。

| 用户事项 | 对应任务 | 当前状态 |
|---|---|---|
| 完整优化提示词，明确任务/步骤，描述与说明可指导代码生成 | 1、2 | 待实施 |
| 计划采集、独立会话、API/网页生成、复制下载、预览导入 | 3、4、5 | 待实施 |
| AI导入待确认，任务复制保留导出时每步状态（最新纠正） | 3、5 | 待实施 |
| 默认512KiB、最高4MiB，全入口计量和设置 | 6 | 待实施 |

交付前：

- [ ] 更新 docs/ai-prompts-current.md，使其展示真实最终提示词，不保留已过时的“建议未实施”。
- [ ] 同步 REQ-003/004/005/006 的实际受影响设计、进度、格式文档及样例；文档里的旧“导入全部确认”和 v1 格式要明确替换。
- [ ] 在本清单记录每项完成状态、运行过的模块测试、未验证平台/真实模型，禁止把规划当成已实现。
- [ ] 运行 `uv run python scripts/check_project.py` 与 `git diff --check`。仅对新失败/新修改追加必要验证，不重复启动全量套件。
- [ ] 给用户简要交付三项功能及状态规则、验证结果、仍存在的实际限制。未获请求不自动提交整棵已有脏工作区、不推送或发布。

## D. 可直接复制给 5.5 的执行指令

```text
在 /Users/dasensen/PycharmProjects/taskweave 实施这三项优化。
先阅读 docs/superpowers/specs/2026-09-23-ai-planning-design.md，里面包含最终提示词全文、数据结构、状态语义和验收标准；再按 docs/superpowers/plans/2026-09-23-ai-planning-implementation.md 完成全部未勾选项。
最新要求：AI 生成任务导入后全部待确认；从已有任务导出的配置携带每步导出时的状态，导入逐步恢复，不能再统一设成已确认。
保留工作区已有变更，不做旧格式兼容，不削减插件能力目录、上下文或日志，不重新添加页面语言切换限制。
核心只负责通用契约与生命周期，具体插件行为由插件适配；页面经 Controller 调用应用服务。
只运行受影响模块测试，全量测试先向我确认。实施后更新清单并报告真实验证结果。
```
