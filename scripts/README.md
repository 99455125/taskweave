# 工程脚本

`uv run python scripts/check_project.py` 从任意工作目录检查新工程结构、语法、模块边界及 Markdown 链接，不启动旧应用。

`uv run python scripts/test_modules.py --list` 列出按业务职责映射的快速回归模块。使用 `--module ui.tasks` 运行指定模块，或使用 `--changed src/taskweave/desktop/pages/tasks.py --dry-run` 预览受影响模块、选择原因与显式 unittest targets。默认不选择浏览器流程；确认需要浏览器验收后添加 `--include-browser`。新增产品源码必须登记到 `tests/module-map.json`，否则选择器会报出未映射路径并退出。
