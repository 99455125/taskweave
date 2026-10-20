# 测试指南

## 选择范围

测试目标与产品源码的映射唯一维护在[tests/module-map.json](../tests/module-map.json)，模块责任见[模块导航](maintenance.md)。按功能命名的unittest是运行入口，不依赖需求编号或旧验收文档。

```bash
uv run python scripts/test_modules.py --list
uv run python scripts/test_modules.py --changed src/taskweave/desktop/pages/tasks.py --dry-run
uv run python scripts/test_modules.py --module ui.tasks
```

changed沿consumer→prerequisite反向闭包选择受影响消费者，并展示原因、去重目标及可选浏览器入口。未知/未映射产品源码报错；新增/移动源码须更新source_globs和实际测试目标，再检查映射。直接选择一个ui模块不等于全工程回归。

可运行精确测试模块/方法，例如：

```bash
uv run python -m unittest tests.presentation.test_task_import -v
```

全量测试只有明确授权后运行，不能分组拼接为全量。闭包很大时先审阅dry-run，再选择与本次变化匹配的必要场景。

## 检查类型

| 检查 | 能证明什么 | 不能替代什么 |
| --- | --- | --- |
| 工程检查 | 布局、源码语法、依赖边界、文档链接、CLI版本 | 功能回归 |
| 普通交互及禁GUI进程 | 状态/动作可脱离GUI运行 | NiceGUI实际接线 |
| 实际组件事件测试 | 输入同步、控件装配和生命周期绑定 | 真实浏览器时序 |
| 本地浏览器/worker集成 | 真实进程、浏览器和关键用户流程 | 原生窗口、远端系统和其他平台 |
| 打包收集测试 | 入口、资源定位、发现及冻结分流规则 | 完整发布构建和目标实机 |

浏览器目标默认不选，确需时显式--include-browser，或运行指定浏览器测试。使用临时工作空间和本地fixture，不操作真实业务数据或模型账号来代替常规测试。

## 文档和工程

```bash
uv run python scripts/check_project.py
git diff --check
```

纯文档变更不运行功能回归。检查器还校验core/application/presentation/runtime/controller依赖和对话框ESC策略；相关守卫不只是文件命名检查。

## 环境与结果解释

若执行环境注入的PYTHONPATH包含沙箱shim，worker启动可能明显变慢；确认该原因后，可用`env -u PYTHONPATH uv run python -m unittest <明确目标>`运行。不要把真实超时一律归因于环境。

记录本次命令、结果、失败与未覆盖范围。旧通过记录不能证明当前版本，替身不能证明真实服务，未运行不称通过。恢复、UNKNOWN、补参续启及持久化变动需选择能观察状态/副作用的行为测试。

任务组合变化可运行`tests.test_task_sequences_storage`、`tests.test_task_sequences`、`tests.test_task_sequences_lifecycle`和`tests.ui.test_sequences_page`。迁移或仓储变更另运行`tests.test_control_db_migration`，页面入口变化选`tests.ui.test_navigation`；独立浏览器三任务流程选`tests.test_sequences_browser`。
