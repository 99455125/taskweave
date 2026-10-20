# 应用操作与本地API

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
| sequence | `sequence.save/get/list/delete/start` → `sequences.save/get/list/delete/start`<br>`sequence.run.get/list/inputs/retry/reconcile/delete` → `sequences.run_get/run_list/run_inputs/run_retry/run_reconcile/run_delete`<br>`sequence.pause/cancel/continue` → `sequences.pause/cancel/continue_run` | 无 |
| step | `step.confirm` → `steps.confirm`<br>`step.confirm.manual` → `steps.confirm_manual`<br>`step.delete` → `steps.delete`<br>`step.diagnose` → `authoring.diagnose`<br>`step.generate` → `authoring.generate`<br>`step.generate_goal` → `authoring.generate_goal`<br>`step.get` → `steps.get`<br>`step.list` → `steps.list`<br>`step.reorder` → `steps.reorder`<br>`step.save` → `steps.save`<br>`step.trial` → `steps.trial`<br>`step.trial.flow` → `steps.trial_flow`<br>`step.validate` → `steps.validate` | `step.generate`, `step.generate_goal`, `step.diagnose` |
| task | `task.clear_runs` → `tasks.clear_runs`<br>`task.copy` → `tasks.copy`<br>`task.create` → `tasks.create`<br>`task.delete` → `tasks.delete`<br>`task.export` → `tasks.export`<br>`task.get` → `tasks.get`<br>`task.import` → `tasks.import_package`<br>`task.list` → `tasks.list`<br>`task.update` → `tasks.update` | 无 |

## 权威实现

[operations.py](../../src/taskweave/application/operations.py)、[Application](../../src/taskweave/application/service.py)、[HTTP](../../src/taskweave/infrastructure/http.py)、[CLI](../../src/taskweave/__main__.py)。关键返回数据由[core/data_contracts.py](../../src/taskweave/core/data_contracts.py)描述；插件/模型扩展JSON保留开放字段。精确参数以实际handler签名为准，不依赖已删除的需求快照。
