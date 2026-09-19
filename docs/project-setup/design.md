# 设计说明

采用 `src/taskweave` 独立包 + `plugins/` 功能包位置 + `legacy/` 迁移来源。当前仅实现包元数据和 CLI 帮助，不提前固定任务/步骤模型及插件契约。

沿用既有 shie-agent-dev 项目的 AGENTS / AI_GUIDE / CLAUDE / TASK_TEMPLATE 与项目级、REQ 级文档方式，去掉与 Java、多仓库及再保业务相关的规则。

Git 以当前 smart_client_easy 最新提交为基线，main 路线留在原分支。旧源码整体移动以保持内部绝对导入布局；数据库、凭据及本地环境不做迁移。产品内部改名，不改变现有 IDE/Codex 工作目录和远端仓库设置。

选择 Python 3.10+ 作为新工程基线，运行依赖为空。Excel/浏览器依赖在以后有实现时分别引入。
