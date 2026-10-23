# 外部 AI 编写、调用与验收

## 当前入口

外部 AI 用例位于 application/agent，通过现有 Application.dispatch、CLI request、本地 HTTP 和可选 MCP stdio 使用。按用途提供发现、详情、编写、上下文、执行、等待、证据查询和验收接口；精确操作名见[操作契约](../contracts/operations.md)，参数类型/默认值由当前外部策略与真实 handler 签名共同确定。discover 的 operation 类型提供操作目录，describe operation 按需返回当前参数 Schema，包括 review.prepare/read/read_spec/open。

发现结果默认20条、最多100条，游标绑定查询及结果版本。动作 Schema 按选中能力读取；插件编写说明按插件去重。查询区分已发现/启用/加载及未检查的外部环境，不把注册成功当成真实服务可用。

context_provider 与 plugin 详情按需公开真实 context_requests 和声明式 config_variables，包含所需字段、默认值、选定目标及录制声明。

## 编写与执行

外部编写材料包含目标基线、当前代码、步骤/任务包 Schema、运行 API、允许内置函数、所选能力、插件贡献、流程语法和显式选择的上下文。材料冻结为 bundle；大型材料返回部分索引，通过 inspect 的 bundle 类型按 section/游标读取。材料不调用模型，支持当前 task-2/task-3、分支、遍历、条件循环及作用域。

创建/保存采用 request_id 回执；本地定义和成功回执共享控制库事务。已有步骤及任务修改要求基线，过期材料或跨任务材料被拒绝。候选校验保留插件 lint 诊断，error 级诊断不能报告 valid=true。一次分支试跑不能确认未执行的其他动作；人工确认与试跑证据确认分别沿用现有入口。

task.run 组合创建和启动，要求目标定义 hash；普通运行与组合均保留原生稳定命令身份。补参后按原 mode/target 续启。未证明持久幂等的组合控制在回执不确定时要求核对，不自动重发。查询、等待和验收不会重执行动作；UNKNOWN 仍须显式证据核对。

## 数据边界

普通返回预算32KiB，大材料/日志/报告采用引用、section、游标或 JSON Pointer；截断有明确标记。Schema 属性名和变量元信息保持有效，只处理实例值和敏感默认值。上下文默认不采集图片预览，向模型发送图片需独立显式选择；本地证据仍按原有会话与持久化规则管理。对外结果不返回内部文件 path。

大型 bundle/result 的字典返回子字段 Pointer，列表分页，文本按 text_offset 分块并附完整值指纹及 next_offset。先对原始结构处理秘密和图像，再执行 Pointer、逐轮 item_pointer 或文本分块，避免选出叶子后丢失敏感字段语义。inspect 的 operation_result 类型使用只读允许集合读取规划生成、草稿、反馈等其他已发现操作；规划内部请求/响应文件位置不进入结果。

## 可视化验收

prepare 将目标版本及声明式核对要求冻结为 review_spec_id；创建运行时在同一事务绑定。相同版本的要求可复用，后来修改要求不改写旧运行。组合的创建先持久化定义、验收绑定和回执，再唤醒推进器，避免外层事务尚未提交时启动。

组合要求同时冻结每个节点的成员任务 hash；启动以实际运行快照核对。仅组合 revision 相同、成员定义已变时，旧要求不会自动复用，显式绑定返回 REVIEW_VERSION_MISMATCH。NEXT/UNTIL 缺参后的续启读取持久 last_command，保留原执行范围。

验收分别记录运行状态、自动 PASS/FAIL/MISSING/ERROR/NOT_APPLICABLE/UNCONFIGURED/INCOMPLETE，以及人工未验收/通过/不通过/已过期。运行成功、没有要求或步骤自报布尔值均不自动等同于人类验收。比较读取持久结果，区分 bool/数字、缺失/null、跳过分支和逐轮结果；报告包含来源运行、组合节点、执行路径、尝试及结果引用。

报告指纹绑定事实；人工决定只通过桌面专用用例记录，对外工具没有伪造 human 决定的操作。结果失效或事实变化后原决定显示过期。大型报告对外分页，完整事实保留本地；查看不会重新访问外部业务系统。

运行与组合提供“查看验收”。弹窗显示目标、版本、核对项、实际执行路径及当前/历史尝试，原始证据复用现有表格、图片和报告结果查看器。外部 review.open 在已连接的工作台客户端打开指定报告，未连接时返回 REVIEW_UI_UNAVAILABLE；不把桌面授权 URL 或会话令牌交给模型。

## MCP、function calling 与 Skill

安装 `taskweave[mcp]` 可选依赖；源码环境可用 `uv run --extra mcp taskweave --home <目录> mcp`。工作台和 serve 启动一个独立的 agent 专用 loopback 端点，但共用同一个 Application 所有者。工作空间中的 agent-connection.json 只供本机桥接读取：POSIX 权限0600，包含随机令牌、实例身份及工作空间摘要；连接先鉴权核对实例身份。客户端不创建第二个 Application，服务关闭只清理自身描述符。

`taskweave --home <目录> connection-config` 导出无令牌的 MCP 配置；设置中的“外部 AI / MCP”提供复制入口。桌面打包版使用另行安装的 taskweave[mcp] CLI 桥接，不能将 GUI 可执行文件当作 Python。不同 AI 客户端的配置位置由客户端决定，不自动改写全局配置。

`taskweave function-tools` 导出与 MCP 共用的8个 function calling 工具定义，自有调用器通过 integration.tools.invoke 与 AgentClient 分派。具体动作 Schema 按需查询；工具定义不装载整个插件目录。普通运行、重复调用和轮询不需要模型。

`taskweave skill <新目录>` 安装/导出随包分发的 Skill；设置页也提供明确的安装按钮。已有不同内容的目录返回 SKILL_DESTINATION_CONFLICT，完全相同内容返回 unchanged。Skill 入口按编写、执行恢复及验收渐进读取参考，当前参数和 Schema 始终来自运行实例，不复制一套静态目录。

## 实现与验证

[用例入口](../../src/taskweave/application/agent/service.py)、[发现](../../src/taskweave/application/agent/discovery.py)、[操作策略](../../src/taskweave/application/agent/contracts.py)、[编写材料](../../src/taskweave/application/agent/authoring.py)、[运行查询](../../src/taskweave/application/agent/execution.py)、[验收](../../src/taskweave/application/agent/review.py)、[回执存储](../../src/taskweave/infrastructure/agent_store.py)、[连接桥](../../src/taskweave/infrastructure/agent_connection.py)、[MCP](../../src/taskweave/integration/mcp.py)、[Skill](../../src/taskweave/integration/skill_assets/SKILL.md)、[验收界面](../../src/taskweave/desktop/components/agent_review.py)。测试键 application.agent、integration.agent 和 ui.agent，映射统一维护在 tests/module-map.json。
