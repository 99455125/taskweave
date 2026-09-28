# 存储、事务与环境

本地 SQLite 与任务文件管理；环境为用户配置来源，不写操作系统环境变量。

## 当前行为与约束

- 工作空间总库为 `taskweave.db`，任务业务库为 `tasks/<task_id>/data.db`；文件按任务/运行作用域管理。路径以 Store 与相关仓储实现为准，不沿用旧项目路径。
- 控制库当前 v17；v15 为规划生成到任务的导入收据并回填旧 `imported_task_id`，v16 为任务/规划本地收藏与共享单层分类。迁移与备份在 storage.py，当前建表资源在 infrastructure/sql/。旧历史设计 DDL 不能直接当作现行 schema。
- 仓储分别管理任务、步骤、环境、运行、结果、步骤上下文、规划、规划上下文、生成记录及本地收藏分类；共同使用 SQLite UoW，组合操作绑定同一事务，线程间不能串用连接。
- 嵌套异常与复制/导入失败不得留下部分记录。任务库、控制库及文件系统不具备跨介质原子事务，恢复须按尝试标记与结果证据处理，不推断外部动作必然失败。
- 环境可设默认，可保存变量与说明，也允许本地普通密钥值；env: 引用仍兼容。模型提示与日志的隐私处理另有边界。
- 输入优先级为环境 < 任务默认/运行输入 < 步骤 schema 默认 < 显式步骤绑定或独立试跑输入 < 本次 step_inputs；封闭 schema 过滤未声明变量。
- 删除环境保留运行历史的展示信息；正在使用的资源/运行须遵守占用检查。删除默认环境需清除默认设置。
- 清理只作用于指定任务/运行；不得顺带删除其他任务、用户配置或公共服务日志。
- 导入收据的 `task_id` 保留为历史文本而不外键到任务；删任务不删收据。分类外键删除时仅置空关联。

## 代码入口

[仓储端口](../../src/taskweave/core/repositories.py)、[SQLite 装配](../../src/taskweave/infrastructure/repositories/__init__.py)、[UoW](../../src/taskweave/infrastructure/unit_of_work.py)、[存储与迁移](../../src/taskweave/infrastructure/storage.py)、[控制库 SQL](../../src/taskweave/infrastructure/sql/control.sql)、[任务库 SQL](../../src/taskweave/infrastructure/sql/task-data.sql)、[环境用例](../../src/taskweave/application/environments.py)。

## 验证入口

`shared.storage`、相应 `repository.*`、`application.environments`、`ui.environments`。共享 SQL/UoW 变化用 changed dry-run 检查消费者；关注回滚、线程隔离、外键、旧库迁移和清理边界。只用临时数据库验证，不修改用户真实数据。关联：[执行](execution.md)、[上下文](contexts.md)。

## 按需深入

[存储迁移与结果](../reference/persistence-results.md)、[API与本地配置](../reference/api-and-configuration.md)。只在本次修改涉及相应契约时阅读。
