# 免安装运行与交付

目标虚拟机不允许安装程序，也不能联网下载依赖。交付为完整便携 zip，解压后双击 TaskWeave.exe，随包提供 Python 依赖、Playwright、Chromium 及可便携的 UI 运行组件。

不调用安装器、不提权、不注册服务、不安装系统运行库。UI 独立窗口方案必须通过目标 Windows 版本及权限环境的免安装原型，不能预先保证任意机器均可运行。具体要求见 [便携交付方案](requirements/REQ-007-v1-release/windows-package.md)。

当前仅有设计与脚手架，未生成 Windows 便携包。
