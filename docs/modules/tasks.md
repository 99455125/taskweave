# 任务与步骤

## 职责

管理任务定义、步骤顺序、编辑确认、复制与任务包导入导出。定义写入与运行记录分开；收藏和分类是独立组织信息。

## 当前流程

- TaskUseCases处理任务创建/更新/复制/删除和运行记录清理；StepUseCases负责步骤保存、校验、调试与确认。
- 任务流程树可把步骤组织成顺序、条件分支、条件循环和列表遍历；任务级流程保存使用定义哈希检查，并在正式执行前整体确认。线性旧任务继续按原确认规则执行。流程修改使任务级确认失效；步骤仍有各自的保存与确认状态。
- 步骤保存使用expected_hash保护并发编辑；确认对应当前内容和有效证据，修改定义使旧确认失效。批量确认先保存并校验全部步骤，再逐项确认；中途失败报告实际成功数并刷新持久状态。
- 导入完整校验任务包、引用与能力后事务写入新身份；失败回滚。复制保留步骤、材料组项及其顺序，不复制运行记录。
- TaskImportSession持有文件/文本模式、原始内容、文件代次和提交防重；文本入口上限2Mi字符，JSON文件上限32MiB。关闭只废弃旧视图结果，已接受写入继续完成。
- 步骤编辑器保留既有插件的能力子集及毫秒级超时，打开或切换步骤不改变定义；新选插件时加入其目录能力，移除插件时移除对应能力。
- TaskDraft保存任务配置的普通草稿；EditorSession管理步骤保存串行、保存版本及冲突。TaskTabTransition/WorkspaceNavigation提供保存、放弃、取消的导航决定，失败保留原草稿。
- CategorySession维护分类弹窗草稿；TaskOrganization串行更新收藏/分类，避免并发动作覆盖先前成功值。目录筛选由CatalogFilter持有，UI绑定输入事件。

## 代码与协作

| 责任 | 代码 |
| --- | --- |
| 任务/步骤用例 | [tasks.py](../../src/taskweave/application/tasks.py)、[steps.py](../../src/taskweave/application/steps.py) |
| 任务包校验与复制 | [task_transfer.py](../../src/taskweave/application/task_transfer.py)、[任务包契约](../contracts/task-packages.md) |
| 持久化 | [任务仓储](../../src/taskweave/infrastructure/repositories/tasks.py)、[步骤仓储](../../src/taskweave/infrastructure/repositories/steps.py) |
| 流程结构与编辑 | [task_flow.py](../../src/taskweave/core/task_flow.py)、[flow_editor.py](../../src/taskweave/presentation/flow_editor.py)、[flow_tree.py](../../src/taskweave/desktop/components/flow_tree.py)、[flow_controls.py](../../src/taskweave/desktop/components/flow_controls.py) |
| 普通交互 | [tasks.py](../../src/taskweave/presentation/tasks.py)、[editor.py](../../src/taskweave/presentation/editor.py)、[step_actions.py](../../src/taskweave/presentation/step_actions.py)、[task_import.py](../../src/taskweave/presentation/task_import.py) |
| UI装配 | [TasksPage](../../src/taskweave/desktop/pages/tasks.py)、[StepEditor](../../src/taskweave/desktop/components/step_editor.py) |

步骤字段与代码约束见[步骤契约](../contracts/steps.md)。任务输入和运行补参的归属见[执行模块](execution.md)。

## 验证定位

application.tasks、application.steps、ui.tasks、ui.editor；重点检查导入回滚、复制引用重映射、哈希冲突、确认失效、批量部分失败及导航保留草稿。用changed dry-run查实际消费者，不默认扩大为全量。
