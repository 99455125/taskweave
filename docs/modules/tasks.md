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

## 画布编辑与步骤复用

节点“更多”菜单提供前后插入，空路径提供文字添加入口；连线不再常驻加号，只有拖动时显示落点。拖拽到落点会改变执行顺序或分支归属，布局自动调整。保存前校验显式输入依赖、条件引用及分支/循环作用域，失败保留原流程；合法重排同步步骤序号，后续保存不会恢复旧顺序。分支连线按节点实际几何位置绘制，空路径接入汇合点后继续后续流程。

节点和步骤菜单提供复制、拆分。复制生成新步骤及独立上下文材料身份；拆分以上下两份表单分别选择完整语句、上下文、输入输出，保留全文和 JSON 编辑。两份默认继承原输入和绑定；字段勾选同步更新 required 和输入绑定。原步骤保留身份及调试历史，新步骤紧随其后且没有历史记录。共用材料创建副本，手写草稿不被旧勾选覆盖；仍被引用的原输出字段不能删除。创建及材料分配在同一事务内完成，并核对任务、步骤与上下文快照。

拆分按代码、上下文、输入输出分类展示，每类上下对照两份；切换分类保留草稿。全文代码及 JSON 收入展开区，摘要、影响说明、错误与确认操作固定可达。提交时防重复并冻结输入；ESC 按项目约定可关闭窗口，已提交的保存继续完成。画布菜单移动失败保留目标和错误，拖拽显示可投放位置并在失败时保留原流程。

空任务、添加节点菜单和节点前后插入均支持“从已有步骤复制”，可选择当前任务或其他任务。外部步骤依赖须映射到目标任务中可用的步骤，或明确删除该绑定；删除绑定保留输入字段和代码，运行时沿用现有输入合并与补录规则。最终依赖仍须符合目标插入位置和作用域。来源步骤、材料及历史均不改写。

复用弹窗显示目标任务、分支与相邻节点；来源和映射选项可搜索并以序号区分重名，映射候选只提供目标位置可引用的前序步骤。完整绑定 JSON 仍为最终提交依据，保存时再次校验作用域和快照。

输入来源绑定按当前运行 / 调试环境列出环境配置字段，按任务输入 Schema 列出任务参数（包含没有默认值的字段），前序结果的 data 字段候选合并已保存的输出 Schema 与最近成功运行的数据，因此未运行时也能绑定声明字段；声明类型优先，历史结果补充字段和示例值。其他结果容器只读取各自的实际结果。选择字段时自动填充空的步骤输入名称，保留已有名称和手填路径；切换来源或环境会刷新候选与类型，不改写绑定路径。

输入和输出 Schema 的“高级 JSON”均可编辑，使用可滚动、可调整高度的多行编辑区；与字段表单共享定义，复杂结构继续在 JSON 模式编辑。

## 代码与协作

运行、调试和补录共用的 ValueForm 对同构对象数组提供逐行增删及类型录入；对象行内的简单字符串列表支持逐项增删，有枚举时多选。新行展示字段默认值，必录和可选仍由 Schema 决定，清空可选项后由运行代码处理缺省。扩展字段和非法草稿保留，提交时显示行/字段校验错误；复杂嵌套 Schema 使用 JSON 编辑。

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
