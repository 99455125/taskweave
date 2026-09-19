# 运行、锁与恢复

## 1. 应用命令

`create_run(task_id, inputs, environment_id, mode=EXECUTION)` → run_id，初始 READY。
`start(run_id, mode=NEXT|UNTIL|ALL, target_step_id?, command_id)` → command ack；UNTIL 包含目标，目标必须可达。
`pause(run_id, command_id)` 在当前步骤结束后停；`cancel` 请求协作取消，不代表撤回业务。
`retry_step(run_id, step_id, command_id)` 显式新建 attempt，先检查 side-effect certainty；UNKNOWN 默认拒绝。
`reconcile_attempt(attempt_id, decision, evidence, command_id)` 记录人工/插件查询证据，确认为已完成或未完成；不伪造原始观察记录。
`abandon_run` 释放租约并转 CANCELLED，保留 UNKNOWN 历史。新建一次运行重新使用当前已验证配置。

同 command_id 相同 body_hash 返回原响应；相同 ID 不同请求拒绝 COMMAND_CONFLICT。并发新 ID 由运行状态与全局租约阻止重复启动。预检查在读取资源前完成基本参数校验。

## 2. 状态表

| 当前 | 事件 | 下一状态 |
|---|---|---|
| READY | start 且获得租约 | RUNNING |
| RUNNING | 单步/UNTIL结束或暂停请求且还有步骤 | PAUSED |
| RUNNING | 所有目标及任务步骤完成 | SUCCEEDED |
| RUNNING | 动作确定失败/校验失败/结果保存失败 | FAILED |
| RUNNING | worker 失联/超时强制结束 | INTERRUPTED |
| PAUSED | continue，配置与资源预检查通过 | RUNNING |
| FAILED | 用户重试且失败可重试 | RUNNING |
| INTERRUPTED | 核对全部不确定尝试，恢复前置条件 | PAUSED |
| READY/PAUSED/FAILED/INTERRUPTED | abandon | CANCELLED |
| RUNNING | 协作取消确认，副作用结果已知 | CANCELLED |

SUCCEEDED/CANCELLED 终止，重跑创建新 run。尝试状态 RUNNING/SUCCEEDED/FAILED/UNKNOWN/CANCELLED，error.phase 区分 resolve/preflight/execute/verify/persist；RESULT_SAVE_FAILED 用 FAILED + effect_state=SUCCEEDED，不能按业务失败重跑。

## 3. 配置与会话锁

一条 durable runtime_lease 代表全局活跃 run，RUNNING/PAUSED/FAILED/INTERRUPTED 保留租约直到恢复或 abandon；避免浏览器会话被另一任务覆盖。READY 无租约，可有多个；获得租约时记录 definition_hash，后续比较不符则 RUN_CONFIG_CHANGED，不偷偷沿用新配置。

有租约的任务禁止保存配置，UI 可本地编辑未保存文本。调试修改需要先结束活跃运行，随后 TRIAL 单独获得租约。配置不保存历史版本；definition_hash 仅做一致性检测。未来子任务在启动前展开依赖集合并锁定相关配置，避免子任务运行中被编辑。

## 4. IPC 与 worker

命令 envelope：api_version=1、command_id、run_id、kind、payload。
事件 envelope：api_version=1、event_id、run_id、attempt_id?、seq（worker 内单调递增）、kind、timestamp、payload。
kind：AttemptStarted、ActionObserved、Log、AttemptPrepared、AttemptCompleted、AttemptFailed、Heartbeat。

协调器先在总库提交 attempt RUNNING，再发命令；worker 长期运行且单事件循环。只有宿主写总库，插件业务输出通过任务 store。队列消息丢失/重复需以 event_id 去重、receipt/数据库核对，不把日志事件视为成功提交。

默认每 2 秒心跳，10 秒失联进入核对；超时先请求取消，5 秒宽限后可终止 worker。退出后资源已丢失，未知副作用不自动重试。Windows 使用 spawn + main guard，启动单实例应用锁防止第二个协调器写入租约；不靠 SQLite 表独立替代操作系统进程锁。

## 5. 结果与恢复

1. 总库登记 attempt ID、输入摘要和 RUNNING。
2. worker 执行业务并 verify。普通 data 默认由核心写任务库；自定义结果由 handler 转为存储描述，由核心执行写入。
3. 有任务库结果：在任务库同一事务写结果和 receipt。文件先写 staging，flush 后 rename，再写 receipt；跨文件窗口可能留下未登记文件，启动时按 attempt 目录扫描后核对，不能自动重做业务。
4. 总库事务登记 ResultRef 和 attempt 状态；coord ack 后清理 staging。

没有业务结果时不创建任务库。若在业务成功到总库确认之间崩溃且无 receipt，则 UNKNOWN，必须查询外部状态。跨两个独立 SQLite 连接没有隐含原子事务。

所有返回的 data 默认持久化，不提供 retain_output 开关。后续步骤按绑定从任务库读取同一 run 内有效成功 attempt 的输出，不能依赖进程内存或读取其他运行的旧值。结果及 receipt 提交并在总库确认成功后才允许下游使用。缺失、失效或解析失败时阻止下游，禁止为取回单号自动重建单据。结果落库不等于浏览器会话可恢复，资源仍需插件重建。

重试或重跑某前置步骤会令下游有效输出失效，保留历史尝试。取消、暂停和回滚是不同概念；不承诺自动回滚外部业务。

## 6. 控制流与布局预留

TaskDocument 有 nodes、entry_node_id；每个节点有 id、kind、next、config。action.config 引用 step_id；condition.config={predicate,true_next,false_next}；loop.config={items_binding,body_task_id,max_iterations}；subflow.config={task_id,input_bindings}。条件/循环详细操作符和分支语义在 REQ-008 实现；基础版本遇到非 action 返回 UNSUPPORTED_NODE_KIND，不静默跳过。

attempt 使用 execution_path（例如 `/main/<node>/iteration/2/subrun/<uuid>/<node>`）与 parent_run_id 预留嵌套，不存步骤版本。基础顺序节点 next 指向下一节点或 null，校验 entry、可达、无环及节点 ID 唯一。布局独立为 ui_layout_json，不影响执行或验证 hash。分享保留模型及布局，导入后重映射 task/step ID。
