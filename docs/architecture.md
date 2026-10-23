# 系统架构

## 模块化单体

TaskWeave是单一Python工程。CLI、本地HTTP和桌面工作台调用同一应用用例；插件以独立包扩展能力。控制与业务数据在本机，固定执行无需模型服务。

```text
NiceGUI / pywebview → desktop → presentation → application → core契约
CLI / 本地HTTP ─────────────────────────────→ application
                                                    ↑ 注入实现
infrastructure → core契约：SQLite、worker、资源会话、模型适配
独立插件 → plugins/sdk → core运行/扩展契约
```

图中的注入由application/composition.py显式完成；这是组合入口，允许选择具体基础设施。其余用例通过语义端口协作，避免将SQL或UI对象透传进用例。

| 层 | 职责 | 主要入口 |
| --- | --- | --- |
| core | 步骤/Schema校验、JSON与业务记录、运行/资源/仓储端口、结果与上下文契约 | [core](../src/taskweave/core) |
| application | 任务、步骤、规划、编写、上下文、环境、组织、设置与运行用例，公开操作分发 | [composition.py](../src/taskweave/application/composition.py)、[operations.py](../src/taskweave/application/operations.py) |
| presentation | 普通草稿、选择、导航决策、请求忙状态、身份与迟到响应、恢复及轮询策略 | [presentation](../src/taskweave/presentation) |
| desktop | 外壳、页面/组件装配、控件输入与渲染、计时器、文件/窗口/剪贴板适配 | [workbench.py](../src/taskweave/desktop/workbench.py)、[launcher.py](../src/taskweave/desktop/launcher.py) |
| infrastructure | SQLite仓储/UoW、进程通信、运行协调、资源会话、本地HTTP、模型与隐私适配 | [infrastructure](../src/taskweave/infrastructure) |
| plugins | 宿主SDK/发现/注册；根目录下十一插件及各自可选依赖 | [SDK](../src/taskweave/plugins/sdk.py)、[插件目录](../plugins/README.md) |

## 桌面交互

输入事件先更新presentation普通状态，再由动作调用应用用例，结果更新状态并呈现。Workbench管理外壳及装配，页面/组件保留控件与视图资源；状态不会反向保存框架客户端或控件树。EditorSession处理保存串行与冲突，WorkspaceNavigation处理离开选择；规划、AI、采集、补参及运行创建分别拥有自己的交互会话。

请求开始时记录页面/任务/步骤/运行及代次；响应回来后由交互层判断是否仍应接纳。共享AI请求由应用会话跨Controller保留；dispose释放UI资源并使旧响应失效，不取消已接受后台工作。将来替换UI可复用presentation和application，仍须实现新布局、事件与平台适配；跨进程前端需要另行定义通信会话。

## 执行与资源

外部 AI 通过 integration 的可选 MCP/function calling 适配进入 application/agent；发现、材料、执行回执和验收复用原任务/运行用例。工作台及 serve 的 agent 端点共享当前 Application，私有连接描述符提供实例校验。默认核心安装不引入 MCP SDK；查询、固定执行和证据核对不调用模型。详见[外部 AI 模块](modules/agent.md)。

`RunUseCases → CoordinatorPool → Coordinator → WorkerTransport → worker → 插件动作`。含控制节点的任务由Coordinator调用FlowRunner推进流程树；纯线性任务保留现有顺序路径。流程决策在core/flow_machine.py完成，执行游标和每轮实例由FlowRunRepository持久化。

实例池选择调试/正式运行实例并控制容量；Coordinator持有运行编排与锁，通过窄查询/事件/租约/写入端口更新持久状态；WorkerTransport负责进程与管道生命周期，worker校验并执行步骤。调试资源按任务复用，正式资源按运行隔离。命令回执、租约与尝试有效性由持久化事实约束，不依赖页面内存。

任务组合由SequenceUseCases与SequenceDriver推进：先保存组合运行和当前节点的子运行关联，再提交普通运行的启动命令。组合操作使用每次组合运行的锁及持久化控制命令，与CoordinatorPool的锁保持一致的调用方向；启动恢复读取已保存的节点、命令与子运行事实，避免重复外部动作。

编写通过core/authoring_ports.py的资源工厂注入基础设施会话；固定执行与编写可复用资源实现，但AI提示/模型策略仅在编写路径。独立采集会话与保留worker会话有明确身份，不因历史记录存在而重建或冒用活跃资源。

## 持久化与兼容

SQLiteStorage负责连接、路径、迁移和UoW，十一个仓储负责任务、步骤、环境、运行、结果、步骤上下文、规划、规划上下文、生成记录、分类收藏和任务组合。业务事务通过共享UoW组合，不按表机械拆分事务。

控制库、任务数据与文件不是跨文件原子事务；回执、结果引用、清理和恢复逻辑负责其一致性边界。具体布局见[存储模块](modules/storage.md)。

兼容入口只显式转发同一实现：storage.Store、Repository/PlanRepository、runtime.Coordinator/CoordinatorPool、core.ports公开类及旧desktop.planning/chat/dependencies导出。正常消费者使用规范模块，公开插件SDK、序列化类路径和打包入口保持兼容，不能直接删除聚合入口。

## 依赖约束

core不依赖GUI、数据库驱动、浏览器或模型SDK；presentation不导入desktop、NiceGUI、pywebview或具体基础设施；core/application不反向依赖presentation。插件只通过宿主SDK协作，可选依赖不进入核心默认安装。工程守卫与实际消费者测试共同验证这些边界，入口见[测试指南](testing.md)。
