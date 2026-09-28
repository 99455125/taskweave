# 操作入口、本地配置与兼容边界

契约入口：[operations.py](../../src/taskweave/application/operations.py)、[service.py](../../src/taskweave/application/service.py)、[HTTP](../../src/taskweave/infrastructure/http.py)、[CLI](../../src/taskweave/__main__.py)、[桌面Controller](../../src/taskweave/desktop/controller.py)。精确参数、默认值和同步/异步分类维护在代码及路由测试，不复制另一份易过期API清单。

## CLI与HTTP

CLI全局--home指定工作空间；serve默认端口8765，workbench可--port或--browser。request接受JSON文件或标准输入，可--url指向默认http://127.0.0.1:8765/api；CLI业务错误非零退出。plugins list/enable/disable管理本地配置，启停仍需满足占用与依赖约束。旧示例demo依赖的插件不是默认启用能力，不作为安装验收捷径。

HTTP监听127.0.0.1，POST /api使用JSON操作请求（operation及params对象）。始终校验Bearer凭据，未配置token时生成随机启动token；存在Origin头或Content-Type不是application/json即拒绝。业务成功为200的ok/result，TaskError或非法请求为400错误结构，内部异常500；前置拒绝可用HTTP错误页，不保证所有拒绝都有同一JSON envelope。CLI回环请求使用TASKWEAVE_API_TOKEN，默认请求超时190秒。

请求体总上限8MiB；普通操作2MiB，较大请求仅开放给step.generate、step.generate_goal、step.diagnose、plan.generate、plan.generation.parse。AI自身容量限制另算，不能把HTTP允许通过视为模型请求一定可接受。

操作族按维护职责定位：task/step到任务与步骤用例，environment到环境，run/result到运行，context到采集，plan到规划，plugin到注册启停，AI到authoring。操作名、参数种类/默认值、只读锁豁免、异步分类及错误码是兼容面；未知操作保持OPERATION_UNKNOWN。新增语义用例后再登记路由，不从UI绕到仓储。

run.get保持历史request_json结构，不新暴露顶层inputs_json；request_json本身可能已有输入内容。DDD拆层不能以隐私理由静默删旧字段。需要改变公开响应时单独设计兼容策略。

## 工作空间与配置

| 位置 | 内容与边界 |
| --- | --- |
| taskweave.db、tasks/、plans/ | 业务持久化；见存储协议 |
| model.json | url、model、key_env、api_key；用户明确选择的本地密钥保存 |
| plugins.json | 启用插件集合，未配置默认空；安装与启用分开 |
| workbench.json | 默认environment_id、executor_max_threads、AI字节上限、显示/AI脱敏开关 |
| logs/server.log | 服务/AI日志及轮转；不属于单任务清理 |
| exports/ | 原生桌面导出JSON文件 |
| coordinator.lock | OS锁协调单一home；不是可共享活会话 |

Windows默认%LOCALAPPDATA%/TaskWeave，macOS默认~/Library/Application Support/TaskWeave，Linux默认${XDG_DATA_HOME:-~/.local/share}/taskweave；标准目录旁taskweave-location.json可记录迁移位置。home选择、系统默认目录及迁移位置标记由 [storage.py](../../src/taskweave/infrastructure/storage.py) 负责；TASKWEAVE_HOME及显式--home用于指定数据目录。不要把程序目录当可写数据库目录。Windows默认本地应用数据，平台具体路径按实现获取。

工作空间迁移要求结束实例、目标为空且不是源目录/其子目录；先复制（排除锁文件），写位置标记，重启到新目录后才处理源目录清理。无关home启动不能误删源目录。它不是任意目录合并或远程同步；配置/数据由用户明确迁移，禁止整理文档时碰真实home。

## 模型、隐私与资源设置

模型完整URL必须HTTPS，回环localhost/127.0.0.1/::1可HTTP，拒绝URL内用户名密码。TLS使用certifi并接受SSL_CERT_FILE/SSL_CERT_DIR额外CA，不能关闭校验。首次可用TASKWEAVE_MODEL_URL、TASKWEAVE_MODEL_NAME、TASKWEAVE_MODEL_API_KEY；本地配置优先按读取实现。留空API Key保留同URL旧密钥，换URL不沿用旧密钥，环境变量引用仍可用。

本地环境值不修改系统环境变量，env:名称为凭据引用的兼容入口；普通值允许入库，不能因此承诺所有导出/日志自动无秘密。隐私开关redact_on_display、redact_for_ai独立默认true，原采集内容不改写；图像不做像素脱敏。

executor_max_threads控制实例池1–8，默认8，不代表单run步骤并行；超限直接失败。AI上限默认2048KiB、最大4096KiB，保存已有值。默认环境保存ID，删除默认环境清除此设置，历史运行展示保留已删除环境名。

启动方式见 [交付](../deployment.md)，数据事务与恢复见 [持久化](persistence-results.md)，HTTP与桌面页面/Socket.IO使用各自入口的凭据校验，不能把本地监听写成公网部署授权。
