# 插件契约与能力包

宿主统一注册、启停和调用，插件提供动作、资源、上下文、AI 编写贡献和结果展示声明。一个步骤可以组合多个已声明能力。

## 当前行为与约束

- 插件 API v1，通过 `taskweave.plugins` entry point 发现；实际字段、schema 与接口以 SDK/registry 为准。
- 每个插件独立声明依赖，核心默认环境不强制安装浏览器、OCR 或数据库驱动。
- 动作输入/输出必须校验，步骤只能调用声明能力；插件会话对象不能作为 JSON 结果或模型输入传出。
- 资源生命周期由统一执行/会话流程管理；打开上下文目标选择器不新建资源，不跨规划/运行接管实例。
- AuthoringContribution 支持 api/web_chat 渠道覆盖，插件补充公共规范而不扩大权限；固定步骤不要求配置模型。
- ContextCollection 分离 AI items 与用户 views；可选目标钩子与 schema 扩展决定选择 UI，核心不按具体插件分支。
- 结果使用 `ctx.result(data=..., outputs=..., views=...)`，outputs 请求必须纳入结果才能保存；renderer 是声明式扩展，不直接访问 UI。实际保存和索引由宿主负责。
- 插件页根据安装注册表和当前加载的能力动态展示；动作/工具说明包含输入输出 schema、读写效果、超时、可重试标记、资源依赖及插件贡献示例。未加载的能力明确显示缺失，不以静态原型数据代替。

## 代码和使用入口

[SDK](../../src/taskweave/plugins/sdk.py)、[registry](../../src/taskweave/plugins/registry.py)、[manager](../../src/taskweave/plugins/manager.py)；插件包位于仓库根 plugins/。

| 插件 | 能力与本地说明 | 测试键 |
| --- | --- | --- |
| Playwright | [页面动作、观察和浏览器资源](../../plugins/playwright/README.md) | plugins.playwright |
| OCR | [本地图片文字识别](../../plugins/ocr/README.md) | plugins.ocr |
| TiDB | [连接、schema 采集、只读查询与展示](../../plugins/tidb/README.md) | plugins.tidb |
| utility | [时间、UUID、精确十进制计算](../../plugins/utility/README.md) | plugins.utility |

## 验证入口

修改插件只选择对应键；SDK/注册变化使用 `shared.contracts` 和 changed dry-run 核对消费者。真实 Playwright 测试需显式 `--include-browser`；插件 fixture 测试不代表真实业务系统验收。新增扩展要保护无该可选钩子的旧插件行为。关联：[上下文](contexts.md)、[AI 编写](authoring.md)、[执行结果](execution.md)。

## 按需深入

[插件开发](../reference/plugin-development.md)。只在本次修改涉及相应契约时阅读。
