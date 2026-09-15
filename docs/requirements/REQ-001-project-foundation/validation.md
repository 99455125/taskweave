# 验证记录

日期：2026-09-15；环境：macOS / Python 3.13.3。

| 检查 | 实际结果 |
|---|---|
| git fetch origin / git pull --ff-only | 成功；smart_client_easy 已为远端最新 b74e911 |
| 原文件对照 git show HEAD:<原路径> | 48 个受跟踪文件与 legacy 中目标逐字节一致 |
| python3 scripts/check_project.py | 通过：布局、新源码语法、核心导入边界、32 个 Markdown 文件相对链接和 CLI 版本 |
| 隔离临时 venv 中 pip install --no-deps . | 构建 wheel 并安装 taskweave 0.1.0 成功 |
| 临时目录中 taskweave --version / --help | 均成功，未依赖仓库当前目录 |
| 已安装包的元数据 | 包版本一致、无第三方运行依赖 |
| git diff --check | 通过 |
| 本地备份/未提交旧测试的忽略规则 | git check-ignore 检查通过 |

首次安装因本机 Python 默认 CA 路径缺失而失败；仅对验证子进程设置 `PIP_CERT=/etc/ssl/cert.pem` 后成功，未关闭 TLS 校验或修改系统配置。

未验证：Windows 环境、旧服务端到端行为、旧数据库迁移。新执行器、插件与 UI 尚未实现，不存在相应功能通过结论。

验证临时虚拟环境自动删除，验证产生的本地 build 与 egg-info 已清理；未改动原 .venv。
