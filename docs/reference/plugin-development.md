# 插件开发与能力扩展

公开API：[sdk.py](../../src/taskweave/plugins/sdk.py)；行为验证：[registry.py](../../src/taskweave/plugins/registry.py)、[manager.py](../../src/taskweave/plugins/manager.py)。只使用公开SDK，不依赖application/infrastructure内部实现。插件是受信任本地代码，不是沙箱。

## 发现、版本与启停

在插件pyproject.toml声明：

```toml
[project.entry-points."taskweave.plugins"]
myplugin = "my_package:Plugin"
```

无参工厂返回插件，manifest.id须匹配入口。manifest包含id/package_version/api_version=1，可声明core_requires和dependencies版本范围；能力从methods/catalog派生，不在manifest重复列表。ID与能力命名空间、重复入口/动作、依赖版本/环、schema与资源引用由registry验证。

安装不等于启用；本地plugins.json保存启用集合，当前默认空，不默认注入demo/text/sample。启动加载失败隔离并保留load_errors，使用缺能力的步骤预检失败；显式配置变更严格校验、失败保留旧配置，活跃租约阻止配置变更。CLI配置需同工作空间服务关闭；服务运行用plugin.configure。

插件独立构建、依赖随插件声明；运行时不自动pip/uv安装、热更新或扫描任意目录执行。冻结包不能保证安装任意wheel。开发命令从 [插件索引](../modules/plugins.md) 进入实际包；旧sample/custom已不是当前正式包。

## 动作、工具与资源

CapabilitySpec描述id/description/input_schema/output_schema/effect/timeout_ms/retry_safe/resource_ids。preflight→execute→verify与输入输出校验由宿主调用；无异常只证明调用结束，业务成功需要断言。WRITE副作用不能靠通用click承诺幂等。

PluginContext提供固定scope、environment、本地secret resolver、日志/取消、受控allocate_file和resources；不能接受模型伪造task_id、总库连接或任意路径。ResourceProvider负责open/close，active枚举实例内活资源；对象只能留在所属worker/event loop。resource_descriptions可提供结束确认说明。

tools与actions可共享底层实现，但编写工具仅从已选能力暴露；READ可观察，WRITE进入用户明确试跑，不在生成时自动执行业务。failure_results为可选诊断钩子，失败产物不伪造成功证据。

## 编写与上下文扩展

AuthoringContribution含instructions/examples/context_provider_ids/tool_ids/constraints，以及可选channel_overrides(api/web_chat)。机器约束冲突拒绝生成，不能覆盖content_format/entrypoint；自由提示不能绕过核心规则。lint/diagnose返回结构化诊断，由统一Authoring服务调用，不另建模型服务。

collect_context返回ContextCollection(items,views)，items为证据，views为预览；ContextItem保留kind/mime_type/content/source/truncated，views为title/renderer/data。图像与文本能力须按模型适配器能力处理，不声称读取不支持的图片。

可选list_context_targets返回target_id/label/request，不创建或导航资源；目标失效不能回退。schema的x-taskweave-context-targets声明selector_label、parameter_mode_label、auto_select_single、hide_parameters_when_selected、keep_parameters_when_selected；无扩展则普通表单。x-taskweave-context-view与页面默认值由插件决定，宿主不按插件类型分支。会话ID在采集前验证，合并参数遵守表单→高级参数→目标request。

Playwright在同一实例隔离role，可枚举同角色多页面；选已有页只观察，不改变动作默认页；新建模式要求URL，创建新页面，不导航既有目标。步骤采集默认full_page、规划默认viewport，重新采集沿用原request。TiDB无此资源目标时显示schema表单。

结果handler、自定义表、视图与文件归属详见 [存储结果](persistence-results.md)。

## 实际能力包与验证

Playwright包含导航/文本/填写/点击/等待/选择/键盘/断言/截图/下载/观察/接管，selector兼容CSS及结构化role/label/placeholder/frame。应使用已观测唯一定位，DOM变化先重采集；按URL/title/输入值/业务状态断言，不仅看点击完成。无名称图片/canvas/iframe保留可验证定位范围；页面快照避免输入值、密码和cookies，文本/截图仍需隐私判断。

OCR为独立本地CPU识别，Playwright只提供通用元素图像；不联网、不自动刷新或无限重试，真实验证码准确率不能由本地fixture保证。TiDB使用MySQL协议参数化只读查询、表结构采集及展示，每次关闭连接；真实用户服务另验。utility提供时区时间、UUID和十进制计算，不开放任意import，秒级时间戳不保证业务编号唯一。

测试应覆盖缺插件、版本/环/schema、结果迁移、READ/WRITE边界、多插件贡献、角色/会话隔离和失败诊断。纯fixture与真实Chromium分开，只有显式选择浏览器才启动。
