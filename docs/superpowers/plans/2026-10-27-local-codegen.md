# 本地代码生成实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans，按任务勾选并记录验证。

**Goal:** 上下文统一录制，Playwright 录制材料支持 AI 编写及确定性的本地步骤代码生成。

**Architecture:** 插件可选纯生成接口处理已保存的版本化录制。宿主校验归属、材料与草稿摘要、输入绑定及输出；presentation 保存候选并保护迟到响应，desktop 在原步骤代码页接线。

**Tech Stack:** Python / uv / NiceGUI / Playwright，沿用现有依赖和上下文仓储。

**Spec:** [已确认设计](../specs/2026-10-27-local-codegen-design.md)。用户已明确授权本会话实施，无需再次审核执行方法。

## Global Constraints

- 沿用现有工作区，保护所有已有改动；不提交、不推送、不写 PR。
- 全量测试未授权，仅运行对应插件、应用、presentation 和 UI 的定向验证。
- 不操作任务组合/流程执行模块；tests/module-map.json、operations 文档等共享文件先协调或最后局部追加。
- 本地生成不调用模型、不启动浏览器、不执行录制材料。
- 旧插件 API v1 兼容；旧录制证据不足明确提示，不猜测动作、秘密或页面身份。

## Review Focus

- 暂停、导航失联、未确认源事件和不支持交互不能生成残缺流程。
- 同页 input/change 与 checkbox 事件归并不丢掉跨控件操作。
- 敏感/截断/空值、输入绑定与动作参数按运行 Schema 验证。
- 源材料、当前代码、输入 Schema 或插件变化时旧候选不能应用。
- 录制 target_id 不能复制到新执行，始终核对主页面及角色。

### Task 1: 可选生成契约、宿主校验与 Playwright 转换器

**Files:** 新增 core/codegen_contracts.py、application/codegen.py、plugins/playwright/src/taskweave_playwright/codegen.py；局部修改 plugins/sdk.py、core/ports.py、plugins/registry.py、Playwright plugin.py、application/composition.py/operations.py。

**Interfaces:** code_generators() 返回声明；generate_code(generator_id, recording, bindings, options) 返回 JSON 候选。step.codegen.sources/generate 使用当前步骤的完整草稿和保存的 capture。生成结果含 source/body_fragment、input_slots、diagnostics、required_capabilities、source_digest、candidate_digest、applicable。

- [x] 写 tests/test_local_codegen.py 的声明、转换、归属/漂移、预算与绑定失败用例并观察失败。
- [x] 实现可选契约、版本化材料解析及纯转换；空/旧/损坏录制明确诊断，转换无模型和资源依赖。
- [x] 宿主校验源 capture、草稿插件/Schema、结果结构、AST 和动作 Schema，复核摘要。
- [x] 定向测试通过后记录结果。

### Task 2: 现有上下文录制补齐生成材料

**Files:** Playwright recording.py、新增 recording_codegen.py 与 recording_codegen.js；tests/test_playwright_codegen_recording.py；现有上下文保存/ack 接口保持。

**Interfaces:** playwright.recording JSON 增加 codegen 字段，含版本、role、primary、起点、归一化动作、每文档源回执和完整性问题；旧 events 保留供 AI。stop 后才能 complete。

- [x] 写真实 Chromium 录制测试：fill/click/select/check、敏感值、重复事件、暂停、未确认文档、导航和 unsupported 哨兵；观察失败。
- [x] 在现有录制器绑定生命周期采集语义与源回执，不创建第二套入口；只在 stop 后产出完成材料。
- [x] 验证保存材料在浏览器关闭后仍能生成、通过插件执行核对 fixture 状态。
- [x] 运行本次录制与既有录制定向回归。

### Task 3: 普通交互状态与步骤代码页

**Files:** 新增 presentation/codegen.py、desktop/components/step_codegen.py；局部修改 desktop/components/step_editor.py；tests/presentation/test_local_codegen.py、tests/ui/test_step_codegen.py。

**Interfaces:** 普通状态持有 source、bindings、options、候选、完整草稿身份；UI 通过 controller.call 调用宿主，不直接调用插件或仓储。

- [x] 写无录制、绑定、生成失败、素材/草稿变化、替换差异确认、插入语句位置和迟到响应失败用例。
- [x] 实现数据源选择、参数补充、三类结果视图、左侧完整候选和应用。
- [x] 在既有辅助栏增加模式；动态插件选择控制入口，保留 AI/插入动作与已有代码。
- [x] 定向组件事件与普通交互验证，通过后记录。

### Task 4: 知识同步与集成审阅

**Files:** docs/contracts/plugins.md、operations.md、docs/modules/authoring.md、contexts.md、plugins.md、plugins/playwright/README.md；tests/module-map.json。

- [x] 与控制流会话协调共享文件，按最新内容局部追加映射和契约，禁止整文件回写旧快照。
- [x] 运行映射检查、必要消费者回归、工程检查和 git diff --check。
- [x] 由独立 reviewer 审阅本次文件与增量；修复实质问题并验证。
- [x] 核对所有已有修改仍在，交付实际通过、未验证与限制。

## 进度

- 2026-10-27：用户确认修订设计和样式并授权实施；当前 main、混合工作区，依用户规则原位实施。
- 已只读核对控制流会话计划，避免其 core/flow、sequence、运行器和画布模块；共享文档/映射待协调。

## 本次验证结果

- `uv run python -m unittest tests.test_local_codegen tests.test_playwright_codegen_recording tests.test_playwright_recording tests.presentation.test_local_codegen tests.ui.test_step_codegen tests.test_codegen_browser tests.ui.test_step_editor_state tests.test_plugin_contract.ContractTests tests.test_context_recording tests.application.test_dispatch_policy tests.presentation.test_operation_ports -v`：75 项通过。
- 加强真实录制回放用例后单独复测：关闭整个录制浏览器、保存至临时仓储、由应用生成、新浏览器执行，通过。
- `uv run python scripts/check_project.py`、`git diff --check`、application.codegen/ui.codegen 映射 dry-run（含浏览器目标）通过。
- 独立审阅提出的 iframe 顺序、scroll 缺口和 discard 生命周期问题，均先复现失败再修复并回归；宿主另补插入片段与完整代码一致性回归。
- 共享映射与操作文档已按另一个控制流会话给出的 notes 追加；步骤编辑器 collect_controls 按该会话明确请求局部接入 conditional_branches，既有用户改动保留。
- 未运行全量测试；未进行 Windows、冻结应用或真实业务网站验收。本地 fixture 与组件/浏览器证据仅覆盖本次已说明范围。

## 用户验收修复：预览误显示示意模板

- 2026-10-27 用户截图显示右侧固定示意代码，误认为录制生成结果。根因是 step_codegen.py 的代码页无条件渲染常量模板，失败诊断默认藏在另一个页签。
- 已改为仅显示真实、可应用的 source；失败直接显示“未生成可用代码”和具体原因，不显示可复制的模板。参数未解决或重新生成失败时保留原编辑代码。
- 只读核对本机最新录制的完整性元数据：9 个动作，停止状态，但含非主页面、不支持交互、额外页面及文档/frame 证据缺失；该材料没有产生可用候选。未改写材料或已保存/未保存的用户代码。
- 18 项针对性的转换、普通交互、组件与实际浏览器回归通过；其中包含先预览成功候选、同一录制变更为不完整后刷新并生成的回归，旧候选与绑定同步失效，左侧恢复原编辑器。工程检查和差异空白检查通过。
- 用户同时报告的流程终点重叠已由控制流会话修复；本会话未重复修改其产品代码，重跑 test_flow_canvas_layout，通过 Chromium / WKWebView 的长直线、分支与遍历布局验证。

## 用户验收修复：多余空白页与已有会话选页

- 根因：录制新地址时，page_for 为新资源创建主空白页，随后录制分支又无条件 new_page，导致多余空白页及 NONPRIMARY_PAGE。修复为新资源复用初始页面；已保留会话的主页面只有 about:blank、无标题、无 DOM 内容时才复用，已有页面和表单不覆盖。
- 选择已有 target 不导航、不新建页面、不改变原角色默认主页面。新录制以 target_mode=selected 记录明确选页，生成时使用 page_targets 在当前运行按地址摘要唯一解析目标，前置检查、显式导航和各动作都传同一 target_id；目标缺失/重复/列表截断在写入前停止。旧录制 ID 不复制、不伪造选页或缺失回执。
- 重复开始录制提前检查忙状态，不先开页或污染正在录制的完整性。
- 独立审阅发现插入第二段生成代码可能覆盖临时目标变量；已先复现并实现插入时变量避重命名。显式“打开地址”同样维持所选页绑定，已验证原主页面和会话 marker 不变。
- 回归覆盖新建会话、已有空白会话、空白地址但有 DOM 内容、已有非主标签页的录制/回放、重复路径阻止写入、宿主动态目标参数校验、两段代码插入隔离。

- 本轮最终验证：53 项录制、生成、选页、组件及实际浏览器定向回归通过；工程检查和 git diff --check 通过。未运行全量、Windows 或真实业务站点验收。

### 上下文列表刷新反馈（2026-10-27）

- 用户要求录入上下文后直接刷新选择列表，无需切换页面。现有“刷新材料”已重读保存材料，本次改为选择框旁明确的“刷新上下文”，增加防重、数量反馈与失败显示，沿用选择保留及材料变更失效规则。
- 新增组件按钮接线回归：面板打开后保存新材料，点击刷新即可读取；再次新增后刷新保留已有选择和代码草稿。

### 上下文结构化查看（2026-10-27）

用户明确本次仅改采集/录制后的可读性：统一“查看上下文”入口，支持用户直接查阅元素、定位器及录制动作以手动编写步骤，不改变编写流程或录制实现。默认展示结构化列表/字段树，截图与原文分标签查看；多插件共用，保留显示脱敏与只读行为。

实现复用 desktop/contexts.py 的共享查看器；列表分页/筛选、逐行详情、定位器复制与通用字段树由共享 UI 处理。验证包含真实 NiceGUI 组件及隔离 Chromium 页面；后者使用本地演示材料，不能替代真实业务页面的采集验收。
