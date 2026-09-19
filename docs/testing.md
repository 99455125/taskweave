# 验证

当前阶段不执行旧服务测试，因为旧服务会访问本地数据库并依赖旧环境。

## 结构检查（无第三方依赖）

```bash
uv run python scripts/check_project.py
```

检查新源码语法、Markdown 相对链接、约定目录、包版本入口，以及核心不直接导入旧模块或具体插件 SDK。

## 安装检查

在隔离的临时虚拟环境中执行：

```bash
uv build
uv run taskweave --version
uv run taskweave --help
```

安装检查验证 Python 包配置与命令入口，不代表任务执行功能可用。

## 功能阶段

在 `tests/` 编写核心执行、插件契约及存储测试，使用临时目录和无副作用的动作。真实浏览器、Excel、数据库检查放在插件各自测试中；集成测试使用专用本地环境。

## REQ-002 契约检查

`python scripts/check_req002.py` 在模拟上下文和临时 SQLite 验证设计示例，不访问真实网站、模型或旧数据。

## REQ-003 实际功能检查

`uv run python -m unittest discover -s tests -v` 运行临时 SQLite、spawn worker、AI 模型 fixture 与 HTTP 接口集成测试。详见 [验证记录](requirements/REQ-003-task-core/validation.md)。

## REQ-004 浏览器检查

`uv run --extra browser --extra sample python -m unittest discover -s tests -v` 包含真实 Chromium 测试，开发机提前下载匹配浏览器。纯核心环境会明确跳过浏览器集成测试；不把跳过算通过。详情见 [验证记录](requirements/REQ-004-plugin-contract/validation.md)。

## REQ-005 桌面工作台

`uv run --extra gui --extra browser --extra sample python -m unittest discover -s tests -v` 包含真实 NiceGUI 服务、浏览器和本机模型 fixture；桌面与业务浏览器分开验证。平台限制见 [验收记录](requirements/REQ-005-local-workbench/validation.md)。
