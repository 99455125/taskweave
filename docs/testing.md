# 验证

从 [维护索引](maintenance.md) 选择受影响模块。测试按功能模块组织。修改哪个功能，就运行对应的 `tests.test_<功能>`；不要把历史 REQ 编号当作日常回归入口。全量测试包含真实浏览器等耗时检查，只有用户明确同意后才运行。

## 文档调整

仅修改 Markdown 时运行 `uv run python scripts/check_project.py` 与 `git diff --check`，检查结构、引用和空白；不执行功能回归，不把结构检查当成功能验收。

## 日常检查

```bash
uv run python scripts/check_project.py
uv run python -m unittest tests.test_utility -v
```

第二条只是示例，应替换成当前改动涉及的模块。涉及多个模块时，在同一命令中列出模块名即可。先用 `rg --files tests` 查找现有测试；新增测试也以功能命名。

## 模块选择器

`tests/module-map.json` 将产品源码映射到明确的快速 unittest targets、反向依赖和可选浏览器 targets。列出模块并运行单个模块：

```bash
uv run python scripts/test_modules.py --list
uv run python scripts/test_modules.py --module ui.tasks
```

按源码改动选择并先检查计划：

```bash
uv run python scripts/test_modules.py --changed src/taskweave/desktop/pages/tasks.py --dry-run
uv run python scripts/test_modules.py --changed src/taskweave/core/repositories.py --dry-run
```

共享模块变化会沿 `depends_on` 的反向传递闭包选择 consumer；直接选择 `ui.tasks` 不会选中无关的 `ui.settings`。dry-run 只显示模块、原因和去重后的目标，不启动测试。真实浏览器目标默认排除，只有显式加入 `--include-browser` 才会执行。未知或未映射的 `src/taskweave/`、`plugins/` 路径以及没有可选模块的请求都会以非零退出并提示修正映射。该工具只运行清单里的目标，不调用全量 discover。

新增或移动产品 Python 文件时，先把文件加入 `tests/module-map.json` 的 `source_globs` 并登记对应测试，再运行 `tests.test_module_selection` 检查源码覆盖。映射中的 SQL 包资源也归 `shared.storage`，由存储完整性/迁移测试验证。

## 模块入口

| 功能 | 测试模块 | 运行条件 |
| --- | --- | --- |
| 步骤输出与依赖 | `tests.test_step_outputs` | 临时工作空间 |
| 执行控制与重试 | `tests.test_execution_control` | 临时工作空间；部分用例耗时 |
| 步骤编写与确认 | `tests.test_step_authoring` | 临时工作空间 |
| 存储与迁移 | `tests.test_storage_integrity` | 临时工作空间 |
| AI 编写与插件上下文 | `tests.test_ai_authoring`、`tests.test_context_captures`、`tests.test_context_sessions`、`tests.test_context_cards`、`tests.test_context_metadata`、`tests.test_planning`、`tests.test_workbench_changes` | 本地模型 fixture；弹窗暂存、组级事务提交及按需预览 |
| HTTP 任务接口 | `tests.test_http_task_api` | 本地回环 HTTP |
| 插件契约 | `tests.test_plugin_contract` | 无真实浏览器 |
| Playwright 浏览器集成 | `tests.test_playwright_browser_integration` | browser extra 和本机 Chromium；耗时 |
| 间隔调度 | `tests.test_interval_scheduler` | 临时工作空间；部分用例耗时 |
| 任务复制 | `tests.test_task_copy_lifecycle` | 临时工作空间 |
| 步骤保存 | `tests.test_desktop_step_save` | 临时工作空间 |
| 控制库迁移 | `tests.test_control_db_migration` | 临时工作空间 |
| 模型密钥配置 | `tests.test_model_secret_settings` | 临时工作空间 |
| 执行器恢复 | `tests.test_executor_recovery` | 临时工作空间 |
| 桌面端口 | `tests.test_desktop_port` | 本机回环端口 |
| 工作台浏览器流程 | `tests.test_workbench_browser` | GUI、browser extra；耗时 |

其他功能（规划、变量、展示、TiDB、OCR 等）各有 `tests/test_<功能>.py`。需要更小范围时可运行单个测试类或方法，例如 `uv run python -m unittest tests.test_plugin_contract.ContractTests -v`。

REQ 文档中的验收记录保留为历史资料，后续需求完成后不再增加 `test_req*.py` 常驻入口。回归用例保留并迁入功能测试模块；过时或重复的测试经核对后删除。

## 安装检查

需要验证打包或命令入口时，按受影响平台执行 `uv build`、`uv run taskweave --version` 等检查。这些检查不替代功能测试。

## 映射维护与发布证据

依赖边按实际构造和调用维护，consumer → prerequisite；共享代码可能有多个真实消费者。覆盖到实际unittest ID并去重，不只检查文件glob或target字符串。fast/browser按是否实际启动浏览器区分，不按文件名猜测。设计理由见 [架构决策](decisions/architecture.md)。发布阶段按 [集成验收](release-checklist.md) 选择场景，不能把历史记录或本次文档检查当作功能通过。
