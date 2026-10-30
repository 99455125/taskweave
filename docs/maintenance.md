# 模块导航

按能力定位模块，模块文档说明当前职责与关键协作；精确接口和测试目标分别以源码和tests/module-map.json为准。

| 能力 | 模块知识 | 主要代码入口 | 测试键 |
| --- | --- | --- | --- |
| 任务、步骤、导入复制、确认 | [任务与步骤](modules/tasks.md) | application/tasks.py、steps.py、task_transfer.py；presentation/tasks.py、editor.py、step_actions.py | application.tasks、application.steps、ui.tasks、ui.editor |
| 规划、生成记录与导入 | [规划](modules/planning.md) | application/planning.py；presentation/planning.py；desktop/pages/planning.py | application.planning、ui.planning |
| 外部AI发现、编写、调用与验收 | [外部AI](modules/agent.md) | application/agent/；integration/；infrastructure/agent_store.py、agent_connection.py；desktop/components/agent_review.py | application.agent、integration.agent、ui.agent |
| 步骤编写、校验、插件诊断与AI候选 | [步骤编写与校验](modules/authoring.md) | application/authoring.py、authoring_sessions.py、ai_requests.py；presentation/authoring.py、chat.py | application.authoring、ui.debug |
| 采集、目标、录制与素材 | [上下文](modules/contexts.md) | application/contexts.py；infrastructure/context_sessions.py；presentation/context_collection.py、collection_form.py | domain.contexts、repository.contexts、ui.contexts |
| 运行、补录、重跑、恢复与结果 | [执行](modules/execution.md) | application/runs.py；infrastructure/run_coordinator.py、coordinator_pool.py、worker_transport.py、worker.py | application.runs、ui.executions、ui.results、ui.debug |
| 任务组合、映射与结构化推进 | [执行](modules/execution.md) | core/task_sequences.py、sequence_flow.py；application/sequences.py、sequence_driver.py、sequence_values.py；infrastructure/repositories/sequences.py；desktop/pages/sequences.py、desktop/components/sequence_execution.py | application.sequences、repository.sequences、ui.sequences |
| 数据库、事务、环境与工作空间设置 | [存储与环境](modules/storage.md) | infrastructure/sqlite_storage.py、repositories/；application/environments.py、settings.py | shared.storage、application.environments、repository.environments、ui.settings |
| 交互、导航、页面与原生窗口 | [桌面UI](modules/desktop.md) | desktop/workbench.py、pages/、components/；presentation/ | 对应ui.*；presentation.interactions |
| 发现、注册、SDK与具体插件 | [插件](modules/plugins.md) | src/taskweave/plugins/；plugins/ | shared.contracts、对应plugins.*（含plugins.pdf） |
| 内部数据集与Excel文件处理 | [存储](modules/storage.md)、[插件](modules/plugins.md) | core/dataset_contracts.py；infrastructure/datasets.py、dataset_sql.py；plugins/dataset/、plugins/excel/ | plugins.dataset、plugins.excel |

以上源码路径以src/taskweave/为基准，根目录plugins/另行标明。完整目录与调用方向见[架构](architecture.md)。

## 横切入口

- [公开操作契约](contracts/operations.md)：CLI/HTTP、操作分发及锁。
- [开发指南](development.md)：依赖与代码组织。
- [测试指南](testing.md)：changed dry-run、快速/浏览器目标及映射。
- [运行与打包](deployment.md)：启动、工作空间和平台构建。
- [能力边界](limitations.md)：未实现边界及验证范围。

维护时先核对当前代码和工作区，再读受影响模块；接口/存储变化同时核对契约及真实消费者。只同步改变的知识，不重写无变化模块。
