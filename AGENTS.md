# Repository Working Instructions

## 开工前阅读

1. `README.md`
2. `docs/ai-operating-model.md`
3. `docs/engineering-playbook.md`
4. `docs/architecture.md`
5. `docs/project-plan.md`
6. `docs/progress.md`
7. 受影响目录的 README，以及当前 `docs/requirements/<REQ>/` 中的需求、设计、映射、进度和验证记录。

## 工作边界

- 本仓库是 TaskWeave 单一 Python 工程；`legacy/` 是历史参考，不属于新包。
- 当前初始化需求为 `REQ-001-project-foundation`。后续工作按需求编号独立建档，不将所有需求塞进初始化需求。
- 核心只编排任务与步骤，不直接依赖 Excel、Playwright、数据库驱动或 AI 服务。
- AI 辅助开发与产品运行分开；默认执行路径不调用大模型。
- 本地部署、本地数据库、模板和插件分享是既定方向。
- 需求范围外不实现 UI、调度、插件市场或通用工作流引擎。
- 旧数据、未提交的用户文件和本地配置不随结构调整删除。迁移代码必须核对原有行为与来源分支。

## 实施与交付

先检查 Git 状态、相关代码和文档，再实施与验证。需求变更同步更新项目进度和需求文档。新依赖仅在当前功能需要时引入，插件依赖不进入核心默认依赖。

接口、任务模板格式、插件契约和数据库变更应记录版本与兼容策略。不得把计划写成已实现。

执行 `python scripts/check_project.py`，并按 `docs/testing.md` 运行受影响检查。报告变更、验证结果、剩余限制。未经实际执行不得声称测试通过。
