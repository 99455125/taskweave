# TaskWeave · 任务织流

本地任务与步骤自动化工具。定义任务、编排步骤，通过插件执行 Excel、浏览器自动化和自定义业务操作。同一个任务可以组合多种能力。

当前版本是 **结构初始化阶段**：已建立新的 Python 包和工程规范，旧实现完整保存在 `legacy/smart_excel/`。新的任务执行器、插件加载器、UI 和数据迁移尚未实现。

## 使用场景

每位开发在自己的电脑或 Windows 虚拟机内运行，使用本地数据库和本地配置。AI 在虚拟机外辅助开发；虚拟机内执行确定的步骤，无需连接 AI。后续通过模板和插件包的导入导出分享流程，不要求共享服务部署。

## 目录

```text
src/taskweave/
  core/             任务、步骤、运行上下文、执行器（待实现）
  plugins/          插件契约与注册机制（待实现）
  infrastructure/   本地存储、配置、日志（待实现）
  application/      应用用例与入口适配（待实现）
plugins/            Excel、Playwright、自定义插件规划
apps/               UI / API 入口规划
examples/           后续任务模板和插件示例
config/             配置约定
scripts/            工程校验脚本
tests/              新架构验证入口
legacy/smart_excel/ 原有代码、依赖、接口文档与示例
docs/               架构、AI 工作流、需求、计划与进度
```

## 初始化环境

新工程要求 Python 3.10+，当前核心没有第三方运行依赖。

```bash
python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e .
taskweave --version
taskweave --help
python scripts/check_project.py
```

`taskweave` 当前仅提供版本和帮助检查，不会启动旧服务、访问数据库或执行任务。旧实现的使用与限制见 [历史实现](legacy/smart_excel/README.md)。

## AI 协作入口

- [AGENTS.md](AGENTS.md)：AI 开工前的阅读顺序与边界。
- [AI_GUIDE.md](AI_GUIDE.md)：给人的协作说明。
- [TASK_TEMPLATE.md](TASK_TEMPLATE.md)：分析、实施和评审请求模板。
- [架构](docs/architecture.md)、[计划](docs/project-plan.md)、[进度](docs/progress.md)。
- [REQ-001 工程初始化](docs/requirements/REQ-001-project-foundation/README.md)。

## 命名与历史

产品名为 TaskWeave，Python 包与命令为 `taskweave`。这是项目内部命名，尚未核验公共包名或商标可用性，不代表发布到 PyPI。

本地目录为 `taskweave`，公开仓库为 [99455125/taskweave](https://github.com/99455125/taskweave)，默认分支为 `main`。新仓库从干净的初始提交开始；旧仓库历史只保留在本地，详见 [迁移记录](docs/migration.md)。
