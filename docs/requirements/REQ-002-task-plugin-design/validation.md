# REQ-002 验证记录

2026-09-16，macOS / Python 3.13.3。

| 命令/检查 | 结果 |
|---|---|
| python3 scripts/check_req002.py | 8 项通过 |
| python3 scripts/check_project.py | 结构、源码语法、Markdown 链接与 CLI 通过 |
| git diff --check | 通过 |

## 实际检查覆盖

- TaskDocument 指向正确 step，插件 capability 引用完整，示例源码与 JSON 一致。
- Python 入口符合单 async run(ctx, inputs)，类型协议可导入。
- 模拟上下文下：仅状态、有数据无截图、有截图、标题为空业务断言、输入类型错误、未声明能力拒绝。
- 两份 DDL 可执行，总库无步骤版本表，验证 hash 约束、单租约、跨任务外键和尝试唯一性有效。
- 临时任务库同名业务表互不污染，结果 receipt 去重。

## 限制

这些是设计契约检查，不是产品测试。fixture schema 检查只覆盖示例中的 type/properties/required/additionalProperties，不是完整 JSON Schema 校验器；REQ-003 需使用合规校验器。

未运行真实模型、Playwright、Windows worker、UI、跨库崩溃恢复和离线安装，相关验证归属 REQ-003～007。模拟 ctx 不证明真实浏览器可用。没有新建生产数据库、读取真实任务数据或改动 legacy。

## 可实施性评审

职责无环：REQ-003 消费 REQ-002 的端口并使用模拟适配，REQ-004 接真实插件，REQ-005 接 UI。配置无历史版本；插件/schema 的兼容版本仍保留。结果为空不建任务库，持久化失败不等于外部业务失败。

评审调整检查：任务库写入步骤输出后关闭并重新打开，验证仍可按 run/step/attempt 读取且不串用其他运行；这仅验证设计 DDL，实际绑定执行器与插件解析尚未实现。
