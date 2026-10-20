# 当前能力边界

这些边界用于判断当前软件可复用到何处；不是新需求清单，也不将候选能力写成已经实现。

| 领域 | 当前边界 | 实现依据 |
| --- | --- | --- |
| 流程组织 | 任务按有序步骤执行；没有独立的条件/循环/嵌套编排节点模型。步骤内容内的允许Python控制流属于另一层 | core/validation.py、infrastructure/run_coordinator.py |
| UI | 当前为NiceGUI/pywebview；普通交互可复用，但没有第二套框架或独立远程前端协议 | presentation/、desktop/ |
| 本地服务 | HTTP仅回环访问与令牌校验，不是面向公网的多租户服务 | infrastructure/http.py、desktop/security.py |
| 请求与草稿恢复 | 编写在途请求和标签页缓存只在当前服务内；资源录制缓冲不跨服务/worker重启保存 | application/authoring_sessions.py、presentation/workspace.py、infrastructure/context_sessions.py |
| 资源 | 历史成功与资源存活无关；操作仍需核对会话、租约和实例条件 | infrastructure/coordinator_pool.py、run_coordinator.py |
| 分享 | 有任务包导入导出，不携带环境、秘密、运行历史；没有据此交付完整插件市场安装/升级流程 | application/task_transfer.py、desktop/pages/marketplace.py |
| 执行安全 | 内容校验和能力限制不等同于对任意恶意代码的完整隔离沙箱 | core/validation.py、infrastructure/worker.py |
| 平台与外部能力 | 打包脚本、注册成功及fixture通过不能证明目标平台/真实模型/外部系统验收完成 | packaging/、scripts/及对应集成测试 |

源码路径以src/taskweave/为基准。当前测试结果应在本次变更中执行和报告；本知识库不继续复制历次通过计数、未复验错误或安装状态，以免将旧证据写成现行保证。
