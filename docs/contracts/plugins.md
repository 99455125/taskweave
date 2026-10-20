# 插件SDK与扩展协议

插件使用[taskweave.plugins.sdk](../../src/taskweave/plugins/sdk.py)作为宿主公开入口。实现类以独立包的`taskweave.plugins` entry point注册，当前api_version为1。

## 声明与注册

manifest提供插件ID、package_version、API及主程序版本兼容信息，Registry校验标识、版本、依赖和能力唯一性。步骤plugin_requirements核对所需插件版本，capabilities限定允许动作。已安装包的entry point可被发现；plugins.json决定当前工作空间是否加载，二者分开。

## 接口职责

| 接口 | 职责 |
| --- | --- |
| Plugin | manifest、actions、tools、result_handlers、resource_providers、authoring、collect_context、lint、diagnose |
| Action / CapabilitySpec | 输入输出Schema与动作声明；preflight、execute、verify |
| PluginContext | scope、环境与任务参数、资源获取、日志、取消、秘密解析和文件分配 |
| ResourceProvider | 在宿主拥有的会话中open/close资源 |
| ResultHandler | 声明Schema、prepare、parse、preview，存储IO由宿主完成 |
| AuthoringContribution | 能力说明、提示材料与渠道贡献 |
| ContextTargetProvider | 可选枚举已有资源目标，不隐式创建资源 |
| ContextRecordingProvider | 可选录制命令；旧Plugin无需强制实现 |

基础运行协议位于[core/ports.py](../../src/taskweave/core/ports.py)，能力/上下文/模型类分别位于capability_contracts.py、context_contracts.py、model_ports.py；旧ports和SDK重导出同一类。移动类时须保留已有导入和pickle解析路径。

## 实现约束

宿主核心不安装插件的可选依赖；插件只导入SDK或声明依赖的普通插件库。结果引用、任务数据库和资源所有权仍由宿主管理。固定动作不得因插件声明了AI贡献而自动调用模型。外部动作的副作用状态和清理错误必须保留，不能吞掉异常伪装成功。

新增插件需要注册与契约测试、module-map源码覆盖；涉及资源/进程/冻结包时另验证真实生命周期和包收集。具体包入口见[插件模块](../modules/plugins.md)。
