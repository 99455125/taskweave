# 插件系统

## 宿主与包边界

根目录plugins/是独立插件包，src/taskweave/plugins/提供SDK、发现、注册及启用管理。宿主通过`taskweave.plugins` entry point发现已安装包，只加载当前工作空间显式启用的工厂；安装、发现、启用和具备外部工具条件是不同状态。

PluginManager管理plugins.json，Registry校验manifest、API版本、包/主工程版本要求、依赖、能力与唯一标识。插件通过taskweave.plugins.sdk导入宿主契约，不直接依赖application、desktop、数据库内部或worker。可选依赖不进入核心默认安装。

## 当前插件

| 插件 | 能力范围 | 主要组织 |
| --- | --- | --- |
| [playwright](../../plugins/playwright/README.md) | 浏览器动作、结构化观察、上下文/录制、截图/文件结果 | session、locators、browser_actions、context、results、plugin及共享schema |
| [ocr](../../plugins/ocr/README.md) | 本地图片识别 | 单动作与线程/模型生命周期，依赖按使用加载 |
| [tidb](../../plugins/tidb/README.md) | 数据库执行、查询证据与结果 | database共享配置/查询，execution动作 |
| [nacos](../../plugins/nacos/README.md) | Nacos 配置读取、批量发布与 JSON/YAML 字段操作 | 客户端、动作及合并策略 |
| [utility](../../plugins/utility/README.md) | 时间、UUID、精确金额 | 小型独立动作 |
| [dataset](../../plugins/dataset/README.md) | 内部数据集创建、结构、分页读取、SQL查询与修改副本 | 动作委托宿主 datasets 端口，数据随步骤结果提交 |
| [excel](../../plugins/excel/README.md) | XLSX工作表读取、新建、区域写入与数据集导出 | files、workbooks及动作，显式依赖dataset |
| [pdf](../../plugins/pdf/README.md) | 纯文本 PDF 创建、中文字体、自动折行分页 | creation、随包字体与动作 |
| [file](../../plugins/file/README.md) | 有界本地文件读取 | 路径约束、读取与动作 |
| [process](../../plugins/process/README.md) | 进程、诊断、受控文件与资源 | runner、session、artifacts、context、actions |
| [ssh](../../plugins/ssh/README.md) | 连接、远端命令与文件传输 | transport、paths、transfer、actions、context |
| [baota_dashboard](../../plugins/baota_dashboard/README.md) | 宝塔接口与管理动作 | endpoints、client、actions、context |
| [wordpress](../../plugins/wordpress/README.md) | WordPress命令、备份与站点操作 | commands、transport、backup、actions、context |
| [uniapp](../../plugins/uniapp/README.md) | 工程、构建、测试与原生工具租约 | project、build、tests、lease、redaction、actions |
| [wechat_dev](../../plugins/wechat_dev/README.md) | 模拟器、截图、预览上传与CI发布 | configuration、bridge、capture、qrcode、release、actions |

插件动作和参数以各包能力声明/Schema为准；这里不复制全量动作清单。process、ssh等被复用的普通库依赖在各插件pyproject.toml显式声明，不跨越宿主资源所有权。

## 生命周期与结果

动作按preflight→execute→verify协作；资源由provider打开/关闭，宿主按运行/会话拥有其生命周期。上下文目标枚举及录制是独立可选扩展。ResultHandler声明准备、Schema、解析和预览，宿主完成存储；插件不接管任务控制库。

SDK公开入口、旧entry point及已使用序列化类路径保持兼容。Playwright包入口保留显式重导出，具体实现只在职责模块维护。插件集成或类移动时必须核对多进程与冻结包收集。

## 验证定位

shared.contracts、对应plugins.*；核对发现/显式启用、API/版本约束、可选依赖隔离、SDK边界、结果契约和资源清理。动作依赖浏览器、SSH、数据库、构建工具或外部账号时，协议替身通过不能代表真实目标可用。开发接口见[插件契约](../contracts/plugins.md)。

本地代码生成是独立可选扩展：当前只有 Playwright 声明，宿主根据 catalog 与当前步骤草稿选择显示入口。它消费保存的录制上下文，输出受校验的 TaskWeave 候选；不改变固定动作调用或其他插件的必选接口。契约见[插件协议](../contracts/plugins.md)。
