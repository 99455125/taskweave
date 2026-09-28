# V2 原型对照归档

2026-09-27 按用户要求集中保存全部11张既有V2截图，供后续与产品版本比较。这里只保存设计参考，不表示当前实现或全部细节已验收。用户后续明确修改优先于旧图。

原 v2-repair-dialog.png 截于弹窗过渡状态，保留以追溯，不作为有效弹窗设计证据。另附重新截取的清晰版本。

- [v2-context-dialog](v2-context-dialog.png)
- [v2-editor](v2-editor.png)
- [v2-env](v2-env.png)
- [v2-home](v2-home.png)
- [v2-market](v2-market.png)
- [v2-planning](v2-planning.png)
- [v2-plugins](v2-plugins.png)
- [v2-repair-dialog](v2-repair-dialog.png)
- [v2-runs](v2-runs.png)
- [v2-settings](v2-settings.png)
- [v2-tasks](v2-tasks.png)

- [AI 修复弹窗清晰重截图](v2-repair-dialog-clear.png)：从既有交互原型重新打开截取，未重新设计。

当前主树实现对照（源码核对，非运行截图）：标题为“选择 AI 修复方式”，反馈含运行/尝试ID时展示修复依据；包含历史轮数、精简重复静态字段、本轮补充说明；底部为 API 修复、Chat 网页修复和取消。原型改用统一调用名称、顶部关闭及提示分区；没有展示当前实现中的运行/尝试ID，这不是删除功能的决定。
