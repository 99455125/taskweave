# 存储契约

## 1. 位置与写入责任

```text
TASKWEAVE_HOME/
  taskweave.db
  tasks/<task_id>/data.db                  # 仅需要业务数据/receipt 时创建
  tasks/<task_id>/artifacts/<run_id>/<attempt_id>/
  tasks/<task_id>/staging/<attempt_id>/
```

总库仅任务/步骤配置、运行/尝试、状态/错误摘要、结果索引和兼容信息。有效业务输出在任务库；文件在任务目录。所有路径由宿主用 UUID 组成，核心存储适配器持有任务作用域，插件只提交结构和存储描述，不接收任意 db_path。

SQL 基线：[control.sql](contracts/control.sql) 与 [task-data.sql](contracts/task-data.sql)。SQLite foreign_keys=ON 每连接设置，busy_timeout=5000；显式短事务。大日志写文件，总库错误摘要上限 4096 字符，运行输入摘要脱敏，不保存 Token。

## 2. 表职责

| 总库表 | 内容 |
|---|---|
| tasks | 名称、输入 schema、节点图与布局 |
| steps | 当前 step_description/step_content、绑定、schema、验证 hash/state；无 revision |
| environments | 非秘密配置及凭据引用，秘密在本机凭据适配中 |
| task_runs | task、环境、模式、状态、定义 hash、父运行、输入摘要 |
| step_attempts | 每次尝试、执行路径、状态、effect_state、错误摘要、时间 |
| result_refs | handler、类型、相对位置、checksum；不存业务 payload |
| command_receipts | 命令去重与 ACK |
| runtime_lease | 单活跃运行会话 |

任务库宿主表：step_outputs（默认保存的 JSON）、result_receipts（完成/结果引用清单）；插件自定义表要求 `p_<plugin_slug>_` 前缀，行数据关联 run/step/attempt 或等价子表。文件 receipt 可使用同一任务库，因此截图任务可能为恢复创建小 data.db；纯状态且无持久化结果不建库。

input_summary 只用于审计。步骤 data 默认保存到任务库，不依赖内存传递；恢复时从库中读取。任务启动输入另行处理：凭据仅存引用，缺少启动参数时须补充，不能拿脱敏摘要当实际参数。

## 3. 没有步骤版本

steps 只一行当前内容，验证 hash 是变更检测字段；不存在 step_versions/revisions 表。修改覆盖当前内容并清空验证，执行记录保存 ID、内容 hash、时间和状态；REQ-005 / 总库 v3 在 task_runs.definition_json 保存执行时定义快照，不创建步骤版本或编辑修订历史。旧记录没有快照时不能还原旧代码。导入覆盖需显式选择，活跃任务禁止覆盖。

## 4. 初始化、迁移、删除和备份

每库 PRAGMA user_version=1 标识 schema。仅首次创建执行 DDL，之后按明确迁移文件逐级升级；未知高版本拒绝打开。迁移前 sqlite backup 到临时备份，迁移事务失败恢复原库。不在服务启动时自动生成迁移。

任务库惰性创建；已存在库打开失败不能当空库重建。删除任务要求无活跃 run：先 tasks.lifecycle=DELETING，清理/隔离任务目录后事务删除关联结果与记录，失败保留 DELETING 供重试；不先删除总库索引再遗留不可追踪文件。

备份暂停新写入并结束或明确暂停 worker 写操作，使用 SQLite backup API 配合拷贝产物/manifest；不能仅复制正在写的主 DB 文件而遗漏 journal/WAL。恢复整套总库+对应任务目录，校验 ID/manifest；不把另一任务的 data.db 随意关联到同名任务。

## 5. 错误与清理

RESULT_SAVE_FAILED 保留外部业务成功/未知状态；任务结果 receipt 与总库不一致按 attempt_id 核对，详见 [运行协议](runtime.md)。缺 handler 的结果保留可见引用。清理可以只删某次运行结果，不改步骤定义；删除运行引用前先完成对应 handler 清理或记录可重试墓碑。

## REQ-005 实施补充

总库 v3 新增 steps.delay_after_previous_seconds、tasks.sort_order、task_runs.definition_json / waiting_step_id / wait_until。原始 DDL 保持 v1 基线，基础设施按 v2→v3 逐级迁移并备份；任务库仍为 v2。新增字段默认间隔 0，旧步骤原有内容 hash 和验证状态保留；修改配置后照常重新验证。
