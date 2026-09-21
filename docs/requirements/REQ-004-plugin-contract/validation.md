# REQ-004 验证记录

环境：macOS 13.7.8 x64、Python 3.13、Playwright 1.58.0、完整 Chromium/Chrome for Testing 145.0.7632.6（revision 1208）。实际 spawn worker，真实浏览器访问本机 HTTP 模拟业务页面。

```bash
uv run --extra browser --extra sample python -m unittest discover -s tests -v
uv run --extra browser --extra sample python examples/req004/browser_demo.py
uv run --extra browser --extra sample python scripts/check_project.py
uv run --extra browser --extra sample python scripts/check_req002.py
uv build --wheel
uv build --wheel --directory plugins/playwright
uv build --wheel --directory plugins/custom
```

验证范围：插件安装入口与启停、重复入口/ID/动作、API/核心/依赖版本、依赖环、加载失败隔离、输入输出 schema、编写约束冲突、自定义表兼容迁移与回滚、核心禁用浏览器后仍可用、角色 DOM/cookies 隔离、资源复用、暂停当前页面观察、人工已提交防重复、提交后 worker 丢失及外部查询确认、失败截图不伪造成功、页面上下文与 AI READ 工具、多个独立插件贡献、固定步骤执行无模型调用、截图/下载保存和 DB 跨步骤传值。

独立业务演示已通过：status=SUCCEEDED，received_order_id=ORDER-001，business_submit_count=1，实际 PNG 和 CSV 文件保存成功。可见浏览器人工操作模拟已通过。三份 wheel 均能独立构建。最终完整回归 40 项测试全部通过（97.492 秒）。

独立安装验证：在项目外的新 uv 虚拟环境中安装构建后的核心与 sample wheel，不通过源码路径导入。标准入口发现、启用、步骤试跑、确认、正式执行通过，输出 PACKAGED；该环境未安装 Playwright，证明核心和自定义插件可独立运行。此验证使用开发机依赖安装，不代表 Windows 离线便携包已交付。

限制：AI 用可控模型 fixture 验证实际只读工具调用，真实外部模型账号未配置。Windows 10 x64、真实内网业务和 Windows 免安装打包不声明已验证；属于后续实机/交付验收。任意网站的防重复需业务查询和步骤逻辑，通用 click 无法提供跨外部系统事务保证。

最终连续搜索检查通过（9.481 秒），新增覆盖 READ 失败自动释放租约后仍保留页面、刷新上下文再修复；观察接口依据实际存活的 session_run_id，而非 DB 租约是否存在。快照最终限制与状态/标签优化已在此用例覆盖。模型/历史 10 项回归通过（6.001 秒），四轮大快照保留全部对话、内存原始快照且请求仅引用历史快照。

2026-09-18：Playwright 四项优化完整回归 72 项通过（339.693 秒），包含真实 NiceGUI/Chromium 界面、插件、运行/存储。运行中追加的历史快照引用优化另以模型/历史 10 项通过（6.001 秒），最终快照与无租约 READ 失败继续采集另以真实连续搜索用例通过（9.481 秒）。工程检查、设计 8 项检查及 diff 检查通过。浏览器搜索使用本机测试站点，AI 使用模型 fixture，未声称真实 DeepSeek/百度端到端成功。首次插件回归发现普通元素不可调用 is_editable、LOCATOR 诊断范围及旧测试误把 selector.value 当成业务输入值；修正后完整回归通过。

2026-09-18 验证：变量/步骤默认输入合并检查通过；核心 26 项通过（37.288 秒），模型与对话 10 项通过（3.412 秒）。原“拒绝本地密钥保存”检查按用户当前要求更新为允许配置、运行摘要仍脱敏，修正测试中的草稿未确认后通过。验证码 3 项通过（16.135 秒）：禁止 socket 网络连接仍实际识别 1234；浏览器真实采图→本地 OCR→填写→提交→URL/title 断言成功；当前上下文包含验证码图片及密码框定位，不含密码值。连续搜索/失败上下文修复额外回归通过（7.114 秒）。首次本机原生库导入约两分钟，完成初始化后复测通过；Windows 实机与真实业务验证码准确率不在本机 fixture 验收中。

2026-09-18 最终交付：本地变量和表单自动预填、独立保存任务配置、网页 AI 两个入口及回复采纳、插件渠道适配、历史名称、超长历史保留最近两轮、本地 ocr 插件与通用元素采图均已实施。变量 5 项（1.798 秒）、执行回归 7 项（6.324 秒）、网页/中文/超长历史 4 项（1.363 秒）通过；核心 26 项、模型 10 项、显示 3 项、插件契约 5 项、OCR 3 项、连续搜索 1 项及真实界面 1 项检查通过。工程检查覆盖 101 个 Markdown 文档并通过，diff 检查通过。实际 OCR 与浏览器登录使用本机测试图片/站点；未操作用户真实登录页，未验收 Windows 便携包。无 DDL 变更；Playwright 0.3.0、ocr 0.1.0、插件 API v1。

### 无名称图片定位回归（2026-09-18）

`tests/test_image_locators.py` 使用真实 Chromium，模拟三个无 ID、无 alt、位于不同父节点的图片，以及 canvas 和 iframe 内图片；验证快照定位唯一、验证码定位指向正确表单、图片可截图、frame 范围有效。真实业务登录与该网站验证码识别准确率不属于此回归验证。

本轮结果：图片定位回归 1 项、本地 OCR 与浏览器集成回归 3 项通过；工程检查及差异空白检查通过。API 与网页对话的插件提示词同步说明 DOM 路径使用规则。
