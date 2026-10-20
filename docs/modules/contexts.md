# 上下文与资源会话

## 职责

为步骤编写、规划及调试提供结构化证据和可选预览，管理有序采集项与可选录制。持久化材料与活跃资源会话分开；材料存在不能证明浏览器或连接仍存活。

## 数据和选择

上下文组归属步骤或规划，拥有provider_id、名称、说明与顺序；组内采集项保存request、items、views、时间、来源、操作说明和send_preview。ContextCollection以items表示证据、views表示用户预览；include_view决定是否采集预览，send_preview另行决定是否将其发给模型。

目标枚举只列出现存资源，不因打开选择器新建浏览器。请求带expected_session_id时必须匹配原资源身份。独立步骤会话、规划会话和保留运行worker会话分开，历史运行记录不能替代活跃会话。

CollectionForm持有提供器、运行选择、动态Schema原始输入和高级参数；TargetSelection持有目标/session选择及请求代次。步骤与规划UI共用这些状态，采集和录制读取普通草稿。ContextCaptureDraft负责暂存；整组保存成功才持久化，取消不写入，失败保留重试内容。

## 录制生命周期

ContextRecordingProvider是可选扩展，旧插件无需实现。命令为start/pause/resume/stop/read/ack/discard，非start命令须绑定原session_id和recording_id。read不消费缓冲；持久化成功后才ack；ack失败重试确认，不重复保存已提交组。

录制期间锁定提供器、目标与请求参数，关闭弹窗暂停并保留暂存。页面重载重建控件，不向旧客户端打开对话框；旧hide不能覆盖新草稿。在途采集、活跃录制或未保存缓冲限制结束实例、删除所属对象等破坏性动作。缓冲只在当前服务/资源进程中存在，不承诺重启恢复。

## 代码与验证

- [契约](../../src/taskweave/core/context_contracts.py)、[证据与录制规则](../../src/taskweave/core/context_recording.py)。
- [ContextUseCases](../../src/taskweave/application/contexts.py)、[ContextSessions](../../src/taskweave/infrastructure/context_sessions.py)。
- [普通表单/目标](../../src/taskweave/presentation/collection_form.py)、[暂存/录制](../../src/taskweave/presentation/context_collection.py)、[步骤材料](../../src/taskweave/presentation/step_contexts.py)。
- [步骤仓储](../../src/taskweave/infrastructure/repositories/step_contexts.py)、[规划仓储](../../src/taskweave/infrastructure/repositories/plan_contexts.py)；UI在desktop/contexts.py、context_recording.py及采集组件。

测试键domain.contexts、repository.contexts、ui.contexts；检查组项顺序、过期session、目标恢复、提供器撤销、保存失败、ack重试、关闭恢复与迟到响应。
