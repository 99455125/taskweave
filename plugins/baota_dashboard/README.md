# baota_dashboard

Optional fixed Chinese BaoTa Linux 11.7.0 API adapter. Protocol tests are not real panel acceptance.

安装：`uv sync --locked --extra baota_dashboard`。发行包 taskweave-baota-dashboard 0.1.0，API v1；httpx/cryptography 仅为此可选插件依赖，核心默认不引入 HTTP 客户端或面板 SDK。

配置合并 environment/task_parameters，任务参数优先：baota_url（显式 origin，不含用户名、密码、查询或安全入口路径）、baota_api_secret_ref（逻辑秘密引用，宿主 secret_refs→env: 映射）、可选 baota_ca_file。TLS 默认校验 CA 和主机；显式 baota_allow_http=true 允许 HTTP。不得在生产网络使用明文传输秘密。baota_timeout_seconds 默认60（1–1800）；baota_max_response_bytes 默认16 MiB（1024 bytes–64 MiB）。动作 max_output_bytes 默认64 KiB（1 KiB–1 MiB）；分页与所有前后核对共用总响应预算和总动作超时。资源 baota_dashboard.connection 按 role 由宿主打开/关闭，同一资源的并行动作会报 BAOTA_CONNECTION_BUSY。

所有 API 动作为固定 action 查询参数 + POST form；request_token=md5(request_time+md5(api_secret))。拒绝所有重定向，不跨主机携认证；无写重试，无任意 endpoint、shell 兜底或跨插件 ctx.call。仅内部备份完整性读取使用官方仅支持 GET 的 `/download?filename=...`，经固定归属/大小核对后签名；不会把生成的临时 token URL 返回结果。响应拒绝未请求的压缩编码，逐字节执行总预算。HTTP 200、status=true 或任务终态都不能独立证实业务完成。

仅支持官方中文 LinuxPanel **11.7.0**（profile bt-linux-11.7.0），每次动作先查实际服务器版本。其他版本和 aaPanel 明确 BAOTA_DASHBOARD_CAPABILITY_UNSUPPORTED，不采用 `>=11.7` 匹配。证据为[官方发布包](https://download.bt.cn/install/update/LinuxPanel-11.7.0.zip)，SHA256 `1803d68b51d04fc5f4740b4715a800dc2bae5dd6755d94f41779fe5f0a6fc1da`；[官方 API 文档](https://docs.bt.cn/api)基于同版源码。下表源码路径相对官方包 panel/；端点的固定字段白名单及参数映射见 endpoints.py。

| 独立动作（均加 baota_dashboard.） | 固定 API | 主要契约/核对 | 源码 |
| --- | --- | --- | --- |
| check_connection | system/GetSystemTotal | version/system 对象，真实版本选择 | class/system.py:261 |
| system_status | system/GetSystemTotal + GetConcifInfo | 限制服务摘要，移除面板安全入口/mysql_root | class/system.py:28 |
| list_software | ajax/GetSoftList；可选 plugin/get_soft_list type=-1,p,row | 基础数组+可选插件分页，云目录失败显式失败 | class/ajax.py:223；class/panelPlugin.py:1930 |
| list_php_versions | site/GetPHPVersion all 可选 | 真实版本数组，00静态 | class/panelSite.py:4234 |
| list_sites | data/getData table=sites,type=-1,p,limit,search | data/page，显式分页/保守 truncated | class/data.py:414 |
| create_site | site/AddSite webname,path,type,version,port,type_id,ps,ftp,sql | 先查重/版本；真实root及全部既存祖先/leaf目录非链接核对，缺失tail只允许在可信目录下；siteStatus与所选 FTP/数据库子项；查站点实际路径 | class/panelSite.py:647 |
| configure_site | SetPath/SetSiteRunPath/SetIndex；data/setPs | 仅所选字段，Index逗号连接；逐步骤留痕 | class/panelSite.py:4112,4156,6140；class/data.py:55 |
| set_site_status | site/SiteStart或SiteStop id,name | ID/名称同一站点，后查 status | class/panelSite.py:3237,3350 |
| list_domains | data/getData table=domain,search=site_id | 核对pid，分页 | class/data.py:725 |
| add_domain | site/AddDomain id,webname,domain:port | 子项状态+域名端口后核对 | class/panelSite.py:1169 |
| remove_domain | site/DelDomain id,webname,domain,port | 不能删最后域名，后核对不存在 | class/panelSite.py:1535 |
| get_site_config | files/GetFileBody path | nginx/apache PHP站点派生路径，先核对存在/符号链接 | class/files.py:2322 |
| set_site_config | files/SaveFileBody path,data,encoding,st_mtime | 用户提供expected_mtime匹配当前；不用force/skip校验；后查内容 | class/files.py:2470 |
| get_rewrite | files/GetFileBody 派生rewrite/.htaccess | 缺失先报错，getter不会暗建文件 | class/files.py:2322 |
| set_rewrite | files/SaveFileBody 同上 | 已有文件、mtime、内部语法校验/重载，后查内容 | class/files.py:2470 |
| set_php_version | site/SetPHPVersion siteName,version；GetSitePHPVersion | 仅安装版本/00，后查phpversion | class/panelSite.py:4281,4329 |
| check_config | system/ServiceAdmin name=nginx或httpd,type=test | WRITE/nonretryable，可能修配置/启动服务 | class/system.py:1089 |
| reload_service | system/ServiceAdmin name=nginx或httpd,type=reload | WRITE，依赖内部预检，不宣传无中断 | class/system.py:1089 |
| list_databases | data/getData table=databases,p,limit,search | MySQL分页，深层删password | class/data.py:725 |
| create_database | database/AddDatabase sid=0,name,db_user,password,address,codeing,ps | 秘密引用；显式Host；后查用户/面板凭据/Host | class/database.py:683 |
| set_database_credentials | database/ResDatabasePassword id,name=username,data_name,password | 仅改密码，拒绝username重命名；后查面板记录 | class/database.py:1310 |
| set_database_access | GetDatabaseAccess/SetDatabaseAccess name,access | 替换账号Host授权，单项假成功必须后核对 | class/database.py:2249,2272 |
| delete_database | database/DeleteDatabase id,name | 后查消失；是否入回收站取面板策略 | class/database.py:990 |
| get_certificate | site/GetSSL siteName | false可为未启用；删真实私钥/CSR原文，摘要 | class/panelSite.py:2743 |
| deploy_certificate | site/SetSSL siteName,key,csr | key引用、匹配证书公钥/链/域名/有效期，后查部署内容 | class/panelSite.py:1670 |
| request_certificate | acme/apply_cert_api id,domains,auth_type,auth_to,auto_wildcard=0 | http/tls或手工dns；pending=accepted，证书=issued；不默认部署 | class/acme_v2.py:2090 |
| renew_certificate | acme/renew_cert index=GetSSL所查记录 | 无证书/跳过不得成功；签发与部署expiry核对分开 | class/acme_v2.py:2514 |
| set_https | SetSSLConf/CloseSSLConf；HttpToHttps/CloseToHttps | HTTPS/跳转分别执行/留痕，后GetSSL核对 | class/panelSite.py:2134,2443,2520,2593 |
| create_backup | site或database/ToBackup id | 同步；查唯一新增备份、实际文件/完整下载MD5/大小 | class/panelSite.py:5572；class/database.py:1381 |
| list_backups | data/getData backup type=0,search=site_id；database/GetBackup | pid/路径精确归属；DB getter不按id过滤 | class/data.py:769；class/database.py:2011 |
| restore_backup | files/UnZip sfile,dfile；database/InputSql name,file | 站点overlay有界tar.gz成员/链接/目标/逐文件MD5；DB要求expected_tables并GetInfo核对 | class/files.py:3198；class/database.py:1721,2760 |
| task_status | task/get_task_lists task_id,num=15,status可选 | status=1只表示worker结束，删shell/other，不伪造业务成功 | class/panelTask.py:60 |
| read_logs | site/GetSiteLogs或get_site_errlog siteName | missing/empty/unavailable/business error；有界文本/JSON转义；cursor仅本响应快照 | class/panelSite.py:6577,6613 |

真实 11.7.0 响应适配：GetFileBody 的规范非负十进制 st_mtime 字符串转换为公开整数（保留合法整数兼容，拒绝符号、前导零、空白、浮点/布尔及超出有符号 64 位值），expected_mtime 仍精确核对。AddDomain 的 domains-only 回复须恰有本次请求域名一项且 status 为 true，再核对实际域名/端口；空列表、混合/错误域名回复不算完成，已确认的部分写入保留诊断。部署证书按完整 PEM 证书链的顺序 DER 内容核对，允许官方 strip 和合法换行归一化，不接受夹杂正文、不同证书/链或实际私钥身份变化；输入的密钥/域名/有效期/链校验保持。

内部只读存在/链接核对：files/GetDirNew(path,p=1,showRow=100,search=准确basename)，响应path/dir/files及lnk；files/get_file_attribute(filename)，响应name/path/st_size/is_dir/is_link/md5；证据 class/files.py:798–936,4801–4852 和 BTPanel/__init__.py:1082–1106 路由。内部归属备份字节读取 `/download` 证据 BTPanel/__init__.py:1517–1569；common.py:295–346/get_input 接受查询签名。数据库恢复 GetInfo(db_name) 的准确表字段为 database/tables[].table_name，见 class/datatool.py:71–128，不使用猜测的data数组。Apache runPath 使用 GetSiteRunPath(id)，先核对站点根存在，避免 getter修建缺失目录（class/panelSite.py:6074–6138）。

持久化：成功返回只能显式纳入 ctx.output("baota_dashboard.json", name, result) + ctx.result(outputs=...) 才保存。当前 attempt 的所有已发送 WRITE（跨动作/role，含先前成功、partial和unknown）保留在插件内存 journal，后续 READ、被捕获的写失败、被动观察或步骤代码失败不会清除证据；失败时经既有 failure_results 钩子保存 baota_dashboard.operation_failure（JSON ≤64 KiB）。条目包含 action_id/role/sequence/endpoint、请求 completion、动作 action_state 及固定标量响应摘要；role仅保留短安全标识，其他值用SHA256标识，已解析秘密会先删去。响应字符串最多128字符；每次发送写请求前按固定7个标量摘要字段各128字符的 JSON 最坏转义字节，核算本 attempt 已保存条目及全部在途响应预留，并提前计入 completion/action_state/error_code/action_id 的最大增长。核算和占用之间没有 await，不同 role 共用同一容量账本。响应、业务/传输/形状错误或取消均由 finally 释放在途预留，已发送条目继续保留；容量不足报 BAOTA_DIAGNOSTIC_CAPACITY，并保留已有条目，不发送这次写入。最多32个活动attempt、128个资源所有者；资源转入新attempt或关闭时清理失去所有者的旧journal，并行attempt各自保留。没有实际发送的写请求不造unknown条目。宿主schema/preflight失败仍为NOT_STARTED；宿主对进入WRITE execute后的效果保守标UNKNOWN，即使业务路径检查在发出请求前拒绝，插件不改变core判定。失败hook不保存秘密参数或连接对象，不把诊断当成功输出，不跨attempt复用。强杀/丢失worker仍可能没有保存机会。

上下文 baota_dashboard.site 及工具 baota_dashboard.inspect_sites 只观察站点元数据/状态，不调用修复型配置测试或创建缺失文件的getter。普通列表getter可能写面板UI偏好/目录搜索历史，GetPHPVersion可能补空静态include；READ标签表示所承诺业务观察，不保证官方面板完全零元数据写入。配置正文/日志属于业务数据；删除已知凭据字段、解析的秘密值和PEM私钥，不保证发现未引用、变形或业务正文里所有未知秘密。

当前支持范围：PHP项目的nginx/apache；本地MySQL/MariaDB；无用户名重命名/任意驱动/云备份/未核对DNS提供商协议/整站全部配置快照/OpenLiteSpeed/任意shell。集成AddSite数据库名与账号必须相同且<=16字符（源码截断规则）；独立create_database允许合法小写名/账号，实际MySQL用户名限制仍以服务版本为准。备份恢复需要远程路径、文件和账号在核对到执行期间保持稳定，客户端检查不提供服务端原子隔离。站点恢复覆盖成员，不删除后来新增文件；DB表名核对不证明全部行数据等价。备份字节内部完整读取用于验证，未提供下载产物动作。列表通过page/limit显式续查；查询定位扫描上限20页×100行，超限先报错，不把不完整查重当不存在。

验收：`uv run --extra baota_dashboard python -m unittest tests.test_baota_dashboard tests.test_devops_discovery -v`，真实临时HTTP/TLS协议fixture执行33动作的业务/错型检查、协议smoke及有针对性的工作流断言；smoke循环不证明48适配端点的全部参数或所有真实响应形状。额外18个关键端点字段契约独立抄录官方源码，核对必需/可选字段及关键业务值；真实Application/worker验证跨动作写入证据落盘。fixture并非真实面板。实际面板安装/建站/配置/数据库/证书/备份验收结果保留在本次实施报告，未取得真实目标证明不能称整体验收完成。
