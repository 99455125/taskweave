# 内部数据集（dataset）

任务内部的表格数据与 SQL 处理插件，无需数据库地址或账号。宿主管理任务数据、执行归属与历史；SQLite 是宿主实现。连接外部数据库使用 [TiDB 插件](../tidb/README.md)。

## 安装与启用

```bash
uv sync --locked --extra gui --extra dataset --extra excel
uv run taskweave --home /path/to/workspace plugins enable dataset
uv run taskweave --home /path/to/workspace plugins enable excel
```

后续同步继续列出需要的 extras。Excel 依赖 dataset；只处理内部数据时可仅选择 dataset。已有工作空间不会自动启用新增插件。

## 使用

create 从列声明和二维行值创建数据集；describe 返回列名、类型和行数；read 分页返回可展示的表格；query 对明确输入的数据集执行单条 SELECT/CTE；execute 对源副本执行单条 INSERT/UPDATE/DELETE，表名固定为 data。精确参数以[动作声明](src/taskweave_dataset/__init__.py)为准。

每次创建或处理返回轻量引用。将其放入步骤 data，通过现有绑定传给后续步骤，不需要复制全部行，也不向插件提供数据库连接。不同运行不能复用引用；其他步骤的数据集必须来自当前步骤的输入，且来源仍有效成功。同一任务组合中的不同子运行也不能直接共用引用，需显式传普通数据或通过文件交接。

```python
async def run(ctx, inputs):
    summary = await ctx.call("dataset.query", {
        "sources": {"orders": inputs["dataset"]},
        "sql": 'SELECT "客户", SUM("金额分") AS total FROM orders WHERE "金额分" >= ? GROUP BY "客户"',
        "params": [0],
        "name": "按客户汇总",
    })
    preview = await ctx.call("dataset.read", {"dataset": summary, "limit": 100})
    return ctx.result(
        data={"dataset": summary, "preview": preview},
        views=[{"title": "汇总预览", "renderer": "core.table", "pointer": "/preview"}],
    )
```

SQL 使用 SQLite 方言和 `?` 值参数；sources 将数据集映射到本次 SQL 的逻辑表名。只能访问明确输入的表，不支持数据库路径、ATTACH、PRAGMA、事务控制、DDL、扩展或外部 I/O。使用常见查询/聚合函数；具体允许函数见[宿主 SQL 实现](../../src/taskweave/infrastructure/dataset_sql.py)。修改生成新数据集，不覆盖输入。SQL 失败不发布部分结果。

execute 使用未被用户列占用的 SQLite 隐式行号保存行序及原布尔类型；禁止修改隐式行号。如果列名同时占用 rowid、_rowid_、oid 三个别名，execute 明确拒绝，先用 query 选择并重命名其中一列后再修改。单独名为 rowid 的普通列可正常使用。

## 类型、持久化与限制

列类型为 any、text、integer、number、boolean，均可为空；列名非空且大小写唯一，行宽一致。金额精度由调用者选择文本或整数最小单位保证，不将文本金额隐式转为浮点。SQL 的布尔表达式遵循 SQLite 的 0/1 结果规则，不能据此声称保存了原 Excel 单元格格式。

动作阶段暂存数据集，步骤成功时与普通输出/回执同事务写入任务 data.db 中的独立表。失败、取消不发布；重跑生成新引用，已失效来源不能继续使用。删除数据集结果同时删除数据表和元数据，沿用宿主结果删除/恢复流程。结果查看预览默认1000行，read 返回 total/offset/truncated；完整导出直接把引用交给 Excel，不能把预览当作全部数据。

单数据集最多100000行、256列、1000000单元格、16 MiB；单步最多16个数据集、累计32 MiB。单条 SQL 最多64 KiB，计算有10秒期限；超限报错。当前能力面向有界表格处理，不提供跨运行共享可变数据集或可视化数据编辑器。

端口及限制以[数据集契约](../../src/taskweave/core/dataset_contracts.py)为准；宿主持久化见[datasets.py](../../src/taskweave/infrastructure/datasets.py)，验证入口统一在 tests/module-map.json 的 plugins.dataset。
