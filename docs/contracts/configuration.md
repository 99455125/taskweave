# 配置与本地工作空间

## 配置来源

CLI --home优先选择工作空间；否则使用TASKWEAVE_HOME，再使用平台默认路径及位置标记文件。默认位置见[运行指南](../deployment.md)，解析实现为[infrastructure/sqlite_storage.py](../../src/taskweave/infrastructure/sqlite_storage.py)。包资源不作为用户数据目录。

| 配置 | 内容和入口 |
| --- | --- |
| plugins.json | `{"format": 1, "enabled": ["plugin_id"]}`；PluginManager校验并显式启用 |
| workbench.json | 默认环境、executor_max_threads、ai_request_limit_kib、redact_on_display、redact_for_ai等；由用例更新 |
| model.json | 桌面模型连接url、model、key_env及相关本地配置；ApplicationSettings读写 |
| 数据库environment | public_config、secret_refs及descriptions，供任务/规划/资源会话使用 |
| taskweave-location.json | 平台标准目录旁的工作空间位置标记；正式迁移用例维护 |

环境secret_refs值使用`env:VARIABLE_NAME`，在本机环境解析。普通配置字符串可能持久化在本机；秘密引用、脱敏和加密是不同概念，不能将自动脱敏描述为静态加密。

独立桌面包在缺少插件配置时按包内清单初始化；已有plugins.json保留原启用选择。源码PluginManager在无配置时默认启用清单为空，不能把安装全部extras等同于启用全部插件。

## 模型与服务变量

CLI模型适配识别TASKWEAVE_MODEL_URL、TASKWEAVE_MODEL_NAME、TASKWEAVE_MODEL_API_KEY；桌面设置通过ApplicationSettings管理模型。请求预算默认2048KiB，可设置1–16384KiB。执行器并发范围1–8，不是操作系统线程/进程的总数量。

本地API服务使用TASKWEAVE_API_TOKEN或启动时生成的令牌；客户端request命令要求环境中提供该令牌。桌面入口的授权跳转/Cookie及Host、Origin校验是另一条适配链，不能混用API令牌和桌面访问参数。

## 共享边界

任务包不携带工作空间配置、账号、运行历史或资源会话。迁移、删除与环境更新须经用例检查活动依赖，不能在运行过程中手工替换数据库或配置文件。模型、插件与平台的精确配置格式以[source settings](../../src/taskweave/application/settings.py)、[PluginManager](../../src/taskweave/plugins/manager.py)及各插件Schema为准。
