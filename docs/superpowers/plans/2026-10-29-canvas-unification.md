# 任务组合与步骤画布交互统一实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox syntax for tracking.

**Goal:** 统一任务组合与步骤画布的编排、状态反馈和辅助操作，修复组合移动顺序与新增选中状态。

**Architecture:** 复用 FlowTree、BranchForm、ControlForm 和现有流程编辑操作，扩展调用方接线及组合草稿操作。流程树是顺序和路径的权威来源；组合仍显式保存草稿，步骤保留现有持久化及确认机制。

**Tech Stack:** Python、uv、NiceGUI，沿用当前依赖。

**Spec:** 本文“已确认设计”记录本聊天 UI/UX 核对后用户批准的三组范围；既有流程编辑基线见 2026-10-28-flow-editing.md，不重复实施该计划已有成果。

## 已确认设计

用户已批准以下范围，并指定一个 GPT-6.1 Sol、中等推理强度子 Agent 实施、主 Agent 审核。

1. 编排入口与位置操作：统一顶部“添加节点”菜单；空流程保留画布，可先添加任务/步骤或控制结构；空路径使用“添加节点”；组合接入节点前后插入、路径内添加、拖动落点和跨分组移动；节点菜单提供“移除任务”。不恢复节点之间常驻加号。
2. 状态与定位反馈：新增后选择新节点并显示配置；移动按流程树相邻关系，节点身份、环境、映射保持；删除后选择有效节点；组合补结构路径及明确修改状态，失败提供就近反馈。修复全局 nodes 列表与结构顺序混用，以及控制块选中后添加任务仍显示控制配置。
3. 画布辅助与表达：提供一致的 75%、100%、125% 缩放和收起，按任务/组合保留当前会话状态；统一分别表达业务节点数与控制节点数；统一“列表遍历”和通用节点提示；窄窗口操作可达。

保留业务差异：任务引用现有任务、独立环境和输入映射；步骤可复制/拆分及编辑代码；移除任务不删除被引用任务；组合显式保存，步骤现有保存与确认规则保留。无需强制统一卡片宽度。范围外：撤销重做、多选、框选、自由连线、自动视口居中、执行模型和数据格式调整。

## Global Constraints

- 沿用当前工作区，保护所有已有修改。禁止 commit、push、PR 写操作、部署和真实业务数据变更。
- 不运行全量测试，不用分组拼成全量；使用独立临时测试数据和端口。
- 使用 uv run，保留依赖与 uv.lock，不另装依赖。
- 主 Agent 仅审核；子 Agent 独占产品代码、测试和对应模块文档写入，不再派子 Agent。
- 实施前基线：/tmp/taskweave-canvas-unification-20261029-baseline；审核相对此基线，不将既有未提交内容归为本次修改。

## Review Focus

- 空步骤任务及只有控制块时仍可编辑：UI/浏览器测试覆盖先建控制块、再插入步骤。
- 分支/循环中混合业务与控制节点：草稿测试覆盖边界移动、序号及跨组身份保持。
- 非法依赖移动或删除：测试验证失败反馈、原草稿保持，以及现有保存验证。
- 控制块有未保存配置时新增任务：组件测试验证配置保留和新任务选中。
- 重绘及窄窗口：浏览器验证缩放/收起状态恢复、菜单可达、无页面横向溢出。

## Task 1: 完整统一画布交互

**Files:**
- Modify: src/taskweave/desktop/components/flow_tree.py、sequence_flow_editor.py、step_editor.py、branch_form.py；desktop/pages/sequences.py；desktop/theme.py；presentation/sequences.py、flow_editor.py（仅必要处）。
- Test: tests/ui/test_sequence_flow_canvas.py、test_flow_editor.py；tests/test_sequence_canvas_browser.py、test_flow_canvas_browser.py；组合草稿定向测试。
- Docs: docs/modules/desktop.md；新增测试文件时维护 tests/module-map.json。

**Interfaces:**
- Consumes: FlowTree 的 on_insert/on_drop/on_delete_step 回调与 SequenceDraft 的 flow/nodes，现有 step.insert、task.flow.save 和 sequence.save。
- Produces: 组合按 parent_id/index 插入和移动，原子校验后更新草稿；两处统一画布入口与状态呈现。业务节点名由调用方提供，保持执行只读画布行为。

- [ ] 读取相关实现、依赖、项目测试约定，复现顺序和选中状态问题并先建立有效回归。
- [ ] 扩展组合草稿按流程树插入、排序、移动与移除；校验失败保持原状态。为跨组、边界、控制块混排和同一任务多引用添加回归。
- [ ] 接入组合画布操作与新增选择，统一菜单、空路径、反馈、路径、视图状态和计数；保留组合保存边界。
- [ ] 让零步骤任务也呈现可编辑画布；统一共用文案和窄屏布局，保护原步骤草稿/控制配置离开规则及执行画布。
- [ ] 运行针对本次改动的组件和普通测试，再运行精确浏览器场景；检查桌面/窄窗口。
- [ ] 同步模块文档，执行 uv run python scripts/check_project.py 与 git diff --check，记录实际结果与限制。
- [ ] 主 Agent 审核本次差异及证据；子 Agent 修正问题并复验。禁止以历史验证替代本次证据。

## 进度

- 已确认设计与实施分工；准备实施。无新增业务决策待确认。
