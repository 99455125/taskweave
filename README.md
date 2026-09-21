# TaskWeave · 任务织流

本地任务与步骤自动化工具。定义任务、编排步骤，通过插件执行浏览器自动化和自定义业务操作。同一个任务可以组合多种能力。

当前已实现 **REQ-003 可运行核心**：任务与步骤管理、调试确认、顺序执行、SQLite 结果传递、运行控制及可选 AI 编写服务。提供 CLI 和本地 HTTP API；真实 Playwright 插件现已接入；跨平台工作台现已实现，Windows 便携包由 REQ-007 实现。旧 Excel 实现已移除。

## 使用场景

每位开发在自己的电脑或 Windows 虚拟机内运行，使用本地数据库和本地配置。产品通过 AI 生成和调试 step content，验证后保存固化；允许使用 AI 的环境负责生成，虚拟机内执行固定步骤，无需连接 AI。后续通过模板和插件包的导入导出分享流程，不要求共享服务部署。

## 目录

```text
src/taskweave/
  core/             任务、步骤、运行上下文、执行器
  plugins/          插件契约与注册机制
  infrastructure/   本地存储、配置、日志
  application/      应用用例与入口适配
plugins/            Playwright、自定义插件规划
apps/               UI / API 入口规划
examples/           后续任务模板和插件示例
config/             配置约定
scripts/            工程校验脚本
tests/              新架构验证入口
docs/               架构、AI 工作流、需求、计划与进度
```

## 初始化环境

新工程要求 Python 3.10+，运行依赖包含 JSON Schema 校验器。

```bash
uv sync --locked
uv run taskweave --version
uv run taskweave --help
uv run python scripts/check_project.py
```

运行示例：`uv run taskweave --home .runtime/req003-demo demo`。接口入口：`uv run taskweave --home .runtime/workbench serve`。详见 [REQ-003 使用指南](docs/requirements/REQ-003-task-core/usage.md)。

独立客户端：`uv run --extra gui --extra browser --extra ocr --extra database taskweave workbench`。

## AI 协作入口

- [AGENTS.md](AGENTS.md)：AI 开工前的阅读顺序与边界。
- [AI_GUIDE.md](AI_GUIDE.md)：给人的协作说明。
- [TASK_TEMPLATE.md](TASK_TEMPLATE.md)：分析、实施和评审请求模板。
- [架构](docs/architecture.md)、[计划](docs/project-plan.md)、[进度](docs/progress.md)。
- [REQ-001 总需求池](docs/requirements/REQ-001-requirement-pool/README.md)。

## 命名与历史

产品名为 TaskWeave，Python 包与命令为 `taskweave`。这是项目内部命名，尚未核验公共包名或商标可用性，不代表发布到 PyPI。

本地目录为 `taskweave`，公开仓库为 [99455125/taskweave](https://github.com/99455125/taskweave)，默认分支为 `main`。新仓库从干净的初始提交开始；旧仓库历史只保留在本地，详见 [迁移记录](docs/migration.md)。

## 当前规划

第一版聚焦 Playwright，支持产品内 AI 编写、调试并固化步骤、条件/循环/嵌套流程及图形拖拽编排。Excel 不纳入本期，运行时 AI 尚未纳入。完整范围见 [总需求池](docs/requirements/REQ-001-requirement-pool/backlog.md)。

总体详细设计已通过用户评审，见 [REQ-002 交付入口](docs/requirements/REQ-002-task-plugin-design/README.md)。REQ-003 核心现可运行；插件架构与 Playwright 已接入，运行见 [REQ-004 指南](docs/requirements/REQ-004-plugin-contract/usage.md)。REQ-005 跨平台客户端运行见 [指南](docs/requirements/REQ-005-local-workbench/usage.md)，Windows 实机与免安装打包仍待验证。

本地验证码识别插件：启动命令增加 `--extra ocr`，插件管理启用 ocr，步骤与 Playwright 配合使用。见 [插件指南](plugins/ocr/README.md)。

TiDB 查询与核对插件见 [使用说明](plugins/tidb/README.md)，使用 `--extra database` 安装；插件管理启用后选择。任务列表支持 JSON 配置分享，环境支持删除。
