# 规划

## 职责与对象

规划组织任务目标、插件选择、环境和上下文材料，经API生成或网页Chat回复解析形成候选任务。规划配置、采集会话、生成记录与导入后的任务分别拥有独立身份。

## 当前流程

1. 保存配置并更新revision；需要后端已保存配置的动作先完成保存。
2. 采集并保存上下文组。生成时冻结规划、能力及材料快照，而非随后读取最新素材。
3. API调用模型或导出Chat提示词，回复经结构解析、能力/引用校验和诊断，生成候选记录。
4. 查看、采纳或导入时核对目标及生成身份；使用冻结材料导入独立任务。

生成记录状态为GENERATING、READY、BLOCKED、FAILED、IMPORTED。同一候选支持显式重复导入，plan_generation_imports保存各次关联；不通过一次导入永久消费候选。

PlanningInteraction处理生成/候选、查询身份和导入协调，PlanEditorSession处理配置草稿、revision及素材变更。失败保留草稿，旧响应不更新新规划；目录搜索和分类由普通状态承载。页面的基础配置、能力与素材、生成记录三个页签共用同一候选详情。

## 代码与边界

- [PlanningService](../../src/taskweave/application/planning.py)：业务校验、快照、生成解析与导入事务。
- [PlanningInteraction / PlanEditorSession](../../src/taskweave/presentation/planning.py)：框架无关交互、明确操作协议及身份保护。
- [规划仓储](../../src/taskweave/infrastructure/repositories/plans.py)、[生成记录仓储](../../src/taskweave/infrastructure/repositories/plan_generations.py)、[上下文仓储](../../src/taskweave/infrastructure/repositories/plan_contexts.py)：分别保存各自数据，复用共享UoW。
- [PlanningPage](../../src/taskweave/desktop/pages/planning.py)组合[采集视图](../../src/taskweave/desktop/components/planning_collection.py)及[生成视图](../../src/taskweave/desktop/components/planning_generations.py)；desktop/planning.py只保留兼容导出。

采集与录制复用[上下文模块](contexts.md)，提示和模型处理复用[AI编写](authoring.md)，导入形状遵守[任务包契约](../contracts/task-packages.md)。

## 验证定位

application.planning、ui.planning；检查revision冲突、快照与最新材料隔离、晚到候选、导入失败原子性、重复导入及保存失败后的材料保留。
