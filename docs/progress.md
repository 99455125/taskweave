# 项目进度

## 2026-09-15 · REQ-001

- `git fetch origin` / `git pull --ff-only` 完成，当前来源 `smart_client_easy` 已是最新，提交 `b74e911`。
- 在 `codex/taskweave-foundation` 上整理；原分支及本地 main 的独有提交保留。
- 产品命名为 TaskWeave，新增独立 Python 包、版本/帮助入口和模块目录。
- 原实现移至 `legacy/smart_excel`；默认安装不包含旧依赖和旧业务文件。
- 删除旧 PyInstaller 构建产物、专属 spec 和缓存；本地用户测试、备份保留并忽略。
- 建立 AI 工作流、工程规范、架构、计划、需求模板与验证文档。
- 新执行器、插件实现、UI 和数据迁移均未开始。

具体验证记录见 `requirements/REQ-001-project-foundation/validation.md`。下一步由用户发起功能设计需求。

## 2026-09-15 · 仓库发布

本地目录改名为 taskweave，新仓库为 `99455125/taskweave`（public），仅发布 main。旧历史本地保留，新仓库使用干净初始提交。旧密钥改为环境变量，历史数据样本仅本地保留。
