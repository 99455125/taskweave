# presentation

普通Python交互状态和流程：编辑/导航、规划/候选、AI、采集/录制、调试/补参、运行创建/查询、筛选、环境与设置。通过窄应用接口协作；禁止导入desktop、GUI框架或具体基础设施，状态中不放控件/客户端/渲染回调。

NiceGUI实际复用这些对象，替换UI时仍需新的渲染、事件及平台适配。见[桌面模块](../../../docs/modules/desktop.md)、[架构](../../../docs/architecture.md)和[测试指南](../../../docs/testing.md)。
