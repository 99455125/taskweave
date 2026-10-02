# TaskWeave · 任务织流

本地任务与步骤自动化工作台。通过手写或 AI 辅助编写步骤，结合插件完成浏览器、数据库和其他业务操作；固定步骤执行无需连接模型。每位用户保留自己的环境、账号和运行数据。

## 开发与启动

使用 Python 3.10+ 和 uv，依赖定义在 pyproject.toml，锁定版本在 uv.lock。

```bash
uv sync --locked
uv run taskweave --help
uv run python scripts/check_project.py
```

桌面工作台及可选插件：

```bash
uv run --extra gui --extra browser --extra ocr --extra database --extra utility --extra files taskweave workbench
```

可按使用需要选择 extras。Playwright 需匹配的本机 Chromium；启动不会替你完成目标 Windows 便携交付验收。安装、服务与平台说明见 [运行与交付](docs/deployment.md)。

## AI 协作与维护

从 [AGENTS.md](AGENTS.md) → [维护索引](docs/maintenance.md) → 受影响模块开始。无需通读其他需求目录。

- [当前架构](docs/architecture.md)：依赖方向和跨模块约束。
- [当前状态](docs/status.md)：正在做什么、已知问题及未验证范围。
- [测试规则](docs/testing.md)：按模块验证，浏览器显式选择。
- [协作指南](AI_GUIDE.md)与[任务模板](TASK_TEMPLATE.md)：按改动规模记录，普通改动不强制建 REQ。

## 代码布局

```text
src/taskweave/
  core/             内容、校验、端口和结果契约
  application/      任务、步骤、规划、AI 编写与运行用例
  infrastructure/   仓储、事务、运行协调、worker、模型适配
  desktop/          页面、组件和本地桌面入口
  plugins/          插件 SDK、发现和注册
plugins/            Playwright、OCR、TiDB、utility 独立包
scripts/            工程检查和模块测试选择
tests/              功能、仓储、应用和 UI 测试
docs/modules/       模块当前知识
docs/requirements/  既有需求交付档案（按需追溯）
```

项目名、Python 包与命令均为 taskweave。旧项目迁移背景见 [迁移记录](docs/migration.md)，历史需求见 [档案索引](docs/requirements/README.md)；两者不属于日常开工必读项。
