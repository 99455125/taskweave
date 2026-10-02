# TiDB 插件

通过 MySQL 协议提供只读查询、显式 SQL 执行、连接测试、表结构上下文，以及表格和核对报告展示。连接方式参考 [TiDB 官方 PyMySQL 文档](https://docs.pingcap.com/developer/dev-guide-sample-application-python-pymysql/)。

## 安装与启用

```bash
uv sync --locked --extra gui --extra browser --extra ocr --extra database
uv run --extra gui --extra browser --extra ocr --extra database taskweave workbench
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

## 显式 SQL 执行

0.2.0 新增 `tidb.execute_sql` 是独立 WRITE 动作，`retry_safe=false`，不作为编写阶段的只读工具提供；`tidb.query` 的参数、结果和只读限制保持兼容。插件 API v1 不变，旧运行仍校验原插件版本；不改写旧任务包或绕过版本保护。它接受 SQL 文本（包括前序 `file.read` 的完整 content），不直接访问文件路径。

| 参数 | 说明 |
| --- | --- |
| `sql` | 必填，UTF-8 文本最多 1MB，脚本最多 100 条有效语句 |
| `mode` | 默认 `transaction`；全部执行成功才 COMMIT。`autocommit` 逐条提交，允许 DDL，失败可能部分生效 |
| `params` | 单条 SQL 的标量参数数组，以 `%s` 绑定，不能把占位符写在引号内 |
| `statement_params` | 多条 SQL 一条对应一组数组，数量须与有效语句相同；与 params 互斥，无参数语句对应 `[]` |
| `max_rows` | 整批共享的返回行数上限，默认 tidb_max_rows，不突破该配置上限 |

支持 SELECT/SHOW/EXPLAIN、INSERT/REPLACE/UPDATE/DELETE；CREATE/ALTER/DROP/TRUNCATE 需要显式 `autocommit`。[TiDB 的 DDL 会隐式提交且无法回滚](https://docs.pingcap.com/tidb/stable/transaction-overview/)。禁止脚本自行包含 BEGIN/COMMIT/ROLLBACK/SET/USE、可执行注释、客户端 DELIMITER 或存储程序脚本；暂不支持 LOAD DATA、CALL 等其他语句。普通注释、字符串内分号不会被误拆；发送原 SQL 而非解析器重写的 SQL。业务值必须参数绑定。

返回 `mode/commit_state/statement_count/affected_rows/statements/database/elapsed_ms`；成功的 commit_state 是 COMMITTED。每条结果包含 index、command、affected_rows 和可选 table；table 包含 columns、rows、row_count、truncated，可用 tidb.table 展示。返回不包含 SQL 文本或参数值；查询数据可能包含业务数据，按需保存。金额/日期/二进制转换沿用查询规则。

事务内执行错误会回滚并报具体语句序号和脱敏错误码；回滚失败或 COMMIT 响应丢失会报 `TIDB_EXECUTE_UNKNOWN`，绝不声称已回滚。autocommit 失败报 `TIDB_EXECUTE_PARTIAL_OR_UNKNOWN`，附已完成语句数，需要核对外部结果。写动作失败的宿主副作用状态保持保守 UNKNOWN，不能盲目重试。每次关闭连接，取消在连接前、语句之间和提交前检查；进行中的网络操作仍受连接超时和宿主 65 秒动作期限约束，取消不保证已发出的 SQL 没有生效。

完整文件链路见 [文件插件](../file/README.md)。默认读取上限与 SQL 上限相同，超限不会执行残缺文件。

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

单元测试覆盖参数绑定、只读兼容、SQL 脚本事务/DDL 边界、失败回滚、未知提交、取消、TLS 配置、表结构、数据类型、截断、错误信息与关闭连接。MySQL 协议 fixture 使用真实 PyMySQL 和独立步骤进程验证查询、展示保存及重启读取；另有文件读取→真实 worker 绑定→PyMySQL SQL 执行链路验证。fixture 不是实际 TiDB 服务，尚未连接用户数据库。
