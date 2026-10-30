# 步骤编写与校验（Authoring）

## 职责

本知识模块对应产品内的步骤编写与校验，跨application、presentation和desktop三个实现层。它涵盖AI生成/修订、描述生成、调试修复候选、提示导出/Chat回复解析，也包括当前Authoring类承载的无模型校验和插件诊断；与研发AI协作流程无关。固定执行不调用模型。

## 当前源码的职责对应

| 责任 | 当前实现 | 调用关系 |
| --- | --- | --- |
| 步骤内容/描述生成、对话材料 | application/authoring.py的generate、generate_goal、reset_conversation | step.generate、step.generate_goal及桌面编写入口 |
| 步骤静态校验与插件lint | Authoring.validate_step | 步骤保存/校验、任务包验证及正式运行创建都会复用；这条路径不调用模型 |
| 插件失败诊断 | Authoring.diagnose | step.diagnose根据attempt证据调用插件诊断，不等同于模型修复生成 |
| 共享在途请求 | application/authoring_sessions.py的AuthoringRequests | 按步骤保留请求，多个Controller复用 |
| 普通交互与候选采纳 | presentation/authoring.py、chat.py | StepAIEditor实际绑定；负责草稿、忙状态、身份及解析/采纳决定 |
| 规划模型调用支撑 | PlanningService读取authoring.model并调用authoring._complete | 当前存在跨服务复用，规划快照/生成记录/导入仍由PlanningService负责 |

Authoring还保留一次性collect_context/context_targets辅助入口；当前常规context.read/targets通过ContextUseCases进入ContextSessions或运行Coordinator，采集持久化与活跃会话不归Authoring统一管理。详见[上下文模块](contexts.md)。

当前类的实际范围比“仅AI生成”更广。这里按源码记录校验、诊断与共享模型调用的落点，不将它们描述成已经拆出的独立服务。

## 当前行为

- application/prompts.py组合提示；Authoring汇集插件能力、步骤契约、上下文和用户选定反馈。API模型与网页Chat渠道共用业务校验，网页渠道通过提示与附件交付材料，桌面端以同一个 ZIP 下载完整对话与所选附件，并提供只读文件预览。
- 输出是候选，必须经本地解析/验证及用户采纳。版本、当前编辑代码、原请求以及修复run/attempt身份变化时，不采纳旧结果。
- 修复不要求失败记录：未调试或调试成功但行为不符合预期时，可根据本轮要求修订代码；存在当前步骤的有效失败尝试时携带该依据并重新核对运行/尝试。历史按用户选择的全部、不携带或最近轮数处理，与是否存在失败依据无关；移除的反馈字段继续从请求中排除。采集预览仅在send_preview开启时发送，图片通过模型支持的图片消息或网页附件传递。
- AI请求大小默认2048KiB，设置范围1–16384KiB；统计实际材料预算，超限在发送前拒绝。该值不是HTTP传输上限，也不保证模型上下文容量足够。
- AuthoringRequests在共享应用会话中按步骤保留最新请求，最多16个步骤槽位，只回收已完成项。同一步骤在途请求阻止重复生成；UI取消等待不取消已接受模型调用。服务重启不保留请求。
- AIInteraction/AIChoiceDraft管理本地弹窗草稿、忙状态和选择身份；AuthoringFlow协调生成、修复及确认，实际NiceGUI绑定相同对象。网页文本解析位于presentation/chat.py。

## 依赖边界

Authoring依赖core资源工厂接口，由composition注入ResourceSessionFactory，不直接构造worker内部资源或具体结果设施。模型协议位于core/model_ports.py，HTTP模型适配位于infrastructure/model.py。可选插件的编写贡献不能越过插件声明的能力与数据边界。

## 代码与验证

[Authoring](../../src/taskweave/application/authoring.py)、[提示](../../src/taskweave/application/prompts.py)、[请求预算](../../src/taskweave/application/ai_requests.py)、[共享请求](../../src/taskweave/application/authoring_sessions.py)、[交互](../../src/taskweave/presentation/authoring.py)、[UI](../../src/taskweave/desktop/components/step_ai.py)。

测试键application.authoring、ui.debug；检查失败保留草稿、Chat解析、预算、请求恢复/防重、切换步骤后隔离、候选采纳以及资源异常清理。模型替身测试不等同于真实账号或模型能力验证。

## 本地生成候选

步骤代码页对选用支持插件的草稿显示“本地代码生成”。录制仍在上下文完成；本地生成与 AI 编写读取同一份保存材料，生成不消费它，不启动浏览器或模型。`application/codegen.py`负责材料归属和摘要、输入绑定及候选契约；插件负责纯转换。`presentation/codegen.py`维护普通候选状态、草稿身份、插入及差异；`desktop/components/step_codegen.py`提供材料选择、参数补充、完整预览和确认应用。

录制上下文选择框旁提供“刷新上下文”，直接重读当前步骤保存的录制列表并反馈可用数量，无需切换页面。已有选择仍有效时保留选择；材料变化沿用候选失效规则，刷新不修改代码草稿。

录制值需明确绑定已有字符串输入或保留完整常量，敏感值只能绑定输入；材料、代码、Schema 或插件改变时需重新生成。插入保留原 return，替换显示差异并确认；结果仅更新草稿，保存与调试沿用现有流程。静态通过不代表输出 Schema 或业务断言已验收。验证目标通过 tests/module-map.json 的 application.codegen / ui.codegen 定位。

本地生成预览显示实际候选源码；未生成可用代码时直接展示阻塞原因，不展示或提供复制示意模板。旧录制缺少选页证据、录制中额外开页、未支持交互和未确认文档等问题分别说明。新录制的所选页可在运行时唯一解析目标，所有生成动作绑定同一页面；插入会重命名与草稿冲突的临时变量。
