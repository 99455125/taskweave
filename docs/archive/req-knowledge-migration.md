# REQ 完整知识迁移台账

迁移日期：2026-09-26。范围：REQ-001至REQ-010的82份作者维护文件（75份Markdown、3份Python、2份SQL、2份JSON；实际清点见下表），不包含生成的__pycache__。需求档案索引另行更新，不算原始来源。

本次迁移的是后续工作必需的知识，不是把历史文档换个目录整份复制。现行事实写模块/契约，长期取舍写架构决策，未实现范围及验收写路线/发布清单，旧命令输出、审核签字、时间线及临时快照路径保留原处。日常维护无需打开REQ；追溯当时要求、某次测试输出或签署才回查。来源hash只是防止遗漏和误改的辅助，不能代替语义核对。

## 完整性口径

- 82个来源均有下表明确去向；本轮不改动这些原始文件。
- 大文件按主题合并且核对现行源码，过时结论不原样升级为规范；重复规则只保留一个现行事实入口。
- 模块摘要连接按需专题，专题直接连接实现；没有把“详见REQ”作为现行契约的必要阅读路径。
- 历史已通过次数不搬成当前通过，未交付候选仍是待办；没有实施业务功能或运行功能回归。

## 主要内容覆盖

| 来源内容 | 现行承接及处理 |
| --- | --- |
| 001需求池/路线/候选/整体验收 | roadmap保留分享、Windows、控制流、图形及候选；release-checklist保留主流程、异常、团队交付场景；旧按编号执行顺序退出当前指令 |
| 002设计§1–6 | architecture/decisions保留本地单体、分层与技术选择；persistence-results保留旧字段/数据不自动迁移；runtime替代单活跃假设 |
| 002步骤§1–5 | step-content保留字段、入口、绑定、hash/确认；authoring保留ModelPort、工具预算、候选与用户采纳；跨环境完整反馈包仍为后续范围 |
| 002插件/运行/存储全文 | plugin-development、runtime、persistence-results承接发现、schema、生命周期、幂等、UNKNOWN、跨介质receipt、插件表迁移与清理；签名以当前SDK/端口为准 |
| 002贯穿示例、3份contract、4份example | step-content提供当前动作/完整截图对象示例；其他专题连实际SDK/端口/SQL+迁移。旧设计样本保留为历史，不作为现行DDL或可复制安装配置 |
| 003设计/范围/存储/使用 | step-content、runtime、persistence-results、api-and-configuration、authoring覆盖当前定义、绑定、分阶段补录、崩溃恢复、变量、历史和接口；过期schema/输入顺序已纠正 |
| 004设计/AI扩展/结果/使用 | plugin-development覆盖独立注册、贡献、资源、预检/验证；contexts覆盖目标枚举、schema、会话及预览；authoring覆盖渠道；persistence-results覆盖views及截图引用 |
| 005初期设计/原型/启动 | desktop维护现行交互和组件；deployment/API配置维护启动与凭据；windows-portable保留独立窗口的平台硬门槛 |
| 005使用/进度中的模型与日志调整 | authoring/API配置覆盖密钥落盘、TLS、连接测试、历史轮次/容量、网页解析、修复上下文；desktop覆盖日志窗口/轮转/正文边界 |
| 005变量/依赖/调试/重跑/补录/默认环境 | step-content、runtime、desktop、API配置覆盖输入优先级、保留草稿、请求去重、原运行续启、同run起点重跑、环境及结束资源 |
| 005按钮/结果/显示名称/分享/清理 | desktop保留现行布局与状态显示；persistence-results保留声明式视图；task-sharing保留v2/导出/复制；任务模块和runtime保留清理作用域 |
| 005规划与上下文09-19至09-25演进 | planning模块、contexts、task-sharing保留修订、冻结证据、空代码草稿、组项持久化、连续弹窗、懒加载、顺序/撤销、图片保真、独立隐私开关及采集范围 |
| 006全部范围/验收/实施顺序 | task-sharing说明已有JSON能力；roadmap保留zip/manifest、角色映射、离线依赖、敏感信息/路径检查及非目标，不照抄“未开始” |
| 007范围/设计/平台打包 | windows-portable与release-checklist保留完整目标约束、构建流程、数据与升级、实机门槛，status保留未验收事实 |
| 008与009全部设计/验收 | roadmap逐项保留结构化条件/循环/子任务语义、边界、错误/恢复、图形同模型/独立布局、稳定ID、兼容升级与验收，不写成已有能力 |
| 010设计§1–7 | decisions保留渐进拆分取舍、九仓储/UoW、兼容、UI所有权与测试传播；阶段进度不作为新任务指令 |
| 010设计§8–9、§11–15 | decisions、desktop、contexts、API配置保留清理过期save_all的原因、显式端口构造、签名/返回值、内部协作、冻结规划、run.get兼容、输入草稿与排队hash |
| 010设计§16–17 | desktop/contexts/runtime保留真实入口防重、旧弹窗提交前身份、补录提交后原运行续启；decisions/testing保留实际消费者闭包、ID去重及fast/browser分类 |
| 010设计§10/16中的调度，计划/进度/审核/终验 | 调度异常、人员ID、临时路径/manifest和逐轮签字保留原档案；通用审核经验提炼至decisions/testing，最终状态及已知失败留status |
| 各REQ README/plan/code-mapping/progress/validation重复项 | 行为和范围合入上述主题；入口转maintenance/modules，验收方法转testing/release-checklist；原命令输出、时间、版本和勾选只保留历史证据 |

## 已纠正的历史冲突

| 历史描述 | 迁移后的处理 |
| --- | --- |
| 单全局活跃会话/不支持多运行 | 当前按task调试、按run执行，池1–8默认8；不排队 |
| AI64/128KiB或自动删到两轮 | 当前默认2048KiB、上限4096，所选历史不应静默缩减；保留已知失败 |
| 总库v1/v2/v4/v12、父上下文单载荷 | 控制库14/任务库2；初始SQL+迁移；组项分离 |
| taskweave-task-1、全部导入已验证 | 当前v2，来源区分ai_generated与task_export，确认状态按当前规则 |
| 环境修改使步骤确认失效 | 环境不是步骤确认条件；已创建运行仍核对定义快照 |
| 步骤默认值优先级在环境后 | 当前实际合并环境→任务→步骤默认→绑定/独立试跑→step_inputs |
| 仅env引用、所有输入都无秘密 | 本地普通值允许，实际输入可保存；脱敏是独立边界，包不自动无秘密 |
| key仅会话保存 | model.json本地落盘，留空保留同地址，换地址不继承 |
| 采集离页丢失/卡片自动save_all | 持久化组项；弹窗确认单批事务，取消不写，摘要懒加载 |
| 图片统一截断/预览即AI证据 | 完整Base64、无像素脱敏，views不自动进AI |
| 旧三栏/五标签、全局Workbench状态 | 现行编辑器/抽屉与独立执行入口，组件拥有状态与dispose |
| 所有UNKNOWN一律无例外/核对必填说明 | 普通UNKNOWN先核对；明确确认的保留会话调试重试保留证据，核对说明可选 |
| 超时宽限5秒、重跑总新建run | 当前1秒；restart可同run从指定起点重跑，重置可能删除范围内旧attempt |
| 所有保存文件自动成为结果标签 | 仅views声明生成标签，未落盘旧staging引用不可恢复 |
| 示例默认启用、--extra sample、旧check_req命令必跑 | 以当前pyproject/plugins配置和测试映射为准；默认启用空集合 |
| REQ-006/007仍统一“未开始” | JSON分享与Windows构建工程已有，完整离线分享/目标实机验收未完成 |
| 所有REQ同步/所有设计全文必读 | AGENTS→maintenance→受影响模块/专题；原档案只作追溯 |

## 历史证据的处置

002模拟检查只验证设计样例/DDL，不能代替产品worker或真实浏览器。003/004/005历次测试有重叠且版本不同，不累加为本轮覆盖数。010最终签署为2026-09-25的DDD A/B/C/D及架构师终验；366个唯一测试ID是当时映射加载统计，不是全量运行通过。原日志/签字/冻结hash保留原路径，不伪造新验收。

仍保留web_chat容量基线失败、Windows目标实机未验证、真实模型账号/内网业务不等于fixture通过。当前限制统一在status；本轮只有文档验证，结果见 [迁移验证记录](2026-09-26-knowledge-migration-result.md)。

## 逐文件来源与去向

表中“证据留档”表示该文件的历史输出保留，长期行为已经迁入所列专题；不是留下待迁移知识。hash为迁移前后同一份来源内容的SHA-256。

| 原始文件 | 处理 | 当前知识去向 | SHA-256 |
| --- | --- | --- | --- |
| [REQ-001-requirement-pool/README.md](../requirements/REQ-001-requirement-pool/README.md) | 现行知识提炼；旧措辞留档 | [后续范围](../roadmap.md)、[发布验收](../release-checklist.md)、[架构决策](../decisions/architecture.md) | `8a8bb502d7b8b9a6c8b3af0b845c9b6eda3f2caf7bc99db37aea0b5ef0a5f365` |
| [REQ-001-requirement-pool/acceptance.md](../requirements/REQ-001-requirement-pool/acceptance.md) | 现行知识提炼；旧措辞留档 | [发布验收](../release-checklist.md)、[后续范围](../roadmap.md) | `60a5b170c0b2d9f5342f81d8ce28e3d16d12d27fe1be6e80d268d75bacc19d73` |
| [REQ-001-requirement-pool/backlog.md](../requirements/REQ-001-requirement-pool/backlog.md) | 现行知识提炼；旧措辞留档 | [后续范围](../roadmap.md)、[当前限制](../status.md) | `68742bde2b83eedab53a0e7d96dc780a942e604d718433ceca2f1ca87374553c` |
| [REQ-001-requirement-pool/future-ideas.md](../requirements/REQ-001-requirement-pool/future-ideas.md) | 现行知识提炼；旧措辞留档 | [后续范围](../roadmap.md) | `775bafd9ad71629cf52ab873221d0ed4f88a7ba540557eca64f26f64245b1fa5` |
| [REQ-001-requirement-pool/progress.md](../requirements/REQ-001-requirement-pool/progress.md) | 行为/限制提炼；历史证据留档 | [后续范围](../roadmap.md)、[发布验收](../release-checklist.md)、[架构决策](../decisions/architecture.md)、[当前限制](../status.md)、[测试规则](../testing.md) | `08b3342d8623b58f2b020d4fd6487f76b24354026ac9040b5a5d3a81590f8c5b` |
| [REQ-001-requirement-pool/roadmap.md](../requirements/REQ-001-requirement-pool/roadmap.md) | 现行知识提炼；旧措辞留档 | [后续范围](../roadmap.md) | `2dd3ee4909d7317ac2ad6754b1225f7b8f369b6c1eb0a0403b102eb04ac73221` |
| [REQ-001-requirement-pool/validation.md](../requirements/REQ-001-requirement-pool/validation.md) | 行为/限制提炼；历史证据留档 | [后续范围](../roadmap.md)、[发布验收](../release-checklist.md)、[架构决策](../decisions/architecture.md)、[当前限制](../status.md)、[测试规则](../testing.md) | `3f6737b30fffbd945322c11036f3d945ac7c304dfb13b87c8efe852731359a54` |
| [REQ-002-task-plugin-design/README.md](../requirements/REQ-002-task-plugin-design/README.md) | 现行知识提炼；旧措辞留档 | [架构决策](../decisions/architecture.md)、[步骤](../reference/step-content.md)、[运行](../reference/runtime.md)、[存储结果](../reference/persistence-results.md)、[插件](../reference/plugin-development.md)、[AI](../reference/authoring.md) | `5566fe64e586b198c1166536d4309e0a67c6f41f7e9e0856bfddadff78a844cf` |
| [REQ-002-task-plugin-design/code-mapping.md](../requirements/REQ-002-task-plugin-design/code-mapping.md) | 现行入口归索引；旧路径留档 | [维护索引](../maintenance.md)、[测试规则](../testing.md)、[架构决策](../decisions/architecture.md)、[步骤](../reference/step-content.md) | `7e1cd29ca39e43a4112f3b92ecb4f0122418f46076ab0ebabe79ee5a7f2dbb9d` |
| [REQ-002-task-plugin-design/contracts/control.sql](../requirements/REQ-002-task-plugin-design/contracts/control.sql) | 旧契约/样例留档；现行协议由源码承接 | [存储结果](../reference/persistence-results.md) | `e6dfe9e05b752b0536d08055ac46de4f454851c449ac1d7ceab3af08e1a6f13a` |
| [REQ-002-task-plugin-design/contracts/ports.py](../requirements/REQ-002-task-plugin-design/contracts/ports.py) | 旧契约/样例留档；现行协议由源码承接 | [插件](../reference/plugin-development.md)、[步骤](../reference/step-content.md)、[架构决策](../decisions/architecture.md) | `56a4ef9d98d0476a0357fc995a1da9c9e6305673b97d4d649f7bfb4b5f339ebf` |
| [REQ-002-task-plugin-design/contracts/task-data.sql](../requirements/REQ-002-task-plugin-design/contracts/task-data.sql) | 旧契约/样例留档；现行协议由源码承接 | [存储结果](../reference/persistence-results.md) | `298f799b923af7195b6273eb05c9d921c974943f255358fb9f23afce88aef50f` |
| [REQ-002-task-plugin-design/design.md](../requirements/REQ-002-task-plugin-design/design.md) | 现行知识提炼；旧措辞留档 | [架构决策](../decisions/architecture.md)、[步骤](../reference/step-content.md)、[运行](../reference/runtime.md)、[存储结果](../reference/persistence-results.md)、[插件](../reference/plugin-development.md)、[AI](../reference/authoring.md) | `d897984c4ad519f75d874aa280d89472bff00c443bd6d7904b5f27cee8b69d66` |
| [REQ-002-task-plugin-design/examples/inspect_page.py](../requirements/REQ-002-task-plugin-design/examples/inspect_page.py) | 旧契约/样例留档；现行协议由源码承接 | [步骤](../reference/step-content.md)、[存储结果](../reference/persistence-results.md) | `c0d457e78eae092d5450cc4bcf513b9113b79afd3359418b646db2c85a59339b` |
| [REQ-002-task-plugin-design/examples/open_page.py](../requirements/REQ-002-task-plugin-design/examples/open_page.py) | 旧契约/样例留档；现行协议由源码承接 | [步骤](../reference/step-content.md)、[运行](../reference/runtime.md) | `2b8b32c8e25df116a0a82246c99679d195837de23d066ce928fd9afbca65f0f7` |
| [REQ-002-task-plugin-design/examples/playwright.json](../requirements/REQ-002-task-plugin-design/examples/playwright.json) | 旧契约/样例留档；现行协议由源码承接 | [插件](../reference/plugin-development.md) | `db5e5cc4fbc5902dc37cb74011c4b24f458428df8e95ff5f289603079305129d` |
| [REQ-002-task-plugin-design/examples/task.json](../requirements/REQ-002-task-plugin-design/examples/task.json) | 旧契约/样例留档；现行协议由源码承接 | [分享](../reference/task-sharing.md)、[步骤](../reference/step-content.md) | `9c4e1cdc81ec88429bf8b3fb6882b000613c62e8de344a20d2c826b342d95bfc` |
| [REQ-002-task-plugin-design/plan.md](../requirements/REQ-002-task-plugin-design/plan.md) | 已做步骤留档；规则/未做范围提炼 | [架构决策](../decisions/architecture.md)、[步骤](../reference/step-content.md)、[运行](../reference/runtime.md)、[存储结果](../reference/persistence-results.md)、[插件](../reference/plugin-development.md)、[AI](../reference/authoring.md)、[协作方法](../ai-operating-model.md) | `b3553b8b2a6b0d68dc85b0fa700ba47437b5d3d28d11779fe2faa7b0b1f62b8c` |
| [REQ-002-task-plugin-design/plugin-contract.md](../requirements/REQ-002-task-plugin-design/plugin-contract.md) | 现行知识提炼；旧措辞留档 | [插件](../reference/plugin-development.md)、[采集](../reference/contexts.md)、[存储结果](../reference/persistence-results.md) | `bfec338e10f06f381323ee3164e2fe74e456f2e63680e83fd53f7c173aa3ef52` |
| [REQ-002-task-plugin-design/progress.md](../requirements/REQ-002-task-plugin-design/progress.md) | 行为/限制提炼；历史证据留档 | [架构决策](../decisions/architecture.md)、[步骤](../reference/step-content.md)、[运行](../reference/runtime.md)、[存储结果](../reference/persistence-results.md)、[插件](../reference/plugin-development.md)、[AI](../reference/authoring.md)、[当前限制](../status.md)、[测试规则](../testing.md) | `68be9be0c9650fdf290ee8cf11c0469f99aeab34b6aa9f6be3ceaeb30a049cb2` |
| [REQ-002-task-plugin-design/runtime.md](../requirements/REQ-002-task-plugin-design/runtime.md) | 现行知识提炼；旧措辞留档 | [运行](../reference/runtime.md) | `c67471be1955ad00d192f51389b32362f82b54eef00bd80de485a14d8e1ab94b` |
| [REQ-002-task-plugin-design/step-content.md](../requirements/REQ-002-task-plugin-design/step-content.md) | 现行知识提炼；旧措辞留档 | [步骤](../reference/step-content.md)、[AI](../reference/authoring.md)、[分享](../reference/task-sharing.md) | `275cdb79ec6ca1e1df5f27d2f41dbd0a071b2b9f6d15ad7f39f2806a39e97012` |
| [REQ-002-task-plugin-design/storage.md](../requirements/REQ-002-task-plugin-design/storage.md) | 现行知识提炼；旧措辞留档 | [存储结果](../reference/persistence-results.md) | `42664f2039c5311b2b6588bca0d0b0936858f4f91af54c8e8d2a4b31d072ebe8` |
| [REQ-002-task-plugin-design/validation.md](../requirements/REQ-002-task-plugin-design/validation.md) | 行为/限制提炼；历史证据留档 | [架构决策](../decisions/architecture.md)、[步骤](../reference/step-content.md)、[运行](../reference/runtime.md)、[存储结果](../reference/persistence-results.md)、[插件](../reference/plugin-development.md)、[AI](../reference/authoring.md)、[当前限制](../status.md)、[测试规则](../testing.md) | `7841cc5695807e4b1911112ea0addb4b7bb3984c74fcc8257fbbac08f7ef9e00` |
| [REQ-002-task-plugin-design/walkthrough.md](../requirements/REQ-002-task-plugin-design/walkthrough.md) | 现行知识提炼；旧措辞留档 | [步骤](../reference/step-content.md)、[运行](../reference/runtime.md)、[存储结果](../reference/persistence-results.md) | `f9485f026774c82ce2652d938b989eb0d3f26984c635f895cae0d66f20c3100f` |
| [REQ-003-task-core/README.md](../requirements/REQ-003-task-core/README.md) | 现行知识提炼；旧措辞留档 | [步骤](../reference/step-content.md)、[运行](../reference/runtime.md)、[存储结果](../reference/persistence-results.md)、[配置API](../reference/api-and-configuration.md)、[AI](../reference/authoring.md) | `40b1171f2eb45478a9c4a8c5ae0022f4a0be2d1ca68f615a3cc65c769796fcf4` |
| [REQ-003-task-core/code-mapping.md](../requirements/REQ-003-task-core/code-mapping.md) | 现行入口归索引；旧路径留档 | [维护索引](../maintenance.md)、[测试规则](../testing.md)、[步骤](../reference/step-content.md)、[运行](../reference/runtime.md) | `bcf31f802b35463d7ae048bc3b474d0b954ad03c2f64c25956f13e4eb8f9e4fb` |
| [REQ-003-task-core/design.md](../requirements/REQ-003-task-core/design.md) | 现行知识提炼；旧措辞留档 | [步骤](../reference/step-content.md)、[运行](../reference/runtime.md)、[存储结果](../reference/persistence-results.md)、[配置API](../reference/api-and-configuration.md)、[AI](../reference/authoring.md) | `441b07a92b0b36969ffddcf63f3022db63cbf3fce4d7644c32402e0a535fd372` |
| [REQ-003-task-core/plan.md](../requirements/REQ-003-task-core/plan.md) | 已做步骤留档；规则/未做范围提炼 | [步骤](../reference/step-content.md)、[运行](../reference/runtime.md)、[存储结果](../reference/persistence-results.md)、[配置API](../reference/api-and-configuration.md)、[AI](../reference/authoring.md)、[协作方法](../ai-operating-model.md) | `ffdef474885ab046cda5a9a3851fbdfd1d601ba38299f3bfbee5a24bbcb055e9` |
| [REQ-003-task-core/progress.md](../requirements/REQ-003-task-core/progress.md) | 行为/限制提炼；历史证据留档 | [步骤](../reference/step-content.md)、[运行](../reference/runtime.md)、[存储结果](../reference/persistence-results.md)、[配置API](../reference/api-and-configuration.md)、[AI](../reference/authoring.md)、[当前限制](../status.md)、[测试规则](../testing.md) | `88427af58533a68ecde809e43930bf373acb58d3d871d8e30568966d5c69083b` |
| [REQ-003-task-core/storage.md](../requirements/REQ-003-task-core/storage.md) | 现行知识提炼；旧措辞留档 | [存储结果](../reference/persistence-results.md)、[采集](../reference/contexts.md)、[步骤](../reference/step-content.md) | `42cadf4c335e3aa3b366bca1ee588eb8acdaa4eecda310219564044b3b10dadf` |
| [REQ-003-task-core/usage.md](../requirements/REQ-003-task-core/usage.md) | 现行知识提炼；旧措辞留档 | [配置API](../reference/api-and-configuration.md)、[运行](../reference/runtime.md)、[步骤](../reference/step-content.md) | `2bf4c5055d0e3ba2f29c059d1668da6a5a5a0cbc52c54c10eb6edffee34c6d23` |
| [REQ-003-task-core/validation.md](../requirements/REQ-003-task-core/validation.md) | 行为/限制提炼；历史证据留档 | [步骤](../reference/step-content.md)、[运行](../reference/runtime.md)、[存储结果](../reference/persistence-results.md)、[配置API](../reference/api-and-configuration.md)、[AI](../reference/authoring.md)、[当前限制](../status.md)、[测试规则](../testing.md) | `6aa8cea50b7859515f84d2efedae5c1f6487109cb7b1ff0e02b02da0598a0f88` |
| [REQ-004-plugin-contract/README.md](../requirements/REQ-004-plugin-contract/README.md) | 现行知识提炼；旧措辞留档 | [插件](../reference/plugin-development.md)、[采集](../reference/contexts.md)、[AI](../reference/authoring.md)、[存储结果](../reference/persistence-results.md) | `0af52b7149314e7fdee14cb05613c5e619264c6ad5f2c52bf79450f617bafd6f` |
| [REQ-004-plugin-contract/ai-extension.md](../requirements/REQ-004-plugin-contract/ai-extension.md) | 现行知识提炼；旧措辞留档 | [插件](../reference/plugin-development.md)、[AI](../reference/authoring.md)、[采集](../reference/contexts.md)、[存储结果](../reference/persistence-results.md) | `a66751cbf6e526cd45713526e122bd8b685d384ae05e5710bfcaf26eb3fcefae` |
| [REQ-004-plugin-contract/code-mapping.md](../requirements/REQ-004-plugin-contract/code-mapping.md) | 现行入口归索引；旧路径留档 | [维护索引](../maintenance.md)、[测试规则](../testing.md)、[插件](../reference/plugin-development.md)、[采集](../reference/contexts.md) | `3db42c674f7071193b850ee906756500c2299ceae041987067e1f571ff55f8f9` |
| [REQ-004-plugin-contract/design.md](../requirements/REQ-004-plugin-contract/design.md) | 现行知识提炼；旧措辞留档 | [插件](../reference/plugin-development.md)、[采集](../reference/contexts.md)、[AI](../reference/authoring.md)、[存储结果](../reference/persistence-results.md) | `fe1e9699d18fd8f40d3e9f8fd5e7a06caf45acf0657ee5e99a73b05594fc17ab` |
| [REQ-004-plugin-contract/plan.md](../requirements/REQ-004-plugin-contract/plan.md) | 已做步骤留档；规则/未做范围提炼 | [插件](../reference/plugin-development.md)、[采集](../reference/contexts.md)、[AI](../reference/authoring.md)、[存储结果](../reference/persistence-results.md)、[协作方法](../ai-operating-model.md) | `a8e3df4cdb43addbbc3244017c8b21844e0b554f6eec1b94727f5bd2dfa21754` |
| [REQ-004-plugin-contract/progress.md](../requirements/REQ-004-plugin-contract/progress.md) | 行为/限制提炼；历史证据留档 | [插件](../reference/plugin-development.md)、[采集](../reference/contexts.md)、[AI](../reference/authoring.md)、[存储结果](../reference/persistence-results.md)、[当前限制](../status.md)、[测试规则](../testing.md) | `3ab196958cbac7e9fe8b434c9269530d9f1736de8171ebc2093079ae426af043` |
| [REQ-004-plugin-contract/result-handling.md](../requirements/REQ-004-plugin-contract/result-handling.md) | 现行知识提炼；旧措辞留档 | [存储结果](../reference/persistence-results.md) | `4206362b174d39b031e9d786b4ddcd6307104b5f82e96704557aacf528017054` |
| [REQ-004-plugin-contract/usage.md](../requirements/REQ-004-plugin-contract/usage.md) | 现行知识提炼；旧措辞留档 | [插件](../reference/plugin-development.md)、[配置API](../reference/api-and-configuration.md) | `5db05cf063c3dbf8e8526e2c95f101dead4028cde0d669088b9482668e39ae0e` |
| [REQ-004-plugin-contract/validation.md](../requirements/REQ-004-plugin-contract/validation.md) | 行为/限制提炼；历史证据留档 | [插件](../reference/plugin-development.md)、[采集](../reference/contexts.md)、[AI](../reference/authoring.md)、[存储结果](../reference/persistence-results.md)、[当前限制](../status.md)、[测试规则](../testing.md) | `448728424ccea59266d7b8b73a36d31bf998a9e4a70cf58eb747fc9fd7329631` |
| [REQ-005-local-workbench/README.md](../requirements/REQ-005-local-workbench/README.md) | 现行知识提炼；旧措辞留档 | [UI](../reference/desktop.md)、[采集](../reference/contexts.md)、[AI](../reference/authoring.md)、[配置API](../reference/api-and-configuration.md)、[运行](../reference/runtime.md)、[分享](../reference/task-sharing.md) | `3857f6881b8db78daf0ffdf412853928f6fd749b6b5ed96b772265d2d10cd8b7` |
| [REQ-005-local-workbench/code-mapping.md](../requirements/REQ-005-local-workbench/code-mapping.md) | 现行入口归索引；旧路径留档 | [维护索引](../maintenance.md)、[测试规则](../testing.md)、[UI](../reference/desktop.md)、[采集](../reference/contexts.md) | `0114f89acb4b61ec8fe736bfca92660295285f0826ca57fabb19f15c19ca6723` |
| [REQ-005-local-workbench/design.md](../requirements/REQ-005-local-workbench/design.md) | 现行知识提炼；旧措辞留档 | [UI](../reference/desktop.md)、[采集](../reference/contexts.md)、[配置API](../reference/api-and-configuration.md)、[存储结果](../reference/persistence-results.md)、[分享](../reference/task-sharing.md) | `cd2971a1f0f245c36bc91cdd62b09fed22beaa820f422d64b057a913915d02dd` |
| [REQ-005-local-workbench/plan.md](../requirements/REQ-005-local-workbench/plan.md) | 已做步骤留档；规则/未做范围提炼 | [UI](../reference/desktop.md)、[采集](../reference/contexts.md)、[AI](../reference/authoring.md)、[配置API](../reference/api-and-configuration.md)、[运行](../reference/runtime.md)、[分享](../reference/task-sharing.md)、[协作方法](../ai-operating-model.md) | `d1cebd7b567fb47d02a67d352adb01d70695867a8cbdeb7e11f15f607b0904bd` |
| [REQ-005-local-workbench/progress.md](../requirements/REQ-005-local-workbench/progress.md) | 行为/限制提炼；历史证据留档 | [UI](../reference/desktop.md)、[采集](../reference/contexts.md)、[AI](../reference/authoring.md)、[配置API](../reference/api-and-configuration.md)、[运行](../reference/runtime.md)、[分享](../reference/task-sharing.md)、[当前限制](../status.md)、[测试规则](../testing.md) | `52ea5d619fb2bb2fd870d692ae952e9d494c402d9b95f951c6538c6eee077f4f` |
| [REQ-005-local-workbench/usage.md](../requirements/REQ-005-local-workbench/usage.md) | 现行知识提炼；旧措辞留档 | [UI](../reference/desktop.md)、[AI](../reference/authoring.md)、[配置API](../reference/api-and-configuration.md)、[步骤](../reference/step-content.md)、[运行](../reference/runtime.md)、[采集](../reference/contexts.md)、[分享](../reference/task-sharing.md) | `49ee21b121c7252bee4f97fc9de319d4708604e799b221be2f1046287b4c1683` |
| [REQ-005-local-workbench/validation.md](../requirements/REQ-005-local-workbench/validation.md) | 行为/限制提炼；历史证据留档 | [UI](../reference/desktop.md)、[采集](../reference/contexts.md)、[AI](../reference/authoring.md)、[配置API](../reference/api-and-configuration.md)、[运行](../reference/runtime.md)、[分享](../reference/task-sharing.md)、[当前限制](../status.md)、[测试规则](../testing.md) | `6c6d82c7360e5647a10051ca8b9c9b1a9341f5bb05cea6b6fa895da6f5f71132` |
| [REQ-006-template-sharing/README.md](../requirements/REQ-006-template-sharing/README.md) | 现行知识提炼；旧措辞留档 | [分享](../reference/task-sharing.md)、[后续范围](../roadmap.md) | `8ee244516e9209f72f5a6f92bdf0e1e3da3cf28158ac5ef10d44f9df8a58c757` |
| [REQ-006-template-sharing/code-mapping.md](../requirements/REQ-006-template-sharing/code-mapping.md) | 现行入口归索引；旧路径留档 | [维护索引](../maintenance.md)、[后续范围](../roadmap.md)、[分享](../reference/task-sharing.md) | `2e9951e1ece0cb56f25a9659f48d8b3c2f34312b8c3779b7da72db003525e184` |
| [REQ-006-template-sharing/design.md](../requirements/REQ-006-template-sharing/design.md) | 现行知识提炼；旧措辞留档 | [分享](../reference/task-sharing.md)、[后续范围](../roadmap.md) | `3b145428aec6861445ea5774721d3d2c77461c0f0cbb5cf5b17a3bbd164cf9ee` |
| [REQ-006-template-sharing/plan.md](../requirements/REQ-006-template-sharing/plan.md) | 已做步骤留档；规则/未做范围提炼 | [分享](../reference/task-sharing.md)、[后续范围](../roadmap.md)、[协作方法](../ai-operating-model.md) | `1d747755ea27bbc8c9a446c0619a40ce043e3220bd742b1bfe12319d6658b233` |
| [REQ-006-template-sharing/progress.md](../requirements/REQ-006-template-sharing/progress.md) | 行为/限制提炼；历史证据留档 | [分享](../reference/task-sharing.md)、[后续范围](../roadmap.md)、[当前限制](../status.md)、[测试规则](../testing.md) | `7b0fe1e3b8042a76d2d40845d0beea56798b5f5944b2808b2cab394e6792e100` |
| [REQ-006-template-sharing/validation.md](../requirements/REQ-006-template-sharing/validation.md) | 行为/限制提炼；历史证据留档 | [分享](../reference/task-sharing.md)、[后续范围](../roadmap.md)、[当前限制](../status.md)、[测试规则](../testing.md) | `3b3aed0cc930ca6fc0e314fb8292f7905ef3c3de7d374f0fdf07a9a655f402c4` |
| [REQ-007-v1-release/README.md](../requirements/REQ-007-v1-release/README.md) | 现行知识提炼；旧措辞留档 | [Windows](../windows-portable.md)、[发布验收](../release-checklist.md)、[后续范围](../roadmap.md) | `a8c0c6e31d4c490ea1c942aa8eda9f3478024915e1ebd9da0539953df441b4b0` |
| [REQ-007-v1-release/code-mapping.md](../requirements/REQ-007-v1-release/code-mapping.md) | 现行入口归索引；旧路径留档 | [维护索引](../maintenance.md)、[测试规则](../testing.md)、[Windows](../windows-portable.md)、[发布验收](../release-checklist.md) | `2a21200a84d4facb79da8c9d0dad0a471c8d60078cb29707eec9a258b1fee4a1` |
| [REQ-007-v1-release/design.md](../requirements/REQ-007-v1-release/design.md) | 现行知识提炼；旧措辞留档 | [Windows](../windows-portable.md)、[发布验收](../release-checklist.md)、[后续范围](../roadmap.md) | `1fe9bafad5cb17c4513e5ba4dfed903e810b1721fcf813eb81261a16d2a9b402` |
| [REQ-007-v1-release/plan.md](../requirements/REQ-007-v1-release/plan.md) | 已做步骤留档；规则/未做范围提炼 | [Windows](../windows-portable.md)、[发布验收](../release-checklist.md)、[后续范围](../roadmap.md)、[协作方法](../ai-operating-model.md) | `1ef6643ea5e95c55a81d87638d7d340711002012d73a6a53c843f5a6bfddd937` |
| [REQ-007-v1-release/progress.md](../requirements/REQ-007-v1-release/progress.md) | 行为/限制提炼；历史证据留档 | [Windows](../windows-portable.md)、[发布验收](../release-checklist.md)、[后续范围](../roadmap.md)、[当前限制](../status.md)、[测试规则](../testing.md) | `fe426c7ea7e638fd31c5ce92e2a20e7defc9728a0c39b4b16a638f3694e1dc94` |
| [REQ-007-v1-release/validation.md](../requirements/REQ-007-v1-release/validation.md) | 行为/限制提炼；历史证据留档 | [Windows](../windows-portable.md)、[发布验收](../release-checklist.md)、[后续范围](../roadmap.md)、[当前限制](../status.md)、[测试规则](../testing.md) | `dcb93e054ab0e3a0a54f5d90b357cfe71189700b3f133a4a96438d3e2d15a1bc` |
| [REQ-007-v1-release/windows-package.md](../requirements/REQ-007-v1-release/windows-package.md) | 现行知识提炼；旧措辞留档 | [Windows](../windows-portable.md) | `1c646269953ace7e1cd68481ba0cced18dcee5cde7ad27e4ceeceec350ef4e9a` |
| [REQ-008-flow-control/README.md](../requirements/REQ-008-flow-control/README.md) | 现行知识提炼；旧措辞留档 | [后续范围](../roadmap.md) | `8dfb36767cc4a880d8f57fb1687c4a2849b81123e4763df67e888ae439bd865c` |
| [REQ-008-flow-control/code-mapping.md](../requirements/REQ-008-flow-control/code-mapping.md) | 现行入口归索引；旧路径留档 | [维护索引](../maintenance.md)、[后续范围](../roadmap.md) | `6b2bdb2e0bb330236de96df6c29b4a4c89c6da068c6518a809472b7e87f2ca26` |
| [REQ-008-flow-control/design.md](../requirements/REQ-008-flow-control/design.md) | 现行知识提炼；旧措辞留档 | [后续范围](../roadmap.md) | `63cd73b94cf3eeba9c0d8766394722486ce87844337530cf9461f37a9ec24b85` |
| [REQ-008-flow-control/plan.md](../requirements/REQ-008-flow-control/plan.md) | 已做步骤留档；规则/未做范围提炼 | [后续范围](../roadmap.md)、[协作方法](../ai-operating-model.md) | `49c09bf9e0f03085f4971ee04480a7a54fe0dcf8ebb6dd9334d8ad4b9f416213` |
| [REQ-008-flow-control/progress.md](../requirements/REQ-008-flow-control/progress.md) | 行为/限制提炼；历史证据留档 | [后续范围](../roadmap.md)、[当前限制](../status.md)、[测试规则](../testing.md) | `1b56906ef4ad34a8cb3677144e68b429900562bbed209a97503abad7cd30dffc` |
| [REQ-008-flow-control/validation.md](../requirements/REQ-008-flow-control/validation.md) | 行为/限制提炼；历史证据留档 | [后续范围](../roadmap.md)、[当前限制](../status.md)、[测试规则](../testing.md) | `bfade2ed8b7ca580def26d17f28525d397f2806985a2c1b98d3beb980f519ce3` |
| [REQ-009-visual-flow-editor/README.md](../requirements/REQ-009-visual-flow-editor/README.md) | 现行知识提炼；旧措辞留档 | [后续范围](../roadmap.md) | `9eb0c7c1ee595586ab73a6fa4816f20471e0b821b7b42935fb10686c0c55123b` |
| [REQ-009-visual-flow-editor/code-mapping.md](../requirements/REQ-009-visual-flow-editor/code-mapping.md) | 现行入口归索引；旧路径留档 | [维护索引](../maintenance.md)、[后续范围](../roadmap.md) | `f3cf9c7ad23470c7e233b64aa4451ced502216bc91ea94a6debb8a78b370c2dd` |
| [REQ-009-visual-flow-editor/design.md](../requirements/REQ-009-visual-flow-editor/design.md) | 现行知识提炼；旧措辞留档 | [后续范围](../roadmap.md) | `9d6f8ebda43566d0ea308ede6c821e6e14461f25fc206e34f627da255d76db3c` |
| [REQ-009-visual-flow-editor/plan.md](../requirements/REQ-009-visual-flow-editor/plan.md) | 已做步骤留档；规则/未做范围提炼 | [后续范围](../roadmap.md)、[协作方法](../ai-operating-model.md) | `9a99f81bfa17534c2e3fdffd3b30bfb08d2dc5c3ac3997e24181b014dbde8a85` |
| [REQ-009-visual-flow-editor/progress.md](../requirements/REQ-009-visual-flow-editor/progress.md) | 行为/限制提炼；历史证据留档 | [后续范围](../roadmap.md)、[当前限制](../status.md)、[测试规则](../testing.md) | `1b56906ef4ad34a8cb3677144e68b429900562bbed209a97503abad7cd30dffc` |
| [REQ-009-visual-flow-editor/validation.md](../requirements/REQ-009-visual-flow-editor/validation.md) | 行为/限制提炼；历史证据留档 | [后续范围](../roadmap.md)、[当前限制](../status.md)、[测试规则](../testing.md) | `05641168fc5a66f9aa883e83c8dd4fa89418778d15fba3486657ec3e66083c89` |
| [REQ-010-ddd-modularization/README.md](../requirements/REQ-010-ddd-modularization/README.md) | 现行知识提炼；旧措辞留档 | [架构决策](../decisions/architecture.md)、[测试规则](../testing.md)、[UI](../reference/desktop.md)、[存储结果](../reference/persistence-results.md)、[运行](../reference/runtime.md)、[采集](../reference/contexts.md) | `3096a291bd0364a9529b4c2a8b8ed3412cc111ff464cd968c0c94b9969ecc1ba` |
| [REQ-010-ddd-modularization/code-mapping.md](../requirements/REQ-010-ddd-modularization/code-mapping.md) | 现行入口归索引；旧路径留档 | [维护索引](../maintenance.md)、[架构决策](../decisions/architecture.md)、[测试规则](../testing.md) | `f45d33674a110a522a4f0c687a35a5a3d7a0deb08d80db50ebfc9b93e710883b` |
| [REQ-010-ddd-modularization/design.md](../requirements/REQ-010-ddd-modularization/design.md) | 现行知识提炼；旧措辞留档 | [架构决策](../decisions/architecture.md)、[测试规则](../testing.md)、[UI](../reference/desktop.md)、[存储结果](../reference/persistence-results.md)、[运行](../reference/runtime.md)、[采集](../reference/contexts.md) | `58350d97b84f99d4926673258f51dbdd0fc4d5cbaaa5d58ee40b3365670b3cea` |
| [REQ-010-ddd-modularization/final-acceptance.md](../requirements/REQ-010-ddd-modularization/final-acceptance.md) | 行为/限制提炼；历史证据留档 | [架构决策](../decisions/architecture.md)、[测试规则](../testing.md)、[当前限制](../status.md)、[发布验收](../release-checklist.md) | `3b3c427739f8904da3d94c3dc1fd76c4f340f7f8b249481a6b05969ad88639c3` |
| [REQ-010-ddd-modularization/plan.md](../requirements/REQ-010-ddd-modularization/plan.md) | 已做步骤留档；规则/未做范围提炼 | [架构决策](../decisions/architecture.md)、[测试规则](../testing.md)、[UI](../reference/desktop.md)、[存储结果](../reference/persistence-results.md)、[运行](../reference/runtime.md)、[采集](../reference/contexts.md)、[协作方法](../ai-operating-model.md) | `403d98b82ca5481787c7bd16218f9cd08ace8dedeea8da32a5c46b77c2d89751` |
| [REQ-010-ddd-modularization/progress.md](../requirements/REQ-010-ddd-modularization/progress.md) | 行为/限制提炼；历史证据留档 | [架构决策](../decisions/architecture.md)、[测试规则](../testing.md)、[UI](../reference/desktop.md)、[存储结果](../reference/persistence-results.md)、[运行](../reference/runtime.md)、[采集](../reference/contexts.md)、[当前限制](../status.md) | `100b8780c39adaf3397b65b500ad67422ce3534f312c16144f54c35e98b54626` |
| [REQ-010-ddd-modularization/review.md](../requirements/REQ-010-ddd-modularization/review.md) | 行为/限制提炼；历史证据留档 | [架构决策](../decisions/architecture.md)、[UI](../reference/desktop.md)、[采集](../reference/contexts.md)、[运行](../reference/runtime.md)、[测试规则](../testing.md)、[当前限制](../status.md) | `666992d42a467c17db26ec482173320b9b2bb3444f3182193fcbbc35ecf39292` |
| [REQ-010-ddd-modularization/validation.md](../requirements/REQ-010-ddd-modularization/validation.md) | 行为/限制提炼；历史证据留档 | [架构决策](../decisions/architecture.md)、[测试规则](../testing.md)、[UI](../reference/desktop.md)、[存储结果](../reference/persistence-results.md)、[运行](../reference/runtime.md)、[采集](../reference/contexts.md)、[当前限制](../status.md) | `fd3bb0f4d9d29d96430fe4fc0f2c97d589de361e281e6cded61af001e31f6948` |
