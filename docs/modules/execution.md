# 执行与结果

## 职责与主链路

RunUseCases接受创建、启动、补参、重跑、控制、核对和结果查询；CoordinatorPool分配实例，Coordinator协调运行，WorkerTransport管理进程/消息，worker加载插件并实际执行步骤。执行状态与有效结果以持久化事实为准。

SequenceUseCases保存有序任务组合，SequenceDriver每次只推进一个普通正式运行。创建子运行与记录节点归属共用控制库事务；节点启动与补参等控制命令保留稳定ID，重启后按子运行事实接管。组合拥有的子运行只能通过组合入口改变生命周期。

## 当前行为

- 正式执行读取确认后的定义与版本快照。调试实例按任务复用，正式执行按运行隔离；实例池并发设置范围1–8。
- 输入由环境、任务值、步骤默认/显式覆盖及绑定解析；具体优先级见[步骤契约](../contracts/steps.md)。单步调试显式false、0和空字符串不等于未填写。
- 缺少必录输入时暂停并记录waiting_input身份；查看运行只显示手动补录入口。RunInputs/InputSubmission保留原始草稿、校验、防重及续启原命令；接受补录后离页仍完成后台续启。
- 从中间重跑要求前序成功，撤销起点及之后的有效输出；从头重跑重新建立资源。旧尝试保留为历史，不再冒作当前输出。
- command_id、命令指纹、锁、租约与回执共同防重复/冲突操作。副作用不确定进入UNKNOWN/人工核对，决策为completed或not_completed，不自动重发业务动作。
- 结束/清理判断同时核对活跃资源、租约与未保存录制，不能用历史成功状态推断可安全结束。

## 任务组合

桌面“任务组合”中按顺序添加已确认步骤的任务，同一任务可重复添加。每个目标任务输入或未绑定的步骤输入可选择固定JSON值、组合启动输入的JSON Pointer，或前序节点的指定步骤JSON输出。来源节点必须排在目标之前；命名输出仅接受JSON，文件输出不直接跨任务传递。

保存组合后填写启动输入并执行；若已保存组合的编排或映射又被编辑，执行按钮先保存当前草稿并检查版本冲突。组合状态显示就绪、执行中、等待输入、已暂停、需要处理、成功或已取消。等待输入可补参；失败可明确选步骤重试；不确定副作用先提供人工核对依据，再继续。暂停或取消后不会自动启动下一节点；离开页面不终止后台组合。任务/环境/插件与启动快照不一致时，当前节点启动前阻塞。完成节点释放工作进程和资源，结果与历史仍可查询；删除组合定义后，运行历史仍在组合页列出。

## UI与查询

RunCreation负责正式运行的任务/起点/输入选择和create→start流程；ExecutionInteraction管理选择、查询缓存与响应代次。步骤轨道选择只切换展示，执行到该步是单独显式动作。

详情查询在页面可见且有变化时刷新；运行日志独立于详情重绘。完整日志按需分页，增量日志默认关闭；run.events.page提供有界游标事件，游标不能跨运行使用。HistoryLoadState控制手动日志的在途与接纳，LogStreamState控制增量状态；离页/隐藏不继续向旧视图写入。

## 代码与验证

[运行用例](../../src/taskweave/application/runs.py)、[组合用例](../../src/taskweave/application/sequences.py)、[组合推进](../../src/taskweave/application/sequence_driver.py)、[运行端口](../../src/taskweave/core/run_ports.py)、[Coordinator](../../src/taskweave/infrastructure/run_coordinator.py)、[Pool](../../src/taskweave/infrastructure/coordinator_pool.py)、[通信](../../src/taskweave/infrastructure/worker_transport.py)、[worker](../../src/taskweave/infrastructure/worker.py)、[结果仓储](../../src/taskweave/infrastructure/repositories/results.py)。

测试键application.runs、repository.runs、repository.results、ui.executions、ui.results、ui.debug；检查命令幂等、输入身份/续启、资源隔离、UNKNOWN恢复、重跑有效性及文件/输出持久化。结果形状见[结果契约](../contracts/results.md)。
组合测试键application.sequences、repository.sequences、ui.sequences；覆盖映射、顺序、恢复、暂停竞争、补参、清理与页面离开。
