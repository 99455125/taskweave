# 历史 Smart Excel 实现

来源：`smart_client_easy@b74e911`。为后续复用保留，默认安装 TaskWeave 不加载此目录。

保留原 app、数据库、DeepSeek、Excel 工具、依赖、运行入口、测试和接口文档。内部导入布局保持原样，迁移时从此处逐项提取到新层，不整体导入核心。

## 旧入口

如需运行旧功能，在单独虚拟环境中安装本目录 `requirements.txt`，设置 `EXCEL_BASE_DIR` 为准备好的本地数据目录，再从本目录运行 `python run.py`。

这是历史启动方式，本轮未验证端到端运行。`run.py` 在加载时会初始化服务并自动生成/执行数据库迁移；历史依赖也未锁定，不应作为新工程启动方式。

`local-backups/` 和 `tests/routes/`、`tests/service/` 中原有本地文件保持未跟踪；它们不是可分发的新架构测试。原数据文件保留在原位置，未迁移。

公开发布前已将历史硬编码密钥改为 `DEEPSEEK_API_KEY` 环境变量。`test_file/` 历史样本仅本地保留，不随公开仓库分发。
