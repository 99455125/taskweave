# 维护索引

从本次改动所在行开始，只读该模块和相关源码。模块文档是当前知识入口，旧需求目录是可选的历史追溯，不是前置阅读任务。

下表测试键用于定位；实际改动跨边界时，用 `--changed <源码路径> --dry-run` 核对依赖闭包。精确映射唯一维护在 [module-map.json](../tests/module-map.json)，不要再手工维护另一份完整测试清单。

| 本次要改什么 | 先读 | 主要源码入口（src/taskweave 下） | 测试键示例 |
| --- | --- | --- | --- |
| 任务 CRUD、复制、任务包、步骤保存与确认 | [任务与步骤](modules/tasks.md) | application/tasks.py、steps.py、task_transfer.py；repositories/tasks.py、steps.py | application.tasks、application.steps、ui.tasks、ui.editor |
| 规划配置、生成、导入、复制 | [规划](modules/planning.md) | application/planning.py；desktop/planning.py；repositories/plans.py、plan_generations.py | application.planning、ui.planning |
| 步骤 AI 生成、网页回复、失败修复 | [AI 编写](modules/authoring.md) | application/authoring.py、prompts.py、ai_requests.py；components/step_ai.py | application.authoring、ui.debug |
| 上下文组、采集项、会话目标与预览 | [上下文](modules/contexts.md) | application/contexts.py；infrastructure/context_sessions.py；desktop/contexts.py | domain.contexts、repository.contexts、ui.contexts |
| 执行、调试、补录、重跑、恢复、结果 | [执行与结果](modules/execution.md) | application/runs.py；infrastructure/runtime.py、worker.py | application.runs、ui.executions、ui.results、ui.debug |
| 环境变量、SQLite、事务、清理与迁移 | [存储与环境](modules/storage.md) | application/environments.py；infrastructure/storage.py、unit_of_work.py、repositories/ | application.environments、shared.storage、repository.environments |
| 页面布局、导航、组件状态、设置与历史 | [桌面 UI](modules/desktop.md) | desktop/workbench.py、pages/、components/、state.py | ui.tasks、ui.editor、ui.settings、ui.history（按实际选择） |
| 插件契约、Playwright/OCR/TiDB/utility | [插件](modules/plugins.md) | plugins/sdk.py、registry.py；仓库根 plugins/ 下对应插件 | shared.contracts、plugins.playwright、plugins.ocr、plugins.tidb、plugins.utility |
| CLI/HTTP 操作路由或整体依赖边界 | [架构](architecture.md)及受影响模块 | __main__.py；application/operations.py、service.py；infrastructure/http.py | 用 --changed 预览实际消费者 |
| 打包、安装或启动 | [交付与运行](deployment.md) | pyproject.toml；packaging/windows/；scripts/build_windows.ps1 | 按受影响平台验证，见 testing.md |
| 测试选择器或模块映射 | [测试规则](testing.md) | scripts/test_modules.py；tests/module-map.json | shared.testing |
| 文档、协作规则 | [协作方法](ai-operating-model.md) | AGENTS.md、本索引及受影响模块文档 | 仅工程与链接检查 |

表中 `repositories/` 是 `infrastructure/repositories/`，`components/` 是 `desktop/components/`。

## 一次修改的最短路径

1. 检查 Git 现场，确认本次目标、范围和可观察验收结果。
2. 本索引 → 受影响模块 → 相关代码/测试；存在当前需求时读取它，不沿 REQ 编号串读历史。
3. 按风险决定是否需要设计，完成修改及相关验证。
4. 模块行为发生变化才更新该模块文档；本次需求记录写实际结果，关闭后不再作为后续维护前置；没有需求目录时记录在当前任务/PR。
5. 存在新工作、阻塞或已知问题变化时更新 [当前状态](status.md)，不在各 README 重复状态。

只改任务列表布局时：读 desktop.md 中组件边界及 TasksPage 源码，预览该文件对应测试；不需要阅读规划、插件历史或 REQ-003/005/010。

## 深入阅读

字段/协议细节从 [契约专题](reference/README.md) 按问题读取；边界理由见 [架构决策](decisions/architecture.md)。规划新能力才看 [后续范围](roadmap.md)，发布才看 [集成验收](release-checklist.md)。历史知识迁移已逐文件登记在 [迁移台账](archive/req-knowledge-migration.md)，它不是日常前置阅读。
