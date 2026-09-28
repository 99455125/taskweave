# 功能插件

独立源码包通过 `taskweave.plugins` 入口注册，由插件管理启停。插件提供动作 schema、版本、AI 编写贡献、结果处理和会话资源，具体依赖保留在插件包中。

- [Playwright](playwright/README.md)：页面操作、观察、验证和图像采集。
- [本地验证码](ocr/README.md)：图片文字验证码本地 CPU 识别，与图片产生插件组合使用。
- [TiDB](tidb/README.md)：连接、schema 采集与只读查询。
- [基础数据工具](utility/README.md)：当前时间、UUID 和精确十进制计算。

一个任务可以组合多个插件或手写步骤。插件不要求 AI，固定步骤执行不调用模型。接口、开发边界和源码入口见 [插件模块](../docs/modules/plugins.md)。

插件快速回归和真实浏览器 targets 由 `tests/module-map.json` 分别登记；`plugins.playwright` 的 Chromium 测试需使用 `uv run python scripts/test_modules.py --module plugins.playwright --include-browser` 显式运行。插件契约替代对象测试留在快速目标中。
