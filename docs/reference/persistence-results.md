# 持久化、迁移与结果协议

现行来源：[storage.py](../../src/taskweave/infrastructure/storage.py)、[UoW](../../src/taskweave/infrastructure/unit_of_work.py)、[仓储装配](../../src/taskweave/infrastructure/repositories/__init__.py)、[结果视图](../../src/taskweave/core/result_views.py)。

## 数据布局与 schema

home/taskweave.db 保存配置、运行和引用；home/tasks/<task_id>/data.db 按需保存结果；同任务目录的 artifacts、staging、backups 管理产物及恢复材料。规划文件由 home/plans 配置给 PlanningService，不经仓储私有 root 获取。路径由宿主作用域构造，插件不能指定任意数据库路径。

| 数据 | 责任 |
| --- | --- |
| tasks / steps / environments | 当前定义、schema、绑定、确认/hash、环境配置；不是步骤版本树 |
| task_runs / step_attempts | 运行快照、实际输入、请求、等待、尝试与人工核对/有效性 |
| runtime_lease / command_receipts / run_events | 实例占用、命令幂等和事件 |
| result_refs | task/run/step/attempt 关联、处理器、位置/摘要及可用状态；不塞完整业务payload |
| plans / plan_generations | revision、配置、候选、冻结证据索引及导入回执 |
| step_contexts / plan_contexts | 组元数据、顺序及修订控制 |
| step_context_captures / plan_context_captures | 完整一次采集的items/views/request/来源/时间/顺序 |
| 任务库step_outputs / result_receipts / plugin_table_schemas | 按尝试的命名输出、提交证据和插件表版本 |

当前控制库v14、任务库v2。SQL资源是初始DDL，完整现行结构是 [control.sql](../../src/taskweave/infrastructure/sql/control.sql)、[task-data.sql](../../src/taskweave/infrastructure/sql/task-data.sql)加storage.py的显式迁移，不能把初始SQL单独当v14。

迁移脉络：v2运行输入/请求/有效性/核对/事件；v3间隔/排序/定义快照/等待；v4确认来源；v5步骤上下文；v6多实例租约；v7编写说明；v8环境说明；v9描述字段规范；v10规划/上下文/生成；v11步骤上下文说明；v12请求/预览/顺序/时间及规划说明；v13规划导入来源；v14组项分离并移除父表旧载荷。任务库v2为插件表版本。

已有未知版本拒绝打开：SCHEMA_TOO_NEW/SCHEMA_UNRECOGNIZED；不将损坏库当空库重建。每连接外键开启、busy_timeout=5000；迁移前SQLite backup，显式事务失败回滚，保留备份，不动态生成迁移脚本。

## 事务与跨介质边界

共享UoW以BEGIN IMMEDIATE开启外层事务，内层用savepoint：内层失败回滚并抛出，外层捕获后可提交其他写入，异常穿透则全回滚；内层成功不提前提交。当前事务内的仓储/兼容门面读取必须看到未提交写入，其他线程看不到。连接不得跨worker传递。

步骤与任务图、任务参数与确认失效、上下文批次与revision、环境删除与引用解除须保持组合一致性。不把模型/采集/文件操作塞进数据库长事务。复制导入失败保留源对象且无半个目标。跨库/文件失败沿receipt与DELETING等生命周期核对；任务删除先标记、再处理目录、再删引用，不先丢索引。

备份原则：停止新写入并协调worker，SQLite backup加对应产物与manifest，不裸拷贝正在写入的DB而漏journal/WAL。整套恢复要校验ID和关联，不能用同名任务替换别的data.db。现有迁移备份不等于已交付一键整机恢复UI；平台恢复演练见 [发布验收](../release-checklist.md)。

## ResultHandler 与结果展示

StepResult包含data、outputs和views。普通data默认持久化；ResultRequest(handler_id,name,payload)经handler.prepare产生json/table/file描述，宿主管理事务、校验、存储、索引和删除。handler仅提供schema/prepare/parse/preview，不接收数据库连接或实现persist/delete。缺处理器保留索引，读取报能力缺失；保存失败不能重做业务。

自定义表前缀p_<插件ID规范化>_，宿主注入run/step/attempt；列限TEXT/INTEGER/REAL/BLOB，声明版本、加列和索引迁移，禁止任意SQL及删列/改类型。升级前备份，结构与数据失败回滚；高于已支持的表版本拒绝。大数据可用表引用，不要求在data复制一遍。

StagedFile.local_path只给本地插件写文件；对外返回token，宿主验证归属和路径/符号链接。仅执行ctx.output不会保存，须加入ctx.result(outputs=...)。无data和持久化产物可不建任务库；文件receipt可能需要小任务库，不能把“无表格”推断为“不建库”。

views为`{title,renderer,pointer}`，pointer指向data中的字段；内部__views以version=1保存在同一结果事务，不作为普通业务输出引用。核心renderer为core.json/table/report/image，插件声明同类命名空间renderer。报告支持passed/message、多tables及query_info。

结果页按声明建页签并保留原始JSON，不自动把每个已存文件建成页签。图片支持当前尝试的名称/结果ID、output/capture引用及Base64；旧staging UUID只在唯一图片时兼容，歧义不猜、未落盘不可恢复、不允许任意本机路径。失败诊断产物不产生成功receipt，也不把失败标成功。

## 旧项目数据边界

更早项目的step_content曾表示自然语言目标、step_sql表示SQL；不能把旧目标字段直接当python-async-v1执行。旧task.db_server/task_<id>.db_server不属于本工程自动迁移链，保留原数据。当前schema迁移仅升级本工程已识别的版本，不承诺把旧Excel/Flask/SQL耦合模型直接转换；提取纯逻辑仍需验证当前接口。
