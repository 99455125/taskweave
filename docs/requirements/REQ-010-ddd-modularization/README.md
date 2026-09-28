# REQ-010 · DDD 模块化与行为保真

当前状态（2026-09-25）：A/B/C/D 四阶段均已通过指定 supervisor 独立审核，D-R1 已关闭；架构师完成兼容性、审核版差异及定向验证核对，签署 REQ-010 最终验收通过。证据与保留限制见 [最终验收记录](final-acceptance.md)。

目标：在现有功能、数据与操作兼容的前提下，按业务职责拆分仓储、应用用例和 UI，建立可单独运行的模块回归。不是新增控制流或重做界面。

- [设计与验收标准](design.md)
- [实施计划](plan.md)
- [代码映射](code-mapping.md)
- [进度](progress.md)
- [验证记录](validation.md)

基线是当前工作区（包含未提交的新功能），而非仅 Git HEAD。前置需求：REQ-002 已确认契约、REQ-003 核心、REQ-004 插件、REQ-005 工作台；任务包遵循当前 taskweave-task-2。

模块回归入口：`uv run python scripts/test_modules.py --list`；按功能执行 `--module ui.tasks`；按源码预览闭包 `--changed <路径> --dry-run`。浏览器流程默认不选，须显式添加 `--include-browser`。映射与已知基线测试归属见 `tests/module-map.json` 和 [验证记录](validation.md)。
