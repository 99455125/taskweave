# 实现映射与交接

本需求的可执行文件都属于设计验证，不进入 src 的产品运行路径。

| 契约 | 实施位置（拟议） | 负责需求 |
|---|---|---|
| Step/task/result/types 与绑定校验 | src/taskweave/core/models.py、bindings.py | REQ-003 |
| save/generate/validate/trial/confirm | src/taskweave/application/step_authoring.py | REQ-003 |
| ModelPort 与模型通信 | infrastructure/ai/ | REQ-003 |
| run 命令、状态和租约 | application/runs.py、infrastructure/runtime/ | REQ-003 |
| control.sql/task-data.sql 迁移与 scoped store | infrastructure/storage/ | REQ-003 |
| Plugin/Action/ResultHandler/ResourceProvider | src/taskweave/plugins/ | REQ-004 |
| Playwright 的执行、编写贡献、图片处理 | plugins/playwright/ | REQ-004 |
| 基础页面与编写/调试操作 | apps/workbench/ | REQ-005 |
| TaskDocument 分享、ID 映射和依赖 | application/sharing.py | REQ-006 |
| Windows/真实浏览器/离线交付 | scripts/、集成测试 | REQ-007 |
| 非 action 节点语义、execution_path | core/、运行/存储适配 | REQ-008 |
| ui_layout 与共享任务模型 | apps/workbench/ | REQ-009 |

旧代码不强制复用。REQ-003 用模拟插件即可完成核心，不提前实现 REQ-004 的真实浏览器或 UI。
