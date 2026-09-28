# 运行控制、间隔与恢复

实现：[运行用例](../../src/taskweave/application/runs.py)、[runtime](../../src/taskweave/infrastructure/runtime.py)、[worker](../../src/taskweave/infrastructure/worker.py)、[运行仓储](../../src/taskweave/infrastructure/repositories/runs.py)。

## 命令和状态

run.create 创建 READY，不执行业务，也不以 command_id 去重创建；start 才启动尝试。run.start 的 ALL/NEXT/UNTIL（包含目标）、target_step_id、retry_step_id 以及 control 的 pause/cancel/abandon 由当前路由/用例定义。重复同 command_id 和同请求返回原响应，同 ID 不同 body 拒绝 COMMAND_CONFLICT；网络重试应重用原命令 ID。

| 状态/动作 | 行为 |
| --- | --- |
| READY → start | 检查定义、输入、插件/资源及容量后运行 |
| RUNNING → pause | 在安全步骤边界停止；不是撤回当前业务动作 |
| NEXT/UNTIL 到达边界 | 尚有后续步骤时 PAUSED；完成整个目标流程时按协调器判定 SUCCEEDED |
| 缺少必录输入 | PAUSED + request_json.waiting_input + InputRequested；动作前停止，不制造失败 attempt |
| 确定失败 | FAILED；记录错误 phase 与 effect_state |
| worker 失联/强制终止 | INTERRUPTED；无持久化成功证据的尝试为 UNKNOWN |
| cancel / abandon | 协作取消/释放资源；不是外部业务回滚 |
| reconcile | completed/not_completed 核对，说明可为空；保留原观察，不虚构丢失的输出 |

尝试状态与运行状态分开：RUNNING/SUCCEEDED/FAILED/UNKNOWN/CANCELLED；effect_state 为 NOT_STARTED/SUCCEEDED/FAILED/UNKNOWN。结果保存失败不能简单当作业务没发生，禁止自动重做副作用。常规 UNKNOWN 重试需核对；调试反馈中的显式保留会话重试是受用户确认的专用路径，保留原证据及 USER_RETRY_WITH_RETAINED_SESSION，不泛化为自动重试。

## 实例、锁与资源

调试实例按任务隔离复用，正式实例按 run 隔离；池容量设置1–8、默认8，超限 EXECUTOR_CAPACITY，不自动排队。每实例保持自己的 worker/锁/资源，单条运行内仍顺序执行；旧“全局唯一活跃运行”规则已被替代。

worker 使用 spawn 与固定事件循环，IPC 不传数据库连接或浏览器对象。应用 OS 锁保护同一工作空间；恢复在持锁后处理旧租约，不把残留租约当活资源。暂停或成功可保留资源；显式结束释放但不改写成功历史，can_end 根据实际资源/租约派生。不同环境不能直接复用旧调试浏览器。

## 间隔、补录、重跑

间隔按同一次运行前序有效成功 finished_at 计算并持久化等待截止时间，不在 UI sleep；首步不等，失败/未知前序不启动下一步，单独调试不要求前序等待。等待可暂停/结束，重启不能重新从零计算间隔。

API defer_inputs 默认false保持旧严格校验；UI可启用分阶段补录。run.inputs 校验当前 request 并幂等写入任务及可选 step_inputs；首步可联合补录，之后 run.start 保持原 mode/target 继续。initial_inputs/initial_step_inputs 保持原始命令幂等比较。提交不得覆盖既有绑定值。请求 ID 去重弹窗，取消仍暂停。

run.restart 在同一运行中重跑，start_step_id 可选；起点前必须成功。中间重跑保留前缀及资源，清理目标范围旧有效结果/相关输入；从头清理并重建资源，保留本次任务输入。历史尝试的保留或清除按具体重试/重置入口实现，不把“所有重跑都新建run”写成规则。run.delete 只删除指定运行，执行中先结束，其他运行和任务保留。

## 结果提交与恢复

总库先登记 attempt；worker 执行业务，任务库原子提交结果和 receipt，协调器再确认总库状态。文件经过当前作用域 staging、落位和引用登记；跨两个 SQLite 库和文件系统没有共同原子事务。无结果状态操作可不创建任务库。

worker 超时/超过10秒无心跳后请求取消；当前宽限1秒，仍未结束则强制停止并查 receipt。receipt 可恢复确认，没证据时 UNKNOWN；日志不是提交凭证。恢复页面资源仍需插件重建和业务预检查，不能从 DB 还原活页面。

事件包括动作观察、日志、尝试准备/结束、心跳和输入请求；精确 envelope 以 worker/runtime 为准，旧设计事件名不是兼容承诺。执行测试覆盖幂等、不同run隔离、重启、间隔、补录和副作用核对，见 [执行模块](../modules/execution.md)。
