# 任务包、复制与规划导入

来源：[任务包schema](../../src/taskweave/core/task_package.py)、[task_transfer.py](../../src/taskweave/application/task_transfer.py)、[规划服务](../../src/taskweave/application/planning.py)。

## 已实现的JSON任务包

format固定taskweave-task-2；origin为task_export或ai_generated。task含name、description、input_schema；steps最多1000项，每项含可移植key、validation_state、document；contexts可携带组和采集项。步骤document字段见schema，不把数据库行原样当分享包。

前序step_id导出为包内key，导入生成新任务/步骤ID并重映射。schema、内容、插件依赖和引用都校验，不运行内容，不覆盖原任务，失败回滚。v1不做隐式兼容，需当前版本重新导出。

ai_generated只能导入DRAFT；task_export恢复每步合法确认状态，不能将所有导入都写成MANUAL/VALIDATED，也不能将所有导入强制变草稿。规划缺证据步骤可空代码导入草稿，非空仍严格校验。

默认分享定义、依赖、参数schema及其默认值、显式上下文；不导出环境对象、运行DB、历史、活资源和运行产物。用户写入参数默认值、步骤源码或采集原文的秘密仍可能进入包，不能保证包自动无敏感信息；分享前须检查实际内容。

复制任务重映射步骤引用并复制上下文组项，保持源对象；复制规划不复制会话和生成记录。规划候选按plan_context_refs从生成时冻结快照复制到目标步骤，不从最新规划偷换证据；每次显式重复导入创建独立任务和上下文副本，失败由事务回滚。存在冻结材料时，每个步骤必须在plan_context_refs中明确列出相关组ID（无相关材料为[]），遗漏会在解析和导入时被拒绝。

## 交互与边界

任务页支持JSON导出、复制、下载和粘贴导入。原生桌面下载写home/exports下独立UTF-8文件并打开目录，浏览器模式使用浏览器下载；剪贴板等异步操作须确认实际成功。环境不提供分享导入导出。

完整zip manifest/资源清单、离线wheel、冲突覆盖/角色映射与控制流/布局分享仍属于 [后续范围](../roadmap.md)，不能把现有JSON分享等同整套离线分发完成。

验证重点：独立临时home往返、绑定/上下文项保真、缺依赖/版本冲突、非法包拒绝、失败回滚及源对象不变。无需重读旧需求；模块入口见 [任务与步骤](../modules/tasks.md)。
