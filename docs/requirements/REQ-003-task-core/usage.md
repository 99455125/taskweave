# REQ-003 使用与接口测试

本需求交付可运行的 Python 应用、CLI 和本地 HTTP API。没有 UI，也不包含 Playwright；默认注册两个本地示例插件 demo/text，用于验证通用调用。只运行你信任的步骤代码，Python 内容校验不是安全沙箱。

## 1. 开发机启动

```bash
uv sync --locked
uv run taskweave --home .runtime/req003-demo demo
```

项目使用 uv 管理 Python 和依赖，无需激活虚拟环境。演示创建五步任务，逐步试跑、确认后执行；第一步完成后替换 worker，第五步从任务 DB 读取订单号。输出应包含 `status=SUCCEEDED` 和 `received_order_id=ORD-1001`，同时打印数据库路径。

这是开发机运行方式；受限 Windows 虚拟机的免安装 EXE 随包交付属于 REQ-007。

## 2. 本地接口

```bash
uv run taskweave --home .runtime/workbench serve --port 8765
```

服务打印地址和本次 token。把 token 设置到另一个终端的 `TASKWEAVE_API_TOKEN` 环境变量；也可以启动前设置固定的本地 token。接口只监听 127.0.0.1；请求必须携带 Bearer token 和 application/json，不开放浏览器跨域请求。

请求文件 `examples/req003/create-task.json`：

```json
{
  "operation": "task.create",
  "params": {"name": "我的任务"}
}
```

```bash
uv run taskweave request examples/req003/create-task.json
```

所有请求 POST 到 `/api`：`{"operation":"...","params":{...}}`。成功返回 `{"ok":true,"result":...}`，错误返回 `{"ok":false,"error":{"code":"...","message":"..."}}`。CLI 错误退出码为 1。

完整接口演示（服务启动后执行）：

```bash
uv run python examples/req003/api_walkthrough.py
```

该脚本实际通过 HTTP 完成创建、试跑、确认、执行和结果查询。

## 3. 常用操作

| operation | params |
|---|---|
| task.create | name、可选 input_schema/description |
| task.list / task.get | 无 / task_id |
| task.update | task_id、name、input_schema、可选 description |
| task.delete | task_id；要求任务没有活跃运行，删除配置、历史及任务结果 |
| step.save | task_id、document；修改时增加 step_id、expected_hash |
| step.list / step.get | task_id / step_id |
| step.reorder | task_id、完整 step_ids；不能把依赖排在来源之前 |
| step.delete | step_id；有执行历史或被引用的步骤拒绝删除，历史随任务整体删除 |
| step.validate | step_id；仅静态验证，不标记已验证 |
| step.trial | step_id、inputs、command_id、可选 environment_id |
| step.confirm | step_id、attempt_id、expected_hash |
| run.create | task_id、可选 inputs/environment_id |
| run.start | run_id、command_id、可选 mode=ALL/NEXT/UNTIL、target_step_id、retry_step_id |
| run.control | run_id、command_id、operation=pause/cancel/abandon |
| run.get / run.list | run_id / 可选 task_id |
| run.wait | run_id、可选 timeout（秒）；HTTP 请求等待默认 30 秒 |
| run.output | run_id、step_id、可选 output（默认 data） |
| run.events | run_id；日志、动作观察、错误等 |
| run.reconcile | attempt_id、decision=completed/not_completed、evidence、command_id |
| result.read / result.delete | result_id |
| capabilities | 无；查看当前可用动作、工具与结果处理器 |
| environment.save | name、public_config、可选 secret_refs/environment_id |
| step.generate | step_id、expected_hash、可选 step_description/feedback/contexts |
| context.read | step_id、provider_id、可选 request/environment_id；返回供用户预览的上下文 |
| step.diagnose | attempt_id；获取插件诊断建议 |
| draft.export / draft.import | step_id / task_id、package |
| feedback.export | attempt_id；仅输出脱敏后的错误元信息 |

command_id 应由调用方生成 UUID；网络失败时重用同一个 ID。重复相同命令返回原响应，不再执行；同 ID 不同参数拒绝。run.create 创建 READY 记录，不执行业务；重复调用会产生不同 READY 记录。正式执行在 run.start 去重。

`step.trial` 单独创建 TRIAL 运行，使用显式 inputs，不自动执行前置步骤。试跑成功后用返回 attempt_id 和当前 content_hash 调用 step.confirm。失败会保留反馈；已知没有副作用的失败试跑释放租约，可直接修改。存在不确定副作用时需核对/结束运行。

## 4. 步骤示例与依赖

step.save 的 document：

```json
{
  "name": "使用订单号",
  "step_description": "接收第一步订单号",
  "step_content": "async def run(ctx, inputs):\n    return ctx.result(data={\"order_id\": inputs[\"order_id\"]})\n",
  "bindings": {
    "order_id": {"ref": {"source": "step", "step_id": "第一步的实际UUID", "pointer": "/order_id"}}
  },
  "input_schema": {"type":"object","required":["order_id"],"properties":{"order_id":{"type":"string"}}},
  "output_schema": {"type":"object"},
  "capabilities": []
}
```

默认 data 按 run/step/attempt 保存至 `tasks/<task_id>/data.db` 的 step_outputs，主库不保存完整业务结果。引用永远读取同一次运行的有效成功尝试；缺少结果或字段时阻止执行，不自动取旧值。

插件自定义命名输出使用 `ref.output`，例如 `{"source":"step","step_id":"...","output":"items","pointer":"/0"}`。核心读取已保存记录，经插件 parse 后再提取字段。无插件时普通 JSON 可直接使用。无业务数据的 `ctx.result()` 仅记录执行状态，不创建任务库。

## 5. AI 配置与手动流程

纯手写不需要配置模型。生成需要以下本地环境变量：

- TASKWEAVE_MODEL_URL：完整 chat-completions 接口 URL。
- TASKWEAVE_MODEL_NAME：服务支持的模型 ID。
- TASKWEAVE_MODEL_API_KEY：可选访问凭据；不写入数据库。

HTTP 适配器支持 JSON 内容和工具调用，使用 HTTPS；本机模型允许 loopback HTTP。当前不支持模型图片输入，明确报错。接口字段参考 [DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)，模型名称由用户配置，不固定厂商。

步骤必须先保存为草稿，然后 step.generate 返回 proposed_content 和 expected_hash。用户检查/修改后调用 step.save，接着 trial → confirm。生成接口不会替用户保存、运行或调用 WRITE 工具。READ 工具也必须来自选中的能力。调试反馈可导出，筛选后作为 feedback 提交；context.read 的结果先展示给人，再按需传入 contexts，不自动发送整个页面。

生成限制：最多 8 轮工具交互、单工具 30 秒、会话 180 秒、本地编写请求 128 KiB。历史轮数由用户选择，超限不自动压缩或改变轮数。模型不可用不影响手动编写和正式执行。固定步骤运行时不调用模型。

凭据通过 environment.save 的 `secret_refs: {"登录角色":"env:LOCAL_SECRET_VARIABLE"}` 配置，动作从插件上下文解析。运行输入及公开环境配置检测到明显凭据字段会拒绝，日志会脱敏已知秘密；不要把秘密硬编码到源码或业务输出，通用脱敏不可能识别任意字符串的秘密含义。

## 6. 恢复与限制

- 一个活跃运行持有租约，暂停/失败/中断后保留，直至完成或 abandon；活跃任务不能修改配置。
- 暂停在当前步骤完成后生效；取消协作执行，不代表撤销业务。超时先请求取消，1 秒后仍不响应则终止 worker，结果标记 UNKNOWN。
- 中断后先核对任务库 receipt；已提交的结果可恢复确认，不重做业务。没有确定证据时 UNKNOWN 阻止继续。run.reconcile 需要外部核对证据；completed 只确认状态，不会虚构丢失的业务输出。
- 重跑前置步骤会撤销它及后续步骤的有效结果，保留历史尝试。失败重试需要显式 retry_step_id，结果保存失败或副作用未知不允许直接重试业务。
- 任务输入中的非秘密参数会随运行保存，重启继续可用；浏览器/连接等资源须由插件重建并执行前置检查。
- 表结构迁移由核心负责；自定义表初始结构支持 TEXT/INTEGER/REAL/BLOB。不兼容表变化明确报 TABLE_MIGRATION_REQUIRED；插件包发现及其兼容迁移流程属于 REQ-004。
- 目前测试环境为 macOS / Python 3.13，实际使用 spawn worker。Windows 10 x64 实机、真实模型服务和 Playwright 尚未验证，不视为本轮已测。
