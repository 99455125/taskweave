# 组合步骤示例

两个文件均为可保存为 `python-async-v1` step_content 的 `async run(ctx, inputs)`，返回真实 `StepResult`（通过 `ctx.result`）。固定执行不调用模型、不安装工具。将源码全文交给步骤保存入口，配置任务 input_schema/defaults，先校验并人工确认当前 hash，再执行。环境、secret_refs、连接对象及结果不属于分享任务包；不能复制他人的真实凭据或 AppID。

[建站](wordpress_site.py) 顺序执行宝塔站点/数据库准备、SSH 上传、WordPress 核心/配置/安装/内容、Playwright 页面断言、站点备份和报告。全部配置对象由 inputs 传入，字段遵循各动作 schema；没有自动省略失败阶段或生成推测成功报告。必须启用 baota_dashboard、ssh、wordpress、playwright，并声明下面各动作以及三个输出 handler：

```text
baota_dashboard.create_site, baota_dashboard.create_database, ssh.upload,
wordpress.core_download, wordpress.config_create, wordpress.core_install,
wordpress.create_post, playwright.page_open, playwright.page_assert_text,
playwright.page_screenshot, wordpress.backup, baota_dashboard.create_backup,
wordpress.json, wordpress.file, playwright.image
```

输入必须包含：`site`（domain/path）、`database`（name/username/password_ref/access）、`transfer`（local_path/remote_path，overwrite 默认拒绝）、`core`（version/locale）、`configuration`（dbname/dbuser/dbhost/dbprefix/db_password_ref）、`install`（url/title/admin_user/admin_email/admin_password_ref）、`content`（post_type/title/status/content）、`page_url`、`page_assertion`（selector/text）和 `backup`（tables，以及明确预算/范围等可选字段）。数据库 password_ref 与 WordPress db_password_ref 必须对应同一实际授权账户；site.path、SSH 远程根、WordPress 环境站点根和访问 URL 必须由操作者核对为同一自有部署目标。transfer.remote_path 是该目标的独立暂存位置，须位于 WordPress 核心目标目录之外；core_download 要求核心目录为空，不能先把上传文件放进去。示例不自动解包或执行上传文件，上传结果作为部署旁证保存。配置本身不证明跨系统归属。

环境提供宝塔 URL/TLS/逻辑 secret_ref，SSH host/known_hosts/remote_root/认证引用/local_root，以及 WordPress mode、WP/PHP 路径、站点根、owned_tables。秘密只通过逻辑引用解析；示例不接收原文密码。Playwright 需要匹配的已准备 Chromium。建站是不可重试写流程，备份是完成后的证据，不是失败阶段的自动回滚；运行前核对独立自有目标和范围，已有站点同名核对不能代替部署身份确认。输出为 `deployment_report`、完整 `site_backup`、`site_screenshot`。

[小程序](miniprogram_selftest.py) 执行 uniapp.inspect/build/check_artifact，再连接模拟器、可选导航/点击、页面和元素断言、可配置 TiDB 数据核对、截图/日志/报告。必须启用 uniapp/wechat_dev；要用 database_query 再启用 tidb（也在声明 capabilities 时配置）。全部动作声明如下；不用数据库分支时可从声明中删除 tidb.query，无源码修改。

```text
uniapp.inspect, uniapp.build, uniapp.check_artifact, uniapp.run_tests,
uniapp.collect_report, wechat_dev.connect, wechat_dev.navigate, wechat_dev.tap,
wechat_dev.assert_page, wechat_dev.assert_element, wechat_dev.screenshot,
wechat_dev.read_logs, wechat_dev.disconnect, tidb.query,
uniapp.file, uniapp.json, wechat_dev.image, wechat_dev.json
```

输入 `expected_page`（实际页面 path，无开头 slash）、`element_assertion`（selector、exists/text/value 的明确断言），可选 `environment`（默认 development）、`navigation`（mode/url）、`tap_selector`。已有测试套件入口 `test_suite` 接受 uniapp.run_tests 参数，包括 platform=mp-weixin、file/case；本轮完整报告收集为 `suite_report_N`。`database_query` 使用只读 sql/params/title/max_rows 与 `expected_rows`，截断或不一致使步骤失败，未配置则报告 database=null，不能称已验证数据库。TiDB 连接依赖环境的逻辑秘密，不写进源码。

环境提供 uniapp_config 与 wechat_dev_config；两者必须指向同一平台构建的真实产物根。默认 CLI development 必须配置 finite 脚本；也可显式 production 或原生 HX development。后验检查需要本资源刚返回的 build_id/started_at，旧产物/未变化文件/CLI0不能代替完成。原生 UNKNOWN 租约需独立新根恢复，Windows native 安全原语准备限制保留。connect 的 launch/attach 和端口、所有权、storage_namespace、component_methods 由环境明确配置，attach 的 AppID+page 身份不能证明 observed root。结果明确 `simulator_only=true`，输出 `selftest_report`、`simulator_screenshot` 和 `simulator_logs`，不当成真机/真实登录/后台事务证明。

业务异常原样传播，主报告只在全部选定动作成功后返回。当前 attempt 的插件 failure hook 保存有限失败证据，微信 hook 在保存前清理该 attempt 拥有的会话；worker 可以跨步骤/失败保留资源，实际 worker teardown 才释放全部缓存资源。成功阶段需要明确 restore/disconnect，不能从失败推断用户工具已结束；未返回的 StepResult 不是已提交的输出。需要跨失败保留前一阶段文件时，将已完成阶段单独保存为前一步，通过 JSON binding 组合。两例都包含 WRITE，无自动重试、自动全局退出或清除用户工具状态。

普通 `tests.test_devops_workflows` 使用实际注册动作、真实 worker/子进程和自有协议目标：正向小程序协议路线、建站早期业务失败及前步文件保留；完整建站受控正向使用真实 registered actions/worker/SFTP/process/Playwright/handler，面板与 WP-CLI 是协议目标，截图来自真实独占 headless Chromium。面板虚拟 /www/wwwroot 命名空间映射到测试的独立临时 WordPress 路径，明确不是同 host 原生部署。它证明完整示例调度和宿主备份/报告/截图保存，不是 PHP/WordPress 或 coherent 外部链验收。小程序编译/SDK 也属于协议目标，不是官方编译器/真实微信验收。完整外部建站组合、真实 TiDB/公网目标权限仍须显式目标验证。原各插件真实目标证据单独保留，不能因示例通过而推断所有服务/平台均通过。映射的外部工具 targets 仅在显式 opt-in 时选择。


## 构建、自测与预览二维码

[小程序预览组合](miniprogram_preview.py) 在现有自测流程后增加官方 CI 预览，可选上传开发版本。启用 uniapp/wechat_dev，并准备 `uniapp_config`、`wechat_dev_config`、`wechat_release_config`；模拟器与 CI 配置根都须指向本轮 `uniapp.check_artifact.output_path`。CI 使用独立准备的 miniprogram-ci2.1.48、真实微信小程序 AppID、上传密钥引用和 IP 白名单，详见 [配置](../../plugins/wechat_dev/README.md#微信预览与上传)。

能力声明沿用上方自测清单，再加 `wechat_dev.check_environment`、`wechat_dev.preview`、`wechat_dev.upload`。保留原自测的 `expected_page`、`element_assertion` 等输入，并明确设置 `allow_unverified_simulator_root=true`：当前 attach/launch 都仅验证 AppID/页面，运行前人工核对开发者工具的工程目录。未确认时组合拒绝发布；报告保留 `tested_build_root_verified=false`。

可选 `preview` 对象支持 `desc/page_path/search_query/scene/robot/timeout_seconds`；组合自身填入本轮产物目录和完整哈希清单，调用者不能覆盖它们。可选 `upload_version` 在预览后上传开发版本；不填则只生成扫码预览二维码。输出增加 `preview_qr` 和 `release_report`。后续上传失败时预览二维码通过插件 failure hook 保留，主报告不会被写成成功。二维码对应扫码预览，上传对应开发版本；选择体验版、提审和正式发布仍需微信平台流程。
