# REQ-003 实际代码映射

| 代码 | 职责 |
|---|---|
| src/taskweave/core/ports.py | 执行、模型和插件共享契约 |
| src/taskweave/core/validation.py | 内容、schema、绑定、指纹规则 |
| src/taskweave/application/service.py | 统一应用接口 |
| src/taskweave/application/authoring.py | AI 建议、工具、上下文与诊断 |
| src/taskweave/infrastructure/repository.py | 配置、试跑证据、运行及结果查询 |
| src/taskweave/infrastructure/storage.py | SQLite 迁移及宿主结果存储 |
| src/taskweave/infrastructure/runtime.py | 命令去重、运行协调和恢复 |
| src/taskweave/infrastructure/worker.py | spawn worker、动作调用、资源生命周期 |
| src/taskweave/infrastructure/model.py | 可选 HTTP 模型适配器 |
| src/taskweave/infrastructure/http.py | 本地 HTTP API |
| src/taskweave/plugins/registry.py、demo.py | 显式注册与最小测试插件 |
| src/taskweave/__main__.py | CLI |
| tests/test_step_outputs.py、tests/test_execution_control.py、tests/test_step_authoring.py、tests/test_storage_integrity.py、tests/test_ai_authoring.py、tests/test_http_task_api.py | 按功能拆分的 worker、SQLite、AI 与 HTTP 集成测试 |
| examples/req003/api_walkthrough.py | HTTP 全流程示例 |

[操作说明](usage.md)。

定向模块选择与 step/共享契约依赖映射维护在 `tests/module-map.json`；使用 `uv run python scripts/test_modules.py --changed <源码路径> --dry-run` 查看受影响目标。
