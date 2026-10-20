# 桌面UI与交互

## 职责划分

NiceGUI/pywebview保留为当前UI框架。desktop负责控件、布局、渲染、定时器及平台行为；presentation负责普通状态与交互决定；DesktopController转接应用操作、共享编写请求和平台适配。页面不直接访问仓储或SQL。

| 交互 | 普通状态/流程所有者 | 实际适配 |
| --- | --- | --- |
| 路由、离开选择、标签页草稿恢复 | WorkspaceNavigation、TaskWorkspace、TaskTabTransition、RecoveryState | Workbench、TasksPage、launcher |
| 任务/步骤编辑、保存与批量操作 | TaskDraft、EditorSession、StepActions | TasksPage、StepEditor、StepList |
| 规划配置、候选与导入 | PlanningInteraction、PlanEditorSession | PlanningPage及采集/生成视图 |
| AI选择、生成/修复候选 | AIInteraction、AIChoiceDraft、AuthoringFlow | StepAIEditor |
| 采集草稿、目标、录制提交 | CollectionForm、TargetSelection、ContextCaptureDraft、RecordingDraft | 步骤/规划采集组件、RecordingControls |
| 调试、正式创建、补参 | DebugInteraction、TrialInputDraft、RunCreation、RunInputs | StepDebugPanel、RunPage、RunInputDialog |
| 执行查询、按需/增量日志 | ExecutionInteraction、PollingState、HistoryLoadState、LogStreamState | ExecutionDetails、HistoryPage、LiveRunLogs |
| 分类、筛选、环境和设置 | CategorySession、CatalogFilter、PluginSelection、EnvironmentSession、SettingsSession | 对应页面与控件事件 |

这些对象位于[presentation](../../src/taskweave/presentation)，UI对象留在[desktop](../../src/taskweave/desktop)。未来替换UI需要新适配器，不需要复制交互规则；当前没有第二套UI或远程前端协议。

## 生命周期规则

输入事件及时写入普通草稿，业务动作消费草稿，不在提交时扫描控件树。异步响应检查任务/步骤/运行、版本及视图代次，旧响应不能修改新目标。控件存活与文档可见性由框架观察并传入，交互层决定是否刷新和接纳。

dispose释放自己拥有的计时器和控件资源、使在途视图响应失效；它不改变真实文档可见性，不终止后台运行，也不取消已接受写入。UI重绘不能重新创建业务请求或清除共享在途状态。

同一标签页的步骤/调试/补参普通草稿可在服务内缓存恢复，标签页相互隔离；恢复保留原expected_hash，其他窗口修改时继续报冲突。缓存不承诺服务重启或标签页关闭后恢复，规划/环境表单和未提交AI弹窗不属于这一标签页恢复范围。

## 页面与平台

Workbench显式装配Home、Tasks、Planning、Executions、History、Plugins、Environments、Settings和Marketplace等页面。StepEditor组合步骤、AI、调试和上下文；窄面板协作，避免将整个Workbench作为任意服务代理。

对话框支持ESC和点外关闭，共享捕获守卫阻止穿透；不要给普通弹窗加persistent/no-esc-dismiss。文件选择、剪贴板、打开路径及原生窗口在desktop/platform.py等适配；浏览器调试模式与原生窗口模式分别验证。

首页“新建执行”直接打开任务选择与运行配置窗口，创建成功后进入执行页；最近执行结果通过“全部记录”进入执行页。任务行的“新建执行”继续预选该任务。

## 验证定位

对应ui.*及presentation.interactions。无GUI导入测试证明普通交互可运行，实际NiceGUI事件测试证明接线，真实浏览器验证页面装配；三者覆盖含义不同。启动与包资源见[运行与打包](../deployment.md)。
