# SSH / SFTP

可选 API v1 插件，`package_version=0.1.0`。不修改任务包、持久化格式、SDK 必需方法或 UI。固定步骤不使用模型。安装同步：

```sh
uv sync --locked --extra ssh --extra process
```

Python 库依赖 `taskweave-process==0.1.0` 和 `asyncssh[bcrypt]==2.24.0`，不要求启用 process 或 SSH 动作后才能被其他业务插件导入。AsyncSSH 支持 Python >=3.10，bcrypt 支持加密 OpenSSH 私钥；依赖依据：[官方 PyPI](https://pypi.org/project/asyncssh/2.24.0/)、[官方文档](https://asyncssh.readthedocs.io/en/latest/)。

## 配置与身份

配置从 environment/task_parameters 合并，任务参数优先。动作参数只能引用 logical secret，秘密映射由宿主的 `secret_refs`（例如 `{"ssh_password": "env:SSH_PASSWORD"}`）和 `ctx.resolve_secret` 提供。

| 变量 | 说明 |
| --- | --- |
| `ssh_host` | 必填目标主机，不是 URL；不包含凭据 |
| `ssh_port` | 整数 1–65535，默认 22 |
| `ssh_username` | 必填远程用户名 |
| `ssh_remote_root` | 必填绝对 POSIX 路径；连接时通过 SFTP 核对真实目录 |
| `ssh_known_hosts` | 已有 OpenSSH known_hosts 文件；默认 `~/.ssh/known_hosts`；不存在/空值/None 都拒绝连接 |
| `ssh_password_ref` | 密码的逻辑秘密引用；未配置时不尝试密码认证 |
| `ssh_key_path` | 可选本地私钥路径，支持 `~` |
| `ssh_key_passphrase_ref` | 加密私钥口令的逻辑秘密引用 |
| `ssh_use_agent` | boolean，默认 false；true 明确启用 SSH Agent |
| `ssh_agent_path` | Agent socket；启用 Agent 时默认取 `SSH_AUTH_SOCK`；缺失拒绝 |
| `ssh_local_root` | upload 必需本地根；源文件真实路径必须在该根内 |
| `ssh_timeout_seconds` | 连接阶段超时 1–1800 秒，默认 60；动作超时使用动作参数 |

始终校验 known_hosts，主机身份不符报 `SSH_HOST_KEY_INVALID`，不降级为 `known_hosts=None`，不自动添加主机 key。使用非默认端口时文件记录应为 `[host]:port`。认证失败 `SSH_AUTH_FAILED`、连接超时 `SSH_CONNECT_TIMEOUT`、其他连接错误 `SSH_CONNECT_FAILED` 分别报告。禁用 OpenSSH 配置文件自动加载、默认私钥发现、Agent forwarding 和交互认证；显式 key、Agent、密码按客户端认证机制使用。缺失秘密引用在连接或命令开始前失败，异常消息不回显密码/口令。

## 动作

全部动作 schema 拒绝未知字段，默认 `role="default"`；资源 `ssh.connection` 按 role 由宿主持有和关闭。角色标识是资源生命周期键，当前使用同一组 ssh 配置，不用于选择另一套凭据。连接对象不返回 JSON。

| 动作 | 参数与结果 | 效果 |
| --- | --- | --- |
| `ssh.check_connection` | 握手/认证 + SFTP 根核对；返回 target/server_version，无命令探针 | READ |
| `ssh.exec` | 必填 argv 数组；cwd 默认 `.`、env、env_secret_refs、stdin 或 stdin_secret_ref；返回通用命令结果 | WRITE |
| `ssh.run_script` | 必填 script，显式 `/bin/sh -c`；其余同 exec | WRITE |
| `ssh.stat` | path；返回 path/size_bytes/type/permissions/mtime；type 为 SFTP 类型码 | READ |
| `ssh.list_directory` | path 默认 `.`，max_entries 默认 100（1–1000）、max_output_bytes；返回 entries 和 truncated | READ |
| `ssh.read_file` | path、encoding=text/base64、max_bytes；完整文件 content/size_bytes/checksum，非法 UTF-8 text 报错 | READ |
| `ssh.read_logs` | path、cursor 默认 0、max_bytes 默认 65536（1–1048576）；content、下一字节 cursor、truncated、rotated | READ |
| `ssh.checksum` | path、max_bytes；完整有界文件 SHA-256、path/size_bytes | READ |
| `ssh.upload` | local_path、remote_path、overwrite 默认 false、max_bytes、可选预期 SHA-256 checksum | WRITE |
| `ssh.download` | remote_path、max_bytes、可选 basename name；返回 artifact 元数据 | READ |
| `ssh.mkdir` | path；只创建一个目录，父目录需已存在 | WRITE |
| `ssh.move` | source、destination、overwrite 默认 false；返回目标 path | WRITE |
| `ssh.remove` | path、recursive 默认 false；递归必须显式，返回 removed_count，禁止删除配置根 | WRITE |

命令返回 `exit_code/stdout/stderr/stdout_truncated/stderr_truncated/duration_ms`；真实非零退出保留为结果，业务调用者必须检查。默认每流 64 KiB，范围 1 KiB–1 MiB，持续排空并单独报告截断；UTF-8 输出仍遵守字节预算。命令 timeout_seconds 默认 60，范围 1–1800；从 run 入口计时，cwd 的 realpath/stat、process 创建与执行共用一个 deadline 并检查取消。远程 exec 必经服务器 POSIX shell，argv/cwd/env 用 POSIX quoting 保持字面值；运输层要求远端 env 支持 `--` 结束选项（GNU/BSD env），防止 executable 被解释为 env 标志；`run_script` 是独立的显式脚本执行能力。env_secret_refs 为远程变量名→逻辑秘密引用；stdin_secret_ref 与普通 stdin 互斥。已解析秘密在输出截断前替换为 `[REDACTED]`，包括跨预算边界的完整值；不记录命令、参数、环境或输出内容。经变形/编码的值、未经引用解析的主机环境和业务文件内容不属于全面脱敏保证。

文件默认 16 MiB，max_bytes 最多 64 MiB；完整读取超限拒绝，不把截断文件当成功。upload 检查本地真实路径/SFTP 远程真实路径，独占创建同目录 `.taskweave-<uuid>`，验证远程临时文件的 SHA-256，再使用 SFTP 普通 rename（flags 0）发布。默认发布在最终 rename 时也拒绝已有目标，预检之后并发出现的目标保持原内容。overwrite=true 使用服务器的 posix-rename 扩展；不支持时失败，不先删除目标做替代。失败清理本次临时文件；网络中断时可能无法确认清理，诊断明确保留 `temporary_cleanup_unconfirmed`。download 通过 `allocate_file` 暂存并计算实际摘要，没有任意本地目标写入。

read_logs 的 cursor 是原始字节偏移；超过当前文件大小重置为 0 并返回 rotated=true。UTF-8 非法/跨读取边界字节以替换字符显示；同大小轮换无法凭偏移识别。业务文件/日志不自动脱敏。

路径核对配置根、realpath、实际存在组件、父目录与符号链接；根内的 remove/move 操作保留链接自身语义，递归删除不会跟随链接删除其目标。越根链接拒绝。客户端 SFTP 路径检查不是服务器沙箱，也不保证抵御恶意服务器或并发替换父目录；远程任意命令同样不是按文件系统根隔离的执行沙箱。配置根应由可信管理者保持稳定。

## 取消、超时与结果保存

开始前取消不运行命令。cwd核对阶段取消/超时保留 NOT_STARTED、result=None，不创建命令诊断；命令请求发出后仍按 UNKNOWN 保存有界部分输出。握手外层取消先取消未完成连接任务，再恢复并关闭同时完成的连接归属。命令超时/取消尝试 terminate 当前 channel 并关闭本次连接，保留有界脱敏的部分 stdout/stderr；远程服务器可能忽略信号，关闭连接不等于回滚，业务副作用为 UNKNOWN。只关闭本次资源，不操作用户已有 SSH 会话或工具。

SFTP 写操作接收已发请求的回复归属再清理本次临时文件；取消清理最多等待未完成请求 5 秒，再关闭本次连接以解除网络等待。递归删除保留完成计数与最多 100 个完成路径；传输保留已确认字节进度；download每个收到的完整块都更新进度，取消/超时可保存部分字节诊断，但完整读取前不allocate_file、不产出成功或不完整artifact。任何写操作不自动重试。

READ download 取消保持宿主原有 run/attempt=CANCELLED、effect_state=NOT_STARTED；其诊断里的 UNKNOWN 是运输库的保守标记，不改变 READ 为 WRITE，也不改宿主状态规则。插件自己的 `failure_results` 保存 `ssh.command_failure` 或 `ssh.transfer_failure` JSON 诊断，不改变宿主原有失败/取消状态（WRITE 为 FAILED/UNKNOWN，READ 下载取消为 CANCELLED/NOT_STARTED）。诊断按 scope.attempt_id 隔离，不是成功 receipt 或步骤业务输出；真实 worker 测试经 Repository 的 read_result 检索诊断，并验证 read_output 仍不可用。强制杀死 worker/进程或宿主无法执行失败 hook 时不能保证保存。

下载保存需在步骤中明确纳入 outputs：

```python
async def run(ctx, inputs):
    downloaded = await ctx.call("ssh.download", {"remote_path": inputs["report_path"]})
    return ctx.result(data=downloaded, outputs=[
        ctx.output("ssh.file", "report", downloaded["artifact"])
    ])
```

artifact 为 `token/name/media_type/size_bytes/checksum`，不包含 local_path；`FileResultHandler` 复用普通 Python 库，宿主实际保存文件。`ssh.inspect_server` 编写工具与 `ssh.server` 上下文只做 SFTP 目录观察，不执行命令；仅暴露目标 host:port、目录项与截断标记，不带凭据，模型 items 与 view 共用字节预算。

## 供 WordPress 等消费者复用

```python
from taskweave_ssh import connect_ssh, SshSession

session = await connect_ssh(ctx, {
    "host": "example.internal", "port": 22, "username": "deploy",
    "remote_root": "/srv/site", "known_hosts": "/trusted/known_hosts",
    "key_path": "/trusted/deploy_key", "key_passphrase_ref": "deploy_passphrase",
})
try:
    result = await session.run(ctx, ["wp", "core", "version"], cwd=".", env={},
                               stdin=None, timeout_seconds=60, max_output_bytes=65536)
    path = await session.resolve_path("reports", must_exist=True)
finally:
    await session.close()
```

公开接口是 `async connect_ssh(ctx, config: dict) -> SshSession`、`async SshSession.run(ctx, argv: list[str], *, cwd: str, env: dict, stdin: bytes | None, timeout_seconds: int=60, max_output_bytes: int=65536) -> dict`、`async SshSession.resolve_path(path: str, *, must_exist: bool) -> str` 和 `async SshSession.close() -> None`。config 使用上表去掉 `ssh_` 前缀的键，不接受未知键。消费者拥有自己创建的会话、关闭它，并独立接入自己的失败诊断 hook；不能借用 SSH 插件的 role 资源或 `ctx.call`。命令异常 `SshError` 派生于公共 ProcessError，保留 `code/result/effect_state`，外层 CancelledError 同样携带安全部分 result 并继续取消语义；宿主不会自动持久化这些异常属性。消费者可复用 `CommandFailureResultHandler` 注册自己的 namespace，然后通过自己的 failure_results 返回 ResultRequest。

## 验证

```sh
uv run --extra ssh --extra process python -m unittest tests.test_ssh tests.test_devops_discovery -v
```

临时真实本地 SSH/SFTP server、真实 shell 命令、加密私钥和 `/usr/bin/ssh-agent`；不连接生产主机，不证明生产服务器权限、网络、POSIX shell/posix-rename 支持。未安装外部工具或项目依赖，未运行 OCR、GUI 或全量测试。
