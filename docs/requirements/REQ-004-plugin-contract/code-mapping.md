# REQ-004 实际代码映射

| 文件 | 职责 |
|---|---|
| src/taskweave/plugins/sdk.py | 公开插件 API |
| src/taskweave/plugins/manager.py | entry point 发现、启用配置和加载错误隔离 |
| src/taskweave/plugins/registry.py | manifest、版本、依赖、schema 和编写约束校验 |
| src/taskweave/application/service.py | CLI/API 共用插件配置和当前页面观察入口 |
| src/taskweave/application/authoring.py | 插件编写贡献、工具、上下文、诊断组合 |
| src/taskweave/infrastructure/worker.py | 通用资源与可选失败产物钩子 |
| src/taskweave/infrastructure/runtime.py | 暂停 worker 观察及诊断结果登记 |
| src/taskweave/infrastructure/storage.py | 自定义表迁移、备份、统一保存与结果引用 |
| plugins/playwright/src/taskweave_playwright/__init__.py | 浏览器动作、角色、观察工具、lint、诊断和文件处理器 |
| plugins/custom/src/taskweave_sample/__init__.py | 独立最小插件、AI 贡献、自定义表及解析 |
| examples/req004/browser_demo.py、mock_site.py | 本机业务网页与实际应用流程 |
| tests/test_req004.py | 插件契约、迁移、真实 Chromium 验证 |

[运行及开发说明](usage.md)。

`plugins/ocr/`：独立本地文字识别插件（无浏览器依赖）；Playwright `page_element_image`：通用元素 PNG Base64 采集，用于跨插件图像传递。`tests/test_ocr.py`：非法输入、无网络本地推理、实际浏览器采集→识别→填写→登录状态断言。
