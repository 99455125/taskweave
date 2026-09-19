# 步骤内容与编写契约

## 1. Step 字段

| 字段 | 类型/默认 | 说明 |
|---|---|---|
| step_id / task_id | UUID 字符串 | 稳定标识；不随排序改变 |
| name / goal | string | 名称、自然语言目标；goal 不作为可执行代码 |
| node_kind | `action` | 后续预留 condition/loop/subflow |
| position | 非负整数 | 当前层顺序 |
| content_format | `python-async-v1` | 内容语法标识，不是步骤版本 |
| step_content | string | 当前唯一内容；允许未验证草稿保存 |
| input_schema / output_schema | JSON Schema object | 对 inputs 和 StepResult.data 校验，data 可为 null |
| bindings | object | 参数来源，规则见下文 |
| capabilities | action/tool/resource/result_handler ID 列表 | 明确所用能力和插件依赖 |
| delay_after_previous_seconds | 非负整数，默认 0，上限 86400 | REQ-005 / 总库 v3：前一步成功后的等待秒数，首步骤忽略 |
| timeout_ms | 正整数，默认 60000 | 整步时限；浏览器动作时限不得超过剩余时间 |
| validation_state | DRAFT / VALIDATED | 改动后 DRAFT，试跑验证后才能执行正式任务 |
| verified_hash | string 或 null | 最近一次成功验证对应内容指纹；不是版本号 |
| validated_environment_id | string 或 null | 验证环境，仅元信息 |

保存草稿与发布为可执行步骤是同一记录的状态变化，不创建 revision 表。草稿不可用于正式运行；验证成功将同一行标记 VALIDATED。

## 2. 唯一可执行入口

```python
async def run(ctx, inputs):
    result = await ctx.call("playwright.page_title", {"role": inputs["role"]})
    return ctx.result(data={"title": result["title"]})
```

必须仅有一个顶层 `async def run(ctx, inputs)`，无顶层执行语句、装饰器、默认参数。首版禁止 import、eval/exec、文件/网络直调和隐式全局依赖，所有外部能力走 ctx；允许函数体内普通 Python 数据计算。静态检查是规范约束，不是抵御恶意 Python 的安全沙箱，执行内容仍需用户信任。

ctx.call 返回已由插件 output_schema 校验的 JSON 值；遇到动作失败抛统一 ActionError，不返回混合 bool/tuple。run 必须返回 StepResult（由 ctx.result 构造），不能隐式 None；`ctx.result()` 表示成功且无业务数据。失败通过异常或业务断言表达。输出的类型/schema 再由核心校验。

声明 capabilities 作为运行 allowlist；动态拼接 action ID 也必须通过 runtime 检查。插件会话不直接暴露给模型或 ctx.call 返回值。普通业务步骤只消费 JSON 或受控文件引用。

## 3. 绑定（无 eval）

每个顶层参数值必须采用以下一种形式：

- `{"literal": 任意JSON值}`。
- `{"ref": {"source": "task", "pointer": "/url"}}`，JSON Pointer 读取本次任务输入。
- `{"ref": {"source": "step", "step_id": "...", "pointer": "/title"}}`，从任务数据库读取本次运行前序有效成功尝试的输出，按需经插件解析后提取字段。
- `{"ref": {"source": "environment", "pointer": "/base_url"}}`，只允许非秘密配置。

JSON Pointer 使用 / 分隔及 ~0/~1 转义；空串表示根；缺失路径是 INPUT_MISSING，数组索引按非负整数处理。无隐式字符串插值、默认回退或类型转换。输入 schema 校验失败时动作不启动。步骤引用必须是已经完成的前序节点；重跑上游时撤销下游有效输出，历史 attempt 保留。

凭据不通过 bindings 或 prompt 传递。插件资源适配器通过环境角色到凭据引用的本地映射解析。

## 4. 服务接口与竞争修改

- `save_step(task_id, step_id, document, expected_hash)`：创建/覆盖当前内容，状态 DRAFT。expected_hash 为当前内容指纹，用于拒绝过时编辑；不是历史版本。新建传 null。
- `generate_step(task_id, step_id, goal, selected_capabilities, feedback, expected_hash)`：返回 proposed_content、diagnostics、authoring_session_id；不自动保存/执行。手动编辑不依赖此接口。
- `validate_step(step_id)`：静态结构、绑定、schema 和插件 lint，返回 diagnostics；仅静态通过不标记 VALIDATED。
- `trial_step(step_id, inputs, environment_id, command_id)`：用户明确启动试跑，生成 mode=TRIAL 的 run/attempt；结果与普通执行用同一协议。
- `confirm_step(step_id, attempt_id, expected_hash)`：仅试跑成功、指纹一致、插件/环境匹配时标记 VALIDATED；不重复执行。

指纹对 goal、规范化源码（UTF-8/LF）、input/output schema、bindings、capabilities 和当前插件依赖标识的规范 JSON 求 SHA-256；UI 布局不参与。用户/AI 修改后旧试跑不能用来确认。AI 返回时如果指纹已变，作为建议显示，不覆盖用户编辑。

运行租约持有期间任务配置不可覆盖；步骤调试需先结束活跃正式运行。TRIAL 输入从显式样本或已选择的任务结果提供，不偷偷执行前置步骤。验证记录只证明所用样本/环境，正式执行仍 preflight。导入另一台机器后校验依赖与环境，标记为待本地验证。

## 5. AI 编写会话

统一 ModelPort 接收 messages、tool_specs、response_contract，返回文本建议或工具调用。顺序：项目规则 → 所选插件贡献（稳定 ID 排序）→ 用户目标/已有内容 → 用户选择的页面/错误上下文。冲突诊断阻止生成，不以最后一条提示词覆盖。

生成结果 envelope：`{"step_content":"async def ...", "explanation":"..."}`；只解析为文本草稿，不执行模型响应。声明能力变化通过用户选择/确认后重新生成。最大 8 轮工具交互、每次 30 秒工具超时、生成会话总时限 180 秒（配置可收紧），达到上限返回诊断，不无限修复。

READ 工具可在用户选定的上下文范围内调用；WRITE 工具只返回待试跑建议，需用户明确执行对应工具/试跑命令，不在生成阶段自动操作业务。图像能力不支持时只能使用可用文本或明确报错。模型调用失败保留当前草稿，手写/执行仍可用。

受限虚拟机不调用模型；在允许环境生成后传递 draft 包（step 文档+依赖清单），执行侧导出用户筛选的脱敏 feedback 包。凭据、全量页面、浏览器登录态默认不传出。
