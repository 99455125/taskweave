# TaskWeave 工程规则

## 知识与源码

- [文档总览](docs/README.md)是知识入口，按[模块导航](docs/maintenance.md)定位受影响代码与测试；跨模块变化核对[架构](docs/architecture.md)，数据/接口变化核对[契约](docs/contracts/README.md)。
- 文档描述当前事实，精确Schema、SQL、签名及测试映射以源码为准；实现变化同步对应知识，不建立第二份操作/测试清单。

## 稳定边界

- 单一Python工程，使用uv；同步用`uv sync --locked`，运行用`uv run`，保留uv.lock，不向虚拟环境另装pip依赖。
- 修改前检查Git状态及真实依赖，保护已有修改、用户配置和数据。覆盖、丢弃、重置或迁移已有工作须有明确授权，不自动清理混合工作树。
- core不依赖GUI、数据库驱动、浏览器或模型SDK；presentation不依赖desktop或具体框架/基础设施；固定执行不调用模型，可选插件依赖不进入核心默认安装。
- 接口、任务包、SDK、序列化路径和数据库变化须核对现行实现及兼容策略，不能用文档类型代替运行时校验。

## 验证与交付

- 按[测试指南](docs/testing.md)选择受影响验证；全量测试须明确授权，不用分组拼成全量。纯文档执行`uv run python scripts/check_project.py`和`git diff --check`，不运行功能回归。
- 交付区分实际通过、失败、未运行和限制；历史证据不替代本次验证，不把fixture或包资源检查扩称真实外部服务/平台验收。
- Git commit、push、PR写操作及非本地部署按具体内容和目标分别取得授权，提交只纳入获授权内容。
