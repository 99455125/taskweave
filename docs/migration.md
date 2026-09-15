# 结构迁移记录

## Git 基线

- 原分支：`smart_client_easy`，提交 `b74e911`（2025-06-20）。
- 同步：2026-09-15 fetch + pull --ff-only，Already up to date。
- 新工作分支：`codex/taskweave-foundation`。
- 远端 main：`0ae1728`（2025-06-06）；本地 main：`79a466a`，含本地独有历史。
- 两条实现路线未强行合并。main 中的 TaskExecution、StepExecution 和 PyQt 客户端后续可从对应 Git 分支参考，不能误认为当前 legacy 已包含它们。

## 路径映射

| 原路径 | 新路径 |
|---|---|
| app、db_server、deepseek、log、tools | legacy/smart_excel/ 同名目录 |
| run.py、enviroment_config.py、requirements.txt | legacy/smart_excel/ 同名文件 |
| tests、test_file | legacy/smart_excel/ 同名目录 |
| docs/routes_*_api_docs.md | legacy/smart_excel/docs/ |
| 未命名文件夹（未跟踪） | legacy/smart_excel/local-backups/（忽略） |

原源码仅移动，未重写业务逻辑。旧测试目录中的本地未跟踪测试保留，但不纳入本次新增代码。

## 清理

删除未跟踪的 `build/`（约 72 MB）、空 `dist/`、含个人绝对路径的 `smartexcel.spec`，清理项目内缓存与 `.DS_Store`（不触碰 `.venv`、`.git`、`.idea`）。新增忽略规则防止重复进入 Git。

## 改名范围

内部产品、包、命令和文档改为 TaskWeave / taskweave。物理目录仍为 `smart_excel`，远端仍为 `https://github.com/99455125/smart_excel.git`。没有发布公共包或修改 GitHub 设置。后续若改远端名称，同步所有 clone 的 origin；若移动本地目录，重新打开 IDE/Codex 并重建含绝对路径的虚拟环境。

## 回退

本次未改旧数据库。历史源码可通过旧分支读取。切换分支前先保存当前未提交变更；不要使用清理未跟踪文件的命令处理保留的用户文件。

## 2026-09-15 · 新仓库发布调整

按用户要求，本地目录改为 `/Users/dasensen/PycharmProjects/taskweave`，新建公开仓库 `99455125/taskweave`，只发布 `main` 分支。以上“改名范围”为第一轮记录，以本节为最新状态。

旧 origin 改名为 legacy-origin；原本地 main 分支保留为 legacy-main-original。新 main 使用干净的初始提交，不携带旧历史。原历史中发现硬编码 API 密钥，归档代码已改为读取 `DEEPSEEK_API_KEY` 环境变量；建议撤销/轮换旧密钥。历史 Excel 数据样本保留在本地且被忽略，不公开发布。原源码逐字节验证是第一轮结果，本轮密钥配置为有意变更。
