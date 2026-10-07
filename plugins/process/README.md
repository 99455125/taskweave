# process 本地进程

可选安装：仓库根运行 `uv sync --locked --extra process`。插件 API v1、包版本 0.1.0，无额外第三方进程依赖，不安装外部工具。

环境或任务参数设置 `process_root`（任务参数优先）。工作目录、采集文件核对真实路径并限制在此根内；可执行程序可以是明确外部工具路径或 PATH 名称。命令不是安全沙箱，程序仍可能访问其他文件；不得执行不可信程序或使子进程后台化。

| 动作 | 输入与结果 | 效果 |
| --- | --- | --- |
| process.check_environment | programs（executable、可选 version_args）、directories；分项 available/error_code/version | READ，可重试 |
| process.run | executable、args、cwd（默认根）、env、env_secret_refs、stdin 或 stdin_secret_ref；真实 exit_code 与有界 stdout/stderr | WRITE，不可自动重试 |
| process.collect_artifacts | paths（1–100）、max_bytes、max_total_bytes；artifacts 和 total_bytes | READ，可重试 |

version_args 只用于用户明确指定的只读版本检查，不自动猜参数。可执行文件存在与版本命令成功分别报告。观察上下文 `process.environment` 和编写工具 `process.inspect_environment` 仅检查文件/程序可用性，不运行版本命令、不读取完整环境。每次最多观察 32 个程序和 32 个目录；上下文 items/views 遵守 max_output_bytes，超限丢弃完整观察行并提供 truncated/omitted_count。

命令默认超时 60 秒，范围 1–1800 秒。每流默认 65536 bytes，可设置 1024–1048576 bytes；两流持续排空，超限返回 `stdout_truncated`/`stderr_truncated`，文本按 UTF-8 解码。完整结果还包含 `duration_ms`。非零退出是实际执行结果，业务步骤必须检查 `exit_code`；不是业务成功声明。宿主动作预算允许最大命令超时及清理。

`env_secret_refs` 如 `{"CHILD_PASSWORD": "site_password"}` 的值是逻辑引用，宿主通过 secret_refs 的 `env:变量名` 映射解析；`stdin_secret_ref` 同理。不存在的引用报 `SECRET_UNAVAILABLE`，不启动命令。`stdin` 与 `stdin_secret_ref` 互斥。已解析秘密值在输出返回前字面替换为 `[REDACTED]`，跨读取块/预算边界也遮蔽；这不保证业务数据全面脱敏。默认日志只有退出码、截断标记、错误码，不打印 argv、环境、标准输入或输出。主机环境被子进程继承，明确 env 覆盖它；主机环境中未经秘密引用解析的值不在遮蔽保证内。秘密不得通过 argv 或普通 env/stdin 传入。

运行前取消无副作用；运行中取消/超时终止本次拥有的进程树并等待子进程退出。POSIX 使用新会话/进程组；主动 setsid/daemonize 的子进程会逃离进程组，因此不支持后台化命令。父进程已退出而后代仍持管道时，也按超时终止组。直接子进程由 asyncio 回收，孤儿后代的退出回收由操作系统父进程负责。Windows 使用暂停启动、kill-on-close Job Object 和线程恢复，先归属再运行；归属失败则终止未运行子进程并报 `PROCESS_TREE_SETUP_FAILED`。Windows 路径本轮未在 Windows 主机验证；受限宿主 Job 可能拒绝归属。不会终止用户已有工具进程。

库 `run_command(ctx, executable, args, *, cwd, env, stdin, timeout_seconds=60, max_output_bytes=65536)` 提供普通 Python 复用。库本身不要求 process_root，业务调用者须先验证自己的配置根。处理秘密时用 `RedactingContext(ctx, resolved_values)` 包装宿主上下文。`ProcessError` 的 code、result（部分输出）与 effect_state 供库调用者检查。process.run 在本 attempt 内保留最后失败命令的有界脱敏结果，通过可选 `failure_results` 钩子交给宿主保存为 `process.command_failure` JSON 诊断，可由结果引用读取。FAILED/UNKNOWN 和原 CANCELLED/PROCESS_TIMEOUT 错误码保持，诊断不成为成功步骤的业务输出。超时/运行中取消不等于回滚；外层 asyncio 取消完成清理后继续抛同一个 CancelledError，也携带最终部分 result 供诊断包装使用。

其他业务插件可独立复用 `CommandFailureEvidence(handler_id, result_name)`：插件实例拥有一个 evidence，动作以 `await evidence.run_command(ctx, action_id, executable, args, **options)` 调用进程库，插件 `failure_results` 委托 `evidence.failure_results(ctx, error)`，在自身 namespace 注册 `CommandFailureResultHandler`。handler_id/result_name 由业务插件指定，例如 wordpress.command_failure/wordpress_command_failure。无需启用 process 动作或跨插件 ctx.call；每实例只保留一个有界最后失败结果，按 scope.attempt_id 隔离。普通 run_command 的异常属性仍需消费者接入自己的诊断 hook 才会持久化。worker 被强制终止/丢失时不能保证插件 hook 有机会保存。

产物默认每文件和总计各 16 MiB，最高 64 MiB；完整文件超限拒绝，数量与预检总计超限时不暂存文件。符号链接不能越根，POSIX 文件打开使用目录描述符与 O_NOFOLLOW 防止路径替换。Windows 校验真实路径，但并发路径替换的 TOCTOU 防护未等同 POSIX；采集期间配置根不得由其他进程修改。文件内容可以含业务秘密，采集文件不作自动内容脱敏。

`stage_artifact(ctx, root, path, *, max_bytes)` 返回 token/name/media_type/size_bytes/checksum，不返回 local_path。`process.file` 的 ResultHandler 用宿主暂存 token 保存文件，宿主计算最终大小/摘要；调用采集动作并不等于保存。步骤显式声明 process.file 并纳入结果：

```python
async def run(ctx, inputs):
    collection = await ctx.call("process.collect_artifacts", {"paths": [inputs["report_path"]]})
    artifact = collection["artifacts"][0]
    return ctx.result(data=collection, outputs=[ctx.output("process.file", "report", artifact)])
```

验证入口：`uv run --extra process python -m unittest tests.test_process tests.test_devops_discovery -v`。macOS 的真实 Python 子进程测试不代表 Windows 或用户外部工具验收。

## 普通持久子进程库

新增 `OwnedProcessSession.start(ctx, executable, args, *, cwd, env, max_line_bytes=1048576, max_stderr_bytes=65536)`，返回有界 newline streams；`write_line(bytes, timeout_seconds=60)` 不接受内嵌换行，`read_line(timeout_seconds=60)` 返回去换行的完整 bytes，`stderr_result()` 返回先 known literal 脱敏再 clip 的捕获与截断标记，`close()` 幂等回收自有进程树。每读/写可用有限正数秒（最多1800，允许小数剩余预算）；行预算1024–1MiB，stderr预算同有限 runner。最多8帧缓冲，stderr持续排空，未完成行/超限行/队列失败即使 caller 空闲也由单一 cleanup owner 自动回收，避免 reader 等待自身死锁。

该普通 stdlib 库复用 runner POSIX独立进程组和 Windows suspended Job Object/terminate helper；不含 WeChat 身份、JSON协议、窗口或重试语义。消费方负责最终 close，不得让子进程 daemonize/移交所有权；单次读写超时/取消回收该 session，不能自动恢复或重放。跨平台真实 Windows Job 验证仍需 Windows 环境，macOS测试不能当作 Windows runtime证明。原 run_command 签名（包括必传 stdin）、三 registered actions、API v1/package0.1.0、默认依赖与既有有限 runner 保持兼容。
