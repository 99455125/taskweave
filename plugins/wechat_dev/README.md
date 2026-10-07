# wechat_dev

可选开发者工具模拟器插件，API v1 / package 0.1.0 / core `>=0.1,<1`。`uv sync --locked --extra wechat_dev` 安装 Python 侧和普通 process 库；核心默认依赖不含 Node/浏览器/模拟器 SDK。显式在自有准备目录用插件随包 `node/package.json` 和 lock 执行 npm ci，官方 miniprogram-automator 固定 0.12.1；运行时不下载或安装依赖。配置必须提供已准备模块根和兼容 Node 的绝对路径，不依赖 PATH 的 Node 版本。Node 脚本和锁包是 wheel 资源。

`wechat_dev_config` 指定编译产物 `project_root`、`node_path`、`module_root`、以冒号结尾的独立 `storage_namespace`。项目 project.config.json/可选 private config 与 app.json（包含分包）有界读取并限定根内。attach 使用显式 ws/wss endpoint；launch 使用官方 `cli_path` 与 port，固定 argv `agent start --project ABS_ROOT --auto-port PORT`，不提供 caller CLI 参数。项目需要开发者工具运行、自动化服务及实际账号权限；touristappid 的模拟器证明不能替代真实 AppID 登录、真机或后端验收。

26 个独立动作：check_environment、connect、disconnect、current_page、page_stack、navigate、observe、get_element、get_page_data、tap、input、scroll、touch、call_component_method、assert_page、assert_element、assert_page_data、wait_for、get_storage、set_storage、remove_storage、clear_storage、mock_method、restore_mock、screenshot、read_logs。导航五种官方方法；navigateBack 不伪造 delta。组件方法仅 configuration.component_methods 中有限名称；不暴露 eval、任意函数源或 generic wx call。路径数据最多20项，观察选择器最多20项，每项首次匹配；断言不符和等待超时都失败。session_id/page_revision 与 opaque element_id 绑定，导航或 SDK 当前页变化使旧句柄失效；同角色忙态拒绝并发调用。不同角色资源分别持有 SDK 会话，不声称借用实例跨角色事务隔离。

attach 只验证固定 getAccountInfoSync 返回的 AppID 及页列表，始终 `identity_level=appid_and_page`, `root_verified=false`；配置路径不是已观察的工具运行根。public owned boolean 不授予关闭权限。只有显式创建的独立随机 private root、0600准备收据（出生时间/来源文件 SHA 验证）、launch 前端口未占用、官方 openedProjectWindow=true 的组合产生内部 owned 标记；内部标记仅 Python 配置/启动逻辑传给自有 Node 桥接，不是公共输入。已占用端口、远端 attach、复用窗口、缺收据均借用/不确定，只断开。独占 root 标记排除本插件并行启动；开发者工具 CLI 没有原子窗口归属证明，外部抢开/端口竞争仍是明确限制。不会自动调用可能关闭原窗口的 automator.launch/auto，不全局 quit 或按进程名 kill。SDK close 仅对证据支持的自有窗口调用；连接失败不能确认关闭时保留 root 标记并记 UNKNOWN，独立 root 可继续工作。

存储所有普通 key 自动加测试 namespace；clear_storage scope=namespace 仅删除该前缀（最多2000键）。scope=all 额外要求 confirm_all=true，用户应仅在确实自有测试数据的实例中授权。mock 仅固定六种官方 wx 方法的 JSON 静态结果；函数源码拒绝，借用实例额外要求 allow_borrowed_mock=true。只恢复本会话预先登记的 mock，恢复的是官方原方法，不能重建用户之前的 mock。显式 restore_mock/disconnect 应在步骤返回前执行，让恢复/关窗失败进入业务结果；自动 resource 清理在 host 持久化后只能警告，不把事后警告伪装成 durable 业务失败。failure hook 在诊断持久化前清理本 attempt，保留此前所有 WRITE（包括其他 role 和后续 READ/异常后的记录）；最多32次写，预算在副作用前预留。WRITE 不重试，超时/退出/迟到回包保持 UNKNOWN，不重放。

Node newline request ID 协议每行1MiB、最多8排队帧；畸形/重复/未知ID/过期身份/退出/取消终止自有桥接进程树。持续排空 stderr，限定捕获预算，先 known literal/两层标准 JSON 表示脱敏，再 clip。env_secret_refs 为逻辑引用；最多32个且每值4096字符，生产端日志/观察摘要也先脱敏后截断，键和值一起遮蔽；不承诺截图或任意业务数据全面脱敏。普通 env 不自动识别秘密，不能用于秘密。

每动作1–1800秒总 RPC 预算，截图所有块共用同一截止时间；释放 capture 另有2秒清理预算。Node SDK 截图先返回完整 base64，无法先限制 SDK 内部内存；收到后明确检查最大16MiB默认/64MiB上限、PNG完整chunk/CRC/IEND、全字节 SHA 再暂存，绝不以截断图声称完整。`wechat_dev.image`/file 自有结果命名空间，经宿主 file handler 保存；image 限 PNG。result view `wechat_dev.screenshot` 通过 output 指针预览。read_logs 100项环形游标、每payload4096字符，返回旧游标缺口而不假装完整历史。

`wechat_dev.page` 和 inspect_page 是被动上下文：没有活跃已连接角色就只检查准备文件；不启动/连接/导航。活跃角色可观察限定 selector/path；context screenshot=true 且 include_view 时读取完整最多1MiB模拟器截图，超限失败，生成图片预览。inspect_page 不隐式获取截图。

快速验证 `uv run --extra wechat_dev python -m unittest tests.test_wechat_dev tests.test_devops_discovery`；显式原生工具目标 tests.test_wechat_dev_tools 要求私有配置与全新 receipt，默认映射不自动运行。SDK double/真实 Node 协议和 Application worker 证明接口、生命周期、诊断持久化，不代替真正 DevTools 结果。实际原生/uni-app来源、产物、有限调用、失败和清理收据分别存当前任务 ledger。

本次实际工具边界：`window_closed=true` 是官方 SDK 定向 close 调用完成的确认，SDK/CLI没有原子窗口消失查询；不得据此推断 UI 窗口或 automation listener 已退出。自有原生/uni-app attach 的 disconnect 后新 SDK 连接仍可读取页，证明借用目标被保留；随后单独准备所有者发送定向 close 收到确认，但早期1–2秒有限端口观察仍占用；最终延后只读复核19560–19568全部可绑定，未进行全局清理。真实工具试验已记录此限制，不将源码、CLI0或close ack充当全部外部资源回收证明。启动连接仅对明确的缺首屏元数据/null rawPath 情况轮询固定READ（最多15秒且受总RPC预算约束），身份/权限/连接错误立即失败，不重放任何WRITE。

fix1 生命周期边界：累计诊断保留完整接受的操作，按最终 JSON/Unicode/已知秘密脱敏字节预留元数据、有限清理、stderr 和信封；长页面/启动来源会更早耗尽64KiB预算，下一次无法预留的 WRITE 在派发前失败。已知秘密策略在同一 attempt 内固定，变化的解析值要求新 attempt，不能在此前记录上追加新的脱敏膨胀。启动收据在 CLI 副作用前单独预留；stderr 摘要先脱敏后截64字符，清理仅保留固定状态与最多8项固定错误。

桥接的总截止时间包含锁等待；等待者到期/取消不会派发或破坏正在持锁的调用。外部 coroutine 取消且通道仍可用时，只忽略这一条已放弃的响应并有限发送固定 disconnect 以恢复自有 mock；共享取消信号、畸形通道或进程失败使协议不可用时，不虚报清理成功，记录 unknown/mocks_restored=false/window_closed=unconfirmed，失败诊断与 WARNING 可见，自有桥接仍有限回收。真实 SDK cleanup 有5秒独立预算；此轮控制路径使用真实 Node + SDK double/真实宿主 worker 验证，未重新运行 GUI。确认 disconnected、mocks_restored=true 且 closed/not_owned 后，显式 disconnect 与最终资源关闭共用精确 inode/非符号链接/空目录 marker 释放，使同 scope 及下一角色可重连；unknown/partial/外来身份标记保留。

宿主 worker 可以跨步骤保留同角色资源。每次动作或已有会话的页面上下文观察先把该资源的 owner、cleanup context、桥接及进程 context 迁移到当前 attempt，核对当前解析秘密与已启动 transport 的固定脱敏策略；同 attempt 各角色策略必须一致，解析值改变则在派发前拒绝，需显式准备另一角色/transport，不能悄悄复活已关闭/poisoned 会话。旧 attempt 仅在最后一个资源 owner 离开后释放 journals/patterns/字节预留，其他活跃角色的证据保留；失败 hook 先持有当前接受记录及策略，再完成清理并构造 durable payload，last-owner prune 不会擦掉待保存结果。正常成功步骤不必结束 worker，建议显式 restore/disconnect；最终 worker teardown 才释放所有缓存资源。


## 微信预览与上传

新增 `wechat_dev.preview`、`wechat_dev.upload`，共 28 个动作（26 个模拟器动作＋2 个 CI 动作）。采用官方 [miniprogram-ci](https://github.com/wechat-miniprogram/miniprogram-ci-dist) 2.1.48；两个动作不需要连接模拟器。代码上传只创建开发版本；选择体验版、提审和正式发布不包含在这两个动作中。

先在独立准备目录放入随包 `src/taskweave_wechat_dev/node/ci/package.json` 和 `package-lock.json`，再手动执行 `npm ci`。推荐明确指定 Node 22，并使用其配套 npm；动作运行时不安装依赖。CI 与 automator 的依赖准备目录可以分开。

环境变量 `wechat_release_config` 为 JSON，步骤参数可同名覆盖字段：

```json
{
  "project_root": "/absolute/project/dist/build/mp-weixin",
  "node_path": "/absolute/node22/bin/node",
  "module_root": "/absolute/prepared/wechat-ci",
  "private_key_ref": "wechat_upload_key"
}
```

`project_root` 是包含 `project.config.json` 的编译产物目录，`miniprogramRoot` 必须位于其内，并存在 `app.json`。必须使用真实微信**小程序** AppID，`touristappid` 和公众号测试 AppID 不适用于这里。按官方要求下载代码上传密钥并配置出口 IP 白名单；HBuilderX 登录、开发者工具登录不能替代这两项配置。密钥放入宿主逻辑 secret 引用；私钥内容只经子进程 stdin 传入，不放入 argv、环境变量或临时密钥文件。

`preview` 可传 `desc`、`page_path`、`search_query`、`scene`、`robot`（1–30）、`timeout_seconds`（1–1800，默认300）；返回 `artifact`（PNG 或 JPEG 二维码）、`appid`、`project_path`、`remote_state=completed`、`sub_packages`、`plugins`。显式保存：

```python
async def run(ctx, inputs):
    preview = await ctx.call("wechat_dev.preview", {"desc": "本轮预览"})
    return ctx.result(data=preview, outputs=[ctx.output("wechat_dev.image", "preview_qr", preview["artifact"])])
```

`upload` 必填 `version`，支持共同的 `desc`、`robot`、超时参数；返回版本与官方完成回执。`project_path` 可作为必须等于配置根的断言；`expected_artifacts` 可提供完整的 `{relative_path: {sha256, size}}` 清单。清单比较包含新增、删除和修改文件，拒绝符号链接；每轮最多4000目录项、2000文件、总64MiB。SDK 始终使用本轮检查字节的独立临时副本，避免原目录在网络调用中变化。

两个动作均 WRITE、不可自动重试。SDK 错误/超时按远端 UNKNOWN 保存有限回执，不宣称上传成功；SDK 已完成但二维码校验/保存失败保留 COMPLETED 回执。当前 attempt 的预览二维码可通过 failure hook 在后续上传失败时持久化；主组合报告只在全部选择的操作完成后返回。诊断只保留最新 CI 回执与当前 attempt 的最新预览，不是全历史发布日志。

一键组合见 [构建、自测、预览](../../examples/devops/miniprogram_preview.py)。当前官方 automator 的运行时身份只验证 AppID/页面，attach 和 launch 都不提供绝对工程根证明。因此组合还检查配置根与本轮产物根一致，并要求显式 `allow_unverified_simulator_root=true`：操作者须先确认开发者工具窗口实际打开同一产物目录。报告保留 `tested_build_root_verified=false`，不能称已证明模拟器工程根或真机业务通过。

本轮新增测试使用真实 Node、进程、worker、暂存与宿主持久化，以及受控 CI SDK 边界；没有真实微信上传密钥和发布目标，未做微信云端预览/上传或手机扫码验收。

本轮定向验证：`tests.test_wechat_dev`、`tests.test_wechat_release`、`tests.test_devops_discovery`、`tests.test_uniapp`、`tests.test_devops_workflows.DevopsWorkflowTests` 与 `tests.test_module_selection` 共139项通过；Node bridge语法、CI锁文件、`uv lock --check`、插件 wheel 资源/源码一致性及空白检查通过。未运行全量或真实云端发布。`scripts/check_project.py` 报告3处已有历史验收文档的输出证据链接缺失（ui-visual-final-acceptance/ui-r10-final-acceptance），本次新增文档引用未报错；未改写历史验收记录。
