# 步骤内容与输入绑定

现行入口：[validation.py](../../src/taskweave/core/validation.py)、[步骤仓储](../../src/taskweave/infrastructure/repositories/steps.py)、[步骤用例](../../src/taskweave/application/steps.py)。这些实现和相关行为测试决定精确签名；本页替代旧需求中的字段/绑定维护说明。

## 定义与确认

| 内容 | 现行规则 |
| --- | --- |
| 标识/归属/顺序 | step_id 稳定，属于 task_id；重排不得把依赖放到来源之前 |
| 描述与代码 | step_description 是自然语言，step_notes 是 AI 编写说明，step_content 才是可执行内容 |
| 格式 | python-async-v1；单一 `async def run(ctx, inputs)`，无注解、装饰器、默认/额外参数及顶层执行语句 |
| schema | input_schema / output_schema；JSON Schema 2020-12，仅本地引用，拒绝外部 $ref/$dynamicRef |
| 能力 | capabilities 去重排序，plugin_requirements 声明依赖版本；动作 ID 必须是已声明的字符串字面量 |
| 时限 | timeout_ms 默认60000，整数1–3600000；delay_after_previous_seconds 默认0，整数0–86400 |
| 状态 | DRAFT/VALIDATED、content_hash/verified_hash、validation_source；不维护步骤版本树 |

保存当前草稿使用 expected_hash 拒绝过期覆盖；修改定义或步骤上下文使确认失效。静态验证不产生成功试跑证据。确认可根据当前内容的成功调试记录，或由用户明确手动验证；取消确认不改数据。环境变化本身不撤销步骤确认，创建后的运行仍检查自己的配置一致性。

活动正式运行禁止覆盖定义；空闲 FAILED/SUCCEEDED 调试允许既有修订路径。排队保存进入串行锁后读取最新 old_step 哈希，不能让两次请求都带锁外旧哈希。

## 执行内容

允许普通函数体内计算与受限 builtins；禁止 import、eval/exec、直接文件访问、私有属性及绕过 ctx 的外部操作。调用入口：`ctx.call`、`ctx.result`、`ctx.output`、`ctx.log`、`ctx.cancelled`。内容和插件都是受信任本地代码，这不是恶意代码安全沙箱。

`ctx.call` 按动作 schema 校验并执行 preflight/execute/verify；业务失败用异常或断言表达。必须返回 StepResult；`ctx.result()` 表示成功且无业务数据，不等于隐式 None。

```python
async def run(ctx, inputs):
    await ctx.call("playwright.page_open", {"url": inputs["url"], "role": inputs["role"]})
    page = await ctx.call("playwright.page_title", {"role": inputs["role"]})
    if not page["title"].strip():
        raise ValueError("Page title is empty")
    outputs = []
    if inputs["capture"]:
        shot = await ctx.call("playwright.page_screenshot", {"role": inputs["role"]})
        outputs.append(ctx.output("playwright.image", "page", shot))
    return ctx.result(data={"title": page["title"]}, outputs=outputs)
```

此为内容范例，不是已执行的本轮测试；使用前声明所调用动作及处理器、对应输入 schema 和本地环境。仅状态场景返回 ctx.result()；普通 data 默认保存；文件请求必须放进 outputs。不能丢弃 ctx.output 返回值或只传 staging token 字符串替代截图对象。

## 绑定与实际输入

绑定形式：`{"literal": JSON}` 或 `{"ref":{"source":"task|environment|step","pointer":"/field"}}`。step 来源还需 step_id，可选 output（默认 data）。JSON Pointer 的 `~0/~1` 表示 `~/`，空路径表示根；缺字段 INPUT_MISSING，非法路径 POINTER_INVALID，不能引用后续步骤。命名输出经处理器 parse 后提取字段；正式执行只读同一 run 的有效成功结果。

按当前 automatic_inputs/effective_inputs，从低到高合并：环境 → 任务默认及本次任务输入 → 步骤 schema 默认 → 显式绑定/独立试跑输入 → 本次 step_inputs。封闭 schema 只保留声明字段；不对绑定值隐式插值/类型转换。表单草稿切环境时可暂存空必填或未完成 JSON，提交时仍严格验证。

独立步骤调试可借最近同任务同环境的成功结果准备样本；正式执行和从首步流程调试不能用其他运行替代当前结果。绑定字段选择器可展示受限深度/数量的历史示例，但不能把示例写成正式执行结果。

相关：[运行协议](runtime.md)、[任务分享](task-sharing.md)、[AI 编写](authoring.md)。
