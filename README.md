# TaskWeave · 任务织流

本地任务与步骤自动化工作台。通过手写或AI辅助编写步骤，结合插件完成浏览器、数据与开发运维操作；固定步骤执行无需连接模型。配置、账号引用与运行数据保存在用户本机。

## 知识入口

从[文档总览](docs/README.md)开始，按问题进入：

- [领域模型](docs/domain.md)：任务、步骤、规划、运行、尝试、结果和资源会话。
- [系统架构](docs/architecture.md)：core、application、presentation、desktop、infrastructure及插件的依赖边界。
- [模块导航](docs/maintenance.md)：能力、代码入口和测试键。
- [契约](docs/contracts/README.md)：步骤、任务包、插件、操作、结果和配置。
- [开发](docs/development.md)、[测试](docs/testing.md)、[运行与打包](docs/deployment.md)。
- [能力边界](docs/limitations.md)：当前产品范围及验证含义。

## 快速启动

要求Python≥3.10和uv，锁文件为uv.lock：

```bash
uv sync --locked --extra gui --extra browser --extra utility
uv run playwright install chromium
uv run taskweave workbench
```

按需要选择其他extras；原生窗口、浏览器开发模式、本地API及平台构建见运行指南。仅检查工程可执行：

```bash
uv run python scripts/check_project.py
```

## 外部 AI 接入

外部 AI 可通过 MCP 或 function calling 编写、验证及调用已有任务，支持当前分支、循环、嵌套和任务组合。在工作台“设置 → 外部 AI / MCP”复制配置并安装 Skill，或执行：

```bash
uv run --extra mcp taskweave connection-config
uv run taskweave skill ~/.agents/skills/taskweave
```

保持目标工作空间的工作台或 serve 运行；配置中的桥接进程连接同一实例。执行后可由 AI 打开“查看验收”，检查路径、核对项及原始结果，再由用户记录决定。详见[外部 AI 接入](docs/modules/agent.md)。

## 仓库布局

```text
src/taskweave/  核心契约、用例、交互、基础设施、桌面适配与SDK
plugins/        十四独立插件包及可选依赖
packaging/      macOS与Windows分发入口
scripts/        工程、测试选择及构建工具
tests/          功能、交互、仓储、应用、UI与集成验证
docs/           当前软件知识
examples/       本地演示与组合示例
```

本仓库文档以当前实现为准，旧需求、阶段验收和AI协作资料不再作为知识入口。工程约束见[AGENTS.md](AGENTS.md)。
