# 上下文组、连续采集与目标会话

来源：[值对象](../../src/taskweave/core/context_collection.py)、[上下文用例](../../src/taskweave/application/contexts.py)、[共享UI](../../src/taskweave/desktop/contexts.py)、[会话服务](../../src/taskweave/infrastructure/context_sessions.py)。

## 持久化结构

步骤和规划分别拥有上下文组及有序采集项。组保存名称/说明/提供者；每次采集保存request、items、views、include_view、来源、时间与顺序。同一次ContextCollection的全部items/views属于同一个采集项，不能拆成多个业务条目。步骤/规划重开及应用重启仍有记录，旧“切换即清空全部上下文”只适用于当时内存实现。

列表查询只取摘要，展开具体capture_id时加载正文/图像；不能每次刷新把全部Base64塞进卡片。复制、导出、冻结、导入须保留完整items/views及顺序。规划生成保存冻结证据，导入不读后来改写的组内容。

## 连续采集弹窗

打开时捕获目标身份、页面代次、原组与修订；本地草稿允许连续追加、编辑名称说明、删除及撤销。删除单项与删除整组分开；空组仍按组操作处理。预览只读取草稿/对应持久化采集项，不触发重新采集。

确认以一个批量请求提交整组，数据库事务成功才更新卡片。步骤确认只失效一次；规划revision只递增一次。失败保留弹窗草稿，取消不写DB；采集过程中已经打开网页等外部资源不会因取消而被数据库回滚。忙碌中真实确认入口只能提交一次，不能只在测试替身中实现去重。

提交前检查目标与页面代次，旧弹窗不能写入后来选中的步骤。已提交且属于原目标的业务操作可完成，随后只禁止迟到UI刷新，不能把导航当业务撤销。统一卡片/弹窗用于步骤和规划，不分叉两套保存逻辑。

## 观察目标

plan.context.targets只列该规划资源；context.targets只列所选、属于该步骤任务的保留运行资源。返回session_id/targets，无实例为空。列目标不创建浏览器、不导航、不接管资源；独立观察没有保留目标。空代码草稿也可观察现存资源。

选择器由提供者schema的x-taskweave-context-targets驱动；无扩展显示参数表单。参数按表单→高级参数→目标request覆盖，选中目标仍保留插件声明的参数。采集携带expected_session_id，实例变更报CONTEXT_SESSION_CHANGED；目标已关闭报CONTEXT_TARGET_UNAVAILABLE，不回退到其他页面。列表和采集在资源事件循环串行运行。

Playwright选已有页只观察该页；新建模式需要URL并创建新页，不导航原目标。scope为viewport/full_page，提供者默认full_page，规划新采集默认viewport；重采集保留原request范围。include_view决定本次是否产生用户预览，插件通过x-taskweave-context-view.default声明默认值。资源结束时忙碌明确失败并保留实例引用，不能丢失关闭入口。

## 证据、预览与隐私

ContextCollection.items是AI证据，views是用户展示声明，不能自动把views并入AI。ContextItem包含kind、mime_type、content、source、truncated；视图为title、renderer、data，renderer须注册。纯文本插件没有预览也应正常工作。

采集原文入库；redact_on_display与redact_for_ai独立、默认true，改变开关不改写历史原文。文本按隐私处理器尽力脱敏；图像Base64完整保留，不能截断后声称是有效PNG，也不执行像素遮盖。已被旧逻辑截断的历史图片不能恢复，需要重新采集。截图可含敏感可见信息，预览脱敏开关不等于图片内容脱敏。

测试重点是事务失败无半组、取消无写入、重启保真、懒加载、旧弹窗身份、session变化、重复确认及冻结证据。入口见 [模块索引](../modules/contexts.md)。
