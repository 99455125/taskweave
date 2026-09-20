# TaskWeave Playwright 插件

独立 Python distribution：taskweave-playwright。SDK 依赖仅在这个插件包，核心默认不包含浏览器。

[运行、动作、AI 扩展与开发指南](../../docs/requirements/REQ-004-plugin-contract/usage.md)。

开发机同步：`uv sync --extra browser`。下载匹配 Chromium 仅在开发/构建机进行；受限虚拟机运行随包浏览器。

任务参数与环境变量支持 playwright_headless、playwright_timeout_ms、playwright_role、playwright_executable_path、playwright_locale。locale 默认 `zh-CN`，在创建 BrowserContext 时应用，不通过页面操作切换通用语言。任务参数优先；声明与说明在 manifest.config_variables 中，UI 统一展示。

插件 manifest 可选 resource_descriptions 提供资源 ID 对应的人类可读说明，供结束执行确认框展示；缺省显示资源 ID，不改变关闭接口或 v1 契约。Playwright 声明浏览器、页面及浏览器上下文。

## 0.2.0 页面观察、验证与 AI 修复

- CSS 字符串定位器继续兼容；selector 可为 `{kind: css|role|label|placeholder, value: ..., name?: ..., exact?: true, frame?: iframe CSS}`。所有读取、填充、点击和断言共用解析器。
- 页面快照过滤隐藏控件，密码框仅描述定位信息、不读取值，优先表单与按钮，提供可见/启用/可编辑状态、标签、placeholder、推荐定位器、实际匹配数量、frame、采集时间与当前会话标识。最多 8 个 frame、80 个元素、每 frame 最多 40 个；不读取输入值、cookie 或完整 HTML。无法可靠定位的嵌套 frame 不生成可执行定位器。
- 新动作 page_input_value / page_assert_value 读取或等待实际控件值；page_assert_title 等待标题包含文字；page_assert_url 等待 Playwright URL glob；page_assert_text 改为等待实际页面文字。文本能力仍不代表输入值。
- 操作前识别 LOCATOR_NOT_FOUND / LOCATOR_AMBIGUOUS / LOCATOR_HIDDEN / LOCATOR_DISABLED / LOCATOR_NOT_EDITABLE，填充不接受不可编辑控件。开始/完成/失败日志标明动作序号、定位器、阶段及耗时，不记录填入的值。
- 失败时尽力采集只读 BrowserFailureSnapshot 与截图，采集失败不覆盖原错误。AI 修复前自动刷新仍保留会话中的页面；丢失会话时明确 unavailable，不打开新页面。
- 插件提示词要求按最新真实快照定位、继续当前页面、区分输入值与文字、验证实际结果，禁止固定 True 伪造成功。运行时 page_inspect 观察现有页面，编写工具 page_inspect 观察明确 URL 的独立页面，两者分别说明。
- package_version 升为 0.2.0，插件 API v1 保持；无数据库迁移。旧步骤 CSS 能力继续工作。新增动作须重新保存插件选择后授权，旧执行仍保留原插件版本快照，不隐式更改旧历史或续跑旧版本。

## 0.3.0 本地图像插件协作

新增通用 `playwright.page_element_image`：唯一可见元素 PNG Base64（上限 1MB），支持原有 CSS/结构化/frame 定位器。当前上下文包含可见 img/canvas、尺寸和定位器，密码框保留标签及定位信息而不读值。选择 captcha 插件后，将验证码图片传给其本地识别动作，填入候选文字并检查真实登录结果。浏览器插件无 OCR 依赖；API 与网页渠道的协作说明均由插件贡献。API v1 与存储不变，旧步骤可继续使用，旧运行仍校验插件版本。
