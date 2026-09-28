# 插件扩展 AI 的能力

插件扩展的是统一的“编写—观察—试跑—修正”流程，而非仅提供提示词。流程控制与模型调用仍由 REQ-003 负责，REQ-004 注册贡献并通过 Playwright 验证。

| 扩展点 | Playwright 示例 | 边界 |
|---|---|---|
| 指令与示例 | 本项目会话 API、定位器规则、合法 step content | 补充公共规范，不覆盖它 |
| 上下文提供器 | 当前页面结构、可交互元素、选定截图、页面状态 | 按需采集并脱敏，不把登录态自动发给模型 |
| AI 可调用工具 | 读取页面结构、定位元素、检查可见性 | 声明输入输出 schema、作用域与副作用；由统一工具调度器执行 |
| 内容校验 | 校验引用的能力、会话使用、必需的等待与输入 | 模型文本不能直接视作合法或成功 |
| 试跑与业务验证 | 执行内容、确认单号/状态变化、收集截图 | 使用统一执行入口；副作用试跑由用户发起，读工具与写工具区别处理 |
| 调试诊断 | 将超时、定位器错误、截图整理成修正建议 | 反馈给同一编写会话，修改由用户采纳，不无限自动重试 |
| 资源生命周期 | 提供指定任务/角色会话，试跑清理及复用 | 会话对象留在本地 worker，不传给模型或序列化进数据库 |

插件可以同时提供给 AI 编写阶段使用的工具和给固定步骤执行的能力；两者可复用底层实现，但权限和调用入口分开。模型若需要点击或提交，进入明确的试跑流程，不因“AI 工具调用”而绕过执行控制。

## 现存资源目标选择

可选插件钩子 `list_context_targets(provider_id, ctx, request)` 枚举当前实例已有资源，返回 `{target_id, label, request}` 列表。宿主只展示 label，并按“表单 → 高级参数 → 目标 request”顺序合并采集参数；不解释浏览器、角色或数据库字段。没有钩子的插件仍可按原参数采集，不因打开选择界面而启动资源。

目标选择界面由提供器 schema 的 `x-taskweave-context-targets` 驱动。插件声明选择器名称、参数模式名称、是否自动选中唯一目标、选中目标后是否隐藏参数表单。没有声明的提供器不显示目标选择器；因此 TiDB 直接显示表名/数据库表单，Playwright 才显示页面目标和“新建页面”。

选中现有目标时，插件还可用 `keep_parameters_when_selected` 指定仍需用户选择的采集参数。Playwright 保留 `scope`（当前视口/完整页面），只隐藏新建页面所需的 URL 和角色；采集 request 合并所选范围与目标参数。

- `plan.context.targets(plan_id, provider_id, request?)` 只读取该规划自己的采集资源。
- `context.targets(step_id, provider_id, run_id?, request?)` 只读取用户所选、属于该步骤任务的保留运行；独立观察没有保留资源，返回空列表。
- 两个入口返回 `{session_id, targets}`；不存在实例时 `session_id=null`、`targets=[]`。
- `plan.context.collect` 和 `context.read` 支持可选 `expected_session_id`。选择目标后携带列表返回的 session_id，实例结束或变化时返回 `CONTEXT_SESSION_CHANGED`；插件目标已关闭时返回 `CONTEXT_TARGET_UNAVAILABLE`。

列表和采集在持有资源的事件循环内串行调用，空草稿不需要通过可执行代码编译才能观察现存资源。观察不会接管资源所有权，也不会把其他规划、调试或正式执行的资源合并。结束忙碌规划采集会话会明确失败，并保留实例引用供稍后关闭。

编写服务支持受限轮次的工具观察 → 生成 → 用户试跑 → 反馈修正。它不让模型无限自主规划业务或在每次固定任务执行时重写步骤。

## 上下文采集与预览

采集器统一返回 `ContextCollection(items, views)`。`items` 是发给 AI 的证据；`views` 是用户预览，二者分开保存。预览项为 `{title, renderer, data}`，renderer 必须由核心或插件注册，宿主只按注册类型渲染，不判断 Playwright、TiDB 等插件类型。调用方通过 `include_view` 决定本次是否生成预览；插件在 context request schema 中用 `x-taskweave-context-view.default` 声明界面默认值。

Playwright 的 `playwright.page` 提供 `scope=viewport|full_page`，默认完整页面，并可返回 `playwright.screenshot`；TiDB 的 `tidb.schema` 可返回 `tidb.table`。没有预览能力的插件只返回 items，现有表单和采集流程不受影响。

旧项目已有 tools_json 的函数描述与 ToolsHandler 的工具执行分发，说明 AI 与工具交互并非全新方向；目前分发硬编码 Excel/SQL。新设计改为统一插件注册，使 Playwright 和后续插件可贡献工具与上下文，不改核心 if/else。

模型适配需要声明是否支持工具调用和图像。插件需要截图理解时模型必须支持图像；不支持则使用可用的文本结构或明确提示能力不足，不伪称已读取截图。无模型配置时仍支持纯手写、校验、试跑和保存。

## 对话渠道适配

`AuthoringContribution.channel_overrides` 为可选字典，默认 `{}`。键 `api` 与 `web_chat` 分别指定渠道覆盖的 `instructions`、`examples`；公共约束和能力目录始终保留，渠道适配不能扩大动作权限。API 使用原有工具调用，网页只导出文本且不暴露可调用工具。插件决定渠道提示词及示例差异，核心不按具体插件分支。旧插件无需修改，新增字段兼容 API v1，使用该字段的新插件要求当前核心。Playwright 已提供网页适配。

### 2026-09-19 结果展示声明 v1

`ctx.result(data=..., outputs=..., views=...)` 增加可选 `views`，默认空列表，旧步骤及插件无需修改。业务内容只保存在 `data`；展示声明为 `{title, renderer, pointer}`，使用 JSON Pointer 引用字段。框架提供 `core.json`、`core.table`、`core.report`、`core.image`；插件可选实现 `result_views()`，以命名空间 ID 注册声明式展示器（type 为 json/table/report/image）。插件不直接访问 UI。

展示声明与业务结果在同一任务 DB 事务中保存，内部保留名 `__views` 存储 `{version:1, items:[...]}`，不创建业务结果引用，不改变前序输出绑定。无 DDL 或模板格式变更；旧结果没有声明时回退 JSON。图片文件使用已保存 outputs 名称引用，禁止直接传任意文件路径。报告支持 passed/message、带标题的多个 tables，以及 query_info。界面渲染已保存内容，不重新执行动作。

API 和 Chat 编写上下文包含所选插件展示器与格式说明；用户在目标中要求保存表格或截图，AI 生成 views。使用插件并不会自动创建展示项。

执行列表“详情”文字固定；详情中成功步骤展示勾。成功步骤旁的查看图标打开对应有效成功尝试的结果窗口，多项展示使用标题页签，保留原始数据；历史详情按具体尝试查看。TiDB 插件已支持连接、只读查询及表格和核对报告展示。
