# 上下文与资源会话

## 职责

为步骤编写、规划及调试提供结构化证据和可选预览，管理有序采集项与可选录制。持久化材料与活跃资源会话分开；材料存在不能证明浏览器或连接仍存活。

## 数据和选择

上下文组归属步骤或规划，拥有provider_id、名称、说明与顺序；组内采集项保存request、items、views、时间、来源、操作说明和send_preview。ContextCollection以items表示证据、views表示用户预览；include_view决定是否采集预览，send_preview另行决定是否将其发给模型。

目标枚举只列出现存资源，不因打开选择器新建浏览器。请求带expected_session_id时必须匹配原资源身份。独立步骤会话、规划会话和保留运行worker会话分开，历史运行记录不能替代活跃会话。

步骤“采集上下文”入口会显示可处理的业务错误；未选择可采集插件时提示“请选择可采集的插件”，不再只在后台抛错。原录制的停止/丢弃权限仍按保留会话处理。

CollectionForm持有提供器、运行选择、动态Schema原始输入和高级参数；TargetSelection持有目标/session选择及请求代次。步骤与规划UI共用这些状态，采集和录制读取普通草稿。ContextCaptureDraft负责暂存；整组保存成功才持久化，取消不写入，失败保留重试内容。

## 查看采集内容

采集暂存卡片与已保存卡片均通过“查看上下文”打开同一只读查看器，步骤和规划共用，不依赖 AI 请求。查看器默认打开“采集数据”，另有“截图与预览”和“原文”页。

页面元素按名称、类型、可见/可用状态和定位器分页展示；录制动作按顺序、动作、目标和定位器展示。列表支持筛选，点击一行查看完整属性、参数、候选定位器及可复制的定位器。页面 frame 单独分组；其他插件的结构化字段按可展开、可查找的字段树展示，纯文本保持可读。原文页保留原始 items 的复制入口。查看过程沿用显示脱敏设置，不改写已采集材料、send_preview 或步骤代码；预览截图仍由插件 renderer 提供。

## 录制生命周期

ContextRecordingProvider是可选扩展，旧插件无需实现。命令为start/pause/resume/stop/read/ack/discard，非start命令须绑定原session_id和recording_id。read不消费缓冲；持久化成功后才ack；ack失败重试确认，不重复保存已提交组。

录制期间锁定提供器、目标与请求参数，关闭弹窗暂停并保留暂存。页面重载重建控件，不向旧客户端打开对话框；旧hide不能覆盖新草稿。在途采集、活跃录制或未保存缓冲限制结束实例、删除所属对象等破坏性动作。缓冲只在当前服务/资源进程中存在，不承诺重启恢复。

## 代码与验证

- [契约](../../src/taskweave/core/context_contracts.py)、[证据与录制规则](../../src/taskweave/core/context_recording.py)。
- [ContextUseCases](../../src/taskweave/application/contexts.py)、[ContextSessions](../../src/taskweave/infrastructure/context_sessions.py)。
- [普通表单/目标](../../src/taskweave/presentation/collection_form.py)、[暂存/录制](../../src/taskweave/presentation/context_collection.py)、[步骤材料](../../src/taskweave/presentation/step_contexts.py)。
- [步骤仓储](../../src/taskweave/infrastructure/repositories/step_contexts.py)、[规划仓储](../../src/taskweave/infrastructure/repositories/plan_contexts.py)；UI在desktop/contexts.py、context_recording.py及采集组件。

测试键domain.contexts、repository.contexts、ui.contexts；检查组项顺序、过期session、目标恢复、提供器撤销、保存失败、ack重试、关闭恢复与迟到响应。

## 录制与本地生成共用材料

Playwright 在既有 `playwright.recording` 项内附带版本化 codegen 证据；旧 events 与保存成功后 ack 的规则保留。生成证据包含归一化操作、角色/主页面、执行起点、源文档发送确认及完整性问题。只有停止且源回执完整的受支持操作可供本地生成；旧录制、暂停、导航失联、额外页面、不支持交互或截断仍可作为 AI 编写证据，但不会生成可应用的残缺步骤。

本地生成只读保存的 capture，原浏览器关闭后仍可使用。源值在浏览器侧脱敏；默认不以页面摘要重新导航，也不把观察值自动转成业务断言。实现入口为 [录制生成证据](../../plugins/playwright/src/taskweave_playwright/recording_codegen.py) 与 [生成器](../../plugins/playwright/src/taskweave_playwright/codegen.py)。

## 条件分支保留会话

允许并行的条件路径使用独立分支 worker，首个匹配模式沿用当前资源会话。暂停、失败或需核对时，运行上下文来源逐一列出仍存活的分支会话；同一 run_id 下按 session_id 和 execution_path 定位当前步骤的真实资源。采集、目标读取和录制均转交对应 worker，并校验过期身份。嵌套分支执行期间保留外层路径自身的会话，内层路径独立建立资源。旧轮次路径不能冒用当前轮次的页面；应用重启后已丢失的会话不会由历史记录自动重建。

录制新地址时，新建资源直接导航初始主页面；已有会话仅复用未使用的空白主页面，有 DOM 内容或实际地址的原页面保留，选已有 target 不开页、不导航。新保存的 target_mode 区分主页面和所选页面，非默认页面不再单独导致生成失败；录制中额外开页、缺失操作等完整性问题仍照常检查。

## 材料移动与复制

采集项及组菜单提供移动、复制，可在弹窗多选采集项，选择同任务的其他步骤、已有同采集器组或新组。移动保留采集项身份，复制创建独立身份；内容、预览、请求、说明、发送预览选择、采集时间和来源会话元数据保留。源组与目标组版本在事务内核对，失败整体回滚；界面阻止覆盖未处理的采集草稿。步骤跨任务复用另外复制所选来源步骤的全部组和材料，不转移来源历史。
