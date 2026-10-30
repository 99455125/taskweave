# 当前能力边界

这些边界用于判断当前软件可复用到何处；不是新需求清单，也不将候选能力写成已经实现。

| 领域 | 当前边界 | 实现依据 |
| --- | --- | --- |
| 流程组织 | 步骤和任务组合支持结构化条件、遍历、循环及嵌套；条件可选择全部命中路径并行并等待成功汇合。未提供任意跳转、break/continue、组合调用组合或跨分支共享活跃资源 | core/task_flow.py、core/sequence_flow.py、infrastructure/parallel_flow_runner.py、application/sequence_driver.py |
| UI | 当前为NiceGUI/pywebview；普通交互可复用，但没有第二套框架或独立远程前端协议 | presentation/、desktop/ |
| 本地服务 | HTTP仅回环访问与令牌校验，不是面向公网的多租户服务 | infrastructure/http.py、desktop/security.py |
| 请求与草稿恢复 | 编写在途请求和标签页缓存只在当前服务内；资源录制缓冲不跨服务/worker重启保存 | application/authoring_sessions.py、presentation/workspace.py、infrastructure/context_sessions.py |
| 资源 | 历史成功与资源存活无关；操作仍需核对会话、租约和实例条件 | infrastructure/coordinator_pool.py、run_coordinator.py |
| 分享 | 有任务包导入导出，不携带环境、秘密、运行历史；没有据此交付完整插件市场安装/升级流程 | application/task_transfer.py、desktop/pages/marketplace.py |
| 执行安全 | 内容校验和能力限制不等同于对任意恶意代码的完整隔离沙箱 | core/validation.py、infrastructure/worker.py |
| PDF | 仅从纯文本新建 PDF，支持随包字体覆盖的中文、自动折行分页；不读取或修改已有 PDF，不支持的字符明确报错 | plugins/pdf/src/taskweave_pdf/ |
| 内部数据集 | 有界不可变表格与SQL处理，引用限定同任务/运行及有效输入；不提供跨运行共享可变表或数据编辑器 | core/dataset_contracts.py、infrastructure/datasets.py、dataset_sql.py |
| Excel | 支持.xlsx读取、新建和普通表格/模板区域写入；复杂对象工作簿拒绝修改，不支持.xls、宏或公式计算；公式值依赖已有缓存 | plugins/excel/src/taskweave_excel/ |
| 平台与外部能力 | 打包脚本、注册成功及fixture通过不能证明目标平台/真实模型/外部系统验收完成 | packaging/、scripts/及对应集成测试 |

源码路径以src/taskweave/为基准。当前测试结果应在本次变更中执行和报告；本知识库不继续复制历次通过计数、未复验错误或安装状态，以免将旧证据写成现行保证。
