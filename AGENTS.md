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
- `REQ-001-requirement-pool` 仅为总需求池，项目创建记录位于 `docs/project-setup/`；正式需求从 REQ-002 开始，总体设计见 REQ-002，实施按总需求池的有效需求及依赖顺序推进。每轮读取实际受影响需求，不将具体功能实现塞进 REQ-001。
- 核心只编排任务与步骤，不直接依赖 Excel、Playwright、数据库驱动或 AI 服务。
- REQ-003 包含产品内 AI 编写、调试和固化 step content；插件经统一接口贡献提示词与能力上下文。固定步骤执行路径不调用模型，模型 SDK 放在基础设施适配层。
- 本地部署、本地数据库、模板和插件分享是既定方向。
- 正式范围包含基础 UI、拖拽编排、条件/循环/嵌套、本地调度与存储。Excel 和运行时 AI 不纳入，插件市场与多运行并发保留候选。
- 旧数据、未提交的用户文件和本地配置不随结构调整删除。迁移代码必须核对原有行为与来源分支。

## 实施与交付

先检查 Git 状态、相关代码和文档，再实施与验证。需求变更同步更新项目进度和需求文档。新依赖仅在当前功能需要时引入，插件依赖不进入核心默认依赖。

接口、任务模板格式、插件契约和数据库变更应记录版本与兼容策略。不得把计划写成已实现。

执行 `python scripts/check_project.py`，并按 `docs/testing.md` 运行受影响检查。报告变更、验证结果、剩余限制。未经实际执行不得声称测试通过。

## 详细设计基线

REQ-002 已经用户评审确认，REQ-003 核心已交付，当前实施 REQ-005，插件与 Playwright 已交付。评审及实施前阅读其 README 与对应接口/DDL。旧代码仅参考，不要求兼容或复用不合理结构。后续实现从 REQ-003 开始，REQ-002 的模拟检查不能替代实际功能验收。

## Python 环境

项目使用 uv 管理 Python 与依赖，保留 uv.lock。同步使用 uv sync --locked，运行及验证使用 uv run；无需向 uv 虚拟环境安装 pip。
