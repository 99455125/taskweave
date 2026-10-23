# 存储、环境与设置

## 持久化布局

工作空间由CLI --home、TASKWEAVE_HOME或平台默认位置选择；默认路径见[运行指南](../deployment.md)。

| 路径 | 数据归属 |
| --- | --- |
| `taskweave.db` | 控制库：任务/步骤、环境、运行/尝试、任务组合定义/运行/节点、引用/事件/回执/租约、规划/采集/生成、分类收藏 |
| `tasks/<task_id>/data.db` | 任务业务数据、输出与结果回执、插件表结构版本 |
| `tasks/<task_id>/` | 该任务的文件结果及相关本地文件 |
| `plans/` | 规划请求、回复与冻结材料等本地文件 |
| `plugins.json` | 当前工作空间显式启用的插件 |
| `workbench.json` | 工作台、模型请求预算、默认环境、隐私及执行容量等设置 |
| `model.json` | 桌面模型连接配置 |
| `exports/` | 用户显式导出的任务包和规划提示 |

数据库名/路径由[SQLiteStorage](../../src/taskweave/infrastructure/sqlite_storage.py)及对应结果/规划实现确定。控制库现行23、任务库2；sql/中的文件是初始DDL，最新结构还必须叠加sqlite_storage.py迁移，不能把初始user_version当作现行版本。v23 增加外部 AI 请求回执与不可变材料记录，定义写入与回执共用控制库 UoW；迁移保留任务、控制流、运行及结果，升级前自动备份，旧版本按 SCHEMA_TOO_NEW 拒绝打开新库。

## 边界与一致性

SQLiteStorage提供连接、迁移、路径及SQLiteUnitOfWork，不构造领域仓储。build_sqlite_repositories装配十一个语义仓储；同一UoW事务中的组合操作共享连接。跨控制库、任务库与文件不能假定全局原子性，必须保留回执、引用、恢复和文件清理规则。组合清理意图保存在控制库，未清理完的子运行仍保留归属保护。

迁移对已识别版本先备份再事务升级，更新PRAGMA user_version；过新或未知数据库报错。Store、Repository、PlanRepository是兼容适配，正常新消费者直接依赖规范存储/仓储接口，不通过通用SQL绕开用例。

## 环境与设置

EnvironmentUseCases管理公共配置、`env:NAME`秘密引用及变量说明；秘密在本机解析。保存入口不保证普通字符串秘密自动加密，隐私脱敏与本地存储是不同机制。环境被运行、规划或资源会话使用时，删除需服从依赖约束。

ApplicationSettings管理默认环境、模型、隐私、执行容量和工作空间迁移；迁移校验目标并遵守实例占用条件。工作空间位置切换与源数据移除有既定顺序，不能用复制文件代替正式用例。桌面环境/设置草稿分别由EnvironmentSession和SettingsSession拥有，平台窗口/文件动作仍在desktop。

## 代码与验证

[装配](../../src/taskweave/infrastructure/repositories/__init__.py)、[UoW](../../src/taskweave/infrastructure/unit_of_work.py)、[环境](../../src/taskweave/application/environments.py)、[设置](../../src/taskweave/application/settings.py)。

测试键shared.storage、repository.environments、application.environments、ui.settings；检查迁移版本、事务回滚、孤立结果/文件清理、环境秘密引用、活动依赖、迁移失败与原配置保护。配置字段见[配置契约](../contracts/configuration.md)。
