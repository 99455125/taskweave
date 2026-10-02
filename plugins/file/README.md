# 文件读取插件

文件插件只依赖 TaskWeave SDK 和 Python 标准库，不进入核心默认依赖。安装 `files` extra 后，在插件页启用 `file`，步骤才能调用 `file.read`。

```bash
uv sync --locked --extra gui --extra files --extra database
uv run --extra gui --extra files --extra database taskweave workbench
```

## 配置与读取

环境或任务变量 `file_root` 指定允许读取的本地目录，任务值覆盖环境值。文件路径以该目录为基准；绝对路径也必须在其中，外部符号链接和目录不能读取。它是读取范围约束，不能替代操作系统权限隔离。

`file.read` 是 READ、可安全重试动作，参数如下：

| 参数 | 默认与含义 |
| --- | --- |
| `path` | 必填，用户提供或实际观察到的文件路径 |
| `format` | `text`；也可选 `json`、`csv`、`base64` |
| `encoding` | `utf-8-sig`，兼容有/无 BOM 的 UTF-8；也支持 utf-8、gb18030、utf-16、latin-1 |
| `max_bytes` | 1048576，范围 1–1048576；超限报错，不返回截断内容 |
| `delimiter` | CSV 分隔符，默认逗号，必须是一个字符 |

返回 `{path, format, content, encoding, size_bytes}`。`path` 是相对 file_root 的路径；text 的 content 是完整字符串，JSON 是合法 JSON 值（拒绝 NaN/Infinity），CSV 是以唯一非空表头为键的行数组且所有值保持字符串，Base64 是完整二进制编码（encoding=null）。无效编码、格式和行宽错误均报错，不部分成功。不默认把文件内容写入日志。

## SQL 文件到 TiDB

读取与执行通过普通步骤输出和输入绑定衔接，两个插件不互相调用。

第一步选择 `file.read`：

```python
async def run(ctx, inputs):
    document = await ctx.call("file.read", {"path": inputs["sql_file"], "format": "text"})
    return ctx.result(data=document)
```

第二步定义字符串输入 `sql_text`，绑定到第一步 `data` 的 `/content`，选择 `tidb.execute_sql`：

```python
async def run(ctx, inputs):
    result = await ctx.call("tidb.execute_sql", {"sql": inputs["sql_text"]})
    return ctx.result(data=result)
```

默认整批事务提交；包含 DDL 的脚本须明确选择 `mode=autocommit`，不提供“整批可回滚”的假象。具体范围与错误处理见 [TiDB 插件](../tidb/README.md)。文件读取不会自动执行文件，也不会把 Base64 解码成 SQL。这个插件暂不提供文件写入或上下文录制。

## 文件到浏览器上传

第一步以 `format=base64` 调用 `file.read`，第二步把完整document作为object输入绑定到第一步data。为上传明确指定不含目录的文件名与MIME类型，content_base64取document的content：

```python
async def run(ctx, inputs):
    uploaded = await ctx.call("playwright.page_upload", {
        "selector": inputs["file_input_selector"],
        "files": [{"name": inputs["upload_name"], "mime_type": inputs["mime_type"],
                   "content_base64": inputs["document"]["content"]}],
    })
    return ctx.result(data=uploaded)
```

file.read返回的path可能含子目录，不能直接当作上传文件名。浏览器控件必须来自实际页面证据；此例只设置文件，业务步骤还须核对页面接收结果。限制与chooser模式见[Playwright插件](../playwright/README.md)。不通过插件传递本机文件句柄或会话对象。

## 验证范围

文件格式、读取限制、目录逃逸、真实 worker 输出绑定，以及文件→TiDB 的真实 PyMySQL 协议测试链路均有针对性测试。协议测试服务不是实际 TiDB；没有读取用户文件或连接用户数据库。
