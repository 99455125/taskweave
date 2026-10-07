# 开发运维与小程序自动化插件完整设计

日期：2026-10-02。状态：用户已明确回复“设计通过”，尚未实现。实施入口见[完整实施计划](../plans/2026-10-02-devops-miniprogram-plugins.md)。

## 用户目标与交付

完成 process、ssh、baota_dashboard、wordpress、uniapp、wechat_dev 六个独立可选插件的全部下列能力，不拆首期。支持远程运维、宝塔 Linux 建站、WordPress 管理和 uni-app 构建＋微信开发者工具模拟器自测。原有 Playwright/OCR/TiDB/file/utility 继续可用，固定步骤不调用模型。

交付产品代码、动作契约、资源生命周期、编写贡献、观察上下文、结果处理、依赖锁、使用说明、两个组合示例和模块测试。通用任意命令入口或静态能力列表不能代替结构化业务动作。原有 OCR 依赖升级修改保留，本次不改变其未安装、未验证状态。

实现与验收证据分别登记真实本地/受控服务执行、协议测试、用户外部目标验收；不以模拟响应冒充真实微信/宝塔/WordPress验收。外部目标不可用时继续完成独立实现，保留真实验收缺口，不将整个目标标完成。

## 架构、兼容与依赖

- 单一 Python 工程，Python >=3.10，使用 uv。plugins/ 下独立包，通过 taskweave.plugins entry point 注册，宿主新增同名 extras 与 tool.uv.sources，并更新 uv.lock。
- 保持插件 API v1、python-async-v1、taskweave-task-2 和数据库格式不变。新增插件 package_version=0.1.0；无可选扩展的旧插件维持原行为。
- core 不引入 SSH、Node、HTTP 客户端或具体插件默认依赖，UI 不增加插件专属分支。
- process 提供普通 Python 进程库，ssh 提供普通 Python SSH 运输库；wordpress 按执行模式复用这些库，uniapp/wechat_dev 复用进程库。业务动作不通过 ctx.call 相互调用，不跨插件借用连接对象。
- 进程使用 asyncio 子进程；SSH 使用异步客户端，其兼容版本在实施时核对 Python 3.10/3.14 支持。宝塔使用有界 HTTP 请求和 TLS 校验，不携认证跨主机重定向。
- Node、包管理器、HBuilderX、微信开发者工具、PHP、WP-CLI 是明确配置的外部工具，不自动下载、不擅自修改项目依赖。wechat_dev 提供固定用途 Node 桥接，使用官方 miniprogram-automator；uniapp 执行项目已有 uni-automator 用例。
- 通过既有 ctx.resolve_secret(reference) 解析环境的 secret_refs 映射：逻辑引用名映射到 env:变量名，再读取该环境变量。动作不得把逻辑引用名直接当环境变量名，引用未配置或变量不存在时报 SECRET_UNAVAILABLE。日志、输出、上下文和示例不包含秘密值。连接/进程对象保留在所属 worker 的 ResourceProvider 中。

## 通用契约与资源

每个动作独立声明 CapabilitySpec 的输入/输出 schema、READ/WRITE、timeout_ms、retry_safe、resource_ids，拒绝未知字段。配置合并 environment/task_parameters，任务参数优先。连接、进程、元素对象不能作为 JSON 结果传播。

本地命令使用 executable＋args 数组，不拼接 shell。SSH argv/cwd/env 按 POSIX 引用编码，明确远程 exec 经 shell；任意远程脚本单独列为 WRITE。标准输入支持秘密引用，不回显秘密参数或主机完整环境。

通用执行结果为 exit_code、stdout、stderr、stdout_truncated、stderr_truncated、duration_ms。双流持续排空，默认每流 64 KiB，可设 1 KiB–1 MiB；超限标记截断，不无限积累。正常非零退出保留真实退出码，业务动作据此报告失败。

默认命令超时 60 秒，范围 1–1800 秒，动作预算匹配；开始前和运行中检查取消。本地终止本次进程树并回收，不终止用户已有进程。远程尝试结束命令并关闭资源，但副作用可能未知；关闭连接不是回滚。写操作不自动重试，批量操作逐项保留部分成功和未知状态。

传输默认 16 MiB，可设至 64 MiB；完整文件超限拒绝，日志可截断并返回游标。产物使用 ctx.allocate_file 与声明式 ResultHandler，步骤显式纳入 ctx.result(outputs=...)。本地/远程路径限于配置根，核对符号链接；不提供任意主机路径写入。不宣称业务数据自动全面脱敏。

## process 本地进程

| 动作 | 行为 |
| --- | --- |
| process.check_environment | 指定程序、版本参数、目录检查；READ |
| process.run | 程序、参数、cwd、环境、秘密标准输入、超时取消、双流与退出码；WRITE |
| process.collect_artifacts | 根内指定文件列表，数量/大小预算、摘要、宿主暂存与保存；READ |

命令库与插件动作分离，供业务包复用；不维持永久后台进程。处理参数特殊字符、秘密遮蔽、找不到程序、目录错误、权限错误和进程清理。

## ssh SSH / SFTP

资源 ssh.connection 按 role 保存 SSH/SFTP 会话。配置目标、端口、用户、known_hosts、key_path、key_passphrase_ref/password_ref、SSH Agent 和远程根。主机身份不符不降级；认证/连接失败、超时、未知副作用分别报告。

| 动作 | 行为 |
| --- | --- |
| ssh.check_connection | 握手/认证、服务器信息；READ |
| ssh.exec / ssh.run_script | argv 或显式脚本、cwd/env/stdin、退出码与有界输出；WRITE |
| ssh.stat / ssh.list_directory | 根内属性与有界目录；READ |
| ssh.read_file / ssh.read_logs / ssh.checksum | 完整文件、有界日志与游标、SHA-256；READ |
| ssh.upload / ssh.download | 指定来源与目的、覆盖策略、字节数/摘要核对；上传 WRITE，下载保存宿主暂存 |
| ssh.mkdir / ssh.move / ssh.remove | 显式写操作；递归删除显式指定，禁止删除根；WRITE |

realpath/父目录/符号链接检查，上传先写临时文件再改名，默认拒绝覆盖；失败清理本次临时文件。ssh.server 上下文仅包含脱敏目标标识和有界目录信息。

## baota_dashboard 宝塔 Linux

官方面板 API request_time/request_token 签名；配置显式 URL、秘密引用、TLS CA 和超时。校验响应业务状态与结构，HTTP 200 不等于业务成功。版本适配表记录端点支持和证据；不支持时报 BAOTA_DASHBOARD_CAPABILITY_UNSUPPORTED，不猜端点或退回任意 shell。

| 能力组 | 动作 |
| --- | --- |
| 环境 | baota_dashboard.check_connection/system_status/list_software/list_php_versions |
| 站点 | baota_dashboard.list_sites/create_site/configure_site/set_site_status/list_domains/add_domain/remove_domain |
| 配置 | baota_dashboard.get_site_config/set_site_config/get_rewrite/set_rewrite/set_php_version/check_config/reload_service |
| 数据库 | baota_dashboard.list_databases/create_database/set_database_credentials/set_database_access/delete_database |
| HTTPS | baota_dashboard.get_certificate/deploy_certificate/request_certificate/renew_certificate/set_https |
| 运维 | baota_dashboard.create_backup/list_backups/restore_backup/task_status/read_logs |

表内斜线表示同一命名空间的独立动作，不是统一任意 operation 入口。查询 READ，修改 WRITE。创建前查询名称，已存在核对配置、不隐式覆盖。证书受理与签发分别返回，备份恢复核对归属/目标；批量失败保留实际结果。所有承诺动作需有可执行适配和错误路径。baota_dashboard.site 上下文提供站点状态/配置摘要。

已核对官方 PDF：签名为 md5(str(request_time) + md5(api_secret))，请求使用 POST。系统信息 /system?action=GetSystemTotal 没有统一 status 包装；站点列表 /data?action=getData&table=sites 返回 data/page；建站 /site?action=AddSite 分别返回 siteStatus/ftpStatus/databaseStatus，且可能包含 ftpPass/databasePass，必须按动作核对成功并删除秘密字段后返回。禁止使用统一 response.status 判断所有端点。

官方 PDF 已明确站点/PHP/域名/文件配置/备份创建与列表等端点，但未完整列出本设计中的证书、数据库和恢复全部接口；这些能力仍在交付范围，实施前需取得当前官方客户端源码或目标版本请求结构作为适配依据，不能把未核对的接口标为已支持。观察响应大小预算包含分页数据，不能无限自动翻页。

## wordpress WordPress / WP-CLI

资源 wordpress.site 使用 local/ssh 模式、WP/PHP 路径、站点路径和执行用户；独立拥有运输资源，不要求启用 ssh 插件动作。结构化参数执行，不默认 --allow-root 或任意 PHP eval。

| 能力组 | 动作 |
| --- | --- |
| 环境/核心 | wordpress.check_environment/is_installed/core_download/core_install/core_update/verify_checksums |
| 配置 | wordpress.config_create/config_get/config_set/option_get/option_set/set_permalink_structure |
| 主题 | wordpress.list_themes/install_theme/activate_theme/update_theme/delete_theme |
| 插件 | wordpress.list_plugins/install_plugin/activate_plugin/deactivate_plugin/update_plugin/delete_plugin |
| 内容 | wordpress.list_posts/create_post/update_post/delete_post，post_type 覆盖文章和页面 |
| 分类 | wordpress.list_terms/create_term/update_term/delete_term |
| 菜单 | wordpress.list_menus/create_menu/delete_menu/add_menu_item/update_menu_item/delete_menu_item |
| 媒体 | wordpress.list_media/import_media/update_media/delete_media |
| 用户 | wordpress.list_users/create_user/set_user_role/set_user_password/delete_user |
| 数据/维护 | wordpress.db_export/db_import/backup/restore/search_replace/cache_flush/set_maintenance_mode |

每个动作独立标 READ/WRITE。列表 JSON 有数量预算；写操作不可自动重试。创建先检测目标状态，文章不按标题强制去重。密码用秘密引用和标准输入/受控临时文件，不持久化秘密命令参数；配置读取默认拒绝秘密字段。

search_replace 默认 dry_run=true，执行须显式切换，核对表范围和影响数；动作整体保守标 WRITE。backup 包含数据库＋站点文件及清单/摘要；restore 校验清单、目标与完整性，拒绝包路径穿越，报告部分恢复，不覆盖其他站点。wordpress.site 上下文含版本、主题/插件和有界页面摘要。

## uniapp 项目与构建

配置项目根、CLI/HBuilderX 类型、Node/包管理器/HBuilderX 路径、平台构建/测试脚本映射、产物相对目录和环境。版本依据目标项目要求，不强制最新 Node，不转换用户项目结构。

| 动作 | 行为 |
| --- | --- |
| uniapp.inspect | 项目类型、Vue/工具版本、依赖脚本、manifest/AppID/pages；正确解析 JSONC/注释 |
| uniapp.build | 指定平台/环境的项目脚本或官方 HBuilderX CLI；微信和 H5 实际适配，WRITE |
| uniapp.check_artifact | 输出目录、app.json/project.config.json、AppID、页面资源与本次构建来源，识别旧产物 |
| uniapp.run_tests | 已有 uni-automator/项目测试脚本、文件/用例筛选、退出码和失败汇总，WRITE |
| uniapp.collect_report | 有界收集明确目录中的报告、日志、截图，交给宿主保存 |

缺少依赖/脚本报准备要求，不猜命令或自动安装。静态产物与实际启动证据分别记录；缺报告/失败不能变成通过。uniapp.project 上下文含平台配置、可用脚本和构建结果。

## wechat_dev 微信模拟器

资源 wechat_dev.simulator 为官方 miniprogram-automator 的 Node 桥接进程；JSON 行协议有请求 ID、错误码和大小限制。工具对象留在桥接端，断线后旧句柄失效。启动/附着到指定编译项目并核对项目身份，支持 uni-app 产物及原生小程序。

| 能力组 | 动作 |
| --- | --- |
| 环境/会话 | wechat_dev.check_environment/connect/disconnect；区分本次启动与用户已有实例 |
| 页面 | wechat_dev.current_page/page_stack/navigate；navigateTo/redirectTo/navigateBack/switchTab/reLaunch |
| 观察 | wechat_dev.observe/get_element/get_page_data；元素/字段/字节预算 |
| 交互 | wechat_dev.tap/input/scroll/touch/call_component_method；显式方法，不默认任意 JS |
| 断言/等待 | wechat_dev.assert_page/assert_element/assert_page_data/wait_for；有限超时 |
| 存储 | wechat_dev.get_storage/set_storage/remove_storage/clear_storage；测试命名空间，清空显式指定 |
| Mock | wechat_dev.mock_method/restore_mock；明确 wx 方法和返回配置，会话结束恢复 |
| 证据 | wechat_dev.screenshot/read_logs；当前会话/页面身份、模拟器截图、有界环形日志与游标 |

首次登录、服务端口、AppID 和权限由开发者准备，检查动作给分项结果。缺权限或不支持的接口明确报错；mock 不当作真实登录验收。关闭释放桥接及本次资源，不退出用户已有工具。wechat_dev.page 上下文只观察，不点击/改页面，提供摘要和截图预览。模拟器证据不等于真机证据。

## 组合示例与验收

建站示例：宝塔准备站点/数据库 → SSH 传输 → WordPress 安装/配置/内容 → Playwright 页面核对 → 备份与报告。

小程序示例：uniapp.inspect/build/check_artifact → wechat_dev.connect → 页面操作/断言 → TiDB 数据核对 → 截图/日志/报告；另提供已有测试套件入口。示例只有变量和秘密引用，无真实凭据或推测成功结果；步骤以 JSON 结果绑定组合，不传连接对象。

| 范围 | 必需证据 |
| --- | --- |
| 发现/兼容 | 六包 entry point、manifest/schema/资源/编写工具一致、extras 可安装、核心依赖隔离、旧插件回归 |
| process | 真实子进程成功/非零退出、特殊 argv/stdin、双流超限、取消/超时、进程树清理、产物逃逸 |
| ssh | 临时真实 SSH/SFTP 握手/传输、身份/认证失败、符号链接/覆盖/摘要/超限、取消超时 |
| baota_dashboard | 官方适配逐动作核对；受控协议签名/业务失败/版本/超大响应/部分成功；实际隔离站点配置/数据库/HTTPS/备份 |
| wordpress | 参数/秘密/失败/解析测试；隔离站点实际核心、主题插件、内容菜单媒体用户、备份恢复、域名预演和执行 |
| uniapp | 临时 CLI 真实执行与失败/取消/JSONC/旧产物；实际 CLI/HBuilderX 微信/H5 构建和报告 |
| wechat_dev | 桥接身份/断线/大小/错误测试；实际模拟器导航、交互组件、观察断言、存储、mock恢复、截图日志 |
| 组合 | 两示例真实动作→宿主结果保存；失败不标成功；用户外部目标权限/未验证项单独记录 |

按 tests/module-map.json 登记六插件测试与必要反向依赖；遵守 docs/testing.md，仅验证影响模块，不跑全量或分组拼成全量。真实工具/浏览器测试显式选择。新行为测试先失败再实现；锁解析/结构检查不替代功能验收。

## 当前进度

已完成完整范围汇总、SDK/架构核对和书面设计审批。待实施计划审阅及执行方式、全部产品实现、依赖/示例/文档、模块测试和真实目标证据。不自动提交、重置或清理混合工作树。目标保持完整范围，未完成真实验收不宣称全部完成。

### 本机验收准备检查（2026-10-02）

以下是实际路径/版本检查，不代表工具已登录、接口可连接或功能验收通过；未启动开发工具、未安装软件、未改工具设置。

| 工具 | 当前证据 | 尚待核对 |
| --- | --- | --- |
| Node / npm / pnpm | PATH 中存在，node --version 为 v24.21.0 | 目标项目 Node 约束、uni-automator/miniprogram-automator 依赖 |
| HBuilderX | /Applications/HBuilderX.app，Info.plist 版本 5.26.2026091802，Contents/MacOS/cli 存在 | 实际 CLI 参数、编译插件、目标项目构建 |
| 微信开发者工具 | /Applications/wechatwebdevtools.app，Contents/MacOS/cli 存在 | 工具实际版本、登录、服务端口、AppID 权限及模拟器连接 |
| PHP | /opt/homebrew/bin/php，php --version 为 PHP 8.5.11 | 对应 WordPress/WP-CLI 兼容性、隔离站点和数据库 |
| WP-CLI | command -v / shutil.which 未发现 wp | 外部已装路径或隔离验收工具准备，当前不得假定可执行 |
| SSH | /usr/bin/ssh 存在 | Python SSH 客户端、临时服务器和实际远程目标 |

源码核对：现行 Registry 的插件 ID 规则允许下划线，wechat_dev 和 baota_dashboard 无需改变插件 API；二者动作、工具、资源、结果处理与上下文均使用一致前缀。包发行名可分别为 taskweave-wechat-dev / taskweave-baota-dashboard，Python 模块名分别为 taskweave_wechat_dev / taskweave_baota_dashboard，extra 名保持用户指定的下划线名称。

## 参考

- [SDK](../../../src/taskweave/plugins/sdk.py)、[插件模块](../../modules/plugins.md)、[架构](../../architecture.md)、[测试规则](../../testing.md)。
- [宝塔 API](https://www.bt.cn/data/api-doc.pdf)、[WP-CLI 命令](https://developer.wordpress.org/cli/commands/)。
- [uni-app 自动化](https://uniapp.dcloud.net.cn/worktile/auto/api.html)、[微信自动化](https://developers.weixin.qq.com/miniprogram/dev/devtools/auto/quick-start.html)。

### 当前实施与验收分层记录（2026-10-03）

完整批准动作集合为133（process3/ssh13/宝塔33/WordPress53/uniapp5/微信26），独立可选 API v1 包和组合示例已有源码，核心默认依赖/任务包/数据库格式不变。各模块协议、真实受控工具、版本变化、失败/UNKNOWN证据保留在对应实施记录。旧132/52计数不适用于当前完整范围。

组合新增证明是实际 registered actions→Application/worker→声明式 handler 保存和重读；建站 full controlled route 的面板/WP-CLI 是明确协议目标，SFTP/process/HTTP/Chromium 真实；小程序编译/SDK协议也与独立真实工具验收分列。它们不代表同host完整原生建站、真实后台登录/TiDB/真机全部通过。原生 H5 production 过去因有效 uni-app AppID 未提供而未验收，该项现按用户要求取消；公网 ACME签发/可续期条件仍未提供，Windows与网络/工具身份/清理边界保留。最终源码审查三项修复已由限定复审确认全部 ADDRESSED（Spec PASS/Quality Ready），83个公共文件安全整合原树且原项目133动作精确注册检查通过；原有 OCR 改动保留。非阻塞 M1 和上述外部门槛未关闭，目标不得因注册数量或协议成功标为全完成，当前事实见[交付记录](../../design/devops-miniprogram-plugin-delivery-2026-10-03.md)。

### 用户确认的验收范围调整（2026-10-03）

2026-10-03 用户确认：uni-app 微信模拟器自测已完成，不需要有效 uni-app AppID；取消有效 DCloud AppID 下原生 H5 production 的本次交付验收要求。历史未实测记录保留，不改写为通过。已验证的微信模拟器运行使用 touristappid 游客模式，启动和附着均覆盖26动作；DCloud AppID与微信项目AppID分别配置。

### 本地验收口径及交付结论（2026-10-03）

2026-10-03 用户确认宝塔按本地验收即可，不要求公网证书签发和续期的真实外部验证；此前已取消有效 DCloud AppID 下原生 H5 production 验收要求。按这一确认口径，六个可选插件、133动作、两份组合示例、依赖/映射/文档及原项目集成完成。公网签发/续期、H5 production和其他外部目标历史未实测范围保留，不改写为通过；本地与受控协议证据按实际类型记录。 当前结论覆盖完整实现范围，不以公网材料缺失重复启动已结束的开发或工具验收。
