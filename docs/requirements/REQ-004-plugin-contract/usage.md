# REQ-004 运行与插件开发

## 直接运行真实浏览器演示

在项目目录执行：

```bash
uv sync --locked --extra browser --extra sample
uv run --extra browser --extra sample python -m playwright install chromium --no-shell
uv run --extra browser --extra sample python examples/req004/browser_demo.py
```

浏览器下载命令只在允许联网的开发/构建机执行。运行时不会自动下载。受限 Windows 10 x64 虚拟机仍采用 REQ-007 的随包浏览器免安装方案。

演示在本机启动模拟订单网站，完成手写步骤 → 试跑 → 确认 → 正式执行 → 暂停继续 → 任务 DB 传值 → 截图和下载。返回 `status=SUCCEEDED`、`received_order_id=ORDER-001`、两个文件路径及 `business_submit_count=1`。

可见窗口演示：

```bash
uv run --extra browser --extra sample python examples/req004/browser_demo.py --headed
```

Playwright SDK 与浏览器必须匹配；默认使用随 SDK 下载的完整 Chromium 通道，可用 `PLAYWRIGHT_BROWSERS_PATH` 指定构建机预置/随包目录，不要求系统 Chrome。依据见 [Playwright 浏览器文档](https://playwright.dev/python/docs/browsers)。当前开发机 macOS 13 使用 1.58 系列，其他平台允许更新版本；实际版本由 uv.lock 固定，Windows 交付需重新实机验收。

## 管理插件

```bash
uv run --extra browser --extra sample taskweave --home .runtime/workbench plugins list
uv run --extra browser --extra sample taskweave --home .runtime/workbench plugins enable playwright
uv run --extra browser --extra sample taskweave --home .runtime/workbench plugins enable sample
uv run --extra browser --extra sample taskweave --home .runtime/workbench serve
```

安装和启用分开：默认启用本地 demo/text 测试适配器，Playwright/sample 要明确启用。配置保存在数据目录 plugins.json，主程序与 worker 使用相同配置。CLI 管理要求服务关闭；服务运行时使用本地 API：

```json
{"operation":"plugin.configure","params":{"plugin_id":"playwright","enabled":true}}
```

plugin.list 查看已安装入口，capabilities 查看实际能力及 load_errors。运行持有租约时禁止插件配置变化；失败启用不改变旧配置。启动时某个已启用包缺失，保留错误并让无关插件继续可用；使用缺失能力的步骤预检查失败。依赖版本与环、重复 ID、API/核心兼容及 schema 都在启用前检查。

禁用示例：

```json
{"operation":"plugin.configure","params":{"plugin_id":"playwright","enabled":false}}
```

## 浏览器能力

| 动作 | 输入（role 可选，默认 operator） | 输出 |
|---|---|---|
| playwright.page_open | url | null |
| playwright.page_title | role | title |
| playwright.page_text | selector（默认 body） | text |
| playwright.page_fill | selector、value | null |
| playwright.page_click | selector | null |
| playwright.page_wait | selector、state（默认 visible） | null |
| playwright.page_assert_text | selector、text | matched |
| playwright.page_screenshot | role | staged_file |
| playwright.page_download | selector | staged_file、suggested_filename |
| playwright.page_inspect | role | title、URL、交互元素描述 |
| playwright.page_handoff | role | ready |

填充、点击和下载声明 WRITE。点击成功不等于业务成功，应等待并断言单号/状态。插件不假设页面布局；模拟网站中的“先查状态，再决定提交”是步骤业务逻辑，不能保证任意网站天然幂等。

角色资源独立，运行期间相同 role 复用页面。单步或 UNTIL 后保持 PAUSED，窗口留给人检查；page_handoff 把窗口带到前台，随后由运行控制暂停。人工操作后继续的步骤应先核对状态。运行完成、放弃或应用退出后资源关闭；重启不还原原页面。

环境配置示例：

```json
{"operation":"environment.save","params":{"name":"Browser","public_config":{"browser":{"headless":false,"timeout_ms":10000}}}}
```

## AI 编写扩展

Playwright 提供提示词、示例、内容 lint、业务断言动作、页面提供器、只读观察工具、错误诊断和会话资源。它不另建模型调用器。

context.read 提供两种方式：

- 给 request.url 和 environment_id，在独立观察浏览器采集并返回供用户预览。
- 给 run_id，在 PAUSED/FAILED 的当前 worker 中读取已有页面；request 可指定 role。不提供 URL 就不会导航或建立新页面。会话已丢失时明确报错。

```json
{"operation":"context.read","params":{"step_id":"实际UUID","provider_id":"playwright.page","run_id":"实际UUID","request":{"role":"operator"}}}
```

采集的是标题、去掉查询部分的 URL、最多 50 个交互元素描述；不采集输入框的值、密码或 cookies。用户选择后再通过 step.generate 的 contexts 传给 AI。页面文本仍可能含业务信息，调用方应检查。截图是本地文件结果，不自动传给模型。

step.generate 可接 environment_id。AI 的 playwright.page_inspect 工具要求明确 url，使用独立观察会话；AI 不可通过生成流程执行点击、填写或下载。模型返回建议后仍需用户保存 → 试跑 → 确认。固定执行不调用模型。

## 结果和错误

普通 JSON 默认由核心保存至任务库 step_outputs。Playwright 的 image/download 处理器只把 staged_file 转换为文件描述；核心校验 token、移动文件、计算摘要、存储引用并清理。sample.rows 演示自定义表声明与解析。没有结果时不建任务库。

通用可选 failure_results 钩子返回诊断产物，由核心保存。失败截图会出现在运行 results，但不会写成功 receipt，也不会把失败尝试变成成功。涉及副作用的异常保持 UNKNOWN，需查业务状态后 run.reconcile，不能直接重试。缺少保存的单号不会因人工确认而虚构出来。

## 开发独立插件

只导入公开 API `taskweave.plugins.sdk`，不要导入 core/application/infrastructure。完整例子在 plugins/custom，浏览器插件在 plugins/playwright。

插件 pyproject.toml：

```toml
[project.entry-points."taskweave.plugins"]
myplugin = "my_package:Plugin"
```

无参工厂返回插件，manifest 中 id 必须与入口名一致。manifest 必填 id、package_version、api_version=1；可声明 core_requires、dependencies（插件 ID → PEP 440 版本范围）。能力 ID 必须以插件 ID 加点开头。actions/tools 提供 CapabilitySpec；资源 ID 必须已注册。各统一方法及数据类型见公开 SDK。

版本用于包/schema 兼容，不是步骤版本。能力清单从插件 methods 读取，以 capabilities 接口展示；不在 manifest 重复维护一份易失配清单。

AuthoringContribution.constraints 是可机器校验的补充约束：同名不同值拒绝生成；项目 content_format 和 entrypoint 不可覆盖。自由文本提示词只作建议，不能绕过核心静态规则或动作 allowlist。

独立构建：

```bash
uv build --directory plugins/custom
uv build --directory plugins/playwright
```

开发机可使用 uv 管理包，离线交付机由构建流程预装收集，不在运行时调用 pip/uv 安装。热更新、插件市场与任意目录扫描未纳入。

### 自定义表和兼容迁移

ResultHandler 提供 schema、prepare、parse、preview，不拿数据库连接。宿主拥有所有实际读写。表名前缀为 p_加插件 ID（点/连字符转下划线）再加下划线；宿主注入 run_id/step_id/attempt_id。声明列类型 TEXT/INTEGER/REAL/BLOB。

```python
{"version": 2,
 "tables": {"p_sample_rows": {"value": "TEXT", "extra": "TEXT"}},
 "indexes": {"p_sample_rows": [["run_id", "step_id"]]},
 "migrations": {"2": {"add_columns": {"p_sample_rows": {"extra": "TEXT"}}}}}
```

支持兼容加列及索引；升级前核心备份至任务 backups 目录，结构和记录写入在同一事务，失败回滚。删列/改类型等破坏性变化明确拒绝，需单独设计迁移，不执行插件任意 SQL。读取更高 schema 版本拒绝。

## 本地验证码 OCR

[验证码插件指南](../../../plugins/ocr/README.md) 提供无 API Key 的本地识别与跨插件步骤示例。启动增加 `--extra ocr`，插件管理启用 ocr，步骤同时选 playwright 和 ocr。普通文字图片适用；真实业务页面先采集上下文，再由 AI 按当前定位器生成完整步骤。
