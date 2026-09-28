# 上下文与采集会话

为步骤、规划及调试提供插件证据与用户预览。业务持久化上下文与内存中的活跃资源会话必须分清。

## 当前行为与约束

- 持久化结构为“上下文组 + 有序采集项”，分别保留名称、说明、采集 request、时间、来源和预览；不是离页就丢失的纯内存列表。
- `ContextCollection(items, views)` 区分 AI 证据和用户预览；预览不自动并入模型证据。核心按注册 renderer 渲染，不按插件名硬编码。
- 步骤上下文属于确定步骤；修改会使确认失效。规划更新还要核对 revision；批量操作保持事务一致性。
- 取消采集不写入，失败保留旧记录或待编辑草稿。旧弹窗提交前核对捕获的目标与页面代次，不能写到后来选择的步骤。
- 目标列表只枚举当前实例已有资源，打开列表不能偷偷新建浏览器。采集携带 expected_session_id 时，资源实例变化必须拒绝旧请求。
- 调试/正式执行可提供本进程仍存活的保留会话；历史数据库记录不代表资源仍存在。规划、调试、正式运行不能合并所有权。
- 复制、导入必须保留组项顺序和完整证据；规划生成导入使用冻结快照而非最新记录。
- 步骤和规划共享分组卡片、暂存采集行和内容预览组件；预览和编辑采集作为主要操作，移动/删除收进更多菜单，暂存删除仍可撤销。隐私脱敏规则同样应用于卡片摘要和预览。
- 内容预览优先呈现插件注册的展示结果，图片等比例完整显示；长图在独立内容区域滚动，标题和关闭操作保持可达。原始采集数据可展开查看，没有展示结果时默认展开；不更改采集内容或持久化格式。
- 采集对话框保留插件动态请求表单、目标选择、可选高级参数、观察会话、采集顺序和删除暂存标记；保存时整组一次提交，取消不写入，失败时保留可重试草稿。

- 组卡片默认折叠，局部更新保留展开状态。每项独立维护标题、长操作说明与 `send_preview`；说明在弹窗编辑，列表只显示摘要。
- `send_preview` 默认 false，与 `include_view` 独立。勾选后按插件预览携带图片或结构化数据；标题、说明始终随该项发送。API 图片使用多模态消息，网页 Chat 导出图片附件供上传，提示词引用附件名称。未勾选的预览不发送。
- 新字段随任务包、复制与规划冻结导入保留；旧包缺字段使用空说明、关闭预览的默认值。

## 代码入口

[数据契约](../../src/taskweave/core/context_collection.py)、[步骤上下文用例](../../src/taskweave/application/contexts.py)、[会话协调](../../src/taskweave/infrastructure/context_sessions.py)、[步骤上下文仓储](../../src/taskweave/infrastructure/repositories/step_contexts.py)、[规划上下文仓储](../../src/taskweave/infrastructure/repositories/plan_contexts.py)、[共享采集 UI](../../src/taskweave/desktop/contexts.py)、[步骤上下文组件](../../src/taskweave/desktop/components/step_contexts.py)。

## 验证入口

`domain.contexts`、`repository.contexts`、`ui.contexts`；共享 session 变更通过 changed dry-run 覆盖真实消费者。重点检查组项顺序、目标会话过期、事务失败、离页迟到写入和草稿保留。关联：[规划](planning.md)、[执行](execution.md)、[插件](plugins.md)。

## 按需深入

[连续采集与会话](../reference/contexts.md)。只在本次修改涉及相应契约时阅读。
