# 当前架构与边界

TaskWeave 是本地任务与步骤自动化工作台；每人本地配置与数据，步骤可以手写或由 AI 辅助编写，验证后执行固定内容。当前能力与后续范围见 [当前状态](status.md)，日常修改从 [维护索引](maintenance.md) 开始。

## 模块化单体

```text
desktop（NiceGUI、控件与平台适配）
               ↓
presentation（普通草稿、交互决策、身份与生命周期）
               ↓
CLI / HTTP → application：操作路由、用例、编写与规划服务
               ↓
core：步骤内容、执行协议、校验、结果与仓储端口
               ↑ 实现端口
infrastructure：SQLite 仓储/UoW、worker/运行协调、模型与 HTTP 适配

插件通过统一 SDK/registry 提供动作、资源、上下文、AI 贡献和结果展示
```

| 层 | 当前职责 | 边界 |
| --- | --- | --- |
| core | 内容契约、绑定/校验、结果与仓储 Protocol | 不依赖 UI、SQL 驱动、模型 SDK 或具体插件 |
| application | 任务/步骤/环境/运行用例，规划、AI 编写、操作分发 | 不写 SQL，不持有 UI 框架对象 |
| infrastructure | 十个 SQLite 仓储、共享事务、运行协调/worker、模型与存储适配 | runtime 通过语义仓储端口持久化；不重写业务到 UI |
| presentation | 编辑、导航、规划、AI候选、补参、执行选择与查询状态 | 普通数据与应用端口；禁止导入 NiceGUI、pywebview、desktop 或 infrastructure |
| desktop | Workbench 装配页面/组件，controller 委托应用及平台适配 | 控件和事件映射留在此层；交互状态委托 presentation，组件释放其视图资源 |
| src/taskweave/plugins | SDK、发现注册、统一契约 | 不塞具体插件实现 |
| 根 plugins/ | Playwright、OCR、TiDB、utility 及其独立依赖 | 不依赖核心内部持久化和 UI |

`application/composition.py` 显式装配依赖，`application/service.py` 保留应用入口与兼容委托；`application/operations.py` 是公开操作路由与锁豁免的代码入口。旧 Repository/PlanRepository 兼容门面仍存在，实际职责分到任务、步骤、环境、运行、结果、步骤上下文、规划元数据、规划上下文、生成记录、本地收藏分类十个仓储。共享 UoW 保证需要原子性的组合写入。

`infrastructure/sqlite_storage.py` 只负责连接、迁移、UoW及路径；仓储依赖它，旧 `storage.Store`、`Repository`、`PlanRepository` 为兼容门面。运行编排、实例池和worker通信分别位于 `run_coordinator.py`、`coordinator_pool.py`、`worker_transport.py`；`runtime.py` 保留旧导入。编写和执行复用资源会话实现，Authoring经core工厂端口获取资源。

core契约按JSON值、能力声明、上下文数据、模型、运行及编写资源端口组织；ports.py保留插件运行契约和旧公开导出，旧导入与序列化类路径可解析到同一实现。data_contracts.py描述任务、步骤、运行摘要及关键执行命令形状；presentation消费者以明确操作名、参数和返回类型声明实际依赖。

替换UI时复用presentation及application，通过新适配器绑定输入、渲染动作、确认和生命周期；NiceGUI的布局、控件、原生窗口及平台行为仍需重写。当前未实现第二套UI。普通状态和实际页面共享同一交互实现，禁止GUI导入的运行测试与真实页面回归共同验证边界。

## 跨模块不变量

- 任务/步骤定义与运行/尝试、业务结果分开；前序输出按本次运行的有效成功尝试读取。
- 规划生成采用冻结上下文，导入不偷偷读取后来改变的采集数据。
- AI 响应是候选内容，经本地校验及用户采纳；固定执行路径不调用模型。
- 页面离开释放其资源，迟到响应不污染新页面；后台运行不因 UI 导航被取消。
- 控制库、任务结果库与文件不假设跨文件原子性；恢复与 UNKNOWN 处理保持显式。
- 当前格式：控制库 v17、任务结果库 v2、插件 API v1、步骤 python-async-v1、任务包 taskweave-task-2。修改格式须先核对源码及兼容策略。

各业务规则由 [模块文档](maintenance.md) 承载，完整 API/DDL 以仓储端口、SDK、路由及 SQL/迁移源码为准。旧 REQ 设计仅用于追溯，不能覆盖当前模块事实。

具体取舍、窄端口、事务组合、UI所有权及测试传播理由见 [长期架构决策](decisions/architecture.md)。详细运行与字段契约通过 [专题索引](reference/README.md) 按需进入。
