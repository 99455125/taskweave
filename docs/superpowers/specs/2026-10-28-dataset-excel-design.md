# 内部数据集与 Excel 插件

用户已确认内部数据集与外部数据库连接分工，并要求完成内部数据集及 Excel 读取、新建、写入。插件 ID 采用 `dataset`（内部数据集）与 `excel`。沿用当前工作区；本次只运行定向验证，不提交、推送或修改真实用户文件。

## 方案与范围

内部数据集由宿主管理；SQLite 是宿主实现，插件无需数据库地址或账号。TiDB 保留外部数据库能力。曾考虑复用 TiDB 或暴露通用 SQLite 文件连接，均不符合已确认的内部数据归属；选择宿主数据集端口加独立插件动作。Excel 消费同一端口，不跨插件调用动作。

数据集是有序列和有序行组成的不可变结果。创建和 SQL 操作返回 JSON 引用，由既有步骤绑定传递，避免把全部数据送入步骤参数。引用限定当前任务、运行和有效成功 attempt；来自其他步骤的引用还须出现在本步已解析输入中。同一 attempt 可读取刚创建的数据集。循环/并行依赖沿用宿主输入解析，重试生成新引用，历史输入不被覆盖。

宿主提供 DatasetStore 协议，PluginContext.datasets 暴露 create/describe/read/query/execute。实际数据以每数据集独立表保存到 tasks/<task_id>/data.db；物理列 c0/c1 等，元数据保留原列名和类型。写入在步骤成功的 Results.persist 中与输出/回执同事务完成，动作阶段只暂存。失败和取消不发布数据集。现有 plugin_table_schemas 跟踪物理表，结果引用采用既有 table kind、dataset.table handler；读取和删除适配元数据、空表与清理，不改变现有数据库版本。已提交回执恢复沿用现有流程。

SQL 在仅含显式输入数据集的临时内存数据库中执行。dataset.query 接受 sources 别名映射和单条 SELECT/CTE，返回新数据集；dataset.execute 接受一个源数据集、单条 INSERT/UPDATE/DELETE（表名 data），复制修改后返回新数据集。禁止 ATTACH、PRAGMA、事务控制、扩展加载、DDL 和外部 I/O，参数绑定使用 ?。允许常见聚合/关联和表达式；限制语句、行、列、单值、结果大小与执行时间，取消可中断，不截断生成的新数据集。read 为分页预览，明确 total/offset/truncated。

列声明 name/type，类型为 text、integer、number、boolean、any，允许 null；金额需精确时使用文本或整数最小单位，不自动转浮点。列名大小写冲突拒绝；空数据集保留列结构。单数据集最多 100000 行、256 列、1000000 单元格、16 MiB JSON 数据，单步累计暂存最多 32 MiB、16 个数据集；SQL 最多 64 KiB、10 秒。

## Excel

实现选择由 agent 承担：使用可选 openpyxl 3.1.x 与 defusedxml，首版 .xlsx。支持 excel.inspect（工作表和区域信息）、excel.read（指定工作表/区域、表头读取到数据集）、excel.create（新建，可附初始二维值）、excel.write（既有文件指定工作表和起始单元格写入二维值或数据集，可另存）。excel 依赖 dataset 插件；依赖不进入核心默认安装。

excel_root 为显式目录，任务参数覆盖环境；路径不得越界，拒绝符号链接写入。create 与另存目标默认不覆盖；write 原地写入必须显式 overwrite=true。临时文件保存成功后才发布，失败保留原文件，原地写前校验原文件未被他人改动；已有内容先读取验证，不生成用户目录。写入只覆盖明确目标区域，其他常规单元格、样式和公式保留。默认字符串作为文本，显式 formulas=true 才把 = 开头字符串写成公式；不执行公式计算。

读取默认 formula_mode=values，遇到公式缓存缺失报错；formula_mode=formulas 返回公式文本。日期时间转 ISO 文本，布尔/数字/空值保留；错误单元格报错。表头需非空且唯一，可显式 columns 覆盖，header=false 时要求 columns。限定压缩文件大小 20 MiB、解压总量 100 MiB、10000 ZIP 项；超限拒绝，区域也受数据集行列/单元格限制。

openpyxl 不保证复杂 Excel 对象的完整往返。写入对 drawing、VBA、外部链接、嵌入对象、透视表等复杂部件及库报告的丢失警告明确拒绝，避免损失原文件内容；不支持旧 .xls、宏、图表编辑、公式计算或 Excel 应用自动化。新建与普通表格/模板单元格写入是本次交付范围。

## 接入与验收

通过 entry point 注册并显式启用两个插件，沿用通用插件/步骤 UI，不新增数据编辑器。打包清单收集两插件、openpyxl/et_xmlfile/defusedxml 与 metadata。README、插件/存储/契约/开发/打包知识及 tests/module-map.json 随实现同步。

验证真实 SQLite 暂存/提交/重启读取、同任务运行隔离、失效引用、删除、空表、SQL 关联/参数/回滚/取消/越权；Excel 多工作表、表头、类型、创建、区域写入、数据集导出、公式文本、模板保留、路径/覆盖/失败清理；真实 Application/worker 完成 Excel 导入→SQL→新建导出→读取核对。执行定向插件/结果生命周期/打包测试与工程检查，不把打包收集称为 Windows 实机验收。

参考：[openpyxl 读写与限制](https://openpyxl.readthedocs.io/en/stable/tutorial.html)、[SQLite authorizer](https://www.sqlite.org/c3ref/set_authorizer.html)。

## 实施审查补充

Excel写入增加跨worker的目标文件排他锁，覆盖读取、修改和发布；锁冲突报忙，进程异常残留锁保留待核对。SQL的行长度限制按完整数据集上限配置，源装载错误统一报告；execute 使用未被用户列占用的隐式行号保持原顺序和原布尔类型。同占 rowid/_rowid_/oid 的数据集需先 query 重命名一列，避免无可靠行序时静默变更数据。
