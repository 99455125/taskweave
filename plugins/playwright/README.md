# TaskWeave Playwright 插件

独立 Python distribution：taskweave-playwright。SDK 依赖仅在这个插件包，核心默认不包含浏览器。

开发边界、SDK 与验证入口见 [插件模块](../../docs/modules/plugins.md)，启动方式见 [运行与交付](../../docs/deployment.md)。动作与参数以本插件能力声明和 schema 为准。

开发机同步：`uv sync --extra browser`。下载匹配 Chromium 仅在开发/构建机进行；受限虚拟机运行随包浏览器。

任务参数与环境变量支持 playwright_headless、playwright_timeout_ms、playwright_role、playwright_executable_path、playwright_locale。locale 默认 `zh-CN`，在创建 BrowserContext 时应用，不通过页面操作切换通用语言。任务参数优先；声明与说明在 manifest.config_variables 中，UI 统一展示。

插件 manifest 可选 resource_descriptions 提供资源 ID 对应的人类可读说明，供结束执行确认框展示；缺省显示资源 ID，不改变关闭接口或 v1 契约。Playwright 声明浏览器、页面及浏览器上下文。

上下文采集支持选择同一实例中所有角色的现存页面，包括新标签页和弹窗。插件提供会话内稳定的 `target_id`、角色/标题/脱敏地址标签，以及 `{role, target_id, url: ""}` 采集参数；列表不会启动浏览器。插件 schema 声明唯一页面自动选中、多个页面明确选择，以及参数模式“新建页面”。新建页面要求 URL，并创建页面而不导航已有页面。选择已有目标只观察该页，不导航，也不改变后续动作使用的角色默认页面。目标关闭后需刷新重新选择，不自动回退；直接 API 同时提供目标和非空 URL 会返回 `CONTEXT_TARGET_REQUEST_INVALID`。可选钩子兼容插件 API v1，无数据库变更。

采集范围可选当前视口或完整页面。任务步骤页默认完整页面，规划页默认当前视口，由插件的 `x-taskweave-context-surface-defaults` 声明；直接调用采集接口且未传 `scope` 时默认完整页面。需要预览时同时保存当前页面 PNG，并以 `playwright.screenshot` 交给宿主渲染；截图不混入发送给 AI 的结构证据。关闭预览只跳过截图，不改变页面结构采集。

选择已有页面后仍可在采集弹窗修改 `scope`；URL 和角色仅在“新建页面”模式中录入。该可见性由插件 schema 的 `keep_parameters_when_selected` 声明。

下拉和日期控件应先展开，再采集对应页面状态。采集器会记录当前可见的自定义选项、日期网格项，以及原生 `<select>` 的选项标签和值；当前视口最多记录 300 个元素。步骤可用 `page_press` 在唯一控件上按 Enter 等键，或用 `page_select_option` 按已观察到的标签/值选择原生下拉项；自定义选项使用采集到的唯一定位器点击。选择后仍需读取或断言实际结果。

## 0.2.0 页面观察、验证与 AI 修复

- CSS 字符串定位器继续兼容；selector 可为 `{kind: css|role|label|placeholder, value: ..., name?: ..., exact?: true, frame?: iframe CSS}`。所有读取、填充、点击和断言共用解析器。
- 页面快照过滤隐藏控件，密码框仅描述定位信息、不读取值，优先表单与按钮，提供可见/启用/可编辑状态、标签、placeholder、推荐定位器、实际匹配数量、frame、采集时间与当前会话标识。最多 8 个 frame、80 个元素、每 frame 最多 40 个；不读取输入值、cookie 或完整 HTML。无法可靠定位的嵌套 frame 不生成可执行定位器。
- 新动作 page_input_value / page_assert_value 读取或等待实际控件值；page_assert_title 等待标题包含文字；page_assert_url 等待 Playwright URL glob；page_assert_text 改为等待实际页面文字。文本能力仍不代表输入值。
- 操作前识别 LOCATOR_NOT_FOUND / LOCATOR_AMBIGUOUS / LOCATOR_HIDDEN / LOCATOR_DISABLED / LOCATOR_NOT_EDITABLE，填充不接受不可编辑控件。开始/完成/失败日志标明动作序号、定位器、阶段及耗时，不记录填入的值。
- 失败时尽力采集只读 BrowserFailureSnapshot 与截图，采集失败不覆盖原错误。AI 修复前自动刷新仍保留会话中的页面；丢失会话时明确 unavailable，不打开新页面。
- 插件提示词要求按最新真实快照定位、继续当前页面、区分输入值与文字、验证实际结果，禁止固定 True 伪造成功。运行时 page_inspect 观察现有页面，编写工具 page_inspect 观察明确 URL 的独立页面，两者分别说明。
- package_version 升为 0.2.0，插件 API v1 保持；无数据库迁移。旧步骤 CSS 能力继续工作。新增动作须重新保存插件选择后授权，旧执行仍保留原插件版本快照，不隐式更改旧历史或续跑旧版本。

## 0.3.0 本地图像插件协作

新增通用 `playwright.page_element_image`：唯一可见元素 PNG Base64（上限 1MB），支持原有 CSS/结构化/frame 定位器。当前上下文包含可见 img/canvas、尺寸和定位器，密码框保留标签及定位信息而不读值。选择 OCR 插件后，将验证码图片传给其本地识别动作，填入候选文字并检查真实登录结果。浏览器插件无 OCR 依赖；API 与网页渠道的协作说明均由插件贡献。API v1 与存储不变，旧步骤可继续使用，旧运行仍校验插件版本。

## 0.4.0 共用定位范围与有界 DOM

本节描述当前实现；统一交互、读取、文件、弹窗和人工录制的范围见下文。上述 0.2/0.3 节是历史版本：0.4 保留默认快照不读输入值的约束，显式局部 DOM 可读脱敏后的值、可定位嵌套 frame，以下行为为准。插件 API v1、旧定位器格式和上下文/任务包存储保持兼容；旧运行仍按其插件版本快照校验，不隐式改写历史或绕过版本保护。

所有动作接受 role、target_id、timeout_ms（1–20000）。未传 target_id 使用原角色主页面；`page_targets` 返回同角色的当前页面 `{target_id,title,url,primary}`，最多32页，超限有 truncated。目标 ID 只在其所属会话有效；关闭/重建后的旧 ID 报 BROWSER_TARGET_STALE，不选择别页或改变主页面。动作/编写工具/上下文会话不能跨会话复用 ID。动作超时设置不改变页面的全局默认超时。

共用 selector 支持原 CSS 字符串及结构化 css/role/label/placeholder；新增 within（CSS字符串或嵌套定位器）、nth（零基、0–9999）、frame（iframe CSS 或由外至内的 CSS 数组，最多8层）。within 嵌套最多8层；nth 必须有页面顺序证据，优先字段组范围，不猜第一个。操作日志保留应用 nth 前的 base_match_count。

```python
selector = {"kind": "label", "value": "否", "within": "#otherTreatyInfo #openPolicy"}
await ctx.call("playwright.page_check", {"selector": selector, "checked": True})
await ctx.call("playwright.page_assert_checked", {"selector": selector, "checked": True})
```

快照仍有 title/url/elements/frames/truncated，新增每项 attributes、checked/mixed、field_group、ancestor_chain；默认整页快照仍不读取输入值。显式 selector 范围的局部 DOM 另外提供非敏感 value（最多2048字符，截断标记），以及经实际执行解析器验证的 candidate_selectors/preferred_selector。语义定位无匹配或多匹配时使用实际唯一的 CSS 备选；均不唯一时不提供可执行推荐。CSS 路径反映本次 DOM，不能保证跳转/重绘后仍稳定。密码、token、secret、凭证、OTP 等识别为敏感的输入值为 `[redacted]`，不采 cookie、任意 data-* 或原始 HTML；这是显式启发式脱敏，不是所有业务敏感字段自动识别的保证。字段组来源于 fieldset/legend 或 ARIA group/radiogroup，不凭元素序号推定字段名。

页面快照最多8个frame，runtime总体80元素、viewport总体300、full_page总体2000，明确 truncated。包括当前可见浮层、原生 select 选项和日期网格；不会主动打开弹窗或加载虚拟化屏外内容。嵌套 iframe 的路径逐层验证；无法建立范围时不推荐定位器。开放 shadow DOM 可由局部 DOM 根范围读取；整页枚举目前仍按普通 DOM 元素查询，不声称覆盖全部 shadow 内容，closed shadow 不可观察。

| 新增/扩展方法 | 参数与结果 |
| --- | --- |
| page_targets | 返回当前会话 live target 列表，READ |
| page_check | selector、checked布尔必填；设置原生或语义checkbox/radio，WRITE；原生radio取消需选择其他选项 |
| page_checked | selector必填；返回 checked布尔/null 与 mixed，READ |
| page_assert_checked | selector、checked必填；等待确切选中状态，mixed不作为true，READ |
| page_inspect | 新增scope(runtime/viewport/full_page)、selector、include_ancestors、include_descendants、depth(0–6)、max_nodes(1–300)、interactive_only；默认仍为总体交互快照 |

指定 selector 或 include_descendants=true 时，page_inspect 额外返回 dom：根节点、children层级、祖先、node_count、truncated；默认局部depth3/max_nodes100，字段候选定位器仍实际校验，并保持所在frame身份。interactive_only 保留结构容器，减少其描述文本，不把父子关系扁平化。局部根须唯一，可观察隐藏节点；不要求每个节点都可点击。编写工具同名接口接受 url 必填及相同观察参数，在其隔离页面先导航再观察。

针对性真实 Chromium 验证覆盖同名“否”与字段范围、显式nth、多/无命中、radio/ARIA checkbox、mixed状态、嵌套iframe、目标关闭、“今天”零语义匹配时的CSS备选、局部层级与截断、敏感输入、编写工具导航顺序。还保留旧动作、上下文目标及图像定位回归；这些不是任意真实业务页面都可自动执行的证明。

### 通用交互、读取与状态断言

以下是当前0.4.0实现，继续共用 role/target_id/within/nth/frame/timeout，不改变 SDK v1 和任务包。上传和原生 dialog 的当前范围见下一节；本轮验证证据和未验证平台范围见[实施记录](../../docs/design/next-repair-implementation-2026-09-30.md)。

| 方法 | 参数与结果 |
| --- | --- |
| page_hover / page_double_click | selector必填；悬停/双击唯一可见启用目标，WRITE、不可自动重试 |
| page_scroll | selector必填；默认滚入视口；可选delta_x/delta_y整数（-10000至10000）在该容器相对滚动，body/html使用该文档滚动根；WRITE、不可自动重试 |
| page_drag | selector源、destination目标必填；均唯一可见启用、同frame，跨frame报DRAG_FRAME_MISMATCH；WRITE、不可自动重试 |
| page_state | selector必填；返回match_count、visible/enabled/editable；0或多个匹配时后三项为null，READ |
| page_assert_state | selector与expected对象必填；expected含count/visible/enabled/editable至少一项；等待实际状态，失败BUSINESS_ASSERTION_FAILED，READ |
| page_attribute | selector与name必填；允许id/class/role/name/type/title/placeholder/alt/tabindex/disabled/checked/selected/readonly/required/colspan/rowspan及aria-*；返回value字符串/null与truncated，READ |
| page_list | selector必填；max_items(1–100，默认100)、max_text(1–2048，默认1024)、include_hidden(默认false)；返回items(index/text/truncated)、total_count、truncated，READ |
| page_table | 唯一native table或ARIA table/grid/treegrid的selector必填；max_rows(1–100)、max_columns(1–30)、max_text(1–2048)、include_hidden；默认100/30/1024/false，返回rows、total_rows、truncated，READ |

状态读取是即时观察，不等待列表加载。状态断言的visible/enabled/editable须对应唯一已挂载元素：hidden与absent不同；缺失用count=0或原page_wait detached。editable断言仅支持表单/contenteditable控件；count与状态字段矛盾时报STATE_EXPECTATION_INVALID，多匹配状态时报LOCATOR_AMBIGUOUS。用现场状态等待，不用固定sleep。

属性字符串在浏览器中截断到8192字符再传回；不接受value、事件处理器和data-*，不借属性批量读取密码。列表/表格仅当前DOM可见文本，默认过滤隐藏项，include_hidden=true时读已加载隐藏文本；不读输入/textarea/select实际值，不复制脚本或HTML。表格保留单元格header/row_span/col_span，不展开跨行跨列、不混入嵌套表格。total_count/total_rows只计当前渲染及可见性范围，不是远端全表总数；虚拟化、翻页、尚未加载行仍需步骤明确滚动/翻页后重新观察。

每项/单元格长度、行列数量及序列化字节预算均在浏览器内限制（集合内容预算96KiB，含外层元数据整体不超过128KiB）；超限truncated，不传回巨大的完整DOM文字后再裁剪。表格/列表读取前只查匹配数量，避免复用点击的可见/可编辑预检触发布局。真实Chromium验证iframe范围、hover/double-click、drag、相对容器滚动、隐藏/禁用/只读/多匹配、延迟启用断言、ARIAgrid、嵌套表与大中文表格截断。方法基于[官方Locator接口](https://playwright.dev/python/docs/api/class-locator)，实际行为以本地浏览器验证为准。


### 文件上传与原生弹窗

`page_upload` 与 `page_dialog` 均为 WRITE、retry_safe=false；复用 role/target_id/within/nth/frame/timeout_ms，SDK v1、任务包与旧动作不变。

| 方法 | 参数与结果 |
| --- | --- |
| page_upload | selector、files必填；mode为input（默认）或chooser；每项含name、mime_type、content_base64；返回files(name/mime_type/size_bytes)、total_bytes |
| page_dialog | selector、dialogs必填；trigger为click（默认）/double_click/press，press须key；每项含type、message、response，可选prompt_text；返回handled(type/response)、completed=true |

上传只接受完整标准Base64与文件名，不接受host路径；最多10个文件，每个1MiB、合计8MiB，空数组明确清除。先校验整批再触发控件。input模式要求唯一启用的input[type=file]，可隐藏；chooser模式点击唯一可见控件，等待实际文件选择器，同次触发多个文件框报UPLOAD_CHOOSER_AMBIGUOUS，改用明确input定位。多文件要求multiple。返回不含文件正文；它证明浏览器文件已设置，不表示服务器已接收，后续仍按本步骤目标核对页面结果。文件插件Base64输出通过普通步骤绑定传入，两个插件不直接调用。

原生弹窗type为alert/confirm/prompt/beforeunload，response为accept/dismiss；最多8项按顺序精确匹配type和完整message，不符或额外弹窗dismiss并报DIALOG_EXPECTATION_MISMATCH。prompt_text仅用于接受prompt；key仅用于press，支持Enter/Tab/Escape/ArrowDown/ArrowUp/Space。beforeunload通常message为空，仍需真实证据和浏览器用户激活；不会为了弹窗自动补业务点击。

监听在动作触发前安装，超时/取消/成功均释放；处理中取消会dismiss仍打开的原生弹窗，避免页面继续阻塞。没有长期自动接受监听，不处理后来动作的弹窗，也不能撤销已发出的点击或已接受的业务确认。当前范围是所选page（含该页iframe）的浏览器JavaScript弹窗；新popup页面的弹窗需先枚举目标再明确操作。HTML模态框用普通DOM定位；操作系统文件/目录/打印窗口不作为本方法目标。

基于[官方文件输入接口](https://playwright.dev/python/docs/api/class-locator#locator-set-input-files)、[FileChooser](https://playwright.dev/python/docs/api/class-filechooser)和[Dialog规则](https://playwright.dev/python/docs/dialogs)。实际验证包含隐藏iframe文件框、动态chooser、多文件/清除/体积边界、超时/取消、confirm/prompt、有序/额外弹窗、键盘/双击及真实beforeunload跳转；真实worker链路还核对file.read输出绑定后页面文件内容一致。外层超时或取消时，仅保留已发出的单次协议调用直至其返回，并接收该调用的异常；调用尚未发出时的取消不触发命令，后续业务操作不继续。真实Chromium用例覆盖被遮挡的chooser超时、弹窗响应中取消、预检及快照/列表预算超时后关闭浏览器的未取回future问题；它不代表任意浏览器/取消时序均零警告，也不能撤销已经发出的操作。iframe定位检查的临时元素句柄检查后即释放。

### 可选人工录制提供器与采集入口

`record_context("playwright.page", ctx, command, request, include_view=...)` 接受 SDK 的 start/pause/resume/stop/read/ack/discard；与现有页面快照采集并存，不增加固定执行动作或自动回放。开始时明确选择保留页面或新 HTTP/HTTPS 地址，同 context 新页面可跟随，已有其他页面不会混入。iframe 证据携带经核对的 frame 路径和页面 target_id。

监听可信 click/input/change，记录原始实际目标、捕获时目标、操作后目标及字段组/祖先；定位核对实际 DOM 元素身份，节点消失则标缺失，不用同路径替换节点冒充证据。密码及常见敏感字段在浏览器发送前遮蔽；启发式规则不能保证覆盖任意业务秘密。页面基线不读取输入值，操作证据只读取操作目标值，不读取整页值或 cookies。开启后的首个基线在操作前，导航/新文档的基线是在首次操作时观察，明确 observation_timing。

缓冲最多1000条、2MB，单条128KB，超大条目替换为缺失说明；超限移除最早条目并报告 dropped_count/available_after。read 最多100条、192KB事件内容，不消费；ack 只能确认已读取游标，重复确认可重试，最终停止并确认后释放待保存预算。最多16个待保存录制、64个已结束确认回执，资源关闭释放临时缓冲。记录并非持久化：宿主仍须保存成功后确认，规划与步骤采集弹窗已接入共享录制控制条，停止后暂存，确认保存成功才消费；保存失败保留录制，确认失败只重试确认。旧快照采集和默认关闭的发送预览选项保留。

每次操作还携带浏览器当时的document_id、无查询参数/凭据的document_url及短标题。采基线前后核对文档身份；快照途中已跳转时记录PAGE_DOCUMENT_CHANGED缺失证据，不将下一页DOM归入上一页。后状态也核对文档，旧token在新页面复用不能作为原元素验证。非安全上下文使用getRandomValues生成文档身份，兼容没有randomUUID的页面。

include_view=false 不获取图片；true 读取时使用现有 playwright.screenshot 预览，明确它是读取时的当前页面，而不是每次操作截图。大于512KB的PNG暂不附图；正文仍保留。录制没有每秒截图/整页扫描或 UI 重绘；初始化脚本覆盖新文档和 frame，但 closed shadow DOM、跨 context 页面、虚拟化未加载内容和浏览器内置界面不保证覆盖。
