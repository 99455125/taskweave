# 功能插件

独立源码包通过 `taskweave.plugins` 入口注册，由插件管理启停。插件提供动作 schema、版本、AI 编写贡献、结果处理和会话资源，具体依赖保留在插件包中。

- [Playwright](playwright/README.md)：页面操作、观察、验证和图像采集。
- [本地验证码](captcha/README.md)：图片文字验证码本地 CPU 识别，与图片产生插件组合使用。
- [自定义示例](custom/README.md)：展示第三方插件契约。

一个任务可以组合多个插件或手写步骤。插件不要求 AI，固定步骤执行不调用模型。接口与开发见 [REQ-004](../docs/requirements/REQ-004-plugin-contract/README.md)。
