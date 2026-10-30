# 步骤内容与输入绑定

## 定义

现行content_format为`python-async-v1`。规范步骤包含name、step_description、step_notes、step_content、input_schema、output_schema、bindings、capabilities、plugin_requirements、timeout_ms及delay_after_previous_seconds。normalize_step补默认值；超时范围1–3600000毫秒，步骤间隔0–86400秒。

```python
async def run(ctx, inputs):
    return ctx.result(data={"value": inputs["value"]})
```

入口和允许语法由[content_tree](../../src/taskweave/core/validation.py)检查。外部操作经`await ctx.call("声明的动作ID", {...})`，静态action_id须属于capabilities；输出用ctx.result/ctx.output，日志与取消经ctx.log/ctx.cancelled。受限执行不是任意代码的完整安全沙箱，不应将未知来源内容视为自动可信。

## Schema与JSON

JSON使用严格序列化，不接受NaN等非JSON值。Schema采用JSON Schema 2020-12，只允许本地引用，禁止远端$ref/$dynamicRef。输入输出校验和插件能力校验分开。新步骤的 input_schema 默认为 {"type":"object"}，output_schema 默认为 {}；这些是基础定义，具体字段由已有步骤、导入定义或编辑配置提供。输出 Schema 校验 ctx.result(data=...) 的业务数据；其中 default 是 Schema 描述信息，不由运行时据此自动补输出。输入字段 default 则参与既有自动输入合并。

## 绑定与优先级

绑定项为`{"literal": value}`或`{"ref": {...}}`。ref.source取task、step、environment，pointer是JSON Pointer；step引用必须指向同一任务中按流程先执行的步骤，可用output指定输出名，默认data。运行时读取同一运行的有效输出。结构化流程还支持`loop`来源的`item`、`index`、`state`和`branch`来源的公开输出，引用受所在循环和分支作用域约束。

同一步骤位于列表遍历或条件循环内时，每轮产生独立执行实例。循环外读取该步骤默认得到按轮次排列的列表；未执行的分支轮次占位为`null`。循环内读取当前轮结果。`step`引用可用`loop_node_id`和`item_pointer`显式取某个循环的逐项投影；既有`pointer`仍作用于完整结果。列表遍历的`item`与`index`可供当前轮步骤绑定，循环`state`由初始值和每轮更新映射组成。

自动输入合并顺序为环境→任务→步骤默认/显式覆盖，后者覆盖同名字段；显式绑定提供依赖解析。单步调试、流程调试与正式执行入口对覆盖有不同组织方式，应使用既有输入解析实现，不能在UI再次推导一套优先级。false、0、空字符串均不能被通用真值判断视为未提供。

## 并发和确认

保存用expected_hash核对现存版本；confirmation/validation_state归持久化定义。普通草稿保留原基线，冲突不自动覆盖他人修改。TypedDict记录见[core/data_contracts.py](../../src/taskweave/core/data_contracts.py)，精确版本算法与保存规则见[步骤仓储](../../src/taskweave/infrastructure/repositories/steps.py)。

## 条件组与路径

流程的显式条件组保留 kind=if，以 cases（每项 id、condition、body）、default（id、body）和可选布尔 parallel 表达。省略 parallel 等同关闭，字符串或数字不作为布尔值接受。关闭时首个匹配，开启时冻结全部命中分支并执行；默认只在零命中时执行。分支 ID 在组内唯一且稳定，body 为顺序容器；输出映射须覆盖全部出口。

并行路径不允许读取兄弟路径结果，后续通过 branch 公共输出读取按分支 ID 区分的值。控制决定和公共输出记录在实例 payload，恢复不重新判定；映射缺失或求值失败阻止汇合。步骤内容不改变，实际尝试仍归属同一 run_id，以 execution_path 区分分支及循环出现；重试精确定位原实例。完整结构及校验以 [task_flow.py](../../src/taskweave/core/task_flow.py) 为准。
