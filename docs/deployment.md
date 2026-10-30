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

程序、包内浏览器/模型与用户工作空间分开。数据布局见[存储](modules/storage.md)，工作空间位置迁移使用正式设置用例；数据库结构维护使用下面的独立脚本。备份数据库时考虑活动连接和SQLite附属文件，不在运行期间用目录覆盖代替迁移。

源码浏览器能力需要匹配Chromium；原生窗口还依赖目标系统的WebView运行条件。插件被发现/启用不表示外部Node、HBuilderX、微信工具、SSH或数据库目标已经准备。

## 数据库结构维护

控制库和任务库各使用单一现行DDL，启动时不自动升级历史库。停止使用该工作空间的程序后，使用[维护脚本](../scripts/maintain_current_schema.py)为每个待维护数据库指定新目标文件；目标父目录须已存在，目标文件须不存在：

```bash
uv run python scripts/maintain_current_schema.py /path/to/source/taskweave.db /path/to/review/taskweave.db --kind control
uv run python scripts/maintain_current_schema.py /path/to/source/data.db /path/to/review/data.db --kind task-data
```

源数据库通过只读连接取得一致快照，转换和校验在独立目标中完成。脚本处理已知历史流程、冻结定义与插件表登记，保留业务数据；未知结构或不满足离线维护条件的运行状态会拒绝处理。结构、外键和完整性检查通过后才发布目标，已存在的文件不覆盖。转换后的任务流程可能需要重新确认。

该命令只生成指定数据库，不替换源文件、不切换工作空间，也不复制任务文件、规划材料和配置。审核维护结果后，再按明确的目标与范围安排替换或工作空间切换；详细边界见[存储模块](modules/storage.md)。

## 本地API及插件管理

```bash
uv run taskweave --home /path/to/workspace serve --port 8765
uv run taskweave request /path/to/request.json
uv run taskweave --home /path/to/workspace plugins list
uv run taskweave --home /path/to/workspace plugins enable utility
```

服务仅绑定回环地址，启动输出地址与令牌；request客户端从TASKWEAVE_API_TOKEN读取令牌，不把真实令牌写入文档或共享脚本。请求与大小限制见[操作契约](contracts/operations.md)。显式启用只适用于已安装插件，不下载/安装插件包。

## 工作空间整体数据维护

[scripts/maintain_workspace.py](../scripts/maintain_workspace.py) 一次准备控制库及全部任务库，持有工作空间独占锁；默认仅备份和验证候选，显式 `--apply` 才写回原数据库路径。配置、素材和旧备份不移动。全部候选通过结构、外键、完整性及记录数量校验后应用，失败逐库恢复；备份与报告保留在工作空间 backups 下的新目录。

```bash
uv run python scripts/maintain_workspace.py /absolute/workspace
uv run python scripts/maintain_workspace.py /absolute/workspace --apply
```

维护旧流程和历史游标时只转换已知结构；活跃运行、未知结构或不安全恢复状态明确拒绝，保留源库。此工具属于显式数据维护，正常启动不包含历史升级链。

转换流程后仅对能够证明定义等价的运行与组合任务更新校验 hash，原本已过期的运行继续保持过期。若之前已转换结构，需要以转换前控制库备份作为证据补正 hash，可增加 `--definition-evidence /absolute/backup/taskweave.db`；工具另行备份证据，逐项记录旧新 hash，并拒绝矛盾的冻结快照。该参数不会恢复旧业务配置或覆盖维护后的业务修改。

## macOS arm64

[build_macos.py](../scripts/build_macos.py)要求macOS arm64和uv，在build/macos/venv建立独立Python3.12构建环境，同步全部extras与build组；收集十五插件、Chromium及OCR资源，构建后完整复制浏览器树并执行本地ad-hoc签名。

```bash
uv run python scripts/build_macos.py
uv run python scripts/verify_macos_bundle.py --app dist/macos/TaskWeave.app
```

产物为dist/macos/TaskWeave.app、ZIP、SHA256及release.json。冻结入口先分流worker/日志子进程，再启动UI；bundle模块定位Resources及浏览器。构建脚本不等同于自动安装或Developer ID签名/公证，已有工作空间插件配置保持自身启用选择。

## Windows x64

[build_windows.ps1](../scripts/build_windows.ps1)及[spec](../packaging/windows/taskweave.spec)构建便携目录/ZIP，脚本当前选择gui、browser、ocr、database、utility、nacos、files、pdf、dataset、excel，不应描述为与macOS全部十五插件相同的包。

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1 -WebView2Runtime C:\path\to\WebView2FixedRuntime
```

构建默认要求明确提供固定WebView2运行目录，也可使用-WebView2Cab提供官方x64 CAB；-SkipWebView2明确跳过收集。目标机的WebView、离线浏览器/OCR资源、worker和外部工具需分别验证。分发脚本和资源测试存在，不代表任意目标平台的发布包已通过实机验收。测试范围见[测试指南](testing.md)。

PDF 插件通过 pypdfium2 / PDFium 与随包中文字体生成文本 PDF；两平台 spec 收集 PDFium 原生库、字体与字符度量、许可和插件 metadata。字体约 9.9 MiB（未压缩），实际分发增量须以目标平台构建为准；Windows EXE 仍需 Windows 构建机实测。配置与范围见 [PDF 插件](../plugins/pdf/README.md)。

内部数据集与 Excel 通过 dataset/excel extras 安装；已有工作空间先启用 dataset 再启用 excel，并配置 excel_root。两平台 spec 收集两插件、openpyxl、et_xmlfile、defusedxml 与 metadata。使用范围见[数据集](../plugins/dataset/README.md)与[Excel](../plugins/excel/README.md)。
