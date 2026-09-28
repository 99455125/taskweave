# 测试

测试文件按功能命名，修改后只运行受影响模块；真实浏览器集成测试单独放置，不与快速单元测试混跑。运行命令和模块索引见 [验证说明](../docs/testing.md)。历史 REQ 验收记录位于 `docs/requirements/`，不作为长期测试入口。

模块级选择由 `scripts/test_modules.py` 与 `tests/module-map.json` 提供：`uv run python scripts/test_modules.py --list` 查看映射；`uv run python scripts/test_modules.py --module ui.tasks` 运行快速 targets；`uv run python scripts/test_modules.py --changed src/taskweave/desktop/pages/tasks.py --dry-run` 只预览选择。浏览器 targets 必须显式添加 `--include-browser`。未映射的 `src/taskweave/` 或 `plugins/` 产品路径会报错，不能静默跳过测试。
