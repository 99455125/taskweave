# 基础数据工具插件

源码环境使用 `--extra utility` 安装；Windows 正式包包含此插件。在“插件”页面启用后可供步骤使用。它只提供明确的动作，不执行任意 Python 代码，也不读取数据库或文件。

| 动作 | 输入 | 返回 |
| --- | --- | --- |
| `utility.now` | 可选 `timezone`（IANA 时区，默认 `UTC`） | `iso`、`compact`（`YYYYMMDDHHMMSS`）、`timezone` |
| `utility.uuid` | 空对象 | UUID v4 字符串 `value` |
| `utility.decimal` | `operation`（`add`、`subtract`、`multiply`、`divide`）、数字字符串 `left`/`right`、小数位 `scale`（0–12）、可选 `rounding` | 按精度舍入后的数字字符串 `value` |

`utility.decimal` 默认使用 `HALF_UP`；也支持 `HALF_EVEN`、`DOWN`。数字以字符串传入和返回，不经过二进制浮点数。除数为零、无效数字和无效时区会报错。Windows 包携带时区数据。

步骤示例：

```python
async def run(ctx, inputs):
    current = await ctx.call("utility.now", {"timezone": "Asia/Shanghai"})
    amount = await ctx.call("utility.decimal", {
        "operation": "multiply", "left": inputs["premium"],
        "right": inputs["rate"], "scale": 2,
    })
    return ctx.result(data={
        "contract_no": "hxy_auto_" + current["compact"],
        "amount": amount["value"],
    })
```

步骤需在 `capabilities` 声明所调用的动作。若时间或 UUID 用作业务编号，应把本次取得的值放进 `data`，供后续步骤和调试结果查看。TiDB 查询和 Playwright 页面操作仍由各自插件负责。
