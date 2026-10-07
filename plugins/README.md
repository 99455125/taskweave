# 功能插件

独立源码包通过 `taskweave.plugins` 入口注册，由插件管理启停。插件提供动作 schema、版本、AI 编写贡献、结果处理和会话资源，具体依赖保留在插件包中。

- [Playwright](playwright/README.md)：页面操作、观察、验证和图像采集。
- [本地验证码](ocr/README.md)：图片文字验证码本地 CPU 识别，与图片产生插件组合使用。
- [TiDB](tidb/README.md)：连接、schema 采集与只读查询。
- [基础数据工具](utility/README.md)：当前时间、UUID 和精确十进制计算。

- [process](process/README.md)：有界本地命令与声明式文件产物。
- [SSH/SFTP](ssh/README.md)：可信主机、受限远程根与传输。
- [宝塔](baota_dashboard/README.md)：33 个面板独立动作。
- [WordPress](wordpress/README.md)：53 个 WP-CLI 独立动作，local/ssh。
- [uni-app](uniapp/README.md)：五个项目/构建/测试/报告动作。
- [微信开发工具](wechat_dev/README.md)：26 个模拟器动作＋预览/上传，共28个动作。

组合步骤见 [devops 示例](../examples/devops/README.md)。六个可选包 API v1/0.1.0，总135个命名动作；源码/注册、协议检查、真实工具与外部业务验收分别记录，不将未验收的平台或公网材料写成已通过。

一个任务可以组合多个插件或手写步骤。插件不要求 AI，固定步骤执行不调用模型。接口、开发边界和源码入口见 [插件模块](../docs/modules/plugins.md)。

插件快速回归和真实浏览器 targets 由 `tests/module-map.json` 分别登记；`plugins.playwright` 的 Chromium 测试需使用 `uv run python scripts/test_modules.py --module plugins.playwright --include-browser` 显式运行。插件契约替代对象测试留在快速目标中。
