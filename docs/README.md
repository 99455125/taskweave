# TaskWeave 知识库

本文档集描述当前源码的产品概念、实现边界和使用方式。知识基线为当前主工程及现有插件源码；版本与约束从对应实现核对，不用需求计划或阶段验收代替现状。

## 阅读路径

| 需要了解什么 | 入口 | 内容边界 |
| --- | --- | --- |
| 软件解决什么问题、对象如何关联 | [领域模型](domain.md) | 业务语言、对象关系、生命周期及不变量 |
| 系统如何分层、关键调用如何流转 | [系统架构](architecture.md) | 依赖方向、组合入口、执行与存储边界 |
| 修改某项能力应定位哪里 | [模块导航](maintenance.md) | 模块职责、源码和测试键 |
| 字段、协议和兼容要求 | [契约索引](contracts/README.md) | 步骤、任务包、插件、操作、结果及配置 |
| 如何准备开发环境 | [开发指南](development.md) | Python/uv、源码布局和维护方法 |
| 如何选择与执行验证 | [测试指南](testing.md) | 定向测试、浏览器、映射及工程检查 |
| 如何启动、分发和保管数据 | [运行与打包](deployment.md) | CLI、桌面、本地服务、macOS/Windows构建 |
| 哪些边界需要额外实现或验证 | [能力边界](limitations.md) | 当前产品限制与验证含义 |

## 当前格式

| 项目 | 现行值 | 权威实现 |
| --- | --- | --- |
| Python / 主包 | Python ≥3.10，TaskWeave 0.1.0 | [pyproject.toml](../pyproject.toml) |
| 控制库 / 任务数据 | 各自单一现行结构 | [control.sql](../src/taskweave/infrastructure/sql/control.sql)、[task-data.sql](../src/taskweave/infrastructure/sql/task-data.sql) |
| 插件API | 1 | [registry.py](../src/taskweave/plugins/registry.py) |
| 步骤内容 | `python-async-v1` | [validation.py](../src/taskweave/core/validation.py) |
| 任务包 | `taskweave-task-3`，统一携带流程树 | [task_package.py](../src/taskweave/core/task_package.py) |

## 知识维护

领域文档定义术语，模块文档解释实现职责，契约文档说明接口，指南提供操作入口。精确签名、SQL和插件动作参数链接到源码，测试清单统一维护在tests/module-map.json，不再复制成多份清单。修改实现时同步相应事实；验证记录留在当次变更中，不累积为产品知识。

旧需求、旧设计、阶段进度、验收截图和AI协作资料已从此知识树移除；需要追溯时使用Git历史。产品内AI编写能力仍是现行软件模块。
