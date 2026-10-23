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

## 采集表单布局

插件在 `manifest.context_requests[provider_id]` 的请求 Schema 中可声明
`x-taskweave-context-form.rows`。每个数组表示一行；单元格是字段名，或
`{"field": "字段名", "width": 2}`。width 是 1–12 的整数宽度比例，默认 1。
字段顺序、换行和比例由插件声明；控件类型仍由参数 Schema 决定，颜色、内边距、字号、
焦点状态与窄屏单列由桌面统一渲染，不加载插件 HTML/CSS 或执行界面代码。

```json
{
  "type": "object",
  "properties": {"table": {"type": "string"}, "database": {"type": "string"}},
  "required": ["table"],
  "x-taskweave-context-view": {"default": true},
  "x-taskweave-context-form": {
    "rows": [["$provider", "$session", {"field": "table", "width": 2}, "database", "$preview"]]
  }
}
```

保留字段 `$provider`、`$session`、`$target`、`$preview` 分别代表采集器、步骤观察会话、
已有目标选择与生成预览选项。仅在对应页面及能力可用时出现，不进入采集请求；
规划没有 `$session`，不支持目标或预览的提供器不会产生对应空位。已有目标隐藏的
请求参数也从排版中移除；余下字段按各自比例使用该行空间。

同一声明由规划和步骤共用。遗漏的参数仍自动追加，遗漏的宿主选择器放在表单上方；
未声明布局的旧插件自动排列普通参数，数组/对象单独成行，无参数时只显示宿主控件。
重复/未知字段、空行和非法宽度在渲染时报告 `CONTEXT_FORM_LAYOUT_INVALID`，不会静默漏掉输入。
该可选展示扩展不改变插件 API 版本、采集请求校验与执行接口；共享动作 Schema 不因采集排版而修改。
