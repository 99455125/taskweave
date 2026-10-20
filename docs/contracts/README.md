# 契约索引

契约描述当前跨层和跨包约定。类型用于表达协作，运行时仍由校验器、应用用例和注册器验证；修改前核对真实消费者与兼容入口。

| 契约 | 主要内容 | 权威源码 |
| --- | --- | --- |
| [步骤内容与绑定](steps.md) | Python入口、Schema、能力、哈希及输入解析 | core/validation.py、core/ports.py |
| [任务包](task-packages.md) | v2格式、来源、引用、采集材料与导入边界 | core/task_package.py、application/task_transfer.py |
| [插件](plugins.md) | SDK、发现、manifest、动作、资源及可选扩展 | plugins/sdk.py、registry.py、core/ports.py |
| [应用操作](operations.md) | 请求/错误、路由、参数、异步与锁 | application/operations.py、infrastructure/http.py |
| [结果与展示](results.md) | StepResult、handler、引用、views及持久化 | core/ports.py、core/result_views.py、infrastructure/storage.py |
| [配置与工作空间](configuration.md) | 插件/模型/环境、秘密引用与路径 | application/settings.py、ai_requests.py、infrastructure/sqlite_storage.py |

源码路径以src/taskweave/为基准。返回JSON中的插件扩展字段保留开放性；不要为消除开放字段而复制插件Schema。旧公开导出与正常规范模块的关系见[架构](../architecture.md)。
