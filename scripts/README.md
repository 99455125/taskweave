# 工程工具

| 工具 | 用途 |
| --- | --- |
| check_project.py | 检查当前知识入口、源码语法、依赖边界、对话框策略、Markdown链接及CLI版本 |
| test_modules.py | 按module-map选择目标；--changed与--dry-run预览实际消费者，默认排除浏览器 |
| build_macos.py / verify_macos_bundle.py | macOS arm64构建与独立包检查 |
| build_windows.ps1 | Windows x64便携分发构建 |

运行方式见[测试指南](../docs/testing.md)与[打包指南](../docs/deployment.md)。工程检查不等于功能/发布验收；脚本不会替代用户对真实数据和外部系统操作的授权。
