# 宿主插件入口

sdk.py是插件公开导入入口，manager.py负责entry point发现与显式启用，registry.py校验并注册能力。具体插件位于根目录plugins/，不在宿主层维护其实现和可选依赖。

见[插件模块](../../../docs/modules/plugins.md)与[SDK契约](../../../docs/contracts/plugins.md)。
