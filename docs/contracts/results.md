# 结果、引用与展示

## 步骤返回

StepResult包含data、outputs和views。data是普通JSON；outputs是ResultRequest序列，每项包含handler_id、name、payload；views是对已保存data的展示声明。data默认保存，不要求每一步产生非空业务值。

ResultHandler将ResultRequest准备成JSON、表格或文件，宿主完成写入并产生ResultRef。表结果声明当前`tables`和`indexes`，宿主按实际列校验；结构不符报告`TABLE_SCHEMA_MISMATCH`，不读取迁移版本或自动执行列变更。插件表登记只保留表名，供运行与结果清理使用。文件先通过allocate_file取得StagedFile，写入后用token提交；插件本地local_path不返回给模型或普通ctx.call调用方。

## 持久化引用

ResultRef包含result_id、handler_id、kind、locator、media_type，可带checksum和size_bytes。locator是作用域内相对引用，不是任意文件系统路径。控制库保存结果引用/状态，任务数据和文件保存在任务目录；回执及清理逻辑处理跨库/文件的一致性。

重跑使旧有效结果失效，但保留历史尝试；查看输出须核对run、step和有效attempt。没有可用输出可能报告OUTPUT_NOT_AVAILABLE，不能据此推断整个尝试失败，也不能转读其他运行的结果。

## 内部数据集

内部数据集使用轻量 JSON 引用在步骤 data/绑定中传递，完整表数据另以 `dataset.table` 的 table 结果保存。引用的任务、运行、步骤、attempt 和数据集身份由宿主核对；来源失效或结果删除后不能继续读取。数据集表与元数据随普通输出同事务提交，结果预览明确返回总行数和截断状态。精确端口见 [dataset_contracts.py](../../src/taskweave/core/dataset_contracts.py)，使用见[内部数据集插件](../../plugins/dataset/README.md)。

## 展示声明

每项view需非空且不重复的title、已注册renderer。通常用pointer引用data中的可解析JSON Pointer；图片view也可用output直接引用本次outputs中的图片文件名，与pointer互斥。宿主校验该输出确为本次保存的图片文件，不包装或修改业务data。内置renderer为core.json、core.table、core.image和core.report；插件可注册自己的renderer。查看结果读取持久数据，不重新执行动作。浏览器插件通过可选result_artifacts钩子为实际涉及页面追加图片输出和view；失败证据钩子也可返回带views的StepResult，诊断保存不生成成功回执。自动截图不要求业务步骤额外声明page_screenshot能力，显式截图仍按原能力授权校验。

错误信息ErrorInfo区分code、message、phase和effect_state；副作用状态为NOT_STARTED、SUCCEEDED、FAILED、UNKNOWN，不能与运行状态混为一谈。

## 实现与验证

[数据类](../../src/taskweave/core/ports.py)、[展示校验](../../src/taskweave/core/result_views.py)、[结果适配](../../src/taskweave/infrastructure/storage.py)、[结果仓储](../../src/taskweave/infrastructure/repositories/results.py)、[UI查看器](../../src/taskweave/desktop/components/result_viewer.py)。验证定位repository.results、ui.results及相应插件handler测试。
