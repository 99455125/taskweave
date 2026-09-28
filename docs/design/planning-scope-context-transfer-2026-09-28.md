# 规划变量作用域与上下文随任务迁移

## 本次修改

- 规划提示词按实际使用范围区分变量：单步骤输入属于步骤，多步骤共享输入才属于任务；前序结果用输出和绑定，环境已有变量复用。
- 网页提示里的任务包 schema 与 API 候选 schema 对齐，明确要求逐步骤的 plan_context_refs；无相关材料明确填 []，不编造或重新生成采集证据。
- 有冻结材料时，候选解析与再次导入均检查是否漏列步骤，失败不创建任务。无材料的历史回复保持兼容；有材料但遗漏映射的旧候选须补齐后重新解析。
- 现有任务包格式和持久化结构不变。既有导出/导入已携带采集组、采集项及图片，本次增加从规划生成到跨工作空间任务包往返的回归证据，并补全导出弹窗说明。
- 不自动移动或改写已有任务变量，不修改用户数据，不提交代码。

## 验证

先添加回归后运行：遗漏映射与提示 schema 不一致的测试失败，跨空间往返测试通过；修复后新增测试全部通过。

定向命令：
`uv run python -m unittest tests.test_planning.PlanningTests.test_context_mapping_cannot_silently_omit_steps tests.test_planning.PlanningTests.test_prompt_schema_requires_explicit_step_context_mapping tests.test_planning.PlanningTests.test_planning_to_task_package_preserves_scope_and_per_step_evidence tests.test_task_transfer tests.test_export_io -q`

结果：14 项通过。往返使用独立临时工作空间，包含两步骤、任务/步骤不同输入、前序结果绑定、两上下文组、每组两采集项及图片；断言每步材料对应关系及再次导出的完整包相同。

另运行 `tests.test_planning tests.test_task_transfer`：29 项中 28 项通过，1 项旧 UI 测试失败。该测试仍期待“新建规划”按钮及旧列表按钮结构，当前未修改的规划页面使用“新建”和整卡点击；未为本次链路修改该 UI 或掩盖失败。

工程检查和 diff 空白检查另行执行。不运行全量测试，不调用真实外部模型；提示词语义引导不能等同真实模型生成质量验收。
