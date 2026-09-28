# 全界面功能覆盖与缺口核对

日期：2026-09-26。范围：当前工作树的桌面 UI，不把 CLI/HTTP 独有操作自动扩成 UI 需求。核对 33 份 desktop Python 文件，提取 450 处控件/操作引用，按下表功能组逐项比对。机器来源见 [源码盘点](source-inventory.json)，含文件 hash、控件标签、函数与行号；450 不是独立功能数量。

用户已认可整体视觉，本轮补的是入口与交互细节。**“已补”仅指原型中的页面、控件或流程设计；不表示产品已接线、持久化或运行回归通过。** 所有真实业务能力仍应复用现有用例，不移植原型模拟状态。

## 核对结论

第一版并非功能等价设计。调试缺少连续调试/结束/AI 修复等入口；上下文被简化成附件列表，丢失组、顺序、会话、暂存提交语义。本轮纠正这两项，并补齐其他一级页面和关键弹窗。

另外发现原型遗漏：任务调试历史、步骤多插件与 null 参数类型、代码编辑、步骤确认、变量绑定、时间设置、执行多选筛选与三种执行到目标的操作、规划生成导入、模型密钥环境变量名、实例与服务日志。均纳入下表。未发现需要删除现有功能的理由。

## 功能映射

| 编号 | 模块 | 当前功能 | 当前源码 | 新界面入口 | 设计覆盖状态 |
| --- | --- | --- | --- | --- | --- |
| G01 | 全局 | 八个主页面、统一导航 | [workbench.py](../../../src/taskweave/desktop/workbench.py) | 顶部导航 | 已补页面 |
| G02 | 全局 | 执行实例（规划/调试/正式）与结束实例 | [workbench.py](../../../src/taskweave/desktop/workbench.py) | 顶部 → 执行实例 | 已补弹窗 |
| G03 | 全局 | 服务日志级别、暂停显示、清空显示、目录 | [server_logs.py](../../../src/taskweave/desktop/server_logs.py) | 顶部 → 服务日志 | 已补弹窗 |
| G04 | 全局 | 离页保存失败保护、迟到响应、dispose | [workbench.py](../../../src/taskweave/desktop/workbench.py) | 未保存切换提示及设计约束 | 行为待接入 |
| T01 | 任务 | 搜索名称/说明、新建、编辑名称说明 | [tasks.py](../../../src/taskweave/desktop/pages/tasks.py) | 左列表、新建、概览编辑 | 已补入口 |
| T02 | 任务 | 任务参数类型/必填/默认/说明/null | [forms.py](../../../src/taskweave/desktop/forms.py) | 任务配置 → 管理变量 | 已补表单 |
| T03 | 任务 | 复制任务 | [tasks.py](../../../src/taskweave/desktop/pages/tasks.py) | 任务右上更多 → 复制 | 已补弹窗 |
| T04 | 任务 | 导出 JSON、复制与下载 | [tasks.py](../../../src/taskweave/desktop/pages/tasks.py) | 任务右上更多 → 导出 | 已补弹窗 |
| T05 | 任务 | 粘贴任务包、校验并导入为新任务 | [tasks.py](../../../src/taskweave/desktop/pages/tasks.py) | 任务更多 / 工作台 → 导入 | 已补弹窗 |
| T06 | 任务 | 清理运行、删除任务与影响确认 | [tasks.py](../../../src/taskweave/desktop/pages/tasks.py) | 任务右上更多 | 已补确认 |
| T07 | 任务 | 本任务调试历史、尝试、结果、错误 | [history.py](../../../src/taskweave/desktop/pages/history.py) | 任务内部“调试历史” → 查看记录 | 已补独立入口 |
| T08 | 任务 | 收藏/分类管理 | [tasks.py](../../../src/taskweave/desktop/pages/tasks.py) | 左侧收藏/分类/管理分类 | 新增候选 |
| S01 | 步骤 | 新增/选择/上移/下移/删除与依赖限制 | [step_list.py](../../../src/taskweave/desktop/components/step_list.py) | 步骤目录 + / 步骤排序与确认 | 已补管理弹窗 |
| S02 | 步骤 | 全部步骤校验及手动确认 | [step_list.py](../../../src/taskweave/desktop/components/step_list.py) | 步骤排序与确认 → 一键确认 | 已补确认 |
| S03 | 步骤 | 名称/描述/长期补充说明 | [step_editor.py](../../../src/taskweave/desktop/components/step_editor.py) | 步骤配置 | 已补字段 |
| S04 | 步骤 | 多插件选择、不可用能力保留 | [step_editor.py](../../../src/taskweave/desktop/components/step_editor.py) | 使用插件多选 | 已有不可用项保留待接入 |
| S05 | 步骤 | CodeMirror 编写、内容校验及诊断 | [step_editor.py](../../../src/taskweave/desktop/components/step_editor.py) | 代码编辑器 → 校验内容 | 已补编辑器/诊断弹窗 |
| S06 | 步骤 | 调试证据确认、手动确认并保存 | [step_ai.py](../../../src/taskweave/desktop/components/step_ai.py) | 编辑区底部 → 确认验证并保存 | 已补确认 |
| S07 | 步骤 | 插件动作按 schema 填写并插入 | [step_editor.py](../../../src/taskweave/desktop/components/step_editor.py) | 插入动作 → 动作表单 | 已补表单 |
| S08 | 步骤 | 输入定义、固定值/任务/环境/前序依赖 | [step_editor.py](../../../src/taskweave/desktop/components/step_editor.py) | 变量与输入依赖 → 两个编辑入口 | 已补表单 |
| S09 | 步骤 | 前序结果容器/字段选择及无历史回退 | [step_editor.py](../../../src/taskweave/desktop/components/step_editor.py) | 编辑输入依赖 | 已补字段；动态候选待接入 |
| S10 | 步骤 | 步骤间隔/超时、首步骤禁用间隔 | [step_editor.py](../../../src/taskweave/desktop/components/step_editor.py) | 时间设置 | 已补表单 |
| D01 | 调试 | 环境、任务输入、步骤输入、只读环境 | [trial_inputs.py](../../../src/taskweave/desktop/components/trial_inputs.py) | 调试区 → 环境与本次输入 | 已补三层输入 |
| D02 | 调试 | 单步调试、保留同环境会话再调试 | [step_debug.py](../../../src/taskweave/desktop/components/step_debug.py) | 调试当前步骤 | 已补弹窗；资源行为待接入 |
| D03 | 调试 | 选起点调试到当前步骤 | [step_debug.py](../../../src/taskweave/desktop/components/step_debug.py) | 从选定步骤调试 | 已补起点选择与终点说明 |
| D04 | 调试 | 结束调试与 can_end | [step_debug.py](../../../src/taskweave/desktop/components/step_debug.py) | 结束调试 | 已补确认；动态可用性待接入 |
| D05 | 调试 | 跨环境结束旧资源、结果不确定再次调试确认 | [step_debug.py](../../../src/taskweave/desktop/components/step_debug.py) | 调试输入弹窗/会话提示 | 已补确认设计；模拟状态 |
| D06 | 调试 | 缺参补录与原运行续启 | [run_inputs.py](../../../src/taskweave/desktop/components/run_inputs.py) | 补充必录参数 | 已补弹窗 |
| D07 | 调试 | 尝试/输出/日志/结果/打开其他失败步骤 | [step_debug.py](../../../src/taskweave/desktop/components/step_debug.py) | 调试结果、报错、日志区域 | 已补入口 |
| D08 | 调试 | 报错证据移除仅影响本轮 AI | [step_debug.py](../../../src/taskweave/desktop/components/step_debug.py) | 本次报错上下文 → 移除 | 已补演示交互 |
| D09 | 调试 | AI 修复补充说明/历史轮数/去重/API/Chat | [step_ai.py](../../../src/taskweave/desktop/components/step_ai.py) | AI 修复 → 渠道与历史配置 | 已补弹窗 |
| D10 | 调试 | 清空 AI 修复上下文不结束实例 | [step_ai.py](../../../src/taskweave/desktop/components/step_ai.py) | 清空 AI 修复上下文 | 已补明确范围 |
| A01 | AI | 生成步骤描述、步骤内容的独立入口 | [step_ai.py](../../../src/taskweave/desktop/components/step_ai.py) | AI 生成步骤描述 / AI 编写 | 已补独立入口 |
| A02 | AI | 网页提示词复制、回复粘贴、解析预览 | [step_ai.py](../../../src/taskweave/desktop/components/step_ai.py) | AI 渠道选择 → 网页 Chat | 已补弹窗 |
| A03 | AI | 候选差异预览、采纳/舍弃、校验失败 | [step_ai.py](../../../src/taskweave/desktop/components/step_ai.py) | 候选预览 | 已补弹窗；模型不调用 |
| A04 | AI | 请求容量/隐私/历史保留/过期响应隔离 | [step_ai.py](../../../src/taskweave/desktop/components/step_ai.py) | 请求提示与设计守卫 | 行为待接入 |
| C01 | 上下文 | 组名称/说明/采集器/组顺序/删除 | [contexts.py](../../../src/taskweave/desktop/contexts.py) | 上下文素材组卡片 | 已补完整层级 |
| C02 | 上下文 | 组内采集项标题/来源/时间/顺序 | [step_contexts.py](../../../src/taskweave/desktop/components/step_contexts.py) | 组卡片、编辑与采集弹窗 | 已补层级与编辑 |
| C03 | 上下文 | 观察会话、当前实例目标、刷新、参数模式 | [step_contexts.py](../../../src/taskweave/desktop/components/step_contexts.py) | 编辑与采集 → 会话/目标 | 已补表单；实际枚举待接入 |
| C04 | 上下文 | 插件 schema 表单、高级 JSON、预览开关 | [step_contexts.py](../../../src/taskweave/desktop/components/step_contexts.py) | 采集参数与高级 JSON | 已补区域；动态 schema 待接入 |
| C05 | 上下文 | 连续采集暂存、编辑、排序、删除和撤销 | [step_contexts.py](../../../src/taskweave/desktop/components/step_contexts.py) | 编辑与采集 → 保留采集项 | 已补内存演示 |
| C06 | 上下文 | 确认整组保存、取消/丢弃、失败保留 | [step_contexts.py](../../../src/taskweave/desktop/components/step_contexts.py) | 弹窗底部与失败预览 | 已补内存演示 |
| C07 | 上下文 | AI 证据 / 用户预览分离、按需加载 | [step_contexts.py](../../../src/taskweave/desktop/components/step_contexts.py) | 内容 / 预览 → 三个页签 | 已补展示结构 |
| C08 | 上下文 | 已保存组重新采集、空组可保存 | [step_contexts.py](../../../src/taskweave/desktop/components/step_contexts.py) | 编辑 / 继续采集 | 已补入口；保留原组暂存语义 |
| C09 | 上下文 | 会话身份/页面代次、事务、修改使步骤确认失效 | [step_contexts.py](../../../src/taskweave/desktop/components/step_contexts.py) | 采集提示与兼容约束 | 行为待接入 |
| P01 | 规划 | 搜索、新建、复制、删除 | [planning.py](../../../src/taskweave/desktop/planning.py) | 规划左侧列表/右上操作 | 已补页面 |
| P02 | 规划 | 名称/描述/操作说明/环境/多插件/保存 | [planning.py](../../../src/taskweave/desktop/planning.py) | 规划配置 | 已补字段 |
| P03 | 规划 | 上下文批量编辑、目标/预览、取消提交 | [planning.py](../../../src/taskweave/desktop/planning.py) | 规划内部上下文素材 | 复用完整组编辑设计 |
| P04 | 规划 | API生成、网页Chat提示词复制/下载/解析 | [planning.py](../../../src/taskweave/desktop/planning.py) | AI生成侧栏及网页弹窗 | 已补流程 |
| P05 | 规划 | 生成记录、诊断、候选上下文、待编写、导入 | [planning.py](../../../src/taskweave/desktop/planning.py) | 生成记录/候选预览 | 已补入口及错误提示 |
| P06 | 规划 | 结束采集实例、revision/冻结快照 | [planning.py](../../../src/taskweave/desktop/planning.py) | AI侧栏结束采集实例 | 已补入口；兼容行为待接入 |
| R01 | 执行 | 任务多选、状态多选、清除筛选 | [executions.py](../../../src/taskweave/desktop/pages/executions.py) | 执行左侧筛选 | 已补多选 |
| R02 | 执行 | 新建选择任务/环境/开始步骤/输入 | [executions.py](../../../src/taskweave/desktop/pages/executions.py) | 新建执行弹窗 | 已补表单 |
| R03 | 执行 | 运行详情、有效与失效尝试、日志、间隔倒计时 | [execution_details.py](../../../src/taskweave/desktop/components/execution_details.py) | 执行详情/历史尝试 | 已补详情；倒计时待接入 |
| R04 | 执行 | 暂停、结束、删除运行 | [execution_details.py](../../../src/taskweave/desktop/components/execution_details.py) | 详情头部 | 已补入口及影响说明 |
| R05 | 执行 | 继续到此步、指定起点重跑、从头重跑到此步 | [workbench.py](../../../src/taskweave/desktop/workbench.py) | 选中节点 → 执行至此 / 重跑 | 已补三种显式操作 |
| R06 | 执行 | 失败跳到对应步骤调试 | [workbench.py](../../../src/taskweave/desktop/workbench.py) | 执行详情 → 前往此步骤调试 | 已补入口；目标身份待接入 |
| R07 | 执行 | UNKNOWN 外部结果核对及证据 | [workbench.py](../../../src/taskweave/desktop/workbench.py) | 状态动作 → 核对结果 | 已补表单 |
| R08 | 执行 | 输入补录、稍后填写、提交继续原run | [run_inputs.py](../../../src/taskweave/desktop/components/run_inputs.py) | 等待输入 → 填写输入 | 已补表单 |
| R09 | 执行 | 新建与继续防重复、can_end/不确定副作用守卫 | [execution_details.py](../../../src/taskweave/desktop/components/execution_details.py) | 状态按钮与设计守卫 | 行为待接入 |
| V01 | 结果 | 动态展示页签、原始数据、无结果与展示失败 | [result_viewer.py](../../../src/taskweave/desktop/components/result_viewer.py) | 查看结果 → renderer 示例 | 已补展示区域；缺省/失败待接入 |
| V02 | 结果 | 表格排序分页、报告多表/查询信息、图片、文件打开 | [result_viewer.py](../../../src/taskweave/desktop/components/result_viewer.py) | 结果各类型页签 | 展示布局；真实renderer待接入 |
| E01 | 环境 | 新建、名称、变量Key/Value/说明、移除及保存 | [environments.py](../../../src/taskweave/desktop/pages/environments.py) | 环境主页面 | 已补表单 |
| E02 | 环境 | 默认环境、删除及引用限制 | [environments.py](../../../src/taskweave/desktop/pages/environments.py) | 环境操作区 | 已补确认；兼容行为待接入 |
| L01 | 插件 | 已安装清单、启用停用、版本及加载错误 | [plugins.py](../../../src/taskweave/desktop/pages/plugins.py) | 插件列表/详情 | 已补页面 |
| L02 | 插件 | 动作说明与schema、配置变量默认/必填说明 | [plugins.py](../../../src/taskweave/desktop/pages/plugins.py) | 能力与配置区域 | 已补区域 |
| F01 | 设置 | 模型URL/名称/本地密钥/环境变量名/保存/测试 | [settings.py](../../../src/taskweave/desktop/pages/settings.py) | AI连接与请求 | 已补字段；测试实际调用说明 |
| F02 | 设置 | AI请求KiB上限独立保存 | [settings.py](../../../src/taskweave/desktop/pages/settings.py) | AI连接与请求 → 请求大小 | 已补表单 |
| F03 | 设置 | 展示与发送AI独立脱敏选项 | [settings.py](../../../src/taskweave/desktop/pages/settings.py) | 脱敏设置 | 已补表单 |
| F04 | 设置 | 执行并发1–8、超限报错 | [settings.py](../../../src/taskweave/desktop/pages/settings.py) | 执行设置 | 已补表单 |
| F05 | 设置 | 迁移工作空间、确认/重启、打开目录 | [settings.py](../../../src/taskweave/desktop/pages/settings.py) | 工作空间 | 已补表单与确认 |
| M01 | 市集 | 建设中占位 | [marketplace.py](../../../src/taskweave/desktop/pages/marketplace.py) | 市集 | 已补页面；无下载或安装 |

## 仍然存在的缺口与处理方式

### 产品接入缺口（不是设计已交付功能）

本原型不调用业务服务。真实保存/自动保存/并发 revision/hash、动态插件 schema、缺参校验、活跃会话身份、结果 renderer、日志轮询、倒计时、权限与依赖限制、离页迟到响应保护仍须正式接入，并按模块验收。不能用模拟弹窗替代这些行为。

原型中的部分操作只展示表单或确认后提示，例如任务复制/删除、步骤增删移动、导入导出、插件启停、环境保存、实际AI生成和执行命令；按钮可达不代表这些业务动作已实现于原型。当前用例本身已有的能力应保留。

表格真实排序/分页、报告多表、图片文件加载与无结果/renderer错误回退需在正式结果组件中验证。本版结果弹窗提供各类型布局示例，不模拟完整文件系统和全部数据格式。手机端导航不在本次桌面窗口适配验收范围。

### 新增或待确认规则

- 收藏/分类已获授权，但规划是否同样支持、层级、单归属/多归属、删除归类、复制/分享携带规则未定。任务侧先给一级单分类候选；不修改持久化或任务包。
- 工作台聚合是新增页面设计，统计口径、活跃资源对象范围需按真实数据映射；示例增长/配额不进入产品。
- 选中执行节点改为仅查看，原来的执行操作迁入“执行至此 / 重跑”。能力保留，入口语义变化待本轮细节确认。
- 插件安装升级与账号按用户要求排除；插件使用统计/独立诊断日志、全局搜索、通知、配额、其他执行器、自动重试策略没有对应已交付能力，不擅自新增。服务日志已有，须保留。

### 固定兼容约束

- 连续调试终点是当前步骤，不是任务末尾；起点只能选当前及前序。保留会话再次调试的明确确认例外不扩大到正式执行。
- 清空 AI 修复上下文不等于结束调试，也不删除运行历史；移除报错证据只影响本轮 AI 请求。
- 上下文按组/项顺序组织证据，预览独立；采集暂存、整组确认提交、取消不写库；旧会话/旧页面不能误提交到新目标。
- 修改步骤上下文使确认失效；规划沿用 revision 和冻结快照。收藏分类不应改变步骤执行定义。
- 正式运行的继续/重跑/结束/核对以核心允许的操作为准，不能仅按界面状态标签决定。

## 下一步验收依据

先审阅细节原型，再按本表建立产品接入任务。每项接入需列出源用例、目标组件和模块测试；优先调试、上下文、执行恢复这些高风险边界。只跑受影响模块，未获授权不运行全量。原型布局检查记录见 [验证记录](validation-v2.json)，不能替代业务回归。

## 审阅补充

用户认可其余设计，并要求合并规划第二页签的插件能力与素材、统一大模型调用名称、插件逐动作完整说明及保留可重复导入入口。已更新原型。现行 PlanningService.import_generation 对 imported_task_id 返回原任务；用户现已确认每次导入创建独立新任务。正式接入须调整现行按生成记录返回原任务的语义，保留原导入关联和历史兼容；新任务具有独立标识、步骤及上下文副本，使用该生成记录的冻结证据，不影响此前导入任务。候选继续保留，校验失败不创建任务。此项设计已确认，核心尚未实现。
