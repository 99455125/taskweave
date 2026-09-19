# 插件协议 1

## 1. 发现和清单

插件包发布 entry point `taskweave.plugins`，值为返回 Plugin 的无参工厂。安装不等于启用；加载只针对本机启用清单。ID 为小写点分命名，能力 ID 为 `<plugin_id>.<local_name>`。重复 ID、缺依赖、api_version != 1、schema 无法解析均拒绝启用。package_version 保留用于依赖兼容，不是步骤版本。

清单字段：id、package_version、api_version、dependencies（插件 ID → 版本约束）、actions、tools、context_providers、resource_providers、result_handlers。依赖图拒绝环。声明和 entry point 加载失败应列出原因，不影响其他未依赖任务。

[ports.py](contracts/ports.py) 明确方法签名；JSON 字段名以本文和例子为准。

## 2. Action 与 AI Tool

ActionSpec：id、description、input_schema、output_schema、effect=READ/WRITE、timeout_ms、resource_ids、retry_safe=false。核心调用 `preflight` 后 `execute`，再 `verify`；没有可执行验证时由内容中的明确断言保证结果，通用“无异常”只能说明调用完成。

ToolSpec 复用动作的输入输出与 effect，但仅在编写会话经 tool dispatcher 访问。工具允许映射到同一个底层实现，调用路径仍区分编写与正式执行。模型不能把工具名称当可执行 Python。

PluginContext 只暴露 scope、环境非秘密配置、本地 secret resolver、取消信号、日志、受控文件暂存入口和 resources；不包含 UI 或总库 connection。作用域由宿主构造，插件不能从模型输入替换 task_id。

## 3. AI 贡献

`authoring(selected_ids)` 返回 instructions、examples、context_provider_ids、tool_ids；`collect_context` 返回类型为 text/image 的 ContextItem（mime、脱敏内容或受控引用、来源、截断标记）；`lint` 返回 Diagnostic（code/message/path/severity）；`diagnose` 将本次运行 ErrorInfo 和产物转换为可供用户选择反馈的诊断。

插件规则不得改变项目内容格式和能力 allowlist。总上下文默认 64 KiB 文本，超限保留来源并标记截断；图像经适配器能力检测与用户选择。资源 provider 负责 open/close，Playwright 以运行/角色键复用，不跨 worker 传实例。

## 4. 结果处理与统一存储

StepResult = data（JSON/null）+ outputs（ResultRequest[]）。data 默认由核心保存到任务库 step_outputs；无数据允许只记录总库执行状态。ResultRequest = handler_id + name + payload。

插件 ResultHandler 提供 schema（JSON Schema、自定义表及兼容迁移声明）、prepare（转为 JSON/表记录/文件 token 的存储描述）、parse（将已读记录解析成稳定的业务值）、preview（展示描述）。这些方法不接收数据库连接或 TaskStore，不实现 persist/delete。核心完成建库建表、迁移、作用域注入、事务、文件落位、结果索引和清理。无自定义 handler 的普通 JSON 由核心直接处理。

自定义表采用 p_<plugin_slug>_ 前缀，核心注入 run/step/attempt 标识；插件提供声明式列、索引和迁移描述，核心校验执行，不允许结果处理器自行提交事务。大结果可保存于自定义表，通用输出保留类型与引用，不必复制完整结果集。文件位于任务目录，DB 保存引用。

结果提交后才可供下游读取。核心按绑定找到同一 run 的有效成功 attempt，读取数据后按需调用 parse，再提取字段和校验输入。插件缺失返回 HANDLER_UNAVAILABLE，不静默使用旧值；通用 JSON 仍可直接读取。保存失败为 RESULT_SAVE_FAILED，不能自动重做已发生的外部业务。按 receipt 恢复或重试保存，清理由核心统一执行。

## 5. Playwright 验证边界

插件拥有 Browser/Context/Page，动作示例见 [manifest](examples/playwright.json)。AI 只看到文本/图片和 opaque alias，不收到浏览器对象；固定步骤用 ctx.call。相同 worker/event loop 保持角色 context，完成一步不关闭；释放运行租约时 close。重启后重建资源并预检查，不承诺恢复原页面。

用另一个简单 JSON 示例插件验证所有接口均不专属于 Playwright。插件和 Python 内容是用户信任的本地代码，接口作用域隔离防止误用，不宣称进程是安全沙箱。

## 存储接口细节

allocate_file 返回只在本地插件可见的 StagedFile(token, local_path)，用于向 Playwright screenshot 传目标路径；动作仅返回 token，不回传 local_path。核心根据 handler 返回的文件存储描述接收 token，并校验它属于当前 scope，拒绝任意路径和越界符号链接。

TaskStore 是宿主存储端口；结果 handler 不调用它。插件声明表结构和记录，宿主限制表命名域、参数化数据、禁止跨库访问并统一提交结果与 receipt。动作只使用受控文件暂存入口生成文件。接口隔离防止误用，受信任 Python 插件仍不是安全沙箱。

ModelReply 经 provider 归一化为 proposed_content/explanation/tool_calls；工具结果以同 call_id 的工具响应消息追加。一次回复若同时有内容和工具调用，先处理工具建议，内容暂不采纳；最终无工具调用的回复才作为草稿建议呈现。

## REQ-004 实施补充

公开入口为 taskweave.plugins.sdk。manifest 的能力集合由插件 methods 与 catalog 派生，不重复维护声明列表。新增 AuthoringContribution.constraints 机器约束与可选 failure_results 诊断产物钩子；资源 active(provider_id) 用于检查当前资源。任务库升级至 v2 增加 plugin_table_schemas，核心执行加列/索引声明，升级前备份且失败回滚。context.read 可在暂停 worker 中读取当前页面。
