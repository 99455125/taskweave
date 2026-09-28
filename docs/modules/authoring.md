# AI 步骤编写

产品内 AI 辅助编写服务，与研发 AI 协作文档无关。生成、修订、试跑、确认分别有明确入口；固定任务执行不调用模型。

## 当前行为与约束

- 支持手写、API 模型生成、网页 Chat 导出/粘贴回复；统一使用步骤内容与插件契约。提示词集中在 prompts.py，模型适配在基础设施层。
- AI 返回候选，本地解析/校验和差异预览后由用户采纳。模型响应不能直接当作运行成功，也不能覆盖已切换步骤的新草稿。
- 所选插件贡献能力、规则、示例、上下文和渠道覆盖；网页渠道只导出文本，不假装能访问本机工具。插件不能越过公共能力约束。
- 普通生成与基于调试历史修复区分处理；历史按用户选择组织，不默默压缩或丢弃选中内容。请求容量检查位于 ai_requests.py；已知失败见当前状态，不因文档整理改业务策略。
- 生成失败保留草稿；调试修复绑定正确步骤和运行，迟到响应不能写入新页面。debug 与 AI 组件共享同一个 trials 会话对象。
- 修复弹窗按当前运行读取最新有效失败尝试与反馈，因此清空 AI 缓存后仍可引用真实运行/尝试编号继续修复。打开或取消弹窗只读运行证据；提交前复核步骤、运行及尝试身份，并继续应用用户移除的反馈字段。
- 输出提示遵守隐私配置；环境/任务本地存储可含普通密钥值，不代表可以原样发给模型。

## 代码入口

[编写服务](../../src/taskweave/application/authoring.py)、[提示词](../../src/taskweave/application/prompts.py)、[请求容量](../../src/taskweave/application/ai_requests.py)、[模型适配](../../src/taskweave/infrastructure/model.py)、[隐私处理](../../src/taskweave/infrastructure/privacy.py)、[AI UI](../../src/taskweave/desktop/components/step_ai.py)。

## 验证入口

`application.authoring`、`ui.editor`、`ui.debug`，实际依赖使用 changed dry-run。检查 API/Chat 回复校验、容量与历史选择、失败保留、步骤切换后的响应隔离；模型 fixture 通过不等于真实服务账号验收。关联知识：[任务与步骤](tasks.md)、[上下文](contexts.md)、[插件](plugins.md)。

## 按需深入

[AI请求与历史](../reference/authoring.md)。只在本次修改涉及相应契约时阅读。

## 选择发送采集预览

采集项的标题、操作说明和正文进入生成/修复材料。只有 `send_preview` 开启才携带该项插件预览：图片为实际图片消息，表格等为结构化 JSON。HTTP 适配器支持 data URL 图片消息，所配置模型仍需支持视觉输入。网页 Chat 提示词引用可下载的图片附件，用户需一并上传，不把 base64 字符串当作文本图片。请求上限核对包括预览数据；文本脱敏不截断或改写图片字节。
