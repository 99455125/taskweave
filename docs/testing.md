# 验证

当前阶段不执行旧服务测试，因为旧服务会访问本地数据库并依赖旧环境。

## 结构检查（无第三方依赖）

```bash
python scripts/check_project.py
```

检查新源码语法、Markdown 相对链接、约定目录、包版本入口，以及核心不直接导入旧模块或具体插件 SDK。

## 安装检查

在隔离的临时虚拟环境中执行：

```bash
python -m pip install --no-deps .
taskweave --version
taskweave --help
```

安装检查验证 Python 包配置与命令入口，不代表任务执行功能可用。

## 功能阶段

在 `tests/` 编写核心执行、插件契约及存储测试，使用临时目录和无副作用的动作。真实浏览器、Excel、数据库检查放在插件各自测试中；集成测试使用专用本地环境。
