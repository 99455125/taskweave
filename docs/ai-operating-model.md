# AI 工作模式

## 文档权责

| 内容 | 唯一主文档 |
|---|---|
| 项目入口 | README.md |
| 工具指令 | AGENTS.md；CLAUDE.md 仅引用 |
| 人机协作 | AI_GUIDE.md、TASK_TEMPLATE.md |
| 工作流 | 本文 |
| 工程与模块边界 | engineering-playbook.md、architecture.md |
| 项目持续状态 | project-plan.md、progress.md |
| 需求上下文 | requirements/REQ-xxx-名称/ |
| 验证与运行 | testing.md、deployment.md |

## 工作流程

检查现场 → 明确范围 → 记录设计/影响 → 实施 → 针对性验证 → 更新进度 → 交付。

非平凡需求建立独立 REQ 目录，维护 README、design、code-mapping、progress、validation。需求文档保存可持续的决策，不转存完整聊天记录。项目规则只放在项目级文档，需求目录记录差异。

## 交付约定

报告目标、改动、关键实现、兼容影响、验证证据和剩余项。标清“已实现 / 待设计 / 未验证”。跨对话先读进度，再检查代码；代码与文档冲突时核查并修正文档，不能靠猜测补齐。

## 完成标准

本轮授权范围完成、对应检查通过或明确受限原因、相关文档同步。结构准备不等于功能已实现；脚手架不使用假成功的执行结果。
