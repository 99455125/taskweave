# 模块边界与兼容设计决策

本记录保存已经实施的设计理由；当前模块入口见 [维护索引](../maintenance.md)。不是再执行一次拆分的实施计划。

## 模块化单体和仓储

保留core/application/infrastructure/desktop分层、Python/SQLite及现有JSON DTO。用窄端口和显式组合降低耦合；不为目录拆分引入ORM、事件总线、DI框架、新服务或巨大mixin。仓储围绕业务一致性，不能仅把SQL按表搬到自由CRUD工具中。

九个仓储分管tasks、steps、environments、runs、results、step_contexts、plans、plan_contexts、plan_generations。规划三个对象分别有实现与实际调用方；任务/步骤跨对象操作共享UoW，避免拆分后复制/导入留下半成品。SQL资源及schema升级由基础设施统一负责。

[核心端口](../../src/taskweave/core/repositories.py)包含消费者实际需要的方法、参数种类/默认值、返回类型；禁止泛型*args包装伪装兼容。基础设施内部窄协作类型保留在 [collaboration.py](../../src/taskweave/infrastructure/repositories/collaboration.py)，不把SQLite细节放进core。

装配在build_sqlite_repositories：环境→步骤→步骤上下文→任务等按依赖构造；结果用TaskLockGuard，规划复制用PlanContextCopier，revision用共享纯函数。必需依赖构造时注入，不用None回填、ServiceLocator或完整Store互相调用。细节以 [装配](../../src/taskweave/infrastructure/repositories/__init__.py) 为准。

## 用例、运行与兼容

Application是装配/调度/生命周期门面，用例依赖具体窄端口。Authoring、Planning不持有整个Application或巨型Repository；Planning使用公开TaskUseCases方法、显式步骤/上下文端口及plan_files_root，不能穿透tasks.steps或仓储私有root。

运行协调器保留原worker/租约/幂等/恢复算法，持久化经RunRepository语义操作，定义和结果经对应端口；不能用execute(sql)泛型包装绕过边界。DesktopController经应用查询，不直接application.repo。core不能依赖UI、模型SDK或数据库驱动。

Repository、PlanRepository、Store及既有导入路径保留显式兼容委托；保留路由名、同步/异步/锁豁免、默认值及JSON返回形状。run.get保留原request_json但不新加顶层inputs_json。架构重构不授权删字段、改变隐私策略或迁移schema；这些行为变更须另行设计。

## UI组合和行为守卫

连续采集改为弹窗批量提交后，导航不得再调用已删除的ContextCards.save_all；补空方法会掩盖未保存问题。

状态归属及异步规则详见 [桌面契约](../reference/desktop.md)。组件拥有实际渲染、状态、保存及生命周期，Workbench只装配/导航/兼容委托；禁止反向同步view handles以保留共享大对象。局部组件测试要跑真实回调入口、重复确认、串行保存、失败草稿、迟到结果及dispose；装配/轮询变化补真实浏览器验证。

依赖守卫应检查不同变量名/访问链形式及真实入口，不只匹配旧字符串；例外精确到必要适配，不整目录豁免。端口替身验证可替换性；回滚测试必须在真实中途写入后失败，不能让递归mock在第一步之前就报错。冻结审核对象必须包含工程检查需要的SQL、资源和被链接记录。

## 测试边界

唯一机器映射为 [module-map.json](../../tests/module-map.json)。depends_on表示消费者→前置模块；源码变更沿反向传递闭包选消费者，模块之间不能凭想象补边。仓储实际依赖涵盖steps→environment、contexts→steps、tasks→steps/contexts、results→tasks、runs→任务/步骤/环境/结果、planning→contexts。

应用层映射按构造实参和调用核对：authoring及runs各消费实际五仓储，runs还依赖authoring；steps/tasks/environments/planning分别登记实际用例、仓储和runtime边。operations覆盖所有受影响用例；context_sessions同时映射运行、规划、环境实际消费者。共享端口变化不能只测端口本身。

按实际执行区分fast/browser：真实Chromium选择与图像定位属于显式browser，替代对象的target测试仍fast。去重到实际unittest ID，不仅target字符串；未知源码/模块/空选择报错。domain.*是逻辑边界，可复用原测试，不为形式创建空tests/domain或丢旧断言。不分组拼全量，任何全量运行仍需用户明确确认。
