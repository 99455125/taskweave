# 任务包

现行格式为`taskweave-task-2`，Schema在[core/task_package.py](../../src/taskweave/core/task_package.py)，规范化、验证与导入在[application/task_transfer.py](../../src/taskweave/application/task_transfer.py)。

## 外层结构

| 字段 | 约束 |
| --- | --- |
| format | 固定taskweave-task-2 |
| origin | task_export或ai_generated |
| task | name、description、input_schema |
| steps | 最多1000项；每项key、validation_state、document |
| contexts | 可选；只有task_export来源可以携带上下文组 |

步骤document遵守[步骤契约](steps.md)，导出包包含完整字段；validation_state取DRAFT或VALIDATED，实际确认还须依据内容、来源和运行时验证规则。顶层和步骤定义不接纳任意未知字段。

## 身份与材料

导出把真实步骤ID改成包内key，步骤绑定同步改写；导入建立新任务/步骤ID，再映射前序引用。不能保留指向原任务的运行身份。上下文组通过step_key关联，保留有序采集项、request、items/views、操作说明和send_preview；旧包缺可选材料字段按实现默认值处理。

任务包不包含本地环境、秘密引用配置、运行/尝试历史或活跃资源。AI生成包不能冒充带原始采集材料的完整导出包。v1包明确拒绝，需要用现行版本重新导出，不静默猜测转换。

## 导入边界

先校验外层、Schema、引用、代码与插件要求，再以用例事务写入，失败回滚。桌面文件导入限32MiB、文本入口限2Mi字符；本地HTTP有独立传输限制，不能用桌面文件上限推断HTTP可接收同等大小。界面关闭或离页只阻止旧结果展示，不撤销已接受的导入。
