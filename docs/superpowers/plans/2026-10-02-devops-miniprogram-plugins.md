# 六插件完整开发 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for inline execution, or superpowers:subagent-driven-development if the user selects delegation. Steps use checkbox syntax for tracking. Do not automatically commit; project AGENTS.md overrides skill commit steps.

**Goal:** 完整实现 process、ssh、baota_dashboard、wordpress、uniapp、wechat_dev，并完成设计约定的能力、文档、示例和验证。

**Architecture:** 六个独立可选包接入既有 SDK、registry、worker 和结果保存。process/ssh 的运输库供业务插件复用，插件动作之间不直调；Node 桥接仅属于 wechat_dev。实现顺序服务于依赖，不缩减交付范围。

**Tech Stack:** Python >=3.10、uv、asyncio、异步 SSH/SFTP 客户端、标准 HTTP/TLS、WP-CLI、HBuilderX CLI、项目包管理器、Node miniprogram-automator、unittest。

**Spec:** [已通过设计](../specs/2026-10-02-devops-miniprogram-plugins-design.md)。本文每个能力集合以设计表为完整验收清单，不以已有测试数量代替能力覆盖。

## Global Constraints

- 保持插件 API v1、python-async-v1、taskweave-task-2 和数据库格式不变。新增插件 package_version=0.1.0。
- core 不引入具体插件默认依赖，UI 不增加插件专属分支；旧插件行为不变。
- 固定步骤不调用模型；秘密通过 ctx.resolve_secret(reference) 和 secret_refs→env:映射解析。
- 默认每流输出 64 KiB，可设 1 KiB–1 MiB；默认超时 60 秒，范围 1–1800 秒。
- 传输默认 16 MiB，可设至 64 MiB；文件完整读取，日志可截断并有游标。
- 配置根内核对真实路径/符号链接；产物通过 allocate_file、ResultHandler、ctx.result(outputs=...) 保存。
- 写操作不自动重试；取消/超时保留部分成功与未知副作用；不终止用户已有工具。
- 不自动安装外部工具或项目依赖、不改用户项目配置、不自动提交/重置/清理。
- 仅运行受影响模块测试，真实工具测试显式选择，不跑全量或分组拼成全量。
- 保留既有 OCR 修改及未验证状态。本轮已有工程检查的三个旧产物缺失链接单独报告，不用编造产物修复。

## Review Focus

1. 子进程主进程退出但后代持有管道：超时仍结束本次进程树、排空回收，无永久挂起（Task 1）。
2. SFTP 路径检查后符号链接变化/并发覆盖：不错误宣称根约束是服务器权限沙箱，不无条件覆盖已存在目标（Task 2）。
3. 宝塔 HTTP 200 返回分项失败或密码：报告实际部分成功，输出和上下文不带密码（Task 3）。
4. WordPress 备份包含绝对路径/链接逃逸或恢复中断：拒绝危险成员，保留部分恢复状态，不标成功（Task 4）。
5. 微信桥接断线/页面改变后迟到回复：请求 ID 与会话/页面身份核对，旧元素失效，截图不会归属错误页面（Task 6）。

## 执行与公共文件约定

每个 Task 同时创建该包 pyproject.toml、README.md，并在宿主 pyproject.toml 添加同名 extra/tool.uv.sources，更新 uv.lock 和 tests/module-map.json。文件包名/模块如下：

| 目录 | 发行名 | Python 模块/entry point factory |
| --- | --- | --- |
| plugins/process | taskweave-process | taskweave_process:ProcessPlugin |
| plugins/ssh | taskweave-ssh | taskweave_ssh:SshPlugin |
| plugins/baota_dashboard | taskweave-baota-dashboard | taskweave_baota_dashboard:BaotaDashboardPlugin |
| plugins/wordpress | taskweave-wordpress | taskweave_wordpress:WordPressPlugin |
| plugins/uniapp | taskweave-uniapp | taskweave_uniapp:UniappPlugin |
| plugins/wechat_dev | taskweave-wechat-dev | taskweave_wechat_dev:WechatDevPlugin |

依赖修改用 uv lock，安装用 uv sync --locked 加本轮已完成插件 extras，执行用 uv run 并显式带 extras；不向虚拟环境安装 pip。每个包 __init__.py 仅装配插件，按下列文件分职责，避免全部动作堆在一个文件。通用文件 handler 由 process 的结果模块构造，以所属插件命名空间注册，不通过其他插件 handler 直调。

## Task 1：process 与公共进程/产物库

**Files:** plugins/process/pyproject.toml、README.md、src/taskweave_process/{__init__,runner,artifacts,actions,context}.py；tests/test_process.py；tests/test_devops_discovery.py；公共文件约定中的宿主配置与映射。

**Interfaces:** `async run_command(ctx, executable: str, args: list[str], *, cwd: str, env: dict, stdin: bytes | None, timeout_seconds: int=60, max_output_bytes: int=65536) -> dict`；`async stage_artifact(ctx, root: str, path: str, *, max_bytes: int) -> dict` 返回 token/name/media_type/size_bytes/checksum，不返回 local_path；`FileResultHandler` 实现既有 ResultHandler。动作为设计中的 check_environment/run/collect_artifacts。

- [ ] 写 tests.test_process：`test_argv_and_stdin_are_literal` 用真实 Python 回显参数 `a;echo bad`，断言完整字面量和标准输入；`test_nonzero_exit_is_reported` 断言 exit_code=7、stderr；`test_output_budget_drains_both_streams` 断言每流≤65536 bytes 且两截断标记为真。
- [ ] 写 `test_timeout_reaps_descendants_holding_pipes`、`test_cancel_before_start_has_no_effect`、`test_cancel_reaps_process_tree`；使用临时 Python 子进程和 PID/探针文件，断言无副作用或进程回收；写产物符号链接逃逸/超限和秘密 echo 输出遮蔽测试。
- [ ] 用 `uv run python -m unittest tests.test_process -v` 观察新增实现缺失失败；尚未安装包时测试模块显式导入新模块，不 skip 缺失。
- [ ] 实现上述库/动作与 resource-free ProcessPlugin；真实路径限制、秘密引用、双流有界读取、POSIX 进程组及 Windows 本次子树回收；注册结果处理和只读观察上下文。
- [ ] 更新包/extra/lock/map/README；运行 `uv run --extra process python -m unittest tests.test_process tests.test_devops_discovery -v`，期望全部通过，记录平台清理限制与证据。

## Task 2：SSH / SFTP 与可复用运输库

**Files:** plugins/ssh/{pyproject.toml,README.md,src/taskweave_ssh/{__init__,transport,paths,transfer,actions,context}.py}；tests/test_ssh.py；tests/fixtures/ssh_server.py；扩展 discovery/map。

**Interfaces:** 消费 process 的 run result/产物 handler 契约；`async connect_ssh(ctx, config: dict) -> SshSession`；`SshSession.run(ctx, argv: list[str], *, cwd: str, env: dict, stdin: bytes | None, timeout_seconds: int, max_output_bytes: int) -> dict`；`SshSession.resolve_path(path: str, *, must_exist: bool) -> str`；`SshSession.close() -> None`（async）。注册 ssh.connection 和设计全部 13 个动作，不让连接进入 JSON。

- [ ] 用临时真实异步 SSH/SFTP server 写连接/密码/密钥/Agent 配置、known_hosts 不符拒绝测试；`test_exec_quotes_argv_cwd_env` 断言含空格/引号/分号参数保持字面值；身份失败时无命令探针。
- [ ] 写文件读写/list/stat/checksum/log cursor、上传下载摘要、覆盖拒绝、root/符号链接逃逸、删除根拒绝、超限、取消超时测试；`test_target_appearing_after_precheck_is_not_overwritten` 断言并发目标保留。
- [ ] 先执行新测试确认缺实现；核对官方 SSH 客户端元数据并锁定兼容 Python >=3.10 的版本；实现运输/路径/传输/动作，远程未知副作用明确报告。
- [ ] 补 README、ssh.server 上下文/编写工具/文件结果处理、extra/lock/map；运行 `uv run --extra ssh --extra process python -m unittest tests.test_ssh tests.test_devops_discovery -v`，期望真实临时服务器与契约通过。

## Task 3：baota_dashboard 完整面板能力

**Files:** plugins/baota_dashboard/{pyproject.toml,README.md,src/taskweave_baota_dashboard/{__init__,client,endpoints,actions,context}.py}；tests/test_baota_dashboard.py；tests/fixtures/baota_server.py；插件 README 的支持版本/端点表。

**Interfaces:** `async PanelClient.request(ctx, endpoint: str, params: dict, *, response_kind: str) -> dict | list`；`EndpointSpec` 固定 method/path/action/字段映射/响应类别/支持条件；`BaotaDashboardPlugin.actions()` 覆盖设计中六组全部动作，独立 schema 和读写性质。HTTP客户端不作为核心依赖。

- [ ] 先取得官方客户端源码或版本接口证据，逐项登记六组端点/参数/响应；官方 PDF 已有端点直接核对，剩余证书/数据库/恢复不能以猜测端点替代。证据缺失保留未完成能力，继续其他已明确实现。
- [ ] 写真实临时 HTTP 服务测试，校验签名时间/token/POST、TLS/跨主机重定向拒绝、超大/畸形响应；`test_add_site_reports_partial_failure_without_passwords` 断言 siteStatus 真但 databaseStatus 假时不标全成功，ftpPass/databasePass 消失。
- [ ] 按每个 EndpointSpec 写动作字段映射/成功/失败契约测试；新增目标已存在、配置校验失败不 reload、证书受理但未签发、恢复归属错误测试；执行确认缺实现。
- [ ] 实现所有端点适配/独立动作、目标核对、资源/上下文/脱敏，保留真实部分结果及未知副作用；不支持版本显式报错，但不能以全部不支持完成该任务。
- [ ] 更新包/extra/lock/map/支持版本 README，运行 `uv run --extra baota_dashboard python -m unittest tests.test_baota_dashboard tests.test_devops_discovery -v`；指定隔离实际面板运行建站/配置/数据库/证书/备份验收，记录真实证据与外部权限缺口。

## Task 4：WordPress 本地/SSH 全部业务动作

**Files:** plugins/wordpress/{pyproject.toml,README.md,src/taskweave_wordpress/{__init__,transport,commands,actions,backup,context}.py}；tests/test_wordpress.py；tests/test_wordpress_integration.py；tests/fixtures/wordpress_site.py。

**Interfaces:** 消费 Task 1 的 run_command、stage_artifact 和 Task 2 的 connect_ssh/SshSession.run；`async run_wp(ctx, config: dict, command: list[str], *, secret_inputs: dict, parse_json: bool) -> dict`；`build_command(action_id: str, inputs: dict) -> list[str]`；`async backup_site(ctx, config: dict, inputs: dict) -> dict` / `restore_site(...) -> dict`。wordpress.site 独立拥有所选运输资源，不依赖 ssh 插件启用状态。

- [ ] 按设计十组动作写真实 argv 构造/解析测试：每个动作目标字段实际进入对应 WP-CLI argv；特殊字符不注入、不默认 allow-root；core/user/config 密码不进入可记录 argv、结果和上下文。
- [ ] 写退出码/JSON 输出/预算错误、只读配置秘密拒绝、已安装不重复初始化、search_replace 默认预演测试；`test_restore_rejects_absolute_and_symlink_escape_members` 与 `test_restore_reports_partial_failure` 验证危险包和中断不能被标成功。先执行新增测试观察缺实现。
- [ ] 实现全部独立动作、站点路径核对、秘密标准输入/受控文件清理、主题插件/内容分类菜单媒体用户管理、数据库/站点完整备份恢复；注册 wordpress.site、上下文和文件结果处理。
- [ ] 更新包/extra/lock/map/README，运行 `uv run --extra wordpress python -m unittest tests.test_wordpress tests.test_devops_discovery -v`；按需准备隔离站点（不改用户站点），显式选择 `tests.test_wordpress_integration` 验证设计全部业务组及 local/ssh 两模式，不以假的 wp 程序当真实验收。

## Task 5：uniapp CLI/HBuilderX 项目与构建测试

**Files:** plugins/uniapp/{pyproject.toml,README.md,src/taskweave_uniapp/{__init__,project,build,tests,actions,context}.py}；tests/test_uniapp.py；tests/test_uniapp_tools.py；tests/fixtures/uniapp_project.py。

**Interfaces:** 消费 Task 1 库；`inspect_project(ctx, config: dict) -> dict`；`async build_project(ctx, config: dict, inputs: dict) -> dict` 返回 command result、build_id、started_at、platform 和产物摘要；`check_artifact(ctx, config: dict, inputs: dict) -> dict` 输入 build_id/started_at 及平台；`async run_tests(ctx, config: dict, inputs: dict) -> dict` 返回明确报告状态；设计五动作全部注册。

- [ ] 写 JSONC、src/与根目录两布局、CLI/HBuilderX 识别、Vue/AppID/pages、缺脚本/工具/依赖测试；真实临时项目执行 Python/Node fixture 构建命令，不 skip 缺实现。
- [ ] 写微信/H5 产物检查、`test_successful_command_with_stale_artifact_is_rejected`、取消/失败、测试筛选、缺报告不能通过、产物/报告符号链接逃逸与预算测试；运行确认失败。
- [ ] 核对官方 HBuilderX CLI 编译/自动测试参数，分别实现 CLI 和 HBuilderX 实际适配；保存本次 build identity，不能只根据目录存在标成功；JSONC 依赖只属于该包。
- [ ] 实现 inspect/build/check_artifact/run_tests/collect_report、uniapp.project 上下文/编写贡献和报告文件结果；更新 extra/lock/map/README。
- [ ] 运行 `uv run --extra uniapp python -m unittest tests.test_uniapp tests.test_devops_discovery -v`；显式选择临时真实 CLI/HBuilderX 工程微信/H5 工具验收 `tests.test_uniapp_tools`，不修改其他仓库来准备测试。

## Task 6：wechat_dev Node 桥接与全部模拟器能力

**Files:** plugins/wechat_dev/{pyproject.toml,README.md,src/taskweave_wechat_dev/{__init__,bridge,actions,context}.py,src/taskweave_wechat_dev/node/{bridge.cjs,package.json,package-lock.json}}；tests/test_wechat_dev.py；tests/test_wechat_dev_tools.py；tests/fixtures/wechat_bridge.cjs。

**Interfaces:** 消费 Task 1 进程回收/产物库；`async SimulatorBridge.start(ctx, config: dict) -> SimulatorBridge`；`await bridge.request(method: str, params: dict, *, timeout_seconds: int) -> dict`；`await bridge.close()`。Node 请求为 `{id,method,params}`，响应 `{id,result}` 或 `{id,error:{code,message}}`，每条最多 1 MiB；身份信息包含 session_id/page_path，失效句柄拒绝。所有设计八组动作单独注册。

- [ ] 核对官方 miniprogram-automator 的导航/组件/触摸/存储/mock/日志/截图方法，锁定 Node 包版本；建立方法白名单和字段映射，不暴露任意 JS eval。
- [ ] 写真实 fixture Node 子进程协议测试：请求 ID 乱序/重复/迟到、超大/畸形行、桥接退出、取消和 stderr 排空；`test_late_reply_after_page_change_is_not_used` 断言身份不符被拒绝，`test_disconnect_preserves_attached_tool` 断言不关闭用户实例；运行观察缺实现。
- [ ] 每个动作覆盖真实输入/输出 schema、缺连接/元素、等待超时、观察大小、存储命名空间、mock 恢复失败、日志游标和 screenshot 暂存；断言失败必须报错，不只是返回描述。
- [ ] 实现 Node bridge 官方方法调用和 Python client/actions/resource provider；会话附着/启动清理、page/context observe、声明式文件/图片结果和编写贡献；Node 桥接脚本作为包资源，不临时下载包。
- [ ] 更新 extra/lock/map/README，运行 `uv run --extra wechat_dev python -m unittest tests.test_wechat_dev tests.test_devops_discovery -v`；显式选择 `tests.test_wechat_dev_tools`，用隔离原生/uni-app小程序实际模拟器覆盖导航/触摸组件/断言/mock/存储/日志截图及异常路径；账号权限缺失记录未验收，不当成通过。

## Task 7：组合示例、映射和完整交付审计

**Files:** examples/devops/{README.md,wordpress_site.py,miniprogram_selftest.py}；tests/test_devops_workflows.py；tests/test_devops_discovery.py；tests/module-map.json；docs/modules/plugins.md；docs/maintenance.md；docs/deployment.md；plugins/README.md；docs/roadmap.md；docs/status.md；本计划及设计验收记录。

**Interfaces:** 两示例导出 `async run(ctx, inputs) -> StepResult`，只调用真实已注册能力，secret_refs 通过环境配置提供。文件/报告结果明确纳入 outputs。测试映射新增 plugins.process/ssh/baota_dashboard/wordpress/uniapp/wechat_dev；依赖按实际库关系维护，工具用例仅进入显式选择 targets。

- [ ] 写 `test_all_declared_capabilities_are_registered_and_valid`：设计动作集合逐项等于 Registry 实际集合、schema有效、命名空间一致、版本/资源/handler可解析，防止写了说明却漏实现。
- [ ] 写 `test_workflow_persists_real_command_artifact` 和 `test_failed_business_action_does_not_produce_success_report`，用临时 Application/worker 验证真实 process 输出与宿主结果保存及失败归属；工具/外部目标组合保持单独真实验收。
- [ ] 在各测试文件按实际类型分别登记快速/真实浏览器/外部工具测试，避免同一整个模块和其中方法重复映射；运行 changed dry-run 核对反向依赖，映射消费者明确含 process→wordpress/uniapp/wechat_dev、ssh→wordpress。
- [ ] 实现两示例，更新仅受影响文档；为所有设计动作记录源码、模块测试、真实目标证据和未验收项，明确 Windows/真机/外部目标限制。
- [ ] 运行 `uv run --extra process --extra ssh --extra baota_dashboard --extra wordpress --extra uniapp --extra wechat_dev python -m unittest tests.test_devops_workflows tests.test_devops_discovery tests.test_plugin_contract tests.test_module_selection -v`，只含指定目标；运行结构检查、git diff --check 和 uv lock --check。
- [ ] 按设计验收矩阵审计全部六插件；缺能力、间接证据、真实目标未验收均保持目标未完成。保留所有改动待用户审阅，不提交、不发布、不连接用户生产站点执行修改。

## 自审与执行交接

覆盖核对：process→Task 1，SSH→Task 2，宝塔六组→Task 3，WordPress十组→Task 4，uni-app五动作→Task 5，微信八组→Task 6，兼容/上下文/产物/示例/映射→各任务＋Task 7。五项 Review Focus 均有所属任务的具体失败测试；通用库签名由前置任务定义，后续仅消费，不新增核心端口。

建议本对话顺序实施：先稳定 process/ssh 库，再实现业务包并做逐项审计。若用户选择子代理执行，按依赖顺序委派独立包并进行审核；共享 pyproject/lock/map 由主执行者整合。无论执行方式，全部范围与验收要求一致。

状态：用户已明确回复“计划通过，子代理实施”；按七项任务顺序实施。进度与验证证据由本计划所属 SDD ledger 记录，不自动提交。

## Task7 当前实施结果（2026-10-03）

六插件的133个批准命名动作已进入 live Registry 精确集合/schema/resource/handler/version/authoring 检查，包含 WordPress delete_post。两份完整 async 步骤示例已实现并声明文件/报告输出；小程序已有测试套件入口、可选 TiDB 核对仍按实际配置执行，不配置时明确 database=null。真实 worker/process 产物提交及后续 registered BaoTa 业务拒绝保留前步文件已定向验证。

完整建站受控路线使用真实 adapter/SFTP/process/HTTP/Playwright/handler，面板/WP-CLI 为协议目标；面板虚拟路径与 owned 临时 WordPress 根的命名空间映射明确，不能拼成真实同host生产部署。小程序受控编译/SDK路线保存 suite/report/PNG/logs。普通 fast 与外部/tool/browser targets 分离，反向库依赖保留，未执行全量或拼接旧插件功能套件。

最终指定检查/结构/锁/差异及源冻结记录保留在本计划所属 ledger。最终三项修复限定复审 Spec PASS、Quality Ready，无新增 finding；83个公共文件已按原474文件哈希守卫安全整合原树（11修改、72新增、0删除），原项目 locked extras 同步和133动作精确注册检查1/2.698秒通过。原 OCR 修改保留，未提交或发布。完整 coherent 外部建站、真实 TiDB、Windows/真机、公网 ACME/可续期及非阻塞 M1 仍保留边界，详见[交付记录](../../design/devops-miniprogram-plugin-delivery-2026-10-03.md)，不宣布完整目标完成。

### 用户确认的验收范围调整（2026-10-03）

2026-10-03 用户确认：uni-app 微信模拟器自测已完成，不需要有效 uni-app AppID；取消有效 DCloud AppID 下原生 H5 production 的本次交付验收要求。历史未实测记录保留，不改写为通过。已验证的微信模拟器运行使用 touristappid 游客模式，启动和附着均覆盖26动作；DCloud AppID与微信项目AppID分别配置。

### 本地验收口径及交付结论（2026-10-03）

2026-10-03 用户确认宝塔按本地验收即可，不要求公网证书签发和续期的真实外部验证；此前已取消有效 DCloud AppID 下原生 H5 production 验收要求。按这一确认口径，六个可选插件、133动作、两份组合示例、依赖/映射/文档及原项目集成完成。公网签发/续期、H5 production和其他外部目标历史未实测范围保留，不改写为通过；本地与受控协议证据按实际类型记录。 当前结论覆盖完整实现范围，不以公网材料缺失重复启动已结束的开发或工具验收。
