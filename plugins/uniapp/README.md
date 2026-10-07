# uni-app

可选包 `taskweave-uniapp` 0.1.0 使用插件 API v1，核心兼容 `>=0.1,<1`。以 `uv sync --locked --extra uniapp` 安装；同时使用其他能力时保留已有 extra。JSONC 解析与 process 库属于插件依赖，固定执行不调用模型。

提供 `uniapp.inspect`、`build`、`check_artifact`、`run_tests`、`collect_report`，资源为 `uniapp.project`，上下文及编写工具只做被动检查。构建和测试是不可重试的 WRITE；其他动作是 READ。不同 role 共享同一工程的互斥执行边界；原生 WRITE 另有跨 worker 的持久租约。失败处理器保存本次尝试中先前写入及中断命令的有限诊断；不会承诺回滚。

在环境或任务参数 `uniapp_config` 中明确配置：

```json
{
  "project_root": "/absolute/owned/project",
  "kind": "cli",
  "node_path": "/absolute/compatible/node",
  "node_major": 22,
  "package_manager": "/absolute/npm",
  "build_scripts": {
    "production:mp-weixin": {"script": "build:mp-weixin", "completion": "Build complete."},
    "production:h5": {"script": "build:h5", "completion": "Build complete."}
  },
  "outputs": {
    "production:mp-weixin": "dist/build/mp-weixin",
    "production:h5": "dist/build/h5"
  },
  "test_scripts": {"mp-weixin": {"script": "test:mp-weixin", "forwards_jest_args": true}},
  "report_root": ".reports"
}
```

脚本、依赖和报告目录须由研发预先准备。插件不会安装 npm 依赖、打开/导入应用或执行工程 Jest/env 配置来完成 inspect。支持根目录和 src 布局、JSONC、Vue/AppID/pages/subpackages 元数据；CLI Node 版本须符合显式 major、可解析 engines 和 `.nvmrc`，复杂范围返回准备要求。密钥只使用 `env_secret_refs` 的逻辑引用，通过进程环境传递并在文本输出/报告入库前脱敏。

构建结果包含 `build_id`、`started_at`、平台、完整受限命令结果和产物快照。`check_artifact` 必须提交同一资源保存的三个身份字段。仅有退出码 0、旧目录、未变化文件或缺少完成标记均不能通过。微信检查 app/project/pages、组件与静态引用；无页面局部样式时 wxss 可缺省。H5 静态产物检查 index 及资源引用。全部文件与路径受真实路径、文件数、字节预算约束。每次扫描累计最多 4000 个目录/文件条目、2000 个文件和 16 MiB 文件内容，并逐条检查取消；空目录同样计入。H5 CSS 的本地 `@import "…"` 与 `url(…)` 会解码 CSS/URL 转义、检查目标存在并限制在产物根内；远程 URL、片段及动态表达式不作为本地产物完整性证明。

HBuilderX 配置 `kind=hbuilderx`、`hbuilderx_path`；development 使用官方 launch/compile/stop 语义。H5 development 的内存编译返回 `compiled_in_memory`，不声称可部署静态产物。production 使用 `imported_project` 的 name/root/evidence 已导入映射执行 publish，仅编译，不上传或托管；有效 uni-app AppID、账户准备仍由工具要求决定。

已有直接 Jest 脚本支持 `file`/`case`；仅验证无 shell 控制语法、可转发 JSON 输出及筛选参数的 Jest/cross-env Jest 路线。报告要求本轮完整 JSON、真实正向执行、无失败/运行错误/中断；过滤后的 focused suite 可含 pending，用例计数及选中文件/名称仍须一致。原生测试读取已安装 `hbuilderx-for-uniapp-test` 的 CLI schema，使用 `test_plugin_root`、已准备的 `native_test_lib_root`、`owned_test_project=true` 及既有 Jest/env 文件；它可能修改 owned 工程 Jest testMatch。仅支持 installed schema 的 testcaseFile，原生无 case flag 时需改用已配置 Jest 路线。

`report_root` 可明确指定工程内目录或独立绝对报告目录，禁止文件系统根目录和越界引用。`collect_report` 完整读取指定 JSON/log/text/image，再返回暂存文件；以 `uniapp.file` 保存。传入 `test_run_id` 时必须包含该运行的未变化报告。JSON/失败证据使用 `uniapp.json`/`uniapp.operation_failure`。

模块验证为 `tests.test_uniapp` 与 `tests.test_devops_discovery`。`tests.test_uniapp_tools` 只用于显式任务自有真实工程，必须配置 `TW_UNIAPP_TOOL_CONFIG`；不进入普通快速目标，不自动下载工具或修改用户工程。真实工具可因 AppID、DevTools 服务权限或浏览器准备返回明确失败，协议 fixture 通过不替代这些验收。

原生 HX 命令通过已运行的扩展宿主启动 Jest；命令 deadline/取消不能保证终止宿主另行启动的测试任务。此时操作效果保持 UNKNOWN，可能有迟到报告、工具窗口或任务残留，不能据此转为通过。安装版 5.4 的停止命令是全局扩展/UI 操作，未提供可证明定向当前 clientId 的 CLI abort；插件不调用全局停止或退出用户工具。插件在工程根原子创建私有 `.taskweave-uniapp-native-lease/owner.json`（格式 v1、目录 0700、文件 0600），记录 root/attempt/PID/token，独立于核心数据库和任务包格式。已有文件、未知版本、符号链接或身份变化均保留并拒绝 WRITE。仅本次拥有的目录/文件 inode 与内容 hash 全部相符，且命令明确 NOT_STARTED 或动作达到完整有限完成验证，才释放租约；退出码 0、失败报告、调用者 cleanup 布尔值、时间戳和 session close 都不能清除 UNKNOWN。超时/取消后同根跨 role、关闭会话或新 worker 继续隔离（切换 CLI 也不绕过），被动 inspect/context 与报告 READ 仍可用。插件提供的恢复路线是明确配置独立自有新工程根；原根需另行以实际进程/工程归属及完成证据安全清理，插件不提供未经证明的清除接口。租约依赖 POSIX 的 O_DIRECTORY/O_NOFOLLOW 与 dir_fd 安全操作；macOS 路线已测试，Windows 原生 WRITE 当前明确返回准备要求，未声称 Windows 已支持。原生内部 Node 由 HX 设置/宿主决定，外层 Node PATH 不证明内部版本。

本次原生微信工具验收中，默认注入的局域网 WebSocket 地址未连接，明确设置自有 `env.js` 的 `UNI_TEST_CUSTOM_ENV: {UNI_AUTOMATOR_HOST: '127.0.0.1'}` 后，新的回环端点、运行时连接和真实页面断言都通过。它与 `mp-weixin.port` 的 DevTools API 端口分别记录；这项测试环境配置不证明其他网络地址可用。原生 Web 的安装版 5.4 先检查 Playwright 默认浏览器缓存，随后才使用项目 `h5.executablePath`；自定义路径存在不能替代此准备要求。

在安装版原生 H5 适配器中，外层 `h5.executablePath` 会选择 macOS `open -a` 路线；即使用例通过，工具收尾仍可能失败且缺少 JSON。对于任务自有 Playwright 浏览器，将精确路径放入 `h5.options.executablePath`，保留外层 `executablePath: ''`，使 provider 实际 launch/close；本次该路线才达到完整本轮 JSON 验收。准备、缓存和浏览器所有权须独立核对，插件不会自动创建全局缓存别名。

命令 stdout/stderr 在 process 字节裁剪、命令摘要与持久诊断之前，对已引用秘密的原文及最多两层标准 JSON 字符串转义表示按最长匹配脱敏；元数据字典键和值同样处理。报告脱敏覆盖已解析 JSON 的完整字符串与标准 JSON 字符串转义表示（含 failureMessage 中最多两层常见序列化），再完整重序列化；重序列化后的字节预算仍在暂存前校验。它不承诺识别任意自定义编码、加密、Base64 或超过该层数的文本包装。未配置秘密引用时保留原报告字节。

构建前将目标平台选中的源 pages/subpackages 拓扑与 pages.json 原始 SHA256 写入不可变 build record；微信 app.json 的主页面列表（含默认首页）与每包页面列表必须保持源顺序；包按 root 映射比较，不要求包声明之间的顺序，并逐页验证产物。后验检查拒绝源计划变化。条件编译仅支持整行 `// #ifdef`、`// #ifndef`、`// #endif`、已知平台符号和 `||`，可嵌套；未知符号或其他表达式/directive 返回准备要求；重复键、无有效页面等选择后无效 JSON/拓扑会失败。inspect 仍只读原始 JSONC 元数据，不执行源代码。

普通快速测试通过 `TW_UNIAPP_TEST_NODE=/absolute/node22` 显式选择 Node 22；未设置时检查 PATH 与本机 nvm Node 22 候选的实际版本。无兼容工具会失败并给出准备要求，不跳过测试或自动安装。

同一 worker 可跨步骤保留 project role。每个公共动作（包括 inspect READ）先将该资源 owner 迁移到当前 attempt，再取得诊断 journal；旧 attempt 只有在最后 owner 离开后释放，peer role 的已接受证据保持。项目关闭幂等并清理最后 owner 的历史 journal；构建/测试不可变历史仍按原有64条上限保留到资源关闭。owner 迁移不清除原生 UNKNOWN 租约，不改跨 worker quarantine 或产物身份验证。

`check_artifact` 的成功结果新增兼容字段 `output_path`（本轮检查的 canonical 产物目录）；既有输入和字段保持不变。微信预览组合以该路径及完整 `artifacts` 清单绑定发布目录与构建字节，见 [组合示例](../../examples/devops/miniprogram_preview.py)。
