# 插件契约与能力包

宿主统一注册、启停和调用，插件提供动作、资源、上下文、AI 编写贡献和结果展示声明。一个步骤可以组合多个已声明能力。

## 当前行为与约束

- 插件 API v1，通过 `taskweave.plugins` entry point 发现；实际字段、schema 与接口以 SDK/registry 为准。
- 每个插件独立声明依赖，核心默认环境不强制安装浏览器、OCR 或数据库驱动。
- 动作输入/输出必须校验，步骤只能调用声明能力；插件会话对象不能作为 JSON 结果或模型输入传出。
- 资源生命周期由统一执行/会话流程管理；打开上下文目标选择器不新建资源，不跨规划/运行接管实例。
- AuthoringContribution 支持 api/web_chat 渠道覆盖，插件补充公共规范而不扩大权限；固定步骤不要求配置模型。
- ContextCollection 分离 AI items 与用户 views；可选目标钩子与 schema 扩展决定选择 UI，核心不按具体插件分支。
- 结果使用 `ctx.result(data=..., outputs=..., views=...)`，outputs 请求必须纳入结果才能保存；renderer 是声明式扩展，不直接访问 UI。实际保存和索引由宿主负责。
- 插件页根据安装注册表和当前加载的能力动态展示；动作/工具说明包含输入输出 schema、读写效果、超时、可重试标记、资源依赖及插件贡献示例。未加载的能力明确显示缺失，不以静态原型数据代替。

## 代码和使用入口

[SDK](../../src/taskweave/plugins/sdk.py)、[registry](../../src/taskweave/plugins/registry.py)、[manager](../../src/taskweave/plugins/manager.py)；插件包位于仓库根 plugins/。

| 插件 | 能力与本地说明 | 测试键 |
| --- | --- | --- |
| Playwright | [页面动作、观察和浏览器资源](../../plugins/playwright/README.md) | plugins.playwright |
| OCR | [本地图片文字识别](../../plugins/ocr/README.md) | plugins.ocr |
| TiDB | [连接、schema 采集、只读查询、显式 SQL 执行与展示](../../plugins/tidb/README.md) | plugins.tidb |
| file | [有界本地文件读取与步骤数据链路](../../plugins/file/README.md) | plugins.file |
| utility | [时间、UUID、精确十进制计算](../../plugins/utility/README.md) | plugins.utility |

## Playwright 观察与定位

0.4.0 动作共用 within/nth/frame链与 target_id；角色主页面保持，关闭目标报错。新增 checked 设置/读取/断言与页面目标枚举；快照候选实际计数，语义无命中有经验证的 CSS 备选；可选 selector 范围的有界局部 DOM、字段组、祖先与敏感值遮蔽；默认整页快照不读输入值，值仅在显式局部 DOM 中提供。旧定位器兼容，插件版本快照校验保持，可选人工录制提供器已实现，规划与步骤采集弹窗已接入共享录制控制条。详细方法和覆盖边界见插件说明。

通用动作补充hover/double-click/容器滚动/同frame拖拽（WRITE且不可自动重试），以及state/assert_state、allowlist属性、列表和native/ARIA表格有界读取（READ）。集合在浏览器端限制长度、行列和字节预算，保留截断信息及表格单元格跨度；只读当前DOM，不自动翻页或加载虚拟化内容。读取预检不做点击的actionability扫描；全部继续共用页面身份与范围定位。新增page_upload接受有界Base64文件（隐藏input或显式chooser触发），page_dialog只处理本次动作按类型/完整提示匹配的原生弹窗；二者WRITE且不可自动重试，取消释放监听，文件通过步骤绑定从file.read取得。方法/参数及限制以[插件说明](../../plugins/playwright/README.md)为准。

Playwright的上传/原生弹窗、定位预检、快照与集合读取在外层取消或预算超时时保留单次已发协议调用的回复归属，接收其最终异常，不保留后续动作流程。取消发生在命令发出前不执行命令；已发生的业务动作不能回滚或自动重试。iframe路径检查使用的临时元素句柄检查后释放。

录制操作保留发生时的文档身份、去除查询参数/凭据的URL和短标题；基线前后及目标后状态均核对文档，快速跳转时标明PAGE_DOCUMENT_CHANGED缺失证据，不能把新页DOM或复用token当旧页验证。

SDK 的可选录制协议已作为独立扩展提供 ContextRecordingCommand/Batch/Provider，不改变 API v1 基础 Plugin 的必需方法。read 返回非消费 ContextCollection，ack 在宿主持久化成功后明确调用；旧插件不支持时保持原快照流程。当前规划会话控制已接入，实际浏览器提供器已验证可信事件、敏感值遮蔽和 frame/新页面身份；采集 schema 的 `x-taskweave-context-recording: true` 是可选界面能力标记；规划与步骤复用控制条与提交后确认流程，见[上下文](contexts.md)。

## SQL 与文件链路

文件插件是可选 `files` extra：`file.read` 完整读取显式 file_root 内的 text/JSON/CSV/Base64，超限报错，不截断 SQL。数据经步骤返回与 `/content` 输入绑定交给 TiDB，不新增跨插件直调协议。任务包、步骤绑定和核心持久化格式保持不变。

TiDB 新增 `tidb.execute_sql` WRITE、不可自动重试；旧 `tidb.query` 保持只读。默认 DML/查询脚本整批事务，DDL 须显式逐条提交；报告逐条结果、影响行数，失败区分已回滚、部分提交和未知提交。语句/文件限制与取消边界见插件说明。数据库驱动和 SQL 解析器仍仅属于 TiDB 插件依赖。

## 验证入口

修改插件只选择对应键；SDK/注册变化使用 `shared.contracts` 和 changed dry-run 核对消费者。真实 Playwright 测试需显式 `--include-browser`；插件 fixture 测试不代表真实业务系统验收。新增扩展要保护无该可选钩子的旧插件行为。关联：[上下文](contexts.md)、[AI 编写](authoring.md)、[执行结果](execution.md)。

## 按需深入

[插件开发](../reference/plugin-development.md)。只在本次修改涉及相应契约时阅读。
