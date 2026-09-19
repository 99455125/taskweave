# TiDB 插件

通过 MySQL 协议提供只读查询、连接测试、表结构上下文，以及表格和核对报告展示。连接方式参考 [TiDB 官方 PyMySQL 文档](https://docs.pingcap.com/developer/dev-guide-sample-application-python-pymysql/)。

## 安装与启用

```bash
uv sync --locked --extra gui --extra browser --extra sample --extra captcha --extra database
uv run --extra gui --extra browser --extra sample --extra captcha --extra database taskweave workbench
```

在插件管理启用 `tidb`，步骤选择 TiDB 插件。第三方数据库依赖只属于插件，不进入核心默认依赖。

## 连接变量

环境或任务配置以下普通本地变量；任务值覆盖环境值，不修改操作系统环境变量。

| 变量 | 说明 |
| --- | --- |
| `tidb_connection_url` | 可选 `mysql://账号:密码@主机:4000/数据库`，特殊字符需要 URL 编码 |
| `tidb_host` | 主机，使用分项配置时必填 |
| `tidb_port` | 默认 4000 |
| `tidb_database` | 数据库，使用分项配置时必填 |
| `tidb_username` | 账号，使用分项配置时必填 |
| `tidb_password` | 密码，允许本地保存 |
| `tidb_tls` | 默认 true，验证服务器证书和主机名；本地没有 TLS 时显式设置 false |
| `tidb_ssl_ca` | 可选 CA 文件路径，否则使用 certifi |
| `tidb_timeout_seconds` | 连接与读写超时，默认 15，范围 1–60 秒 |
| `tidb_max_rows` | 最多保存行数，默认 1000，范围 1–10000 |

连接串与分项字段同时存在时，显式分项字段覆盖连接串。连接串支持 `tls`、`ssl_verify_cert`、`ssl_verify_identity` 和 `ssl_ca` 查询参数；启用 TLS 后始终验证证书和身份。无需在步骤代码或展示结果中保存连接账号密码。

## 动作与上下文

- `tidb.test_connection`：参数 `{}`，返回版本和当前数据库的表格。
- `tidb.describe_table`：参数 `{table, database?}`，参数化查询 information_schema 字段、类型、默认值和注释。
- `tidb.query`：参数 `{sql, params?, title?, max_rows?}`，只允许一条 SELECT（支持只读 CTE），拒绝写入、锁定及文件导出，连接使用只读事务。
- `tidb.schema`：插件上下文采集；表单由插件的 `context_requests` 声明，输入表名与可选数据库。API 和 Chat 均携带采集结果；网页 AI 不直接访问本地数据库。

查询返回 `title/columns/rows/row_count/truncated/query_info`。数量是本次保存行数；`truncated=true` 时不能把部分数据当作完整结果核对。金额 Decimal 保存为字符串，日期时间保存为 ISO 字符串，二进制字段保存为 Base64 对象。查询信息含 SQL、参数数量、数据库和耗时，不包含密码或参数值。每次查询结束关闭连接，没有长期保留的数据库会话。

## 步骤示例

前序步骤返回 `data.order_no`，在当前步骤绑定输入 `order_no` 到前序结果 `/order_no`。目标可写“根据单号查询订单，确认状态为 SUBMITTED，保存订单表和核对说明供查看”。AI 使用插件提供的格式生成：

```python
async def run(ctx, inputs):
    table = await ctx.call("tidb.query", {
        "sql": "SELECT order_no, status FROM orders WHERE order_no = %s",
        "params": [inputs["order_no"]],
        "title": "订单信息",
    })
    passed = not table["truncated"] and len(table["rows"]) == 1 and table["rows"][0]["status"] == "SUBMITTED"
    report = {
        "passed": passed,
        "message": "订单核对通过" if passed else "订单核对未通过",
        "tables": [table],
        "query_info": table["query_info"],
    }
    return ctx.result(
        data={"order_no": inputs["order_no"], "verified": passed, "report": report},
        views=[{"title": "订单数据库核对", "renderer": "tidb.verification", "pointer": "/report"}],
    )
```

`orders` 与字段必须替换为实际表结构，不能让 AI 猜。查询异常使步骤失败；保存的 `verified=false` 表示查询已完成但业务核对不通过，报告显示红色，供后续步骤决策。直接抛断言会阻止普通业务结果保存，因此需要保留核对证据时采用上述返回方式。

## 展示

- `tidb.table`：将字段引用的 `{columns, rows}` 渲染为可分页排序表格。
- `tidb.verification`：显示核对摘要、多个带标题的表格页签和可展开查询信息。
- 多个 views 可以混合数据库报告和 Playwright 截图；原始数据始终可查看。展示读取已保存快照，不再次查询。

## 验证范围

单元测试覆盖参数绑定、只读 SQL、TLS 配置、表结构、数据类型、截断、错误信息与关闭连接。MySQL 协议 fixture 使用真实 PyMySQL 和独立步骤进程验证查询、展示保存及重启读取；fixture 不是实际 TiDB 服务，尚未连接用户数据库。
