# Nacos 配置插件

管理 Nacos 2.x 的配置；开发环境基线为 2.4.3，使用其 `/nacos/v1/cs/configs` 兼容接口、`/nacos/v1/auth/login` 及命名空间列表接口。本插件不管理服务发现、账号或命名空间。3.x 使用不同管理 API，不在本版本的支持范围内。

在插件管理中安装并启用 `nacos`。源码运行环境可通过 `uv sync --locked --extra nacos` 安装可选依赖；分发包从其打包清单收集插件。

## 环境配置

在 TaskWeave 环境中新建 JSON 类型变量 `nacos_profiles`，每个键是步骤中选择的连接名称；多个 Nacos 环境可配置在同一个 TaskWeave 环境中。例如：

```json
{
  "dev": {"url": "http://127.0.0.1:8848", "namespace": "local", "allow_http": true},
  "test": {"url": "https://nacos.example", "namespace": "test", "username": "operator", "password_ref": "nacos_test_password"}
}
```

URL 可为服务根地址或以 `/nacos` 结尾，默认验证 TLS；仅在明确需要 HTTP 时配置 `allow_http: true`。可选 `ca_file` 指定可信 CA，`timeout_seconds` 为 1–60 秒，默认 15 秒。`namespace` 是命名空间 ID，省略时使用服务端默认命名空间。启用认证时，`username` 与 `password_ref` 须同时提供；`password_ref` 是 TaskWeave 的逻辑密钥名，配置在环境密钥引用中，例如 `nacos_test_password` 映射到 `env:NACOS_TEST_PASSWORD`。确保启动 TaskWeave 的进程拥有该环境变量；不要把实际密码放进 profile 或步骤中。不启用认证时两项均省略。任务参数中同名变量覆盖环境配置。

## 动作

所有动作接收 `profile`，配置项使用 `data_id`、`group`（省略时为 `DEFAULT_GROUP`），命名空间可由动作参数指定，省略时取 profile。名称和参数的准确 Schema 以插件动作声明为准。

- `nacos.list`：按数据 ID 和组过滤，使用 `page`、`page_size` 分页。
- `nacos.get`：读取配置文本，返回 `content`。
- `nacos.get_json`：读取 JSON 对象并返回 `value`，供步骤选择字段。
- `nacos.publish`：完整内容发布；不存在则创建，存在则覆盖。`content` 是文本，必须明确指定配置 `type`（如 `yaml`、`json`）。
- `nacos.patch_json`：读取已有 JSON 对象，将 `patch` 中的对象递归合并后发布；数组、标量和 `null` 为替换值，未指定字段保留。目标不存在、内容不是合法 JSON 对象或有重复键时失败。写入时携带原始内容的 MD5 供服务端 CAS 校验，服务端会检查已存在配置的内容变更；Nacos 2.4.3 对并发删除和仅修改元数据有例外，见下文。
- `nacos.delete`：删除指定配置。

所有写操作都不自动重试；连接中断或服务器错误可能导致写入结果未知，先检查目标配置。发布完整内容和删除操作会产生外部副作用，按实际任务流程安排确认。不同环境不能作为一个原子事务提交；多目标流程发生失败时，需核对已完成的目标。配置内容可能含敏感业务数据，读取结果及 TaskWeave 运行记录应按业务权限管理。

## 同步选定字段

以下步骤读取来源 JSON 的一个字段，在目标环境增量发布，目标其他字段保持不变。步骤需声明使用 `nacos.get_json` 和 `nacos.patch_json` 能力；目标 JSON 必须已经存在。

```python
async def run(ctx, inputs):
    source = await ctx.call("nacos.get_json", {
        "profile": "dev", "data_id": "app.json", "group": "DEFAULT_GROUP",
    })
    published = await ctx.call("nacos.patch_json", {
        "profile": "test", "data_id": "app.json", "group": "DEFAULT_GROUP",
        "patch": {"service": {"limit": source["value"]["service"]["limit"]}},
    })
    return ctx.result(data=published)
```

如果需要创建一份完整配置，可先用 `nacos.get` 读取，再将其 `content` 和确认过的配置 `type` 传给目标 `nacos.publish`；这是整份替换。读取与发布仅处理内容及指定类型，不会自动复制应用名、描述和标签等元数据。固定值同样可直接写入 `patch`，或由步骤输入传入。配置项选择和多个目标的执行顺序由任务定义控制。

## 字段级操作与多命名空间

`nacos.namespaces` 读取目标 Nacos 服务可见的命名空间，返回 ID 和名称。`nacos.select_fields` 从指定 namespace 的 JSON 或 YAML 配置中读取路径，返回可直接用于发布的 `operations`；`nacos.update_fields` 把操作应用到一个 namespace；`nacos.update_many` 按顺序应用到所选的多个 namespace（最多 50 个）。`nacos.update_batch` 支持一次指定多个配置和多个 namespace。每次读取各目标现有内容和元数据，并使用该目标内容的 MD5 作为 CAS 条件，未选字段保持原值；不支持 Nacos 加密配置。Nacos 2.4.3 在读取后目标被并发删除时，CAS 发布可能重新创建该配置，因此 CAS 不能防止这种情况。CAS 只校验内容，不能检测并发修改的配置类型、描述等元数据；这些字段可能被读取时的旧值覆盖。应用名和标签不重新提交，以沿用服务端的现值。

路径是从根节点开始的字段名数组，例如 `spring.cloud.aaa` 写作 `["spring", "cloud", "aaa"]`；字段名中有点也不会被误拆分。支持：

| op | 行为 | 参数 |
| --- | --- | --- |
| `set` | 设置或新增指定字段 | `path`、`value` |
| `remove` | 删除指定字段 | `path` |
| `list_add` / `list_remove` | 在 YAML/JSON 列表中追加或按值删除一项 | `path`、`value` |
| `csv_add` / `csv_remove` | 在逗号分隔字符串中追加或按值删除一项 | `path`、`value` |

父路径必须存在。按值删除找不到或有多个相同值时会报错；不会猜测删除哪一项。逗号字符串不支持包含逗号的单个元素或空项。YAML 增量操作尽量保留注释和引号，拒绝重复键、锚点和别名，删除字段可能丢失无法安全转移的注释时拒绝执行；当来源的所选值无法表示为 JSON，或 YAML 1.1 与 1.2 对所选值解释不一致时，不生成操作。YAML 序列化可能调整缩进或文档头；不保证字节格式完全不变。目标配置必须已经存在，并应与指定的 `format` 一致。

例如，在任务输入中提供目标命名空间 ID 数组 `namespaces`，读取验证环境中的字段后批量同步：

```python
async def run(ctx, inputs):
    selected = await ctx.call("nacos.select_fields", {
        "profile": "cluster", "namespace": "test1", "data_id": "app.yaml",
        "format": "yaml", "paths": [["spring", "cloud", "aaa"]],
    })
    result = await ctx.call("nacos.update_many", {
        "profile": "cluster", "namespaces": inputs["namespaces"],
        "data_id": "app.yaml", "format": "yaml", "operations": selected["operations"],
    })
    return ctx.result(data=result)
```

也可直接为 `operations` 提供固定变更，例如 `{"op":"remove","path":["spring","cloud","bbb"]}`，或使用 `list_add`、`list_remove`、`csv_add`、`csv_remove`。多个配置可用 `nacos.update_batch` 的 `configs` 数组一次提交，每项指定 `data_id`、可选 `group`、`format` 和 `operations`。批量写入不是事务：遇到失败即停止后续目标，错误和日志标识已成功及当前目标；超时或异常时核对实际结果后再继续。运行时可在任务输入中填写目标 ID 数组；当前任务表单还不能动态加载 Nacos 命名空间并勾选。
