# 步骤内容与输入绑定

## 定义

现行content_format为`python-async-v1`。规范步骤包含name、step_description、step_notes、step_content、input_schema、output_schema、bindings、capabilities、plugin_requirements、timeout_ms及delay_after_previous_seconds。normalize_step补默认值；超时范围1–3600000毫秒，步骤间隔0–86400秒。

```python
async def run(ctx, inputs):
    return ctx.result(data={"value": inputs["value"]})
```

入口和允许语法由[content_tree](../../src/taskweave/core/validation.py)检查。外部操作经`await ctx.call("声明的动作ID", {...})`，静态action_id须属于capabilities；输出用ctx.result/ctx.output，日志与取消经ctx.log/ctx.cancelled。受限执行不是任意代码的完整安全沙箱，不应将未知来源内容视为自动可信。

## Schema与JSON

JSON使用严格序列化，不接受NaN等非JSON值。Schema采用JSON Schema 2020-12，只允许本地引用，禁止远端$ref/$dynamicRef。输入输出校验和插件能力校验分开。

## 绑定与优先级

绑定项为`{"literal": value}`或`{"ref": {...}}`。ref.source取task、step、environment，pointer是JSON Pointer；step引用必须指向同一任务前序步骤，可用output指定输出名，默认data。运行时读取同一运行前序有效输出。

自动输入合并顺序为环境→任务→步骤默认/显式覆盖，后者覆盖同名字段；显式绑定提供依赖解析。单步调试、流程调试与正式执行入口对覆盖有不同组织方式，应使用既有输入解析实现，不能在UI再次推导一套优先级。false、0、空字符串均不能被通用真值判断视为未提供。

## 并发和确认

保存用expected_hash核对现存版本；confirmation/validation_state归持久化定义。普通草稿保留原基线，冲突不自动覆盖他人修改。TypedDict记录见[core/data_contracts.py](../../src/taskweave/core/data_contracts.py)，精确版本算法与保存规则见[步骤仓储](../../src/taskweave/infrastructure/repositories/steps.py)。
