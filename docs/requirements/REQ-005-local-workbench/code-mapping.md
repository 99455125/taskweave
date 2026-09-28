# REQ-005 代码映射

- `src/taskweave/desktop/contexts.py`：规划/步骤共享的上下文卡片、注释自动保存，以及插件 schema 驱动的通用目标选择；`planning.py`、`workbench.py` 连接对应服务。
- `src/taskweave/infrastructure/storage.py`：控制库 v14 事务迁移，旧组各生成一个采集项并从父表移除单次采集载荷；`repository.py`、`plan_repository.py` 保存组摘要与采集项内容。
- `context.capture.*` 与 `plan.context.capture.*`：按项追加、替换、删除、排序、改标题及按需读取；列表仅返回组和项摘要。
- `src/taskweave/application/planning.py`、`task_transfer.py`：规划 AI 冻结快照、导入任务以及任务包/任务副本对组和项的复制。
- `tests/test_context_cards.py`：编辑后操作前保存、失败重试、保存期间继续输入、乱序目标刷新、唯一目标自动选择和无目标扩展插件。

| 文件 | 职责 |
|---|---|
| src/taskweave/desktop/launcher.py | 回环服务、原生窗口、启动/退出、延迟构建 Application |
| src/taskweave/desktop/workbench.py | 一级导航、任务二级导航、编辑、运行、历史、插件、环境和设置 |
| src/taskweave/desktop/controller.py | 异步服务调用、幂等草稿保存、调试确认、AI 差异、模型连接配置 |
| src/taskweave/desktop/forms.py | schema 参数表单、参数定义编辑 |
| src/taskweave/desktop/security.py | HTTP / Socket.IO 启动凭据、Host / Origin 校验 |
| src/taskweave/infrastructure/runtime.py | 持久化间隔等待、暂停/取消与继续 |
| src/taskweave/infrastructure/storage.py | 总库 v3 自动备份迁移 |
| src/taskweave/infrastructure/repository.py | 任务复制/排序、环境列表、执行定义快照 |
| src/taskweave/core/validation.py | 步骤间隔字段与整数范围校验 |
| tests/test_interval_scheduler.py、tests/test_task_copy_lifecycle.py、tests/test_desktop_step_save.py、tests/test_control_db_migration.py、tests/test_model_secret_settings.py、tests/test_executor_recovery.py、tests/test_desktop_port.py | 按功能拆分的调度、保存、恢复与桌面端口检查 |
| tests/test_workbench_browser.py | 实际界面全流程与本机模型 fixture |

入口：taskweave workbench；运行见 [指南](usage.md)。Windows/macOS 各架构原生窗口与冻结包验收分开记录。

新增 src/taskweave/desktop/server_logs.py：日志缓冲、轮转、脱敏、独立窗口与实时查看；tests/test_model_logs.py：模型解析与日志检查。

`src/taskweave/desktop/display.py`：历史步骤快照名称、执行标题与界面元数据格式化；`tests/test_display.py`：历史名称、业务数据保留及会话标题验证。

`src/taskweave/desktop/chat.py`：网页回复解析；authoring.generate(export_only=True)：共享规范组合、插件渠道适配及无 API 导出；`tests/test_web_chat.py`：无密钥导出、历史边界及回复格式。

`tests/test_variables.py`：本地配置不修改系统、任务/环境/步骤输入优先级、正式/调试执行、必填环境变量及表单切换环境与空白行。

`Workbench.trial_variables`：三组可折叠变量、只读环境和步骤来源、任务运行输入；`start_trial`：环境切换与同环境重试分流；`DesktopController.repeat_trial`：当前任务输入覆盖历史输入。回归入口 `tests/test_trial_variable_groups.py`。

- 结果展示声明：`src/taskweave/core/result_views.py`、`StepResult.views`、任务 DB 内部 `__views` 元数据；插件注册 result_views，desktop 统一渲染。
- TiDB：`plugins/tidb`；查询与变量配置/上下文/AI/展示独立于核心。
- 上下文采集契约与预览校验：`src/taskweave/core/context_collection.py`；共享排序、重采集及预览卡片：`src/taskweave/desktop/contexts.py`；规划持久化与采集会话：`src/taskweave/infrastructure/plan_repository.py`、`context_sessions.py`。
- 任务分享：`src/taskweave/application/task_transfer.py`、task.export/task.import；environment.delete 保留历史记录。


任务运行清理：`task.clear_runs` → Application.clear_task_runs → Coordinator.clear_task_runs；任务列表确认入口 Workbench.clear_task_runs。验证：tests/test_task_cleanup.py。

工作台 pages/components 与共享桌面适配层的快速 targets、反向依赖及可选本机浏览器流程维护在 `tests/module-map.json`；页面模块可通过 `uv run python scripts/test_modules.py --module ui.tasks` 精确运行。
