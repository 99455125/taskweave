# application

用例、应用服务与公开操作路由。composition.py显式装配依赖；service.py提供Application及兼容转发；operations.py集中声明handler、异步与锁策略。用例不持有GUI对象，不直接写SQL。

从[模块导航](../../../docs/maintenance.md)定位业务，[系统架构](../../../docs/architecture.md)说明依赖，[操作契约](../../../docs/contracts/operations.md)列出现行调用入口。
