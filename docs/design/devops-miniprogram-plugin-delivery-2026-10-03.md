# 六插件源码交付与原项目集成记录（2026-10-03）

六个可选插件、两份组合示例及测试映射已完成源审查并安全集成到原项目。最终缓存资源 owner、失败证据清理和 WordPress 相对 source 三项问题均已修复，限定复审为 Spec PASS、Quality Ready，无新增 finding。本记录说明源码交付及实际证据边界；用户确认宝塔本地验收足够，且不再要求有效 uni-app AppID 的 H5 production 验收；按该口径本轮开发目标已完成。外部业务和平台未测范围仍分别记录。

## 已实现范围

| 插件 | 批准命名动作数 | 主要能力 |
| --- | ---: | --- |
| process | 3 | 有界命令、进程状态、完整产物收集与脱敏 |
| ssh | 13 | SSH命令、SFTP文件/目录及传输后核对 |
| baota_dashboard | 33 | Linux面板站点、数据库、文件、证书、任务及备份 |
| wordpress | 53 | WP-CLI核心、配置、主题插件、内容、用户、媒体、数据库和备份恢复 |
| uniapp | 5 | 被动检查、CLI/HBuilderX构建、产物核对、已有测试套件执行与报告收集 |
| wechat_dev | 26 | 微信模拟器连接、页面/元素操作断言、组件、网络、截图、日志与安全清理 |

完整集合为133，含 WordPress `delete_post`。插件 API v1、各新包0.1.0、现有任务包与数据库格式保持兼容；核心默认依赖不增加具体插件。动作详细说明见[插件入口](../../plugins/README.md)及各包 README，契约见[插件模块](../modules/plugins.md)。

[两份组合示例](../../examples/devops/README.md)分别提供建站的 BaoTa→SSH→WordPress→Playwright→备份/报告，以及 uni-app→微信模拟器→可选 TiDB→截图/日志/报告。输出经实际 Application worker 和声明式结果处理保存、重读；固定执行不调用模型、不自动安装外部工具。

## 原项目集成事实

集成前核对原474文件哈希，逐文件守卫转移83个冻结公共文件：11修改、72新增、0删除，所有目标字节与冻结源一致，清单外0修改。原有 OCR README/依赖声明保持原字节，锁文件的 OCR 包记录及原有说明保留。未复制私有 ledger、凭据、原生项目/缓存、租约或临时验收输出；未提交、重置或清理混合工作树。

原项目已实际完成锁定 Python extras 同步（exit0）和批准133动作 live Registry 精确集合/schema/resource/handler/authoring/version测试（1项/2.698秒，OK）。锁检查118包 exit0、差异空白检查 exit0；结构检查 exit1仅为原有三条历史 UI 输出断链，未制造占位文件。原项目另执行实际 Application 两步 worker 保留资源/当前失败清理脱敏检查（1项/1.824秒，OK，协议工具目标），验证整合后的运行路径；未启动nativeGUI或扩大旧套件。同步、注册和此worker检查不代表重跑全部外部动作。

## 安装和启动

以下是本次原项目实际同步的 extras，包含六新包、示例 browser/database 与已有 gui/utility；运行时不需要 OCR：

```bash
uv sync --locked --extra process --extra ssh --extra baota_dashboard --extra wordpress --extra uniapp --extra wechat_dev --extra browser --extra database --extra gui --extra utility
uv run --no-sync taskweave --help
uv run --no-sync taskweave --home .runtime/workbench serve
# 需要桌面工作台时，单独启动：
uv run --no-sync taskweave --home .runtime/workbench workbench
```

原项目解释器为 `/Users/xiaojuju/Projects/opensource/taskweave/.venv/bin/python`（Python3.14.7），六插件模块均从原项目 `plugins/` 解析、版本均0.1.0，无跨工作树引用；OCR未安装。需要配置IDE时可使用该解释器，但本次未核查 PyCharm 当前设置。启动写法按当前 `taskweave.__main__` 与[部署文档](../deployment.md)核对，本次未启动GUI。`--no-sync`复用已选 extras，避免普通默认同步移除可选包；更改所需 extras 时仍用完整 `uv sync --locked`。安装不等于环境中启用插件或准备外部 Node/HX/微信/PHP/WP-CLI/SSH/Chromium；配置和逻辑秘密引用按各 README 与[示例](../../examples/devops/README.md)完成。

## 验证分层和剩余条件

- 分模块历史证据包括实际有界 process/SSH、Linux面板与 WP-CLI、uni-app CLI/HX 和微信 SDK 工具检查，分别保留失败、UNKNOWN和后续正向记录；它们不是本次集成时全动作重新运行。
- 两示例的组合证明使用真实注册动作、worker与宿主保存。建站受控路线的面板和 WP-CLI 为协议目标，SFTP/process/HTTP/独占 headless Chromium真实，备份解包重读；面板虚拟目录与临时WP目录的映射不证明同host原生部署。小程序受控编译/SDK报告不替代真机、真实登录或后台事务。
- 快速测试与 opt-in 外部工具目标分离；未执行全量或按旧模块拼全量。选择方法见[测试规则](../testing.md)。Task7历史指定41项命令曾因枚举依赖失败并跳过单独opt-in浏览器；已保留失败记录，补齐锁定前置依赖后仅失败枚举通过，浏览器组合另有真实通过记录，不重写历史命令为PASS。
- 公网 ACME签发及续期、真实 TiDB查询和完整 coherent 外部建站未实测；宝塔按用户确认的本地验收口径交付，公网材料不再构成阻塞。有效 uni-app AppID 下的原生 H5 production 验收已按用户要求取消；其历史未实测记录保留，不再作为交付阻塞。Windows原生租约安全原语准备、Windows实机/真机、工具root身份与网络/清理限制按各插件README保留。
- 非阻塞 M1 内部类型建议仍待后续；原有 OCR安装/识别未验收。上述未测范围保留；用户确认的本地验收范围已完成，不宣称这些外部用例通过。

## uni-app 模拟器验收范围确认（2026-10-03）

2026-10-03 用户确认：uni-app 微信模拟器自测已完成，不需要有效 uni-app AppID；取消有效 DCloud AppID 下原生 H5 production 的本次交付验收要求。历史未实测记录保留，不改写为通过。已验证的微信模拟器运行使用 touristappid 游客模式，启动和附着均覆盖26动作；DCloud AppID与微信项目AppID分别配置。 页面导航、触摸/输入、组件与数据断言、存储、mock恢复、截图和日志均有真实开发者工具记录；请求与登录回调的 mock 已验证，结论不扩展为真实服务端登录。

## 宝塔本地验收与交付结论（2026-10-03）

2026-10-03 用户确认宝塔按本地验收即可，不要求公网证书签发和续期的真实外部验证；此前已取消有效 DCloud AppID 下原生 H5 production 验收要求。按这一确认口径，六个可选插件、133动作、两份组合示例、依赖/映射/文档及原项目集成完成。公网签发/续期、H5 production和其他外部目标历史未实测范围保留，不改写为通过；本地与受控协议证据按实际类型记录。 本轮未运行全量测试、未提交代码，保留原有 OCR 修改；结构检查仍有3处原有历史UI证据断链。
