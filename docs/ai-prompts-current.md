# TaskWeave 当前 AI 提示词清单

本文对应当前代码中的真实提示词结构。完整固定正文以
[`src/taskweave/application/prompts.py`](../src/taskweave/application/prompts.py)
为唯一来源；该文件中的常量会直接进入模型请求。

## 场景与组装

| 场景 | 系统提示词 | 回复契约 | 历史 |
| --- | --- | --- | --- |
| 生成步骤描述 | `DOMAIN_RULES + STEP_DESCRIPTION_RULES` | 仅 `step_description`、`step_notes` | 不携带 |
| 生成步骤内容 | `DOMAIN_RULES + EXECUTABLE_STEP_RULES + STEP_CONTENT_RULES + STEP_RESPONSE_RULES` | 仅 `step_content`、`explanation` | 不携带 |
| 调试修复 | `DOMAIN_RULES + EXECUTABLE_STEP_RULES + REPAIR_RULES + STEP_RESPONSE_RULES` | 仅 `step_content`、`explanation` | 按用户选择 |
| 计划生成 | `DOMAIN_RULES + EXECUTABLE_STEP_RULES + PLAN_RULES` | `taskweave-task-2` 或 `PLAN_INFORMATION_MISSING` | 不携带 |

网页渠道追加 `WEB_CHAT_RULES`；包含 Python 的回复再追加
`WEB_CHAT_CODE_RULES`，要求 JSON 中用 `\u0020` 表示代码缩进。

## 动态材料

- `available_variables` 只发送 core 合并后的最终变量目录，每个变量只出现一次；字段为 `name/schema/required`，密钥可标记 `secret`，不发送默认实际值或来源。
- `input_dependencies` 只包含前序步骤输出绑定。
- 能力目录区分 runtime API、builtins、actions、authoring tools、result handlers、result views 和插件版本。
- 插件上下文保留名称、provider、采集时间、顺序、用户操作说明和完整正文。
- 描述、内容和计划首次生成不携带历史；调试修复按页面选择的轮次与去重设置处理。

## 输出与纠错

- 描述生成不会返回代码；内容和修复必须返回完整 `async def run(ctx, inputs)`。
- 内容不足时返回空 `step_content`，且 `explanation` 以“缺少必要信息：”开头；应用不会覆盖草稿。
- JSON 格式纠错保留上一条无效 assistant 回复和具体 Schema 错误，最多重试一次。
- 计划成功回复顶层就是任务包，不额外包 `task_package`；AI 包的每一步固定为 `DRAFT`。

## 请求大小

API 使用最终 UTF-8 JSON body 计量；网页渠道使用最终 UTF-8 提示文本计量。
工作空间设置 `ai_request_limit_kib` 默认 512，范围 1–4096。格式纠错和工具回合继续使用同一冻结上限。

## 插件提示词

Playwright、OCR、TiDB 的完整规则由各插件 `authoring()` 返回：

- `plugins/playwright/src/taskweave_playwright/__init__.py`
- `plugins/ocr/src/taskweave_ocr/__init__.py`
- `plugins/tidb/src/taskweave_tidb/__init__.py`

插件规则只描述自身能力和边界，不扩大当前步骤范围。能力目录与插件贡献完整发送。
