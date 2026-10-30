# 内部数据集与 Excel 实施计划

**Spec:** [设计](../specs/2026-10-28-dataset-excel-design.md)
**目标：**dataset 内部数据集与 excel 读取、新建、写入形成可运行链路。
**执行：**当前会话按用户“完成”要求连续实施；沿用已确认分工，不重复请求执行授权。主 agent 唯一写入公共文件；只读 agent 审查设计及最终差异。

## 约束与审核重点

保留当前已有修改；uv 管理可选依赖；只运行定向测试；不提交/push/PR。不修改实际用户数据。关键审核：跨运行/失效引用、SQL 访问边界、步骤提交原子性、Excel 覆盖与公式处理、包隔离。

### Task 1：宿主数据集端口与 dataset 插件

文件：core/dataset_contracts.py、plugins/sdk.py、core/ports.py；infrastructure/datasets.py、dataset_sql.py、storage.py、resource_sessions.py、worker.py、repositories/results.py；plugins/dataset/；tests/test_dataset_plugin.py。

接口：DatasetStore.create(name,columns,rows)、describe(ref)、read(ref,offset,limit)、query(sources,sql,params,name)、execute(ref,sql,params,name)，同步有界操作由动作调用；引用携带 kind/version/task_id/run_id/step_id/attempt_id/dataset_id。dataset.create/describe/read/query/execute 动作及 dataset.table handler。

- [x] 先测试创建、关联聚合、更新副本、空表、参数绑定和禁止 SQL，观察缺能力失败。
- [x] 实现验证/暂存、受控临时 SQL、原子落库与引用授权，验证成功后重启读取和失败不落库。
- [x] 验证结果查看/删除、运行隔离、失效 attempt、引用不在输入中时拒绝；重试保持前序数据。

验证：`uv run --extra dataset python -m unittest tests.test_dataset_plugin tests.test_step_outputs tests.test_storage_integrity -v`。

### Task 2：Excel 插件与真实链路

文件：plugins/excel/{pyproject.toml,src/taskweave_excel/}；tests/test_excel_plugin.py；pyproject.toml、uv.lock。

- [x] 先写读取/新建/区域写入/数据集导出及失败保护测试，观察缺能力失败。
- [x] 实现 inspect/read/create/write、文件根限制、原子发布、类型与公式策略、库警告保护。
- [x] 真实 worker 完成导入→SQL→导出→读取核对，验证跨步骤引用与普通模板样式/公式保持。

验证：`uv run --extra dataset --extra excel python -m unittest tests.test_dataset_plugin tests.test_excel_plugin -v`。

### Task 3：打包、知识同步与交付

文件：desktop/bundle.py、packaging/{macos,windows}/taskweave.spec、scripts/build_{macos.py,windows.ps1}；tests/test_data_plugins_packaging.py、test_plugin_architecture.py、test_macos_bundle.py、module-map.json；相关现行知识与插件 README。

- [x] 发现/可选依赖/收集验证先覆盖新增插件，再更新接入。
- [x] 同步现行事实，执行本次受影响测试、check_project.py、git diff --check。
- [x] 独立只读审核本次增量；修复重要问题并定向回归，记录实际结果与平台限制。

## 持久化进度

2026-10-28：已核对当前数据/结果/worker/插件链路。沿用混合工作区；此文为唯一实施进度，不使用要求 commit 的辅助脚本。用户明确要求完成两插件，授权覆盖本地实现与定向验证。实现选项和边界已在设计中标明为 agent 决策。

Task 1/2：数据集端口、插件及 Excel 读写已实现，核心两插件 19 项测试通过（包括实际 worker 导入→SQL→导出）。测试先观察缺能力失败；新增 Boolean-any 落库保真、NaN SQL 参数拒绝和异步取消防迟到写入均观察失败后修复。数据集/普通输出同事务失败回滚、原文件改变拒绝覆盖已验证。

定向旧回归：tests.test_step_outputs 4 项通过；tests.test_storage_integrity 4 项通过、test_state_only_does_not_create_task_db 失败。审计 sqlite3.connect 调用栈定位到已有 run_coordinator.py:573 在派发前 initialize(data.db)，与本次新增数据集暂存无关；不修改该既有流程或放宽旧断言。两插件/打包/插件架构/macOS接入合计44项首轮43过1失败，失败为清单计数仍为12，已随新增两插件更新为14，待复验。


## 最终验证与交付

Task 1、2、3：本次实现与知识同步完成。新插件维持 API v1，插件版本0.1.0，控制库/任务库版本不变；锁文件仅增加本次插件与 Excel 依赖。

- 两插件24项、插件边界与平台接入25项，共49项在最终相关回归中全部通过，包括真实worker Excel导入→SQL汇总→新建/写入→重读核对、失败不发布数据集、失效来源拒绝、跨进程Excel写入冲突。
- 最终定向命令：`uv run --no-sync python -m unittest tests.test_dataset_plugin tests.test_excel_plugin tests.test_data_plugins_packaging tests.test_plugin_architecture tests.test_macos_bundle tests.test_macos_packaging tests.test_step_outputs tests.test_plugin_contract tests.test_core_contracts tests.test_result_views tests.test_executor_recovery tests.test_storage_layering tests.repositories.test_storage_compatibility tests.test_module_selection -v`，93项，90通过、3项既有检查失败；日志 `/tmp/taskweave-dataset-excel-tests.log`。
- 3项失败：StorageLayeringTests.test_low_level_storage_initializes_without_domain_repositories 写死控制库版本17，当前实际为24；ModuleSelectionTests.test_all_mapped_targets_resolve_to_unique_test_ids 与 test_target_ids_have_no_module_method_overlap 均因已有 tests.test_flow_parallel 和其 ParallelFlowTests 类重叠（重复7项）。内存中移除本次新增两个模块后仍存在同一重叠，未改原测试或已有映射。
- 前期额外回归的 StorageIntegrityTests.test_state_only_does_not_create_task_db 失败原因见上文。合计记录4项范围外既有检查失败，没有通过跳过/放宽断言掩盖。
- `uv run python scripts/check_project.py`、`git diff --check`、`uv lock --check` 通过。新产品源码映射 dry-run 正确选择 plugins.dataset/excel。
- `uv build plugins/dataset --wheel --out-dir /tmp/taskweave-dataset-excel-wheels` 与对应 plugins/excel 命令成功。两个 wheel 位于上述临时目录；两平台spec收集测试通过，未执行完整macOS/Windows发布构建或Windows/Excel应用实机验收。

### 审查处理

独立只读审查发现4项Important，均在新增复现测试观察失败后修复：跨进程目标排他锁防止Excel并发丢失修改；SQL整行长度限制与合法数据集上限一致并包装源装载错误；选择不与用户列冲突的隐式行号维持顺序；按行身份保留修改副本中原布尔类型。相关新回归及最终49项接入检查均通过，无待处理审查Minor。

Ruling：SQLite隐式行号的三个别名同时被用户列占用时，execute明确拒绝并要求先query重命名一列；其余行序/类型可靠保留，代价是该少见列组合需额外转换步骤。Excel排他锁异常终止后保留，待确认进程/文件状态再清理；代价是异常退出后可能需人工恢复，不自动夺取未知写入锁。两者均已写入插件说明。

审查未判定为缺陷的事项：引用授权/有效来源、提交原子性与可重复清理已有实现及验证；公式缓存不由openpyxl计算，按已声明边界缺缓存时报错；既有提前建库检查失败留在本次范围外。没有修改用户数据/启用配置；沿用当前工作区保留已有工作。
