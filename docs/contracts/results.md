# 结果、引用与展示

## 步骤返回

StepResult包含data、outputs和views。data是普通JSON；outputs是ResultRequest序列，每项包含handler_id、name、payload；views是对已保存data的展示声明。data默认保存，不要求每一步产生非空业务值。

ResultHandler将ResultRequest准备成JSON、表格或文件，宿主完成写入并产生ResultRef。文件先通过allocate_file取得StagedFile，写入后用token提交；插件本地local_path不返回给模型或普通ctx.call调用方。

## 持久化引用

ResultRef包含result_id、handler_id、kind、locator、media_type，可带checksum和size_bytes。locator是作用域内相对引用，不是任意文件系统路径。控制库保存结果引用/状态，任务数据和文件保存在任务目录；回执及清理逻辑处理跨库/文件的一致性。

重跑使旧有效结果失效，但保留历史尝试；查看输出须核对run、step和有效attempt。没有可用输出可能报告OUTPUT_NOT_AVAILABLE，不能据此推断整个尝试失败，也不能转读其他运行的结果。

## 展示声明

每项view需非空且不重复的title、已注册renderer、可解析JSON Pointer。内置renderer为core.json、core.table、core.image和core.report；插件可注册自己的renderer。查看结果读取持久数据，不重新执行动作，不为未声明的文件凭空生成展示项。

错误信息ErrorInfo区分code、message、phase和effect_state；副作用状态为NOT_STARTED、SUCCEEDED、FAILED、UNKNOWN，不能与运行状态混为一谈。

## 实现与验证

[数据类](../../src/taskweave/core/ports.py)、[展示校验](../../src/taskweave/core/result_views.py)、[结果适配](../../src/taskweave/infrastructure/storage.py)、[结果仓储](../../src/taskweave/infrastructure/repositories/results.py)、[UI查看器](../../src/taskweave/desktop/components/result_viewer.py)。验证定位repository.results、ui.results及相应插件handler测试。
