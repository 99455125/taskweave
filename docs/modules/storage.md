# 存储、环境与设置

## 持久化布局

工作空间由CLI --home、TASKWEAVE_HOME或平台默认位置选择；默认路径见[运行指南](../deployment.md)。

| 路径 | 数据归属 |
| --- | --- |
| `taskweave.db` | 控制库：任务/步骤、环境、运行/尝试、任务组合定义/运行/节点、引用/事件/回执/租约、规划/采集/生成、分类收藏 |
| `tasks/<task_id>/data.db` | 任务业务数据、输出与结果回执、插件表登记 |
| `tasks/<task_id>/` | 该任务的文件结果及相关本地文件 |
| `plans/` | 规划请求、回复与冻结材料等本地文件 |
| `plugins.json` | 当前工作空间显式启用的插件 |
| `workbench.json` | 工作台、模型请求预算、默认环境、隐私及执行容量等设置 |
| `model.json` | 桌面模型连接配置 |
| `exports/` | 用户显式导出的任务包和规划提示 |

数据库名/路径由[SQLiteStorage](../../src/taskweave/infrastructure/sqlite_storage.py)及对应结果/规划实现确定。[control.sql](../../src/taskweave/infrastructure/sql/control.sql)与[task-data.sql](../../src/taskweave/infrastructure/sql/task-data.sql)分别定义完整现行结构，新库直接按DDL初始化。运行时校验已有表、索引等结构，差异报告 `SCHEMA_MAINTENANCE_REQUIRED`，不执行历史版本迁移。控制库保存组合流程、游标、执行实例、路径命令队列及外部AI回执；定义写入与回执共用控制库UoW。

## 边界与一致性

SQLiteStorage提供连接、结构初始化/校验、路径及SQLiteUnitOfWork，不构造领域仓储。build_sqlite_repositories装配十一个语义仓储；同一UoW事务中的组合操作共享连接。跨控制库、任务库与文件不能假定全局原子性，必须保留回执、引用、恢复和文件清理规则。组合清理意图保存在控制库，未清理完的子运行仍保留归属保护。

Store、Repository、PlanRepository仍是现有调用者使用的仓储适配；正常新消费者直接依赖规范存储/仓储接口，不通过通用SQL绕开用例。`revision`用于并发冲突检测，`content_hash`及确认哈希用于判断内容与验收的一致性，均保留其业务作用。

历史数据通过[显式维护脚本](../../scripts/maintain_current_schema.py)在新目标库收敛为现行结构，源库只读，目标已存在时拒绝覆盖。控制库维护转换已知历史流程与冻结定义，转换的任务流程重新进入待确认状态；未知字段、无法确定的转换或不满足离线维护条件的运行状态均报错。任务库维护保留业务表、数据及索引，移除插件登记表的旧版本列。脚本校验结构、外键与完整性后才发布目标文件；它不切换工作空间，也不复制任务文件、规划材料或配置。命令与适用范围见[运行指南](../deployment.md#数据库结构维护)。

插件表登记只保存表名，供结果及运行清理使用。handler声明当前列与索引，宿主校验并建表；已有列与声明不符时报告 `TABLE_SCHEMA_MISMATCH`，数据转换须显式维护。插件API和包版本仍按[插件契约](../contracts/plugins.md)检查。

## 内部数据集

内部数据集由宿主 [Datasets](../../src/taskweave/infrastructure/datasets.py) 暂存，步骤成功时与普通输出及回执同事务提交。每个数据集使用独立 `p_dataset_` 表，列名/类型/行序元数据归属于同一 attempt；既有表结构登记用于运行清理。结果读取/删除复用结果仓储，数据集删除同时清理表与元数据。这些动态业务表使用任务库的现行登记机制。

数据集引用只在同任务/运行内流转；前序引用必须来自已解析步骤输入且来源仍有效成功。SQL通过 [dataset_sql.py](../../src/taskweave/infrastructure/dataset_sql.py) 在仅装载明确输入的内存库中执行，操作产生新快照；不把任务数据库连接交给插件。对外数据库连接仍由 TiDB 等插件负责。用户操作见[内部数据集](../../plugins/dataset/README.md)。

## 环境与设置

EnvironmentUseCases管理公共配置、`env:NAME`秘密引用及变量说明；秘密在本机解析。保存入口不保证普通字符串秘密自动加密，隐私脱敏与本地存储是不同机制。环境被运行、规划或资源会话使用时，删除需服从依赖约束。

ApplicationSettings管理默认环境、模型、隐私、执行容量和工作空间迁移；迁移校验目标并遵守实例占用条件。工作空间位置切换与源数据移除有既定顺序，不能用复制文件代替正式用例。桌面环境/设置草稿分别由EnvironmentSession和SettingsSession拥有，平台窗口/文件动作仍在desktop。

## 代码与验证

[装配](../../src/taskweave/infrastructure/repositories/__init__.py)、[UoW](../../src/taskweave/infrastructure/unit_of_work.py)、[环境](../../src/taskweave/application/environments.py)、[设置](../../src/taskweave/application/settings.py)。

测试映射见[模块导航](../maintenance.md)与[测试指南](../testing.md)。配置字段见[配置契约](../contracts/configuration.md)。
