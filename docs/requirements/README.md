# 需求档案索引

需求记录一次变化，模块文档描述当前系统。日常维护从 [维护索引](../maintenance.md) 定位；当前进行中事项、交付状态与已知问题只维护在 [status.md](../status.md)。本表仅登记编号与主题，不复制状态。

| 编号 | 主题/档案入口 |
| --- | --- |
| REQ-001 | [原始总需求池](REQ-001-requirement-pool/README.md)（历史范围与顺序，不作为当前执行指令） |
| REQ-002 | [总体设计](REQ-002-task-plugin-design/README.md) |
| REQ-003 | [任务与步骤](REQ-003-task-core/README.md) |
| REQ-004 | [插件架构与 Playwright](REQ-004-plugin-contract/README.md) |
| REQ-005 | [跨平台工作台](REQ-005-local-workbench/README.md) |
| REQ-006 | [任务与插件分享](REQ-006-template-sharing/README.md) |
| REQ-007 | [基础版本集成与交付](REQ-007-v1-release/README.md) |
| REQ-008 | [条件、循环与嵌套流程](REQ-008-flow-control/README.md) |
| REQ-009 | [流程图拖拽编排](REQ-009-visual-flow-editor/README.md) |
| REQ-010 | [DDD 模块化与行为保真](REQ-010-ddd-modularization/README.md) |

下一可用编号为 REQ-011；这不表示应自动创建或启动它。旧目录及签署记录保留原貌，里面的状态、路径和契约可能只适用于当时版本。

普通改动无需创建 REQ。确需需求交付时按 [协作方法](../ai-operating-model.md) 建立最少必要记录。完成后提炼已实现行为更新对应模块，不要求阅读或修改其他需求目录，也不把同一状态复制到每个需求 README。

REQ-001至REQ-010的现行契约、长期决策和未来范围已提炼到模块/专题/路线文档，逐文件来源与过期规则处理见 [完整知识迁移台账](../archive/req-knowledge-migration.md)。日常维护不需要阅读本目录；只有核查某次原始需求、验收日志或签署时回查。原档案保留，不同步改写为今天的状态。
