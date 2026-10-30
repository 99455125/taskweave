# 任务包

任务导入与导出统一使用`taskweave-task-3`，线性任务也携带流程树。Schema在[core/task_package.py](../../src/taskweave/core/task_package.py)，规范化、验证与导入在[application/task_transfer.py](../../src/taskweave/application/task_transfer.py)。完整任务包必须符合现行格式。

## 外层结构

| 字段 | 约束 |
| --- | --- |
| format | taskweave-task-3 |
| origin | task_export或ai_generated |
| task | name、description、input_schema |
| steps | 最多1000项；每项key、validation_state、document |
| flow、flow_validation_state | 必填；流程树动作通过步骤key关联，导入时映射为新身份 |
| contexts | 可选；只有task_export来源可以携带上下文组 |

步骤document遵守[步骤契约](steps.md)，导出包包含完整字段；validation_state取DRAFT或VALIDATED，实际确认还须依据内容、来源和运行时验证规则。顶层和步骤定义不接纳任意未知字段。流程使用`version: 2`与`root`，条件节点声明`cases`和`default`，每条分支拥有身份与流程体；精确结构及引用校验见[task_flow.py](../../src/taskweave/core/task_flow.py)。

## 身份与材料

导出把真实步骤ID改成包内key，步骤绑定及流程树引用同步改写；导入建立新任务/步骤ID，再映射引用。不能保留指向原任务的运行身份。上下文组通过step_key关联，保留有序采集项、request、items/views、操作说明和send_preview；可选材料字段按契约处理。

任务包不包含本地环境、秘密引用配置、运行/尝试历史或活跃资源。AI生成包不能冒充带原始采集材料的完整导出包。历史完整包格式在导入入口明确拒绝；先通过显式数据维护处理已知历史定义，再使用现行格式重新导出。维护范围与入口见[存储模块](../modules/storage.md)。

## 导入边界

先校验外层、Schema、引用、代码与插件要求，再以用例事务写入，失败回滚。桌面文件导入限32MiB、文本入口限2Mi字符；本地HTTP有独立传输限制，不能用桌面文件上限推断HTTP可接收同等大小。界面关闭或离页只阻止旧结果展示，不撤销已接受的导入。
