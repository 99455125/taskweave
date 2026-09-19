# 项目计划

[总需求池](requirements/REQ-001-requirement-pool/backlog.md)按连续编号实施：总体设计 → 任务与步骤 → 插件架构与 Playwright → 操作台 → 分享 → 基础交付 → 控制流 → 拖拽编排。

AI 和手动编写均属于 REQ-003，插件统一向编写服务贡献提示词、能力与校验；Playwright 在 REQ-004 内完成并作为架构验证案例。REQ-003 核心已实现。

REQ-002 已通过用户评审，REQ-003 已进入实现与验收。步骤输出默认落任务库，核心统一保存，插件定义结果结构、自定义表和解析。

2026-09-17：REQ-002 已由用户确认；REQ-003 可运行核心交付，待验收。入口见 [使用指南](requirements/REQ-003-task-core/usage.md)，后续 REQ-004 实现真实插件管理和 Playwright。

2026-09-17：REQ-004 代码已交付，插件与真实浏览器入口见 [运行指南](requirements/REQ-004-plugin-contract/usage.md)。下一项为 REQ-005 Windows 客户端 UI；Windows 免安装交付由 REQ-007 验证。

2026-09-17：REQ-005 调整为 Windows / macOS 跨平台独立客户端，共用 UI 和应用服务，分平台验证与打包；Windows 10 x64 离线免安装约束保持。

2026-09-17：REQ-005 已完成代码实现并进入最终回归：跨平台任务内界面与核心执行间隔已落地。macOS 原生窗口与实际 UI 流程通过，Windows/Apple Silicon/冻结包待各自实机验收。运行见 [REQ-005 指南](requirements/REQ-005-local-workbench/usage.md)。

2026-09-17：断电后恢复完整验证，52 项测试全部通过（269.131 秒），包含核心、Playwright、间隔恢复和真实界面操作。工程校验、8 项设计检查、core 与 Playwright wheel 构建均通过。REQ-005 源码客户端交付，待用户验收；Windows / Apple Silicon 实机与冻结包仍未验证。
