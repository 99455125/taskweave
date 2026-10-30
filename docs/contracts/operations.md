# 应用操作与本地API

调试现场通过 `step.trial.sessions` 按所选环境枚举；`step.trial` 和 `step.trial.flow` 可传 `new_session` 新建，或同时传 `session_run_id`、`expected_session_id` 选择已有现场。运行时校验类型、会话存活、环境与插件版本，两种选择互斥；共享现场使用物理资源锁串行，结果归本次试跑。精确参数与默认值以 [StepUseCases](../../src/taskweave/application/steps.py) 为准。

`run.create` 的 `step_inputs` 接收按步骤分组的预填人工值，允许 `defer_inputs` 延后必录；`sequence.start`（正式）和 `sequence.trial`（调试）的 `node_inputs`、`node_step_inputs` 分别接收按调用节点分组的任务和步骤人工值。组合预填值进入运行快照及幂等指纹，不改写定义，不覆盖自动来源；实际调用时按现有规则合并。精确结构及运行时校验见 [SequenceUseCases](../../src/taskweave/application/sequences.py)。

## 调用形式

Application.dispatch(operation, params)是CLI/本地HTTP共用同步入口，内部将异步编写操作交给相应协程执行。参数和默认值从实际handler签名导出；build_operation_contracts是路由、同步/异步及锁豁免的统一入口，presentation消费者再声明各自所需的窄接口。

```json
{"operation": "task.list", "params": {}}
```

HTTP成功返回`{"ok": true, "result": ...}`，业务错误返回`{"ok": false, "error": {"code": "...", "message": "..."}}`。TaskError.document提供业务错误结构；未知操作为OPERATION_UNKNOWN。HTTP无效字段/JSON为REQUEST_INVALID，未处理内部错误以INTERNAL_ERROR对外返回。

## 传输与并发

POST /api只绑定127.0.0.1，要求application/json和Bearer令牌，拒绝携带Origin的请求；URL与桌面授权入口是不同适配。HTTP请求总上限8MiB，除step.generate、step.generate_goal、step.diagnose、plan.generate、plan.generation.parse外，其余操作上限2MiB。AI内容预算和桌面文件导入还有各自独立限制。

普通写操作在协调器锁内分发；只读或独立协调的操作按LOCK_EXEMPT_OPERATIONS执行，异步操作由自身业务边界协调。豁免不表示没有事务、请求防重或资源锁，不能在文档维护第二套名单覆盖代码。

## 当前操作清单

下表从当前operations.py的路由声明提取；入口列相对于Application，不列出可漂移的参数默认值。调整接口时同时修改实现、消费者类型和契约测试。

| 操作族 | 操作与入口 | 异步处理 |
| --- | --- | --- |
| agent | `agent.discover/describe/author/context/execute/wait/inspect/review` → `agent` 对应用例 | 外层同步，原用例仍管理自己的异步边界 |
| ai | `ai.settings.get` → `ai_settings.get`<br>`ai.settings.update` → `ai_settings.update` | 无 |
| capabilities | `capabilities` → `registry.catalog` | 无 |
| context | `context.ai` → `contexts.ai_records`<br>`context.capture.append` → `contexts.append_capture`<br>`context.capture.delete` → `contexts.delete_capture`<br>`context.capture.get` → `contexts.get_capture`<br>`context.capture.label` → `contexts.label_capture`<br>`context.capture.reorder` → `contexts.reorder_capture`<br>`context.capture.replace` → `contexts.replace_capture`<br>`context.delete` → `contexts.delete_group`<br>`context.group.update` → `contexts.update_group`<br>`context.list` → `contexts.list`<br>`context.read` → `contexts.collect`<br>`context.record` → `contexts.record`<br>`context.reorder` → `contexts.reorder_group`<br>`context.save` → `contexts.save`<br>`context.save_batch` → `contexts.save_batch`<br>`context.targets` → `contexts.targets` | 无 |
| draft | `draft.export` → `steps.export_draft`<br>`draft.import` → `steps.import_draft` | 无 |
| environment | `environment.delete` → `environments.delete`<br>`environment.list` → `environments.list`<br>`environment.save` → `environments.save` | 无 |
| feedback | `feedback.export` → `steps.export_feedback` | 无 |
| instance | `instance.end` → `end_instance`<br>`instance.list` → `instances` | 无 |
| organization | `organization.category.create` → `organization.create_category`<br>`organization.category.delete` → `organization.delete_category`<br>`organization.category.list` → `organization.categories`<br>`organization.category.rename` → `organization.rename_category`<br>`organization.metadata.set` → `organization.set_metadata` | 无 |
| plan | `plan.context.capture.append` → `planning.context_capture_append`<br>`plan.context.capture.delete` → `planning.context_capture_delete`<br>`plan.context.capture.get` → `planning.context_capture_get`<br>`plan.context.capture.label` → `planning.context_capture_label`<br>`plan.context.capture.reorder` → `planning.context_capture_reorder`<br>`plan.context.capture.replace` → `planning.context_capture_replace`<br>`plan.context.collect` → `planning.context_collect`<br>`plan.context.delete` → `planning.context_delete`<br>`plan.context.list` → `planning.context_list`<br>`plan.context.read` → `planning.context_collect`<br>`plan.context.record` → `planning.context_record`<br>`plan.context.reorder` → `planning.context_reorder`<br>`plan.context.save_batch` → `planning.context_save_batch`<br>`plan.context.targets` → `planning.context_targets`<br>`plan.context.update` → `planning.context_update`<br>`plan.copy` → `planning.copy`<br>`plan.create` → `planning.create`<br>`plan.delete` → `planning.delete`<br>`plan.generate` → `planning.generate`<br>`plan.generation.get` → `planning.generation_get`<br>`plan.generation.import` → `planning.import_generation`<br>`plan.generation.imports` → `planning.generation_imports`<br>`plan.generation.list` → `planning.generation_list`<br>`plan.generation.parse` → `planning.parse`<br>`plan.get` → `planning.get`<br>`plan.list` → `planning.list`<br>`plan.update` → `planning.update` | `plan.generate` |
| plugin | `plugin.configure` → `configure_plugin`<br>`plugin.list` → `installed_plugins` | 无 |
| result | `result.delete` → `runs.delete_result`<br>`result.read` → `runs.read_result` | 无 |
| run | `run.context.sessions` → `runs.context_sessions_for_task`<br>`run.control` → `runs.control`<br>`run.create` → `runs.create`<br>`run.delete` → `runs.delete`<br>`run.events` → `runs.events`<br>`run.events.page` → `runs.event_page`<br>`run.get` → `runs.get`<br>`run.inputs` → `runs.provide_inputs`<br>`run.instances` → `runs.instances`<br>`run.list` → `runs.list`<br>`run.output` → `runs.output`<br>`run.reconcile` → `runs.reconcile`<br>`run.restart` → `runs.restart`<br>`run.start` → `runs.start`<br>`run.wait` → `runs.wait` | 无 |
| sequence | `sequence.save/get/list/delete/start/trial` → `sequences.save/get/list/delete/start/trial`<br>`sequence.run.get/list/inputs/retry/reconcile/delete` → `sequences.run_get/run_list/run_inputs/run_retry/run_reconcile/run_delete`<br>`sequence.pause/cancel/continue` → `sequences.pause/cancel/continue_run` | 无 |
| step | `step.confirm` → `steps.confirm`<br>`step.confirm.manual` → `steps.confirm_manual`<br>`step.delete` → `steps.delete`<br>`step.diagnose` → `authoring.diagnose`<br>`step.generate` → `authoring.generate`<br>`step.generate_goal` → `authoring.generate_goal`<br>`step.get` → `steps.get`<br>`step.list` → `steps.list`<br>`step.reorder` → `steps.reorder`<br>`step.save` → `steps.save`<br>`step.trial` → `steps.trial`<br>`step.trial.flow` → `steps.trial_flow`<br>`step.validate` → `steps.validate` | `step.generate`, `step.generate_goal`, `step.diagnose` |
| task | `task.clear_runs` → `tasks.clear_runs`<br>`task.copy` → `tasks.copy`<br>`task.create` → `tasks.create`<br>`task.delete` → `tasks.delete`<br>`task.export` → `tasks.export`<br>`task.flow.get` → `tasks.flow`<br>`task.flow.describe` → `tasks.describe_flow`<br>`task.flow.save` → `tasks.save_flow`<br>`task.flow.confirm` → `tasks.confirm_flow`<br>`task.get` → `tasks.get`<br>`task.import` → `tasks.import_package`<br>`task.list` → `tasks.list`<br>`task.update` → `tasks.update` | 无 |

## 权威实现

外部 AI 使用8个 agent 用途入口；具体操作属于当前显式允许集合，参数通过 discover operation → describe operation 获取。MCP/function calling 的共同工具参数见[integration/tools.py](../../src/taskweave/integration/tools.py)，验收参数由[review.py](../../src/taskweave/application/agent/review.py)的 review_contract 提供；人工验收决定没有对外操作。连接、回执与预算语义见[外部 AI 模块](../modules/agent.md)。

[operations.py](../../src/taskweave/application/operations.py)、[Application](../../src/taskweave/application/service.py)、[HTTP](../../src/taskweave/infrastructure/http.py)、[CLI](../../src/taskweave/__main__.py)。关键返回数据由[core/data_contracts.py](../../src/taskweave/core/data_contracts.py)描述；插件/模型扩展JSON保留开放字段。精确参数以实际handler签名为准，不依赖已删除的需求快照。

## 本地代码生成操作

`step.codegen.sources(step_id, document)`列出当前草稿所选生成器支持的已保存录制 capture，返回归属、名称、采集时间和材料摘要。`step.codegen.generate(step_id, document, generator_id, context_id, capture_id, expected_source_digest, bindings=None, options=None)`核对归属及摘要后纯生成候选，不持久化步骤或消费上下文。生成与应用前复核使用同一操作；缺值/不支持项通过 diagnostics/applicable 返回，源材料漂移抛出 CODEGEN_SOURCE_CHANGED。两者使用应用普通互斥操作锁，不占用运行 worker。

## 条件分支与组合流程参数

`sequence.save`接收 `flow` 结构化组合流程（省略时创建顺序流程），叶节点 step_id 指向组合任务引用 node_id。条件组采用带稳定分支 ID 的 cases/default 与布尔 parallel，同时适用于 task.flow.save；关闭并行取首个匹配，开启并行执行全部命中路径并等待成功汇合。`sequence.run.get/list`返回任务调用 nodes、控制/任务 flow_instances 与组合游标；任务调用的 execution_path 区分轮次和路径。`sequence.run.inputs/retry/reconcile`及 sequence.continue 可提供组合级 execution_path，多个候选实例时必须明确选择；重试中的 retry_execution_path 是子任务内执行路径，两者不混用。补参继续核对 expected_input_id。实际实现与验证由控制流变更负责。

分支资源会话通过 `run.context.sessions` 返回 `session_id`、`resource_path` 与对应步骤/出现的 `execution_paths`。`context.read/targets/record` 可指定 `execution_path` 和 `expected_session_id`；重复出现的步骤必须定位实际路径，过期会话或路径明确拒绝。上下文界面按当前步骤筛选分支会话并传递该身份，录制仍在所选会话内进行。

## 画布与步骤派生

`step.insert` 指定目标顺序容器和插入索引，以任务定义哈希防止过期落点；创建和安置原子提交。`step.copy`、`step.split` 同时核对任务定义、原步骤内容哈希及上下文组版本。拆分提交两份步骤文档和各自材料选择，返回新步骤，原步骤历史不变。

`step.reuse` 指定来源步骤、目标任务及位置，核对来源和目标双快照，接收用户审核后的完整输入绑定。外部步骤引用不自动猜测，删除依赖通过从 bindings 中移除对应项表达。`context.capture.transfer` 指定移动或复制、采集项选择、目标步骤/组以及源目标组版本。精确签名以 [派生用例](../../src/taskweave/application/step_derivation.py)、[步骤用例](../../src/taskweave/application/steps.py)、[上下文用例](../../src/taskweave/application/contexts.py) 为准。

`run.list` 返回 `sequence_run_id` 与 `sequence_execution_path`，供客户端区分独立运行与组合拥有的子运行；组合自身仍由 `sequence.run.list/get` 查询。正式与调试模式冻结在组合快照中，不能用同一启动请求 ID 交叉复用。正式组合要求所有任务/流程已确认，编排保存及调试允许未确认草稿。
