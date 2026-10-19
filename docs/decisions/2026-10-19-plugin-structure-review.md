# 十一插件结构复核

本记录是[已批准架构优化方案](2026-10-19-architecture-optimization.md) F 工作包的局部证据，不另建需求或进度体系。复核依据为当前工作树源码、独立包声明、入口注册与实际消费者；保留实施前 Playwright、TiDB 和 OCR 的未提交修改。没有更改插件 API、版本、动作参数、结果形状、可选依赖或数据库格式。

## 逐项结论

| 插件 | 结论 | 代码依据与处理 |
| --- | --- | --- |
| Playwright | 已整改 | 原入口同时包含 BrowserSession、定位/快照、BrowserAction、FileResult、上下文采集和装配；分别迁入 session、locators、browser_actions、results、context、plugin，schema 独立共享。现有 observation/actions/side_effects/protocol/recording 保持职责。入口仅显式导出。 |
| TiDB | 已整改 | execution 原先从包入口导入 configuration/wire_value，SQL 执行依赖插件装配。配置、只读查询与 wire 值处理迁入 database，execution 直接依赖共享实现，原入口重导出。既有 TiDB 原生只读 TSO 事务、MySQL READ ONLY、查询主因及清理异常保留。 |
| OCR | 保留 | 95 行单文件围绕一个识别动作；image_bytes 校验、LocalOcr 线程/模型生命周期、Recognize 执行职责可定位。PIL/ddddocr 在使用时导入，不依赖浏览器或宿主实现；没有强行增加目录层级。 |
| file | 保留 | 单一有界读取流程，由 source_path/read_file/ReadFile 分层；没有把内容读取与 SQL 执行合并。SDK 是唯一宿主依赖，无第三方依赖。 |
| utility | 保留 | Now/Uuid/DecimalCalculate 为三个独立小动作，使用标准库及 SDK，注册/编写声明很小；不需要会话或通用服务对象。 |
| process | 保留 | runner 负责命令与诊断，session 负责自有长驻进程，artifacts 负责有界文件，context 负责遮蔽及采集，actions 负责注册动作；普通库接口显式导出，被其他插件复用。 |
| ssh | 保留 | transport/paths/transfer/actions/context 已区分连接、路径、传输、动作和采集；通过 process 普通库复用文件 handler 与命令诊断，并在包依赖中声明 process。没有调用宿主 worker 或跨插件资源注册。 |
| baota_dashboard | 保留 | endpoints 固定接口声明、client 协议/认证、actions 业务步骤/结果证据、context 采集已分开；动作步骤及其写入证据必须共同保持部分完成语义，本次未发现必须再次分割的依赖问题。 |
| wordpress | 保留 | commands/transport/backup/actions/context 分别负责命令验证、站点传输、备份协议、业务动作和采集；通过 process/ssh 普通库复用执行与连接，独立包明确声明依赖；不复制宿主执行协议。入口的小型 provider/JSON handler 与注册关系直接。 |
| uniapp | 保留 | project/build/tests/lease/redaction/context/actions 已按工程证据、构建、报告、原生租约、隐私、采集及动作组织；process 依赖显式声明。ProjectSession 与动作共享操作日志所有权，此次不机械拆类。 |
| wechat_dev | 保留 | configuration/bridge/capture/qrcode/release/context/actions 已分离配置、模拟器通信、截图、二维码、独立 CI 发布和采集；Node bridge/CI 包资源由本插件声明。模拟器资源与发布证据分开持有，普通进程所有权复用 process。 |

所有 Python 插件的宿主导入均为 `taskweave.plugins.sdk`；新增 AST 守卫防止插件导入 application、infrastructure、desktop 或其他宿主内部路径。宿主 SDK/registry 在禁用浏览器、数据库、OCR 和 GUI 依赖导入的独立进程中可导入。该检查验证依赖方向，不代表每项外部服务功能已经执行。

## Playwright 兼容与调用链

- entry point 继续为 `taskweave_playwright:PlaywrightPlugin`；各包版本、API v1、setuptools 包发现规则均不变，新增模块属于既有 Python 包。
- 原 BrowserSession、BrowserAction、ReadTool、FileResult、PlaywrightPlugin、schema/常量、locate、target_state、snapshot、page_for、_live_context_targets 路径保留显式导出。旧 pickle GLOBAL 类路径仍可解析；新实例序列化往返使用同一个实际类。
- BrowserSession → session 资源/页面身份；BrowserAction → locators、现有 actions/side_effects；插件装配 → context/results。这些模块各有唯一实现，没有双写逻辑。
- 两个既有替换钩子 `taskweave_playwright.async_playwright` 和 `taskweave_playwright.snapshot` 有实际测试消费者。`_compat` 仅在调用时解析这两个命名钩子，以保留启动替身、上下文截图替身及录制迟到快照测试；默认调用 canonical 实现。其他内部依赖直达负责模块，recording 的页面身份查找已转向 session。
- 所有类移动保持构造签名和方法实现；运行资源仍属宿主生命周期，未改变页面选择、主页面、取消、超时、异常与结果保存行为。

## 验证与集成要求

既有基线命令：

```bash
env -u PYTHONPATH uv run python -m unittest tests.test_plugin_contract tests.test_context_targets_playwright tests.test_workbench_changes.WorkbenchChanges.test_playwright_task_parameters_override_environment tests.test_tidb tests.test_tidb_execution
```

修改前执行 45 项，通过。新增 `tests.test_plugin_architecture` 首次执行明确因职责模块及 TiDB 共享实现缺失而失败（7 个断言失败）；拆分后边界断言通过。该文件还检查旧类路径 pickle、11 个声明 entry point 的加载/注册及可选依赖隔离。

修改后的同一定向命令另加入 `tests.test_plugin_architecture`：52 项全部通过（1.927 秒），包含两个真实 worker/本地受控数据库协议用例；不连接外部数据库。`git diff --check` 对本工作包文件通过。中途发现运行工作包并行迁移导致 `run_coordinator.py` 缺少 os 导入，已反馈负责人；没有修改插件测试期望掩盖失败。

映射：Playwright 现有 `*.py` glob 覆盖新增模块；TiDB 需要覆盖 database.py；插件快速目标需登记 `tests.test_plugin_architecture`。公共 module-map 由主 Agent 维护。changed dry-run 首次受其他工作包新增源码尚未映射阻断，完整映射后统一复核。

真实 Chromium 集成、worker spawn 与打包/冻结资源收集交由主 Agent 串行验证；本局部记录不将未运行的平台或外部服务验收写成通过。其他九插件只做本次结构、依赖和入口复核，没有运行它们的外部业务系统或安装任何工具。
