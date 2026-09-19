# REQ-006 代码映射（拟议）

- src/taskweave/application/sharing.py：导入导出用例。
- src/taskweave/infrastructure/bundles/：manifest 与资源校验。
- apps/workbench/：预览、冲突和本地映射页面。
- tests/sharing/：round-trip、冲突、缺依赖和路径测试。

以上位置尚未实现；代码落地后更新为实际文件与入口。

本需求先验证基础顺序任务分享；后续控制流和图形定义的格式兼容、版本升级与导入导出回归分别由 REQ-008/009 完成，不构成本需求的前置依赖。
