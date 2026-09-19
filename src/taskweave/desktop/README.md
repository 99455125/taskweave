# desktop

可选 NiceGUI / pywebview 展示层，提供 Windows / macOS 独立工作台。launcher 仅在显式 workbench 命令调用时启动；controller 经 Application.dispatch 调用真实任务、编写和运行服务；forms 根据 schema 生成参数表单。

服务绑定回环地址，security 同时校验 HTTP 和 Socket.IO 的本次启动凭据。业务浏览器仍由核心 worker 与插件管理。

运行与平台限制见 [REQ-005 指南](../../../docs/requirements/REQ-005-local-workbench/usage.md)。
