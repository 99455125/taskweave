# Excel（excel）

读取、新建和写入 `.xlsx`，与[内部数据集插件](../dataset/README.md)协作。使用 openpyxl，不要求安装或启动 Excel 应用。可选依赖只属于插件，不进入核心默认安装。

先安装 excel extra 并依次启用 dataset、excel，命令见[数据集安装说明](../dataset/README.md)。环境或任务变量设置 `excel_root` 为已存在的本地目录，任务值覆盖环境值。输入输出路径须位于该目录内，父目录需已存在。

## 动作

| 动作 | 用途 |
| --- | --- |
| excel.inspect | 返回工作表名称与范围信息 |
| excel.read | 指定工作表和可选区域，导入为内部数据集 |
| excel.create | 新建工作簿，可同时写入二维值或数据集 |
| excel.write | 写入既有工作簿的指定区域，支持另存新文件 |

精确参数和默认值见[动作声明](src/taskweave_excel/__init__.py)，无需另配数据库。

read 默认使用活动工作表、首行为表头；表头须非空且唯一，或显式传 columns。可用 range 指定 `B2:D20`；header=false 时必须声明 columns。返回 dataset 引用、来源工作表和行数。日期时间转 ISO 文本，布尔、数字与空值保留；不导入单元格样式。错误单元格报错。默认读取公式缓存，缓存缺失报错；formula_mode=formulas 返回公式文本，插件不计算公式。

create/write 可传 values 等宽二维数组，或 dataset 引用，二者互斥。start_cell 默认 A1；导出数据集默认带表头，可设置 include_header=false。write 的 sheet 不存在时需要 create_sheet=true。普通字符串默认按文本写入，明确要写公式时设置 formulas=true。超过15位的整数须改用文本，避免 Excel 数值精度损失。

```python
async def run(ctx, inputs):
    document = await ctx.call("excel.create", {
        "path": "汇总.xlsx",
        "sheet": "结果",
        "dataset": inputs["dataset"],
    })
    return ctx.result(data=document)
```

向已有模板写入并保留原件：

```python
async def run(ctx, inputs):
    document = await ctx.call("excel.write", {
        "path": "模板.xlsx",
        "output_path": "填写结果.xlsx",
        "sheet": "明细",
        "start_cell": "A3",
        "dataset": inputs["dataset"],
    })
    return ctx.result(data=document)
```

原地写入需明确 overwrite=true；新建或另存目标已存在时拒绝覆盖。目标区域以外的普通单元格、样式与公式保留，写入只处理指定矩形，不自动清除原区域余下行。保存到同目录临时文件，成功后发布；取消/失败不发布不完整文件，原地写前核对源内容未改变。此目录与摘要检查是本地操作约束，不保证恶意并发替换路径或校验后竞争写入的隔离。

TaskWeave 写入者通过目标目录内的排他锁覆盖读取—修改—发布全过程，跨 worker 并发写同一目标会报 EXCEL_FILE_BUSY。正常结束清理本次锁；异常终止残留锁时，需核对相关进程及文件状态后处理，插件不会自动删除未知锁。其他应用不遵循该锁，源内容检查仍用于发现其已完成的修改。

## 范围

首版支持 `.xlsx`；不支持 `.xls`、宏、Excel 应用自动化或公式计算。包含图形、图表、外部链接、嵌入对象、透视表等复杂部件，或解析器提示可能丢失内容的工作簿，明确拒绝写入并保留原文件。普通模板支持范围及完整往返限制参考 [openpyxl 官方说明](https://openpyxl.readthedocs.io/en/stable/tutorial.html)。

文件最多20 MiB，ZIP解压累计最多100 MiB/10000项；读取及写入数据还受行列、单元格与16 MiB数据上限约束。超限失败，完整导出不使用截断预览。工作簿公式缓存不会由插件重新计算，写入后应由实际表格软件计算保存再读取缓存值。

两平台构建清单包含插件、openpyxl、et_xmlfile、defusedxml 与 metadata；收集检查不代表 Windows EXE 或 Excel 应用实机验收。验证入口统一在 tests/module-map.json 的 plugins.excel。
