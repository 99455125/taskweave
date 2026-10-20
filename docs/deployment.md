# 运行与打包

## 从源码启动

先按[开发指南](development.md)准备需要的extras。主命令的全局--home放在子命令之前：

```bash
uv run taskweave --home /path/to/workspace workbench
uv run taskweave --home /path/to/workspace workbench --browser
uv run taskweave --home /path/to/workspace workbench --port 8090
uv run taskweave --home /path/to/temporary-workspace demo
```

workbench默认原生窗口，--browser用于浏览器开发检查；demo在指定空间建立五步演示，不应指向要保持只读的用户空间。具体入口见[__main__.py](../src/taskweave/__main__.py)。

## 工作空间与资源

显式--home优先，其后TASKWEAVE_HOME，最后平台默认位置（存在有效位置标记时使用标记）：

| 平台 | 默认目录 |
| --- | --- |
| Windows | `%LOCALAPPDATA%/TaskWeave` |
| macOS | `~/Library/Application Support/TaskWeave` |
| Linux | `$XDG_DATA_HOME/taskweave`，未设置时`~/.local/share/taskweave` |

程序、包内浏览器/模型与用户工作空间分开。数据布局见[存储](modules/storage.md)，迁移使用正式设置用例，备份数据库时考虑活动连接和SQLite附属文件，不在运行期间用目录覆盖代替迁移。

源码浏览器能力需要匹配Chromium；原生窗口还依赖目标系统的WebView运行条件。插件被发现/启用不表示外部Node、HBuilderX、微信工具、SSH或数据库目标已经准备。

## 本地API及插件管理

```bash
uv run taskweave --home /path/to/workspace serve --port 8765
uv run taskweave request /path/to/request.json
uv run taskweave --home /path/to/workspace plugins list
uv run taskweave --home /path/to/workspace plugins enable utility
```

服务仅绑定回环地址，启动输出地址与令牌；request客户端从TASKWEAVE_API_TOKEN读取令牌，不把真实令牌写入文档或共享脚本。请求与大小限制见[操作契约](contracts/operations.md)。显式启用只适用于已安装插件，不下载/安装插件包。

## macOS arm64

[build_macos.py](../scripts/build_macos.py)要求macOS arm64和uv，在build/macos/venv建立独立Python3.12构建环境，同步全部extras与build组；收集十一插件、Chromium及OCR资源，构建后完整复制浏览器树并执行本地ad-hoc签名。

```bash
uv run python scripts/build_macos.py
uv run python scripts/verify_macos_bundle.py --app dist/macos/TaskWeave.app
```

产物为dist/macos/TaskWeave.app、ZIP、SHA256及release.json。冻结入口先分流worker/日志子进程，再启动UI；bundle模块定位Resources及浏览器。构建脚本不等同于自动安装或Developer ID签名/公证，已有工作空间插件配置保持自身启用选择。

## Windows x64

[build_windows.ps1](../scripts/build_windows.ps1)及[spec](../packaging/windows/taskweave.spec)构建便携目录/ZIP，脚本当前选择gui、browser、ocr、database、utility、files，不应描述为与macOS全部十一插件相同的包。

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1 -WebView2Runtime C:\path\to\WebView2FixedRuntime
```

构建默认要求明确提供固定WebView2运行目录，也可使用-WebView2Cab提供官方x64 CAB；-SkipWebView2明确跳过收集。目标机的WebView、离线浏览器/OCR资源、worker和外部工具需分别验证。分发脚本和资源测试存在，不代表任意目标平台的发布包已通过实机验收。测试范围见[测试指南](testing.md)。
