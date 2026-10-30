# 开发指南

## 环境

主包要求Python≥3.10，使用uv和提交的uv.lock；macOS独立构建脚本使用Python3.12。核心默认依赖为jsonschema、packaging和certifi，GUI、浏览器、数据库等通过extras选择。

```bash
uv sync --locked
uv run taskweave --help
uv run python scripts/check_project.py
```

按需要同步可选能力，例如桌面与浏览器：

```bash
uv sync --locked --extra gui --extra browser --extra utility
uv run playwright install chromium
uv run taskweave workbench --browser
```

内部表格工作选择 `--extra dataset --extra excel`，Excel 引擎仅在可选插件中安装。

后续uv sync需继续列出需要的extras；它会使环境匹配所选集合。不向项目虚拟环境另行安装pip包，不以依赖升级代替架构或业务修复。

## 源码定位

| 目录 | 内容 |
| --- | --- |
| src/taskweave/core | 数据、校验与端口 |
| src/taskweave/application | 用例、显式装配与操作分发 |
| src/taskweave/presentation | UI框架无关的交互状态和流程 |
| src/taskweave/infrastructure | 存储、运行、资源、模型和HTTP实现 |
| src/taskweave/desktop | NiceGUI/pywebview页面、组件与平台适配 |
| src/taskweave/plugins | 宿主SDK、发现、注册 |
| plugins/ | 十五独立插件包 |
| tests/、scripts/、packaging/ | 验证、工程工具和平台分发 |

按[模块导航](maintenance.md)定位责任，接口见[契约](contracts/README.md)。模块文档描述当前行为；精确SQL/Schema/签名在源码维护，不在文档复制整份实现。

## 变更与验证

修改前核对工作区及真实依赖，保护已有修改、用户数据和配置。新业务能力先明确范围和验收，跨模块或持久化变化说明兼容策略；实现与知识同步更新。保留本地令牌和凭据，提交前检查文件范围。

纯文档修改执行工程/链接检查和git diff --check。产品源码变化按[测试指南](testing.md)预览消费者并运行必要验证；全量、真实外部系统、Git提交推送及发布分别按明确授权执行，不用计划或历史通过代替本次证据。
